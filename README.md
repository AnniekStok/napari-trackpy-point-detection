# napari-trackpy-point-detection

[![License BSD-3](https://img.shields.io/pypi/l/napari-trackpy-point-detection.svg?color=green)](https://github.com/AnniekStok/napari-trackpy-point-detection/raw/main/LICENSE)
[![PyPI](https://img.shields.io/pypi/v/napari-trackpy-point-detection.svg?color=green)](https://pypi.org/project/napari-trackpy-point-detection)
[![Python Version](https://img.shields.io/pypi/pyversions/napari-trackpy-point-detection.svg?color=green)](https://python.org)
[![tests](https://github.com/AnniekStok/napari-trackpy-point-detection/workflows/tests/badge.svg)](https://github.com/AnniekStok/napari-trackpy-point-detection/actions)
[![codecov](https://codecov.io/gh/AnniekStok/napari-trackpy-point-detection/branch/main/graph/badge.svg)](https://codecov.io/gh/AnniekStok/napari-trackpy-point-detection)
[![napari hub](https://img.shields.io/endpoint?url=https://api.napari-hub.org/shields/napari-trackpy-point-detection)](https://napari-hub.org/plugins/napari-trackpy-point-detection)

A Napari plugin for detecting objects in 2D, 2D + time, 3D, and 3D + time, using the locate function from [TrackPy](https://pypi.org/project/trackpy/), with helper tools to visualize and correct the detections manually.

----------------------------------

This [napari] plugin was generated with [Cookiecutter] using [@napari]'s [cookiecutter-napari-plugin] template.

## Installation

You can install `napari-trackpy-point-detection` via [pip]:

To install latest development version :

    pip install git+https://github.com/AnniekStok/napari-trackpy-point-detection.git

## Usage

Choose an estimated diameter in xy (and optionally z) (this must be an odd integer, in pixels) and an estimated distance between objects. When your data is 3D but you leave the 'Use Z dimension' checkbox unticked, the third dimension will be treated as time, meaning that objects are detected frame by frame. The 'Intensity percentile threshold' parameter can be used to filter out dimmer objects that are below set intensity percentile. 
Detected points are added to an interactive table that allows selection and deletion of points. Missing points can be added via the 'add' button on the Points layer. Optionally, you can display the orthogonal views, or link the Points layer to the Image layer and display a (clipping) plane to help evaluate the detections. Results can be copied to the clipboard or exported to CSV. 

![](instructions/trackpy_point_detection.gif)

## Contributing

Contributions are very welcome. Tests can be run with [tox], please ensure
the coverage at least stays the same before you submit a pull request.

## License

Distributed under the terms of the [BSD-3] license,
"napari-trackpy-point-detection" is free and open source software

## Issues

If you encounter any problems, please [file an issue] along with a detailed description.

[napari]: https://github.com/napari/napari
[Cookiecutter]: https://github.com/audreyr/cookiecutter
[@napari]: https://github.com/napari
[MIT]: http://opensource.org/licenses/MIT
[BSD-3]: http://opensource.org/licenses/BSD-3-Clause
[GNU GPL v3.0]: http://www.gnu.org/licenses/gpl-3.0.txt
[GNU LGPL v3.0]: http://www.gnu.org/licenses/lgpl-3.0.txt
[Apache Software License 2.0]: http://www.apache.org/licenses/LICENSE-2.0
[Mozilla Public License 2.0]: https://www.mozilla.org/media/MPL/2.0/index.txt
[cookiecutter-napari-plugin]: https://github.com/napari/cookiecutter-napari-plugin

[file an issue]: https://github.com/AnniekStok/napari-trackpy-point-detection/issues

[napari]: https://github.com/napari/napari
[tox]: https://tox.readtheinstructions.io/en/latest/
[pip]: https://pypi.org/project/pip/
[PyPI]: https://pypi.org/

## References
Allan, D. B., Caswell, T., Keim, N. C., van der Wel, C. M.& Verweij, R. W. (2025). soft-matter/trackpy: v0.7 (Version v0.7) [Computer software]. Zenodo. https://doi.org/10.5281/zenodo.16089574
