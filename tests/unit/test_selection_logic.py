"""Pure-logic tests for :class:`SelectionMixin` (no GL context).

Covers the parts of the pick *policy* that are plain CPU work: pick-event
optimisation (mouse-move filtering + pixel de-duplication), the pick-region
projection maths, the screen-space bounding-box projection, the lazy FBO
accessors and the buffer-path early-outs. The GL-driven pick paths live in
``test_selection_render_gl.py``.
"""
import numpy as np

from OpenGLContext.arrays import identity
from OpenGLContext.events import mouseevents
from OpenGLContext.passes.selection import (
    SelectionFBO, SelectionBufferFBO, SelectionMixin,
)


def _bare():
    sel = SelectionMixin.__new__(SelectionMixin)
    sel._selection_fbo = None
    sel._selection_buffer = None
    sel._has_mousemove_handlers = None
    sel.projection = identity(4, 'f')
    return sel


class FakeEvent(mouseevents.MouseButtonEvent):
    """A real mouse event with a chosen type and pick point.

    Only what the optimiser reads is stood in for; the keys it de-duplicates
    on are the ones the event classes really produce, since which events count
    as the same news is exactly what is under test.
    """

    def __init__(self, etype, x, y, button=0, state=1):
        super(FakeEvent, self).__init__()
        self.type = etype
        self.pickPoint = (x, y)
        self.button = button
        self.state = state
        self.paths = None

    def setObjectPaths(self, p):
        self.paths = p


class FakeContext:
    def __init__(self, has_move):
        self._has_move = has_move
        self.move_queries = 0

    def hasMouseMoveHandlers(self):
        self.move_queries += 1
        return self._has_move


# --------------------------------------------------------------------------- #
# lazy accessors
# --------------------------------------------------------------------------- #
class TestLazyAccessors:
    def test_selection_fbo_created_once(self):
        sel = _bare()
        fbo = sel._getSelectionFBO()
        assert isinstance(fbo, SelectionFBO)
        assert sel._getSelectionFBO() is fbo         # cached

    def test_selection_buffer_created_once(self):
        sel = _bare()
        buf = sel._getSelectionBuffer()
        assert isinstance(buf, SelectionBufferFBO)
        assert sel._getSelectionBuffer() is buf


# --------------------------------------------------------------------------- #
# _optimizePickEvents
# --------------------------------------------------------------------------- #
class TestOptimizePickEvents:
    def test_empty_events_returned_unchanged(self):
        sel = _bare()
        assert sel._optimizePickEvents(FakeContext(False), {}) == {}

    def test_mousemove_filtered_when_no_handlers(self):
        sel = _bare()
        events = {
            'a': FakeEvent('mousemove', 100, 200),
            'b': FakeEvent('mousebutton', 100, 200),
        }
        out = sel._optimizePickEvents(FakeContext(False), events)
        assert len(out) == 1
        assert list(out.values())[0].type == 'mousebutton'

    def test_mousemove_kept_when_handlers_present(self):
        sel = _bare()
        events = {'a': FakeEvent('mousemove', 10, 20)}
        out = sel._optimizePickEvents(FakeContext(True), events)
        assert len(out) == 1

    def test_events_deduplicated_by_pixel(self):
        sel = _bare()
        first = FakeEvent('mousebutton', 50, 60)
        second = FakeEvent('mousebutton', 50, 60)   # same pixel + type
        out = sel._optimizePickEvents(
            FakeContext(True), {'a': first, 'b': second})
        assert len(out) == 1
        assert list(out.values())[0] is second      # latest wins

    def test_a_press_and_its_release_on_one_pixel_are_both_kept(self):
        """They land on the same pixel by definition; only one is a click.

        De-duplication is for events that say the same thing twice, and a
        button's two halves do not: dropping the press leaves a release
        nothing began, and dropping the release leaves a press nothing ends.
        """
        press = FakeEvent('mousebutton', 50, 60, button=0, state=1)
        release = FakeEvent('mousebutton', 50, 60, button=0, state=0)
        out = _bare()._optimizePickEvents(
            FakeContext(True), {'a': press, 'b': release})
        assert set(out.values()) == {press, release}

    def test_wheel_notches_on_one_pixel_are_all_kept(self):
        """The pointer does not move while scrolling, and each notch is a line."""
        notches = [FakeEvent('mousebutton', 50, 60, button=3, state=1)
                   for _ in range(3)]
        events = {index: notch for index, notch in enumerate(notches)}
        assert len(_bare()._optimizePickEvents(FakeContext(True), events)) == 3

    def test_different_buttons_on_one_pixel_are_kept(self):
        left = FakeEvent('mousebutton', 50, 60, button=0)
        right = FakeEvent('mousebutton', 50, 60, button=1)
        out = _bare()._optimizePickEvents(
            FakeContext(True), {'a': left, 'b': right})
        assert set(out.values()) == {left, right}

    def test_moves_on_one_pixel_are_still_one_move(self):
        """Where the pointer is now is the whole of the news, and moves flood."""
        first = FakeEvent('mousemove', 50, 60)
        second = FakeEvent('mousemove', 50, 60)
        out = _bare()._optimizePickEvents(
            FakeContext(True), {'a': first, 'b': second})
        assert list(out.values()) == [second]

    def test_distinct_pixels_are_kept(self):
        sel = _bare()
        out = sel._optimizePickEvents(FakeContext(True), {
            'a': FakeEvent('mousebutton', 1, 1),
            'b': FakeEvent('mousebutton', 2, 2),
        })
        assert len(out) == 2

    def test_handler_query_is_cached_across_events(self):
        sel = _bare()
        ctx = FakeContext(True)
        sel._optimizePickEvents(ctx, {
            'a': FakeEvent('mousemove', 1, 1),
            'b': FakeEvent('mousemove', 2, 2),
        })
        assert ctx.move_queries == 1                 # asked once, then cached


# --------------------------------------------------------------------------- #
# _createPickProjection
# --------------------------------------------------------------------------- #
class TestCreatePickProjection:
    def test_zoom_scales_by_viewport_over_region(self):
        sel = _bare()
        # region 100x50 inside a 400x200 viewport -> 4x zoom in x, 4x in y.
        result = sel._createPickProjection((150, 75, 100, 50), (0, 0, 400, 200))
        assert result[0, 0] == 4.0
        assert result[1, 1] == 4.0

    def test_centered_region_has_no_translation(self):
        sel = _bare()
        # A region centred in the viewport => no NDC shift.
        result = sel._createPickProjection((150, 75, 100, 50), (0, 0, 400, 200))
        assert result[3, 0] == 0.0
        assert result[3, 1] == 0.0

    def test_offcenter_region_translates(self):
        sel = _bare()
        result = sel._createPickProjection((0, 0, 100, 50), (0, 0, 400, 200))
        assert result[3, 0] != 0.0
        assert result[3, 1] != 0.0

    def test_zero_size_region_avoids_divide_by_zero(self):
        sel = _bare()
        result = sel._createPickProjection((10, 10, 0, 0), (0, 0, 400, 200))
        assert result[0, 0] == 1.0                   # guard scale
        assert result[1, 1] == 1.0


# --------------------------------------------------------------------------- #
# _computeScreenSpaceBBoxes
# --------------------------------------------------------------------------- #
class _Vol:
    def __init__(self, points):
        self._points = points

    def getPoints(self):
        return self._points


class _RaisingVol:
    def getPoints(self):
        raise ValueError("no bounds")


def _record(bvolume):
    return ('key', identity(4, 'f'), None, bvolume, ['path'])


class TestComputeScreenSpaceBBoxes:
    def test_none_bvolume_yields_none(self):
        sel = _bare()
        assert sel._computeScreenSpaceBBoxes([_record(None)], 100.0, 100.0) == [None]

    def test_empty_points_yields_none(self):
        sel = _bare()
        vol = _Vol(np.zeros((0, 4), 'f'))
        assert sel._computeScreenSpaceBBoxes([_record(vol)], 100.0, 100.0) == [None]

    def test_4d_points_project_to_bbox(self):
        sel = _bare()
        pts = np.array([[-1, -1, 0, 1], [1, 1, 0, 1]], 'f')
        out = sel._computeScreenSpaceBBoxes([_record(_Vol(pts))], 100.0, 100.0)
        # identity mvp, NDC == xy; screen = (ndc+1)*0.5*size -> 0..100.
        assert out[0] is not None
        min_x, min_y, max_x, max_y = out[0]
        assert min_x == 0.0 and min_y == 0.0
        assert max_x == 100.0 and max_y == 100.0

    def test_3d_points_are_homogenised(self):
        sel = _bare()
        pts = np.array([[-1, -1, 0], [1, 1, 0]], 'f')     # shape (N, 3)
        out = sel._computeScreenSpaceBBoxes([_record(_Vol(pts))], 100.0, 100.0)
        assert out[0] == (0.0, 0.0, 100.0, 100.0)

    def test_points_behind_camera_yield_none(self):
        sel = _bare()
        pts = np.array([[0, 0, 0, -1], [1, 1, 0, -2]], 'f')   # w <= 0
        out = sel._computeScreenSpaceBBoxes([_record(_Vol(pts))], 100.0, 100.0)
        assert out == [None]

    def test_exception_in_getpoints_is_swallowed(self):
        sel = _bare()
        out = sel._computeScreenSpaceBBoxes([_record(_RaisingVol())], 100.0, 100.0)
        assert out == [None]


# --------------------------------------------------------------------------- #
# processPickEventsFromBuffer early-outs
# --------------------------------------------------------------------------- #
class _FakeBuffer:
    _initialized = False
    id_map: dict = {}

    def read_pixel(self, x, y):    # pragma: no cover - not reached in these tests
        raise AssertionError("should not read from an uninitialized buffer")


class TestProcessPickEventsFromBufferEarlyOut:
    def test_empty_events_returns(self):
        sel = _bare()
        # No buffer needed; must return before touching one.
        sel.processPickEventsFromBuffer(mode=None, events={})

    def test_uninitialized_buffer_falls_back(self):
        sel = _bare()
        buf = _FakeBuffer()
        sel._getSelectionBuffer = lambda: buf
        sel.matrix = identity(4, 'f')
        sel.viewport = (0, 0, 16, 16)
        # read_pixel must not be called when the buffer isn't initialized.
        sel.processPickEventsFromBuffer(
            mode=None, events={'k': FakeEvent('mousebutton', 1, 1)})
