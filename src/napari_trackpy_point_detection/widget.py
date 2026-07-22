import napari
from qtpy.QtWidgets import (
    QTabWidget,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from .utilities.measure_widget import MeasureWidget
from .utilities.selection_widget import SelectionWidget
from .utilities.trackpy_widget import TrackpyWidget

from napari_trackpy_point_detection.utilities.interactive_table_widget import InteractiveTableWidget

class PointDetection(QWidget):
    """Main QWidget for point detection with Trackpy, visualization, and filtering"""

    def __init__(self, viewer: napari.Viewer):
        super().__init__()
        self.viewer = viewer

        # initializations
        self.intensity_layer = None

        # initialize trackpy widget
        self.trackpy_widget = TrackpyWidget(self.viewer)
        self.trackpy_widget.points_detected.connect(self._update_points)

        # initialize selection widget
        self.selection_widget = SelectionWidget(self.viewer)
        self.selection_widget.points_updated.connect(self._finalize_trackpy_points)

        # assemble in tab1
        tab1_widget = QWidget()
        tab1_widget_layout = QVBoxLayout()
        tab1_widget_layout.addWidget(self.trackpy_widget)
        tab1_widget_layout.addWidget(self.selection_widget)
        tab1_widget.setLayout(tab1_widget_layout)
        
        # Create an interactive table in separate widget to navigate confirmed points
        self.table_widget = InteractiveTableWidget(self.selection_widget.points, self.viewer)

        # Create a tab widget
        self.tab_widget = QTabWidget()
        self.tab_widget.addTab(tab1_widget, "Trackpy Configuration")
        self.tab_widget.addTab(self.table_widget, "View and edit points")
        self.tab_widget.setCurrentIndex(0)

        # wrap in scroll area
        scroll_area = QScrollArea()
        scroll_area.setWidget(self.tab_widget)
        scroll_area.setWidgetResizable(True)

        # set main layout
        main_layout = QVBoxLayout()
        main_layout.addWidget(scroll_area)
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

    def _finalize_trackpy_points(self):
        """Accept this points layer and move on the to the second step where points can manually be edited"""

        self.table_widget._layer = self.selection_widget.points
        self.table_widget.refresh()
        self.tab_widget.setCurrentIndex(1)

