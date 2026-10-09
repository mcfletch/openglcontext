"""``oglc-x3d-volume``: the X3D volume scene, its generated scans and its keys"""
import os

import numpy as np
import pytest

from OpenGLContext.bin import x3d_volume
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import volumestyles
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context

#: A smaller scan than the demo's, for the tests of its arithmetic.
SHAPE = (24, 48, 48)


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    found = x3d_volume.VolumeScene(str(tmp_path_factory.mktemp('volume')))
    assert background.wait_for_idle(20.0)
    return found


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_scans_and_images_it_names_are_written_beside_it(demo):
    assert {'x3d_volume.x3d', 'ammonite.nrrd', 'ammonite_segments.nrrd',
            'ammonite_transfer.png', 'marble_base.png', 'steel_normal.png',
            'sandstone_mr.png'} <= set(os.listdir(demo.directory))


def test_each_specimen_has_its_scan(demo):
    for name in ('Study', 'Sections', 'Surfaces'):
        found = volumestyles.plan(demo.node(name))
        assert found is not None, name
    assert volumestyles.plan(demo.node('Sections')).segmented
    assert volumestyles.plan(demo.node('Surfaces')).mode == 'isosurface'


def test_the_scan_holds_every_material_at_its_density():
    voxels, labels = x3d_volume.ammonite()
    assert voxels.shape == labels.shape == x3d_volume.SHAPE
    def median(name):
        found = voxels[labels == x3d_volume.LABELS[name]]
        assert len(found), name
        return np.median(found) / 255.0
    # The thick parts read at their density; the thin septa and siphuncle
    # less, spread over the voxels beside them as a scanner spreads them.
    assert median('wall') == pytest.approx(x3d_volume.DENSITY['wall'], abs=0.2)
    assert median('sediment') == pytest.approx(x3d_volume.DENSITY['sediment'], abs=0.1)
    assert median('wall') > median('septum') > median('siphuncle') > median('air')
    assert median('air') < 0.04


def test_the_scan_is_the_same_each_time():
    first, _labels = x3d_volume.ammonite(SHAPE)
    again, _labels = x3d_volume.ammonite(SHAPE)
    assert np.array_equal(first, again)


def test_blurring_keeps_a_constant_and_spreads_a_point():
    assert np.allclose(x3d_volume.blurred(np.full((4, 5, 6), 3.0), 1.0), 3.0)
    point = np.zeros((5, 5, 5))
    point[2, 2, 2] = 1.0
    spread = x3d_volume.blurred(point, 1.0)
    assert spread.sum() == pytest.approx(1.0)
    assert spread[2, 2, 2] < 1.0 and spread[2, 2, 3] > 0.0


def test_the_transfer_function_hides_the_sediment_and_shows_the_shell():
    table = x3d_volume.transfer_function()
    assert table.shape == (1, 256, 4)
    at = lambda density: table[0, int(density * 255)]  # noqa: E731 a lookup
    assert at(x3d_volume.DENSITY['sediment'])[3] == 0
    assert at(x3d_volume.DENSITY['wall'])[3] > 200


@pytest.mark.parametrize('key', sorted(x3d_volume.STYLES))
def test_each_style_key_gives_the_left_specimen_that_style(demo, key):
    said = demo.press(key)
    assert x3d_volume.STYLES[key] in said
    assert volumestyles.plan(demo.node('Study')) is not None


def test_s_hides_and_shows_the_sediment(demo):
    assert demo.press('s') == 'sediment hidden'
    assert not demo.node('Sections').segmentEnabled[x3d_volume.LABELS['sediment']]
    assert demo.press('s') == 'sediment shown'


def test_i_steps_the_inner_surface(demo):
    first = demo.node('Surfaces').surfaceValues[0]
    said = demo.press('i')
    assert demo.node('Surfaces').surfaceValues[0] != first
    assert said.startswith('inner surface at')
    assert demo.press('x') == ''


def test_the_specimens_are_drawn(demo):
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    with scene_context(demo.scene, size=(160, 90),
                       environment={'OPENGLCONTEXT_RENDERER': 'pbr'}) as context:
        for _ in range(3):
            background.wait_for_idle(20.0)
            context.renderQueue.run()
            context.OnDraw(force=1)
        image = drawn_image(context).astype(int)
    # The shells are lighter than the dark wall behind them.
    band = image[25:50]
    for left, right in ((15, 45), (65, 95), (115, 145)):
        assert band[:, left:right].max() > 150, (left, right)


def test_every_volume_rendering_node_is_the_engines(demo):
    """No VolumeRendering node is listed among the problems as not drawn"""
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.x3d import prototypes  # noqa: PLC0415 kept with its use
    component = {name for name, cls in x3d.CONCRETE_NODES.items()
                 if cls.COMPONENT[0] == 'VolumeRendering'}
    assert len(component) == 13
    assert component <= set(prototypes())
    unread = [problem for problem in demo.scene.problems if 'Volume' in str(problem)]
    assert not unread
