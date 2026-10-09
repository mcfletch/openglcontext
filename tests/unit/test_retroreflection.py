"""KHR_materials_retroreflection: specular light sent back towards its source.

A retroreflective surface evaluates its specular lobes with the view
direction mirrored about the normal, so a light beside the eye lights a
tilted panel that an ordinary surface reflects away. The factor blends the
two, and the texture's red channel scales it.
"""
import numpy as np
import pytest

from OpenGLContext.passes.pbrpass import (
    PBR_SHARED_CHANNELS, PBR_TEXTURE_BITS, pack_material_block,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial


def test_the_factor_is_packed_in_the_block():
    buf = pack_material_block(PhysicalMaterial(retroreflection=0.75))
    assert buf[36] == pytest.approx(0.75)
    assert pack_material_block(PhysicalMaterial())[36] == 0.0


def test_the_map_has_a_bit_and_shares_a_sampler():
    assert 'retroreflection' in PBR_TEXTURE_BITS
    assert PBR_SHARED_CHANNELS['retroreflection'] in PBR_TEXTURE_BITS


PANEL = b'''<X3D version="4.0"><Scene>
  <Background skyColor="0 0 0"/><Viewpoint position="0 0 4"/>
  <NavigationInfo headlight="false"/>
  <PointLight location="0 0 4" intensity="3" attenuation="0 0 0.06"/>
  <Transform rotation="0 1 0 0.9"><Shape><Appearance>%s</Appearance>
    <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
      <Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>
      <TextureCoordinate point="0 0 1 0 1 1 0 1"/>
    </IndexedTriangleSet></Shape></Transform>
</Scene></X3D>'''


def panel(material):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(PANEL % material, 'panel.x3d')
    with scene_context(scene, size=(48, 48), environment={'OPENGLCONTEXT_IBL': 'off'}) as context:
        return drawn_image(context)[24, 24].astype(int)


BLACK = (b'<PixelTexture containerField="retroreflectionTexture" image="1 1 1 0x00"/>')


def material(factor, texture=b''):
    return (b'<PhysicalMaterial baseColor="0.1 0.1 0.1" metallic="0" roughness="0.3">'
            b'<RetroreflectionMaterialExtension retroreflection="%s">%s'
            b'</RetroreflectionMaterialExtension></PhysicalMaterial>'
            % (str(factor).encode(), texture))


def test_a_retroreflective_panel_returns_the_light_beside_the_eye(gl_context):
    plain = panel(material(0))
    retro = panel(material(1))
    assert retro.sum() > plain.sum() + 60, (plain, retro)


def test_a_black_map_leaves_the_panel_ordinary(gl_context):
    plain = panel(material(0))
    masked = panel(material(1, BLACK))
    assert np.abs(masked - plain).max() <= 3, (plain, masked)
