"""A file says what a thing *is*; the application says what to make of it.

``OGLC_hook`` is the tag, in a material's or a node's ``extras`` or
``extensions``, and :mod:`OpenGLContext.loaders.gltf.hooks` is the registry the
kind it names is looked up in. Each test here writes a document with
:mod:`OpenGLContext.loaders.gltf.writer` and reads it back with
:func:`OpenGLContext.loaders.gltf.load_gltf`, so what is asserted is the pair.

No GL and no network: a document is bytes, and a loaded scene is nodes.
"""
import contextlib
import logging

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform
from OpenGLContext.scenegraph.basenodes import Group


def _quad(material=None):
    """A two-triangle quad, optionally carrying a material."""
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material,
    )


def _tagged_material(**named):
    """A material carrying whatever spelling of the tag the test wants."""
    material = PBRMaterial(baseColor=(0.1, 0.2, 0.3))
    for name, value in named.items():
        setattr(material, name, value)
    return material


def _shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _shapes(child, out)
    return out


@contextlib.contextmanager
def bound(kind, factory, **named):
    """Register a kind for the length of one test and take it away again."""
    hooks.register(kind, factory, **named)
    try:
        yield
    finally:
        hooks.unregister(kind)


class Recorder:
    """A hook that remembers every context it was called with."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __call__(self, ctx):
        self.calls.append(ctx)
        return self.result(ctx) if callable(self.result) else self.result

    @property
    def only(self):
        assert len(self.calls) == 1, 'called %d times' % len(self.calls)
        return self.calls[0]


# --- reading the tag ----------------------------------------------------------

def test_a_tag_in_extras_reaches_the_hook():
    """The Blender spelling: a custom property on the material datablock."""
    material = _tagged_material(
        extras={'OGLC_hook': {'kind': 'probe', 'style': 'choppy', 'level': 12.5}})
    seen = Recorder()
    with bound('probe', seen):
        gltf.load_gltf(write_glb(_quad(material)))
    ctx = seen.only
    assert ctx.kind == 'probe'
    assert ctx.params == {'style': 'choppy', 'level': 12.5}
    assert ctx.at == 'material'


def test_a_tag_in_extensions_reaches_the_hook():
    """The authored spelling: an extension block a tool wrote."""
    material = _tagged_material(hook={'kind': 'probe', 'style': 'flowing'})
    seen = Recorder()
    with bound('probe', seen):
        gltf.load_gltf(write_glb(_quad(material)))
    assert seen.only.params == {'style': 'flowing'}


def test_the_extension_wins_over_extras():
    """A file carrying both was written by a tool that knew what it meant."""
    material = _tagged_material(
        extras={'OGLC_hook': {'kind': 'probe', 'style': 'still'}},
        hook={'kind': 'probe', 'style': 'choppy'})
    seen = Recorder()
    with bound('probe', seen):
        gltf.load_gltf(write_glb(_quad(material)))
    assert seen.only.params == {'style': 'choppy'}


def test_a_bare_string_is_the_kind():
    """The shorthand: a kind with no parameters, as an artist types it."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    seen = Recorder()
    with bound('probe', seen):
        gltf.load_gltf(write_glb(_quad(material)))
    assert seen.only.kind == 'probe'
    assert seen.only.params == {}


def test_an_unregistered_kind_loads_as_an_ordinary_shape(caplog):
    """A file authored for another engine must not fail to load here."""
    material = _tagged_material(extras={'OGLC_hook': 'forcefield'})
    with caplog.at_level(logging.DEBUG, logger='OpenGLContext.loaders.gltf.hooks'):
        scene = gltf.load_gltf(write_glb([SceneNode(mesh=_quad(material)),
                                          SceneNode(mesh=_quad(material))]))
    assert len(_shapes(scene.group)) == 2
    said = [record for record in caplog.records if 'forcefield' in record.getMessage()]
    assert len(said) == 1, 'said it %d times' % len(said)


def test_the_environment_switch_leaves_every_tag_unread(monkeypatch):
    """``OPENGLCONTEXT_GLTF_HOOKS=0`` turns the whole mechanism off."""
    monkeypatch.setenv(hooks.ENVIRONMENT, '0')
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    seen = Recorder()
    with bound('probe', seen):
        scene = gltf.load_gltf(write_glb(_quad(material)))
    assert seen.calls == []
    assert len(_shapes(scene.group)) == 1


# --- the material hook --------------------------------------------------------

def test_the_material_hook_gets_what_the_loader_built():
    """The finished objects, not the accessors: mesh, material and Shape."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    seen = Recorder()
    with bound('probe', seen):
        scene = gltf.load_gltf(write_glb(_quad(material)))
    ctx = seen.only
    shape = _shapes(scene.group)[0]
    assert ctx.shape is shape
    assert ctx.mesh is shape.geometry
    assert ctx.material is shape.appearance.material
    assert ctx.primitive is not None


def test_a_material_hook_may_return_a_node_in_the_shapes_place():
    """What the hook made stands where the loader's own ``Shape`` would have."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    made = Group()
    with bound('probe', lambda ctx: made):
        scene = gltf.load_gltf(write_glb(_quad(material)))
    assert _shapes(scene.group) == []
    assert made in list(scene.group.children[0].children)


def test_bounds_the_hook_widened_frame_the_camera():
    """A hook that changes the extent says so, and the framing follows."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})

    def widen(ctx):
        low, high = ctx.bounds
        ctx.bounds = (low - 50.0, high + 50.0)

    plain = gltf.load_gltf(write_glb(_quad(_tagged_material())))
    with bound('probe', widen):
        widened = gltf.load_gltf(write_glb(_quad(material)))
    assert widened.radius > plain.radius * 10


def test_the_world_matrix_reaches_the_material_hook():
    """Where the primitive stands, so a hook can put a box round it."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    seen = Recorder()
    with bound('probe', seen, shareable=False):
        gltf.load_gltf(write_glb(SceneNode(mesh=_quad(material),
                                           translation=(4.0, 0.0, 0.0))))
    low, high = seen.only.world_bounds()
    assert low[0] == pytest.approx(4.0)
    assert high[0] == pytest.approx(5.0)


# --- sharing ------------------------------------------------------------------

def _two_nodes_on_one_mesh(material):
    mesh = _quad(material)
    return write_glb([SceneNode(mesh=mesh, name='first'),
                      SceneNode(mesh=mesh, name='second')])


def test_a_shareable_hook_leaves_one_mesh_shared():
    """The default: two nodes on one mesh draw one geometry, as before."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    seen = Recorder()
    with bound('probe', seen):
        scene = gltf.load_gltf(_two_nodes_on_one_mesh(material))
    first, second = _shapes(scene.group)
    assert first.geometry is second.geometry
    assert len(seen.calls) == 1


def test_an_unshareable_hook_gives_each_node_its_own_geometry():
    """A hook whose result carries per-node state must not be shared."""
    material = _tagged_material(extras={'OGLC_hook': 'probe'})
    seen = Recorder()
    with bound('probe', seen, shareable=False):
        scene = gltf.load_gltf(_two_nodes_on_one_mesh(material))
    first, second = _shapes(scene.group)
    assert first.geometry is not second.geometry
    assert len(seen.calls) == 2


# --- the node hook ------------------------------------------------------------

def _tagged_node(tag, **named):
    return SceneNode(mesh=_quad(), extras={'OGLC_hook': tag}, **named)


def test_a_node_tag_reaches_the_hook_with_the_group_and_the_children():
    """A node-level fact: the Transform, what is under it, and where it is."""
    seen = Recorder()
    with bound('probe', seen):
        scene = gltf.load_gltf(write_glb(
            _tagged_node({'kind': 'probe', 'depth': 3.0}, name='lake',
                         translation=(0.0, 2.0, 0.0))))
    ctx = seen.only
    assert ctx.at == 'node'
    assert ctx.params == {'depth': 3.0}
    assert ctx.transform is scene.getDEF('lake')
    assert len(_shapes(Transform(children=list(ctx.children)))) == 1
    assert ctx.world_matrix[3][1] == pytest.approx(2.0)
    assert ctx.local_matrix[3][1] == pytest.approx(2.0)


def test_a_node_hook_returning_none_leaves_the_transform_and_children():
    """The hook augmented and nothing else changed."""
    with bound('probe', lambda ctx: None):
        scene = gltf.load_gltf(write_glb(_tagged_node('probe', name='lake')))
    placed = scene.getDEF('lake')
    assert isinstance(placed, Transform)
    assert len(_shapes(placed)) == 1


def test_a_node_hook_may_stand_under_the_transform():
    """``(node, False)``: the node's TRS still places what the hook made."""
    made = Group()
    with bound('probe', lambda ctx: (made, False)):
        scene = gltf.load_gltf(write_glb(
            _tagged_node('probe', name='lake', translation=(5.0, 0.0, 0.0))))
    placed = scene.getDEF('lake')
    assert isinstance(placed, Transform)
    assert tuple(placed.translation) == pytest.approx((5.0, 0.0, 0.0))
    assert list(placed.children) == [made]


def test_a_node_hook_may_take_the_nodes_own_slot():
    """``(node, True)``: the Transform is gone and the hook owns the placement."""
    made = Group()
    seen = Recorder(result=lambda ctx: (made, True))
    with bound('probe', seen):
        scene = gltf.load_gltf(write_glb(
            _tagged_node('probe', name='lake', translation=(5.0, 0.0, 0.0))))
    assert list(scene.group.children) == [made]
    assert seen.only.local_matrix[3][0] == pytest.approx(5.0)


def test_one_kind_may_replace_one_node_and_not_another():
    """Replacing is a property of what the hook made of *this* node."""
    def take_the_named_one(ctx):
        made = Group()
        return (made, ctx.transform.DEF == 'taken')

    with bound('probe', take_the_named_one):
        scene = gltf.load_gltf(write_glb([_tagged_node('probe', name='taken'),
                                          _tagged_node('probe', name='under')]))
    assert isinstance(scene.getDEF('taken'), Group)
    assert isinstance(scene.getDEF('under'), Transform)


@pytest.mark.parametrize('result, expected', [
    (None, Transform),
    ((Group(), False), Transform),
    ((Group(), True), Group),
])
def test_the_def_resolves_to_whatever_is_in_the_slot(result, expected):
    """``getDEF`` finds the same name it would have found."""
    with bound('probe', lambda ctx: result):
        scene = gltf.load_gltf(write_glb(_tagged_node('probe', name='lake')))
    placed = scene.getDEF('lake')
    assert isinstance(placed, expected)
    assert placed.DEF == 'lake'
    assert placed in _descendants(scene.group)


def _descendants(node, out=None):
    out = [] if out is None else out
    for child in getattr(node, 'children', None) or []:
        out.append(child)
        _descendants(child, out)
    return out


def test_a_node_hook_returning_a_bare_node_is_refused():
    """The pair says whether the node was replaced; a node alone does not."""
    with bound('probe', lambda ctx: Group()):
        with pytest.raises(ValueError, match='replacing'):
            gltf.load_gltf(write_glb(_tagged_node('probe', name='lake')))


# --- what the hooks left behind -----------------------------------------------

def test_hook_data_arrives_on_the_scene():
    """What a hook recorded is on the scene, keyed by kind."""
    with bound('probe', lambda ctx: ctx.collect({'seen': ctx.at}) and None):
        scene = gltf.load_gltf(write_glb(_tagged_node('probe', name='lake')))
    assert scene.hook_data['probe'] == [{'seen': 'node'}]


def test_advance_walks_the_kinds_that_registered_one():
    """A scene with no timed hook has nothing to advance."""
    moved = []

    def note(data, when):
        moved.append((list(data), when))
        return True

    with bound('probe', lambda ctx: ctx.collect('body') and None, advance=note):
        scene = gltf.load_gltf(write_glb(_tagged_node('probe', name='lake')))
        assert scene.advance(2.5) is True
    assert moved == [(['body'], 2.5)]


def test_advance_is_a_return_for_a_scene_with_no_hooks():
    scene = gltf.load_gltf(write_glb(_quad()))
    assert scene.advance(1.0) is False


# --- writing it back ----------------------------------------------------------

def test_the_extras_spelling_round_trips():
    """A scene loaded and re-saved keeps its tags."""
    material = _tagged_material(extras={'OGLC_hook': {'kind': 'probe', 'level': 2.0}})
    first = gltf.load_gltf(write_glb(_quad(material)))
    loaded = _shapes(first.group)[0].appearance.material
    assert loaded.extras == {'OGLC_hook': {'kind': 'probe', 'level': 2.0}}
    seen = Recorder()
    with bound('probe', seen):
        gltf.load_gltf(write_glb(_quad(loaded)))
    assert seen.only.params == {'level': 2.0}


def test_the_extension_spelling_round_trips():
    material = _tagged_material(hook={'kind': 'probe', 'level': 2.0})
    first = gltf.load_gltf(write_glb(_quad(material)))
    loaded = _shapes(first.group)[0].appearance.material
    assert loaded.hook == {'kind': 'probe', 'level': 2.0}
    seen = Recorder()
    with bound('probe', seen):
        gltf.load_gltf(write_glb(_quad(loaded)))
    assert seen.only.params == {'level': 2.0}


def test_a_written_hook_extension_is_declared_used():
    """A reader is told which extensions a document carries."""
    from OpenGLContext.loaders.gltf.writer import GLTFWriter
    writer = GLTFWriter()
    writer.add_node(SceneNode(mesh=_quad(_tagged_material(hook={'kind': 'probe'}))))
    assert hooks.EXTENSION in writer.document()['extensionsUsed']


def test_a_node_tag_round_trips_through_the_writer():
    seen = Recorder()
    with bound('probe', seen):
        scene = gltf.load_gltf(write_glb(
            SceneNode(mesh=_quad(), name='lake', hook={'kind': 'probe'})))
    assert seen.only.at == 'node'
    assert scene.getDEF('lake') is not None


# --- the registry -------------------------------------------------------------

def test_register_works_as_a_decorator_and_as_a_call():
    try:
        @hooks.register('probe')
        def probe(ctx):
            return None
        assert hooks.registered('probe').factory is probe
        assert hooks.registered('probe').shareable is True
    finally:
        hooks.unregister('probe')


def test_registered_reports_what_is_bound():
    assert hooks.registered('nothing-is-bound-to-this') is None


# --- a hook that fails ------------------------------------------------------------

def _fails(ctx):
    raise RuntimeError('the lantern hook broke on %s' % ctx.at)


def test_a_material_hook_that_raises_leaves_the_loaders_shape(caplog):
    """One broken hook costs its holder the hook, not the file its load."""
    material = _tagged_material(extras={'OGLC_hook': 'lantern'})
    with bound('lantern', _fails), caplog.at_level(logging.ERROR):
        scene = gltf.load_gltf(write_glb(_quad(material)))
    shape, = _shapes(scene.group)
    assert isinstance(shape.geometry, PBRMesh)
    assert 'lantern' in caplog.text


def test_a_node_hook_that_raises_leaves_the_transform_and_children(caplog):
    with bound('lantern', _fails), caplog.at_level(logging.ERROR):
        scene = gltf.load_gltf(write_glb(_tagged_node('lantern', name='lamp')))
    assert len(_shapes(scene.group)) == 1
    assert 'lantern' in caplog.text and 'lamp' in caplog.text
