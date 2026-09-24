"""A mirror shows what stands in front of it (GL, PBR core).

A mirror hangs on the far wall and a red box stands behind the camera, where
the camera cannot see it: red reaches the screen only through the mirror. The
arithmetic is asserted without a window in ``test_planar_reflection.py`` and
``test_reflection_planner.py``; these are the claims that need one.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial  # noqa: E402
from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: E402
from OpenGLContext.scenegraph.reflector import PlanarReflector  # noqa: E402
from tests.unit.glrender import base_env, frames_of  # noqa: E402

SIZE = (160, 120)


def _mirror(x=0.0, z=-4.0, size=6.0, reflector=None, **material):
    half = size / 2.0
    mesh = PBRMesh(
        positions=np.array([(-half, -half, 0), (half, -half, 0),
                            (half, half, 0), (-half, half, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32))
    settings = dict(baseColor=(1.0, 1.0, 1.0), metallic=1.0, roughness=0.0)
    settings.update(material)
    return basenodes.Transform(translation=(x, 0.0, z), children=[basenodes.Shape(
        geometry=mesh, appearance=basenodes.Appearance(material=PBRMaterial(
            reflector=PlanarReflector() if reflector is None else reflector,
            **settings)))])


def _box(x, z, colour, size=3.0):
    return basenodes.Transform(translation=(x, 0.0, z), children=[basenodes.Shape(
        geometry=basenodes.Box(size=(size, size, size)),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=colour, emissiveColor=colour)))])


def _room(*mirrors):
    """A camera at z = 6 facing a mirror at z = -4, a red box behind the camera.

    Lit from overhead, so the mirror carries no highlight of a light at the
    eye over the middle of it.
    """
    return [basenodes.Viewpoint(position=(0.0, 0.0, 6.0)),
            basenodes.NavigationInfo(headlight=False),
            basenodes.DirectionalLight(direction=(0.0, -1.0, 0.0)),
            _box(0.0, 9.0, (1.0, 0.0, 0.0))] + list(mirrors or [_mirror()])


def _red(frame, box=12):
    """How many pixels of the middle of the frame are red."""
    height, width = frame.shape[:2]
    middle = frame[height // 2 - box:height // 2 + box,
                   width // 2 - box:width // 2 + box].astype(int)
    return int(((middle[..., 0] > 120) & (middle[..., 0] > middle[..., 1] + 60)).sum())


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    return monkeypatch


def test_the_mirror_shows_what_stands_behind_the_camera(render_scene, env):
    frame = frames_of(render_scene, _room(), frames=3, size=SIZE)[-1]
    assert _red(frame) > 300


def test_switched_off_the_mirror_reflects_the_sky(render_scene, env):
    env.setenv('OPENGLCONTEXT_PLANAR_REFLECTIONS', '0')
    frame = frames_of(render_scene, _room(), frames=3, size=SIZE)[-1]
    assert _red(frame) == 0


def test_a_disabled_reflector_reflects_the_sky(render_scene, env):
    frame = frames_of(render_scene, _room(_mirror(reflector=PlanarReflector(
        enabled=False))), frames=3, size=SIZE)[-1]
    assert _red(frame) == 0


def test_a_mirror_that_replaces_its_surface_shows_the_reflection_whatever_its_material(
        render_scene, env):
    """A rough blue plastic would reflect nothing; replacing, it shows the box."""
    rough_blue = dict(baseColor=(0.0, 0.0, 1.0), metallic=0.0, roughness=1.0)
    shown = frames_of(render_scene, _room(_mirror(
        reflector=PlanarReflector(replace=True), **rough_blue)),
        frames=3, size=SIZE)[-1]
    shaded = frames_of(render_scene, _room(_mirror(**rough_blue)),
                       frames=3, size=SIZE)[-1]
    assert _red(shown) > 300
    assert _red(shaded) == 0


def test_the_mirror_is_drawn_from_its_own_reflection_not_the_screen(render_scene, env):
    """A mirror off to one side still reflects the box along its own normal."""
    frame = frames_of(render_scene, _room(_mirror(x=0.0, size=4.0)),
                      frames=3, size=SIZE)[-1]
    height, width = frame.shape[:2]
    corner = frame[:12, :12].astype(int)
    assert _red(frame) > 300
    assert int((corner[..., 0] > 120).sum()) == 0


def test_each_view_sees_the_mirror_from_where_it_stands(render_scene, env):
    from OpenGLContext.move.viewplatform import ViewPlatform
    from OpenGLContext.multiview.views import View, ViewLayout

    def layout(context):
        left = View(ViewPlatform(position=(0.0, 0.0, 6.0), orientation=(0, 1, 0, 0)),
                    name='left')
        right = View(ViewPlatform(position=(0.0, 0.0, 6.0), orientation=(0, 1, 0, 0)),
                     name='right')
        return ViewLayout.split(left, right)

    frame = frames_of(render_scene, _room(), frames=3, size=(2 * SIZE[0], SIZE[1]),
                      layout=layout)[-1]
    left, right = frame[:, :SIZE[0]], frame[:, SIZE[0]:]
    assert _red(left, box=8) > 100 and _red(right, box=8) > 100


def _wall(y, colour):
    return basenodes.Transform(translation=(0.0, y, 14.0), children=[
        basenodes.Shape(geometry=basenodes.Box(size=(60.0, 15.0, 1.0)),
                        appearance=basenodes.Appearance(material=basenodes.Material(
                            diffuseColor=colour)))])


def _mirror_draws(render_scene, env, strategy, mirrors):
    """Mirror views drawn, and the draws they took, for a row of mirrors.

    Behind the camera stand two walls, one above the mirrors' centre line and
    one below, so every mirror of the row sees both of them and nothing else.
    """
    from OpenGLContext.multiview.strategy import MultiviewCapabilities
    from OpenGLContext.passes import renderpass
    env.setenv('OPENGLCONTEXT_MULTIVIEW', strategy)
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '16')
    scene = [basenodes.Viewpoint(position=(0.0, 0.0, 6.0)),
             basenodes.NavigationInfo(headlight=False),
             basenodes.DirectionalLight(direction=(0.0, -1.0, 0.0)),
             _wall(7.5, (0.2, 0.6, 0.2)), _wall(-7.5, (0.2, 0.2, 0.6))]
    scene += [_mirror(x=x, size=2.5) for x in np.linspace(-4.5, 4.5, mirrors)]
    render_scene(scene, frames=3, size=(320, 120))
    flat = renderpass.FLAT
    if flat.multiviewStrategy != strategy:
        pytest.skip('this driver cannot draw with %s (%r)'
                    % (strategy, MultiviewCapabilities.detect()))
    return flat.stats.mirrorViews, flat.stats.mirrorDraws


@pytest.mark.parametrize('strategy', ['vertex', 'geometry'])
def test_one_draw_per_shape_serves_every_mirror(render_scene, env, strategy):
    two = _mirror_draws(render_scene, env, strategy, 2)
    four = _mirror_draws(render_scene, env, strategy, 4)
    assert (two[0], four[0]) == (2, 4)
    assert four[1] == two[1] == 2          # each wall once


def test_drawn_in_turn_each_mirror_costs_its_own_draws(render_scene, env):
    two = _mirror_draws(render_scene, env, 'sequential', 2)
    four = _mirror_draws(render_scene, env, 'sequential', 4)
    assert (two, four) == ((2, 4), (4, 8))


def test_drawn_in_turn_two_mirrors_a_frame_is_the_default(render_scene, env):
    env.setenv('OPENGLCONTEXT_MULTIVIEW', 'sequential')
    row = [_mirror(x=x, size=2.5) for x in np.linspace(-4.5, 4.5, 4)]
    render_scene(_room(*row), frames=2, size=(320, 120))
    from OpenGLContext.passes import renderpass
    assert renderpass.FLAT.stats.mirrorViews == 2


def test_a_reflection_reused_after_a_small_move_matches_a_fresh_one(
        render_scene, env, monkeypatch):
    """A tile kept past its frame is read through the matrix it was drawn with.

    Two mirrors and room for one mirror view a frame: the left one, redrawn
    every frame and far more important, takes it, and the right one is left
    stale. After the camera steps sideways by a centimetre the stale
    reflection reads where a fresh one would put it, which is what reading a
    tile by projection buys. (Half a metre leaves half a percent of the
    mirror off by parallax, which is the bound this is measured against.)
    """
    from OpenGLContext import glfwcontext
    from OpenGLContext.capture import read_back_buffer
    from OpenGLContext.move.viewplatform import ViewPlatform
    from OpenGLContext.multiview.views import ViewLayout
    from OpenGLContext.passes import renderpass

    frames = []
    original = glfwcontext.GLFWContext.SwapBuffers

    def capturing(self):
        frames.append(read_back_buffer()[0].astype(int))
        return original(self)

    monkeypatch.setattr(glfwcontext.GLFWContext, 'SwapBuffers', capturing)
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '1')
    platform = ViewPlatform(position=(0.0, 0.0, 6.0), orientation=(0, 1, 0, 0))
    stale = PlanarReflector(interval=1000)
    rendered = render_scene(
        _room(_mirror(x=-2.0, size=3.5,
                      reflector=PlanarReflector(interval=1, priority=100.0)),
              _mirror(x=2.0, size=3.5, reflector=stale)),
        frames=4, size=(240, 120), layout=lambda context: ViewLayout.single(platform))
    platform.setPosition((0.01, 0.0, 6.0))
    rendered.context.OnDraw(force=1)
    assert renderpass.FLAT.stats.mirrorViews == 1
    kept = frames[-1]
    stale.interval = 1
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '2')
    from OpenGLContext import renderoptions
    renderoptions.reset_env_cache()
    rendered.context.OnDraw(force=1)
    assert renderpass.FLAT.stats.mirrorViews == 2
    fresh = frames[-1]
    right = (slice(None), slice(120, None))
    assert (fresh[right][..., 0] > 120).sum() > 500      # the box, in the mirror
    differing = (np.abs(kept[right] - fresh[right]).max(axis=-1) > 24).mean()
    assert differing <= 0.001
