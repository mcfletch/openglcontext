"""Transparency routing: Appearance.sortKey decides opaque vs transparent pass.

The appearance's alphaMode decides: only BLEND is routed to the back-to-front
blended pass; OPAQUE and MASK render in the opaque pass whatever the alpha.
AUTO, the default, follows the material's transparency field.
"""
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.scenegraph.material import Material
from OpenGLContext import renderoptions
from OpenGLContext.passes.transmission import resolve_mode


def _transparent(material, mode='AUTO'):
    """First element of the sort key is the transparent flag."""
    return Appearance(material=material, alphaMode=mode).sortKey(mode=None, matrix=None)[0]


def test_pbr_blend_routes_to_transparent():
    assert _transparent(PhysicalMaterial(), 'BLEND') is True


def test_pbr_blend_transparent_even_with_opaque_basecolor_alpha():
    # BLEND with baseColor alpha 1.0 (alpha lives in a texture) still blends.
    assert _transparent(PhysicalMaterial(transparency=0.0), 'BLEND') is True


def test_pbr_opaque_stays_opaque_despite_basecolor_alpha():
    # glTF OPAQUE ignores any alpha; must not leak into the transparent pass.
    assert _transparent(PhysicalMaterial(transparency=0.5), 'OPAQUE') is False


def test_pbr_mask_is_opaque():
    # MASK is opaque geometry with a shader-side discard, not a blended surface.
    assert _transparent(PhysicalMaterial(transparency=0.5), 'MASK') is False


def test_pbr_default_is_opaque():
    assert _transparent(PhysicalMaterial()) is False


def test_legacy_material_uses_transparency_field():
    # AUTO follows the VRML97 transparency field.
    assert _transparent(Material(transparency=0.4)) is True
    assert _transparent(Material(transparency=0.0)) is False


def test_no_material_is_opaque():
    assert Appearance().sortKey(mode=None, matrix=None)[0] is False


def test_transmissive_material_stays_in_opaque_pass():
    # A transmissive material in OPAQUE mode must NOT route to the
    # blended pass -- it draws after opaque, sampling the backdrop.
    m = PhysicalMaterial(transmission=1.0)
    assert _transparent(m, 'OPAQUE') is False


def test_transmission_resolve_mode(monkeypatch):
    monkeypatch.delenv('OPENGLCONTEXT_TRANSMISSION', raising=False)
    # auto: software rasteriser -> blend, real GPU -> full
    assert resolve_mode('llvmpipe (LLVM 15)') == 'blend'
    assert resolve_mode('NVIDIA GeForce RTX 4090') == 'full'
    for val, expect in [('off', 'off'), ('blend', 'blend'), ('full', 'full'),
                        ('none', 'off'), ('fake', 'blend'), ('on', 'full')]:
        monkeypatch.setenv('OPENGLCONTEXT_TRANSMISSION', val)
        renderoptions.reset_env_cache()      # the variable is read once
        assert resolve_mode('llvmpipe') == expect


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
