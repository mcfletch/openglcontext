"""The Geospatial valley `tests/x3d_geospatial.py` opens

`x3d_geospatial.x3d` is written with its four tiles and their maps, read by
the engine's loader and drawn through both renderers: the GeoLOD reads its
tiles from the first viewpoint, the viewer is sensed where that viewpoint
says, and the valley is drawn under the sky.
"""
import os

import numpy as np
import pytest

from OpenGLContext.bin import x3d_geospatial_demo
from OpenGLContext.loaders import background
from OpenGLContext.testing.glcontext import profile_unavailable


@pytest.fixture(scope='module')
def directory(tmp_path_factory):
    return str(tmp_path_factory.mktemp('x3d-geospatial'))


def test_the_document_and_its_files_are_written(directory):
    path = x3d_geospatial_demo.prepare(directory)
    assert os.path.basename(path) == 'x3d_geospatial.x3d'
    for name in ('tile00.x3d', 'tile11.x3d', 'valley_colour.png', 'tile01_normal.png',
                 'plaster.png'):
        assert os.path.exists(os.path.join(directory, name)), name


def test_the_valley_lies_between_its_floor_and_its_peaks():
    latitude, longitude = np.meshgrid(np.linspace(46.53, 46.57, 40),
                                      np.linspace(7.95, 8.01, 40), indexing='ij')
    found = x3d_geospatial_demo.heights(latitude, longitude)
    assert 990.0 < found.min() < 1020.0
    assert 2000.0 < found.max() < 2800.0


def test_every_hut_stands_on_the_valley_floor():
    huts = np.array(x3d_geospatial_demo.HUTS)
    assert (x3d_geospatial_demo.heights(huts[:, 0], huts[:, 1]) < 1030.0).all()


def test_the_colour_map_is_an_image_of_the_ground():
    ground = np.linspace(1000.0, 2700.0, 64)[None, :].repeat(16, axis=0)
    image = x3d_geospatial_demo.colour_map(ground)
    assert image.shape == (16, 64, 3) and image.dtype == np.uint8
    assert image[:, -1].mean() > image[:, 0].mean()        # snow is brighter than meadow


def test_each_viewpoint_has_the_documents_speed_factor(directory):
    showcase = x3d_geospatial_demo.Showcase(directory)
    views = [node for node in showcase.scene.children
             if type(node).__name__ == 'GeoViewpoint']
    assert [view.speedFactor for view in views] == [pytest.approx(0.1)] * 3


def test_nothing_is_said_of_a_touch_before_one(directory):
    assert x3d_geospatial_demo.Showcase(directory).said_of_touch() == ''


def test_the_keys_answer(directory):
    showcase = x3d_geospatial_demo.Showcase(directory)
    assert 'not been sensed' in showcase.press('g')
    assert showcase.press('w').startswith('wrote written.x3d')
    assert showcase.press('?') == ''


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_the_valley_is_drawn_and_placed(directory, renderer):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    showcase = x3d_geospatial_demo.Showcase(directory)
    with scene_context(showcase.scene, size=(160, 90), renderer=renderer) as context:
        for _ in range(3):
            drawn_image(context)
        assert background.wait_for_idle(20.0)
        image = drawn_image(context).astype(int)
        step = context.movementManager.STEPDISTANCE
    lod = next(node for node in showcase.scene.children
               if type(node).__name__ == 'Group').children[1]
    assert lod.level_changed == 1
    assert showcase.where() == pytest.approx((46.533, 7.9805, 1450.0), abs=1e-9)
    assert showcase.press('g') == '46.53300 N 7.98050 E, 1450 m'
    # 1450 m above the ellipsoid: 146 times the speed factor, a quarter unit each.
    assert step == pytest.approx(0.25 * 146.0 * x3d_geospatial_demo.SPEED_FACTOR, rel=1e-3)
    sky, ground = image[2, 80], image[80, 80]
    assert sky[2] > sky[0] and sky[2] > 150                 # blue above
    assert ground[1] > ground[2]                            # meadow below


def test_a_touch_is_said_as_latitude_longitude_and_height(directory):
    showcase = x3d_geospatial_demo.Showcase(directory)
    showcase.scene.getDEF('Touch').hitGeoCoord_changed = (46.545, 7.986, 1004.0)
    assert showcase.said_of_touch() == 'the ground at 46.54500 N 7.98600 E, 1004 m'
