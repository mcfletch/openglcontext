"""Names that survive the file: a material's, and an animation clip's.

A game drives an asset by name -- repaint the material called ``paint``, pose
the clip called ``steer`` -- so the name an artist gave a material has to arrive
with it. Each test here writes a document with
:mod:`OpenGLContext.loaders.gltf.writer` and reads it back with
:func:`OpenGLContext.loaders.gltf.load_gltf`, so what is asserted is the pair.

No GL and no network: a document is bytes, and a loaded scene is arrays.
"""
import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.animation import Animation, Channel, Sampler
from OpenGLContext.loaders.gltf.scene import GLTFScene
from OpenGLContext.loaders.gltf.writer import GLTFWriter, SceneNode, write_glb
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform


def _quad(material=None):
    """A two-triangle quad, optionally carrying a material."""
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material,
    )


def _shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _shapes(child, out)
    return out


# --- material names -----------------------------------------------------------

def test_material_name_round_trips():
    """The DEF an artist put on a material is the name it loads under."""
    paint = PBRMaterial(baseColor=(0.62, 0.09, 0.07), metallic=0.55)
    paint.DEF = 'paint'
    scene = gltf.load_gltf(write_glb(_quad(paint)))
    loaded = _shapes(scene.group)[0].appearance.material
    assert loaded.DEF == 'paint'


def test_named_material_indexes_the_object_the_shape_uses():
    """``materials[name]`` is the material the geometry is drawn with.

    Identity, not a copy: repainting what the index hands back is what repaints
    the model.
    """
    paint = PBRMaterial(baseColor=(0.2, 0.4, 0.6))
    paint.DEF = 'paint'
    scene = gltf.load_gltf(write_glb(_quad(paint)))
    shape = _shapes(scene.group)[0]
    assert scene.materials['paint'] is shape.appearance.material
    assert scene.materials['paint'] is shape.geometry.material


def test_unnamed_materials_are_not_indexed():
    """A material with no name is drawn, and is not in the index."""
    scene = gltf.load_gltf(write_glb(_quad(PBRMaterial(baseColor=(1.0, 1.0, 1.0)))))
    assert scene.materials == {}
    assert _shapes(scene.group)[0].appearance.material is not None


def test_repeated_names_index_the_first_and_load_both():
    """glTF names need not be unique; the index keeps the first of a name."""
    first, second = PBRMaterial(baseColor=(1.0, 0.0, 0.0)), PBRMaterial(baseColor=(0.0, 0.0, 1.0))
    first.DEF = second.DEF = 'paint'
    scene = gltf.load_gltf(write_glb([SceneNode(mesh=_quad(first)),
                                      SceneNode(mesh=_quad(second))]))
    materials = [shape.appearance.material for shape in _shapes(scene.group)]
    assert len(materials) == 2
    assert materials[0] is not materials[1]
    assert list(scene.materials) == ['paint']
    assert tuple(scene.materials['paint'].baseColor) == pytest.approx((1.0, 0.0, 0.0))


def test_writer_name_argument_wins_over_the_def():
    """A caller naming a material explicitly gets that name in the document."""
    material = PBRMaterial(baseColor=(0.5, 0.5, 0.5))
    material.DEF = 'ignored'
    writer = GLTFWriter()
    writer.add_material(material, name='trim')      # named before the mesh reuses it
    writer.add_node(SceneNode(mesh=_quad(material)))
    scene = gltf.load_gltf(writer.to_glb())
    assert 'trim' in scene.materials
    assert 'ignored' not in scene.materials


def test_a_node_and_a_material_may_share_a_name():
    """glTF names nodes and materials in separate namespaces; VRML has one.

    A vehicle whose glass is a node called ``glass`` made of a material called
    ``glass`` is ordinary authoring, and both have to stay addressable: the node
    through ``getDEF``, the material through ``materials``.
    """
    glass = PBRMaterial(baseColor=(0.1, 0.2, 0.3), transmission=1.0)
    glass.DEF = 'glass'
    scene = gltf.load_gltf(write_glb([SceneNode(mesh=_quad(glass), name='glass')]))
    assert isinstance(scene.getDEF('glass'), Transform)
    assert scene.materials['glass'] is _shapes(scene.group)[0].appearance.material


# --- finding one clip by name -------------------------------------------------

def _spin_clip(name, node_index=0):
    """A one-second rotation clip, as the loader would have built it."""
    times = np.array([0.0, 1.0], 'd')
    values = np.array([(0.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 0.0)], 'd')
    sampler = Sampler(times, values, interpolation='LINEAR', is_rotation=True)
    return Animation(name, [Channel(node_index, 'rotation', sampler)])


def _scene_with_clips(*names):
    node = Transform()
    return GLTFScene(Transform(children=[node]), (0, 0, 0), 1.0,
                     animations=[_spin_clip(name) for name in names],
                     node_transforms={0: node})


def test_player_named_finds_the_clip():
    """A clip is addressed by the name it was authored under."""
    scene = _scene_with_clips('idle', 'steer')
    player = scene.player_named('steer')
    assert player is not None
    assert player.animation.name == 'steer'
    assert player.duration == pytest.approx(1.0)


def test_player_named_poses_the_scenegraph():
    """The player a name returns drives the nodes, like the one an index returns."""
    scene = _scene_with_clips('steer')
    player = scene.player_named('steer', loop=False)
    player.evaluate(0.5 * player.duration)
    angle = scene.node_transforms[0].rotation[3]
    assert angle == pytest.approx(np.pi / 2, abs=1e-6)


def test_player_named_unknown_clip_is_none():
    """A name no clip carries is None, as an out-of-range index is."""
    assert _scene_with_clips('idle').player_named('steer') is None
    assert GLTFScene(Transform(), (0, 0, 0), 1.0).player_named('steer') is None
