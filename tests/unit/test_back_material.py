"""Back faces drawn with their own material: X3D 4's backMaterial and TwoSidedMaterial.

A shape whose geometry is not ``solid`` draws its back faces with
``Appearance.backMaterial``, or with a ``TwoSidedMaterial``'s ``back...``
fields where its ``separateBackColor`` is true; the front faces keep the
material. ``pbr_material(appearance, back=True)`` is what the back faces are
drawn with.
"""
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph.basenodes import Appearance, Material
from OpenGLContext.scenegraph.physicalmaterial import (
    PhysicalMaterial, material_to_pbr, pbr_material, two_sided,
)


def test_back_material_is_drawn_for_the_back():
    back = PhysicalMaterial(baseColor=(0, 0, 1))
    appearance = Appearance(material=PhysicalMaterial(), backMaterial=back)
    assert two_sided(appearance)
    assert pbr_material(appearance, back=True) is back
    assert pbr_material(appearance) is appearance.material


def test_a_vrml97_style_back_material_is_up_converted():
    appearance = Appearance(material=Material(diffuseColor=(1, 0, 0)),
                            backMaterial=Material(diffuseColor=(0, 1, 0)))
    front, back = pbr_material(appearance), pbr_material(appearance, back=True)
    assert front is not back
    assert back.material is appearance.backMaterial


def test_a_two_sided_material_with_separate_colours_has_a_back():
    material = x3d.TwoSidedMaterial(diffuseColor=(1, 0, 0), backDiffuseColor=(0, 0, 1),
                                    separateBackColor=True)
    appearance = Appearance(material=material)
    assert two_sided(appearance)
    back = material_to_pbr(pbr_material(appearance, back=True).material)
    front = material_to_pbr(pbr_material(appearance).material)
    assert back['base_color'][2] > back['base_color'][0]
    assert front['base_color'][0] > front['base_color'][2]


def test_a_two_sided_material_without_separate_colours_is_one_sided():
    assert not two_sided(Appearance(material=x3d.TwoSidedMaterial()))
    assert not two_sided(Appearance(material=Material()))


def test_the_two_sided_material_is_the_engines():
    assert prototypes()['TwoSidedMaterial'] is x3d.TwoSidedMaterial


def wall(appearance, eye):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint ''' + eye + b'''/>
      <DirectionalLight direction="0 0 -1" intensity="0"/>
      <Shape>''' + appearance + b'''
        <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
          <Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>
        </IndexedTriangleSet></Shape>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(32, 32)) as context:
        return drawn_image(context)[16, 16].astype(int)


@pytest.mark.parametrize('appearance', [
    b'''<Appearance><UnlitMaterial emissiveColor="1 0 0"/>
        <UnlitMaterial containerField="backMaterial" emissiveColor="0 0 1"/></Appearance>''',
    b'''<Appearance><TwoSidedMaterial emissiveColor="1 0 0" backEmissiveColor="0 0 1"
        diffuseColor="0 0 0" backDiffuseColor="0 0 0" separateBackColor="true"/></Appearance>''',
])
def test_the_back_of_a_wall_wears_its_back_material(gl_context, appearance):
    front = wall(appearance, b'position="0 0 3"')
    back = wall(appearance, b'position="0 0 -3" orientation="0 1 0 3.14159265"')
    assert front[0] > front[2] + 100
    assert back[2] > back[0] + 100
