"""The PBR pass's baked-lightmap channel.

A lightmap is pre-integrated static irradiance (the Quake/Source workflow): the
map compiler solves the static lights offline and stores the result in a texture
addressed by a second UV set. The PBR program treats it as an *additional*
ambient irradiance source, so a lightmapped surface still gets normal mapping,
IBL reflection and dynamic lights on top.

These are the static contracts -- unit assignment, sampler/flag naming and the
shader's use of the sampled value -- that hold with no GL context.
"""
import os
import re

import pytest

from OpenGLContext.passes.pbrpass import PBR_UNITS, _PBR_HAS, _PBR_SAMPLER
from OpenGLContext.passes.shaderpass import SHADER_DIR
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

# texCoordMask bit selecting TEXCOORD_1 for the lightmap channel.
LIGHTMAP_UV_BIT = 32


def _frag():
    with open(os.path.join(SHADER_DIR, 'pbr.frag')) as f:
        return f.read()


class TestChannelRegistration:
    def test_lightmap_is_a_pbr_texture_channel(self):
        assert 'lightmap' in PBR_UNITS
        assert _PBR_SAMPLER['lightmap'] == 'lightmapTexture'
        assert _PBR_HAS['lightmap'] == 'hasLightmap'

    def test_lightmap_unit_is_within_the_baseline_budget(self):
        # GL 3.3 guarantees only 16 fragment texture units; every other index is
        # already spoken for (material maps, shadows, transmission, IBL), so the
        # lightmap takes unit 0 -- see the unit map in pbrpass.
        assert PBR_UNITS['lightmap'] == 0

    def test_material_carries_a_lightmap_strength(self):
        assert float(PBRMaterial().lightmapStrength) == 1.0
        assert float(PBRMaterial(lightmapStrength=2.0).lightmapStrength) == 2.0


class TestShaderSource:
    def test_declares_the_sampler_and_presence_flag(self):
        src = _frag()
        assert 'uniform sampler2D lightmapTexture' in src
        assert 'hasLightmap' in src
        assert 'uniform float lightmapStrength' in src

    def test_samples_on_the_lightmap_uv_set(self):
        # uvFor(32) routes through texCoordMask so a material can put the
        # lightmap on either UV set; BSP geometry uses TEXCOORD_1.
        assert re.search(r'texture\s*\(\s*lightmapTexture\s*,\s*uvFor\(%d\)\s*\)'
                         % LIGHTMAP_UV_BIT, _frag())

    def test_reads_the_lightmap_as_linear_light(self):
        # A lightmap is a radiosity solution written straight to 8 bits, not an
        # sRGB colour texture. Running it through the sRGB decode would crush
        # the midtones and leave a baked level looking unlit.
        assert not re.search(r'toLinear\s*\(\s*texture\s*\(\s*lightmapTexture',
                             _frag())
        assert re.search(r'texture\s*\(\s*lightmapTexture[^;]*\*\s*lightmapStrength',
                         _frag())

    def test_feeds_the_ambient_diffuse_term(self):
        # It is irradiance, so it multiplies albedo and is *added* to the ambient
        # diffuse -- not multiplied into it like an occlusion map.
        assert re.search(r'ambDiffuse\s*\+=\s*lightmap\s*\*\s*albedo', _frag())

    def test_feeds_the_ambient_specular_term(self):
        # Without this a glossy lightmapped surface reads flat: the baked light
        # would light the diffuse lobe but never reflect.
        assert re.search(r'ambSpecular\s*\+=\s*lightmap', _frag())

    def test_applies_before_diffuse_transmission_splits_the_ambient(self):
        src = _frag()
        add = src.index('ambDiffuse += lightmap')
        split = src.index('ambDiffuse *= (1.0 - diffuseTransFactorEff)')
        assert add < split, \
            "the lightmap must be in ambDiffuse before diffuse transmission " \
            "takes its share of it"


# --- rendered-frame checks ---------------------------------------------------
# The capture scene draws two identical grey quads under a near-dark light with
# IBL off, so the only real illumination is the baked ramp on the left quad's
# TEXCOORD_1. Every brightness difference between them is the lightmap.

@pytest.fixture(scope="module")
def lightmap_image(tmp_path_factory):
    rendering = pytest.importorskip("tests.unit.test_pbr_rendering")
    np = pytest.importorskip("numpy")
    image_mod = pytest.importorskip("PIL.Image")
    out = str(tmp_path_factory.mktemp("lm") / "lightmap.png")
    if not rendering._capture(out, mode="lightmap", env={'OPENGLCONTEXT_IBL': 'off'}):
        pytest.skip("OpenGL context unavailable for lightmap render test")
    return np.asarray(image_mod.open(out).convert("RGB")).astype(int)


def _quad_profile(image):
    """Per-column mean brightness of each quad, as (lightmapped, plain) arrays.

    The quads are located by scanning for runs of lit columns and averaged over
    only their own lit pixels, so nothing here depends on the capture's window
    size, aspect or framing.
    """
    import numpy as np
    lit = image.mean(2) > 8
    on = lit.any(0)
    runs, start = [], None
    for i, col in enumerate(on):
        if col and start is None:
            start = i
        elif not col and start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, len(on)))
    runs = [r for r in runs if r[1] - r[0] > 8]
    assert len(runs) == 2, "expected two quads, found lit column runs %r" % (runs,)
    return [np.array([image[lit[:, c], c].mean() for c in range(a, b)])
            for a, b in runs]


def test_baked_ramp_is_visible(lightmap_image):
    baked, _plain = _quad_profile(lightmap_image)
    third = max(1, len(baked) // 3)
    assert baked[-third:].mean() > baked[:third].mean() + 20, \
        "the lightmap's black->white ramp must brighten the quad left to right"


def test_lightmap_lights_a_surface_no_light_reaches(lightmap_image):
    baked, plain = _quad_profile(lightmap_image)
    quarter = max(1, len(baked) // 4)
    assert baked[-quarter:].mean() > plain.mean() + 20, \
        "the lightmapped quad must out-brighten the identical plain one"


def test_unlit_end_of_the_ramp_matches_the_plain_quad(lightmap_image):
    # Where the lightmap is black it must add nothing: the channel is additive
    # irradiance, not a brightness offset applied to the whole surface.
    # The outermost column straddles the quad's silhouette edge and is part
    # background, so the comparison starts one column in.
    baked, plain = _quad_profile(lightmap_image)
    assert abs(baked[1:4].mean() - plain.mean()) < 12


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
