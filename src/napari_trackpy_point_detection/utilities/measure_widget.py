import napari
import numpy as np
import pandas as pd
from napari.utils.events import Selection
from qtpy.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .layer_dropdown import LayerDropdown
from .table_widget import TableWidget


class MeasureWidget(QWidget):
    """Measurements widget for point detections"""

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        self.viewer = viewer
        self.points = None
        self.intensity_layer = None
        self.regions = None
        self.table_widget = TableWidget(data={})
        self.table_widget.rowClicked.connect(self._select_point)
        self.dimensions = []

        self.intensity_layer_dropdown = LayerDropdown(
            self.viewer, (napari.layers.Image)
        )
        self.intensity_layer_dropdown.layer_changed.connect(
            self._update_intensity_layer
        )

        checkbox_layout = QHBoxLayout()
        self.use_regions_checkbox = QCheckBox("Measure in regions?")
        self.use_regions_checkbox.setChecked(False)
        self.use_regions_checkbox.clicked.connect(self._check_activation)
        self.hide_points_checkbox = QCheckBox("Hide points outside regions?")
        self.hide_points_checkbox.setChecked(False)
        self.hide_points_checkbox.setEnabled(False)
        self.hide_points_checkbox.clicked.connect(self._update_visibility)
        checkbox_layout.addWidget(self.use_regions_checkbox)
        checkbox_layout.addWidget(self.hide_points_checkbox)

        self.regions_dropdown = LayerDropdown(
            self.viewer, (napari.layers.Shapes, napari.layers.Labels)
        )
        self.regions_dropdown.layer_changed.connect(self._update_regions_layer)

        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setEnabled(False)
        self.measure_btn.clicked.connect(self._measure)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Choose intensity layer"))
        layout.addWidget(self.intensity_layer_dropdown)
        layout.addLayout(checkbox_layout)
        layout.addWidget(QLabel("Choose optional regions labels layer"))
        layout.addWidget(self.regions_dropdown)
        layout.addWidget(self.measure_btn)
        layout.addWidget(self.table_widget)

        self.setLayout(layout)

    def _update(
        self, points: napari.layers.Points, data: pd.DataFrame
    ) -> None:
        """Update the points"""

        self.points = points
        self.points.filter = False  # add custom filter boolean
        self.dimensions = []
        if "t" in data.columns:
            self.dimensions.append("t")
        if "z" in data.columns:
            self.dimensions.append("z")
        self.dimensions.append("y")
        self.dimensions.append("x")

        self._check_activation()
        self.table_widget.set_content({})  # reset

    def _update_visibility(self) -> None:
        """Update visibility of points not in any region"""

        if (
            self.use_regions_checkbox.isChecked
            and self.hide_points_checkbox.isChecked()
            and "region" in self.table_widget._table.columns
        ):
            self.points.shown = self.table_widget._table["region"] > 0
            self.points.filter = True
        else:
            self.points.shown = True
            self.points.filter = False

    def _select_point(self, point_index: int) -> None:
        """Select the point in the point layer when it was clicked in the table"""

        selection = Selection()
        selection.add(point_index)
        self.points.selected_data = selection
        self.points.refresh()

        point = self.points.data[point_index]
        self.viewer.dims.current_step = (
            int(point[i] + 0.5) for i in range(len(point))
        )

    def _check_activation(self) -> None:
        """Check whether the measure button should be active or not"""

        if (
            self.intensity_layer is not None
            and self.points is not None
            and not (
                self.regions is None and self.use_regions_checkbox.isChecked()
            )
        ):
            self.measure_btn.setEnabled(True)
        else:
            self.measure_btn.setEnabled(False)

        if self.use_regions_checkbox.isChecked():
            self.hide_points_checkbox.setEnabled(True)
        else:
            self.hide_points_checkbox.setEnabled(False)

    def _update_intensity_layer(self, selected_layer) -> None:
        """Update the intensity layer via the dropdown"""

        if selected_layer == "":
            self.intensity_layer = None
        else:
            self.intensity_layer = self.viewer.layers[selected_layer]
            self.intensity_layer_dropdown.setCurrentText(selected_layer)

        self._check_activation()

    def _update_regions_layer(self, selected_layer) -> None:
        """Update the regions layer via the dropdown"""

        if selected_layer == "":
            self.regions = None
        else:
            self.regions = self.viewer.layers[selected_layer]
            self.regions_dropdown.setCurrentText(selected_layer)

        self._check_activation()

    def _measure(self) -> None:
        """Measure the intensity of the points in the intensity layer, optionally per region"""

        points = np.asarray(self.points.data)
        coordinates = (points + 0.5).astype(int)
        intensities = self.intensity_layer.data.take(
            np.ravel_multi_index(
                coordinates.T, self.intensity_layer.data.shape
            )
        )

        data = {
            "point": np.asarray(list(range(len(points)))),
            "intensity": intensities,
            "x": coordinates[:, -1],
            "y": coordinates[:, -2],
        }

        if "z" in self.dimensions and "t" not in self.dimensions:
            data["z"] = coordinates[:, -3]
        elif "t" in self.dimensions and "z" not in self.dimensions:
            data["t"] = coordinates[:, -3]
        elif "t" in self.dimensions and "z" in self.dimensions:
            data["z"] = coordinates[:, -3]
            data["t"] = coordinates[:, -4]

        if self.use_regions_checkbox.isChecked():
            if isinstance(self.regions, napari.layers.Shapes):
                self.regions.visible = False
                # convert to labels
                self.regions = self.viewer.add_labels(
                    self.regions.to_labels(self.intensity_layer.data.shape)
                )

            # Retrieve the labels at the point coordinates
            if self.points.data.shape[1] == 2:  # 2D points
                point_labels = self.regions.data[data["y"], data["x"]]
            elif "z" in self.dimensions and "t" not in self.dimensions:
                point_labels = self.regions.data[
                    data["z"], data["y"], data["x"]
                ]
            elif "t" in self.dimensions and "z" not in self.dimensions:
                point_labels = self.regions.data[
                    data["t"], data["y"], data["x"]
                ]
            elif "t" in self.dimensions and "z" in self.dimensions:
                point_labels = self.regions.data[
                    data["t"], data["z"], data["y"], data["x"]
                ]
            else:
                raise ValueError(
                    f"Unsupported number of dimensions: {points.shape[1]}"
                )

            data["region"] = point_labels
            self.table_widget.set_content(data, self.regions.colormap)
        else:
            self.table_widget.set_content(data)

        self._update_visibility()
        self.points.properties = data
