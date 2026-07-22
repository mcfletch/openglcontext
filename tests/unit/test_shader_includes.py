"""Tests for the shared-GLSL #include mechanism and the shaders it assembles.

Two layers:
  * pure-Python: the preprocessor (include splicing, the include-once guard,
    define injection) and the material/shadow define helpers -- run everywhere.
  * GL: every reviewed shader permutation actually compiles/links in a real GL
    context (subprocess helper; skips when no context is available).
"""
import os
import re
import subprocess
import sys

import pytest

from OpenGLContext.passes import shaderpass as SP
from OpenGLContext.passes.pbrpass import pbr_feature_defines, PBR_OPTIONAL_FEATURES

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))
COMPILE_CHECK = os.path.join(TESTS_DIR, "helpers", "_shader_compile_check.py")


def _read_raw(name):
    with open(os.path.join(SP.SHADER_DIR, name)) as fh:
        return fh.read()


# --------------------------------------------------------------- preprocessor --
class TestIncludeResolver:
    def test_no_include_shader_round_trips(self):
        """A shader with no #include comes back byte-for-byte."""
        raw = open(os.path.join(SP.SHADER_DIR, "shadow_depth.frag")).read()
        assert SP.preprocess_shader("shadow_depth.frag") == raw

    def test_include_is_spliced(self):
        src = SP.preprocess_shader("pbr.frag")
        # bodies from three different includes must all be present
        assert "vec3 sRGBToLinear(" in src        # _common_inc.glsl
        assert "float V_SmithGGXCorrelated(" in src  # _brdf_inc.glsl
        assert "vec4 encodeObjectId(" in src       # _lights_inc.glsl
        assert 'void resolveShadows' in src        # _shadow_inc.glsl
        # every include directive was resolved (prose like "#included" is fine)
        assert not re.search(r'^\s*#include\b', src, re.M)

    def test_nested_include_resolved_once(self):
        """_brdf_inc includes _common_inc; pbr.frag includes both. The shared
        helper must appear exactly once (include-once guard), or GLSL errors on
        the redefinition."""
        src = SP.preprocess_shader("pbr.frag")
        assert src.count("vec3 sRGBToLinear(vec3 c)") == 1
        assert src.count("const float PI") == 1

    def test_missing_include_raises(self, tmp_path):
        bad = tmp_path / "bad.frag"
        bad.write_text('#version 330 core\n#include "_does_not_exist.glsl"\n')
        # resolver reads relative to SHADER_DIR, so point it there via a temp name
        target = os.path.join(SP.SHADER_DIR, "_tmp_bad_include_test.frag")
        try:
            with open(target, "w") as fh:
                fh.write('#version 330 core\n#include "_nope_inc.glsl"\n')
            with pytest.raises((IOError, OSError)):
                SP.preprocess_shader("_tmp_bad_include_test.frag")
        finally:
            if os.path.exists(target):
                os.remove(target)

    def test_defines_injected_after_version(self):
        src = SP.preprocess_shader("pbr.frag", ["#define FOO 1", "#define BAR 2"])
        lines = src.split("\n")
        vi = next(i for i, l in enumerate(lines) if l.lstrip().startswith("#version"))
        assert lines[vi + 1] == "#define FOO 1"
        assert lines[vi + 2] == "#define BAR 2"

    def test_extension_line_precedes_shader_body(self):
        """#extension is only legal right after #version -- verify ordering."""
        src = SP.load_fragment_source("pbr.frag", 4, cube_array=True)
        ext = src.index("#extension GL_ARB_texture_cube_map_array")
        body = src.index("void main")
        assert ext < body
        # and it sits within a couple of lines of #version
        head = src[:src.index("#extension")]
        assert head.count("\n") <= 3


# ----------------------------------------------------------------- define helpers
class TestShadowDefines:
    def test_cube_array_emits_extension_and_define(self):
        d = SP.shadow_defines(4, cube_array=True)
        assert "#define MAX_SHADOW_LIGHTS 4" in d
        assert "#define SHADOW_CUBE_ARRAY 1" in d
        assert any("GL_ARB_texture_cube_map_array" in x for x in d)

    def test_fallback_omits_cube_array(self):
        d = SP.shadow_defines(2, cube_array=False)
        assert "#define MAX_SHADOW_LIGHTS 2" in d
        assert not any("SHADOW_CUBE_ARRAY" in x for x in d)
        assert not any("extension" in x for x in d)


class TestPBRFeatureDefines:
    def _map(self, enabled):
        return dict(x.replace("#define ", "").split()
                    for x in pbr_feature_defines(enabled))

    def test_default_keeps_every_lobe_on(self):
        """None => the shipped program: every optional lobe ON."""
        d = self._map(None)
        for f in PBR_OPTIONAL_FEATURES:
            assert d["USE_%s" % f] == "1"

    def test_constrained_profile_drops_selected_lobes(self):
        """A per-platform choice keeps only the named lobes; the rest compile out."""
        d = self._map(["SHEEN"])
        assert d["USE_SHEEN"] == "1"
        assert d["USE_CLEARCOAT"] == "0"
        assert d["USE_TRANSMISSION"] == "0"

    def test_empty_drops_all_optional_lobes(self):
        d = self._map([])
        assert all(d["USE_%s" % f] == "0" for f in PBR_OPTIONAL_FEATURES)

    def test_covers_exactly_the_shader_guards(self):
        """The helper emits one USE_* per optional guard in pbr.frag, no more."""
        src = SP.preprocess_shader("pbr.frag")
        for f in PBR_OPTIONAL_FEATURES:
            assert ("USE_%s" % f) in src
        assert len(pbr_feature_defines(None)) == len(PBR_OPTIONAL_FEATURES)


# ----------------------------------------------------------- assembled-source locks
class TestAssembledSource:
    def test_direct_lighting_uses_height_correlated_visibility(self):
        """Direct spec is D * Vis * F (no separable Schlick G that was
        fed alpha where it expected perceptual roughness)."""
        src = SP.preprocess_shader("pbr.frag")
        assert "V_SmithGGXCorrelated(NdotV, NdotL, alphaR)" in src
        assert "G_SchlickSmith" not in src

    def test_tripwire_guard_present_when_over_budget(self):
        src = SP.preprocess_shader("pbr.frag", ["#define MAX_SHADOW_LIGHTS 5"])
        # the #error lives inside a `#if MAX_SHADOW_LIGHTS > 4` block
        assert re.search(r"#if\s+MAX_SHADOW_LIGHTS\s*>\s*4", src)
        assert "#error" in src

    def test_ibl_and_direct_share_one_brdf_definition(self):
        """The BRDF machinery is defined once, in the include, not
        copy-pasted into pbr.frag and the IBL frags."""
        for name in ("pbr.frag", "ibl_prefilter.frag", "ibl_brdf.frag"):
            src = SP.preprocess_shader(name)
            assert src.count("vec3 importanceSampleGGX(") <= 1
            assert not re.search(r'^\s*#include\b', src, re.M)

    def test_ibl_brdf_lut_samples_the_same_alpha_lobe_as_prefilter(self):
        """The split-sum halves must integrate the same GGX lobe. The
        shared importanceSampleGGX consumes alpha (= roughness*roughness); both
        the LUT and the prefilter must feed it alpha, not perceptual roughness,
        or the LUT and the probe disagree."""
        brdf = _read_raw("ibl_brdf.frag")
        pre = _read_raw("ibl_prefilter.frag")
        assert "roughness * roughness" in brdf
        assert re.search(r"importanceSampleGGX\(Xi, N, alpha\)", brdf)
        assert re.search(r"importanceSampleGGX\(Xi, N, a\)", pre)  # a = roughness*roughness


# --------------------------------------------------------------------------- GL
def test_all_shader_permutations_compile_and_link():
    """Every lit/IBL/depth program links in a real GL context, and the shadow-slot
    tripwire rejects an over-budget build. Skips when no GL context is available."""
    proc = subprocess.run([sys.executable, COMPILE_CHECK],
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=180)
    out = proc.stdout.decode("utf-8", "replace")
    if proc.returncode == 77:
        pytest.skip("no GL context for shader compile check:\n" + out)
    assert proc.returncode == 0, "shader compile/link failed:\n" + out


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
