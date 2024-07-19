import copy
import os

import napari
import numpy as np
import pandas as pd
from PyQt5.QtCore import pyqtSignal
from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .custom_range_slider_widget import CustomRangeSliderWidget
from .plane_slider import PlaneSlider


class SelectionWidget(QWidget):
    """QWidget displaying range sliders for trackpy detection measurements to select objects"""

    points_updated = pyqtSignal()

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.outputdir = ""
        self.points = None
        self.sliders = []

        # specify outputdir
        output_layout = QHBoxLayout()
        self.outputdirbtn = QPushButton("Select output directory")
        self.outputdirbtn.clicked.connect(self._on_get_output_dir)
        self.output_path = QLineEdit()
        self.output_path.textChanged.connect(self._update_outputdir)
        output_layout.addWidget(self.outputdirbtn)
        output_layout.addWidget(self.output_path)

        # Button for saving of filtered result.
        self.save_btn = QPushButton("Save selected objects")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save_results)

        # add plane slider
        self.plane_slider = PlaneSlider(self.viewer)
        self.plane_slider.setMaximumHeight(100)

        # initiate the slider layout to be populated later
        self.sliders_layout = QVBoxLayout()

        layout = QVBoxLayout()
        layout.addLayout(output_layout)
        layout.addWidget(self.save_btn)
        layout.addLayout(self.sliders_layout)
        layout.addWidget(self.plane_slider)
        self.setLayout(layout)

    def _update_outputdir(self) -> None:
        """Update the output directory when the user modifies the text in the QLineEdit widget"""

        self.outputdir = str(self.output_path.text())

    def _on_get_output_dir(self) -> None:
        """Open a dialog to choose a label directory"""

        path = QFileDialog.getExistingDirectory(self, "Select output folder")
        if path:
            self.output_path.setText(path)
            self.outputdir = str(self.output_path.text())

    def _save_results(self) -> None:
        """Save the points based on the current selection in the points layer"""

        if len(self.outputdir) == 0 or not os.path.exists(self.outputdir):
            self._on_get_output_dir()

        pointdata = pd.DataFrame(self.points.data)
        pointdata = pointdata.reset_index()

        # Rename the columns so that they are recognized by napari when reading back in
        new_columns = ["index"] + [
            f"axis-{i}" for i in range(pointdata.shape[1] - 1)
        ]
        pointdata.columns = new_columns

        filename = self.intensity_layer.name + "_points.csv"
        pointdata.to_csv(os.path.join(self.outputdir, filename), index=False)

    def _update_points_and_sliders(
        self, df: pd.DataFrame, intensity_layer: napari.layers.Image
    ):
        """Initializes the points layer based on the detection dataframe, and the sliders for filtering"""

        self.df = df
        self.filtered_df = df
        self.intensity_layer = intensity_layer
        self.save_btn.setEnabled(True)

        if self.points is not None and self.points in self.viewer.layers:
            self.viewer.layers.remove(self.points)
        self.points = None

        self._update_points(df)
        self.initial_points = copy.deepcopy(self.points.data)

        filter_properties = [
            {
                "display_name": "Brightness",
                "name": "mass",
                "type": "int",
                "tip": "Total neighborhood brightness",
            },
            {
                "display_name": "Size",
                "name": "size",
                "type": "float",
                "tip": "Radius-of-gyration of brightness of Gaussian-like profile",
            },
            {
                "display_name": "Size XY",
                "name": "size_x",
                "type": "float",
                "tip": "Radius-of-gyration of brightness of Gaussian-like profile",
            },
            {
                "display_name": "Size Z",
                "name": "size_z",
                "type": "float",
                "tip": "Radius-of-gyration of brightness of Gaussian-like profile",
            },
        ]

        # Create a range slider widget for each of the properties.
        self.sliders = []
        for prop in filter_properties:
            if prop["name"] in self.df.columns:
                slider_widget = CustomRangeSliderWidget(
                    self.df,
                    name=prop["name"],
                    display_name=prop["display_name"],
                    dtype=prop["type"],
                    tip=prop["tip"],
                )
                # Connect filtering of object to change in value of the range slider.
                slider_widget.range_slider._slider.valueChanged.connect(
                    lambda: self._filter_objects(self.df)
                )
                slider_widget.range_slider._slider.rangeChanged.connect(
                    lambda: self._filter_objects(self.df)
                )
                slider_widget.setMinimumHeight(100)
                self.sliders.append(slider_widget)

        # remove any old sliders if there are any
        for i in reversed(range(self.sliders_layout.count())):
            self.sliders_layout.itemAt(i).widget().deleteLater()
        # add the new sliders
        for slider_widget in self.sliders:
            self.sliders_layout.addWidget(slider_widget)

    def _filter_objects(self, df: pd.DataFrame):
        """Filter the data in the points layer based on the slider settings"""

        masks = []
        for slider in self.sliders:
            # Create a mask for for each of the slider settings.
            prop = slider.name
            value = slider.range_slider._slider.value()
            mask = (df[prop] >= value[0]) & (df[prop] <= value[1])
            masks.append(mask)

        # Combine all masks.
        combined_mask = pd.Series(True, index=df.index)
        for mask in masks:
            combined_mask &= mask

        # Select the rows that satisfy all the criteria.
        self.filtered_df = df[combined_mask]

        # Update the points.
        self._update_points(self.filtered_df)

    def _update_points(self, df: pd.DataFrame) -> None:
        """Create a point layer from a pandas dataframe"""

        # Check which columns are present in the dataframe
        columns = df.columns
        if "t" in columns and "z" in columns:
            # 4D data: tzyx
            coordinates_df = df[["t", "z", "y", "x"]]
            coordinates_array = coordinates_df.to_numpy()
            self.plane_slider.intensity_layer = self.intensity_layer
            self.plane_slider._set_maximum(self.intensity_layer.data.shape[1])
        elif "z" in columns:
            # 3D data: zyx
            coordinates_df = df[["z", "y", "x"]]
            coordinates_array = coordinates_df.to_numpy()
            self.plane_slider.intensity_layer = self.intensity_layer
            self.plane_slider._set_maximum(self.intensity_layer.data.shape[0])
        elif "t" in columns:
            # 3D data: tyx
            coordinates_df = df[["t", "y", "x"]]
            coordinates_array = coordinates_df.to_numpy()
            self.plane_slider.slider.setEnabled(False)
        else:
            # 2D data: yx
            coordinates_df = df[["y", "x"]]
            coordinates_array = coordinates_df.to_numpy()
            self.plane_slider.slider.setEnabled(False)

        # Reshape the array based on the number of dimensions
        coordinates = coordinates_array.reshape(-1, coordinates_array.shape[1])

        # Create or update the points layer
        if self.points is None:
            self.points = self.viewer.add_points(
                name="Detected objects",
                data=coordinates,
                face_color="red",
                opacity=0.5,
            )
        else:
            current_points = self.points.data
            filtered_points = current_points[
                ~np.isin(current_points, self.initial_points).all(axis=1)
            ]  # to include manually edited points
            if len(filtered_points) > 0:
                self.points.data = np.vstack((coordinates, filtered_points))
                self.points.face_color = [
                    ["red"] * len(coordinates)
                    + ["blue"] * len(filtered_points)
                ]
            else:
                self.points.data = coordinates

        self.plane_slider.points = self.points
        self.points_updated.emit()
