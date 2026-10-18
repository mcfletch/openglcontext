"""Tone curve, exposure and colour space as a document is drawn (GL)

X_ITE's defaults: no curve, exposure 1, a PhysicalMaterial lit in linear
light and encoded to sRGB, a Material and an unlit appearance drawn on their
colour values as given. The curve and the exposure apply to all of them.
"""
import pytest

#: sRGB encodings of the linear values the cases below write
ENCODED = {0.25: 137, 0.5: 188, 0.6163: 206}

QUAD = (b"<IndexedFaceSet coordIndex='0 1 2 3'>"
        b"<Coordinate point='-5 -5 -3 5 -5 -3 5 5 -3 -5 5 -3'/></IndexedFaceSet>")


def document(appearance, background=b''):
    return (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
            b"<NavigationInfo headlight='false'/>" + background
            + b"<Shape><Appearance>" + appearance + b"</Appearance>" + QUAD
            + b"</Shape></Scene></X3D>")


def centre(text, at=(16, 16), **definition):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    with scene_context(Loader.loads(text, 'a.x3d'), size=(32, 32), **definition) as context:
        drawn_image(context)
        return tuple(drawn_image(context)[at].astype(int))


PHYSICAL = b"<PhysicalMaterial baseColor='0 0 0' metallic='1' roughness='1' emissiveColor='0.5 0.5 0.5'/>"
PHONG = b"<Material diffuseColor='0 0 0' specularColor='0 0 0' emissiveColor='0.5 0.5 0.5'/>"
UNLIT = b"<PixelTexture image='1 1 3 0x808080'/>"


@pytest.mark.parametrize('definition, expected', [
    ({}, ENCODED[0.5]),
    ({'toneMapping': 'aces_narkowicz'}, ENCODED[0.6163]),
    ({'exposure': 0.5}, ENCODED[0.25]),
    ({'colorSpace': 'srgb'}, 128),
    ({'bloom': True}, ENCODED[0.5]),
])
def test_a_physical_material(gl_context, definition, expected):
    assert centre(document(PHYSICAL), **definition) == pytest.approx((expected,) * 3, abs=3)


@pytest.mark.parametrize('definition, expected', [
    ({}, 128),
    ({'exposure': 0.5}, 64),
    # Narkowicz's curve on the value as given: 0.6425 / 1.0425
    ({'toneMapping': 'aces_narkowicz'}, 157),
    ({'colorSpace': 'linear'}, ENCODED[0.5]),
    ({'bloom': True}, 128),
    ({'bloom': True, 'toneMapping': 'khr_pbr_neutral'}, 117),
])
def test_a_material(gl_context, definition, expected):
    assert centre(document(PHONG), **definition) == pytest.approx((expected,) * 3, abs=3)


@pytest.mark.parametrize('definition, expected', [
    ({}, 128),
    ({'exposure': 0.5}, 64),
    ({'toneMapping': 'khr_pbr_neutral'}, 117),
])
def test_an_unlit_appearance(gl_context, definition, expected):
    assert centre(document(UNLIT), **definition) == pytest.approx((expected,) * 3, abs=3)


@pytest.mark.parametrize('definition, expected', [
    ({}, 128),
    ({'exposure': 0.5}, 64),
])
def test_a_background(gl_context, definition, expected):
    sky = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
           b"<Background skyColor='0.5 0.5 0.5'/></Scene></X3D>")
    assert centre(sky, **definition) == pytest.approx((expected,) * 3, abs=3)


@pytest.mark.parametrize('definition, expected', [
    ({}, 128),
    ({'exposure': 0.5}, 64),
])
def test_a_textured_background(gl_context, definition, expected):
    sky = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
           b"<TextureBackground><PixelTexture containerField='frontTexture' image='1 1 3 0x808080'/>"
           b"</TextureBackground></Scene></X3D>")
    assert centre(sky, **definition) == pytest.approx((expected,) * 3, abs=3)


LINES = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
         b"<Shape><Appearance><Material emissiveColor='0.5 0.5 0.5'/>"
         b"<LineProperties linewidthScaleFactor='%s'/></Appearance>"
         b"<IndexedLineSet coordIndex='0 1 -1 2 3'>"
         b"<Coordinate point='-1 0.013 -1 1 0.013 -1 0.013 -1 -1 0.013 1 -1'/></IndexedLineSet></Shape>"
         b"</Scene></X3D>")


@pytest.mark.parametrize('width', [b'1', b'4'])
@pytest.mark.parametrize('definition, expected', [
    ({}, 128),
    ({'exposure': 0.5}, 64),
])
def test_a_line(gl_context, width, definition, expected):
    assert centre(LINES % width, **definition) == pytest.approx((expected,) * 3, abs=3)


POINTS = (b"<X3D version='4.0'><Scene><Viewpoint position='0 0 0'/>"
          b"<Shape><Appearance><PointProperties pointSizeScaleFactor='8' pointSizeMaxValue='8'/></Appearance>"
          b"<PointSet><Color color='0.5 0.5 0.5'/><Coordinate point='0 0 -1'/></PointSet></Shape>"
          b"</Scene></X3D>")


@pytest.mark.parametrize('definition, expected', [
    ({}, 128),
    ({'exposure': 0.5}, 64),
])
def test_a_point(gl_context, definition, expected):
    assert centre(POINTS, **definition) == pytest.approx((expected,) * 3, abs=3)


def built_in_code(**definition):
    from OpenGLContext.scenegraph import basenodes as b  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    shape = b.Shape(appearance=b.Appearance(material=b.Material(diffuseColor=(0.8, 0.8, 0.8))),
                    geometry=b.Box(size=(20, 20, 0.1)))
    with scene_context([b.Viewpoint(position=(0, 0, 3)), b.Transform(translation=(0, 0, -2),
                        children=[shape])], size=(32, 32), **definition) as context:
        drawn_image(context)
        return tuple(drawn_image(context)[16, 16].astype(int))


def test_a_scene_built_in_code_is_drawn_with_the_engines_curve(gl_context):
    engine = built_in_code()
    assert engine == built_in_code(toneMapping='aces_narkowicz')
    assert engine != built_in_code(toneMapping='none')
