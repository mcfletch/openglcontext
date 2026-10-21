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
    CLUSTER_ROWS, DISC_MARGIN_METRES, MARGIN_METRES, MIN_TRIANGLES, CulledRows,
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


class TestADisc:
    """Rows beyond a radius of the camera are not wanted, however the view looks."""

    def test_rows_beyond_the_radius_are_not_sent(self) -> None:
        rows = _scatter(count=6000, radius=60.0)
        culled, buffer = _culled(rows)
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        assert 0 < len(buffer.uploads[-1]) < 0.5 * len(rows)

    def test_every_row_within_the_radius_is_sent(self) -> None:
        rows = _scatter(count=6000, radius=60.0)
        culled, buffer = _culled(rows)
        culled.show(types.SimpleNamespace(), (3.0, -2.0, 20.0))
        sent = {tuple(row) for row in buffer.uploads[-1]}
        near = np.hypot(rows[:, 0] - 3.0, rows[:, 2] + 2.0) < 20.0
        assert near.any()
        assert all(tuple(row) in sent for row in rows[near])

    def test_a_disc_and_a_view_together_send_what_both_want(self) -> None:
        rows = _scatter(count=40000, radius=60.0)
        culled, buffer = _culled(rows)
        mode = _view()
        count = culled.show(mode, (0.0, 0.0, 25.0))
        in_both = _in_view(rows, mode) & (np.hypot(rows[:, 0], rows[:, 2]) < 25.0)
        sent = {tuple(row) for row in buffer.uploads[-1]}
        assert all(tuple(row) in sent for row in rows[in_both])
        assert count < _in_view(rows, mode).sum()

    def test_a_disc_wider_than_the_set_sends_every_row(self) -> None:
        rows = _scatter(count=6000, radius=30.0)
        culled, _ = _culled(rows)
        assert culled.show(types.SimpleNamespace(), (0.0, 0.0, 200.0)) == len(rows)

    def test_a_set_cheaper_to_draw_than_to_test_is_still_cut_to_the_disc(self) -> None:
        rows = _scatter(count=3000, radius=60.0)
        culled, _ = _culled(rows, triangles=1)
        assert culled.show(types.SimpleNamespace(), (0.0, 0.0, 15.0)) < len(rows)

    def test_a_disc_does_nothing_with_culling_turned_off(self) -> None:
        rows = _scatter()
        culled, _ = _culled(rows, enabled=False)
        assert culled.show(types.SimpleNamespace(), (0.0, 0.0, 5.0)) == len(rows)

    def test_a_disc_about_a_point_the_rows_are_not_near_sends_nothing(self) -> None:
        culled, buffer = _culled(_scatter(radius=60.0))
        assert culled.show(types.SimpleNamespace(), (500.0, 500.0, 20.0)) == 0
        assert buffer.count == 0


class TestWhenADiscUploads:
    def test_the_same_disc_twice_uploads_once(self) -> None:
        culled, buffer = _culled(_scatter())
        for _ in range(2):
            culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        assert len(buffer.uploads) == 1

    def test_a_disc_that_moves_less_than_its_margin_uploads_nothing_more(self) -> None:
        culled, buffer = _culled(_scatter())
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        culled.show(types.SimpleNamespace(), (0.5 * DISC_MARGIN_METRES, 0.0, 20.0))
        assert len(buffer.uploads) == 1

    def test_a_disc_that_moves_past_its_margin_uploads_again(self) -> None:
        culled, buffer = _culled(_scatter())
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        culled.show(types.SimpleNamespace(), (25.0, 0.0, 20.0))
        assert len(buffer.uploads) == 2

    def test_a_disc_that_moves_on_still_has_its_rows_sent(self) -> None:
        rows = _scatter(count=6000, radius=60.0)
        culled, buffer = _culled(rows)
        for x in np.arange(0.0, 30.0, 0.7):
            culled.show(types.SimpleNamespace(), (float(x), 0.0, 20.0))
            sent = {tuple(row) for row in buffer.uploads[-1]}
            near = np.hypot(rows[:, 0] - x, rows[:, 2]) < 20.0
            assert all(tuple(row) in sent for row in rows[near])

    def test_staging_again_uploads_for_the_same_disc(self) -> None:
        culled, buffer = _culled(_scatter())
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        culled.stage(_scatter(seed=8))
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        assert len(buffer.uploads) == 2

    def test_a_view_without_a_disc_after_one_with_replaces_it(self) -> None:
        rows = _scatter(count=6000, radius=60.0)
        culled, buffer = _culled(rows)
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 10.0))
        assert culled.show(types.SimpleNamespace()) == len(rows)
        assert len(buffer.uploads) == 2


class _CountingBoxes:
    """Counts the frustum tests a CulledRows makes, which are the costly half of a check."""

    def __init__(self, monkeypatch) -> None:
        from OpenGLContext.scenegraph.vegetation import viewcull
        self.calls = 0
        real = viewcull.frustums.boxes_outside

        def counting(*arguments):
            self.calls += 1
            return real(*arguments)
        monkeypatch.setattr(viewcull.frustums, 'boxes_outside', counting)


class TestASmallSetUnderADisc:
    """A set cheaper to draw than to cull by the frustum is still limited to its disc."""

    def test_the_view_does_not_cut_it(self) -> None:
        rows = _scatter(count=3000, radius=30.0)
        culled, _ = _culled(rows, triangles=1)
        in_disc = np.hypot(rows[:, 0], rows[:, 2]) < 100.0
        assert culled.show(_view(), (0.0, 0.0, 100.0)) == in_disc.sum()

    def test_a_disc_that_has_not_moved_far_is_covered_without_a_frustum_test(
            self, monkeypatch) -> None:
        culled, buffer = _culled(_scatter(radius=60.0), triangles=1)
        boxes = _CountingBoxes(monkeypatch)
        culled.show(_view(), (0.0, 0.0, 20.0))
        culled.show(_view(toward=(1.0, 1.7, 0.0)), (0.4 * DISC_MARGIN_METRES, 0.0, 20.0))
        assert boxes.calls == 0
        assert len(buffer.uploads) == 1

    def test_a_disc_that_has_moved_past_its_margin_is_chosen_again(self) -> None:
        culled, buffer = _culled(_scatter(radius=60.0), triangles=1)
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        culled.show(types.SimpleNamespace(), (30.0, 0.0, 20.0))
        assert len(buffer.uploads) == 2

    def test_a_disc_that_grows_is_chosen_again(self) -> None:
        culled, buffer = _culled(_scatter(radius=60.0), triangles=1)
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 20.0))
        culled.show(types.SimpleNamespace(), (0.0, 0.0, 40.0))
        assert len(buffer.uploads) == 2


class TestAnythingSentWhole:
    def test_a_set_every_cluster_of_which_is_wanted_is_not_chosen_again_each_view(self) -> None:
        culled, buffer = _culled(_scatter(count=2000, radius=10.0))
        culled.show(_view(eye=(0.0, 1.7, 30.0)))
        culled.show(_view(eye=(0.0, 1.7, 30.0), toward=(0.0, 1.7, 0.0)))
        culled.show(_view(eye=(0.0, 1.7, 30.0), toward=(0.0, 1.7, 0.0)))
        assert len(buffer.uploads) == 1

    def test_a_set_sent_whole_for_want_of_a_disc_is_cut_to_one_when_it_has_one(self) -> None:
        rows = _scatter(count=6000, radius=60.0)
        culled, buffer = _culled(rows)
        assert culled.show(types.SimpleNamespace()) == len(rows)
        assert culled.show(types.SimpleNamespace(), (0.0, 0.0, 10.0)) < len(rows)


class TestTheDecisionIsTheFrustumsOwn:
    """The clusters a view wants are those ``frustum.boxes_outside`` does not put outside."""

    def test_the_clusters_wanted_by_a_view_are_the_ones_the_frustum_keeps(self) -> None:
        from OpenGLContext.frustum import boxes_outside
        rows = _scatter(count=20000, radius=80.0)
        culled, _ = _culled(rows)
        for toward in ((0.0, 1.7, -1.0), (1.0, 1.7, 0.3), (-0.4, 2.5, 1.0)):
            mode = _view(toward=toward)
            planes = np.asarray(mode.frustum.planes, 'd')
            culled.show(mode)
            for margin in (0.0, MARGIN_METRES):
                widened = planes.copy()
                widened[:, 3] += margin
                kept = ~boxes_outside(*culled._boxes, None, widened)  # noqa: SLF001 the boxes are the thing compared
                assert np.array_equal(culled._wanted(planes, None, margin, 0.0), kept)  # noqa: SLF001 the decision is the thing compared
