"""MultiTexture, cube maps and 3D textures drawn: the stage chain on screen

A square facing the camera, unlit so the chain's result is the colour drawn,
in each renderer: the PBR program and the VRML97 one.
"""
import pytest

RENDERERS = ['pbr', 'vrml97']


def pixel(colour, alpha=None):
    if alpha is None:
        return b'<PixelTexture image="1 1 3 %s"/>' % colour
    return b'<PixelTexture image="1 1 4 %s%02X"/>' % (colour, alpha)


def square(texture, coordinates=b'', material=b'<UnlitMaterial emissiveColor="1 1 1"/>',
           transform=b''):
    return (b'<Shape><Appearance>' + material + texture + transform + b'</Appearance>'
            b'<IndexedTriangleSet index="0 1 2 0 2 3" solid="false">'
            b'<Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>' + coordinates +
            b'</IndexedTriangleSet></Shape>')


def drawn(body, renderer, size=32):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         b'<Viewpoint position="0 0 2.4"/>' + body + b'</Scene></X3D>',
                         'scene.x3d')
    with scene_context(scene, size=(size, size), renderer=renderer) as context:
        context.OnDraw(force=1)
        return drawn_image(context).astype(int)


def centre(image):
    height, width = image.shape[:2]
    return tuple(image[height // 2, width // 2])


def close(found, expected, tolerance=6):
    return all(abs(a - b) <= tolerance for a, b in zip(found, expected))


CASES = [
    # (mode, source, function, colours, expected)
    (b'"MODULATE" "MODULATE"', b'', b'', (b'0xFF8000', b'0x00FFFF'), (0, 128, 0)),
    (b'"MODULATE" "ADD"', b'', b'', (b'0x800000', b'0x008000'), (128, 128, 0)),
    # The PBR program combines an unlit or physical surface's textures in
    # linear light, the VRML97 one as they are displayed.
    (b'"MODULATE" "SUBTRACT"', b'', b'', (b'0x808080', b'0xFF4000'),
     {'vrml97': (127, 0, 0), 'pbr': (229, 0, 0)}),
    (b'"MODULATE" "REPLACE"', b'', b'', (b'0xFF0000', b'0x0000FF'), (0, 0, 255)),
    (b'"MODULATE" "SELECT_ARG2"', b'', b'', (b'0xFF0000', b'0x0000FF'), (255, 0, 0)),
    (b'"MODULATE" "MODULATE"', b'"" "FACTOR"', b'', (b'0xFFFFFF', b'0x0000FF'), (64, 128, 191)),
    (b'"REPLACE"', b'', b'"COMPLEMENT"', (b'0xFF0000',), (0, 255, 255)),
    (b'"MODULATE" "ADDSIGNED"', b'', b'', (b'0x808080', b'0x404040'),
     {'vrml97': (64, 64, 64), 'pbr': (0, 0, 0)}),
]


@pytest.mark.parametrize('renderer', RENDERERS)
@pytest.mark.parametrize('mode, source, function, colours, expected', CASES)
def test_a_multitexture_combines_its_layers_by_their_modes(
        gl_context, renderer, mode, source, function, colours, expected):
    texture = (b"<MultiTexture mode='" + mode + b"' color='0.25 0.5 0.75'"
               + (b" source='" + source + b"'" if source else b'')
               + (b" function='" + function + b"'" if function else b'') + b'>'
               + b''.join(pixel(colour) for colour in colours) + b'</MultiTexture>')
    if isinstance(expected, dict):
        expected = expected[renderer]
    found = centre(drawn(square(texture), renderer))
    assert close(found, expected), (found, expected)


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_multitexture_starts_from_the_materials_colour(gl_context, renderer):
    texture = b'<MultiTexture mode=\'"MODULATE"\'>' + pixel(b'0xFFFFFF') + b'</MultiTexture>'
    found = centre(drawn(square(
        texture, material=b'<UnlitMaterial emissiveColor="0 1 0"/>'), renderer))
    assert close(found, (0, 255, 0)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_each_layer_reads_its_own_transform(gl_context, renderer):
    # Two texels: red on the left, green on the right; the second layer's
    # coordinates are moved half a texture, so it reads the other texel.
    two = b'<PixelTexture repeatS="true" image="2 1 3 0xFF0000 0x00FF00"/>'
    texture = (b'<MultiTexture mode=\'"REPLACE" "ADD"\'>' + two + two + b'</MultiTexture>')
    transforms = (b'<MultiTextureTransform><TextureTransform/>'
                  b'<TextureTransform translation="0.5 0"/></MultiTextureTransform>')
    coordinates = b'<TextureCoordinate point="0 0 1 0 1 1 0 1"/>'
    image = drawn(square(texture, coordinates, transform=transforms), renderer, size=64)
    # Red plus green, on both halves.
    assert close(tuple(image[32, 20]), (255, 255, 0))
    assert close(tuple(image[32, 44]), (255, 255, 0))


FACES = (b'frontTexture', b'backTexture', b'leftTexture', b'rightTexture', b'topTexture',
         b'bottomTexture')
FACE_COLOURS = (b'0xFF0000', b'0x00FF00', b'0x0000FF', b'0xFFFF00', b'0x00FFFF', b'0xFF00FF')


def cube():
    return (b'<ComposedCubeMapTexture>' + b''.join(
        b'<PixelTexture containerField="%s" image="1 1 3 %s"/>' % (face, colour)
        for face, colour in zip(FACES, FACE_COLOURS)) + b'</ComposedCubeMapTexture>')


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_cube_map_shows_the_face_the_view_reflects_toward(gl_context, renderer):
    # Looking along -Z at a square facing +Z, the view reflects back along +Z:
    # the front face.
    found = centre(drawn(square(cube()), renderer))
    assert close(found, (255, 0, 0)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_cube_map_layer_in_a_multitexture(gl_context, renderer):
    texture = (b'<MultiTexture mode=\'"MODULATE" "MODULATE"\'>' + pixel(b'0xFFFF00') + cube()
               + b'</MultiTexture>')
    found = centre(drawn(square(texture), renderer))
    assert close(found, (255, 0, 0)), found


VOLUME = b'<PixelTexture3D image="3 1 1 2 0xFF0000 0x0000FF"/>'


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_3d_texture_reads_its_3d_coordinates(gl_context, renderer):
    coordinates = b'<TextureCoordinate3D point="0 0 1 1 0 1 1 1 1 0 1 1"/>'
    found = centre(drawn(square(VOLUME, coordinates), renderer))
    assert close(found, (0, 0, 255)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_3d_texture_without_coordinates_spans_the_bounds(gl_context, renderer):
    # The square is flat in z, so it reads r = 0: the first slice.
    found = centre(drawn(square(VOLUME), renderer))
    assert close(found, (255, 0, 0)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_generator_makes_a_layers_coordinates(gl_context, renderer):
    two = b'<PixelTexture repeatS="false" image="2 1 3 0xFF0000 0x00FF00"/>'
    texture = b'<MultiTexture mode=\'"REPLACE"\'>' + two + b'</MultiTexture>'
    coordinates = (b'<MultiTextureCoordinate><TextureCoordinateGenerator mode="COORD"/>'
                   b'</MultiTextureCoordinate>')
    image = drawn(square(texture, coordinates), renderer, size=64)
    # COORD reads the square's own x: below 0 on the left (clamped red),
    # above 0.5 on the right (green).
    assert close(tuple(image[32, 12]), (255, 0, 0))
    assert close(tuple(image[32, 54]), (0, 255, 0))


def drawn_fixed(body, size=32):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'<X3D version="4.0"><Scene><Background skyColor="0 0 0"/>'
                         b'<Viewpoint position="0 0 2.4"/>' + body + b'</Scene></X3D>',
                         'scene.x3d')
    with scene_context(scene, size=(size, size),
                       environment={'OPENGLCONTEXT_PROFILE': 'compatibility'}) as context:
        context.OnDraw(force=1)
        return drawn_image(context).astype(int)


def test_the_compatibility_profile_draws_a_multitextures_first_layer(gl_context):
    texture = (b'<MultiTexture mode=\'"REPLACE" "MODULATE"\'>' + pixel(b'0x00FF00')
               + pixel(b'0xFF0000') + b'</MultiTexture>')
    found = centre(drawn_fixed(square(texture, material=b'')))
    assert close(found, (0, 255, 0)), found


def test_the_compatibility_profile_reflects_a_cube_map(gl_context):
    found = centre(drawn_fixed(square(cube(), material=b'')))
    assert close(found, (255, 0, 0)), found


def test_the_compatibility_profile_spans_a_3d_texture_across_the_bounds(gl_context):
    found = centre(drawn_fixed(square(VOLUME, material=b'')))
    assert close(found, (255, 0, 0)), found


@pytest.mark.parametrize('renderer', RENDERERS)
def test_a_face_set_with_a_multitexture_coordinate_draws(gl_context, renderer):
    two = b'<PixelTexture repeatS="false" image="2 1 3 0xFF0000 0x00FF00"/>'
    texture = b'<MultiTexture mode=\'"REPLACE"\'>' + two + b'</MultiTexture>'
    body = (b'<Shape><Appearance><UnlitMaterial emissiveColor="1 1 1"/>' + texture
            + b'</Appearance><IndexedFaceSet coordIndex="0 1 2 3 -1" solid="false">'
            b'<Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>'
            b'<MultiTextureCoordinate><TextureCoordinateGenerator mode="COORD"/>'
            b'<TextureCoordinate point="0 0 1 0 1 1 0 1"/></MultiTextureCoordinate>'
            b'</IndexedFaceSet></Shape>')
    image = drawn(body, renderer, size=64)
    assert close(tuple(image[32, 12]), (255, 0, 0)), tuple(image[32, 12])
    assert close(tuple(image[32, 54]), (0, 255, 0)), tuple(image[32, 54])
