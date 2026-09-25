"""The PBR pass's per-shape batching answers follow every input they are made from.

``PBRPass.batchers`` remembers, per shape, the key an instance grouping puts it
under and whether it can be drawn instanced at all, so a frame does not work
either out again for a shape nothing has touched. Each test here asks, edits
one input in place, and asks again.
"""
import numpy as np
import pytest

from OpenGLContext.passes.pbrpass import PBRPass
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import PlanarReflector


def _mesh():
    return PBRMesh(
        positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0)], 'f'),
        normals=np.array([(0, 0, 1)] * 3, 'f'),
        texcoords=np.array([(0, 0), (1, 0), (1, 1)], 'f'),
        indices=np.array([0, 1, 2], np.uint32))


def _shape(material=None, geometry=None):
    return basenodes.Shape(
        geometry=geometry if geometry is not None else _mesh(),
        appearance=basenodes.Appearance(material=material or PBRMaterial()))


@pytest.fixture
def ask(monkeypatch):
    """Ask a pass for a shape's ``(key, instanceable)``, one grouping at a time."""
    monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', raising=False)
    passing = PBRPass.__new__(PBRPass)

    def answer(shape):
        key, instanceable = passing.batchers()
        return key(shape), instanceable(shape)
    return answer


def test_an_untouched_shape_is_answered_from_the_memo(ask, monkeypatch):
    shape = _shape()
    first = ask(shape)
    monkeypatch.setattr(PBRPass, '_keyFor', lambda *a: pytest.fail('asked again'))
    assert ask(shape) == first


def test_a_shape_that_becomes_a_mirror_is_drawn_singly(ask):
    shape = _shape()
    assert ask(shape)[1] is True
    shape.appearance.material.reflector = PlanarReflector()
    assert ask(shape)[1] is False


def test_a_mirror_switched_off_batches_again(ask):
    reflector = PlanarReflector()
    shape = _shape(PBRMaterial(reflector=reflector))
    assert ask(shape)[1] is False
    reflector.enabled = False
    assert ask(shape)[1] is True


def test_geometry_that_becomes_water_is_drawn_singly(ask):
    from OpenGLContext.scenegraph.water.surface import WaterStyle
    shape = _shape()
    assert ask(shape)[1] is True
    shape.geometry.waveStyle = WaterStyle()
    assert ask(shape)[1] is False


def test_a_texture_set_in_place_changes_the_key(ask):
    from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
    from PIL import Image
    material = PBRMaterial()
    shape = _shape(material)
    before = ask(shape)[0]
    material.textures['baseColor'] = PBRTexture(Image.new('RGB', (2, 2)), srgb=True)
    assert ask(shape)[0] != before


def test_a_texture_removed_in_place_changes_the_key(ask):
    from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
    from PIL import Image
    material = PBRMaterial(textures={
        'baseColor': PBRTexture(Image.new('RGB', (2, 2)), srgb=True)})
    shape = _shape(material)
    before = ask(shape)[0]
    del material.textures['baseColor']
    assert ask(shape)[0] != before


def test_an_impostor_does_not_batch_with_a_plain_material(ask):
    plain, impostor = _shape(), _shape()
    assert ask(plain)[0][1:] == ask(impostor)[0][1:]
    impostor.appearance.material.octahedralViews = 8
    assert ask(plain)[0][1:] != ask(impostor)[0][1:]


def test_a_new_appearance_is_seen(ask):
    shape = _shape()
    ask(shape)
    shape.appearance = basenodes.Appearance(material=PBRMaterial(
        reflector=PlanarReflector()))
    assert ask(shape)[1] is False
