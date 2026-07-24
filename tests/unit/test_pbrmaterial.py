"""Unit tests for the PBRMaterial node and VRML97->PBR up-conversion (no GL)."""
import math

import pytest

from OpenGLContext.scenegraph.pbrmaterial import (
    PBRMaterial, PBRTexture, material_is_transparent, material_to_pbr,
    uv_transform_matrix,
)


class TestPBRMaterialDefaults:
    def test_glTF_aligned_defaults(self):
        m = PBRMaterial()
        assert tuple(m.baseColor) == (1.0, 1.0, 1.0)
        assert m.metallic == 1.0
        assert m.roughness == 1.0
        assert tuple(m.emissiveColor) == (0.0, 0.0, 0.0)
        assert m.alphaMode == 'OPAQUE'
        assert m.alphaCutoff == 0.5
        assert bool(m.doubleSided) is False
        assert m.textures == {}

    def test_fields_and_textures_set(self):
        t = PBRTexture(image=None, srgb=True)
        m = PBRMaterial(baseColor=(0.1, 0.2, 0.3), metallic=0.5, roughness=0.4,
                        textures={'baseColor': t})
        assert tuple(round(float(x), 2) for x in m.baseColor) == (0.1, 0.2, 0.3)
        assert m.metallic == 0.5 and m.roughness == 0.4
        assert m.texture('baseColor') is t
        assert m.texture('normal') is None

    def test_fits_in_appearance_slot(self):
        from OpenGLContext.scenegraph.basenodes import Appearance
        m = PBRMaterial()
        a = Appearance(material=m)
        assert a.material is m


class TestUpConversion:
    def test_none_material_defaults(self):
        f = material_to_pbr(None)
        assert f['metallic'] == 0.0
        assert 0.0 < f['roughness'] <= 1.0

    def test_shininess_maps_to_roughness(self):
        from OpenGLContext.scenegraph.basenodes import Material
        shiny = material_to_pbr(Material(diffuseColor=(1, 0, 0), shininess=0.9))
        dull = material_to_pbr(Material(diffuseColor=(1, 0, 0), shininess=0.1))
        # higher shininess -> lower roughness
        assert shiny['roughness'] < dull['roughness']
        assert tuple(round(float(x), 2) for x in shiny['base_color']) == (1.0, 0.0, 0.0)
        assert shiny['metallic'] == 0.0

    def test_roughness_clamped(self):
        from OpenGLContext.scenegraph.basenodes import Material
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
        assert tuple(f['base_color']) == (0.8, 0.8, 0.8)
        assert 0.0 < f['roughness'] <= 1.0


class TestTransparency:
    def test_none_material_is_opaque(self):
        assert material_is_transparent(None) is False

    def test_explicit_blend_is_transparent(self):
        assert material_is_transparent(PBRMaterial(alphaMode='BLEND')) is True

    def test_explicit_opaque_and_mask_stay_opaque(self):
        assert material_is_transparent(PBRMaterial(alphaMode='OPAQUE')) is False
        assert material_is_transparent(PBRMaterial(alphaMode='MASK')) is False

    def test_legacy_transparency_without_alpha_mode(self):
        class Legacy:
            transparency = 0.4
        assert material_is_transparent(Legacy()) is True

        class Opaque:
            transparency = 0.0
        assert material_is_transparent(Opaque()) is False


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


glfw = pytest.importorskip("glfw")
from PIL import Image  # noqa: E402
from OpenGL.GL import (  # noqa: E402
    GL_CLAMP_TO_EDGE, GL_LINEAR, GL_NEAREST, GL_REPEAT, GL_TEXTURE_2D,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_WRAP_S, glBindTexture, glGetError,
    glGetTexParameteriv, GL_NO_ERROR,
)
import types  # noqa: E402


@pytest.fixture
def gl():
    if not glfw.init():
        pytest.skip("glfw init failed (no GL)")
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    win = glfw.create_window(32, 32, "pbrtex", None, None)
    if not win:
        glfw.terminate()
        pytest.skip("no GL context available")
    glfw.make_context_current(win)
    try:
        yield win
    finally:
        glfw.destroy_window(win)
        glfw.terminate()


class TestPBRTextureGL:
    def test_cached_builds_once_and_applies_sampler(self, gl):
        img = Image.new("RGBA", (4, 4), (200, 100, 50, 255))
        tex = PBRTexture(img, srgb=True, wrap_s=GL_REPEAT, wrap_t=GL_CLAMP_TO_EDGE,
                         min_filter=GL_LINEAR, mag_filter=GL_NEAREST)
        mode = types.SimpleNamespace(context=object())

        built = tex.cached(mode)
        assert built is not None
        assert glGetError() == GL_NO_ERROR

        # The wrap/mag sampler state reached the GL texture object.
        glBindTexture(GL_TEXTURE_2D, built.texture)
        wrap = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S))
        mag = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER))
        assert wrap == GL_REPEAT
        assert mag == GL_NEAREST

        # A second lookup with the same context returns the cached object.
        assert tex.cached(mode) is built

    def test_cached_defaults_without_sampler_overrides(self, gl):
        img = Image.new("RGBA", (2, 2), (10, 20, 30, 255))
        tex = PBRTexture(img)                      # no wrap/filter overrides
        mode = types.SimpleNamespace(context=object())
        built = tex.cached(mode)
        assert built is not None
        glBindTexture(GL_TEXTURE_2D, built.texture)
        mag = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER))
        assert mag == GL_LINEAR                    # default mag filter
        assert glGetError() == GL_NO_ERROR

    def test_mipmap_failure_falls_back_to_linear_min_filter(self, gl, monkeypatch):
        # A driver that cannot generate mipmaps -> _apply_sampler must degrade the
        # min filter to plain GL_LINEAR rather than a mipmap filter (else sampling
        # an incomplete mip chain renders black).
        import OpenGL.GL as GLmod
        from OpenGL.GL import GL_TEXTURE_MIN_FILTER

        def _boom(_target):
            raise RuntimeError("no mipmaps on this driver")

        monkeypatch.setattr(GLmod, 'glGenerateMipmap', _boom)
        img = Image.new("RGBA", (4, 4), (1, 2, 3, 255))
        tex = PBRTexture(img)
        mode = types.SimpleNamespace(context=object())
        built = tex.cached(mode)
        glBindTexture(GL_TEXTURE_2D, built.texture)
        min_f = int(glGetTexParameteriv(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER))
        assert min_f == GL_LINEAR


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
