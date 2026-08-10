import dask.array as da
import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_rgba
from qtpy.QtGui import QBrush

from napari_trackpy_point_detection.utilities.interactive_table_widget import (
    InteractiveTableWidget,
)
from napari_trackpy_point_detection.utilities.measure_widget import (
    MeasureWidget,
)

# image where each voxel holds its own flat index, so measurements are easy to check
IMAGE = np.arange(4 * 20 * 20, dtype=np.int32).reshape(4, 20, 20)

# one point per region: label 3, label 7, and one outside any region
POINTS = pd.DataFrame(
    {"z": [1.0, 1.0, 1.0], "y": [2.0, 8.0, 15.0], "x": [2.0, 8.0, 15.0]}
)


def expected_intensities(image=IMAGE, scale=1):
    return [
        image[int(z * scale), int(y * scale), int(x * scale)]
        for z, y, x in zip(POINTS["z"], POINTS["y"], POINTS["x"], strict=False)
    ]


@pytest.fixture
def widgets(make_napari_viewer):
    """A viewer with an image, a points layer, and a table + measure widget on it."""

    viewer = make_napari_viewer()
    image = viewer.add_image(IMAGE, name="intensity")
    points = viewer.add_points(
        POINTS[["z", "y", "x"]].to_numpy(), name="points"
    )

    table = InteractiveTableWidget(points, viewer)
    table.df = POINTS.copy()
    table.refresh()

    measure = MeasureWidget(viewer, table)
    measure.refresh(image)

    return viewer, table, measure


@pytest.fixture
def regions(widgets):
    """A labels layer covering the first two points, selected as regions layer."""

    viewer, _, measure = widgets
    labels = np.zeros_like(IMAGE, dtype=np.uint8)
    labels[:, :5, :5] = 3
    labels[:, 5:12, 5:12] = 7
    layer = viewer.add_labels(labels, name="regions")

    measure.use_regions_checkbox.setChecked(True)
    measure._update_regions_layer("regions")

    return layer


def row_background(table, row):
    return table._table_widget.item(row, 0).background()


def has_default_background(table, row):
    return row_background(table, row).style() == QBrush().style()


def test_measure_adds_intensity_column(widgets):
    _, table, measure = widgets

    measure._measure()

    assert list(table.df["intensity"]) == expected_intensities()
    headers = [
        table._table_widget.horizontalHeaderItem(col).text()
        for col in range(table._table_widget.columnCount())
    ]
    assert "intensity" in headers


def test_measure_button_needs_points_and_intensity_layer(make_napari_viewer):
    viewer = make_napari_viewer()
    image = viewer.add_image(IMAGE, name="intensity")
    table = InteractiveTableWidget(None, viewer)
    measure = MeasureWidget(viewer, table)

    measure.refresh(image)
    assert not measure.measure_btn.isEnabled()  # no points layer yet

    table._layer = viewer.add_points(POINTS[["z", "y", "x"]].to_numpy())
    measure.refresh(image)
    assert measure.measure_btn.isEnabled()


def test_measure_takes_layer_scales_into_account(widgets):
    viewer, table, measure = widgets

    # twice as many voxels per world unit as the points layer
    upsampled = np.arange(8 * 40 * 40, dtype=np.int32).reshape(8, 40, 40)
    viewer.add_image(upsampled, scale=(0.5, 0.5, 0.5), name="upsampled")
    measure._update_intensity_layer("upsampled")

    measure._measure()

    assert list(table.df["intensity"]) == expected_intensities(
        upsampled, scale=2
    )


def test_measure_dask_image(widgets):
    viewer, table, measure = widgets
    viewer.add_image(da.from_array(IMAGE, chunks=(2, 10, 10)), name="dask")
    measure._update_intensity_layer("dask")

    measure._measure()

    assert list(table.df["intensity"]) == expected_intensities()


def test_measure_in_regions_adds_region_column(widgets, regions):
    _, table, measure = widgets

    measure._measure()

    assert list(table.df["region"]) == [3, 7, 0]


def test_rows_are_colored_by_region(widgets, regions):
    _, table, measure = widgets

    measure._measure()

    for row, label in enumerate([3, 7]):
        red, green, blue, _ = to_rgba(
            np.atleast_2d(regions.colormap.map(label))[0]
        )
        assert row_background(table, row).color().getRgb()[:3] == (
            int(red * 255),
            int(green * 255),
            int(blue * 255),
        )

    # the point outside any region keeps the default background
    assert has_default_background(table, 2)


def test_measuring_without_regions_drops_region_column(widgets, regions):
    _, table, measure = widgets
    measure._measure()

    measure.use_regions_checkbox.setChecked(False)
    measure._measure()

    assert "region" not in table.df.columns
    assert all(
        has_default_background(table, row)
        for row in range(table._table_widget.rowCount())
    )


def test_points_outside_regions_can_be_hidden(widgets, regions):
    _, table, measure = widgets
    measure._measure()

    measure.hide_points_checkbox.setChecked(True)
    measure._update_visibility()
    assert list(measure.points.shown) == [True, True, False]

    measure.hide_points_checkbox.setChecked(False)
    measure._update_visibility()
    assert list(measure.points.shown) == [True, True, True]


def test_measurements_stay_with_their_point_when_sorted(widgets, regions):
    _, table, measure = widgets
    measure._measure()

    # sort twice to toggle to descending, so the row order really changes
    column = table.df.columns.get_loc("y")
    table._sort_table(column)
    table._sort_table(column)

    assert list(table.df.index) == [2, 1, 0]
    measure._measure()
    assert list(table.df["region"]) == [0, 7, 3]
    assert list(table.df["intensity"]) == expected_intensities()[::-1]


def test_point_count_label_stays_up_to_date(widgets):
    _, table, _ = widgets
    assert table.point_count_label.text() == "Number of points: 3"

    table._table_widget.selectRow(0)
    table._delete_points()
    assert table.point_count_label.text() == "Number of points: 2"

    table._undo_delete_points()
    assert table.point_count_label.text() == "Number of points: 3"

    # a point added on the layer itself, e.g. in the viewer or an ortho view
    table._layer.data = np.vstack([table._layer.data, [[1.0, 5.0, 5.0]]])
    assert table.point_count_label.text() == "Number of points: 4"


def test_measurement_column_follows_the_layer_order(widgets, regions):
    _, table, measure = widgets
    measure._measure()

    column = table.df.columns.get_loc("y")
    table._sort_table(column)
    table._sort_table(column)

    assert list(table.measurement_column("region")) == [3, 7, 0]
    assert table.measurement_column("nonexistent") is None
