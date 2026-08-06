import inspect

from napari import Viewer
from napari.layers import Points
from napari_orthogonal_views.ortho_view_manager import (  # noqa
    OrthoViewManager,
    _get_manager,
)


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
        # ``data`` must be excluded here and should be synced exclusively by the
        # coordinator in point_data_hook. If ``_sync_property`` also syncs it, too many
        # 'data' events get emitted that corrupt the table.
        "forward_exclude": {
            "data",
            "size",
            "current_size",
        },  # data / size / border are synced separately in point_data_hook
        "reverse_exclude": {
            "data",
            "size",
            "current_size",}
    }
}

# actions on the Points ``data`` event that represent an actual edit to the points
_POINT_DATA_ACTIONS = ("added", "changed", "removed")

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
        orig_layer.events.data.connect(forward_data, position="first")

    if copied_layer not in state["copies"]:
        state["copies"].append(copied_layer)

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
            with orig_layer.events.data.blocker():
                orig_layer.data = copied_layer.data

            # Resize the other ortho views before anything downstream reacts, before
            # re-imitting the data event, so that other reacting components get the
            # updated array on time.
            for copy in state["copies"]:
                if copy is not copied_layer:
                    _mirror_points(orig_layer, copy)

            # Re-emit the main layer's ``data`` event with the *source* action/indices so
            # ``_sync_table_with_layer`` processes the real edit.
            orig_layer.events.data(
                value=orig_layer.data,
                action=action,
                data_indices=getattr(event, "data_indices", ()),
                vertex_indices=getattr(event, "vertex_indices", ((),)),
            )

        finally:
            state["syncing"] = False

    # Keep strong references so the closures are not garbage collected while connected.
    copied_layer._ortho_point_sync_reverse = reverse_data
    copied_layer.events.data.connect(reverse_data)

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
