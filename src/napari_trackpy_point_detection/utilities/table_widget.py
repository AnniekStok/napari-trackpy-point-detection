import pandas as pd
from matplotlib.colors import to_rgb
from napari.utils.colormaps.colormap import CyclicLabelColormap
from PyQt5.QtCore import pyqtSignal
from qtpy.QtGui import QColor
from qtpy.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QWidget,
)


class TableWidget(QWidget):
    """
    napari_skimage_regionprops inspired TableWidget displaying point data measurements.
    """

    rowClicked = pyqtSignal(int)

    def __init__(self, data: dict):
        super().__init__()

        self._table = pd.DataFrame()
        self._view = QTableWidget()
        self._view.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._view.itemClicked.connect(self._on_item_clicked)

        copy_button = QPushButton("Copy to clipboard")
        copy_button.clicked.connect(self._copy_clicked)

        save_button = QPushButton("Save as csv...")
        save_button.clicked.connect(self._save_clicked)

        self.setLayout(QGridLayout())
        action_widget = QWidget()
        action_widget.setLayout(QHBoxLayout())
        action_widget.layout().addWidget(copy_button)
        action_widget.layout().addWidget(save_button)
        self.layout().addWidget(action_widget)
        self.layout().addWidget(self._view)
        action_widget.layout().setSpacing(3)
        action_widget.layout().setContentsMargins(0, 0, 0, 0)

        self.set_content(data)

    def _copy_clicked(self):
        """Send the dataframe to the clipboard"""

        pd.DataFrame(self._table).to_clipboard()

    def _save_clicked(self, event=None, filename=None):
        """Save the table to csv"""

        if filename is None:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save as csv...", ".", "*.csv"
            )
        pd.DataFrame(self._table).to_csv(filename)

    def _on_item_clicked(self, item):
        """Send a signal that a node was clicked"""

        self.rowClicked.emit(self._view.currentRow())

    def set_content(
        self, data: dict, colormap: CyclicLabelColormap | None = None
    ):
        """Update the displayed contents in the QTableWidget"""

        self._view.clear()
        self._table = pd.DataFrame.from_dict(data)
        if len(data) > 0:
            num_rows = len(
                next(iter(data.values()))
            )  # Assume all columns have the same number of rows
            num_cols = len(data)

            self._view.setColumnCount(num_cols)
            self._view.setRowCount(num_rows)

            # Set the table headers
            self._view.setHorizontalHeaderLabels(data.keys())

            # Fill the table with data
            for col, (header, column_data) in enumerate(data.items()):
                for row, item in enumerate(column_data):
                    # Convert item to string before creating QTableWidgetItem
                    item_str = str(item)
                    self._view.setItem(row, col, QTableWidgetItem(item_str))

                    if colormap is not None and "region" in data:
                        label = self._table["region"][row]
                        label_color = to_rgb(colormap.map(label))
                        scaled_color = (
                            int(label_color[0] * 255),
                            int(label_color[1] * 255),
                            int(label_color[2] * 255),
                        )
                        self._view.item(row, col).setBackground(
                            QColor(*scaled_color)
                        )
