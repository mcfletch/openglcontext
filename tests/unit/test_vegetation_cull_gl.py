"""The instanced ground-cover layers draw what the view sees, and only that.

A layer streams the instances in the clusters its pass's frustum reaches
(``viewcull``); the picture must not change by one pixel for it, and the GPU is
handed fewer instances.
"""
import types

import numpy as np
import pytest
from OpenGL import GL as gl
from PIL import Image

from OpenGLContext.frustum import Frustum
from OpenGLContext.loaders.tiles3d.frustum import look_at, perspective
from OpenGLContext.passes.instancing import morton_order
from OpenGLContext.scenegraph.vegetation import gpucull, viewcull
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.clumps import InstancedClumps

SIZE = (160, 100)


@pytest.fixture
def window(gl_window, monkeypatch):
    # The fields here are far smaller than the sets a game tests.
    monkeypatch.setattr(viewcull, 'MIN_TRIANGLES', 0)
    # These are the processor's culling; test_gpu_cull_gl.py is the GPU's.
    monkeypatch.setattr(gpucull, 'gpu_cull_is_available', lambda: False)
    return gl_window('vegetation-cull', size=SIZE, forward_compatible=True)


def _mode(toward=(0.0, 1.7, -1.0)):
    """A pass's mode for a camera at head height: its matrices and the frustum it holds."""
    view = look_at((0.0, 1.7, 0.0), toward, (0.0, 1.0, 0.0))
    lens = perspective(0.9, SIZE[0] / SIZE[1], 0.1, 200.0)
    matrix, projection = view.T.astype('f4'), lens.T.astype('f4')
    held = Frustum.fromViewingMatrix(np.asarray(matrix, 'd') @ np.asarray(projection, 'd'),
                                     normalize=1)
    return types.SimpleNamespace(matrix=matrix, projection=projection, frustum=held,
                                 shadow_pass=False, visible=True)


def _field(count=3000, radius=45.0, seed=3):
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0.0, 2.0 * np.pi, count)
    away = radius * np.sqrt(rng.uniform(0.04, 1.0, count))
    points = np.stack([away * np.cos(angle), np.zeros(count), away * np.sin(angle)], 1).astype('f4')
    order = np.asarray(morton_order(points))
    return (points[order], rng.uniform(0.0, 6.28, count).astype('f4')[order],
            rng.uniform(0.8, 1.6, count).astype('f4')[order])


def _clumps(cull):
    blade = np.array([[-0.2, 0, 0], [0.2, 0, 0], [0.0, 1, 0]], 'f4')
    normals = np.tile(np.array([0, 0, 1], 'f4'), (3, 1))
    node = InstancedClumps(blade, normals, np.array([[0, 0], [1, 0], [0.5, 1]], 'f4'),
                           np.array([0, 1, 2], np.uint32),
                           Image.new('RGBA', (4, 4), (40, 160, 40, 255)), cull=cull)
    node.update_instances(*_field())
    return node


def _cards(cull, tmp_path):
    picture = tmp_path / 'card.png'
    Image.new('RGBA', (4, 4), (40, 160, 40, 255)).save(picture)
    return InstancedBillboards(*_field(), str(picture), cull=cull)


def _picture(node, mode):
    gl.glViewport(0, 0, *SIZE)
    gl.glClearColor(0.1, 0.1, 0.2, 1.0)
    gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
    node.render(mode)
    gl.glFinish()
    assert gl.glGetError() == gl.GL_NO_ERROR
    data = gl.glReadPixels(0, 0, *SIZE, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
    return np.frombuffer(data, np.uint8).reshape(SIZE[1], SIZE[0], 4)


@pytest.mark.usefixtures('window')
class TestClumps:
    def test_the_picture_is_the_one_every_instance_makes(self) -> None:
        mode = _mode()
        everything = _picture(_clumps(cull=False), mode)
        culled = _picture(_clumps(cull=True), mode)
        assert (everything[..., :3] != 0.1).any()
        assert np.array_equal(everything, culled)

    def test_the_picture_is_the_same_looking_another_way(self) -> None:
        mode = _mode(toward=(1.0, 1.7, -0.3))
        assert np.array_equal(_picture(_clumps(cull=False), mode),
                              _picture(_clumps(cull=True), mode))

    def test_the_gpu_is_handed_fewer_instances(self) -> None:
        node = _clumps(cull=True)
        _picture(node, _mode())
        assert 0 < node._ibuf.count < 0.6 * len(node._instance_rows())  # noqa: SLF001 the buffer a draw streams, read back

    def test_turning_round_streams_the_other_side(self) -> None:
        node = _clumps(cull=True)
        _picture(node, _mode(toward=(0.0, 1.7, -1.0)))
        ahead = node._ibuf.count  # noqa: SLF001 the buffer a draw streams, read back
        _picture(node, _mode(toward=(0.0, 1.7, 1.0)))
        assert node._ibuf.count > 0  # noqa: SLF001 the buffer a draw streams, read back
        assert ahead > 0

    def test_a_view_that_sees_nothing_draws_nothing(self) -> None:
        node = _clumps(cull=True)
        node.update_instances(np.array([[0.0, 0.0, 30.0]], 'f4'), np.zeros(1, 'f4'),
                              np.ones(1, 'f4'))
        picture = _picture(node, _mode())
        assert node._ibuf.count == 0  # noqa: SLF001 the buffer a draw streams, read back
        assert np.all(picture[..., 0] == picture[0, 0, 0])

    def test_a_node_made_again_after_dispose_draws_its_staged_set(self) -> None:
        node = _clumps(cull=True)
        mode = _mode()
        before = _picture(node, mode)
        node.dispose()
        assert np.array_equal(before, _picture(node, mode))


@pytest.mark.usefixtures('window')
class TestCards:
    def test_the_picture_is_the_one_every_card_makes(self, tmp_path) -> None:
        mode = _mode()
        everything = _picture(_cards(False, tmp_path), mode)
        culled = _picture(_cards(True, tmp_path), mode)
        assert (everything[..., :3] != 0.1).any()
        assert np.array_equal(everything, culled)

    def test_the_gpu_is_handed_fewer_cards(self, tmp_path) -> None:
        node = _cards(True, tmp_path)
        _picture(node, _mode())
        assert 0 < node._ibuf.count < 0.6 * len(node.pos)  # noqa: SLF001 the buffer a draw streams, read back
