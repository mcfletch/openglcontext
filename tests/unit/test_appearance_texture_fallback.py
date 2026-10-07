"""Appearance.texture as a PhysicalMaterial's or UnlitMaterial's base map.

X3D 4 (ISO/IEC 19775-1, 17.2.2.4 and 17.2.2.6): where the material's own
``baseTexture`` or ``emissiveTexture`` is NULL, the appearance's ``texture``
is used in its place. ``pbr_material`` answers a view of the material that
has it.
"""
import pytest

from OpenGLContext.scenegraph.basenodes import Appearance, ImageTexture
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial, pbr_material
from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial


@pytest.mark.parametrize('kind', [PhysicalMaterial, UnlitMaterial])
def test_the_appearance_texture_is_the_base_map(kind):
    texture = ImageTexture()
    appearance = Appearance(material=kind(), texture=texture)
    assert pbr_material(appearance).textures['baseColor'] is texture


def test_the_materials_own_map_comes_first():
    own, other = ImageTexture(), ImageTexture()
    material = PhysicalMaterial(baseTexture=own)
    drawn = pbr_material(Appearance(material=material, texture=other))
    assert drawn is material
    assert drawn.textures['baseColor'] is own


def test_with_no_appearance_texture_the_material_is_drawn_as_itself():
    material = UnlitMaterial()
    assert pbr_material(Appearance(material=material)) is material


def test_the_view_reads_the_materials_fields():
    material = UnlitMaterial(emissiveColor=(1, 0, 0), transparency=0.25)
    appearance = Appearance(material=material, texture=ImageTexture())
    drawn = pbr_material(appearance)
    assert drawn.transparency == pytest.approx(0.25)
    assert drawn.material is material


def test_the_views_version_moves_with_the_material_and_the_texture():
    material = PhysicalMaterial()
    appearance = Appearance(material=material, texture=ImageTexture())
    drawn = pbr_material(appearance)
    first = drawn.factorVersion
    material.roughness = 0.25
    second = pbr_material(appearance).factorVersion
    assert second != first
    appearance.texture = ImageTexture()
    assert pbr_material(appearance).factorVersion != second


CHECKER = b'<PixelTexture repeatS="false" repeatT="false" image="2 1 3 0xFF0000 0x00FF00"/>'


def test_an_unlit_material_draws_the_appearance_texture(gl_context):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint position="0.5 0.5 2"/>
      <Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/>''' + CHECKER + b'''</Appearance>
        <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
          <Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/>
          <TextureCoordinate point="0 0 1 0 1 1 0 1"/>
        </IndexedTriangleSet></Shape>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(64, 64)) as context:
        image = drawn_image(context).astype(int)
    left, right = image[32, 22], image[32, 42]
    assert left[0] > left[1] + 100
    assert right[1] > right[0] + 100
