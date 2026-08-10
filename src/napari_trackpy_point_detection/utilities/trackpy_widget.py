import warnings

import dask.array as da
import napari
import numpy as np
import pandas as pd
import trackpy
from napari.layers import Image
from psygnal import Signal
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
from scipy.ndimage import gaussian_filter

from .layer_dropdown import LayerDropdown


def downsample_and_blur(img: np.ndarray, factors: list[int], sigmas:list[int]) -> np.ndarray:
    """Bin and apply gaussian filter"""

    if not all(f == 1 for f in factors):
        cropped_shape = tuple((s // factors[i]) * factors[i] for i, s in enumerate(img.shape))
        slices = tuple(slice(0, s) for s in cropped_shape)
        img = img[slices]

        reshaped_shape = []
        for i, s in enumerate(cropped_shape):
            reshaped_shape.extend([s // factors[i], factors[i]])

        reshaped = img.reshape(reshaped_shape)
        img = reshaped.mean(axis=tuple(range(1, len(reshaped_shape), 2)))

    if not all(s == 1 for s in sigmas):
        img = gaussian_filter(img, sigmas)

    return img

class TrackpyWidget(QWidget):
    """Widget for running detection with trackpy on an open image"""

    points_detected = Signal()

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        self.viewer = viewer

        self.intensity_layer = None
        self.df = None

        self.use_z = False

        # Add a dropdown to select layer
        self.layer_dropdown = LayerDropdown(self.viewer, (Image))
        self.layer_dropdown.layer_changed.connect(self._update_layer)

        # Ask use if there is a Z axis
        self.z_dim_cb = QCheckBox("Use Z dimension?")
        self.z_dim_cb.setToolTip(
            "If disabled but your data is 3D, the third dimension will be interpreted as time and not as z"
        )
        self.z_dim_cb.setToolTipDuration(5000)
        self.z_dim_cb.setChecked(False)
        self.z_dim_cb.stateChanged.connect(self._toggle_z)

        # Add trackpy detection configuration.
        diameter_settings = QGroupBox("Object diameter (odd number, pixels)")
        diameter_settings_layout = QVBoxLayout()

        xy_diameter_layout = QHBoxLayout()
        self.diameter_spinbox_xy = QSpinBox()
        self.diameter_spinbox_xy.setMinimum(1)
        self.diameter_spinbox_xy.setMaximum(501)
        self.diameter_spinbox_xy.setValue(31)
        self.diameter_spinbox_xy.setSingleStep(2)

        xy_diameter_widget = QWidget()
        xy_label = QLabel("XY")
        xy_label.setMinimumWidth(50)
        xy_diameter_layout.addWidget(xy_label)
        xy_diameter_layout.addWidget(self.diameter_spinbox_xy)
        xy_diameter_layout.setContentsMargins(0, 0, 0, 0)
        xy_diameter_widget.setLayout(xy_diameter_layout)

        diameter_settings_layout.addWidget(xy_diameter_widget)

        # Z diameter (optional)
        z_label = QLabel("Z")
        z_label.setMinimumWidth(50)

        self.diameter_spinbox_z = QSpinBox()
        self.diameter_spinbox_z.setMinimum(1)
        self.diameter_spinbox_z.setMaximum(501)
        self.diameter_spinbox_z.setValue(9)
        self.diameter_spinbox_z.setSingleStep(2)

        z_diameter_layout = QHBoxLayout()
        z_diameter_layout.addWidget(z_label)
        z_diameter_layout.setContentsMargins(0, 0, 0, 0)
        z_diameter_layout.addWidget(self.diameter_spinbox_z)

        self.z_diameter_widget = QWidget()
        self.z_diameter_widget.setLayout(z_diameter_layout)

        # assemble widgets in layout
        diameter_settings_layout.addWidget(self.z_diameter_widget)
        diameter_settings.setLayout(diameter_settings_layout)

        # settings for separation
        separation_settings = QGroupBox("Object separation (pixels)")
        separation_settings_layout = QVBoxLayout()

        xy_label = QLabel("XY")
        xy_label.setMinimumWidth(50)

        self.separation_spinbox_xy = QDoubleSpinBox()
        self.separation_spinbox_xy.setMaximum(500)
        self.separation_spinbox_xy.setValue(32)

        xy_separation_widget = QWidget()
        xy_separation_layout = QHBoxLayout()
        xy_separation_layout.addWidget(xy_label)
        xy_separation_layout.addWidget(self.separation_spinbox_xy)
        xy_separation_layout.setContentsMargins(0, 0, 0, 0)
        xy_separation_widget.setLayout(xy_separation_layout)

        separation_settings_layout.addWidget(xy_separation_widget)

        # Separation in Z (optional)
        z_label = QLabel("Z")
        z_label.setMinimumWidth(50)

        self.separation_spinbox_z = QDoubleSpinBox()
        self.separation_spinbox_z.setMaximum(500)
        self.separation_spinbox_z.setValue(9)

        self.z_separation_widget = QWidget()
        z_separation_layout = QHBoxLayout()
        z_separation_layout.addWidget(z_label)
        z_separation_layout.addWidget(self.separation_spinbox_z)
        z_separation_layout.setContentsMargins(0, 0, 0, 0)
        self.z_separation_widget.setLayout(z_separation_layout)

        # assemble widgets in layout)
        separation_settings_layout.addWidget(self.z_separation_widget)
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

        # Downsample and blur to speed up detections
        downsample_settings = QGroupBox("Optional downsampling and gaussian blur")
        downsample_settings.setToolTip("Optionally, the data can be downscaled and/or a gaussian blur can be applied to speed up or improve the detection process. Downsampling occurs internally and detected points will be placed back in the original dimensions. A value of 1 will not downsample or apply a blur")
        downsample_settings_layout = QVBoxLayout()

        downsample_label_xy = QLabel("XY")
        self.xy_downsample = QSpinBox()
        self.xy_downsample.setMinimum(1)
        self.xy_downsample.setMaximum(10)
        self.xy_downsample.setValue(4)
        self.xy_downsample.setToolTip("Downsampling factor in XY. A value of 1 will not downsample.")

        downsample_xy_widget = QWidget()
        downsample_xy_layout = QHBoxLayout()
        downsample_xy_layout.addWidget(downsample_label_xy)
        downsample_xy_layout.addWidget(self.xy_downsample)
        downsample_xy_layout.setContentsMargins(0, 0, 0, 0)
        downsample_xy_widget.setLayout(downsample_xy_layout)

        downsample_label_z = QLabel("Z")
        self.z_downsample = QSpinBox()
        self.z_downsample.setMinimum(1)
        self.z_downsample.setMaximum(10)
        self.z_downsample.setValue(2)
        self.z_downsample.setToolTip("Downsampling factor in Z. A value of 1 will not downsample.")

        z_downsample_layout = QHBoxLayout()
        z_downsample_layout.addWidget(downsample_label_z)
        z_downsample_layout.addWidget(self.z_downsample)
        z_downsample_layout.setContentsMargins(0, 0, 0, 0)
        self.z_downsample_widget = QWidget()
        self.z_downsample_widget.setLayout(z_downsample_layout)

        sigma_label_xy = QLabel("Sigma XY")
        self.xy_sigma = QSpinBox()
        self.xy_sigma.setMinimum(1)
        self.xy_sigma.setMaximum(10)
        self.xy_sigma.setValue(2)
        self.xy_sigma.setToolTip("Gaussian blur sigma in XY. A value of 1 will not apply a blur")

        sigma_xy_widget = QWidget()
        sigma_xy_layout = QHBoxLayout()
        sigma_xy_layout.addWidget(sigma_label_xy)
        sigma_xy_layout.addWidget(self.xy_sigma)
        sigma_xy_layout.setContentsMargins(0, 0, 0, 0)
        sigma_xy_widget.setLayout(sigma_xy_layout)

        sigma_label_z = QLabel("Sigma Z")
        self.z_sigma = QSpinBox()
        self.z_sigma.setMinimum(1)
        self.z_sigma.setMaximum(10)
        self.z_sigma.setValue(1)
        self.z_sigma.setToolTip("Gaussian blur sigma in Z. A value of 1 will not apply a blur")

        z_sigma_layout = QHBoxLayout()
        z_sigma_layout.addWidget(sigma_label_z)
        z_sigma_layout.addWidget(self.z_sigma)
        z_sigma_layout.setContentsMargins(0, 0, 0, 0)
        self.z_sigma_widget = QWidget()
        self.z_sigma_widget.setLayout(z_sigma_layout)

        downsample_settings_layout.addWidget(downsample_xy_widget)
        downsample_settings_layout.addWidget(self.z_downsample_widget)
        downsample_settings_layout.addWidget(sigma_xy_widget)
        downsample_settings_layout.addWidget(self.z_sigma_widget)

        downsample_settings.setLayout(downsample_settings_layout)

        # button to start detecting
        self.detect_trackpy_btn = QPushButton("Detect objects")
        self.detect_trackpy_btn.clicked.connect(self._run)
        self.detect_trackpy_btn.setEnabled(False)

        # combine all settings
        settings_layout = QVBoxLayout()
        settings_layout.addWidget(self.layer_dropdown)
        settings_layout.addWidget(self.z_dim_cb)
        settings_layout.addWidget(diameter_settings)
        settings_layout.addWidget(separation_settings)
        settings_layout.addWidget(percentile_settings)
        settings_layout.addWidget(downsample_settings)
        settings_layout.addWidget(self.detect_trackpy_btn)

        self.setLayout(settings_layout)
        self.setMaximumHeight(1100)
        self._toggle_z(False)

    def _toggle_z(self, state: bool) -> None:
        """Toggle between enabling/disabling the use of the z dimension for object detecction"""

        if state:
            self.z_diameter_widget.setEnabled(True)
            self.z_diameter_widget.setVisible(True)
            self.z_separation_widget.setVisible(True)
            self.z_separation_widget.setEnabled(True)
            self.z_downsample_widget.setVisible(True)
            self.z_downsample_widget.setEnabled(True)
            self.z_sigma_widget.setVisible(True)
            self.z_sigma_widget.setEnabled(True)
            self.use_z = True
        else:
            self.z_diameter_widget.setEnabled(False)
            self.z_diameter_widget.setVisible(False)
            self.z_separation_widget.setVisible(False)
            self.z_separation_widget.setEnabled(False)
            self.z_downsample_widget.setVisible(False)
            self.z_downsample_widget.setEnabled(False)
            self.z_sigma_widget.setVisible(False)
            self.z_sigma_widget.setEnabled(False)
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
                self.z_dim_cb.setEnabled(False)
            elif len(shape) == 4:  # 3D + time, force activate the z dimension
                self.z_dim_cb.setChecked(True)
                self.z_dim_cb.setEnabled(False)
            else:  # user has to decide whether this is 2D + time or 3D xyz
                self.z_dim_cb.setEnabled(True)

    def _run(self) -> None:
        """Run detection"""

        self.df = self._detect()
        self.points_detected.emit()
        if self.viewer.dims.ndim > 2:
            self.viewer.dims.ndisplay = 3


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

        # make sure that odd integers are used
        value_xy = self.diameter_spinbox_xy.value()
        if value_xy % 2 == 0:
            self.diameter_spinbox_xy.setValue(value_xy + 1)
            warnings.warn("Updated value to next odd integer", stacklevel=2)
        value_z = self.diameter_spinbox_z.value()
        if value_z % 2 == 0 and self.use_z:
            self.diameter_spinbox_z.setValue(value_z + 1)
            warnings.warn("Updated value to next odd integer", stacklevel=2)

        xy_downsample = self.xy_downsample.value()
        z_downsample = self.z_downsample.value()
        xy_diameter = int(self.diameter_spinbox_xy.value() / xy_downsample) | 1
        z_diameter = int(self.diameter_spinbox_z.value() / z_downsample) | 1
        xy_separation = self.separation_spinbox_xy.value() / xy_downsample
        z_separation = self.separation_spinbox_z.value() / z_downsample
        xy_sigma = self.xy_sigma.value()
        z_sigma = self.z_sigma.value()
        percentile=self.percentile_spinbox.value()

        img = self.intensity_layer.data

        diameter = [xy_diameter, xy_diameter]
        separation = [xy_separation, xy_separation]
        downsample = [xy_downsample, xy_downsample]
        sigmas = [xy_sigma, xy_sigma]
        if self.use_z:
            diameter.insert(0, z_diameter)
            separation.insert(0, z_separation)
            downsample.insert(0, z_downsample)
            sigmas.insert(0, z_sigma)

        # single image
        if img.ndim == 2 or (img.ndim == 3 and self.use_z):
            img = downsample_and_blur(img, downsample, sigmas)
            d = trackpy.locate(
                img,
                diameter=diameter,
                separation=separation,
                percentile=percentile
            )

        # looping over the first dimensions
        else:
            d = []
            for t in range(img.shape[0]):
                if isinstance(img, da.core.Array):
                    img_t = img[t].compute()
                else:
                    img_t = img[t]

                img_t = downsample_and_blur(img_t, downsample, sigmas)
                d_t = trackpy.locate(
                    img_t,
                    diameter=diameter,
                    separation=separation,
                    percentile=percentile
                )
                d_t["t"] = t
                d.append(d_t)
            d = pd.concat(d, ignore_index=True)

        d = d.round(3)
        d['x'] = d['x'] * downsample[-1]
        d['y'] = d['y'] * downsample[-2]
        if self.use_z:
            d['z'] = d['z'] * downsample[-3]

        return d


