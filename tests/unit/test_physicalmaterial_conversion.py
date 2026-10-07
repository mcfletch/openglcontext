"""PhysicalMaterial's fields, the VRML97 material conversion, and ImageDataTexture's GL texture."""
import math

import pytest

from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.sampler import texture_properties
from OpenGLContext.scenegraph.physicalmaterial import (
    PhysicalMaterial, material_to_pbr, srgb_to_linear,
    uv_transform_matrix,
)
from OpenGLContext.scenegraph.basenodes import Appearance, Material


class TestPhysicalMaterialDefaults:
    def test_glTF_aligned_defaults(self):
        m = PhysicalMaterial()
        assert tuple(m.baseColor) == (1.0, 1.0, 1.0)
        assert m.metallic == 1.0
        assert m.roughness == 1.0
        assert tuple(m.emissiveColor) == (0.0, 0.0, 0.0)
        assert m.textures == {}

    def test_fields_and_textures_set(self):
        t = ImageDataTexture(image=None)
        m = PhysicalMaterial(baseColor=(0.1, 0.2, 0.3), metallic=0.5, roughness=0.4,
                        baseTexture=t)
        assert tuple(round(float(x), 2) for x in m.baseColor) == (0.1, 0.2, 0.3)
        assert m.metallic == 0.5 and m.roughness == 0.4
        assert m.texture('baseColor') is t
        assert m.texture('normal') is None

    def test_fits_in_appearance_slot(self):
        m = PhysicalMaterial()
        a = Appearance(material=m)
        assert a.material is m


class TestUpConversion:
    def test_none_material_defaults(self):
        f = material_to_pbr(None)
        assert f['metallic'] == 0.0
        assert 0.0 < f['roughness'] <= 1.0

    def test_shininess_maps_to_roughness(self):
        shiny = material_to_pbr(Material(diffuseColor=(1, 0, 0), shininess=0.9))
        dull = material_to_pbr(Material(diffuseColor=(1, 0, 0), shininess=0.1))
        # higher shininess -> lower roughness
        assert shiny['roughness'] < dull['roughness']
        assert tuple(round(float(x), 2) for x in shiny['base_color']) == (1.0, 0.0, 0.0)
        assert shiny['metallic'] == 0.0

    def test_roughness_clamped(self):
        f = material_to_pbr(Material(shininess=1.0))
        assert f['roughness'] >= 0.04

    def test_null_node_material_defaults(self):
        """A Shape with no material (VRML's NullNode) must up-convert to the
        default grey material, not crash -- so VRML97 geometry with an empty
        appearance still renders under the PBR pass."""
        class NullNode:
            """Mimics vrml's null sentinel: truthy, but no material fields."""
        f = material_to_pbr(NullNode())
        assert f['metallic'] == 0.0
        assert tuple(f['base_color']) == srgb_to_linear((0.8, 0.8, 0.8))
        assert 0.0 < f['roughness'] <= 1.0


class TestUVTransform:
    def test_identity_transform(self):
        m = uv_transform_matrix()
        assert m == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    def test_offset_populates_translation_column(self):
        m = uv_transform_matrix(offset=(0.25, 0.75))
        assert m[0][2] == 0.25 and m[1][2] == 0.75

    def test_scale_populates_diagonal(self):
        m = uv_transform_matrix(scale=(2.0, 3.0))
        assert m[0][0] == pytest.approx(2.0)
        assert m[1][1] == pytest.approx(3.0)

    def test_rotation_is_negated_relative_to_spec(self):
        # module negates the angle so authored texcoords rotate the glTF way.
        m = uv_transform_matrix(rotation=math.pi / 2)
        # cos(-pi/2)=0, sin(-pi/2)=-1 -> [0,0][1,0] follow that sign convention.
        assert m[0][0] == pytest.approx(0.0, abs=1e-9)
        assert m[1][0] == pytest.approx(-1.0)


from PIL import Image
from OpenGL.error import GLError
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE, GL_INVALID_OPERATION, GL_LINEAR, GL_NEAREST, GL_NO_ERROR, GL_REPEAT,
    GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S, glBindTexture, glGetError,
    glGetTexParameteriv,
)
import OpenGL.GL as GLmod
import types

from vrml.cache import Cache
from OpenGLContext.texturecache import TextureCache


@pytest.fixture
def gl(gl_window):
    return gl_window('pbrtex', size=(32, 32), profile='any')


class _Mode:
    """A shader-mode render pass, as far as a texture's compile reads it."""

    shader_mode = True

    def __init__(self):
        self.cache = Cache()
        self.context = types.SimpleNamespace(textureCache=TextureCache())


class TestImageDataTextureGL:
    @pytest.mark.usefixtures('gl')
    def test_cached_builds_once_and_applies_sampler(self):
        img = Image.new("RGBA", (4, 4), (200, 100, 50, 255))
        tex = ImageDataTexture(image=img, textureProperties=texture_properties(
            'REPEAT', 'CLAMP_TO_EDGE', 'AVG_PIXEL', 'NEAREST_PIXEL'))
        mode = _Mode()

        built = tex.cached(mode)
        assert built is not None
        assert glGetError() == GL_NO_ERROR

        # The wrap/mag sampler state reached the GL texture object.
        glBindTexture(GL_TEXTURE_2D, built.texture)
        wrap = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S))
        mag = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER))
        assert wrap == GL_REPEAT
        assert mag == GL_NEAREST

        # A second lookup in the same mode returns the cached object.
        assert tex.cached(mode) is built

    @pytest.mark.usefixtures('gl')
    def test_a_new_image_is_compiled_again(self):
        tex = ImageDataTexture(image=Image.new("RGBA", (2, 2), (1, 2, 3, 255)))
        mode = _Mode()
        first = tex.cached(mode)
        tex.image = Image.new("RGBA", (4, 4), (4, 5, 6, 255))
        assert tex.cached(mode) is not first

    @pytest.mark.usefixtures('gl')
    def test_a_new_sampler_is_compiled_again(self):
        tex = ImageDataTexture(image=Image.new("RGBA", (2, 2), (1, 2, 3, 255)))
        mode = _Mode()
        first = tex.cached(mode)
        tex.textureProperties = texture_properties('CLAMP_TO_EDGE', 'CLAMP_TO_EDGE')
        built = tex.cached(mode)
        assert built is not first
        glBindTexture(GL_TEXTURE_2D, built.texture)
        assert int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S)) == GL_CLAMP_TO_EDGE

    @pytest.mark.usefixtures('gl')
    def test_cached_defaults_without_sampler_overrides(self):
        img = Image.new("RGBA", (2, 2), (10, 20, 30, 255))
        tex = ImageDataTexture(image=img)
        built = tex.cached(_Mode())
        assert built is not None
        glBindTexture(GL_TEXTURE_2D, built.texture)
        mag = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER))
        assert mag == GL_LINEAR                    # default mag filter
        assert glGetError() == GL_NO_ERROR

    @pytest.mark.usefixtures('gl')
    def test_mipmap_failure_falls_back_to_linear_min_filter(self, monkeypatch):
        # A driver that cannot generate mipmaps: the min filter is plain
        # GL_LINEAR rather than a mipmap filter, which would sample an
        # incomplete mip chain as black.

        def _boom(_target):
            raise GLError(GL_INVALID_OPERATION, None)

        monkeypatch.setattr(GLmod, 'glGenerateMipmap', _boom)
        img = Image.new("RGBA", (4, 4), (1, 2, 3, 255))
        built = ImageDataTexture(image=img).cached(_Mode())
        glBindTexture(GL_TEXTURE_2D, built.texture)
        min_f = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER))
        assert min_f == GL_LINEAR


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
