"""The engine's memos follow every input their answers are made from.

Each test here holds one memo to the inputs its answer is worked out from,
through :func:`OpenGLContext.testing.memo.check_memo_inputs`: every input is
edited in turn, and the memo's answer is compared with the answer worked out
afresh. The memos are the ones a frame is drawn from: which shapes batch,
which level of detail each node draws, which shapes are mirrors, and where
each zone is.
"""
import numpy as np
import pytest
from PIL import Image

from OpenGLContext.passes import reflection

from OpenGLContext.passes.pbrpass import PBRPass, instance_collapse_is_enabled
from OpenGLContext.scenegraph import basenodes, lod, zone as zonemodule
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.passes.flatcore import FlatPass
from OpenGLContext.scenegraph.water.surface import WaterStyle
from OpenGLContext.scenegraph.zone import Zone, ZoneSetting


def _mesh(offset=0.0):
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0)], 'f') + offset,
        normals=np.array([(0, 0, 1)] * 3, 'f'),
        texcoords=np.array([(0, 0), (1, 0), (1, 1)], 'f'),
        indices=np.array([0, 1, 2], np.uint32))


def _texture():
    return PBRTexture(Image.new('RGB', (2, 2)), srgb=True)


# --- the PBR pass's batching memo -------------------------------------------

@pytest.fixture
def batching(monkeypatch):
    """``(ask, fresh)`` for one shape's ``(key, instanceable)`` answer."""
    monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', raising=False)
    passing = PBRPass.__new__(PBRPass)

    def ask(shape):
        key, instanceable = passing.batchers()
        return key(shape), instanceable(shape)

    def fresh(shape):
        key = passing._keyFor(shape, instance_collapse_is_enabled())
        return key, key is not None and bool(passing._instanceable(shape))
    return ask, fresh


def test_the_batching_memo_follows_a_pbr_shape(batching):
    ask, fresh = batching
    material = PBRMaterial()
    shape = basenodes.Shape(geometry=_mesh(),
                            appearance=basenodes.Appearance(material=material))
    mirror = PlanarReflector()
    # Made before the edits: making a node sets its fields, and a set field
    # would move the generations the memo compares, hiding a missed input.
    water, other_mesh = _water_style(), _mesh(offset=1.0)
    appearance = basenodes.Appearance(material=PBRMaterial(
        reflector=PlanarReflector()))
    plain = PBRMaterial()
    check_memo_inputs(lambda: ask(shape), [
        ('material.textures, set in place',
         lambda: material.textures.__setitem__('baseColor', _texture())),
        ('material.alphaMode', lambda: setattr(material, 'alphaMode', 'BLEND')),
        ('material.transmission', lambda: setattr(material, 'transmission', 0.5)),
        ('material.octahedralViews',
         lambda: setattr(material, 'octahedralViews', 8)),
        ('geometry.waveStyle', lambda: setattr(shape.geometry, 'waveStyle', water)),
        ('geometry.waveStyle, cleared',
         lambda: setattr(shape.geometry, 'waveStyle', None)),
        ('material.reflector', lambda: setattr(material, 'reflector', mirror)),
        ('reflector.enabled', lambda: setattr(mirror, 'enabled', False)),
        ('shape.geometry', lambda: setattr(shape, 'geometry', other_mesh)),
        ('shape.appearance', lambda: setattr(shape, 'appearance', appearance)),
        ('appearance.material', lambda: setattr(appearance, 'material', plain)),
    ], fresh=lambda: fresh(shape))


def _water_style():
    return WaterStyle()


def test_the_batching_memo_follows_a_vrml97_shape(batching):
    ask, fresh = batching
    material = basenodes.Material()
    appearance = basenodes.Appearance(material=material)
    shape = basenodes.Shape(geometry=basenodes.Box(), appearance=appearance)
    texture, larger = basenodes.ImageTexture(), basenodes.Box(size=(3, 3, 3))
    check_memo_inputs(lambda: ask(shape), [
        ('material.transparency', lambda: setattr(material, 'transparency', 0.5)),
        ('appearance.texture', lambda: setattr(appearance, 'texture', texture)),
        ('shape.geometry', lambda: setattr(shape, 'geometry', larger)),
    ], fresh=lambda: fresh(shape))


def test_the_batching_memo_follows_a_mesh_with_its_own_material(batching):
    """A mesh placed with no appearance material is drawn with its own."""
    ask, fresh = batching
    mesh = _mesh()
    shape = basenodes.Shape(geometry=mesh)
    mirrored = PBRMaterial(reflector=PlanarReflector())
    check_memo_inputs(lambda: ask(shape), [
        ('mesh.material', lambda: setattr(mesh, 'material', mirrored)),
    ], fresh=lambda: fresh(shape))


# --- the scene's mirrors ------------------------------------------------------

def test_a_mesh_under_an_appearance_with_no_material_is_drawn_with_its_own():
    own = PBRMaterial(reflector=PlanarReflector())
    shape = basenodes.Shape(geometry=PBRMesh(material=own),
                            appearance=basenodes.Appearance())
    assert reflection.shape_material(shape) is own
    assert reflection.shape_reflector(shape) is own.reflector


def test_the_mirror_generation_follows_every_field_deciding_a_mirror():
    """What a pass keys its set of mirrors on moves with every such field.

    The answer is whether the shape is a mirror, kept against
    :func:`~OpenGLContext.passes.reflection.mirror_generation` as
    ``sceneMirrors`` keeps it.
    """
    held = {}

    def ask():
        generation = reflection.mirror_generation()
        if held.get('generation') != generation:
            held['generation'] = generation
            held['answer'] = reflection.shape_reflector(shape) is not None
        return held['answer']

    material = PBRMaterial()
    mesh = _mesh()
    shape = basenodes.Shape(geometry=mesh,
                            appearance=basenodes.Appearance(material=material))
    mirror = PlanarReflector()
    mirroring = PBRMaterial(reflector=PlanarReflector())
    plain = basenodes.Appearance(material=PBRMaterial())
    water, other_mesh = _water_style(), _mesh()
    own = PBRMaterial(reflector=PlanarReflector())
    check_memo_inputs(ask, [
        ('material.reflector', lambda: setattr(material, 'reflector', mirror)),
        ('reflector.enabled', lambda: setattr(mirror, 'enabled', False)),
        ('appearance.material', lambda: setattr(
            shape.appearance, 'material', mirroring)),
        ('shape.appearance', lambda: setattr(shape, 'appearance', plain)),
        ('mesh.waveStyle', lambda: setattr(mesh, 'waveStyle', water)),
        ('shape.geometry', lambda: setattr(shape, 'geometry', other_mesh)),
        ('shape.appearance, to none, and the mesh its own mirror', lambda: (
            setattr(other_mesh, 'material', own),
            setattr(shape, 'appearance', None))),
        ('mesh.material', lambda: setattr(other_mesh, 'material', None)),
    ], fresh=lambda: reflection.shape_reflector(shape) is not None)


# --- the level-of-detail memo -------------------------------------------------

class _Path(tuple):
    """A node path whose world matrix is fixed: the part of a path chooseLevels reads."""

    def __new__(cls, node, matrix):
        path = super().__new__(cls, (node,))
        path.matrix = matrix
        return path

    def transformMatrix(self):
        return self.matrix


def _levels_pass(paths):
    passing = FlatPass.__new__(FlatPass)
    passing.paths = {}
    passing._pathGeneration = 0
    passing._levelChoice = None
    passing.paths[lod.LOD] = paths
    return passing


def _viewer(distance):
    modelview = np.identity(4, 'd')
    modelview[3, 2] = -distance
    return lod.Viewer(modelview, lod.viewer_tangent(60.0))


def _fresh_levels(nodes, distance):
    """The levels a node would choose with no memo, for the same viewer."""
    viewer = _viewer(distance)
    answers = []
    for node in nodes:
        numbers = (float(np.linalg.norm(np.asarray(node.center, 'd')
                                        - (0, 0, distance))), 1.0,
                   float(viewer.tangent))
        answers.append(node.levelAt(*numbers))
    return answers


def test_the_level_memo_follows_every_field_deciding_a_level():
    plain = lod.LOD(level=[basenodes.Group(), basenodes.Group(),
                           basenodes.Group()], range=[5.0, 10.0])
    covered = lod.ScreenCoverageLOD(
        level=[basenodes.Group(), basenodes.Group(), basenodes.Group()],
        screenCoverage=[0.5, 0.1, 0.0], radius=1.0)
    nodes = [plain, covered]
    passing = _levels_pass([_Path(node, np.identity(4, 'd')) for node in nodes])
    distance = 7.5

    def ask():
        passing.chooseLevels([_viewer(distance)])
        return [node.whichLevel for node in nodes]

    def fresh():
        return _fresh_levels(nodes, distance)

    check_memo_inputs(ask, [
        ('LOD.range', lambda: setattr(plain, 'range', [20.0, 30.0])),
        ('LOD.center', lambda: setattr(plain, 'center', (0, 0, -20))),
        ('LOD.level', lambda: setattr(plain, 'level', [basenodes.Group()])),
        ('ScreenCoverageLOD.radius', lambda: setattr(covered, 'radius', 0.1)),
        ('ScreenCoverageLOD.screenCoverage', lambda: setattr(
            covered, 'screenCoverage', [0.001, 0.0005, 0.0])),
    ], fresh=fresh)


def test_the_level_memo_follows_the_hysteresis_band():
    """A band narrowed while the viewer stands inside it lets the coarser level in."""
    node = lod.LOD(level=[basenodes.Group(), basenodes.Group()], range=[10.0])
    passing = _levels_pass([_Path(node, np.identity(4, 'd'))])
    distance = [9.0]

    def ask():
        passing.chooseLevels([_viewer(distance[0])])
        return node.whichLevel

    assert ask() == 0
    distance[0] = 10.5          # past the threshold, inside the band
    assert ask() == 0
    check_memo_inputs(ask, [
        ('LOD.hysteresis', lambda: setattr(node, 'hysteresis', 0.0)),
    ], fresh=lambda: node.levelAt(distance[0], 1.0, 1.0))


# --- the zone placement memo --------------------------------------------------

def test_the_zone_placement_follows_every_field_placing_a_zone():
    node = Zone(shapeType='box', size=(2, 2, 2))
    matrix = np.identity(4, 'd')
    cache = {}

    def ask():
        placed = zonemodule.placed_zones([(node, matrix)], cache)
        return placed[0]

    def describe(placed):
        return (placed.shape, placed.priority, placed.blend,
                tuple(placed.zone.settings or ()))

    def fresh():
        return describe(zonemodule.placed_zones([(node, matrix)])[0])

    settings = _zone_settings()
    check_memo_inputs(lambda: describe(ask()), [
        ('Zone.size', lambda: setattr(node, 'size', (4, 4, 4))),
        ('Zone.shapeType', lambda: setattr(node, 'shapeType', 'sphere')),
        ('Zone.radius', lambda: setattr(node, 'radius', 3.0)),
        ('Zone.priority', lambda: setattr(node, 'priority', 5)),
        ('Zone.blend', lambda: setattr(node, 'blend', 0.5)),
        ('Zone.settings', lambda: setattr(node, 'settings', settings)),
    ], fresh=fresh, same=_same_placement)


def test_a_zone_setting_edited_in_place_makes_a_new_placement():
    settings = _zone_settings()
    node = Zone(shapeType='box', size=(2, 2, 2), settings=settings)
    matrix = np.identity(4, 'd')
    cache = {}
    first = zonemodule.placed_zones([(node, matrix)], cache)[0]
    check_memo_inputs(
        lambda: zonemodule.placed_zones([(node, matrix)], cache)[0],
        [('a setting field', lambda: setattr(settings[0], 'enabled', False))],
        same=lambda a, b: a is b)
    assert zonemodule.placed_zones([(node, matrix)], cache)[0] is not first


def _zone_settings():
    classes = [cls for cls in _subclasses(ZoneSetting) if 'enabled' in dir(cls)]
    return [classes[0]()]


def _subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _subclasses(sub)


def _same_placement(a, b):
    shape_a, *rest_a = a
    shape_b, *rest_b = b
    return _same_shape(shape_a, shape_b) and rest_a == rest_b


def _same_shape(a, b):
    if type(a) is not type(b):
        return False
    for name in getattr(a, '__dataclass_fields__', ()) or vars(a):
        x, y = getattr(a, name), getattr(b, name)
        if isinstance(x, np.ndarray) or isinstance(y, np.ndarray):
            if not np.array_equal(np.asarray(x), np.asarray(y)):
                return False
        elif x != y:
            return False
    return True
