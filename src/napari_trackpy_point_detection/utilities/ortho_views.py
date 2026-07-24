import inspect

import napari_orthogonal_views.ortho_view_widget as ov_widget
import numpy as np
from matplotlib.colors import to_rgba
from napari import Viewer
from napari.layers import Labels, Layer, Points, Shapes
from napari.utils.notifications import show_info
from napari_orthogonal_views.ortho_view_manager import (  # noqa
    OrthoViewManager,
    _get_manager,
)

# border colour drawn around selected points, used instead of napari's built-in selection
# highlight (which does not render on the main canvas while ortho views are active)
_SELECTION_BORDER_COLOR = np.array([0.0, 1.0, 1.0, 1.0])  # cyan

def get_property_names_from_class(layer_cls):
    """Return all property names for a Layer class."""
    res = []
    for name, obj in inspect.getmembers(layer_cls):
        # must be a property with a setter
        if isinstance(obj, property) and obj.fset is not None:
            # skip special or non-sync properties
            if name in ("thumbnail", "name"):
                continue
            res.append(name)
    return res

sync_filters = {
    Points: {
        # ``data`` MUST stay excluded here. It is synced exclusively by the coordinator in
        # point_data_hook. If ``_sync_property`` also syncs it, a forward data event writes
        # ``copied.data = orig.data``, which makes the copy emit a ``data`` event covering
        # *every* index; that re-enters the coordinator and reaches the table as a
        # "changed over all points", corrupting the table and ballooning the selection.
        "forward_exclude": {
            "data",
            "size",
            "current_size",
        },  # data / size / border are synced separately in point_data_hook
        # ``current_size`` is intentionally NOT kept here: napari refreshes it on every
        # selection change, so reverse-syncing it makes a selection bounce between layers
        # and, via its setter's ``refresh(highlight=False)``, wipes the selection
        # highlight. The actual point ``size`` array still syncs.
        "reverse_exclude": set(get_property_names_from_class(Points))
        - {"mode", "size", "visible", "selected_data"},
    }
}

# actions on the Points ``data`` event that represent an actual edit to the points
_POINT_DATA_ACTIONS = ("added", "changed", "removed")


def _apply_selection(layer: Points, selection: set) -> None:
    """Set ``selected_data`` on a layer without letting the resulting ``current_size``
    update cascade through the property sync.

    Setting ``selected_data`` makes napari refresh ``current_size`` from the selected
    points (``Points.current_size`` setter). ``current_size`` is reverse-synced between the
    layers, so unblocked it bounces around (orig -> copy -> orig -> ...) and, because that
    setter runs ``refresh(highlight=False)``, it wipes the selection highlight on the main
    layer. Blocking only ``current_size`` stops the bounce while leaving the ``highlight``
    event free, so every view still draws the selection ring.
    """

    with layer.events.current_size.blocker():
        layer.selected_data = set(selection)


def _mirror_points(orig_layer: Points, copied_layer: Points) -> None:
    """Copy point data + visualization (size, shown) from ``orig_layer`` onto a single
    ortho-view copy.

    This is only ever called while the shared sync guard is held, so the copy's own
    ``data`` event (and the size/shown property sync) cannot bounce the change back to the
    main layer.
    """

    copied_layer.data = orig_layer.data
    with copied_layer.events.blocker_all():
        copied_layer.size = orig_layer.size
        copied_layer.shown = orig_layer.shown
    copied_layer.refresh()


def point_data_hook(orig_layer: Points, copied_layer: Points) -> None:
    """Hook that syncs point data and visualization between the main Points layer and its
    ortho-view copies.

    ``data`` is excluded from the automatic property sync (see ``sync_filters``) and
    handled here instead, because it needs careful ordering and recursion control:

      forward  (orig_layer -> every copy): a point added/removed/moved on the main layer
               is mirrored onto all ortho-view copies.
      reverse  (a copy -> orig_layer): a point added/removed/moved inside an ortho view is
               pushed onto the main layer, which then re-emits its ``data`` event so
               downstream consumers (e.g. the interactive table's
               ``_sync_table_with_layer``) process it, and is then mirrored onto the other
               copies.

    All copies of a given main layer share a single coordinator (stored on the main layer)
    with one re-entrancy guard. This is what prevents the feedback storm you get if each
    copy syncs independently in both directions: once a sync is in progress, every other
    data handler bails out, and the coordinator itself fans the change out to the layers
    that still need it.

    Args:
        orig_layer (Points): the main layer from which the copy is derived.
        copied_layer (Points): Points equivalent shown in an orthogonal view.
    """

    # Shared coordinator state, created once per main layer and reused by every copy.
    state = getattr(orig_layer, "_ortho_point_sync", None)
    if state is None:
        state = {
            "copies": [],
            "syncing": False,
            "sel_syncing": False,
        }

        def forward_selection(event=None) -> None:
            """orig_layer selection -> every copy (drives the border highlight)."""

            if state["sel_syncing"]:
                return
            state["sel_syncing"] = True
            try:
                selection = set(orig_layer.selected_data)
                for copy in state["copies"]:
                    _apply_selection(copy, selection)
            finally:
                state["sel_syncing"] = False

        state["forward_selection"] = forward_selection  # keep a strong reference
        # ``selected_data`` is not a layer property event (it lives on the psygnal
        # Selection), so ``_sync_property`` cannot sync it - we wire it up explicitly.
        orig_layer.selected_data.events.items_changed.connect(forward_selection)

        def forward_data(event) -> None:
            """orig_layer -> every registered copy (main layer was edited directly).

            Must run *before* any other ``data`` listener (e.g. the interactive table),
            because the table sets ``orig_layer.selected_data`` to a freshly added index,
            which is forward-synced onto every copy - and that indexing fails if a copy has
            not grown yet. See the ``position="first"`` connection below.
            """

            if getattr(event, "action", None) not in _POINT_DATA_ACTIONS:
                return
            if state["syncing"]:
                return

            state["syncing"] = True
            try:
                for copy in state["copies"]:
                    _mirror_points(orig_layer, copy)
            finally:
                state["syncing"] = False

        state["forward_data"] = forward_data  # keep a strong reference
        orig_layer._ortho_point_sync = state
        # position="first": the copies are resized before the table (or any other
        # ``data`` consumer) reacts, so downstream selection/color updates never index a
        # copy that has not grown yet.
        orig_layer.events.data.connect(forward_data, position="first")

    if copied_layer not in state["copies"]:
        state["copies"].append(copied_layer)

    def sync_visualization(event=None) -> None:
        """Sync the visible points and their size (not synced automatically). Bound to the
        border_color event, which is emitted when shown points / point size change."""

        with copied_layer.events.blocker_all():
            copied_layer.size = orig_layer.size
            copied_layer.shown = orig_layer.shown
        copied_layer.refresh()

    orig_layer.events.border_color.connect(sync_visualization)

    def reverse_data(event) -> None:
        """this copy -> orig_layer (+ the other copies) — a point was edited in this
        ortho view."""

        action = getattr(event, "action", None)
        if action not in _POINT_DATA_ACTIONS:
            return
        if state["syncing"]:
            return

        state["syncing"] = True
        try:
            # Update the main layer's data silently (its ``data`` event is re-emitted
            # below). We cannot simply rely on assigning ``orig_layer.data`` to notify
            # listeners: napari's data setter only reports ``added``/``removed`` when the
            # layer was empty, so an ortho-view add would otherwise reach the table as a
            # ``changed`` over every index.
            with orig_layer.events.data.blocker():
                orig_layer.data = copied_layer.data

            # Resize the *other* ortho views before anything downstream reacts. This must
            # happen before re-emitting the data event, because a consumer (e.g. the
            # table) may set ``orig_layer.selected_data`` to a freshly added index, which
            # is forward-synced onto every copy - and that indexing fails if a copy has
            # not grown yet.
            for copy in state["copies"]:
                if copy is not copied_layer:
                    _mirror_points(orig_layer, copy)

            # Re-emit the main layer's ``data`` event with the *source* action/indices so
            # ``_sync_table_with_layer`` (and any other listener) processes the real edit.
            # The forward handler is suppressed by the guard, so copies are not synced
            # twice.
            orig_layer.events.data(
                value=orig_layer.data,
                action=action,
                data_indices=getattr(event, "data_indices", ()),
                vertex_indices=getattr(event, "vertex_indices", ((),)),
            )

            with orig_layer.events.blocker_all():  # try to suppress updating visibility
                orig_layer.selected_data = (
                    copied_layer.selected_data
                )  # make sure the same data is selected

        finally:
            state["syncing"] = False

    def reverse_selection(event=None) -> None:
        """this copy's selection -> orig_layer (+ the other copies)."""


        if state["sel_syncing"]:
            return
        state["sel_syncing"] = True
        try:
            selection = set(copied_layer.selected_data)
            _apply_selection(orig_layer, selection)
            for copy in state["copies"]:
                if copy is not copied_layer:
                    _apply_selection(copy, selection)
        finally:
            state["sel_syncing"] = False

    # Keep strong references so the closures are not garbage collected while connected.
    copied_layer._ortho_point_sync_reverse = reverse_data
    copied_layer._ortho_point_sync_reverse_selection = reverse_selection
    copied_layer.events.data.connect(reverse_data)
    copied_layer.selected_data.events.items_changed.connect(reverse_selection)

def initialize_ortho_views(viewer: Viewer) -> OrthoViewManager:
    """Initialize orthoviews on the current napari Viewer and register hooks and filters.

    Args:
        viewer (napari.Viewer): viewer to set the orthogonal views for.

    Returns:
        OrthoViewManager: reference to the OrthoViewManager instance
    """

    orth_view_manager = _get_manager(viewer)
    orth_view_manager.register_layer_hook((Points), point_data_hook)
    orth_view_manager.set_sync_filters(sync_filters)
    orth_view_manager.activate_checkboxes = True

    return orth_view_manager
