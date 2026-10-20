"""Instanced rows streamed as the view sees them.

The arithmetic is NumPy over rows and the pass's own frustum, so these tests hold
it with no GL context; the layers that use it are drawn in
``test_vegetation_cull_gl.py``.
"""
import types

import numpy as np

from OpenGLContext.frustum import Frustum
from OpenGLContext.loaders.tiles3d.frustum import look_at, perspective
from OpenGLContext.passes.instancing import morton_order
from OpenGLContext.scenegraph.instancedgl import instance_rows
from OpenGLContext.scenegraph.vegetation.viewcull import (
    CLUSTER_ROWS, MARGIN_METRES, MIN_TRIANGLES, CulledRows,
)


def _view(eye=(0.0, 1.7, 0.0), toward=(0.0, 1.7, -1.0), fovy=1.0, aspect=1.6):
    """A pass's ``mode`` for a camera here, with the frustum the pass holds."""
    view = look_at(eye, toward, (0.0, 1.0, 0.0))
    lens = perspective(fovy, aspect, 0.1, 200.0)
    modelproj = (lens @ view).T.copy()
    return types.SimpleNamespace(frustum=Frustum.fromViewingMatrix(modelproj, normalize=1))


def _rows(points, scale=1.0):
    points = np.asarray(points, 'f4').reshape(-1, 3)
    return instance_rows(points, np.zeros(len(points)), np.full(len(points), scale))


def _scatter(count=4000, radius=60.0, seed=7, ordered=True):
    rng = np.random.default_rng(seed)
    angle = rng.uniform(0.0, 2.0 * np.pi, count)
    away = radius * np.sqrt(rng.uniform(0.0, 1.0, count))
    points = np.stack([away * np.cos(angle), rng.uniform(0.0, 3.0, count),
                       away * np.sin(angle)], 1)
    rows = _rows(points)
    return rows[np.asarray(morton_order(rows[:, :3]))] if ordered else rows


def _in_view(rows, mode):
    """The rows whose base point is inside every plane, by the plain per-point test."""
    planes = np.asarray(mode.frustum.planes, 'd')
    return np.all(rows[:, :3].astype('d') @ planes[:, :3].T + planes[:, 3] >= 0.0, axis=1)


class FakeBuffer:
    """What an ``InstanceBuffer`` offers: a count, and rows streamed into it."""

    def __init__(self) -> None:
        self.count = 0
        self.uploads: list[np.ndarray] = []

    def upload(self, rows) -> None:
        self.uploads.append(np.array(rows))
        self.count = len(rows)


def _culled(rows, **named):
    buffer = FakeBuffer()
    named.setdefault('triangles', MIN_TRIANGLES)
    culled = CulledRows(buffer, reach=named.pop('reach', 0.5), rise=named.pop('rise', 1.0),
                        **named)
    culled.stage(rows)
    return culled, buffer


class TestWhatAViewIsSent:
    def test_the_rows_in_front_of_the_camera_are_sent(self) -> None:
        rows = _scatter(count=6000)
        culled, buffer = _culled(rows)
        mode = _view()
        culled.show(mode)
        sent = {tuple(row) for row in buffer.uploads[-1]}
        assert all(tuple(row) in sent for row in rows[_in_view(rows, mode)])

    def test_a_good_part_of_what_is_behind_the_camera_is_not(self) -> None:
        rows = _scatter(count=40000)
        culled, _ = _culled(rows)
        seen = _in_view(rows, _view()).sum()
        assert seen <= culled.show(_view()) < 0.5 * len(rows)

    def test_the_rows_sent_are_the_staged_rows_untouched(self) -> None:
        rows = _scatter()
        culled, buffer = _culled(rows)
        culled.show(_view())
        assert {tuple(row) for row in buffer.uploads[-1]} <= {tuple(row) for row in rows}

    def test_the_count_is_what_the_buffer_holds(self) -> None:
        culled, buffer = _culled(_scatter())
        assert culled.show(_view()) == buffer.count

    def test_a_plant_based_out_of_view_whose_crown_reaches_in_is_sent(self) -> None:
        mode = _view(fovy=1.0, aspect=1.0)
        # 2.8 m outside the right-hand plane: further than the margin, nearer than the crown.
        outside = 2.8
        assert MARGIN_METRES < outside < 3.0
        rows = _rows([[20.0 * np.tan(0.5) + outside / np.cos(0.5), 0.0, -20.0]])
        wide, _ = _culled(rows, reach=3.0)
        narrow, _ = _culled(rows, reach=0.1)
        assert wide.show(mode) == 1
        assert narrow.show(mode) == 0

    def test_a_plant_just_outside_the_view_is_sent_within_the_margin(self) -> None:
        mode = _view(fovy=1.0, aspect=1.0)
        rows = _rows([[20.0 * np.tan(0.5) + 0.5 * MARGIN_METRES / np.cos(0.5), 0.0, -20.0]])
        culled, _ = _culled(rows, reach=0.1)
        assert culled.show(mode) == 1

    def test_a_tall_plant_below_the_view_is_sent_when_its_top_reaches_it(self) -> None:
        mode = _view(eye=(0.0, 30.0, 0.0), toward=(0.0, 30.0, -1.0), fovy=0.2)
        short, _ = _culled(_rows([[0.0, 0.0, -30.0]], scale=1.0), reach=0.1)
        tall, _ = _culled(_rows([[0.0, 0.0, -30.0]], scale=40.0), reach=0.1)
        assert short.show(mode) == 0
        assert tall.show(mode) == 1

    def test_a_view_that_sees_nothing_is_sent_nothing(self) -> None:
        culled, buffer = _culled(_rows([[0.0, 0.0, 50.0], [3.0, 0.0, 60.0]]))
        assert culled.show(_view()) == 0
        assert buffer.count == 0

    def test_a_set_cheaper_to_draw_than_to_test_is_sent_whole(self) -> None:
        rows = _rows([[0.0, 0.0, 50.0], [3.0, 0.0, 60.0]])
        culled, _ = _culled(rows, triangles=1)
        assert culled.show(_view()) == 2


class TestWhenItUploads:
    def test_the_same_view_twice_uploads_once(self) -> None:
        culled, buffer = _culled(_scatter())
        culled.show(_view())
        culled.show(_view())
        assert len(buffer.uploads) == 1

    def test_a_camera_that_turns_to_other_clusters_uploads_again(self) -> None:
        culled, buffer = _culled(_scatter())
        culled.show(_view(toward=(0.0, 1.7, -1.0)))
        culled.show(_view(toward=(1.0, 1.7, 0.0)))
        assert len(buffer.uploads) == 2

    def test_staging_again_uploads_even_for_the_same_view(self) -> None:
        culled, buffer = _culled(_scatter())
        culled.show(_view())
        culled.stage(_scatter(seed=8))
        culled.show(_view())
        assert len(buffer.uploads) == 2

    def test_a_camera_that_turns_a_little_uploads_nothing_more(self) -> None:
        culled, buffer = _culled(_scatter(count=40000))
        culled.show(_view(toward=(0.0, 1.7, -1.0)))
        culled.show(_view(toward=(0.005, 1.7, -1.0)))
        assert len(buffer.uploads) == 1

    def test_a_camera_that_turns_back_to_what_it_saw_uploads_nothing_more(self) -> None:
        culled, buffer = _culled(_scatter(count=40000))
        culled.show(_view(toward=(0.0, 1.7, -1.0)))
        culled.show(_view(toward=(0.0, 1.7, -1.0)))
        assert len(buffer.uploads) == 1

    def test_a_view_that_sees_every_cluster_replaces_one_that_saw_some(self) -> None:
        culled, buffer = _culled(_scatter(count=40000))
        culled.show(_view())
        everything = _view()
        everything.viewCopies = 2
        assert culled.show(everything) == 40000
        assert len(buffer.uploads) == 2


class TestWhenEverythingIsSent:
    def test_a_shared_draw_of_several_views_is_sent_every_row(self) -> None:
        rows = _scatter()
        culled, _ = _culled(rows)
        mode = _view()
        mode.viewCopies = 2
        assert culled.show(mode) == len(rows)

    def test_a_pass_with_no_frustum_is_sent_every_row(self) -> None:
        rows = _scatter()
        culled, _ = _culled(rows)
        assert culled.show(types.SimpleNamespace()) == len(rows)

    def test_a_frustum_with_no_planes_is_sent_every_row(self) -> None:
        rows = _scatter()
        culled, _ = _culled(rows)
        mode = types.SimpleNamespace(frustum=types.SimpleNamespace(planes=np.zeros((0, 4))))
        assert culled.show(mode) == len(rows)

    def test_culling_can_be_turned_off(self) -> None:
        rows = _scatter()
        culled, _ = _culled(rows, enabled=False)
        assert culled.show(_view()) == len(rows)

    def test_rows_that_are_not_numbers_are_all_sent(self) -> None:
        rows = _rows([[0.0, 0.0, 50.0], [np.inf, 0.0, 5.0]])
        culled, _ = _culled(rows)
        assert culled.show(_view()) == 2

    def test_an_empty_set_sends_nothing(self) -> None:
        culled, _ = _culled(np.zeros((0, 6), 'f4'))
        assert culled.show(_view()) == 0


class TestClusters:
    def test_a_set_in_spatial_order_is_culled_harder_than_the_same_set_scattered(self) -> None:
        mode = _view()
        ordered, _ = _culled(_scatter(count=8000, ordered=True))
        scattered, _ = _culled(_scatter(count=8000, ordered=False))
        assert ordered.show(mode) < scattered.show(mode)

    def test_the_last_cluster_may_be_short(self) -> None:
        rows = _scatter(count=CLUSTER_ROWS * 3 + 5)
        culled, buffer = _culled(rows)
        mode = _view(toward=(0.0, 1.7, 1.0), fovy=3.0, aspect=1.0)
        assert culled.show(mode) <= len(rows)
