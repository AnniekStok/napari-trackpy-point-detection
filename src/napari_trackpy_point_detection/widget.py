import napari
from qtpy.QtWidgets import (
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .utilities.measure_widget import MeasureWidget
from .utilities.selection_widget import SelectionWidget
from .utilities.trackpy_widget import TrackpyWidget


class PointDetection(QWidget):
    """Main QWidget for point detection with Trackpy, visualization, and filtering"""

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        self.viewer = viewer

        # initializations
        self.intensity_layer = None

        # initialize trackpy widget
        self.trackpy_widget = TrackpyWidget(self.viewer)
        self.trackpy_widget.setMaximumHeight(600)
        self.trackpy_widget.points_detected.connect(self._update_points)

        # initialize selection widget
        self.selection_widget = SelectionWidget(self.viewer)
        self.selection_widget.points_updated.connect(self._update_measurements)
        self.selection_widget.setMaximumHeight(500)

        # initialize measurements widget
        self.measurements_widget = MeasureWidget(self.viewer)

        # Create a tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(self.trackpy_widget, "Trackpy Configuration")
        self.tab_widget.addTab(self.selection_widget, "Selection Criteria")
        self.tab_widget.addTab(self.measurements_widget, "Measurements")
        self.tab_widget.setCurrentIndex(0)

        # set main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(self.tab_widget)
        self.setLayout(main_layout)

    def _update_points(self):
        """Call the selection widget to update the points and sliders based on the data calculated in the trackpy_widget class"""

        self.selection_widget._update_points_and_sliders(
            self.trackpy_widget.df, self.trackpy_widget.intensity_layer
        )

    def _update_measurements(self):
        """Updates the points layer in the measurements widget"""

        self.measurements_widget._update(
            self.selection_widget.points, self.trackpy_widget.df
        )
