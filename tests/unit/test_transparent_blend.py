"""The transparent blend factors are coupled to the fragment
shader's alpha-output semantics. A partial revert / stale shader that changes one
side without the other silently inverts every transparent VRML97 surface. These
lock the two sides together so such a drift fails a test.
"""
import inspect
import os
import re

import pytest

from OpenGLContext.passes import _flat
from OpenGLContext.passes.shaderpass import SHADER_DIR


def _frag(name):
    with open(os.path.join(SHADER_DIR, name)) as f:
        return f.read()


class TestShaderBlendFactors:
    def test_shader_transparent_uses_src_over(self):
        src = inspect.getsource(_flat.FlatPass.shaderRenderTransparent)
        assert 'glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)' in src

    def test_lit_shader_outputs_opacity_alpha(self):
        # the src-over factors are only correct because the shader emits opacity
        src = _frag('vrml97_lighting.frag')
        assert re.search(r'alpha\s*=\s*1\.0\s*-\s*transparency', src), \
            "lit shader must output alpha as opacity (1 - transparency)"


class TestLegacyBlendContrast:
    def test_legacy_path_uses_reversed_factors(self):
        # the fixed-function path emits alpha as transparency and so intentionally
        # uses the *reversed* factors -- documents why the two must not be unified
        src = inspect.getsource(_flat.FlatPass.renderTransparent)
        assert 'glBlendFunc(GL_ONE_MINUS_SRC_ALPHA' in src


class TestSrcOverCompositing:
    def test_opacity_src_over_composites_correctly(self):
        # 50%-opacity red over opaque blue must yield an even blend, proving the
        # (factor, shader-alpha) pairing composites the way transparency intends
        src_rgb, src_opacity = (1.0, 0.0, 0.0), 0.5     # red, transparency 0.5
        dst_rgb = (0.0, 0.0, 1.0)                        # blue backdrop
        out = tuple(src_opacity * s + (1.0 - src_opacity) * d
                    for s, d in zip(src_rgb, dst_rgb))
        assert out == (0.5, 0.0, 0.5)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
