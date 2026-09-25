"""A file saying which of its objects cast shadows.

glTF has no flag for it, so the engine reads one out of ``extras``:
``OGLC_castsShadow: false`` on a node means that node's geometry is lit and
receives shadows like anything else, and is left out of the depth pass. A room
is the case it is for -- an interior's walls stand between every light and
everything inside, so a hall whose shell casts is a hall with the lights
switched off.

Each test writes a document with the writer and reads it back with the loader.
"""
import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.loaders.gltf.scene import _light_node

FLAG = 'OGLC_castsShadow'


def _slab(colour=(0.8, 0.8, 0.8), size=1.0):
    return PBRMesh(
        positions=np.array([(0, 0, 0), (size, 0, 0), (size, 0, size), (0, 0, size)], 'f'),
        normals=np.array([(0, 1, 0)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=PBRMaterial(baseColor=colour),
    )


def _shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _shapes(child, out)
    return out


def _loaded(*nodes):
    scene = gltf.load_gltf(write_glb(list(nodes)))
    return scene, _shapes(scene.group)


def test_a_shape_casts_unless_the_file_says_otherwise():
    _scene, shapes = _loaded(SceneNode(mesh=_slab()))
    assert shapes[0].castsShadow


def test_a_node_can_say_it_does_not_cast():
    _scene, shapes = _loaded(SceneNode(mesh=_slab(), extras={FLAG: False}))
    assert bool(shapes[0].castsShadow) is False


def test_saying_it_does_cast_is_the_default_said_out_loud():
    _scene, shapes = _loaded(SceneNode(mesh=_slab(), extras={FLAG: True}))
    assert shapes[0].castsShadow


def test_the_flag_says_what_one_node_does():
    """It does not reach a node's children: that is how the tools that author
    it treat shadow visibility, and a group is not a decision about what
    stands inside it."""
    _scene, shapes = _loaded(SceneNode(
        extras={FLAG: False},
        children=[SceneNode(mesh=_slab()), SceneNode(mesh=_slab(size=2.0))],
    ))
    assert len(shapes) == 2
    assert [bool(shape.castsShadow) for shape in shapes] == [True, True]


def test_a_child_speaks_for_itself():
    _scene, shapes = _loaded(SceneNode(
        children=[SceneNode(mesh=_slab(), extras={FLAG: False}),
                  SceneNode(mesh=_slab(size=2.0))],
    ))
    assert sorted(bool(shape.castsShadow) for shape in shapes) == [False, True]


def test_two_nodes_on_one_mesh_keep_their_own_answer():
    """The loader shares a mesh's shape between nodes; the flag is per node,
    so a wall and a plinth cut from one box do not settle each other's."""
    mesh = _slab()
    _scene, shapes = _loaded(
        SceneNode(mesh=mesh, translation=(0, 0, 0), extras={FLAG: False}),
        SceneNode(mesh=mesh, translation=(4, 0, 0)),
    )
    assert len(shapes) == 2
    assert sorted(bool(shape.castsShadow) for shape in shapes) == [False, True]


def test_nodes_that_agree_still_share_one_shape():
    """Sharing is what makes a hall of thirty identical beams one mesh."""
    mesh = _slab()
    _scene, shapes = _loaded(
        SceneNode(mesh=mesh, translation=(0, 0, 0)),
        SceneNode(mesh=mesh, translation=(4, 0, 0)),
    )
    assert shapes[0] is shapes[1]


@pytest.mark.parametrize('written, expected', [
    (0, False), (1, True), (False, False), (True, True),
])
def test_what_a_custom_property_writes_is_read(written, expected):
    """A Blender custom property is an int as often as a bool."""
    _scene, shapes = _loaded(SceneNode(mesh=_slab(), extras={FLAG: written}))
    assert bool(shapes[0].castsShadow) is expected


def _sun(extras=None, casts=None):
    """A directional light on its own node, as a file carries one."""
    definition = {'type': 'directional', 'intensity': 3.0}
    if casts is not None:
        definition['castShadows'] = casts
    return _light_node(definition, np.eye(4),
                       True if extras is None else bool(extras))


def test_a_directional_light_casts_by_default():
    assert _sun().castShadows


def test_a_light_on_a_node_that_does_not_cast_is_a_fill():
    """A bounce light standing in for what a room's surfaces throw back has
    nothing to shadow, and a map for it costs a map for nothing."""
    assert bool(_sun(extras=False).castShadows) is False


def test_a_light_on_a_marked_node_does_not_cast_even_asking_to():
    assert bool(_sun(extras=False, casts=True).castShadows) is False


def test_a_flagged_node_still_draws_and_still_frames_the_camera():
    """Not casting is not being absent: the wall is lit, drawn and in the box."""
    scene = gltf.load_gltf(write_glb(SceneNode(mesh=_slab(size=3.0),
                                               extras={FLAG: False})))
    shape = _shapes(scene.group)[0]
    assert shape.geometry is not None
    assert float(scene.radius) > 0.0
