"""X3D's GaussianSplats node, drawn in a real context.

Each test draws a few splats in front of a camera at the origin looking down
-z, through the renderer the test names, and reads the frame back. The
arithmetic is held by tests/unit/test_splatmath.py; these hold the draw to it:
the falloff's width, opacity, the order, the colour space, the view-dependent
colour, picking, shadows and the frame's GL work.
"""
import math

import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes, splatmath
from OpenGLContext.scenegraph.gaussiansplats import (
    GaussianSplats, HARMONIC_FIELDS, from_arrays,
)
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.layers import check_failing_layer
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.testing.scenes import drawn_image, scene_context
from OpenGLContext.testing.stillframe import check_still_frame

SIZE = 96
#: The pixel focal length of the default 0.785-radian Viewpoint in a square view.
FOCAL = SIZE / 2 / math.tan(0.785398 / 2)
IDENTITY = (0.0, 0.0, 0.0, 1.0)
PBR = {'OPENGLCONTEXT_RENDERER': 'pbr'}
FLAT = {'OPENGLCONTEXT_RENDERER': 'flat'}


@pytest.fixture
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


def _dc(rgb):
    """The degree-0 coefficient whose colour is `rgb` (before the clamp)"""
    return (np.asarray(rgb, float) - 0.5) / splatmath.SH_C0


def _splats(positions, scales, colours, opacities=None, **named):
    count = len(positions)
    return from_arrays(
        positions=positions, rotations=np.tile(IDENTITY, (count, 1)),
        scales=scales, opacities=opacities if opacities is not None else [1.0] * count,
        harmonics=[[_dc(colour) for colour in colours]], **named)


def _scene(*children, background=None):
    found = [basenodes.Viewpoint(position=(0, 0, 0))]
    if background is not None:
        found.append(basenodes.Background(skyColor=[background]))
    return found + list(children)


def _draw(children, environment=PBR, frames=2):
    with scene_context(children, size=(SIZE, SIZE), environment=environment) as context:
        for _ in range(frames):
            context.OnDraw(force=1)
        return drawn_image(context).astype(float)


def _placed(node, translation=(0.0, 0.0, -4.0), **named):
    return basenodes.Transform(translation=translation, children=[node], **named)


# --- the node ---------------------------------------------------------------


def test_the_loader_reads_the_engines_node():
    from OpenGLContext.loaders.x3d import prototypes
    assert prototypes()['GaussianSplats'] is GaussianSplats
    assert basenodes.GaussianSplats is GaussianSplats


def test_an_x3d_document_builds_the_node():
    from OpenGLContext.loaders.loader import Loader
    document = b'''<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Full" version="4.1"><head><component name="GaussianSplats" level="1"/></head>
<Scene><GaussianSplats DEF="S" positions="0 0 0, 1 0 0"
  orientations="0 0 0 1, 0 0.7071068 0 0.7071068" scales="0.1 0.1 0.1, 0.2 0.2 0.2"
  opacities="0.5 1" sphericalHarmonicsDegree0Coef0="1 0 0, 0 1 0"/></Scene></X3D>'''
    scene = Loader.loads(document, 'splats.x3d')
    node = scene.getDEF('S')
    assert isinstance(node, GaussianSplats)
    assert node.splats().count == 2
    assert np.allclose(node.orientations[1], (0, 0.7071068, 0, 0.7071068))


def test_the_bounds_hold_every_splat():
    node = _splats([(0, 0, 0), (2, 0, 0)], [(0.1, 0.2, 0.3)] * 2, [(1, 0, 0)] * 2)
    volume = node.boundingVolume()
    assert np.allclose(volume.center, (1.0, 0.0, 0.0))
    assert np.allclose(volume.size, (2.6, 1.2, 1.8))


def test_a_given_bounding_box_is_used():
    node = _splats([(0, 0, 0)], [(0.1, 0.1, 0.1)], [(1, 0, 0)],
                   bboxSize=(4, 5, 6), bboxCenter=(1, 2, 3))
    volume = node.boundingVolume()
    assert np.allclose(volume.size, (4, 5, 6)) and np.allclose(volume.center, (1, 2, 3))


def test_no_splats_draw_nothing():
    assert GaussianSplats().drawsNothing()
    assert not _splats([(0, 0, 0)], [(1, 1, 1)], [(1, 1, 1)]).drawsNothing()


def test_an_invisible_set_draws_nothing():
    assert _splats([(0, 0, 0)], [(1, 1, 1)], [(1, 1, 1)], visible=False).drawsNothing()


def test_pointer_events_say_whether_a_pick_reaches_the_splats():
    node = _splats([(0, 0, 0)], [(1, 1, 1)], [(1, 1, 1)])
    assert node.pickable
    node.pointerEvents = False
    assert not node.pickable


def test_the_packed_splats_follow_every_field():
    """Every field, with each degree of coefficients complete so each is read."""
    node = from_arrays([(0, 0, 0), (1, 0, 0)], [IDENTITY] * 2, [(0.1, 0.1, 0.1)] * 2,
                       [1.0, 1.0], [np.zeros((2, 3))] * 16)

    def packed():
        found = node.splats()
        return (found.count, found.degree, found.centres.tobytes(),
                found.covariances.tobytes(), found.opacities.tobytes(),
                found.harmonics.tobytes())

    def fresh():
        found = splatmath.SplatSet.from_fields(
            node.positions, node.orientations, node.scales, node.opacities,
            [getattr(node, name) for name in HARMONIC_FIELDS])
        return (found.count, found.degree, found.centres.tobytes(),
                found.covariances.tobytes(), found.opacities.tobytes(),
                found.harmonics.tobytes())

    edits = [
        ('positions', lambda: setattr(node, 'positions', [(0, 1, 0), (1, 0, 0)])),
        ('orientations', lambda: setattr(node, 'orientations',
                                         [(0, 0, 0.3826834, 0.9238795), IDENTITY])),
        ('scales', lambda: setattr(node, 'scales', [(0.1, 0.3, 0.1), (0.1, 0.1, 0.1)])),
        ('opacities', lambda: setattr(node, 'opacities', [0.5, 1.0])),
        ('sphericalHarmonicsDegree0Coef0',
         lambda: setattr(node, 'sphericalHarmonicsDegree0Coef0', [(1, 1, 1), (0, 0, 0)])),
    ]
    rng = np.random.default_rng(4)
    for name in HARMONIC_FIELDS[1:]:
        values = rng.normal(size=(2, 3))
        edits.append((name, lambda name=name, values=values: setattr(node, name, values)))
    check_memo_inputs(packed, edits, fresh=fresh)


def test_the_bounds_follow_the_fields_they_are_made_from():
    node = _splats([(0, 0, 0)], [(0.1, 0.1, 0.1)], [(1, 0, 0)])

    def box():
        volume = node.boundingVolume()
        return tuple(volume.center) + tuple(volume.size)

    check_memo_inputs(box, [
        ('positions', lambda: setattr(node, 'positions', [(3, 0, 0)])),
        ('scales', lambda: setattr(node, 'scales', [(1, 0.1, 0.1)])),
        ('orientations', lambda: setattr(node, 'orientations',
                                         [(0, 0, 0.7071068, 0.7071068)])),
    ])


def test_from_arrays_sets_the_colour_space_and_the_harmonics():
    node = from_arrays([(0, 0, 0)], [IDENTITY], [(1, 1, 1)], [1.0],
                       [[(1, 0, 0)], [(0, 0, 0)], [(0, 0, 1)], [(0, 0, 0)]],
                       color_space='LIN_REC709_DISPLAY')
    assert node.colorSpace == 'LIN_REC709_DISPLAY'
    assert node.splats().degree == 1
    assert np.allclose(node.sphericalHarmonicsDegree1Coef1, [(0, 0, 1)])


# --- drawn ------------------------------------------------------------------


def _half_maximum_radius(image, channel=0):
    """The radius in pixels of the area brighter than half the peak"""
    values = image[:, :, channel]
    return math.sqrt(np.count_nonzero(values > values.max() / 2.0) / math.pi)


@pytest.mark.usefixtures('core')
@pytest.mark.parametrize('environment', [PBR, FLAT], ids=['pbr', 'flat'])
def test_a_round_splat_falls_off_as_its_gaussian(environment):
    sigma, distance = 0.25, 4.0
    node = _splats([(0, 0, 0)], [(sigma,) * 3], [(1, 1, 1)])
    image = _draw(_scene(_placed(node, (0, 0, -distance))), environment)
    spread = FOCAL * sigma / distance
    expected = math.sqrt(2.0 * math.log(2.0) * (spread ** 2 + splatmath.DILATION))
    assert _half_maximum_radius(image) == pytest.approx(expected, rel=0.08)
    assert image[SIZE // 2, SIZE // 2, 0] >= 245            # 0.99 of white


@pytest.mark.usefixtures('core')
def test_a_long_splat_is_drawn_along_its_axis():
    node = from_arrays([(0, 0, 0)], [(0, 0, 0.3826834, 0.9238795)],   # 45 degrees about z
                       [(0.5, 0.05, 0.05)], [1.0], [[_dc((1, 1, 1))]])
    image = _draw(_scene(_placed(node)))[:, :, 0]
    rows, cols = np.nonzero(image > 128)
    x, y = cols - SIZE / 2, SIZE / 2 - rows                  # y up
    assert np.corrcoef(x, y)[0, 1] > 0.95


@pytest.mark.usefixtures('core')
def test_opacity_blends_over_what_is_behind():
    node = _splats([(0, 0, 0)], [(0.5,) * 3], [(1, 0, 0)], opacities=[0.5])
    image = _draw(_scene(_placed(node), background=(0, 0, 1)))
    centre = image[SIZE // 2, SIZE // 2]
    assert centre[0] == pytest.approx(0.5 * 255, abs=6)
    assert centre[2] == pytest.approx(0.5 * 255, abs=6)


@pytest.mark.usefixtures('core')
def test_the_nearer_splat_is_drawn_over_the_farther():
    node = _splats([(0, 0, 1), (0, 0, -1)], [(0.4,) * 3] * 2, [(1, 0, 0), (0, 0, 1)])
    front = _draw(_scene(_placed(node, (0, 0, -5))))
    centre = front[SIZE // 2, SIZE // 2]
    assert centre[0] > 200 and centre[2] < 20


def _composited(centres, sigma, colours, order):
    """The frame splatmath says round splats at eye-space `centres` make, drawn in `order`"""
    centres = np.asarray(centres, float)
    spread = splatmath.projected(np.identity(3) * sigma * sigma, centres, np.identity(3),
                                 (FOCAL, FOCAL))
    x, y = np.meshgrid(np.arange(SIZE) + 0.5 - SIZE / 2, SIZE / 2 - np.arange(SIZE) - 0.5)
    frame = np.zeros((SIZE, SIZE, 3))
    for index in order:
        a, b, c = spread[index]
        centre = FOCAL * centres[index, :2] / -centres[index, 2]
        dx, dy = x - centre[0], y - centre[1]
        reach = (c * dx * dx - 2 * b * dx * dy + a * dy * dy) / (a * c - b * b)
        alpha = np.minimum(0.99, np.exp(-0.5 * reach))
        alpha[(reach > 9.0) | (alpha < 1.0 / 255.0)] = 0.0
        frame = frame * (1.0 - alpha[..., None]) + alpha[..., None] * np.asarray(colours[index])
    return frame * 255.0


@pytest.mark.usefixtures('core')
def test_the_splats_are_drawn_farthest_from_the_camera_first():
    """Off to the side, the red splat is nearer by depth and farther by distance."""
    centres = [(0.8, 0, -2.0), (0.3, 0, -2.1)]
    colours = [(1, 0, 0), (0, 0, 1)]
    node = _splats(centres, [(0.25,) * 3] * 2, colours)
    image = _draw(_scene(_placed(node, (0, 0, 0))))
    by_distance = _composited(centres, 0.25, colours, [0, 1])
    by_depth = _composited(centres, 0.25, colours, [1, 0])
    assert np.abs(by_distance - by_depth).max() > 60
    assert np.abs(image - by_distance).max() < 8


@pytest.mark.usefixtures('core')
def test_the_colour_turns_with_the_splats_and_is_not_bent_by_their_scale():
    """A degree 1 coefficient on x, seen off axis through a stretch along x."""
    harmonics = [[_dc((0.5, 0.5, 0.5))], [(0, 0, 0)], [(0, 0, 0)], [(-2.0, 0, 0)]]
    node = from_arrays([(0.5, 0, 0)], [IDENTITY], [(0.1, 0.4, 0.4)], [1.0], harmonics)
    stretched = basenodes.Transform(scale=(4, 1, 1), children=[node])
    image = _draw(_scene(_placed(stretched, (0, 0, -6))))
    column = round(SIZE / 2 + FOCAL * 2.0 / 6.0)
    seen = splatmath.colours([np.concatenate([[_dc((0.5, 0.5, 0.5))], np.zeros((2, 3)),
                                              [(-2.0, 0, 0)]])],
                             [(2.0, 0.0, -6.0)])[0]
    assert image[SIZE // 2, column, 0] == pytest.approx(0.99 * 255 * seen[0], abs=8)


@pytest.mark.usefixtures('core')
def test_turning_round_sorts_the_splats_again():
    node = _splats([(0, 0, 1), (0, 0, -1)], [(0.4,) * 3] * 2, [(1, 0, 0), (0, 0, 1)])
    turn = basenodes.Transform(rotation=(0, 1, 0, math.pi), children=[node])
    behind = _draw(_scene(_placed(turn, (0, 0, -5))))
    centre = behind[SIZE // 2, SIZE // 2]
    assert centre[2] > 200 and centre[0] < 20


@pytest.mark.usefixtures('core')
def test_the_linear_colour_space_is_encoded_for_the_display():
    colour = (0.2140, 0.2140, 0.2140)                        # sRGB 0.5
    shown = {}
    for space in ('SRGB_REC709_DISPLAY', 'LIN_REC709_DISPLAY'):
        node = _splats([(0, 0, 0)], [(0.6,) * 3], [colour], colorSpace=space)
        shown[space] = _draw(_scene(_placed(node)))[SIZE // 2, SIZE // 2, 0]
    assert shown['SRGB_REC709_DISPLAY'] == pytest.approx(0.99 * 0.214 * 255, abs=4)
    assert shown['LIN_REC709_DISPLAY'] == pytest.approx(0.99 * 0.5 * 255, abs=4)


@pytest.mark.usefixtures('core')
def test_the_colour_changes_with_the_side_it_is_seen_from():
    """A degree 1 coefficient on z: red seen along -z, cyan along +z."""
    harmonics = [[_dc((0.5, 0.5, 0.5))], [(0, 0, 0)], [(-0.8, 0.8, 0.8)], [(0, 0, 0)]]
    node = from_arrays([(0, 0, 0)], [IDENTITY], [(0.6,) * 3], [1.0], harmonics)
    ahead = _draw(_scene(_placed(node)))[SIZE // 2, SIZE // 2]
    turned = basenodes.Transform(rotation=(0, 1, 0, math.pi), children=[node])
    behind = _draw(_scene(_placed(turned)))[SIZE // 2, SIZE // 2]
    assert ahead[0] > ahead[1] + 60
    assert behind[1] > behind[0] + 60


@pytest.mark.usefixtures('core')
def test_an_invisible_set_is_not_drawn():
    node = _splats([(0, 0, 0)], [(0.5,) * 3], [(1, 1, 1)], visible=False)
    assert _draw(_scene(_placed(node))).max() == 0


@pytest.mark.usefixtures('core')
def test_bloom_shows_the_same_colour():
    node = _splats([(0, 0, 0)], [(0.6,) * 3], [(0.8, 0.4, 0.2)])
    plain = _draw(_scene(_placed(node)))[SIZE // 2, SIZE // 2]
    bloomed = _draw(_scene(_placed(node)), dict(PBR, OPENGLCONTEXT_BLOOM='1'), frames=4)
    assert np.allclose(bloomed[SIZE // 2, SIZE // 2], plain, atol=8)


@pytest.mark.usefixtures('core')
def test_a_mirrored_set_is_its_mirror_image():
    rng = np.random.default_rng(11)
    count = 40
    positions = rng.uniform(-1.0, 1.0, (count, 3)) * (1.2, 1.0, 0.5)
    turns = rng.normal(size=(count, 4))
    node = from_arrays(positions, turns, rng.uniform(0.05, 0.3, (count, 3)),
                       rng.uniform(0.4, 1.0, count),
                       [rng.normal(size=(count, 3)), rng.normal(size=(count, 3)) * 0.3,
                        rng.normal(size=(count, 3)) * 0.3, rng.normal(size=(count, 3)) * 0.3])
    plain = _draw(_scene(_placed(node)))
    mirrored = _draw(_scene(basenodes.Transform(scale=(-1, 1, 1), children=[_placed(node)])))
    assert np.mean(plain.max(axis=2) > 24) > 0.05
    differing = np.mean(np.abs(mirrored - plain[:, ::-1]).max(axis=2) > 24)
    assert differing <= 0.02


@pytest.mark.usefixtures('core')
def test_a_still_frame_asks_nothing_new_of_gl():
    node = _splats([(0, 0, 0), (1, 0, 0)], [(0.3,) * 3] * 2, [(1, 0, 0), (0, 1, 0)])
    with scene_context(_scene(_placed(node)), environment=PBR) as context:
        work = check_still_frame(lambda: context.OnDraw(force=1))
    assert work.allocations == work.uploads == work.compiles == 0


def _sorts(node):
    """How many sorts the node's orders have made, in every context"""
    return sum(entry[1].sorts for held in node._splat_buffers.by_context.values()
               for key, entry in held.items() if key[0] == 'order')


@pytest.mark.usefixtures('core')
def test_only_a_move_that_could_change_the_order_sorts_again():
    rng = np.random.default_rng(6)
    node = _splats(rng.normal(size=(200, 3)), [(0.1,) * 3] * 200, [(1, 1, 1)] * 200)
    place = _placed(node, (0.0, 0.0, -20.0))
    with scene_context(_scene(place), environment=PBR) as context:
        context.OnDraw(force=1)
        place.translation = (0.0, 0.0001, -20.0)
        context.OnDraw(force=1)
        assert _sorts(node) == 1
        place.translation = (0.5, 0.0, -20.0)
        context.OnDraw(force=1)
        assert _sorts(node) == 2


@pytest.mark.usefixtures('core')
def test_shadow_maps_draw_without_sorting():
    environment = dict(PBR, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='2')
    with scene_context(_shadow_scene(True), size=(SIZE, SIZE), environment=environment) as context:
        for _ in range(3):
            context.OnDraw(force=1)
        node = context.sg.children[-1].children[0]
        assert isinstance(node, GaussianSplats)
        assert _sorts(node) == 1


@pytest.mark.usefixtures('core')
def test_turning_back_finds_the_order_kept_for_that_view():
    rng = np.random.default_rng(6)
    node = _splats(rng.normal(size=(200, 3)), [(0.1,) * 3] * 200, [(1, 1, 1)] * 200)
    place = _placed(node)
    with scene_context(_scene(place), environment=PBR) as context:
        for angle in (0.0, 0.5, 1.0, 0.0, 0.5, 1.0):
            place.rotation = (0, 1, 0, angle)
            context.OnDraw(force=1)
        assert _sorts(node) == 3


@pytest.mark.usefixtures('core')
def test_a_failing_draw_is_reported_once_and_left_off():
    node = _splats([(0, 0, 0)], [(0.3,) * 3], [(1, 0, 0)])
    with scene_context(_scene(_placed(node)), environment=PBR) as context:
        context.OnDraw(force=1)
        check_failing_layer(lambda: context.OnDraw(force=1), GaussianSplats, '_draw',
                            context=context)
    assert node.failed


@pytest.mark.usefixtures('core')
def test_the_compatibility_profile_draws_the_splats():
    refused = profile_unavailable('compatibility')
    if refused:
        pytest.skip(refused)
    node = _splats([(0, 0, 0)], [(0.25,) * 3], [(1, 1, 1)])
    image = _draw(_scene(_placed(node)), {'OPENGLCONTEXT_PROFILE': 'compatibility'})
    assert image[SIZE // 2, SIZE // 2, 0] >= 245


# --- shadows and picking ----------------------------------------------------


def _shadow_scene(casts):
    node = _splats([(0, 0, 0)], [(0.6, 0.6, 0.6)], [(1, 1, 1)], castShadow=casts)
    ground = basenodes.Shape(
        geometry=basenodes.Box(size=(8, 0.1, 8)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))
    return [basenodes.Viewpoint(position=(0, 6, 0), orientation=(1, 0, 0, -math.pi / 2)),
            basenodes.DirectionalLight(direction=(0, -1, 0), intensity=1.0),
            basenodes.NavigationInfo(headlight=False),
            _placed(ground, (0, -2, 0)), _placed(node, (2.5, 0, 0))]


def _caster_scene(light, caster):
    """`caster` 2 m up and the ground below, seen from under the caster looking down"""
    ground = basenodes.Shape(
        geometry=basenodes.Box(size=(8, 0.1, 8)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))
    return [basenodes.Viewpoint(position=(0, 1.5, 0), orientation=(1, 0, 0, -math.pi / 2)),
            light, basenodes.NavigationInfo(headlight=False),
            _placed(ground, (0, -2, 0)), _placed(caster, (0, 2, 0))]


#: A splat's core reaches 1.17 deviations: where 0.99 exp(-d^2 / 2) is one half.
CORE = math.sqrt(2.0 * math.log(2.0 * 0.99))


@pytest.mark.usefixtures('core')
@pytest.mark.parametrize('light', [
    lambda: basenodes.DirectionalLight(direction=(0.1, -1, 0), intensity=1.0),
    lambda: basenodes.PointLight(location=(0.2, 8, 0), intensity=1.0, radius=50),
    lambda: basenodes.SpotLight(location=(0.2, 8, 0), direction=(0, -1, 0), intensity=1.0,
                                radius=50, cutOffAngle=0.6, beamWidth=0.6),
], ids=['directional', 'point', 'spot'])
def test_a_splats_shadow_is_the_shadow_of_its_core(light):
    """The ground a round splat darkens matches what a sphere of its core's size darkens."""
    environment = dict(PBR, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='1')
    sigma = 0.4
    splat = _splats([(0, 0, 0)], [(sigma,) * 3], [(1, 1, 1)])
    ball = basenodes.Shape(geometry=basenodes.Sphere(radius=CORE * sigma),
                           appearance=basenodes.Appearance(
                               material=basenodes.Material(diffuseColor=(1, 1, 1))))
    lit = _draw(_caster_scene(light(), basenodes.Group()), environment, 3).max(axis=2)
    shaded = {}
    for name, caster in (('splat', splat), ('ball', ball)):
        dark = _draw(_caster_scene(light(), caster), environment, 3).max(axis=2)
        shaded[name] = np.count_nonzero(lit - dark > 30)
    assert shaded['ball'] > 100
    assert shaded['splat'] == pytest.approx(shaded['ball'], rel=0.12)


@pytest.mark.usefixtures('core')
@pytest.mark.parametrize('fields', [{'castShadow': False}, {'visible': False}],
                         ids=['castShadow', 'visible'])
def test_a_set_casts_no_shadow_where_its_fields_say_not(fields):
    environment = dict(PBR, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='1')
    light = basenodes.DirectionalLight(direction=(0.1, -1, 0), intensity=1.0)
    lit = _draw(_caster_scene(light, basenodes.Group()), environment, 3)
    node = _splats([(0, 0, 0)], [(0.4,) * 3], [(1, 1, 1)], **fields)
    light = basenodes.DirectionalLight(direction=(0.1, -1, 0), intensity=1.0)
    assert np.abs(_draw(_caster_scene(light, node), environment, 3) - lit).max() <= 2


@pytest.mark.usefixtures('core')
def test_a_set_casts_its_cores_shadow():
    environment = dict(PBR, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_SHADOW_CASCADES='1')
    lit = _draw(_shadow_scene(False), environment, frames=3)
    shaded = _draw(_shadow_scene(True), environment, frames=3)
    # The splat sits right of centre, above the ground; its shadow falls
    # straight down under it, which the camera above sees around the splat.
    under = (slice(SIZE // 2 - 4, SIZE // 2 + 4), slice(SIZE - 14, SIZE - 6))
    assert shaded[under].mean() < lit[under].mean() - 20


def _pick(node):
    from OpenGLContext.events.mouseevents import MouseButtonEvent
    found = {}
    with scene_context(_scene(_placed(node)), environment=PBR) as context:
        context.contextDefinition.pickAsync = True

        def hit(event):
            paths = event.getObjectPaths()
            found['node'] = paths[0][-1] if paths and paths[0] else None
            found['depth'] = event.viewCoordinate[2]

        context.addEventHandler('mousebutton', button=0, state=1, function=hit)
        for frame in range(12):
            if 2 <= frame <= 4:
                event = MouseButtonEvent()
                event.button, event.state, event.modifiers = 0, 1, (0, 0, 0)
                event.pickPoint = (SIZE // 2, SIZE // 2)
                context.addPickEvent(event)
                context.triggerPick()
            context.OnDraw(force=1)
        context.flushPendingPicks()
    return found


@pytest.mark.usefixtures('core')
def test_a_pick_finds_the_splats():
    node = _splats([(0, 0, 0)], [(0.5,) * 3], [(1, 0, 0)])
    found = _pick(node)
    assert found['node'] is node
    assert found['depth'] < 1.0


@pytest.mark.usefixtures('core')
def test_a_pick_passes_through_splats_without_pointer_events():
    node = _splats([(0, 0, 0)], [(0.5,) * 3], [(1, 0, 0)], pointerEvents=False)
    assert _pick(node).get('node') is not node
