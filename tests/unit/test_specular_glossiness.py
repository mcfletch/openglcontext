"""SpecularGlossinessMaterial: glTF's specular/glossiness workflow, drawn as X_ITE draws it.

The diffuse colour is the base colour, the specular colour the reflectance at
normal incidence and the roughness 1 - glossiness, with no metal; the
specular/glossiness map's RGB tints the reflectance and its alpha the
glossiness. A glTF material with KHR_materials_pbrSpecularGlossiness and no
pbrMetallicRoughness loads as one.
"""
import numpy as np
import pytest

from OpenGLContext.passes.pbrpass import SPECULAR_GLOSSINESS_BIT, pack_material_block
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.physicalmaterial import pbr_material
from OpenGLContext.scenegraph.specularglossiness import SpecularGlossinessMaterial


def test_the_block_is_the_diffuse_colour_with_the_specular_reflectance():
    material = SpecularGlossinessMaterial(diffuseColor=(0.5, 0.25, 0.125),
                                          specularColor=(0.9, 0.6, 0.3), glossiness=0.75,
                                          emissiveColor=(0.1, 0.0, 0.0), transparency=0.5)
    buf = pack_material_block(material)
    assert np.allclose(buf[0:3], (0.5, 0.25, 0.125))
    assert buf[3] == 0.0                      # no metal
    assert buf[7] == pytest.approx(0.75)      # the glossiness, under the flag
    assert np.allclose(buf[8:11], (0.9, 0.6, 0.3))
    assert np.allclose(buf[4:7], (0.1, 0.0, 0.0))
    assert buf.view(np.int32)[29] & SPECULAR_GLOSSINESS_BIT


def test_its_maps_are_channels():
    diffuse, gloss = ImageDataTexture(), ImageDataTexture()
    material = SpecularGlossinessMaterial(diffuseTexture=diffuse,
                                          specularGlossinessTexture=gloss,
                                          specularGlossinessTextureMapping='TEXCOORD_1')
    assert material.texture('baseColor') is diffuse
    assert material.texture('specularColor') is gloss
    assert material.textureMapping('specularColor') == 'TEXCOORD_1'
    assert pbr_material(Appearance(material=material)) is material


SPHERES = b'''<X3D version="4.0"><head><component name="X_ITE" level="1"/></head><Scene>
  <Background skyColor="0 0 0"/><Viewpoint position="0 0 3"/>
  <NavigationInfo headlight="false"/>
  <PointLight location="0 0 3" intensity="1"/>
  <Shape><Appearance><SpecularGlossinessMaterial diffuseColor="0 0 0"
     specularColor="%s" glossiness="%s"/></Appearance><Sphere/></Shape>
</Scene></X3D>'''


def highlight(specular, glossiness):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(SPHERES % (specular, glossiness), 'sg.x3d')
    with scene_context(scene, size=(48, 48), environment={'OPENGLCONTEXT_IBL': 'off'}) as context:
        return drawn_image(context)[24, 24].astype(int)


def test_the_specular_colour_is_the_reflection(gl_context):
    gold = highlight(b'1 0.6 0.1', b'0.9')
    assert gold[0] > gold[1] > gold[2], gold
    assert gold[0] > 150


def test_glossiness_narrows_the_highlight(gl_context):
    sharp = highlight(b'1 1 1', b'0.95')
    broad = highlight(b'1 1 1', b'0.2')
    assert sharp.sum() > broad.sum() + 45, (sharp, broad)


def test_a_gltf_round_trip_keeps_the_workflow():
    from OpenGLContext.loaders import gltf  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.gltf.writer import write_glb  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.shape import Shape  # noqa: PLC0415 kept with its use
    material = SpecularGlossinessMaterial(diffuseColor=(0.5, 0.25, 0.0),
                                          specularColor=(0.9, 0.6, 0.3), glossiness=0.75)
    mesh = PBRMesh(appearance=Appearance(material=material),
                   positions=np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0)], 'f'),
                   indices=np.array([0, 1, 2], np.uint32))
    scene = gltf.load_gltf(write_glb(mesh))
    stack, found = [scene.group], None
    while stack and found is None:
        current = stack.pop()
        if isinstance(current, Shape):
            found = current.appearance.material
        stack.extend(getattr(current, 'children', None) or ())
    assert isinstance(found, SpecularGlossinessMaterial)
    assert list(found.specularColor) == pytest.approx([0.9, 0.6, 0.3])
    assert found.glossiness == pytest.approx(0.75)


@pytest.mark.parametrize('encoding', ['xml', 'classic', 'json'])
def test_an_x3d_round_trip_keeps_the_node(encoding):
    from vrml import x3d as vrml_x3d  # noqa: PLC0415 kept with its use
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    from vrml.x3d.scene import X3DScene  # noqa: PLC0415 kept with its use

    from OpenGLContext.loaders.x3d import prototypes  # noqa: PLC0415 kept with its use
    material = SpecularGlossinessMaterial(specularColor=(0.9, 0.6, 0.3), glossiness=0.25)
    scene = X3DScene(children=[x3d.Shape(appearance=Appearance(material=material),
                                         geometry=x3d.Box())])
    read = vrml_x3d.loads(vrml_x3d.dumps(scene, encoding=encoding), prototypes=prototypes())
    found = read.children[0].appearance.material
    assert isinstance(found, SpecularGlossinessMaterial)
    assert found.glossiness == pytest.approx(0.25)
