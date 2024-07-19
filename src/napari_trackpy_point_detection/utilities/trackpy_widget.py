import napari
import numpy as np
import pandas as pd
import trackpy
from napari.layers import Image
from PyQt5.QtCore import pyqtSignal
from qtpy.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .layer_dropdown import LayerDropdown


class TrackpyWidget(QWidget):
    """Widget for running detection with trackpy on an open image"""

    points_detected = pyqtSignal()

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        self.viewer = viewer

        self.intensity_layer = None
        self.df = None

        self.use_z = False

        settings_layout = QVBoxLayout()

        # Add a dropdown to select layer
        self.layer_dropdown = LayerDropdown(self.viewer, (Image))
        self.layer_dropdown.layer_changed.connect(self._update_layer)
        settings_layout.addWidget(self.layer_dropdown)

        # Add trackpy detection configuration.
        diameter_settings = QGroupBox("Object diameter (odd number)")
        diameter_settings_layout = QVBoxLayout()

        xy_diameter_layout = QHBoxLayout()
        self.diameter_spinbox_xy = QSpinBox()
        self.diameter_spinbox_xy.setMinimum(1)
        self.diameter_spinbox_xy.setMaximum(501)
        self.diameter_spinbox_xy.setValue(9)
        self.diameter_spinbox_xy.setSingleStep(2)

        xy_label = QLabel("XY")
        xy_label.setMinimumWidth(50)
        xy_diameter_layout.addWidget(xy_label)

        xy_diameter_layout.addWidget(self.diameter_spinbox_xy)
        diameter_settings_layout.addLayout(xy_diameter_layout)

        z_diameter_layout = QHBoxLayout()
        self.diameter_z_cb = QCheckBox("Use Z dimension?")
        self.diameter_z_cb.setToolTip(
            "If disabled but your data is 3D, the third dimension will be interpreted as time and not as z"
        )
        self.diameter_z_cb.setToolTipDuration(5000)
        self.diameter_z_cb.stateChanged.connect(self._toggle_z)

        self.diameter_spinbox_z = QSpinBox()
        self.diameter_spinbox_z.setMinimum(1)
        self.diameter_spinbox_z.setMaximum(501)
        self.diameter_spinbox_z.setValue(9)
        self.diameter_spinbox_z.setEnabled(False)
        self.diameter_spinbox_z.setSingleStep(2)

        z_label = QLabel("Z")
        z_label.setMinimumWidth(50)
        z_diameter_layout.addWidget(z_label)
        z_diameter_layout.addWidget(self.diameter_spinbox_z)

        diameter_settings_layout.addWidget(self.diameter_z_cb)
        diameter_settings_layout.addLayout(z_diameter_layout)
        diameter_settings.setLayout(diameter_settings_layout)

        # settings for separation
        separation_settings = QGroupBox("Object separation")
        separation_settings_layout = QVBoxLayout()

        xy_separation_layout = QHBoxLayout()
        self.separation_spinbox_xy = QDoubleSpinBox()
        self.separation_spinbox_xy.setMaximum(500)
        self.separation_spinbox_xy.setValue(9)

        xy_label = QLabel("X")
        xy_label.setMinimumWidth(50)
        xy_separation_layout.addWidget(xy_label)

        xy_separation_layout.addWidget(self.separation_spinbox_xy)
        separation_settings_layout.addLayout(xy_separation_layout)

        z_separation_layout = QHBoxLayout()
        self.separation_z_cb = QCheckBox("Use Z dimension?")
        self.separation_z_cb.setToolTip(
            "If disabled but your data is 3D, the third dimension will be interpreted as time and not as z"
        )
        self.separation_z_cb.setToolTipDuration(5000)
        self.separation_z_cb.stateChanged.connect(self._toggle_z)

        self.separation_spinbox_z = QDoubleSpinBox()
        self.separation_spinbox_z.setMaximum(500)
        self.separation_spinbox_z.setValue(9)
        self.separation_spinbox_z.setEnabled(False)

        z_label = QLabel("Z")
        z_label.setMinimumWidth(50)
        z_separation_layout.addWidget(z_label)
        z_separation_layout.addWidget(self.separation_spinbox_z)

        separation_settings_layout.addWidget(self.separation_z_cb)
        separation_settings_layout.addLayout(z_separation_layout)
        separation_settings.setLayout(separation_settings_layout)

        # percentile settings
        percentile_settings = QGroupBox("Intensity percentile threshold")
        percentile_settings_layout = QHBoxLayout()
        percentile_label = QLabel("Percentile")
        self.percentile_spinbox = QSpinBox()
        self.percentile_spinbox.setMinimum(1)
        self.percentile_spinbox.setMaximum(100)
        self.percentile_spinbox.setValue(64)
        percentile_settings_layout.addWidget(percentile_label)
        percentile_settings_layout.addWidget(self.percentile_spinbox)
        percentile_settings.setLayout(percentile_settings_layout)

        # button to start detecting
        self.detect_trackpy_btn = QPushButton("Detect objects")
        self.detect_trackpy_btn.clicked.connect(self._run)
        self.detect_trackpy_btn.setEnabled(False)

        # combine all settings
        settings_layout.addWidget(diameter_settings)
        settings_layout.addWidget(separation_settings)
        settings_layout.addWidget(percentile_settings)
        settings_layout.addWidget(self.detect_trackpy_btn)

        self.setLayout(settings_layout)

    def _toggle_z(self, state: bool) -> None:
        """Toggle between enabling/disabling the use of the z dimension for object detecction"""

        if state:
            self.diameter_z_cb.setChecked(True)
            self.separation_z_cb.setChecked(True)
            self.diameter_spinbox_z.setEnabled(True)
            self.separation_spinbox_z.setEnabled(True)
            self.use_z = True
        else:
            self.diameter_z_cb.setChecked(False)
            self.separation_z_cb.setChecked(False)
            self.diameter_spinbox_z.setEnabled(False)
            self.separation_spinbox_z.setEnabled(False)
            self.use_z = False

    def _update_layer(self, selected_layer) -> None:
        """Update the layer that is set to be the 'labels' layer that is being edited."""

        if selected_layer == "":
            self.intensity_layer = None
        else:
            self.intensity_layer = self.viewer.layers[selected_layer]
            self.layer_dropdown.setCurrentText(selected_layer)

        if self.intensity_layer is None:
            self.detect_trackpy_btn.setEnabled(False)
        else:
            self.detect_trackpy_btn.setEnabled(True)

        self._check_dimensions()

    def _check_dimensions(self) -> None:
        """Checks the dimensions of the selected image to know whether to do detection in 2D or 3D"""

        if self.intensity_layer is not None:
            shape = self.intensity_layer.data.shape
            if len(shape) == 2:  # 2D, force deactivate the z dimension
                self.use_z = False
                self.diameter_z_cb.setChecked(False)
                self.diameter_z_cb.setEnabled(False)
                self.separation_z_cb.setChecked(False)
                self.separation_z_cb.setEnabled(False)
                self.diameter_spinbox_z.setEnabled(False)
                self.separation_spinbox_z.setEnabled(False)
            elif len(shape) == 4:  # 3D + time, force activate the z dimension
                self.diameter_z_cb.setChecked(True)
                self.diameter_z_cb.setEnabled(False)
                self.separation_z_cb.setChecked(True)
                self.separation_z_cb.setEnabled(False)
                self.diameter_spinbox_z.setEnabled(True)
                self.separation_spinbox_z.setEnabled(True)
            else:  # user has to decide whether this is 2D + time or 3D xyz
                self.diameter_z_cb.setEnabled(True)
                self.separation_z_cb.setEnabled(True)

    def _run(self) -> None:
        """Run detection"""

        self.df = self._detect()
        self.points_detected.emit()

    def _detect(self) -> pd.DataFrame:
        """Load the image data, and run trackpy.locate to detect objects"""

        self.intensity_layer.data = np.squeeze(self.intensity_layer.data)

        if not (
            len(self.intensity_layer.data.shape) >= 2
            and len(self.intensity_layer.data.shape) <= 4
        ):
            msg = QMessageBox()
            msg.setWindowTitle("Invalid dimensions")
            msg.setText(
                "Please select an image that has 2-4 dimensions (x, y, (z), (t)). Current image has",
                str(len(self.intensity_layer.data.shape)),
                "dimensions.",
            )
            msg.setIcon(QMessageBox.Information)
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
            return

        elif len(self.intensity_layer.data.shape) == 2:
            diameter = (
                self.diameter_spinbox_xy.value(),
                self.diameter_spinbox_xy.value(),
            )

            separation = (
                self.separation_spinbox_xy.value(),
                self.separation_spinbox_xy.value(),
            )

            d = trackpy.locate(
                self.intensity_layer.data,
                diameter=diameter,
                separation=separation,
                percentile=self.percentile_spinbox.value(),
            )

        elif len(self.intensity_layer.data.shape) == 3 and self.use_z:
            diameter = (
                self.diameter_spinbox_z.value(),
                self.diameter_spinbox_xy.value(),
                self.diameter_spinbox_xy.value(),
            )

            separation = (
                self.separation_spinbox_z.value(),
                self.separation_spinbox_xy.value(),
                self.separation_spinbox_xy.value(),
            )

            d = trackpy.locate(
                self.intensity_layer.data,
                diameter=diameter,
                separation=separation,
                percentile=self.percentile_spinbox.value(),
            )

        elif len(self.intensity_layer.data.shape) == 3 and not self.use_z:
            # interprete the third dimension as time in this case
            diameter = (
                self.diameter_spinbox_xy.value(),
                self.diameter_spinbox_xy.value(),
            )

            separation = (
                self.separation_spinbox_xy.value(),
                self.separation_spinbox_xy.value(),
            )

            d = []
            for t in range(self.intensity_layer.data.shape[0]):
                df = trackpy.locate(
                    self.intensity_layer.data[t],
                    diameter=diameter,
                    separation=separation,
                    percentile=self.percentile_spinbox.value(),
                )
                df["t"] = t
                d.append(df)

            d = pd.concat(d, ignore_index=True)

        elif len(self.intensity_layer.data.shape) == 4:
            diameter = (
                self.diameter_spinbox_z.value(),
                self.diameter_spinbox_xy.value(),
                self.diameter_spinbox_xy.value(),
            )

            separation = (
                self.separation_spinbox_z.value(),
                self.separation_spinbox_xy.value(),
                self.separation_spinbox_xy.value(),
            )

            d = []

            for t in range(self.intensity_layer.data.shape[0]):
                df = trackpy.locate(
                    self.intensity_layer.data[t],
                    diameter=diameter,
                    separation=separation,
                    percentile=self.percentile_spinbox.value(),
                )
                df["t"] = t
                d.append(df)
            d = pd.concat(d, ignore_index=True)

        d = d.round(3)

        return d
