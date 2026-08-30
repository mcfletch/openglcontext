"""What the receiver's depth bias has to get right, measured on a real driver.

The bias is a nudge toward the light before the depth comparison, and it is
squeezed between two failures. Too little and a lit surface reports itself as its
own occluder -- acne, a shimmer of dark speckles across ground the light plainly
reaches. Too much and a shadow lets go of the object casting it, floating away
from the contact point and leaving a lit gap where the two meet.

Both are pixel facts, and neither is visible in the arithmetic: the conversion
from texels to depth is checked without GL in ``test_shadow_depth_bias``, and a
conversion that is right and never bound looks exactly like one that is wrong.
Each test here therefore renders a scene chosen to show one of the two failures
plainly, and measures it.
"""
import os

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import numpy as np  # noqa: E402
import pytest  # noqa: E402

glfw = pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402

pytest_plugins = ['tests.unit.test_passes_render_gl']

#: The wall the shadows land on: far enough back to fill the frame, wide enough
#: that the light's map has to cover a large area, which is where too small a
#: bias shows as acne.
WALL_Z = -6.0
WALL = (30.0, 30.0, 0.3)
WALL_FACE = WALL_Z + WALL[2] / 2.0

#: A caster resting against the wall, so its shadow's near edge is its own
#: silhouette edge and any gap between them is the shadow letting go.
BOX = 2.0
BOX_CENTRE = (1.5, 1.5, WALL_FACE + BOX / 2.0)


@pytest.fixture(autouse=True)
def shadowed_env(monkeypatch):
    """Shadows on, in the core profile, with the frame-rate probe out of it."""
    from tests.unit.test_passes_render_gl import _base_env
    _base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='3')


def wall_scene(light):
    """A grey wall, a red box against it, and one shadow-casting light."""
    return [
        basenodes.Transform(translation=(0, 0, WALL_Z), children=[basenodes.Shape(
            geometry=basenodes.Box(size=WALL),
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=(0.75, 0.75, 0.75), ambientIntensity=0.3)),
        )]),
        basenodes.Transform(translation=BOX_CENTRE, children=[basenodes.Shape(
            geometry=basenodes.Box(size=(BOX, BOX, BOX)),
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=(0.9, 0.1, 0.1), ambientIntensity=0.3)),
        )]),
        light,
    ]


def spot():
    """A spot up and to the right, so the box's shadow falls down-left of it."""
    return basenodes.SpotLight(
        location=(7, 7, 7), direction=(-9, -9, -13), cutOffAngle=0.9,
        color=(1, 1, 1), intensity=1.0, ambientIntensity=0.3, attenuation=(1, 0, 0),
    )


#: The second scene: a pole standing on a floor with the light beside it. The
#: pole reaches past the light, so the map's near plane is fitted right up
#: against it and its far plane out at the floor's far corner -- a range of a
#: hundred to one, which is where projected depth is at its least linear and a
#: bias fixed in depth units is worth a long way across the floor.
POLE = (0.5, 8.0, 0.5)
POLE_AT = (2.0, 3.62, 0.0)
FLOOR = (5.0, 0.05, 5.0)
FLOOR_TOP = -0.38 + FLOOR[1] / 2.0


def pole_scene():
    """A red pole standing on a grey floor, lit by a spot three units away."""
    return [
        basenodes.Viewpoint(position=(0.5, 1.0, 3.0)),
        basenodes.Transform(translation=(0, -0.38, 0), children=[basenodes.Shape(
            geometry=basenodes.Box(size=FLOOR),
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=(0.7, 0.7, 0.7), shininess=0.8, ambientIntensity=0.1)),
        )]),
        basenodes.Transform(translation=POLE_AT, children=[basenodes.Shape(
            geometry=basenodes.Box(size=POLE),
            appearance=basenodes.Appearance(material=basenodes.Material(
                diffuseColor=(1.0, 0, 0), ambientIntensity=0.4, shininess=0.0)),
        )]),
        basenodes.SpotLight(
            location=(3, 3, 3), direction=(-3, -3, -3), color=(0.75, 0.75, 1.0),
            intensity=0.5, ambientIntensity=0.05, attenuation=(1, 0, 0)),
    ]


def foot_gap(render_scene):
    """Pixels between the pole's foot and the nearest shadow it casts."""
    from tests.unit.test_passes_render_gl import frames_of
    image = frames_of(render_scene, pole_scene(), frames=6)[-1].astype(int)
    lit = frames_of(render_scene, pole_scene(), frames=6, shadows=False)[-1].astype(int)
    if image.shape != lit.shape:
        pytest.skip("the two renders disagree on size")
    shadow = (lit.mean(2) - image.mean(2)) > 20
    pole = ((image[:, :, 0] > image[:, :, 1] + 60)
            & (image[:, :, 0] > image[:, :, 2] + 60))
    rows, columns = np.nonzero(pole)
    if not len(rows):
        pytest.skip("the pole did not render")
    foot = (rows.max(), (columns.min() + columns.max()) // 2)
    shadow_rows, shadow_columns = np.nonzero(shadow)
    if not len(shadow_rows):
        return float('inf')
    return float(np.hypot(shadow_rows - foot[0], shadow_columns - foot[1]).min())


def frame(render_scene, light):
    """The last frame the wall scene draws with ``light`` in it."""
    from tests.unit.test_passes_render_gl import frames_of
    return frames_of(render_scene, wall_scene(light), frames=6)[-1].astype(int)


def _masks(image):
    """(box, wall, shadow) masks: the caster, the lit receiver, the dark part."""
    grey = image.mean(2)
    box = (image[:, :, 0] > image[:, :, 1] + 40) & (image[:, :, 0] > image[:, :, 2] + 40)
    receiver = ~box & (grey > 8)
    shadow = receiver & (grey < np.percentile(grey[receiver], 60) * 0.75)
    return box, receiver & ~shadow, shadow


def _speckle(image, lit):
    """Fraction of the lit receiver carrying single-pixel darkening.

    A discrete Laplacian answers "is this pixel unlike its neighbours", which is
    what acne is and what a shadow edge or a shaded gradient is not: an edge is
    a step, and its Laplacian is confined to the step itself.
    """
    grey = image.mean(2)
    lap = np.abs(grey[1:-1, 1:-1] * 4 - grey[:-2, 1:-1] - grey[2:, 1:-1]
                 - grey[1:-1, :-2] - grey[1:-1, 2:])
    inner = lit[1:-1, 1:-1]
    if not inner.any():
        pytest.skip("nothing lit in the frame; the scene did not render")
    return float((lap[inner] > 4.0).mean())


def test_a_lit_wall_does_not_shadow_itself(render_scene):
    """No acne: a surface the light plainly reaches stays smooth.

    The wall is 30 units across and the light 12 away, so one shadow texel covers
    a good deal of it -- which is exactly when a bias too small to clear the map's
    own quantisation lets the wall report itself as its own occluder.
    """
    image = frame(render_scene, spot())
    _, lit, _ = _masks(image)
    assert _speckle(image, lit) < 0.02


def test_a_shadow_keeps_hold_of_the_object_casting_it(render_scene):
    """No peter-panning: the shadow starts at the pole's foot, not short of it.

    A vertical pole standing on a floor with the light close by is where a bias
    in the map's own depth units is worth the most: depth there is steep in 1/z,
    so the offset that clears the far end of the map floats the near end of the
    shadow off the ground.
    """
    gap = foot_gap(render_scene)
    assert gap <= 12, f"the shadow starts {gap:.0f}px from the foot casting it"


def test_the_shadow_is_a_shadow_and_not_the_whole_wall(render_scene):
    """A bias big enough to hide acne must not have eaten the lit wall.

    Both failures above can be made to pass by a shadow that covers everything
    or nothing, so pin the shape: the box shades a part of the wall, not most of
    it and not none.
    """
    image = frame(render_scene, spot())
    _, lit, shadow = _masks(image)
    covered = shadow.sum() / float(shadow.sum() + lit.sum())
    assert 0.02 < covered < 0.5


@pytest.mark.parametrize('light', ['point', 'directional'])
def test_the_other_light_types_reach_their_contact_too(render_scene, light):
    """A cube map and a cascade convert their own bias, and are checked for it.

    They are separate conversions -- one perspective, one orthographic -- so a
    fix that only reached the spot path would pass every test above.
    """
    node = (basenodes.PointLight(
        location=(7, 7, 7), color=(1, 1, 1), intensity=1.0,
        ambientIntensity=0.3, attenuation=(1, 0, 0))
        if light == 'point' else
        basenodes.DirectionalLight(
            direction=(-0.7, -0.7, -1.0), color=(1, 1, 1),
            intensity=1.0, ambientIntensity=0.3))
    image = frame(render_scene, node)
    box, lit, shadow = _masks(image)
    assert _speckle(image, lit) < 0.02
    assert shadow.any(), "the box cast no shadow at all"


def test_a_lights_own_bias_reaches_its_own_shadow(render_scene):
    """The field is not decoration: turning it off brings the acne back.

    Measured against the same wall, a light asking for no slack speckles an
    order of magnitude more of it than the default does. This is also what says
    the per-light field is read where the map is built rather than collapsed
    into one number for every light in the scene.
    """
    unbiased, biased = spot(), spot()
    unbiased.shadowBias = 0.0
    _, lit_off, _ = _masks(frame(render_scene, unbiased))
    speckled = _speckle(frame(render_scene, unbiased), lit_off)
    _, lit_on, _ = _masks(frame(render_scene, biased))
    smooth = _speckle(frame(render_scene, biased), lit_on)
    assert speckled > smooth * 10


def test_more_slack_than_asked_for_still_holds_the_contact(render_scene, monkeypatch):
    """Five times the default must not float the shadow off the box.

    In texels the offset scales with the same quantisation the shadow edge is
    already subject to, so a generous bias cannot detach the contact -- which is
    what a bias in the map's own depth units did, and the reason for the unit.
    """
    from OpenGLContext.passes import shadowmath
    generous = shadowmath.depth_bias_terms

    monkeypatch.setattr(
        shadowmath, 'depth_bias_terms',
        lambda projection, texel_bias, resolution: generous(
            projection, texel_bias * 5.0, resolution))
    assert foot_gap(render_scene) <= 12


def test_a_bias_in_depth_units_cannot_do_both(render_scene, monkeypatch):
    """The trade-off the texel unit removes, shown on the same scene.

    A bias fixed in the map's own depth units has to be set large enough for the
    farthest, coarsest part of a map and is then far too large near the light,
    where it detaches the shadow from what casts it. Substituting that conversion
    -- a flat offset, the shape the shader used to be given -- for the texel one
    reproduces the gap; the tests above say the texel conversion does not have it.
    """
    from OpenGLContext.passes import shadowmath

    def flat_offset(projection, texel_bias, resolution):
        return (0.0, 0.0, 0.0015 * texel_bias)

    monkeypatch.setattr(shadowmath, 'depth_bias_terms', flat_offset)
    gap = foot_gap(render_scene)
    assert gap > 20, f"expected the flat offset to detach the shadow, gap was {gap:.0f}px"
