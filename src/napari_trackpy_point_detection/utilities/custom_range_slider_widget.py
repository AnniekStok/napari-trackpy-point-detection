import pandas as pd
from qtpy import QtCore
from qtpy.QtWidgets import QLabel, QVBoxLayout, QWidget
from superqt import QLabeledDoubleRangeSlider, QLabeledRangeSlider


class CustomRangeSliderWidget(QWidget):
    """implements superqt RangeSlider widget to select a range of values based on a pandas dataframe"""

    def __init__(
        self,
        df: pd.DataFrame,
        name: str,
        display_name: str,
        dtype: str,
        tip: str,
    ):
        super().__init__()

        self.name = name
        slider_layout = QVBoxLayout()
        if dtype == "float":
            self.range_slider = QLabeledDoubleRangeSlider(QtCore.Qt.Horizontal)
            self.min = round(df[name].min(), 2)
            self.max = round(df[name].max(), 2)
            self.span = self.max - self.min
            stepsize = round(self.span / 100, 2)
            self.range_slider.setRange(
                self.min - stepsize, self.max + stepsize
            )

        else:
            self.range_slider = QLabeledRangeSlider(QtCore.Qt.Horizontal)
            self.min = int(df[name].min())
            self.max = int(df[name].max())
            self.span = self.max - self.min
            stepsize = int(self.span / 100)
            self.range_slider.setRange(
                self.min - stepsize, self.max + stepsize
            )

        self.range_slider.setSingleStep(stepsize)
        self.range_slider.setTickInterval(stepsize)
        self.range_slider.setValue((self.min - stepsize, self.max + stepsize))
        self.range_slider.setEdgeLabelMode(0)

        self.label = QLabel(display_name)
        self.label.setToolTip(tip)
        self.label.setToolTipDuration(1000)

        slider_layout.addWidget(self.label)
        slider_layout.addWidget(self.range_slider)

        self.setLayout(slider_layout)
