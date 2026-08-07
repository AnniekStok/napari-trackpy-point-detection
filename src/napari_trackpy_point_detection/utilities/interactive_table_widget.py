
import copy

import napari
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgba
from napari.utils import CyclicLabelColormap, DirectLabelColormap
from qtpy.QtCore import (
    QEvent,
    QItemSelection,
    QItemSelectionModel,
    QModelIndex,
    QObject,
    QSignalBlocker,
    Qt,
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
            self.parent()._center_point(
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
        self.df = pd.DataFrame()
        self.undo_df = pd.DataFrame()
        self._table_widget = CustomTableWidget()
        self._table_widget.selectionModel().selectionChanged.connect(
            self._selection_changed
        )
        self._updating_selection = False
        self._deleting_points = False
        self._selection_connected = False
        self._region_colormap = None  # colors the rows by region, if measured

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
        # Guard so the resulting layer ``selected_data`` change does not bounce back into
        # ``_update_selection`` (which clears + reselects the table). During a drag on the
        # row index that clearing resets the drag anchor and undoes the range selection.
        self._updating_selection = True
        try:
            self._layer.selected_data = rows
        finally:
            self._updating_selection = False

    def _set_data(self, column_index: int | None = None) -> None:
        """Set the content of the table from the layer's properties."""

        if self._layer is None:
            return

        if column_index is not None:
            selected_column = self.df.columns[column_index]
            self.df = self.df.sort_values(
                by=selected_column,
                ascending=self.ascending,
                ignore_index=False,
            )

        self._table_widget.clear()

        n_rows, n_cols = self.df.shape

        self._table_widget.setRowCount(n_rows)
        self._table_widget.setColumnCount(n_cols)

        row_colors = self._region_row_colors()

        for col_idx, column in enumerate(self.df.columns):
            self._table_widget.setHorizontalHeaderItem(
                col_idx, QTableWidgetItem(column)
            )

            for row_idx, value in enumerate(self.df[column]):
                item = QTableWidgetItem(str(value))
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)

                colors = row_colors[row_idx]
                if colors is not None:
                    background, foreground = colors
                    item.setBackground(background)
                    item.setForeground(foreground)

                self._table_widget.setItem(row_idx, col_idx, item)

        self._table_widget.setItemDelegate(
            FloatDelegate(3, self._table_widget)
        )

    def _region_row_colors(self) -> list[tuple[QColor, QColor] | None]:
        """Return the (background, text) color per row, from the regions colormap.

        Rows keep their default colors (None) when no regions were measured, and for
        points outside any region (label 0, which the colormap maps to transparent).
        """

        if self._region_colormap is None or "region" not in self.df.columns:
            return [None] * len(self.df)

        row_colors = []
        for label in self.df["region"]:
            if pd.isna(label):
                row_colors.append(None)
                continue

            red, green, blue, alpha = to_rgba(
                np.atleast_2d(self._region_colormap.map(int(label)))[0]
            )
            if alpha == 0:  # not inside any region
                row_colors.append(None)
                continue

            # Keep the text readable on both light and dark region colors.
            luminance = 0.299 * red + 0.587 * green + 0.114 * blue
            row_colors.append(
                (
                    QColor(int(red * 255), int(green * 255), int(blue * 255)),
                    QColor(Qt.black) if luminance > 0.5 else QColor(Qt.white),
                )
            )

        return row_colors

    def add_measurements(
        self,
        measurements: dict[str, np.ndarray],
        region_colormap: "CyclicLabelColormap | DirectLabelColormap | None" = None,
        drop: tuple[str, ...] = (),
    ) -> None:
        """Add (or replace) measurement columns for the points in the table.

        Args:
            measurements (dict[str, np.ndarray]): column name -> one value per point, in
                the order in which the points appear in the layer.
            region_colormap: colormap of the regions layer the 'region' column was
                measured in, used to color each row by its region.
            drop (tuple[str, ...]): columns to remove, e.g. a 'region' column that is no
                longer measured.
        """

        if self._layer is None or self.df.empty:
            return

        self._region_colormap = region_colormap
        self.df = self.df.drop(columns=list(drop), errors="ignore")

        for name, values in measurements.items():
            # The dataframe index labels are the positional indices of the points in the
            # layer, while the row order can differ from it (e.g. after sorting the
            # table), so label the values the same way and let pandas align them.
            self.df[name] = pd.Series(np.asarray(values), index=range(len(values)))

        self._set_data()

    def measurement_column(self, name: str) -> np.ndarray | None:
        """Return column ``name`` in the order of the points in the layer, with NaN for
        points the table has no value for, or None if the column does not exist."""

        if self._layer is None or name not in self.df.columns:
            return None

        return self.df[name].reindex(range(len(self._layer.data))).to_numpy()

    def _sync_table_with_layer(self, event):
        """Synchronize the table when points are added, changed, or removed."""

        if self._deleting_points or event.action not in {"removed", "added", "changed"}:
            return

        if event.action == "removed":
            indices = list(event.data_indices)
            self.df = self.df.drop(index = indices)
            self.df = self.df.reset_index(drop = True)
            to_select = []

        elif event.action == "added":
            index = self.df.index.max() + 1
            self.df.loc[index] = np.nan
            if "z" in self.df.columns:
                self.df.loc[index, "z"] = self._layer.data[index, -3]
            if "t" in self.df.columns:
                self.df.loc[index, "t"] = self._layer.data[index, 0]
            self.df.loc[index, "y"] = self._layer.data[index, -2]
            self.df.loc[index, "x"] = self._layer.data[index, -1]
            to_select = [index]

        elif event.action == "changed":
            indices = list(event.data_indices)
            props = {
                key: np.array(values, copy=True)
                for key, values in self.df.items()
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
            self.df = pd.DataFrame(props)
            to_select = indices

        self._set_data()
        self._layer.selected_data = to_select
        self._undo_info = None
        self.undo_button.setEnabled(False)


    def _center_point(
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

        if self._layer is None:
            return

        row = index.row()
        spatial_columns = [c for c in ['z', 'y', 'x'] if c in self.df]

        # Access by positional row (``.iloc``) rather than by index label: the table shows
        # the dataframe in row order, which need not match the index labels (e.g. after a
        # sort, or if the dataframe carries non-contiguous labels).
        location = [
            self.df[col].iloc[row] for col in spatial_columns
        ]

        if 't' in self.df:
            location.insert(0, int(self.df['t'].iloc[row]))

        # ``self.df`` stores the point coordinates in layer (data) space, while
        # ``dims.point`` and ``camera.center`` are expressed in world coordinates.
        world_location = self._layer.data_to_world(location)

        # Layer dimensions are right-aligned with the world dimensions, so only fill in
        # the trailing axes and leave any leading viewer-only dimension untouched.
        point = list(self._viewer.dims.point)
        point[-len(world_location):] = world_location
        self._viewer.dims.point = point

        # Center the main viewer and each orthogonal view on the point when it is out of
        # view there.
        corner_coordinates = self._layer.corner_pixels

        # ``dims.displayed`` are world axes, while ``corner_pixels`` and ``data_location``
        # are indexed by layer axes, which are right-aligned with the world axes.
        offset = self._viewer.dims.ndim - self._layer.ndim
        x_dim = self._viewer.dims.displayed[-1]
        y_dim = self._viewer.dims.displayed[-2]

        # find corner pixels for the displayed axes
        _min_x = corner_coordinates[0][x_dim - offset]
        _max_x = corner_coordinates[1][x_dim - offset]
        _min_y = corner_coordinates[0][y_dim - offset]
        _max_y = corner_coordinates[1][y_dim - offset]

        # check whether the point falls within the corner spatial range
        if not (
            (
                location[x_dim - offset] > _min_x
                and location[x_dim - offset] < _max_x
            )
            and (
                location[y_dim - offset] > _min_y
                and location[y_dim - offset] < _max_y
            )
        ):
            camera_center = list(self._viewer.camera.center)

            # The camera center is in world coordinates and follows the displayed axes, so
            # set its y and x to the point, by using the index of the currently displayed
            # dimensions.
            camera_center[-2] = point[y_dim]
            camera_center[-1] = point[x_dim]
            self._viewer.camera.center = tuple(camera_center)

    def _update_selection(self, event=None):
        """Select the corresponding table 
        rows when points are selected in napari."""

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

            self.undo_df = copy.deepcopy(self.df)
            self.df = self.df.drop(index = selected_rows)
            self.df = self.df.reset_index(drop = True)

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
        rows_to_select = []
        for info in sorted(self._undo_info, key=lambda x: x["row"]):
            data = np.insert(data, info["row"], info["point"], axis=0)
            rows_to_select.append(info['row'])

        self.df = self.undo_df
        self._layer.data = data

        # Rebuild the table from the restored layer data
        self._set_data()

        # Select the restored data
        self._layer.selected_data = rows_to_select
        self._deleting_points = False

        # disable undo since the table is now altered by the layer
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
        pd.DataFrame(self.df).to_csv(filename)

    def _copy_table(self) -> None:
        """Copy table to clipboard"""

        pd.DataFrame(self.df).to_clipboard()
