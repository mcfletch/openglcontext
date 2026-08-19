"""Source-level locks for PBR shader fixes that also compile-validate headlessly
elsewhere: tangent transform (4.1) and analytic-IBL diffuse energy (4.4)."""
import os
import re
import pytest

from OpenGLContext.passes.shaderpass import SHADER_DIR, preprocess_shader


def _read(name):
    with open(os.path.join(SHADER_DIR, name)) as f:
        return f.read()


def _assembled(name):
    """Shader source with its #includes resolved -- what actually compiles."""
    return preprocess_shader(name)


class TestTangentTransform:
    def test_tangent_uses_modelview_not_normal_matrix(self):
        src = _read('pbr.vert')
        # The tangent must transform by the modelview upper-3x3, not normalMatrix.
        # ``mv`` is the modelview (the per-draw uniform, or the per-instance
        # attribute when instancing); either spelling is accepted. What is
        # transformed is the local ``tangent``, which is the attribute after any
        # skinning has moved it.
        m = re.search(r'mat3\((?:mv|modelViewMatrix)\)\s*\*\s*(?:aTangent|tangent)', src)
        assert m, "tangent must transform by mat3(modelview) (4.1)"
        assert re.search(r'tangent\s*=\s*aTangent\.xyz', src), \
            "the transformed tangent must start from the attribute"
        assert 'normalize(normalMatrix * aTangent' not in src
        # And ``mv`` really is the modelview, not some other matrix.
        assert re.search(r'mv\s*=\s*.*(?:aInstanceModelView|modelViewMatrix)', src)

    def test_tangent_normalize_is_zero_guarded(self):
        src = _read('pbr.vert')
        # no unguarded normalize() of the tangent (would be NaN with no attribute)
        assert 'normalize(normalMatrix * aTangent' not in src
        assert 'length(tEye)' in src or 'tLen' in src


class TestAnalyticIBLEnergy:
    def test_analytic_diffuse_divided_by_pi(self):
        src = _read('pbr.frag')
        # the analytic env diffuse must be irradiance (radiance / PI == radiance *
        # INV_PI), not raw radiance
        assert re.search(r'envColor\(Nw\)\s*(?:/\s*PI|\*\s*INV_PI)', src), \
            "analytic IBL diffuse must divide by PI (4.4)"


class TestSRGBPipeline:
    """5.1: the sRGB decode/encode uses the accurate piecewise curve, not the
    pow(c, 2.2) approximation that crushes near-black."""

    def test_piecewise_functions_defined(self):
        # sRGBToLinear / linearToSRGB now live in the shared _common_inc.glsl, so
        # check the assembled (include-resolved) source that actually compiles.
        src = _assembled('pbr.frag')
        assert 'vec3 sRGBToLinear(' in src and 'vec3 linearToSRGB(' in src
        # the piecewise breakpoints identify a real sRGB curve, not a bare power
        assert '0.04045' in src and '0.0031308' in src
        assert '12.92' in src and '1.055' in src

    def test_decode_routes_through_piecewise(self):
        src = _read('pbr.frag')
        assert 'toLinear(vec3 c) { return sRGBToLinear(c); }' in src

    def test_final_encode_is_piecewise_not_gamma_shortcut(self):
        src = _read('pbr.frag')
        # no leftover pow(..., 1.0/2.2) gamma-encode shortcut anywhere
        assert not re.search(r'pow\([^;]*1\.0\s*/\s*2\.2', src), \
            "final sRGB encode must use linearToSRGB, not pow(c, 1/2.2)"
        assert 'color = linearToSRGB(color);' in src


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
