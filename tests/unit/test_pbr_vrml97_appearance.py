"""A VRML97 Appearance drawn by the PBR pass: its texture, transform and factors.

The PBR program reads a material's maps from ``textures`` and its factors,
UV transform included, from the packed material block.
:func:`~OpenGLContext.scenegraph.pbrmaterial.pbr_material` gives a VRML97
``Appearance`` that shape: its ``texture`` is the base colour map, its
``textureTransform`` the UV transform, and its ``Material`` the factors.
"""
import numpy as np
import pytest
from PIL import Image

from OpenGLContext.passes.pbrpass import (
    PBRShaderProgram, _pack_material_block, pack_material_block,
)
from OpenGLContext.passes.shaderpass import texture_transform_matrix
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, ImageTexture, Material, PixelTexture, Shape,
    TextureTransform,
)
from OpenGLContext.scenegraph.pbrmaterial import (
    PBRMaterial, pbr_material, srgb_to_linear,
)
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.testing.scenes import drawn_image, scene_context

#: The block's words for the UV transform's three columns, and the mask.
UV_COLUMNS = (slice(32, 35), slice(36, 39), slice(40, 43))
TEX_COORD_MASK = 29
BASE_COLOR_TRANSFORMED = 1 << 8


def _uv_matrix(block):
    return np.stack([block[c] for c in UV_COLUMNS], axis=1)


def _red():
    return ImageTexture(image=Image.new('RGB', (4, 4), (255, 0, 0)))


class TestTheView:
    def test_the_texture_is_the_base_colour_map(self):
        texture = _red()
        appearance = Appearance(material=Material(), texture=texture)
        assert pbr_material(appearance).textures == {'baseColor': texture}

    def test_no_texture_is_no_maps(self):
        assert pbr_material(Appearance(material=Material())).textures == {}

    def test_a_pbr_material_is_its_own_view(self):
        material = PBRMaterial()
        assert pbr_material(Appearance(material=material)) is material

    def test_no_appearance_has_no_material(self):
        assert pbr_material(None) is None

    def test_one_view_per_appearance(self):
        appearance = Appearance(material=Material())
        assert pbr_material(appearance) is pbr_material(appearance)
        assert pbr_material(appearance) is not pbr_material(
            Appearance(material=appearance.material))

    def test_transparency_is_the_materials(self):
        appearance = Appearance(material=Material(transparency=0.25))
        assert pbr_material(appearance).transparency == pytest.approx(0.25)

    def test_the_factors_are_the_materials(self):
        appearance = Appearance(material=Material(diffuseColor=(0.2, 0.4, 0.6)))
        block = pack_material_block(pbr_material(appearance))
        assert np.allclose(block[0:3], srgb_to_linear((0.2, 0.4, 0.6)))

    def test_the_texture_transform_is_the_uv_transform(self):
        transform = TextureTransform(scale=(2.0, 3.0), translation=(0.5, 0.25),
                                     rotation=0.3, center=(0.5, 0.5))
        appearance = Appearance(material=Material(), texture=_red(),
                                textureTransform=transform)
        block = pack_material_block(pbr_material(appearance))
        assert np.allclose(_uv_matrix(block),
                           texture_transform_matrix(transform), atol=1e-6)
        mask = int(block.view(np.int32)[TEX_COORD_MASK])
        assert mask & BASE_COLOR_TRANSFORMED

    def test_no_texture_transform_is_untransformed(self):
        appearance = Appearance(material=Material(), texture=_red())
        block = pack_material_block(pbr_material(appearance))
        assert np.allclose(_uv_matrix(block), np.identity(3))
        assert not int(block.view(np.int32)[TEX_COORD_MASK]) & BASE_COLOR_TRANSFORMED


def test_the_packed_block_follows_every_input():
    material = Material(diffuseColor=(1.0, 1.0, 1.0))
    transform = TextureTransform()
    appearance = Appearance(material=material, texture=_red())

    def ask():
        return pack_material_block(pbr_material(appearance)).copy()

    def fresh():
        return _pack_material_block(pbr_material(appearance))

    replacement = Material(diffuseColor=(0.1, 0.9, 0.1))
    check_memo_inputs(ask, [
        ('material.diffuseColor',
         lambda: setattr(material, 'diffuseColor', (0.5, 0.25, 0.125))),
        ('material.emissiveColor',
         lambda: setattr(material, 'emissiveColor', (0.1, 0.2, 0.3))),
        ('material.shininess', lambda: setattr(material, 'shininess', 0.9)),
        ('appearance.textureTransform',
         lambda: setattr(appearance, 'textureTransform', transform)),
        ('textureTransform.scale', lambda: setattr(transform, 'scale', (4.0, 4.0))),
        ('textureTransform.translation',
         lambda: setattr(transform, 'translation', (0.5, 0.0))),
        ('textureTransform.rotation', lambda: setattr(transform, 'rotation', 0.5)),
        ('textureTransform.center', lambda: setattr(transform, 'center', (0.5, 0.5))),
        ('appearance.material', lambda: setattr(appearance, 'material', replacement)),
        ('replacement.diffuseColor',
         lambda: setattr(replacement, 'diffuseColor', (0.3, 0.3, 0.9))),
    ], fresh=fresh)


class TestConfiguringTheProgram:
    """GL-free: an uncompiled program's setters return before any GL call."""

    def _program(self):
        program = PBRShaderProgram()
        program.transmission_mode = 'off'
        program.reset_appearance_cache()
        return program

    def test_appearances_sharing_a_material_each_bind_their_texture(self):
        program = self._program()
        bound = []
        program.bind_pbr_textures = lambda material, mode: bound.append(
            dict(material.textures))
        material = Material()
        first, second = _red(), _red()
        program.configure_appearance(
            Appearance(material=material, texture=first), None)
        program.configure_appearance(
            Appearance(material=material, texture=second), None)
        assert bound == [{'baseColor': first}, {'baseColor': second}]


class TestAnEditedMaterialsBlock:
    """An edit repacks the block into the buffer the material already has."""

    @staticmethod
    def _contents(buffer, nbytes):
        from OpenGL import GL
        GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, buffer)
        try:
            data = GL.glGetBufferSubData(GL.GL_UNIFORM_BUFFER, 0, nbytes)
        finally:
            GL.glBindBuffer(GL.GL_UNIFORM_BUFFER, 0)
        return np.frombuffer(bytes(data), dtype=np.float32)

    @pytest.mark.parametrize('kind', ['vrml97', 'pbr'])
    def test_the_buffer_is_refilled_not_replaced(self, gl_context, kind):
        program = PBRShaderProgram()
        if kind == 'vrml97':
            appearance = Appearance(material=Material(diffuseColor=(1, 0, 0)))
            material = pbr_material(appearance)

            def edit(colour):
                appearance.material.diffuseColor = colour
        else:
            material = PBRMaterial(baseColor=(1, 0, 0))

            def edit(colour):
                material.baseColor = colour
        try:
            first = program._material_ubo(material)
            for colour in ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
                edit(colour)
                assert program._material_ubo(material) == first
                block = self._contents(first, pack_material_block(material).nbytes)
                assert np.allclose(block[0:3], colour)
        finally:
            program.release()


def _box(appearance):
    return Shape(geometry=Box(size=(3, 3, 3)), appearance=appearance)


def _patch(image, dx=0):
    """The mean colour of an 8-pixel square ``dx`` pixels right of the centre."""
    h, w = image.shape[:2]
    y, x = h // 2, w // 2 + dx
    return image[y - 4:y + 4, x - 4:x + 4].reshape(-1, 3).mean(axis=0)


def _drawn(appearance, renderer):
    with scene_context([_box(appearance)], renderer=renderer) as context:
        context.OnDraw(force=1)
        return drawn_image(context)


@pytest.fixture(scope='module')
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


WHITE = (1.0, 1.0, 1.0)


@pytest.fixture(scope='module')
def pbr_frames(core):
    """The centre of a box drawn by the PBR pass, untextured and textured."""
    appearances = {
        'plain': Appearance(material=Material(diffuseColor=WHITE)),
        'image': Appearance(material=Material(diffuseColor=WHITE),
                            texture=_red()),
        'pixels': Appearance(material=Material(diffuseColor=WHITE),
                             texture=PixelTexture(image=[1, 1, 3, 0x00FF00])),
    }
    return {name: _patch(_drawn(appearance, 'pbr'))
            for name, appearance in appearances.items()}


class TestDrawnByThePBRPass:
    def test_untextured_is_grey(self, pbr_frames):
        r, g, b = pbr_frames['plain']
        assert r > 40 and abs(r - g) < 10 and abs(r - b) < 10

    def test_an_image_texture_colours_the_surface(self, pbr_frames):
        r, g, b = pbr_frames['image']
        assert r > 40 and r > 4 * max(g, b, 1)

    def test_a_pixel_texture_colours_the_surface(self, pbr_frames):
        r, g, b = pbr_frames['pixels']
        assert g > 40 and g > 4 * max(r, b, 1)


def _halves(image):
    """Which channel is brightest a little left and a little right of the centre."""
    return tuple(int(np.argmax(_patch(image, dx))) for dx in (-10, 10))


RED, GREEN = 0, 1
#: Where a red|green texture's colours land, left and right, under each transform.
TRANSFORMED = {
    'none': ((0.0, 0.0), 0.0, (RED, GREEN)),
    'shifted half its width': ((0.5, 0.0), 0.0, (GREEN, RED)),
    'turned half a turn': ((0.0, 0.0), np.pi, (GREEN, RED)),
}


@pytest.mark.parametrize('renderer', ['vrml97', 'pbr'])
@pytest.mark.parametrize('name', list(TRANSFORMED))
def test_the_texture_transform_moves_the_texture(core, renderer, name):
    translation, rotation, expected = TRANSFORMED[name]
    texture = ImageTexture(image=Image.frombytes(
        'RGB', (2, 1), bytes((255, 0, 0, 0, 255, 0))))
    appearance = Appearance(
        material=Material(diffuseColor=WHITE), texture=texture,
        textureTransform=TextureTransform(translation=translation,
                                          rotation=rotation))
    assert _halves(_drawn(appearance, renderer)) == expected


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestAVrml97MaterialsColoursAreDecoded:
    """VRML97 states colours in the display's encoding."""

    @pytest.mark.parametrize('encoded, linear', [
        (0.0, 0.0), (1.0, 1.0), (0.5, 0.21404114), (0.04, 0.04 / 12.92),
    ])
    def test_colours_are_decoded_from_the_display_encoding(self, encoded, linear):
        assert srgb_to_linear((encoded,) * 3) == pytest.approx((linear,) * 3, rel=1e-5)

    def test_out_of_range_colours_are_clamped(self):
        assert srgb_to_linear((-1.0, 2.0, 0.0)) == (0.0, 1.0, 0.0)

    def test_the_emissive_colour_is_decoded_too(self):
        appearance = Appearance(material=Material(emissiveColor=(0.5, 0.5, 0.5)))
        block = pack_material_block(pbr_material(appearance))
        assert np.allclose(block[4:7], srgb_to_linear((0.5,) * 3))
