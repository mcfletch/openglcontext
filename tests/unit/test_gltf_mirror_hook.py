"""Mirrors authored in a model: the ``mirror`` hook kind.

On a material, every surface drawn with it reflects the scene through the
material's own shading. On an object, every surface of it shows the reflection
and nothing of its material. Each test writes a document with
:mod:`OpenGLContext.loaders.gltf.writer` and reads it back; no GL.
"""
import logging

import numpy as np
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.loaders.gltf.writer import SceneNode, write_glb
from OpenGLContext.scenegraph import water
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import WATER, PlanarReflector
from OpenGLContext.scenegraph.shape import Shape


def _quad(tag=None, colour=(0.8, 0.8, 0.8), metallic=1.0, roughness=0.0):
    material = PBRMaterial(baseColor=colour, metallic=metallic, roughness=roughness)
    if tag is not None:
        material.extras = {'OGLC_hook': tag}
    return PBRMesh(
        positions=np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 4, 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], np.uint32),
        material=material)


def _shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _shapes(child, out)
    return out


def _load(root):
    return gltf.load_gltf(write_glb(root))


def _material_of(scene, index=0):
    return _shapes(scene.group)[index].appearance.material


# --- the kind ships registered ------------------------------------------------

def test_the_mirror_kind_is_bound_without_being_imported():
    assert hooks.registered('mirror') is not None


# --- on a material ------------------------------------------------------------

def test_the_shorthand_is_a_mirror_with_every_default():
    material = _material_of(_load(SceneNode(mesh=_quad('mirror'))))
    reflector = material.reflector
    assert isinstance(reflector, PlanarReflector)
    assert (reflector.scale, reflector.interval, reflector.priority) == \
        pytest.approx((0.5, 3, 1.0))
    assert not reflector.replace


def test_the_parameters_say_what_the_mirror_is_worth():
    material = _material_of(_load(SceneNode(mesh=_quad({
        'kind': 'mirror', 'scale': 0.25, 'interval': 2, 'priority': 4.0,
        'distortion': 0.05, 'reflectance': 0.9}))))
    reflector = material.reflector
    assert (reflector.scale, reflector.interval, reflector.priority,
            reflector.distortion, reflector.reflectance) == pytest.approx(
                (0.25, 2, 4.0, 0.05, 0.9))


def test_the_material_the_file_carries_is_kept():
    """Its colour tints the reflection, and its roughness weights it."""
    material = _material_of(_load(SceneNode(mesh=_quad(
        'mirror', colour=(0.9, 0.7, 0.4), metallic=0.0, roughness=0.1))))
    assert tuple(material.baseColor) == pytest.approx((0.9, 0.7, 0.4))
    assert material.metallic == pytest.approx(0.0)
    assert material.roughness == pytest.approx(0.1)


def test_a_parameter_that_is_not_a_number_is_reported_and_left_at_its_default(caplog):
    with caplog.at_level(logging.WARNING):
        material = _material_of(_load(SceneNode(mesh=_quad(
            {'kind': 'mirror', 'interval': 'often'}))))
    assert material.reflector.interval == 3
    assert any('interval' in record.getMessage() for record in caplog.records)


# --- on an object -------------------------------------------------------------

def test_an_object_tagged_mirror_shows_only_its_reflection():
    scene = _load(SceneNode(name='glass', mesh=[_quad(colour=(1, 0, 0)),
                                                _quad(colour=(0, 0, 1))],
                            extras={'OGLC_hook': 'mirror'}))
    materials = [shape.appearance.material for shape in _shapes(scene.getDEF('glass'))]
    assert len(materials) == 2
    assert all(material.reflector.replace for material in materials)
    assert materials[0].reflector is materials[1].reflector


def test_an_object_tag_leaves_the_rest_of_the_scene_alone():
    scene = _load(SceneNode(children=[
        SceneNode(name='glass', mesh=_quad(), extras={'OGLC_hook': 'mirror'}),
        SceneNode(name='wall', mesh=_quad())]))
    assert not _shapes(scene.getDEF('wall'))[0].appearance.material.reflector


def test_an_object_mirror_takes_the_parameters_too():
    scene = _load(SceneNode(name='glass', mesh=_quad(),
                            extras={'OGLC_hook': {'kind': 'mirror', 'interval': 1}}))
    material = _shapes(scene.getDEF('glass'))[0].appearance.material
    assert material.reflector.interval == 1 and material.reflector.replace


def test_an_object_tag_leaves_other_objects_on_the_same_mesh_alone():
    """The loader hands every node on one glTF mesh the same shapes."""
    mesh = _quad(colour=(0.2, 0.6, 0.2))
    scene = _load(SceneNode(children=[
        SceneNode(name='before', mesh=mesh),
        SceneNode(name='glass', mesh=mesh, extras={'OGLC_hook': 'mirror'}),
        SceneNode(name='after', mesh=mesh)]))
    before, = _shapes(scene.getDEF('before'))
    glass, = _shapes(scene.getDEF('glass'))
    after, = _shapes(scene.getDEF('after'))
    assert glass.appearance.material.reflector.replace
    for plain in (before, after):
        assert not plain.appearance.material.reflector
        assert tuple(plain.appearance.material.baseColor) == pytest.approx((0.2, 0.6, 0.2))
    assert glass.geometry is before.geometry is after.geometry


def _object_hook(children, params=None):
    from OpenGLContext.loaders.documentvalues import DocumentValues
    from OpenGLContext.scenegraph.mirrorhooks import mirror_hook
    ctx = hooks.HookContext(at='node', kind='mirror', params=params or {}, document=None,
                            resolver=None, scene_data={}, values=DocumentValues(),
                            children=children)
    assert mirror_hook(ctx) is None
    return ctx.children


def test_an_object_tag_reaches_the_shapes_under_its_levels_and_choices():
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.appearance import Appearance

    def shape():
        return Shape(geometry=_quad(), appearance=Appearance(material=PBRMaterial()))

    near, far, shown, hidden = shape(), shape(), shape(), shape()
    lod = basenodes.LOD(level=[near, far])
    switch = basenodes.Switch(choice=[basenodes.Transform(children=[shown]), hidden])
    children = _object_hook([lod, switch])
    found = [lod.level[0], lod.level[1], switch.choice[0].children[0], switch.choice[1]]
    for made, original in zip(found, (near, far, shown, hidden)):
        assert made is not original and made.geometry is original.geometry
        assert made.appearance.material.reflector.replace
        assert not original.appearance.material.reflector
    assert children == [lod, switch]


def test_a_replace_written_as_a_word_is_read_as_a_flag():
    material = _material_of(_load(SceneNode(mesh=_quad({'kind': 'mirror',
                                                         'replace': 'yes'}))))
    assert material.reflector.replace


def test_a_flag_where_a_number_belongs_is_reported_and_left_at_its_default(caplog):
    with caplog.at_level(logging.WARNING):
        material = _material_of(_load(SceneNode(mesh=_quad({'kind': 'mirror',
                                                             'scale': True}))))
    assert material.reflector.scale == pytest.approx(0.5)
    assert any('scale' in record.getMessage() for record in caplog.records)


# --- round trips --------------------------------------------------------------

def test_a_material_reflector_round_trips_through_the_writer():
    mesh = _quad()
    mesh.material.reflector = PlanarReflector(scale=0.75, interval=5, priority=2.0,
                                              reflectance=0.85)
    material = _material_of(_load(SceneNode(mesh=mesh)))
    reflector = material.reflector
    assert (reflector.scale, reflector.interval, reflector.priority,
            reflector.reflectance) == pytest.approx((0.75, 5, 2.0, 0.85))


def test_a_disabled_reflector_is_not_written():
    mesh = _quad()
    mesh.material.reflector = PlanarReflector(enabled=False)
    assert not _material_of(_load(SceneNode(mesh=mesh))).reflector


# --- water is a mirror --------------------------------------------------------

def test_water_puts_a_reflector_on_its_material():
    sheet = _quad('water')
    material = _material_of(_load(SceneNode(mesh=sheet)))
    assert material.reflector is WATER


def test_the_engines_water_material_reflects():
    assert water.water_material().reflector is WATER


# --- values a file should not have given ----------------------------------------

@pytest.mark.parametrize('params, name, expected', [
    ({'interval': float('inf')}, 'interval', 3),
    ({'interval': 1e999}, 'interval', 3),
    ({'interval': 0}, 'interval', 1),
    ({'interval': 2.5}, 'interval', 3),
    ({'scale': 'nan'}, 'scale', 0.5),
    ({'scale': float('nan')}, 'scale', 0.5),
    ({'scale': 1e9}, 'scale', 1.0),
    ({'scale': 0.0}, 'scale', 0.05),
    ({'priority': -4.0}, 'priority', 0.0),
    ({'distortion': float('-inf')}, 'distortion', 0.0),
    ({'reflectance': 7.0}, 'reflectance', 1.0),
    ({'replace': 'maybe'}, 'replace', False),
])
def test_a_value_no_mirror_can_have_is_its_default_or_its_bound(params, name, expected):
    """One malformed number is a mirror at its default, not a load that fails
    or a frame that fails every time the mirror is in view."""
    from OpenGLContext.scenegraph.mirrorhooks import reflector_for
    value = getattr(reflector_for(params), name)
    if isinstance(expected, bool):
        assert bool(value) is expected
    else:
        assert value == pytest.approx(expected)


def test_an_infinite_interval_in_a_file_loads():
    """``1e999`` in a JSON chunk is read as infinity."""
    scene = _load(SceneNode(mesh=_quad({'kind': 'mirror', 'interval': 1e999,
                                        'scale': float('nan')})))
    reflector = _material_of(scene).reflector
    assert reflector.interval == 3
    assert reflector.scale == pytest.approx(0.5)
