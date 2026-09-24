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
        'distortion': 0.05}))))
    reflector = material.reflector
    assert (reflector.scale, reflector.interval, reflector.priority,
            reflector.distortion) == pytest.approx((0.25, 2, 4.0, 0.05))


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


# --- round trips --------------------------------------------------------------

def test_a_material_reflector_round_trips_through_the_writer():
    mesh = _quad()
    mesh.material.reflector = PlanarReflector(scale=0.75, interval=5, priority=2.0)
    material = _material_of(_load(SceneNode(mesh=mesh)))
    reflector = material.reflector
    assert (reflector.scale, reflector.interval, reflector.priority) == \
        pytest.approx((0.75, 5, 2.0))


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
