"""Vegetation and terrain in a shared draw of several views (GL, PBR core).

Ground and instanced vegetation draw with programs of their own. Compiled for a
shared draw, one draw of each reaches every view that sees it -- the editor's
views and a frame's mirror views alike -- and the picture is the one each view
drawn in turn gives.
"""
import numpy as np
import pytest

glfw = pytest.importorskip("glfw")

from PIL import Image

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.terrain.ground import GroundPatch, GroundShading
from OpenGLContext.scenegraph.terrain.heightfield import HeightField
from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.field import _drawn
from tests.unit.glrender import base_env, frames_of
from tests.unit.test_planar_mirror_gl import _mirror
from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.multiview.views import View, ViewLayout
from OpenGLContext.passes import renderpass

EXTENT = 60.0
WIDTH, HEIGHT = 240, 120


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    return monkeypatch


@pytest.fixture
def images(tmp_path):
    ground = tmp_path / 'grass.png'
    Image.new('RGBA', (16, 16), (70, 110, 40, 255)).save(ground)
    control = tmp_path / 'control.png'
    Image.new('RGBA', (8, 8), (255, 0, 0, 0)).save(control)
    card = tmp_path / 'card.png'
    Image.new('RGBA', (8, 8), (180, 40, 160, 255)).save(card)
    return str(ground), str(control), str(card)


def _ground(images):
    grass, control, _card = images
    field = HeightField(np.zeros((9, 9)), EXTENT, 1.0)
    vertices, indices = field.mesh()
    shading = GroundShading(extent=EXTENT, layers=['grass'], control=control,
                            shading=np.ones((8, 8), 'f'),
                            material_fn=lambda *_args, **_named: {'color': grass})
    return basenodes.Shape(geometry=GroundPatch(shading, vertices, indices))


def _cards(images, count=24):
    rng = np.random.default_rng(3)
    positions = np.c_[rng.uniform(-8, 8, count), np.zeros(count), rng.uniform(-14, -2, count)]
    return _drawn(InstancedBillboards(positions.astype('f4'), np.zeros(count, 'f4'),
                                      np.full(count, 2.0, 'f4'), images[2]))


def _scene(images):
    return [basenodes.NavigationInfo(headlight=False),
            basenodes.DirectionalLight(direction=(0.0, -1.0, -0.3)),
            _ground(images), _cards(images)]


def _two_views(context):
    def camera(x):
        return ViewPlatform(position=(x, 1.7, 6.0), orientation=(0, 1, 0, 0))

    return ViewLayout.split(View(camera(-1.0), name='left'), View(camera(1.0), name='right'))


def _drawn_frame(render_scene, env, images, strategy):
    env.setenv('OPENGLCONTEXT_MULTIVIEW', strategy)
    frame = frames_of(render_scene, _scene(images), frames=3, size=(WIDTH, HEIGHT),
                      layout=_two_views)[-1].astype(int)
    if renderpass.FLAT.multiviewStrategy != strategy:
        pytest.skip('this driver cannot draw with %s' % strategy)
    return frame, renderpass.FLAT.stats.draws


@pytest.mark.parametrize('strategy', ['vertex', 'geometry'])
def test_ground_and_cards_draw_once_for_both_views_and_look_the_same(
        render_scene, env, images, strategy):
    shared, shared_draws = _drawn_frame(render_scene, env, images, strategy)
    in_turn, in_turn_draws = _drawn_frame(render_scene, env, images, 'sequential')
    assert (shared[..., 0] > 150).sum() > 50, 'the cards were drawn'
    differing = (np.abs(shared - in_turn).max(axis=-1) > 12).mean()
    assert differing < 0.01
    assert (shared_draws, in_turn_draws) == (2, 4)


def test_a_mirror_shows_the_ground_in_front_of_it(render_scene, env, images):
    """The ground is culled by the side it faces, and a mirror turns that over."""
    env.setenv('OPENGLCONTEXT_MULTIVIEW', 'sequential')
    scene = [basenodes.Viewpoint(position=(0.0, 1.7, 6.0), orientation=(1, 0, 0, -0.1)),
             basenodes.NavigationInfo(headlight=False),
             basenodes.DirectionalLight(direction=(0.0, -1.0, -0.3)),
             _ground(images),
             _mirror(y=1.2, z=-3.0, size=2.4)]
    frame = frames_of(render_scene, scene, frames=4, size=(160, 120))[-1].astype(int)
    middle = frame[40:60, 70:90]
    green = (middle[..., 1] > middle[..., 0] + 20) & (middle[..., 1] > 50)
    assert green.mean() > 0.2


@pytest.mark.parametrize('strategy', ['vertex', 'geometry'])
def test_mirrors_draw_the_ground_and_cards_once_however_many_there_are(
        render_scene, env, images, strategy):
    """Ground and vegetation share the mirror views' submission too, and no
    longer count against the budget of views that draw on their own."""
    env.setenv('OPENGLCONTEXT_MULTIVIEW', strategy)
    env.setenv('OPENGLCONTEXT_REFLECTION_VIEWS', '16')
    env.setenv('OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS', '0')
    counts = []
    for mirrors in (2, 4):
        scene = [basenodes.Viewpoint(position=(0.0, 1.7, -16.0)),
                 basenodes.NavigationInfo(headlight=False),
                 basenodes.DirectionalLight(direction=(0.0, -1.0, -0.3)),
                 _ground(images), _cards(images)]
        scene += [_mirror(x=x, y=1.5, z=-24.0, size=2.5)
                  for x in np.linspace(-4.5, 4.5, mirrors)]
        render_scene(scene, frames=4, size=(WIDTH, HEIGHT))
        if renderpass.FLAT.multiviewStrategy != strategy:
            pytest.skip('this driver cannot draw with %s' % strategy)
        stats = renderpass.FLAT.stats
        counts.append((stats.mirrorViews, stats.mirrorDraws))
    assert [views for views, _draws in counts] == [2, 4]
    assert counts[0][1] == counts[1][1] == 2
