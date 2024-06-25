import numpy as np
from qtpy import QtCore
from qtpy.QtWidgets import (
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from superqt import QLabeledSlider


class PlaneSlider(QWidget):
    """QWidget for sliding through the z-plane"""

    def __init__(self, viewer):
        super().__init__()

        self.viewer = viewer
        self.points = None

        # buttons for switching between plane and volume view
        self.plane_btn = QPushButton("Plane")
        self.plane_btn.clicked.connect(self._set_plane_mode)
        self.plane_btn.setEnabled(False)
        self.volume_btn = QPushButton("Volume")
        self.volume_btn.clicked.connect(self._set_volume_mode)
        self.volume_btn.setEnabled(False)

        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.plane_btn)
        btn_layout.addWidget(self.volume_btn)

        # Slider widget to move through the plane stack in 3D
        self.slider = QLabeledSlider(QtCore.Qt.Horizontal)
        self.slider.setSingleStep(1)
        self.slider.setTickInterval(1)
        self.slider.setValue(0)
        self.slider.valueChanged.connect(self._set_plane)
        self.slider.setEnabled(False)

        layout = QVBoxLayout()
        layout.addLayout(btn_layout)
        layout.addWidget(self.slider)
        self.setLayout(layout)

    def _set_maximum(self, value: int | float):
        """Activate the slider and set the maximum value depending on the data associated with it"""

        self.slider.setEnabled(True)
        self.slider.setMaximum(value)
        self._set_volume_mode()

    def _set_plane(self):
        """Set the plane of the intensity image to the value of the slider and adjust visible points accordingly"""

        plane_position = self.slider.value()
        pos = self.intensity_layer.plane.position
        self.intensity_layer.plane.position = (plane_position, pos[1], pos[2])

        # only show points close to the plane position
        to_show = np.zeros(self.points.data.shape[0], dtype=bool)
        to_show = (self.points.data[:, 0] >= (plane_position - 5)) & (
            self.points.data[:, 0] <= (plane_position + 5)
        )
        self.points.shown = to_show

    def _set_plane_mode(self):
        """Switch depiction to plane mode and enable/disable buttons"""

        self.viewer.dims.ndisplay = 3
        self.intensity_layer.depiction = "plane"
        self.slider.setEnabled(True)
        self.plane_btn.setEnabled(False)
        self.volume_btn.setEnabled(True)
        if self.points is not None:
            self._set_plane()

    def _set_volume_mode(self):
        """Switch depiction to volume mode and enable/disable buttons"""

        self.viewer.dims.ndisplay = 3
        self.intensity_layer.depiction = "volume"
        self.slider.setEnabled(False)
        self.plane_btn.setEnabled(True)
        self.volume_btn.setEnabled(False)
        if self.points is not None:
            self.points.shown = True
