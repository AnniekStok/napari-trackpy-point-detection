import dask.array as da
import napari
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from napari.utils import CyclicLabelColormap, DirectLabelColormap
from qtpy.QtCore import (
    QEvent,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    Qt,
    QTimer,
    QItemSelection,
    QSignalBlocker
)
from qtpy.QtGui import QColor, QPen
from qtpy.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

import copy

class NoSelectionHighlightDelegate(QStyledItemDelegate):
    """Prevents Qt from painting the default selection background,
    preserving each row's custom background color, and draws a cyan border instead."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)

        table = index.model().parent()

        if opt.state & QStyle.State_Selected:
            opt.state &= ~QStyle.State_Selected

        # Paint normally first (preserving your setBackground + setForeground)
        super().paint(painter, opt, index)

        # Draw a cyan border around the *entire row* if selected
        if index.row() in {i.row() for i in table.selectedIndexes()}:
            pen = QPen(Qt.cyan, 2)
            painter.setPen(pen)
            painter.drawRect(opt.rect.adjusted(1, 1, -2, -2))


class ClickToSingleSelectFilter(QObject):
    """Event filter to make plain left-clicks act like single selection
    while still allowing Ctrl/Shift clicks to behave normally (append/range)."""

    def __init__(self, table_widget):
        super().__init__(table_widget)
        self.table = table_widget

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.LeftButton
        ):
            modifiers = event.modifiers()
            if not (
                modifiers
                & (Qt.ShiftModifier | Qt.ControlModifier | Qt.MetaModifier)
            ):
                self.table.clearSelection()
            return False

        return False


class FloatDelegate(QStyledItemDelegate):
    def __init__(self, decimals, parent=None):
        super().__init__(parent)
        self.nDecimals = decimals

    def displayText(self, value, locale):
        try:
            number = float(value)
        except (ValueError, TypeError):
            return str(value)

        if number.is_integer():
            return str(int(number))
        return f"{number:.{self.nDecimals}f}"


class CustomTableWidget(QTableWidget):
    def mousePressEvent(self, event):
        index = self.indexAt(event.pos())
        if index.isValid():
            control = bool(event.modifiers() & Qt.ControlModifier)
            right = event.button() == Qt.RightButton
            self.parent()._clicked_table(
                right=right, ctrl=control, index=index
            )

        # Call super so selection behavior still works
        super().mousePressEvent(event)


class InteractiveTableWidget(QWidget):
    """Customized table widget"""

    def __init__(
        self, layer: "napari.layers.Points", viewer: "napari.Viewer" = None
    ):
        super().__init__()

        self._layer = layer
        self._viewer = viewer
        self._table_widget = CustomTableWidget()
        self._table_widget.selectionModel().selectionChanged.connect(
            self._selection_changed
        )
        self._updating_selection = False
        self._deleting_points = False
        self._selection_connected = False

        self._set_data()

        self.ascending = (
            False  # for choosing whether to sort ascending or descending
        )

        # Connect to single click in the header to sort the table.
        self._table_widget.horizontalHeader().sectionClicked.connect(
            self._sort_table
        )

        # Instruction label to explain left and right mouse click.
        label = QLabel(
            "Use left mouse click to select and center a label, use right mouse click to show the selected label only. Use Ctrl/Meta for multi-selection, Shift for range selection."
        )
        label.setWordWrap(True)
        font = label.font()
        font.setItalic(True)
        label.setFont(font)

        copy_button = QPushButton("Copy to clipboard")
        copy_button.clicked.connect(self._copy_table)

        save_button = QPushButton("Save as csv")
        save_button.clicked.connect(self._save_table)

        button_layout = QHBoxLayout()
        button_layout.addWidget(copy_button)
        button_layout.addWidget(save_button)

        delete_undo_layout = QHBoxLayout()
        delete_button = QPushButton("Delete selected points")
        delete_button.clicked.connect(self._delete_points)
        self.undo_button = QPushButton("Undo")
        self.undo_button.setEnabled(False)
        self.undo_button.clicked.connect(self._undo_delete_points)
        delete_undo_layout.addWidget(delete_button)
        delete_undo_layout.addWidget(self.undo_button)

        main_layout = QVBoxLayout()
        main_layout.addLayout(button_layout)
        main_layout.addLayout(delete_undo_layout)
        main_layout.addWidget(label)
        main_layout.addWidget(self._table_widget)
        self.setLayout(main_layout)
        self.setMinimumHeight(300)

        # Selection behavior
        self._table_widget.setStyleSheet("""
            QTableWidget::item:selected {
                border: 2px solid cyan;
            }
        """)

        self._table_widget.verticalHeader().setStyleSheet("""
            QHeaderView::section {
                background-color: rgb(40,40,40);       /* normal */
                color: white;
                padding: 4px;
                border: 1px solid #555;
            }

            QHeaderView::section:selected {            /* when the row is selected */
                background-color: cyan;
                color: black;
            }

            QHeaderView::section:pressed {
                background-color: cyan;
                color: black;
            }
        """)

        self._table_widget.setSelectionMode(
            QAbstractItemView.ExtendedSelection
        )
        self._table_widget.setSelectionBehavior(QAbstractItemView.SelectRows)

        self._click_filter = ClickToSingleSelectFilter(self._table_widget)
        self._table_widget.viewport().installEventFilter(self._click_filter)

        delegate = NoSelectionHighlightDelegate(self._table_widget)
        self._table_widget.setItemDelegate(delegate)

    def refresh(self):
        
        if self._layer is not None: 
            self._set_data()

            if self._sync_table_with_layer not in self._layer.events.data.callbacks:
                self._layer.events.data.connect(self._sync_table_with_layer)

            if not self._selection_connected:
                self._layer.selected_data.events.items_changed.connect(
                    self._update_selection
            )
            self._selection_connected = True

    def _selection_changed(self, _selected, _deselected):
        rows = [
            index.row()
            for index in self._table_widget.selectionModel().selectedRows()
        ]
        self._layer.selected_data = rows

    def _set_data(self, column_index: int | None = None) -> None:
        """Set the content of the table from the layer's properties."""

        if self._layer is None:
            return

        props = self._layer.properties

        # Update coordinate properties
        props["x"] = self._layer.data[:, -1]
        props["y"] = self._layer.data[:, -2]

        if "z" in props:
            props["z"] = self._layer.data[:, -3]

        if "t" in props:
            props["t"] = self._layer.data[:, 0]

        # Create dataframe for optional sorting
        df = pd.DataFrame(props)

        if column_index is not None:
            selected_column = df.columns[column_index]
            df = df.sort_values(
                by=selected_column,
                ascending=self.ascending,
                ignore_index=True,
            )

        self._table_widget.clear()

        n_rows, n_cols = df.shape

        self._table_widget.setRowCount(n_rows)
        self._table_widget.setColumnCount(n_cols)

        for col_idx, column in enumerate(df.columns):
            self._table_widget.setHorizontalHeaderItem(
                col_idx, QTableWidgetItem(column)
            )

            for row_idx, value in enumerate(df[column]):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self._table_widget.setItem(row_idx, col_idx, item)

        self._table_widget.setItemDelegate(
            FloatDelegate(3, self._table_widget)
        )

    def _sync_table_with_layer(self, event):
        """Synchronize the table when points are added, changed, or removed."""

        if self._deleting_points:
            return
    
        if event.action == "removed":
            # Rebuild everything after deletion so IDs match indices
            self._set_data()
            return

        if event.action not in {"added", "changed"}:
            return

        indices = list(event.data_indices)

        # Make writable copies of all properties
        props = {
            key: np.array(values, copy=True)
            for key, values in self._layer.properties.items()
        }

        # Update coordinate columns from layer.data
        props["x"] = self._layer.data[:, -1]
        props["y"] = self._layer.data[:, -2]

        if "z" in props:
            props["z"] = self._layer.data[:, -3]

        if "t" in props:
            props["t"] = self._layer.data[:, 0]

        coord_keys = {"x", "y", "z", "t"}

        # Set non-coordinate, properties to NaN for affected points only
        for key, values in props.items():
            if key not in coord_keys:
                # Convert integer arrays to float so they can hold NaN
                if not np.issubdtype(values.dtype, np.floating):
                    values = values.astype(float)

                values[indices] = np.nan
                props[key] = values

        # Assign back to the layer and refresh the table
        self._layer.properties = props
        self._set_data()

    def _clicked_table(
        self, right: bool, ctrl: bool, index: QModelIndex
    ) -> None:
        """Center the viewer to clicked row. 
        The special selection behavior can be modified by the ctrl/meta key, to view
        multiple points simultaneously.

        Args:
            right (bool): right mouse click detected.
            ctrl (bool): ctrl/meta key was used.
            index (QModelIndex): index of the clicked row
        """
        row = index.row()
        spatial_columns = [c for c in ['z', 'y', 'x'] if c in self._layer.properties.keys()]
       
        spatial_coords = [
            self._layer.properties[col][row] for col in spatial_columns
        ]

        location = [c for c in spatial_coords]

        dims = ["Y", "X"]
        if 'z' in self._layer.properties:
            dims.insert(0, 'Z')
        if 't' in self._layer.properties:
            dims.insert(0, 'T')
            location.insert(0, int(self._layer.properties['t'][row]))
       
        self._viewer.dims.point = location

        corner_coordinates = self._layer.corner_pixels
        dims_displayed = self._viewer.dims.displayed
    
        # find corner pixels for the displayed axes
        x_dim = dims_displayed[-1]
        y_dim = dims_displayed[-2]
        _min_x = corner_coordinates[0][x_dim]
        _max_x = corner_coordinates[1][x_dim]
        _min_y = corner_coordinates[0][y_dim]
        _max_y = corner_coordinates[1][y_dim]

        # check whether the node location falls within the corner spatial range
        if not (
            (location[x_dim] > _min_x and location[x_dim] < _max_x)
            and (location[y_dim] > _min_y and location[y_dim] < _max_y)
        ):
            camera_center = self._viewer.camera.center

            # set the center y and x to the center of the node, by using the index
            # of the currently displayed dimensions
            self._viewer.camera.center = (
                camera_center[0],
                location[y_dim],
                # camera center is calculated in scaled coordinates, and the optional
                # labels layer is scaled by the layer.scale attribute
                location[x_dim],
            )

    def _update_selection(self, event=None):
        """Select the corresponding table rows when points are selected in napari."""

        if self._updating_selection:
            return

        self._updating_selection = True
        try:
            selected_points = copy.deepcopy(self._layer.selected_data)
            with QSignalBlocker(self._table_widget.selectionModel()):
                self._table_widget.clearSelection()
                self._select_rows(selected_points)

        finally:
            self._updating_selection = False

    def _select_rows(self, rows: list[int]) -> None:
        """Select exactly the given rows in the table."""

        selection_model = self._table_widget.selectionModel()
        model = self._table_widget.model()

        selection = QItemSelection()

        for row in sorted(rows):
            index = model.index(row, 0)
            selection.select(index, index)

        # Block table selection signals while updating 
        with QSignalBlocker(selection_model):
            selection_model.clearSelection()
            selection_model.select(
                selection,
                QItemSelectionModel.SelectionFlag.Select
                | QItemSelectionModel.SelectionFlag.Rows,
            )

        # Optionally scroll to the first selected row
        if rows:
            self._table_widget.scrollTo(
                model.index(sorted(rows)[0], 0)
            )

    def _delete_points(self) -> None:
        """Delete selected points and store enough information for one-step undo."""

        selected_rows = sorted(
            {index.row() for index in self._table_widget.selectedIndexes()}
        )
        if not selected_rows:
            return

        self._undo_info = [
            {"row": row, "point": self._layer.data[row].copy()}
            for row in selected_rows
        ]

        self._deleting_points = True
        try:
            self._layer.data = np.delete(
                self._layer.data,
                selected_rows,
                axis=0,
            )
        finally:
            self._deleting_points = False

        self._set_data()

        self.undo_button.setEnabled(True)


    def _undo_delete_points(self) -> None:
        """Undo the last point deletion."""

        if not self._undo_info:
            return

        data = self._layer.data

        self._deleting_points = True
        # Reinsert points in ascending row order
        for info in sorted(self._undo_info, key=lambda x: x["row"]):
            data = np.insert(data, info["row"], info["point"], axis=0)

        self._layer.data = data

        # Rebuild the table from the restored layer data
        self._set_data()

        self._deleting_points = False

        self._undo_info = None
        self.undo_button.setEnabled(False)

    def _sort_table(self, column_index: int) -> None:
        """Sorts the table in ascending or descending order

        Args:
            column_index (int): The index of the clicked column header
        """

        self.ascending = not self.ascending
        self._set_data(column_index)

    def _save_table(self) -> None:
        """Save table to csv file"""

        filename, _ = QFileDialog.getSaveFileName(
            self, "Save as csv", ".", "*.csv"
        )
        pd.DataFrame(self._layer.properties).to_csv(filename)

    def _copy_table(self) -> None:
        """Copy table to clipboard"""

        pd.DataFrame(self._layer.properties).to_clipboard()
