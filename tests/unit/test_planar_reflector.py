"""A surface is a mirror when its material carries a PlanarReflector.

The node is how an author opts into the cost of reflecting the scene, and its
fields say how much one mirror is worth. These are the node's own claims: its
defaults, that it is a field of the material, that one can be shared and one
varied, and that it survives the VRML97 writer.
"""
import pytest

from OpenGLContext.loaders.vrml97 import VRML97Handler, defaultHandler
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.reflector import PlanarReflector


def test_a_reflector_defaults_to_half_scale_every_third_frame():
    reflector = PlanarReflector()
    assert reflector.reflectance == pytest.approx(0.97)
    assert reflector.scale == pytest.approx(0.5)
    assert reflector.interval == 3
    assert reflector.priority == pytest.approx(1.0)
    assert reflector.distortion == pytest.approx(0.0)
    assert reflector.enabled
    assert not reflector.replace


def test_a_material_reflects_the_probe_until_it_is_given_one():
    assert not PBRMaterial().reflector


def test_a_material_carries_its_reflector():
    reflector = PlanarReflector(interval=2)
    material = PBRMaterial(reflector=reflector)
    assert material.reflector is reflector


def test_one_reflector_serves_a_set_of_mirrors():
    shared = PlanarReflector(priority=2.0)
    first, second = PBRMaterial(reflector=shared), PBRMaterial(reflector=shared)
    shared.priority = 3.0
    assert first.reflector.priority == second.reflector.priority == pytest.approx(3.0)


def test_a_varied_reflector_is_a_mirror_of_its_own():
    shared = PlanarReflector(interval=2)
    own = shared.varied(interval=1)
    assert (shared.interval, own.interval) == (2, 1)


def test_a_reflector_survives_the_vrml97_writer():
    written = VRML97Handler.dumps(PlanarReflector(
        scale=0.25, interval=4, priority=2.5, distortion=0.1, enabled=False,
        replace=True))
    parsed, scene = defaultHandler().parse('#VRML V2.0 utf8\n' + written, 'memory:')
    assert parsed
    read, = scene.children
    assert isinstance(read, PlanarReflector)
    assert (read.scale, read.interval, read.priority, read.distortion) == \
        pytest.approx((0.25, 4, 2.5, 0.1))
    assert (bool(read.enabled), bool(read.replace)) == (False, True)
