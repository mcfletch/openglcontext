"""Several views of one scene on one window, drawn and picked for real.

Each view draws through its own camera into its own rectangle. These render a
real scene in a hidden window and read the finished frame back, so what they
check is what a player would see: which box is in which tile, what each tile's
background is, and which object a click in each tile lands on.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.multiview.views import View, ViewLayout, ViewStyle
from tests.unit.glrender import base_env, frames_of
from OpenGLContext.events.mouseevents import MouseButtonEvent
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.multiview import strategy as multiview
from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform
from OpenGLContext.multiview.grid import Grid
from OpenGLContext.passes import _flat, renderpass

WIDTH, HEIGHT = 200, 100


def _box(x, colour):
    return basenodes.Transform(translation=(x, 0, 0), children=[
        basenodes.Shape(
            geometry=basenodes.Box(size=(2, 2, 2)),
            appearance=basenodes.Appearance(
                material=basenodes.Material(diffuseColor=colour)))])


def _scene():
    return [
        _box(-3.0, (1.0, 0.0, 0.0)),
        _box(3.0, (0.0, 0.0, 1.0)),
        basenodes.DirectionalLight(direction=(0, 0, -1), intensity=1.0),
    ]


def _camera(x):
    return ViewPlatform(position=(x, 0, 6), orientation=(0, 1, 0, 0))


def _side_by_side(_context, right_style=None, right_camera=None):
    left = View(_camera(-3.0), name='left')
    right = View(right_camera if right_camera is not None else _camera(3.0),
                 name='right', style=right_style)
    return ViewLayout.split(left, right)


def _tile_centre(frame, x):
    """The pixel in the middle of the window's height at column ``x``."""
    return frame[frame.shape[0] // 2, x].astype(int)


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')


class TestEachViewThroughItsOwnCamera:
    @pytest.mark.usefixtures('env')
    def test_each_tile_shows_the_box_its_camera_faces(self, render_scene):
        frames = frames_of(render_scene, _scene(), frames=3,
                           layout=_side_by_side, size=(WIDTH, HEIGHT))
        frame = frames[-1]
        assert frame.shape[:2] == (HEIGHT, WIDTH)
        left = _tile_centre(frame, WIDTH // 4)
        right = _tile_centre(frame, 3 * WIDTH // 4)
        assert left[0] > 100 and left[2] < 40, left
        assert right[2] > 100 and right[0] < 40, right

    @pytest.mark.usefixtures('env')
    def test_a_perspective_view_takes_the_aspect_of_its_tile(self, render_scene):
        """A square tile of a wide window draws a box square, not stretched."""
        frames = frames_of(render_scene, _scene(), frames=3,
                           layout=_side_by_side, size=(WIDTH, HEIGHT))
        red = frames[-1][:, :WIDTH // 2, 0] > 100
        rows = np.flatnonzero(red.any(axis=1))
        columns = np.flatnonzero(red.any(axis=0))
        height = rows[-1] - rows[0] + 1
        width = columns[-1] - columns[0] + 1
        assert abs(width - height) <= 2, (width, height)

    @pytest.mark.usefixtures('env')
    def test_the_default_layout_is_one_view_of_the_whole_window(self, render_scene):
        rendered = render_scene(_scene(), frames=2, size=(WIDTH, HEIGHT))
        (view,) = rendered.context.getViewLayout().views
        assert view.rect == (0, 0, WIDTH, HEIGHT)
        assert view.camera is None


class TestPerViewStyle:
    @pytest.mark.usefixtures('env')
    def test_a_flat_background_fills_only_its_own_tile(self, render_scene):
        green = ViewStyle(background=(0.0, 1.0, 0.0))
        frames = frames_of(render_scene, _scene(), frames=3, size=(WIDTH, HEIGHT),
                           layout=lambda context: _side_by_side(context, green))
        frame = frames[-1]
        right_corner = frame[2, WIDTH - 3].astype(int)
        left_corner = frame[2, 2].astype(int)
        assert right_corner[1] > 200 and right_corner[0] < 30, right_corner
        assert left_corner.max() < 30, left_corner

    @pytest.mark.usefixtures('env')
    def test_a_wireframe_view_draws_lines_where_its_twin_draws_faces(self, render_scene):
        wire = ViewStyle(wireframe=True)
        frames = frames_of(
            render_scene, _scene(), frames=3, size=(WIDTH, HEIGHT),
            layout=lambda context: _side_by_side(context, wire, _camera(-3.0)))
        frame = frames[-1]
        shaded = int((frame[:, :WIDTH // 2, 0] > 60).sum())
        lines = int((frame[:, WIDTH // 2:, 0] > 60).sum())
        assert shaded > 1000
        assert 0 < lines < shaded // 3, (lines, shaded)

    @pytest.mark.usefixtures('env')
    def test_the_wireframe_does_not_outlast_its_view(self, render_scene):
        """The next frame's first view is shaded again."""
        wire = ViewStyle(wireframe=True)
        frames = frames_of(
            render_scene, _scene(), frames=3, size=(WIDTH, HEIGHT),
            layout=lambda context: _side_by_side(context, wire, _camera(-3.0)))
        for frame in frames[1:]:
            assert int((frame[:, :WIDTH // 2, 0] > 60).sum()) > 1000


class TestPickingThroughTheViewClicked:
    def _click(self, context, x, y):
        """Press and release at ``(x, y)``; the press, once the pick resolves it.

        The first press warms the selection buffer the second one reads. One
        point at a time, because presses of one button in one frame are the
        same question asked twice and only the later is kept.
        """
        for _warm in range(2):
            press = MouseButtonEvent()
            press.button, press.state, press.modifiers = 0, 1, (0, 0, 0)
            press.pickPoint = (x, y)
            context.addPickEvent(press)
            context.triggerPick()
            context.OnDraw(force=1)
            release = MouseButtonEvent()
            release.button, release.state, release.modifiers = 0, 0, (0, 0, 0)
            release.pickPoint = (x, y)
            context.routeEvent(release)
        return press

    def _pick(self, rendered, points):
        return [self._click(rendered.context, x, y) for (x, y) in points]

    def _colour_of(self, event):
        paths = event.getObjectPaths()
        assert paths and paths[0], 'the click landed on nothing'
        shape = paths[0][-1]
        return tuple(float(c) for c in shape.appearance.material.diffuseColor)

    @pytest.mark.usefixtures('env')
    def test_a_click_in_each_tile_lands_on_that_tiles_box(self, render_scene):
        rendered = render_scene(_scene(), frames=2, picks=[], size=(WIDTH, HEIGHT),
                                layout=_side_by_side)
        left, right = self._pick(rendered, [(WIDTH // 4, HEIGHT // 2),
                                            (3 * WIDTH // 4, HEIGHT // 2)])
        assert self._colour_of(left) == (1.0, 0.0, 0.0)
        assert self._colour_of(right) == (0.0, 0.0, 1.0)
        assert left.view.name == 'left'
        assert right.view.name == 'right'

    @pytest.mark.usefixtures('env')
    def test_a_click_unprojects_through_its_views_camera(self, render_scene):
        rendered = render_scene(_scene(), frames=2, picks=[], size=(WIDTH, HEIGHT),
                                layout=_side_by_side)
        left, right = self._pick(rendered, [(WIDTH // 4, HEIGHT // 2),
                                            (3 * WIDTH // 4, HEIGHT // 2)])
        # The middle of each tile is the middle of the front face its camera
        # faces: x at the box's centre, z at its front.
        for event, x in ((left, -3.0), (right, 3.0)):
            point = np.asarray(event.unproject(), 'd')
            assert point[0] == pytest.approx(x, abs=0.1), point
            assert point[2] == pytest.approx(1.0, abs=0.1), point

    @pytest.mark.usefixtures('env')
    def test_the_view_clicked_becomes_the_active_one(self, render_scene):
        rendered = render_scene(_scene(), frames=2, picks=[], size=(WIDTH, HEIGHT),
                                layout=_side_by_side)
        layout = rendered.context.getViewLayout()
        assert layout.active.name == 'left'
        self._pick(rendered, [(3 * WIDTH // 4, HEIGHT // 2)])
        assert layout.active.name == 'right'


def _ruled(_context):
    """Two top views of the same ground, the left one ruled."""
    black = (0.0, 0.0, 0.0)
    left = View(OrthoViewPlatform(OrthoView('top', span=20.0)), name='ruled',
                style=ViewStyle(background=black, grid=True))
    right = View(OrthoViewPlatform(OrthoView('top', span=20.0)), name='plain',
                 style=ViewStyle(background=black))
    return ViewLayout.split(left, right)


def _grid_scene():
    return [Grid(colour=(1.0, 1.0, 0.0), heavyColour=(1.0, 1.0, 0.0))]


class TestTheGrid:
    def _lit(self, tile):
        return int(((tile[..., 0] > 150) & (tile[..., 1] > 150)
                    & (tile[..., 2] < 60)).sum())

    @pytest.mark.usefixtures('env')
    def test_it_is_drawn_in_the_view_whose_style_asks(self, render_scene):
        frame = frames_of(render_scene, _grid_scene(), frames=3,
                          layout=_ruled, size=(WIDTH, HEIGHT))[-1]
        assert self._lit(frame[:, :WIDTH // 2]) > 100
        assert self._lit(frame[:, WIDTH // 2:]) == 0

    @pytest.mark.usefixtures('env')
    def test_and_in_a_compatibility_profile(self, render_scene, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'compatibility')
        frame = frames_of(render_scene, _grid_scene(), frames=3,
                          layout=_ruled, size=(WIDTH, HEIGHT))[-1]
        assert self._lit(frame[:, :WIDTH // 2]) > 100
        assert self._lit(frame[:, WIDTH // 2:]) == 0


class TestCompatibilityProfile:
    @pytest.mark.usefixtures('env')
    def test_each_tile_shows_the_box_its_camera_faces(self, render_scene, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'compatibility')
        frames = frames_of(render_scene, _scene(), frames=3,
                           layout=_side_by_side, size=(WIDTH, HEIGHT))
        frame = frames[-1]
        left = _tile_centre(frame, WIDTH // 4)
        right = _tile_centre(frame, 3 * WIDTH // 4)
        assert left[0] > 100 and left[2] < 40, left
        assert right[2] > 100 and right[0] < 40, right


class TestTheStrategy:
    @pytest.mark.usefixtures('env')
    def test_a_frame_of_several_views_settles_how_it_is_drawn(self, render_scene):
        render_scene(_scene(), frames=2, size=(WIDTH, HEIGHT), layout=_side_by_side)
        assert renderpass.FLAT.multiviewStrategy in multiview.STRATEGIES

    @pytest.mark.usefixtures('env')
    def test_one_view_asks_the_driver_nothing(self, render_scene):
        render_scene(_scene(), frames=2, size=(WIDTH, HEIGHT))
        assert renderpass.FLAT.multiviewStrategy is None

    @pytest.mark.usefixtures('env')
    def test_a_pinned_strategy_is_the_one_drawn_with(self, render_scene):
        def layout(context):
            context.contextDefinition.multiview = 'sequential'
            return _side_by_side(context)

        multiview.reset_detected()
        render_scene(_scene(), frames=2, size=(WIDTH, HEIGHT), layout=layout)
        assert renderpass.FLAT.multiviewStrategy == 'sequential'


    @pytest.mark.usefixtures('env')
    def test_a_strategy_chosen_while_running_is_the_one_drawn_with(self, render_scene):
        """The settings screen's field takes effect on the next frame."""

        def layout(context):
            context.contextDefinition.multiview = 'sequential'
            return _side_by_side(context)

        multiview.reset_detected()
        rendered = render_scene(_scene(), frames=2, size=(WIDTH, HEIGHT), layout=layout)
        assert renderpass.FLAT.multiviewStrategy == 'sequential'
        context = rendered.context
        context.setCurrent()
        try:
            expected = multiview.MultiviewCapabilities.detect().choose('geometry')
        finally:
            context.unsetCurrent()
        context.contextDefinition.multiview = 'geometry'
        context.OnDraw(force=1)
        assert renderpass.FLAT.multiviewStrategy == expected
        context.contextDefinition.multiview = 'sequential'
        context.OnDraw(force=1)
        assert renderpass.FLAT.multiviewStrategy == 'sequential'


class TestAnArrangementThatLeavesRoom:
    """Views need not be equal, and need not cover the window.

    A window with a toolbar down one side gives its views the rest, through an
    arrangement of its own. What the views do not cover is still cleared, so
    the band is a colour rather than whatever the last frame left there.
    """

    def _with_a_band(self, _context):
        band = 60

        def arrangement(width, height):
            return [(band, 0, (width - band) // 2, height),
                    (band + (width - band) // 2, 0, (width - band) // 2, height)]

        left = View(_camera(-3.0), name='left',
                    style=ViewStyle(background=(1.0, 0.0, 0.0)))
        right = View(_camera(3.0), name='right',
                     style=ViewStyle(background=(0.0, 0.0, 1.0)))
        return ViewLayout([left, right], arrangement=arrangement)

    @pytest.mark.usefixtures('env')
    def test_the_views_are_where_the_arrangement_put_them(self, render_scene):
        frame = frames_of(render_scene, _scene(), frames=2,
                          layout=self._with_a_band, size=(WIDTH, HEIGHT))[-1]
        assert _tile_centre(frame, 80)[0] > 100      # the left view, red
        assert _tile_centre(frame, 170)[2] > 100     # the right view, blue

    @pytest.mark.usefixtures('env')
    def test_what_a_view_stops_covering_is_cleared(self, render_scene):
        """A band given up to a toolbar keeps no part of the frame before it."""
        def shrinking(_context):
            drawn = []

            def arrangement(width, height):
                drawn.append(1)
                # The first frame fills the window; the rest leave a band.
                band = 0 if len(drawn) < 2 else 60
                return [(band, 0, width - band, height)]

            return ViewLayout(
                [View(_camera(0.0), name='one',
                      style=ViewStyle(background=(1.0, 0.0, 0.0)))],
                arrangement=arrangement)

        frames = frames_of(render_scene, _scene(), frames=3,
                           layout=shrinking, size=(WIDTH, HEIGHT))
        assert _tile_centre(frames[0], 20)[0] > 100      # the view was here
        band = frames[-1][:, :55].astype(int)
        assert band.max() < 40, band.max()               # ...and is not now


class TestAViewThroughTheWindowsCamera:
    @pytest.mark.usefixtures('env')
    def test_it_takes_the_aspect_of_its_tile(self, render_scene):
        """A view with no camera of its own draws a box square in a square tile."""
        def layout(context):
            context.getViewPlatform().setPosition((-3.0, 0.0, 6.0))
            return ViewLayout.split(View(name='window'), View(_camera(3.0), name='right'))

        frames = frames_of(render_scene, _scene(), frames=3,
                           layout=layout, size=(WIDTH, HEIGHT))
        red = frames[-1][:, :WIDTH // 2, 0] > 100
        rows = np.flatnonzero(red.any(axis=1))
        columns = np.flatnonzero(red.any(axis=0))
        assert rows.size and columns.size
        height = rows[-1] - rows[0] + 1
        width = columns[-1] - columns[0] + 1
        assert abs(width - height) <= 2, (width, height)

    @pytest.mark.usefixtures('env')
    def test_the_windows_camera_keeps_the_windows_aspect(self, render_scene):
        def layout(_context):
            return ViewLayout.split(View(name='window'), View(_camera(3.0), name='right'))

        rendered = render_scene(_scene(), frames=2, size=(WIDTH, HEIGHT), layout=layout)
        platform = rendered.context.getViewPlatform()
        assert platform.frustum[1] == pytest.approx(WIDTH / HEIGHT)


class TestAViewThatRaises:
    @pytest.mark.usefixtures('env')
    def test_the_next_frame_is_not_confined_to_its_tile(self, render_scene, monkeypatch):
        """A view that fails part-way leaves no scissor rectangle behind it."""

        original = _flat.FlatPass.renderViewShader
        calls = []

        def failing(self, frame, *args, **named):
            calls.append(frame.view.name)
            drawn = original(self, frame, *args, **named)
            if len(calls) == 2:
                raise RuntimeError('a view that fails')
            return drawn

        monkeypatch.setattr(_flat.FlatPass, 'renderViewShader', failing)
        drawing = _flat.FlatPass.__call__

        def surviving(self, context):
            # What an application's loop does with a frame that raised: it
            # reports it and draws the next one.
            try:
                return drawing(self, context)
            except RuntimeError:
                return False

        monkeypatch.setattr(_flat.FlatPass, '__call__', surviving)

        def layout(_context):
            drawn = []
            green = ViewStyle(background=(0.0, 1.0, 0.0))

            def arrangement(width, height):
                drawn.append(1)
                if len(drawn) < 2:
                    return [(0, 0, width // 2, height), (width // 2, 0, width // 2, height),
                            (0, 0, 0, 0)]
                return [(0, 0, 0, 0), (0, 0, 0, 0), (0, 0, width, height)]

            return ViewLayout([
                View(_camera(-3.0), name='left', style=green),
                View(_camera(3.0), name='right', style=green),
                View(_camera(0.0), name='whole',
                     style=ViewStyle(background=(1.0, 0.0, 0.0))),
            ], arrangement=arrangement)

        frames = frames_of(render_scene, _scene(), frames=3,
                           layout=layout, size=(WIDTH, HEIGHT))
        assert 'right' in calls
        corner = frames[-1][2, 2].astype(int)
        assert corner[0] > 200 and corner[1] < 30, corner
