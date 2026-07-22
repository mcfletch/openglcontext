"""Transparency routing: Appearance.sortKey decides opaque vs transparent pass.

glTF/PBR materials carry an explicit alphaMode that is authoritative -- only
BLEND is routed to the (back-to-front, blended) transparent pass; OPAQUE and MASK
render in the opaque pass regardless of any baseColor/texture alpha. Legacy
VRML97 materials (no alphaMode) fall back to the transparency field.
"""
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.material import Material


def _transparent(material):
    """First element of the sort key is the transparent flag."""
    return Appearance(material=material).sortKey(mode=None, matrix=None)[0]


def test_pbr_blend_routes_to_transparent():
    assert _transparent(PBRMaterial(alphaMode='BLEND')) is True


def test_pbr_blend_transparent_even_with_opaque_basecolor_alpha():
    # BLEND with baseColor alpha 1.0 (alpha lives in a texture) still blends.
    assert _transparent(PBRMaterial(alphaMode='BLEND', transparency=0.0)) is True


def test_pbr_opaque_stays_opaque_despite_basecolor_alpha():
    # glTF OPAQUE ignores any alpha; must not leak into the transparent pass.
    assert _transparent(PBRMaterial(alphaMode='OPAQUE', transparency=0.5)) is False


def test_pbr_mask_is_opaque():
    # MASK is opaque geometry with a shader-side discard, not a blended surface.
    assert _transparent(PBRMaterial(alphaMode='MASK', transparency=0.5)) is False


def test_pbr_default_is_opaque():
    assert _transparent(PBRMaterial()) is False


def test_legacy_material_uses_transparency_field():
    # No alphaMode attribute -> fall back to the VRML97 transparency field.
    assert _transparent(Material(transparency=0.4)) is True
    assert _transparent(Material(transparency=0.0)) is False


def test_no_material_is_opaque():
    assert Appearance().sortKey(mode=None, matrix=None)[0] is False


def test_transmissive_material_stays_in_opaque_pass():
    # KHR_materials_transmission is alphaMode=OPAQUE: it must NOT route to the
    # blended pass -- it draws after opaque, sampling the backdrop.
    m = PBRMaterial(alphaMode='OPAQUE', transmission=1.0)
    assert _transparent(m) is False


def test_transmission_resolve_mode():
    import os
    from OpenGLContext.passes.transmission import resolve_mode
    saved = os.environ.pop('OPENGLCONTEXT_TRANSMISSION', None)
    try:
        # auto: software rasteriser -> blend, real GPU -> full
        assert resolve_mode('llvmpipe (LLVM 15)') == 'blend'
        assert resolve_mode('NVIDIA GeForce RTX 4090') == 'full'
        for val, expect in [('off', 'off'), ('blend', 'blend'), ('full', 'full'),
                            ('none', 'off'), ('fake', 'blend'), ('on', 'full')]:
            os.environ['OPENGLCONTEXT_TRANSMISSION'] = val
            assert resolve_mode('llvmpipe') == expect
    finally:
        os.environ.pop('OPENGLCONTEXT_TRANSMISSION', None)
        if saved is not None:
            os.environ['OPENGLCONTEXT_TRANSMISSION'] = saved


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
