"""Order-independent transparency (X_ITE's OrderIndependentTransparency)

Weighted blended: each transparent fragment adds its colour times its
opacity and a weight to one target and its opacity times the weight to
another, and the two are composed over the opaque scene. The order the
surfaces are drawn in no longer decides which is on top.
"""
import pytest

from OpenGLContext import contextdefinition, renderoptions
from OpenGLContext.passes import oit


def quad(z, colour, transparency, half=False):
    left = b'0' if half else b'-5'
    return (b"<Shape><Appearance><Material diffuseColor='0 0 0' emissiveColor='%s'"
            b" transparency='%s'/></Appearance><IndexedFaceSet coordIndex='0 1 2 3'>"
            b"<Coordinate point='%s -5 %s 5 -5 %s 5 5 %s %s 5 %s'/></IndexedFaceSet></Shape>"
            % (colour, transparency, left, z, z, z, left, z))


def document(*shapes):
    return (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
            b"<NavigationInfo headlight='false'/>" + b''.join(shapes) + b"</Scene></X3D>")


def drawn(text, **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    from OpenGL import GL  # noqa: PLC0415 kept with its use
    with scene_context(Loader.loads(text, 'a.x3d'), size=(32, 32), **definition) as context:
        drawn_image(context)
        image = drawn_image(context).astype(int)
        assert GL.glGetError() == GL.GL_NO_ERROR
        return image


def test_the_weight_is_x_ites():
    assert oit.weight(0.5, 0.0) == pytest.approx(3e3)
    assert oit.weight(0.001, 0.5) == pytest.approx(0.02 ** 3 * 1e8 * 0.55 ** 3)
    assert oit.weight(0.0, 1.0) == pytest.approx(0.01 ** 3 * 1e8 * 0.1 ** 3)


def test_the_environment_is_the_default(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_ORDER_INDEPENDENT_TRANSPARENCY', '1')
    renderoptions.reset_env_cache()
    assert oit.enabled(contextdefinition.ContextDefinition())
    assert 'OPENGLCONTEXT_ORDER_INDEPENDENT_TRANSPARENCY' in renderoptions.ENVIRONMENT
    assert 'orderIndependentTransparency' in contextdefinition.ContextDefinition.RENDERING_FIELDS


def test_on_by_default():
    assert oit.enabled(contextdefinition.ContextDefinition())


def test_the_environment_can_turn_it_off(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_ORDER_INDEPENDENT_TRANSPARENCY', 'no')
    renderoptions.reset_env_cache()
    assert not oit.enabled(contextdefinition.ContextDefinition())


# Two surfaces whose shapes share an origin, so sorting by origin leaves
# them in the order the document gives
TWO = document(quad(b'-2', b'1 0 0', b'0.5'), quad(b'-3', b'0 0 1', b'0.5'))
SWAPPED = document(quad(b'-3', b'0 0 1', b'0.5'), quad(b'-2', b'1 0 0', b'0.5'))


def test_sorted_blending_depends_on_the_order_drawn(gl_context):
    assert abs(drawn(TWO, orderIndependentTransparency=False)[16, 16][2]
               - drawn(SWAPPED, orderIndependentTransparency=False)[16, 16][2]) > 50


def test_weighted_blending_mixes_the_two_surfaces(gl_context):
    red, green, blue = drawn(TWO, orderIndependentTransparency=True)[16, 16]
    swapped = drawn(SWAPPED, orderIndependentTransparency=True)[16, 16]
    assert tuple(swapped) == pytest.approx((red, green, blue), abs=2)
    assert abs(red - blue) < 20
    assert green < 4
    # three quarters covered: (1 - 0.5)(1 - 0.5) of the black behind shows
    assert red + blue == pytest.approx(0.75 * 255, abs=12)


def test_opaque_geometry_hides_what_is_behind_it(gl_context):
    scene = document(quad(b'-2', b'0 1 0', b'0', half=True), quad(b'-3', b'1 0 0', b'0.5'))
    image = drawn(scene, orderIndependentTransparency=True)
    assert tuple(image[16, 28]) == pytest.approx((0, 255, 0), abs=3)
    assert tuple(image[16, 4]) == pytest.approx((128, 0, 0), abs=6)


def test_a_transparent_line_is_weighted_too(gl_context):
    line = (b"<Shape><Appearance><Material emissiveColor='1 1 1' transparency='0.5'/>"
            b"</Appearance><IndexedLineSet coordIndex='0 1'>"
            b"<Coordinate point='-1 0.013 -1 1 0.013 -1'/></IndexedLineSet></Shape>")
    plain = drawn(document(line), orderIndependentTransparency=False)[16, 16]
    weighted = drawn(document(line), orderIndependentTransparency=True)[16, 16]
    assert tuple(weighted) == pytest.approx(tuple(plain), abs=4)


@pytest.mark.parametrize("weighted", [False, True])
def test_a_transparent_surface_is_picked(gl_context, weighted):
    from OpenGLContext.events import synthetic  # noqa: PLC0415 kept with its use
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(document(
        b"<Group>" + quad(b'-3', b'1 0 0', b'0.5') + b"<TouchSensor DEF='T'/></Group>"),
        'a.x3d')
    with scene_context(scene, size=(64, 64), orderIndependentTransparency=weighted) as context:
        context.OnDraw(force=1)
        synthetic.dispatch(context, {'type': 'mousemove', 'buttons': [], 'x': 32, 'y': 32,
                                     'pick': True})
        touch = scene.getDEF('T')
        for _ in range(120):
            context.OnDraw(force=1)
            if 'hitPoint_changed' in touch.__dict__:
                break
    assert touch.isOver is True
    assert tuple(touch.hitPoint_changed)[2] == pytest.approx(-3, abs=0.05)


SHADED = (b"<Shape><Appearance><Material transparency='0.5'/>"
          b"<ComposedShader language='GLSL'>"
          b"<field name='colour' type='SFColor' accessType='inputOutput' value='1 0 0'/>"
          b"<ShaderPart type='VERTEX'><![CDATA[#version 330 core\n"
          b"in vec4 x3d_Vertex; uniform mat4 x3d_ModelViewMatrix;"
          b" uniform mat4 x3d_ProjectionMatrix;\n"
          b"void main() { gl_Position = x3d_ProjectionMatrix * x3d_ModelViewMatrix * x3d_Vertex; }"
          b"]]></ShaderPart><ShaderPart type='FRAGMENT'><![CDATA[#version 330 core\n"
          b"uniform vec3 colour; out vec4 fragColour;\n"
          b"void main() { fragColour = vec4(colour, 0.5); }]]></ShaderPart>"
          b"</ComposedShader></Appearance><IndexedFaceSet coordIndex='0 1 2 3'>"
          b"<Coordinate point='-5 -5 -4 5 -5 -4 5 5 -4 -5 5 -4'/></IndexedFaceSet></Shape>")


@pytest.mark.parametrize("shaded_depth", [b'-4', b'-1'])
def test_a_shape_with_a_program_of_its_own_is_blended_in_order(gl_context, shaded_depth):
    """A custom-shader shape is drawn between the weighted surfaces by its depth"""
    scene = document(SHADED.replace(b'-4', shaded_depth), quad(b'-2', b'0 1 0', b'0.5'))
    plain = drawn(scene, orderIndependentTransparency=False)[16, 16]
    weighted = drawn(scene, orderIndependentTransparency=True)[16, 16]
    assert tuple(weighted) == pytest.approx(tuple(plain), abs=4)
    assert plain[0] > 40 and plain[1] > 100


def test_only_shapes_the_pass_draws_are_weighted():
    from OpenGLContext.scenegraph import basenodes  # noqa: PLC0415 kept with its use
    assert basenodes.Shape().drawsWeighted()
    shaded = basenodes.Shape(appearance=basenodes.Appearance(
        shaders=[basenodes.ComposedShader()]))
    assert not shaded.drawsWeighted()


def test_a_shape_naming_a_blend_mode_is_not_weighted():
    from OpenGLContext.scenegraph import basenodes, rendermodes  # noqa: PLC0415 kept with its use
    blended = basenodes.Shape(appearance=basenodes.Appearance(
        blendMode=rendermodes.BlendMode(sourceColorFactor='ONE')))
    assert not blended.drawsWeighted()


def test_text_is_not_weighted():
    from OpenGLContext.scenegraph import basenodes  # noqa: PLC0415 kept with its use
    assert not basenodes.Shape(geometry=basenodes.Text(string=['x'])).drawsWeighted()


def test_a_transparent_point_set_is_weighted_as_the_blend_gives(gl_context):
    points = (b"<Shape><Appearance><Material emissiveColor='1 1 1' transparency='0.5'/>"
              b"<PointProperties pointSizeScaleFactor='20'/></Appearance>"
              b"<PointSet><Coordinate point='0 0 -3'/></PointSet></Shape>")
    plain = drawn(document(points), orderIndependentTransparency=False)[16, 16]
    weighted = drawn(document(points), orderIndependentTransparency=True)[16, 16]
    assert plain[0] > 100
    assert tuple(weighted) == pytest.approx(tuple(plain), abs=4)


def test_a_transparent_textured_surface_is_weighted_as_the_blend_gives(gl_context):
    textured = (b"<Shape><Appearance><Material emissiveColor='1 1 1' transparency='0.5'/>"
                b"<PixelTexture image='1 1 3 0xFF8000'/></Appearance>"
                b"<IndexedFaceSet coordIndex='0 1 2 3'>"
                b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/>"
                b"<TextureCoordinate point='0 0 1 0 1 1 0 1'/></IndexedFaceSet></Shape>")
    plain = drawn(document(textured), orderIndependentTransparency=False)[16, 16]
    weighted = drawn(document(textured), orderIndependentTransparency=True)[16, 16]
    assert plain[0] > 100
    assert tuple(weighted) == pytest.approx(tuple(plain), abs=4)
