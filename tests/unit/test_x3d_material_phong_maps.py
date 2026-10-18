"""X3D 4 Material's ambientTexture, shininessTexture and specularTexture, drawn.

Under X3D's lighting a Material is drawn by the Phong equation (19775-1,
17.2.2.5), and its maps multiply its terms as X_ITE applies them: the ambient
term by ``ambientTexture.rgb``, the specular colour by
``specularTexture.rgb``, and ``shininess`` by ``shininessTexture.a``.
"""
import pytest

from OpenGLContext.loaders.loader import Loader

#: A square facing the camera at the middle of the view, lit along the view.
SCENE = '''<X3D version="4.0"><Scene>
  <NavigationInfo headlight="false"/>
  <Viewpoint position="0 0 3"/>
  <DirectionalLight direction="0 0 -1" intensity="%(intensity)s" ambientIntensity="%(ambient)s"/>
  <Shape><Appearance><Material %(material)s>%(maps)s</Material></Appearance>
    <Box size="2 2 0.01"/></Shape>
</Scene></X3D>'''


def pixel(field_name, color):
    return '<PixelTexture containerField="%s" image="1 1 4 %s"/>' % (field_name, color)


def drawn(material, maps='', intensity='1', ambient='0', at=(16, 16), **definition):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    document = SCENE % dict(material=material, maps=maps, intensity=intensity, ambient=ambient)
    scene = Loader.loads(document.encode('utf-8'), 'scene.x3d')
    with scene_context(scene, size=(32, 32), **definition) as context:
        drawn_image(context)
        return drawn_image(context)[at].astype(int)


def test_the_ambient_texture_colours_the_ambient_term(gl_context):
    material = 'diffuseColor="1 1 1" ambientIntensity="1"'
    plain = drawn(material, intensity='0', ambient='1')
    tinted = drawn(material, pixel('ambientTexture', '0xFF0000FF'), intensity='0',
                   ambient='1')
    assert plain == pytest.approx((255, 255, 255), abs=3)
    assert tinted == pytest.approx((255, 0, 0), abs=3)


def test_the_ambient_texture_is_a_colour_map_in_linear_light(gl_context):
    # A mid-grey texel lit in linear light is decoded, so the frame's encoding
    # returns it as authored; read raw it would display as 188.
    material = 'diffuseColor="1 1 1" ambientIntensity="1"'
    shown = drawn(material, pixel('ambientTexture', '0x808080FF'), intensity='0',
                  ambient='1', colorSpace='linear')
    assert shown == pytest.approx((128, 128, 128), abs=3)


def test_the_specular_texture_colours_the_highlight(gl_context):
    material = 'diffuseColor="0 0 0" specularColor="1 1 1" shininess="0.01"'
    plain = drawn(material)
    tinted = drawn(material, pixel('specularTexture', '0x00FF00FF'))
    assert plain[0] > 200 and plain[2] > 200
    assert tinted[1] > 200 and tinted[0] < 5 and tinted[2] < 5


def test_the_shininess_texture_scales_the_shininess_by_its_alpha(gl_context):
    material = 'diffuseColor="0 0 0" specularColor="1 1 1" shininess="1"'
    corner = (4, 4)
    sharp = drawn(material, at=corner)
    softened = drawn(material, pixel('shininessTexture', '0xFFFFFF10'), at=corner)
    assert softened[0] > sharp[0] + 20


def test_the_specular_texture_is_drawn_with_sixteen_samplers(gl_context, sixteen_samplers):
    material = 'diffuseColor="0 0 0" specularColor="1 1 1" shininess="0.01"'
    tinted = drawn(material, pixel('specularTexture', '0x00FF00FF'))
    assert tinted[1] > 200 and tinted[0] < 5 and tinted[2] < 5


def test_all_three_maps_are_drawn_with_sixteen_samplers(gl_context, sixteen_samplers):
    # Blue is the diffuse term's alone where the ambient map is red and the
    # specular map green: 0.5 of each light's intensity
    material = ('diffuseColor="0.5 0.5 0.5" specularColor="1 1 1" shininess="0.01" '
                'ambientIntensity="1"')
    maps = (pixel('specularTexture', '0x00FF00FF') + pixel('ambientTexture', '0xFF0000FF')
            + pixel('shininessTexture', '0xFFFFFFFF'))
    tinted = drawn(material, maps, ambient='1')
    assert tinted == pytest.approx((255, 255, 128), abs=4)
