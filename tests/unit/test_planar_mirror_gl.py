"""A mirror shows what stands in front of it (GL, PBR core).

A mirror hangs on the far wall and a red box stands behind the camera, where
the camera cannot see it: red reaches the screen only through the mirror. The
arithmetic is asserted without a window in ``test_planar_reflection.py`` and
``test_reflection_planner.py``; these are the claims that need one.
"""
import os

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial  # noqa: E402
from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: E402
from OpenGLContext.scenegraph.reflector import PlanarReflector  # noqa: E402
from tests.unit.glrender import base_env, frames_of  # noqa: E402

SIZE = (160, 120)


def _mirror(x=0.0, z=-4.0, size=6.0, reflector=None, y=0.0, **material):
    half = size / 2.0
    mesh = PBRMesh(
        positions=np.array([(-half, -half, 0), (half, -half, 0),
                            (half, half, 0), (-half, half, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32))
    settings = dict(baseColor=(1.0, 1.0, 1.0), metallic=1.0, roughness=0.0)
    settings.update(material)
    return basenodes.Transform(translation=(x, y, z), children=[basenodes.Shape(
        geometry=mesh, appearance=basenodes.Appearance(material=PBRMaterial(
            reflector=PlanarReflector() if reflector is None else reflector,
            **settings)))])


def _box(x, z, colour, size=3.0, y=0.0):
    return basenodes.Transform(translation=(x, y, z), children=[basenodes.Shape(
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
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS',
               os.environ.get('OPENGLCONTEXT_REFLECTION_VIEWS') or '16')
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


@pytest.mark.parametrize('strategy', ['vertex', 'geometry'])
def test_mirror_views_share_one_set_of_programs_however_many_there_are(
        render_scene, env, strategy):
    """The count of mirror views changes as the camera turns; compiling a set
    of programs for each count stalls the frame that first meets it."""
    from OpenGLContext.passes import renderpass
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '8')
    _mirror_draws(render_scene, env, strategy, 3)
    sets = renderpass.FLAT.shader_program.__dict__.get('_program_sets', {})
    assert sorted(views for _strategy, views in sets) == [0, 8]


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


def _floor(**material):
    """A polished floor, 20 metres square, at y = -1, facing up."""
    half = 10.0
    mesh = PBRMesh(
        positions=np.array([(-half, 0, half), (half, 0, half),
                            (half, 0, -half), (-half, 0, -half)], 'f'),
        normals=np.array([(0, 1, 0)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32))
    settings = dict(baseColor=(0.05, 0.05, 0.06), metallic=0.0, roughness=0.05)
    settings.update(material)
    return basenodes.Transform(translation=(0.0, -1.0, 0.0), children=[basenodes.Shape(
        geometry=mesh, appearance=basenodes.Appearance(material=PBRMaterial(
            reflector=PlanarReflector(), **settings)))])


def _lamp_room():
    """A camera looking down the floor at a lamp standing a metre above it."""
    return [basenodes.Viewpoint(position=(0.0, 1.0, 6.0), orientation=(1, 0, 0, -0.25)),
            basenodes.NavigationInfo(headlight=False),
            basenodes.DirectionalLight(direction=(0.0, -1.0, 0.0), intensity=0.2),
            basenodes.Transform(translation=(0.0, 1.0, 0.0), children=[
                _box(0.0, -3.0, (1.0, 0.9, 0.2), size=1.0)]),
            _floor()]


def _yellow_rows(frame):
    """Rows of the frame, top first, holding any of the lamp's yellow."""
    pixels = frame.astype(int)
    yellow = ((pixels[..., 0] > 90) & (pixels[..., 1] > 80)
              & (pixels[..., 2] * 4 < pixels[..., 1] * 3))
    return np.flatnonzero(yellow.any(axis=1))


def test_a_polished_floor_reflects_the_lamp_standing_on_it(render_scene, env):
    """A dielectric floor reflects faintly looking down, and it reflects the lamp."""
    from OpenGLContext import renderoptions
    lit = frames_of(render_scene, _lamp_room(), frames=3, size=SIZE)[-1]
    env.setenv('OPENGLCONTEXT_PLANAR_REFLECTIONS', '0')
    renderoptions.reset_env_cache()
    plain = frames_of(render_scene, _lamp_room(), frames=3, size=SIZE)[-1]
    # The lamp itself, and below it on screen its reflection in the floor.
    assert _yellow_rows(lit).max() > _yellow_rows(plain).max() + 8


def _twelve(render_scene, env, strategy):
    env.setenv('OPENGLCONTEXT_MULTIVIEW', strategy)
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '16')
    mirrors = [_mirror(x=x, z=-4.0 - 0.01 * index, size=1.6)
               for index, x in enumerate(np.linspace(-5.0, 5.0, 12))]
    frame = frames_of(render_scene, [
        basenodes.Viewpoint(position=(0.0, 0.0, 6.0)),
        basenodes.NavigationInfo(headlight=False),
        basenodes.DirectionalLight(direction=(0.0, -1.0, 0.0)),
        _wall(7.5, (0.2, 0.6, 0.2)), _wall(-7.5, (0.2, 0.2, 0.6)),
        _box(0.0, 9.0, (1.0, 0.0, 0.0))] + mirrors, frames=3, size=(320, 120))[-1]
    from OpenGLContext.passes import renderpass
    if renderpass.FLAT.multiviewStrategy != strategy:
        pytest.skip('this driver cannot draw with %s' % strategy)
    assert renderpass.FLAT.stats.mirrorViews == 12
    return frame.astype(int)


@pytest.mark.parametrize('strategy', ['vertex', 'geometry'])
def test_twelve_mirrors_draw_alike_whichever_way_they_are_drawn(render_scene, env, strategy):
    shared = _twelve(render_scene, env, strategy)
    in_turn = _twelve(render_scene, env, 'sequential')
    differing = (np.abs(shared - in_turn).max(axis=-1) > 8).mean()
    assert differing < 0.005


def test_a_still_scene_asks_for_frames_until_its_mirrors_settle(render_scene, env):
    """Drawn only when asked, the hall asks until every mirror is settled, then stops."""
    from OpenGLContext.bin.mirrors_demo import MirrorHall
    from OpenGLContext.passes import renderpass
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '2')
    rendered = render_scene(MirrorHall().children, frames=1, size=(320, 180))
    context = rendered.context
    drawn = []
    # Two mirror views a frame, and the hall's mirrors and the mirrors seen in
    # them come to a few dozen reflections: settled within twenty-odd frames.
    for _ in range(40):
        before = renderpass.FLAT._reflection_planner.frame
        # What the main loop does: force a frame where one was asked for.
        context.OnDraw(force=1 if context.redrawRequest.is_set() else 0)
        drawn.append(renderpass.FLAT._reflection_planner.frame > before)
    planner = renderpass.FLAT._reflection_planner
    assert drawn[0] and not drawn[-1]
    assert planner._held and not any(held.provisional for held in planner._held.values())
    # Every mirror reads a tile held for it, several in one plane reading one.
    read = {planner._aliases.get(key, key) for key in renderpass.FLAT._reflection_lookups}
    assert read == set(planner._held)



def _floor_and_wall():
    return [basenodes.Viewpoint(position=(0.0, 1.0, 6.0), orientation=(1, 0, 0, -0.2)),
            basenodes.NavigationInfo(headlight=False),
            basenodes.DirectionalLight(direction=(0.0, -1.0, 0.0)),
            _box(0.0, 9.0, (1.0, 0.0, 0.0), size=4.0, y=6.5),
            _mirror(y=1.5, size=3.0),
            _floor(baseColor=(0.9, 0.9, 0.9), metallic=1.0, roughness=0.02)]


def test_a_mirror_seen_in_a_mirror_shows_its_own_reflection(render_scene, env):
    """The floor reflects the wall mirror, and the wall mirror reflects the box.

    The box stands behind the camera, so the only way red reaches the floor is
    through the wall mirror's reflection, seen in the floor. It stands high,
    where the wall mirror seen from under the floor looks: the camera
    reflected in the floor and then in the wall looks up through the wall.
    """
    scene = _floor_and_wall()
    frame = frames_of(render_scene, scene, frames=6, size=SIZE)[-1].astype(int)
    height = frame.shape[0]
    floor = frame[int(height * 0.7):]
    red = (floor[..., 0] > 120) & (floor[..., 0] > floor[..., 1] + 60)
    assert int(red.sum()) > 40


def test_a_still_scene_settles_with_each_mirror_in_the_other(render_scene, env):
    """Drawn only when asked, a floor reflecting a wall mirror ends up showing
    what the wall mirror shows."""
    scene = _floor_and_wall()
    frames = []
    from OpenGLContext import glfwcontext
    from OpenGLContext.capture import read_back_buffer
    original = glfwcontext.GLFWContext.SwapBuffers

    def capturing(self):
        frames.append(read_back_buffer()[0].astype(int))
        return original(self)

    env.setattr(glfwcontext.GLFWContext, 'SwapBuffers', capturing)
    context = render_scene(scene, frames=1, size=SIZE).context
    for _ in range(12):
        context.OnDraw(force=1 if context.redrawRequest.is_set() else 0)
    assert not context.redrawRequest.is_set()
    floor = frames[-1][int(frames[-1].shape[0] * 0.7):]
    red = (floor[..., 0] > 120) & (floor[..., 0] > floor[..., 1] + 60)
    assert int(red.sum()) > 40


def _behind_the_camera():
    """A mirror behind the camera, facing the one in front of it, and a red box
    only that mirror's reflection can reach: behind the front mirror's plane
    and outside the camera's view."""
    half = 6.0
    mesh = PBRMesh(
        positions=np.array([(-half, -half, 0), (half, -half, 0),
                            (half, half, 0), (-half, half, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32))
    back = basenodes.Transform(
        translation=(0.0, 0.0, 10.0), rotation=(0.0, 1.0, 0.0, np.pi),
        children=[basenodes.Shape(geometry=mesh, appearance=basenodes.Appearance(
            material=PBRMaterial(reflector=PlanarReflector(), baseColor=(1.0, 1.0, 1.0),
                                 metallic=1.0, roughness=0.0)))])
    return [basenodes.Viewpoint(position=(0.0, 0.0, 6.0)),
            basenodes.NavigationInfo(headlight=False),
            basenodes.DirectionalLight(direction=(0.0, -1.0, 0.0)),
            _box(10.0, -8.0, (1.0, 0.0, 0.0), size=2.0),
            _mirror(), back]


def test_a_mirror_out_of_view_shows_its_reflection_in_a_mirror_in_view(render_scene, env):
    """The mirror behind the camera is seen only in the front mirror, and what
    it reflects there is drawn from the front mirror's camera."""
    red = _red_anywhere(frames_of(render_scene, _behind_the_camera(), frames=8,
                                  size=SIZE)[-1])
    env.setenv('OPENGLCONTEXT_PLANAR_REFLECTIONS', '0')
    unreflected = _red_anywhere(frames_of(render_scene, _behind_the_camera(), frames=3,
                                          size=SIZE)[-1])
    assert unreflected == 0
    assert red > 20


def _red_anywhere(frame):
    frame = frame.astype(int)
    return int(((frame[..., 0] > 120) & (frame[..., 0] > frame[..., 1] + 60)).sum())


def test_one_bounce_leaves_a_mirror_in_a_mirror_reflecting_the_probe(render_scene, env):
    env.setenv('OPENGLCONTEXT_REFLECTION_BOUNCES', '1')
    assert _red_anywhere(frames_of(render_scene, _behind_the_camera(), frames=8,
                                   size=SIZE)[-1]) == 0


def test_a_mirror_reflects_its_reflectance_of_the_light(render_scene, env):
    """A mirror is told from an opening by reflecting less than all of it."""
    def red_level(reflectance):
        frame = frames_of(render_scene, _room(_mirror(reflector=PlanarReflector(
            replace=True, reflectance=reflectance))), frames=3, size=SIZE)[-1]
        height, width = frame.shape[:2]
        return float(frame[height // 2 - 6:height // 2 + 6,
                           width // 2 - 6:width // 2 + 6, 0].mean())
    full, half = red_level(1.0), red_level(0.3)
    assert full > 120
    assert half < full * 0.85


def test_a_shape_made_a_mirror_while_out_of_view_is_found_in_a_mirror(render_scene, env):
    """The mirror behind the camera is plain metal until its material is given
    a reflector, and no view but the front mirror's can see it."""
    scene = _behind_the_camera()
    back = scene[-1].children[0].appearance.material
    reflector, back.reflector = back.reflector, None
    rendered = render_scene(scene, frames=4, size=SIZE)
    from OpenGLContext.capture import read_back_buffer
    context = rendered.context
    before = _red_anywhere(read_back_buffer()[0])
    back.reflector = reflector
    for _ in range(6):
        context.OnDraw(force=1)
    assert before == 0
    assert _red_anywhere(read_back_buffer()[0]) > 20


def test_a_scene_without_mirrors_looks_at_no_shape_for_one(render_scene, env, monkeypatch):
    from OpenGLContext.passes import reflection
    asked = []
    real = reflection.reflector_for
    monkeypatch.setattr(reflection, 'reflector_for',
                        lambda record: asked.append(record) or real(record))
    boxes = [_box(x, -4.0, (0.2, 0.6, 0.2), size=1.0) for x in range(-3, 4)]
    frames_of(render_scene, _room(*boxes), frames=3, size=SIZE)   # boxes, no mirror
    assert asked == []


def test_the_planner_looks_only_at_the_mirrors(render_scene, env, monkeypatch):
    from OpenGLContext.passes import reflection
    from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
    asked = []
    real = ReflectionPlanner._surface
    monkeypatch.setattr(ReflectionPlanner, '_surface',
                        lambda self, frame, record, eye: asked.append(record[5])
                        or real(self, frame, record, eye))
    boxes = [_box(x, -2.0, (0.2, 0.6, 0.2), size=0.5) for x in range(-3, 4)]
    frames_of(render_scene, _room() + boxes, frames=3, size=SIZE)
    assert asked
    assert all(reflection.shape_reflector(shape) is not None for shape in asked)


def _points_behind(z=9.0):
    """A cloud of points behind the camera: one draw cannot serve several
    views with it, and only a mirror sees it."""
    from OpenGL.GL import GL_POINTS
    grid = np.array([(x, y, 0.0) for x in np.linspace(-2, 2, 5)
                     for y in np.linspace(-2, 2, 5)], 'f')
    mesh = PBRMesh(positions=grid, normals=np.tile((0, 0, 1), (len(grid), 1)),
                   draw_mode=GL_POINTS)
    return basenodes.Transform(translation=(0.0, 0.0, z), children=[basenodes.Shape(
        geometry=mesh, appearance=basenodes.Appearance(material=PBRMaterial(
            baseColor=(1.0, 1.0, 0.0))))])


@pytest.mark.parametrize('behind, views', [(False, 2), (True, 1)])
def test_a_mirror_view_seeing_what_a_shared_draw_refuses_is_a_separate_view(
        render_scene, env, behind, views):
    """What counts is what the mirror's own camera sees, which here is behind
    the viewer's: with one separate view a frame, only one mirror is drawn."""
    from OpenGLContext.passes import renderpass
    from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '4')
    env.setenv('OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS', '1')
    scene = _room(_mirror(x=-2.5, size=3.0, reflector=PlanarReflector(interval=1)),
                  _mirror(x=2.5, size=3.0, reflector=PlanarReflector(interval=1)))
    if behind:
        scene.append(_points_behind())
    drawn = []
    real = ReflectionPlanner.plan

    def planning(self, *args, **named):
        plan = real(self, *args, **named)
        drawn.append(len(plan.draws))
        return plan

    env.setattr(ReflectionPlanner, 'plan', planning)
    render_scene(scene, frames=4, size=SIZE)
    assert renderpass.FLAT is not None
    assert drawn[-1] == views


def test_the_atlas_is_not_on_its_unit_while_it_is_drawn_into(render_scene, env):
    """A program able to sample the texture it draws into makes a feedback
    loop; with no mirror seen in a mirror, nothing is on the unit."""
    from OpenGL import GL as gl
    from OpenGLContext.passes.reflection import REFLECTION_UNIT
    from OpenGLContext.passes.reflectionatlas import ReflectionAtlas
    found = []
    real = ReflectionAtlas.begin

    def begin(self):
        gl.glActiveTexture(gl.GL_TEXTURE0 + REFLECTION_UNIT)
        found.append((int(gl.glGetIntegerv(gl.GL_TEXTURE_BINDING_2D)), self.texture))
        gl.glActiveTexture(gl.GL_TEXTURE0)
        return real(self)

    env.setattr(ReflectionAtlas, 'begin', begin)
    render_scene(_room(_mirror(reflector=PlanarReflector(interval=1))), frames=4, size=SIZE)
    assert len(found) >= 2
    assert all(bound != texture for bound, texture in found)


def test_mirror_views_are_drawn_one_at_a_time_where_the_shared_programs_fail(
        render_scene, env):
    """A driver refusing the programs one draw serves several views with
    leaves each mirror view drawn in turn, and the mirrors reflect as before."""
    from OpenGLContext.passes import renderpass, shaderpass
    env.setenv('OPENGLCONTEXT_MULTIVIEW', 'vertex')

    def pair():
        return _room(_mirror(x=-2.0, size=3.5), _mirror(x=2.0, size=3.5))

    shared = _red_anywhere(frames_of(render_scene, pair(), frames=3, size=SIZE)[-1])
    if renderpass.FLAT.multiviewStrategy != 'vertex':
        pytest.skip('this driver cannot draw with vertex')
    refused = []
    real = shaderpass.VRML97ShaderProgram.select_program_set

    def select(self, views, strategy='geometry'):
        if views:
            refused.append(views)
            return False
        return real(self, views, strategy)

    env.setattr(shaderpass.VRML97ShaderProgram, 'select_program_set', select)
    alone = _red_anywhere(frames_of(render_scene, pair(), frames=3, size=SIZE)[-1])
    assert refused
    assert shared > 100 and alone >= 0.9 * shared
