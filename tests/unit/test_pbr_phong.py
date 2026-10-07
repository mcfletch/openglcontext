"""X3D's Phong equation in the PBR pass, for a document's Material.

X3D (19775-1, 17.2.2.5): emissive + the sum over the lights of
colour x intensity x attenuation x (ambient + diffuse N.L + specular (N.H)^(128
shininess)), on the colour values as given. A document's Material is drawn by
it; a Material built in code keeps the metallic-roughness conversion.
"""
import pytest

from OpenGLContext.passes.pbrpass import PHONG_BIT, pack_material_block
from OpenGLContext.scenegraph.physicalmaterial import pbr_material

QUAD = (b"<IndexedFaceSet coordIndex='0 1 2 3'>"
        b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/></IndexedFaceSet>")


def document(appearance):
    return (b"<X3D version='3.3'><Scene><Viewpoint position='0 0 0'/><Shape><Appearance>"
            + appearance + b"</Appearance>" + QUAD + b"</Shape></Scene></X3D>")


def centre(text, **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(text, 'a.x3d'), size=(32, 32), **definition) as context:
        drawn_image(context)
        return tuple(drawn_image(context)[16, 16].astype(int))


def flags(appearance):
    return int(pack_material_block(pbr_material(appearance)).view('int32')[29])


def test_a_documents_material_is_phong():
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    scene = Loader.loads(document(b"<Material/>"), 'a.x3d')
    assert flags(scene.children[1].appearance) & PHONG_BIT


def test_a_material_built_in_code_is_converted():
    from OpenGLContext.scenegraph.basenodes import Appearance, Material  # noqa: PLC0415 kept with its use
    assert not flags(Appearance(material=Material())) & PHONG_BIT


@pytest.mark.parametrize('appearance, expected', [
    # the headlight, straight on: the diffuse colour itself
    (b"<Material diffuseColor='0.5 0.25 0'/>", (128, 64, 0)),
    # emissive adds
    (b"<Material diffuseColor='0.25 0.25 0.25' emissiveColor='0.25 0 0'/>", (128, 64, 64)),
    # a texture multiplies the diffuse colour, as given
    (b"<Material diffuseColor='1 1 1'/><PixelTexture image='1 1 3 0x804000'/>", (128, 64, 0)),
    # specular at the highlight: N.H is 1
    (b"<Material diffuseColor='0.25 0.25 0.25' specularColor='0.25 0.25 0.25'/>", (128, 128, 128)),
])
def test_drawn_by_x3ds_equation(gl_context, appearance, expected):
    assert centre(document(appearance)) == pytest.approx(expected, abs=3)


@pytest.mark.parametrize('appearance, expected', [
    (b"<Material diffuseColor='0.5 0.25 0'/>", (128, 64, 0)),
    # no material: unlit, the texture's colour as given
    (b"<PixelTexture image='1 1 3 0x804000'/>", (128, 64, 0)),
])
def test_bloom_leaves_what_x3d_displays_as_it_is(gl_context, appearance, expected):
    assert centre(document(appearance), bloom=True) == pytest.approx(expected, abs=4)


FOGGED = (b"<X3D version='3.3'><Scene><Viewpoint position='0 0 0'/>"
          b"<Fog fogType='LINEAR' color='0.5 0.25 0' visibilityRange='1'/>"
          b"<Shape><Appearance>%s</Appearance>" + QUAD + b"</Shape></Scene></X3D>")


@pytest.mark.parametrize('bloom', [False, True])
@pytest.mark.parametrize('appearance', [b"<Material diffuseColor='0 0 1'/>",
                                        b"<PhysicalMaterial baseColor='0 0 1'/>"])
def test_a_surface_past_the_fogs_range_is_the_fog_colour(gl_context, appearance, bloom):
    assert centre(FOGGED % appearance, bloom=bloom) == pytest.approx((128, 64, 0), abs=4)


LIT = (b"<X3D version='3.3'><Scene><Viewpoint position='0 0 0'/><NavigationInfo headlight='false'/>"
       b"%s<Shape><Appearance><Material diffuseColor='1 1 1' ambientIntensity='%s'/></Appearance>"
       + QUAD + b"</Shape></Scene></X3D>")


def lit(light, ambient, renderer):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(LIT % (light, ambient), 'a.x3d'), size=(32, 32),
                       renderer=renderer) as context:
        drawn_image(context)
        return int(drawn_image(context)[16, 16][0])


@pytest.mark.parametrize('renderer', ['pbr', 'vrml97'])
def test_a_lights_ambient_intensity(gl_context, renderer):
    """X3D's ambient: the light's ambientIntensity times the Material's, times
    the diffuse colour; a document has no other ambient light"""
    light = b"<PointLight location='0 0 -1' intensity='0.5' ambientIntensity='%s'/>"
    assert lit(light % b'0', b'0.5', renderer) == pytest.approx(128, abs=3)
    assert lit(light % b'0.4', b'0.5', renderer) == pytest.approx(255 * 0.7, abs=3)


def test_a_glTF_light_has_no_ambient():
    import numpy as np  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.gltf import scene  # noqa: PLC0415 kept with its use
    from OpenGLContext.passes.shaderpass import configure_light_from_node  # noqa: PLC0415 kept with its use

    class Recording:
        lights = []

        def set_light(self, index, **named):
            self.lights.append(named)
    program = Recording()
    configure_light_from_node(program, 0, scene._light_node({'type': 'point'}, np.identity(4)),  # noqa: SLF001 one KHR_lights_punctual entry built without a document around it
                              np.identity(4))
    assert program.lights[0]['ambient_intensity'] == 0.0
