import copy
import os

import napari
import numpy as np
import pandas as pd
from psygnal import Signal

from qtpy.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QGroupBox
)

from .custom_range_slider_widget import CustomRangeSliderWidget

class SelectionWidget(QWidget):
    """QWidget displaying range sliders for trackpy detection measurements to select objects"""

    points_updated = Signal()

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.points = None
        self.sliders = []

        box = QGroupBox("Refine selection")

        # initiate the slider layout to be populated later
        self.sliders_layout = QVBoxLayout()

        self.confirm_btn = QPushButton("Confirm current selection")
        self.confirm_btn.clicked.connect(self._confirm_points)
        self.confirm_btn.setEnabled(False)

        box_layout = QVBoxLayout()
        box_layout.addLayout(self.sliders_layout)
        box_layout.addWidget(self.confirm_btn)
        box.setLayout(box_layout)

        layout = QVBoxLayout()
        layout.addWidget(box)

        self.setLayout(layout)
        self.setMaximumHeight(500)

    def _update_points_and_sliders(
        self, df: pd.DataFrame, intensity_layer: napari.layers.Image
    ):
        """Initializes the points layer based on the detection dataframe, and the sliders for filtering"""

        self.df = df
        self.filtered_df = df
        self.intensity_layer = intensity_layer

        if self.points is not None and self.points in self.viewer.layers:
            self.viewer.layers.remove(self.points)
        self.points = None

        self._update_points(df)

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

        self.confirm_btn.setEnabled(True)

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
        elif "z" in columns:
            # 3D data: zyx
            coordinates_df = df[["z", "y", "x"]]
            coordinates_array = coordinates_df.to_numpy()
        elif "t" in columns:
            # 3D data: tyx
            coordinates_df = df[["t", "y", "x"]]
            coordinates_array = coordinates_df.to_numpy()
        else:
            # 2D data: yx
            coordinates_df = df[["y", "x"]]
            coordinates_array = coordinates_df.to_numpy()

        # Reshape the array based on the number of dimensions
        coordinates = coordinates_array.reshape(-1, coordinates_array.shape[1])

        # Create or update the points layer
        if self.points is None:
            self.points = self.viewer.add_points(
                name="Detected objects",
                data=coordinates,
                face_color="cyan",
                opacity=0.5,
            )
        else:
            self.points.data = coordinates
    
    def _confirm_points(self): 
        self.points.face_color = 'red'
        self.points.out_of_slice_display = True
        self.points_updated.emit()
        self.confirm_btn.setEnabled(False)
        for slider_widget in self.sliders:
            slider_widget.setEnabled(False)