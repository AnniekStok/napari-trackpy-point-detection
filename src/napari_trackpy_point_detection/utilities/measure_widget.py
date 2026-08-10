import napari
import numpy as np
from napari.utils.notifications import show_info
from qtpy.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .interactive_table_widget import InteractiveTableWidget
from .layer_dropdown import LayerDropdown


class MeasureWidget(QWidget):
    """Controls to measure image intensities at the detected points, optionally per
    region. The results are added as extra columns to the interactive table."""

    def __init__(
        self, viewer: napari.Viewer, table_widget: InteractiveTableWidget
    ):
        super().__init__()

        self.viewer = viewer
        self.table_widget = table_widget
        self.intensity_layer = None
        self.regions = None

        self.intensity_layer_dropdown = LayerDropdown(
            self.viewer, (napari.layers.Image)
        )
        self.intensity_layer_dropdown.layer_changed.connect(
            self._update_intensity_layer
        )
        self.intensity_layer_dropdown.setMaximumWidth(200)

        self.use_regions_checkbox = QCheckBox("Measure in regions?")
        self.use_regions_checkbox.setChecked(False)
        self.use_regions_checkbox.clicked.connect(self._check_activation)
        self.hide_points_checkbox = QCheckBox("Hide points\noutside regions?")
        self.hide_points_checkbox.setChecked(False)
        self.hide_points_checkbox.setEnabled(False)
        self.hide_points_checkbox.clicked.connect(self._update_visibility)

        checkbox_layout = QHBoxLayout()
        checkbox_layout.addWidget(self.use_regions_checkbox)
        checkbox_layout.addWidget(self.hide_points_checkbox)

        self.regions_label = QLabel("Regions layer")
        self.regions_dropdown = LayerDropdown(
            self.viewer, (napari.layers.Shapes, napari.layers.Labels)
        )
        self.regions_dropdown.layer_changed.connect(self._update_regions_layer)

        regions_layout = QHBoxLayout()
        regions_layout.addWidget(self.regions_label)
        regions_layout.addWidget(self.regions_dropdown)

        intensity_layout = QHBoxLayout()
        intensity_layout.addWidget(QLabel("Intensity layer"))
        intensity_layout.addWidget(self.intensity_layer_dropdown)

        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setEnabled(False)
        self.measure_btn.clicked.connect(self._measure)

        box_layout = QVBoxLayout()
        box_layout.addLayout(intensity_layout)
        box_layout.addLayout(checkbox_layout)
        box_layout.addLayout(regions_layout)
        box_layout.addWidget(self.measure_btn)

        box = QGroupBox("Measure intensities")
        box.setLayout(box_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)
        self.setLayout(layout)

        self._check_activation()

    @property
    def points(self) -> "napari.layers.Points | None":
        """The points layer shown in the table, which is what is measured."""

        return self.table_widget._layer

    def refresh(
        self, intensity_layer: "napari.layers.Image | None" = None
    ) -> None:
        """Pick up the points layer that the table is currently showing, optionally
        preselecting ``intensity_layer`` (e.g. the layer the points were detected on)."""

        if (
            intensity_layer is not None
            and intensity_layer.name in self.viewer.layers
        ):
            self.intensity_layer_dropdown.setCurrentText(intensity_layer.name)

        # A dropdown only emits when its text actually changes, so read back what they
        # are showing now: the layers may already have been selected before this widget
        # was created.
        self._update_intensity_layer(
            self.intensity_layer_dropdown.currentText()
        )
        self._update_regions_layer(self.regions_dropdown.currentText())

    def _check_activation(self) -> None:
        """Check whether the measure button should be active or not"""

        use_regions = self.use_regions_checkbox.isChecked()

        self.measure_btn.setEnabled(
            self.intensity_layer is not None
            and self.points is not None
            and not (self.regions is None and use_regions)
        )

        self.hide_points_checkbox.setEnabled(use_regions)
        self.regions_label.setEnabled(use_regions)
        self.regions_dropdown.setEnabled(use_regions)

    def _update_intensity_layer(self, selected_layer: str) -> None:
        """Update the intensity layer via the dropdown"""

        if selected_layer in self.viewer.layers:
            self.intensity_layer = self.viewer.layers[selected_layer]
            self.intensity_layer_dropdown.setCurrentText(selected_layer)
        else:
            self.intensity_layer = None

        self._check_activation()

    def _update_regions_layer(self, selected_layer: str) -> None:
        """Update the regions layer via the dropdown"""

        if selected_layer in self.viewer.layers:
            self.regions = self.viewer.layers[selected_layer]
            self.regions_dropdown.setCurrentText(selected_layer)
        else:
            self.regions = None

        self._check_activation()

    def _fits_points(self, layer: napari.layers.Layer) -> bool:
        """Check that ``layer`` can be indexed with the point coordinates."""

        if layer.ndim > self.points.ndim:
            show_info(
                f"Cannot measure in '{layer.name}': it has more dimensions "
                f"({layer.ndim}) than the points ({self.points.ndim})."
            )
            return False

        return True

    def _sample(self, layer: napari.layers.Layer) -> np.ndarray:
        """Read one value from ``layer`` for each point.

        The points and the measured layer can carry a different scale and translate, so
        the points are taken to world coordinates first. Rotation, shear and affine
        transforms are not taken into account.
        """

        points = np.asarray(self.points.data)
        world = points * np.asarray(self.points.scale) + np.asarray(
            self.points.translate
        )

        # Layer dimensions are right-aligned with the world dimensions, so a layer with
        # fewer dimensions than the points (e.g. a 3D regions layer for 4D points) is
        # indexed with the trailing coordinates.
        world = world[:, -layer.ndim :]
        coordinates = (world - np.asarray(layer.translate)) / np.asarray(
            layer.scale
        )
        coordinates = np.round(coordinates).astype(int)

        # Points can sit just outside the array (e.g. after moving one to the very
        # edge), which would raise on indexing.
        data = layer.data
        index = tuple(np.clip(coordinates, 0, np.asarray(data.shape) - 1).T)

        # Dask has no pointwise fancy indexing over multiple axes, but offers ``vindex``.
        values = data.vindex[index] if hasattr(data, "vindex") else data[index]

        return np.asarray(values)

    def _measure(self) -> None:
        """Measure the intensity at each point, optionally together with the region it
        falls in, and add the results to the table."""

        if self.points is None or self.intensity_layer is None:
            return

        if not self._fits_points(self.intensity_layer):
            return

        measurements = {"intensity": self._sample(self.intensity_layer)}
        colormap = None
        drop = ("region",)  # a region measured earlier no longer applies

        if self.use_regions_checkbox.isChecked() and self.regions is not None:
            regions = self._regions_as_labels()
            if not self._fits_points(regions):
                return
            measurements["region"] = self._sample(regions)
            # give each table row the color of the region it falls in
            colormap = regions.colormap
            drop = ()

        self.table_widget.add_measurements(
            measurements, region_colormap=colormap, drop=drop
        )
        self._update_visibility()

    def _regions_as_labels(self) -> "napari.layers.Labels":
        """Return the regions as a Labels layer, rasterizing a Shapes layer if needed.

        The rasterized version is added to the viewer and replaces the shapes layer as
        the selected regions layer, so it is reused for the next measurement.
        """

        if isinstance(self.regions, napari.layers.Shapes):
            shapes = self.regions
            shapes.visible = False
            labels = self.viewer.add_labels(
                shapes.to_labels(self.intensity_layer.data.shape),
                name=f"{shapes.name} (labels)",
                scale=self.intensity_layer.scale,
                translate=self.intensity_layer.translate,
            )
            self.regions = labels
            self.regions_dropdown.setCurrentText(labels.name)

        return self.regions

    def _update_visibility(self) -> None:
        """Show or hide the points that fall outside any region"""

        if self.points is None:
            return

        regions = self.table_widget.measurement_column("region")

        if (
            self.use_regions_checkbox.isChecked()
            and self.hide_points_checkbox.isChecked()
            and regions is not None
        ):
            self.points.shown = regions > 0
        else:
            self.points.shown = True
