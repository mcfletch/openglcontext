"""Instanced vegetation culled by the GPU: a compute pass keeps the instances in the view.

The pass reads the staged rows, writes the ones whose box reaches into the view
and the disc to the buffer the draw takes its instance attributes from, and
counts them in an indirect draw command. Nothing comes back to the processor.
These tests read the buffers back to hold it to the per-instance arithmetic
``viewcull`` does for clusters, and draw the layers to hold the picture to the
one every instance makes.
"""
import types

import numpy as np
import pytest
from OpenGL import GL as gl

from OpenGLContext.frustum import Frustum
from OpenGLContext.loaders.tiles3d.frustum import look_at, perspective
from OpenGLContext.scenegraph.instancedgl import InstanceBuffer, instance_rows
from OpenGLContext.scenegraph.vegetation import gpucull, viewcull
from OpenGLContext.scenegraph.vegetation.gpucull import GPUCulledRows
from tests.unit.test_vegetation_cull_gl import SIZE, _cards, _clumps, _mode, _picture

REACH, RISE, DROP = 0.5, 2.0, 0.25


@pytest.fixture
def window(gl_window):
    context = gl_window('gpu-cull', size=SIZE, forward_compatible=True)
    if not gpucull.gpu_cull_is_available():
        pytest.skip('this driver cannot run compute shaders or indirect draws')
    return context


def _view(eye=(0.0, 1.7, 0.0), toward=(0.0, 1.7, -1.0), fovy=1.0, aspect=1.6, copies=0):
    view = look_at(eye, toward, (0.0, 1.0, 0.0))
    lens = perspective(fovy, aspect, 0.1, 200.0)
    modelproj = (lens @ view).T.copy()
    return types.SimpleNamespace(frustum=Frustum.fromViewingMatrix(modelproj, normalize=1),
                                 viewCopies=copies)


def _rows(count=4000, radius=60.0, seed=11):
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0.0, 2.0 * np.pi, count)
    away = radius * np.sqrt(rng.uniform(0.0, 1.0, count))
    points = np.stack([away * np.cos(angle), rng.uniform(0.0, 3.0, count),
                       away * np.sin(angle)], 1)
    return instance_rows(points, rng.uniform(0.0, 6.28, count), rng.uniform(0.5, 2.0, count),
                         rng.uniform(0.0, 1.0, count))


def _expected(rows, mode=None, disc=None):
    """The rows the arithmetic of one instance's box keeps, in the order they are staged."""
    scale = np.abs(rows[:, 4]).astype('d')
    base = rows[:, :3].astype('d')
    keep = np.ones(len(rows), bool)
    if disc is not None:
        keep &= np.hypot(base[:, 0] - disc[0], base[:, 2] - disc[1]) - REACH * scale <= disc[2]
    if mode is not None:
        planes = np.asarray(mode.frustum.planes, 'd')
        centre = base + np.stack([0.0 * scale, 0.5 * (RISE - DROP) * scale, 0.0 * scale], 1)
        half = np.stack([REACH * scale, 0.5 * (RISE + DROP) * scale, REACH * scale], 1)
        front = centre @ planes[:, :3].T + planes[:, 3] + half @ np.abs(planes[:, :3]).T
        keep &= (front >= 0.0).all(axis=1)
    return rows[keep]


def _culler(rows, **named):
    buffer = InstanceBuffer()
    culler = GPUCulledRows(buffer, reach=REACH, rise=RISE, drop=DROP, triangles=2, **named)
    culler.stage(rows)
    return culler


def _same_rows(found, wanted):
    return sorted(map(tuple, np.round(found, 5))) == sorted(map(tuple, np.round(wanted, 5)))


@pytest.mark.usefixtures('window')
class TestWhatIsKept:
    def test_the_instances_in_the_view_are_kept(self) -> None:
        rows, mode = _rows(), _view()
        culler = _culler(rows)
        culler.show(mode)
        wanted = _expected(rows, mode)
        assert 0 < len(wanted) < len(rows)
        assert _same_rows(culler.visible_rows(), wanted)

    def test_the_instances_in_the_disc_are_kept(self) -> None:
        rows = _rows()
        culler = _culler(rows)
        culler.show(types.SimpleNamespace(), (5.0, -3.0, 25.0))
        wanted = _expected(rows, disc=(5.0, -3.0, 25.0))
        assert 0 < len(wanted) < len(rows)
        assert _same_rows(culler.visible_rows(), wanted)

    def test_the_view_and_the_disc_together_keep_what_both_do(self) -> None:
        rows, mode = _rows(), _view(toward=(1.0, 1.7, -0.4))
        culler = _culler(rows)
        culler.show(mode, (0.0, 0.0, 30.0))
        wanted = _expected(rows, mode, (0.0, 0.0, 30.0))
        assert 0 < len(wanted) < len(_expected(rows, mode))
        assert _same_rows(culler.visible_rows(), wanted)

    def test_without_a_frustum_or_a_disc_every_instance_is_kept(self) -> None:
        rows = _rows()
        culler = _culler(rows)
        assert culler.show(types.SimpleNamespace()) == len(rows)
        assert _same_rows(culler.visible_rows(), rows)

    def test_a_crown_that_reaches_into_the_view_keeps_its_instance(self) -> None:
        mode = _view(fovy=1.0, aspect=1.0)
        outside = 0.5 * REACH * 4.0
        edge = 20.0 * np.tan(0.5) + outside / np.cos(0.5)
        rows = instance_rows([[edge, 0.0, -20.0]], [0.0], [4.0])
        culler = _culler(rows)
        culler.show(mode)
        assert len(culler.visible_rows()) == 1

    def test_the_view_turned_round_keeps_the_other_side(self) -> None:
        rows = _rows()
        culler = _culler(rows)
        for toward in ((0.0, 1.7, -1.0), (0.0, 1.7, 1.0)):
            mode = _view(toward=toward)
            culler.show(mode)
            assert _same_rows(culler.visible_rows(), _expected(rows, mode))

    def test_a_view_that_sees_nothing_keeps_nothing(self) -> None:
        rows = instance_rows([[0.0, 0.0, 50.0], [3.0, 0.0, 60.0]], [0.0, 0.0], [1.0, 1.0])
        culler = _culler(rows)
        culler.show(_view())
        assert len(culler.visible_rows()) == 0

    def test_an_empty_set_draws_nothing(self) -> None:
        culler = _culler(np.zeros((0, 6), 'f4'))
        assert culler.show(_view()) == 0
        assert len(culler.visible_rows()) == 0


@pytest.mark.usefixtures('window')
class TestTheDrawCommand:
    def test_it_counts_the_instances_kept(self) -> None:
        rows, mode = _rows(), _view()
        culler = _culler(rows)
        culler.show(mode)
        assert culler.visible_count() == len(_expected(rows, mode))

    def test_it_counts_each_instance_once_for_each_view_it_is_sent_to(self) -> None:
        rows = _rows()
        culler = _culler(rows)
        culler.show(_view(copies=3))
        assert culler.visible_count() == 3 * len(rows)

    def test_a_second_pass_counts_afresh(self) -> None:
        rows, mode = _rows(), _view()
        culler = _culler(rows)
        culler.show(mode)
        culler.show(mode)
        assert culler.visible_count() == len(_expected(rows, mode))

    def test_staging_again_replaces_the_set(self) -> None:
        mode = _view()
        culler = _culler(_rows(seed=1))
        culler.show(mode)
        rows = _rows(count=900, seed=2)
        culler.stage(rows)
        culler.show(mode)
        assert _same_rows(culler.visible_rows(), _expected(rows, mode))

    def test_a_set_larger_than_the_one_before_is_all_kept(self) -> None:
        culler = _culler(_rows(count=100, seed=1))
        culler.show(types.SimpleNamespace())
        rows = _rows(count=6000, seed=2)
        culler.stage(rows)
        assert culler.show(types.SimpleNamespace()) == len(rows)
        assert _same_rows(culler.visible_rows(), rows)

    def test_the_pass_leaves_the_program_the_pass_drawing_had(self) -> None:
        before = int(gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM))
        culler = _culler(_rows())
        culler.show(_view())
        assert int(gl.glGetIntegerv(gl.GL_CURRENT_PROGRAM)) == before
        assert gl.glGetError() == gl.GL_NO_ERROR

    def test_culling_turned_off_keeps_every_instance(self) -> None:
        rows = _rows()
        culler = _culler(rows, enabled=False)
        culler.show(_view(), (0.0, 0.0, 1.0))
        assert culler.visible_count() == len(rows)


class TestWhenItIsUsed:
    def test_it_is_not_used_where_it_is_turned_off(self, monkeypatch) -> None:
        from OpenGLContext import renderoptions
        monkeypatch.setattr(renderoptions, 'env_flag_once', lambda name, default: False)
        assert not gpucull.gpu_cull_is_enabled()

    def test_the_culler_a_layer_is_given_is_the_cpus_where_there_is_no_compute(
            self, monkeypatch) -> None:
        monkeypatch.setattr(gpucull, 'gpu_cull_is_available', lambda: False)
        culler = gpucull.rows_culler(types.SimpleNamespace(count=0), reach=1.0, rise=1.0)
        assert isinstance(culler, viewcull.CulledRows)

    @pytest.mark.usefixtures('window')
    def test_the_culler_a_layer_is_given_is_the_gpus_where_there_is(self) -> None:
        culler = gpucull.rows_culler(InstanceBuffer(), reach=1.0, rise=1.0)
        assert isinstance(culler, GPUCulledRows)


@pytest.mark.usefixtures('window')
class TestTheLayersDrawn:
    """A layer culled on the GPU draws the picture every one of its instances makes."""

    def test_clumps_make_the_picture_every_instance_makes(self) -> None:
        mode = _mode()
        everything = _picture(_clumps(cull=False), mode)
        node = _clumps(cull=True)
        culled = _picture(node, mode)
        assert isinstance(node._visible, GPUCulledRows)  # noqa: SLF001 the culler a layer draws with
        assert (everything[..., :3] != 0.1).any()
        assert np.array_equal(everything, culled)

    def test_clumps_make_it_looking_another_way(self) -> None:
        mode = _mode(toward=(1.0, 1.7, -0.3))
        assert np.array_equal(_picture(_clumps(cull=False), mode),
                              _picture(_clumps(cull=True), mode))

    def test_cards_make_the_picture_every_card_makes(self, tmp_path) -> None:
        mode = _mode()
        everything = _picture(_cards(False, tmp_path), mode)
        node = _cards(True, tmp_path)
        culled = _picture(node, mode)
        assert isinstance(node._visible, GPUCulledRows)  # noqa: SLF001 the culler a layer draws with
        assert (everything[..., :3] != 0.1).any()
        assert np.array_equal(everything, culled)

    def test_the_gpu_is_handed_fewer_instances(self) -> None:
        node = _clumps(cull=True)
        _picture(node, _mode())
        assert 0 < node._visible.visible_count() < 0.6 * len(node._instance_rows())  # noqa: SLF001 the command a draw is issued from

    def test_a_view_that_sees_nothing_draws_nothing(self) -> None:
        node = _clumps(cull=True)
        node.update_instances(np.array([[0.0, 0.0, 30.0]], 'f4'), np.zeros(1, 'f4'),
                              np.ones(1, 'f4'))
        picture = _picture(node, _mode())
        assert node._visible.visible_count() == 0  # noqa: SLF001 the command a draw is issued from
        assert np.all(picture[..., 0] == picture[0, 0, 0])

    def test_a_disc_keeps_the_layer_to_the_plants_within_it(self) -> None:
        node = _clumps(cull=True)
        node.disc = (0.0, 0.0, 10.0)
        _picture(node, _mode())
        kept = node._visible.visible_rows()  # noqa: SLF001 the rows a draw is issued with
        assert len(kept) > 0
        assert np.hypot(kept[:, 0], kept[:, 2]).max() < 10.0 + 0.5 * kept[:, 4].max()

    def test_a_node_made_again_after_dispose_draws_its_staged_set(self) -> None:
        node = _clumps(cull=True)
        mode = _mode()
        before = _picture(node, mode)
        node.dispose()
        assert np.array_equal(before, _picture(node, mode))

