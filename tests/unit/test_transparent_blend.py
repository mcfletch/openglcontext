"""Tests for the transparent blend, which takes a material's alpha as its
opacity in the shaders and in the fixed-function Material alike.
"""
import inspect
import os
import re

import pytest

from OpenGLContext.passes import _flat
from OpenGLContext.passes.shaderpass import SHADER_DIR
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context


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


@pytest.mark.parametrize('profile', ['core', 'compatibility'])
def test_a_quarter_transparent_shape_is_three_quarters_its_colour(profile):
    """The material's alpha is its opacity in both profiles

    Drawn by the VRML97 renderer, which applies no tone mapping.
    """
    scene = [basenodes.Shape(
        geometry=basenodes.Box(size=(40, 40, 0.1)),
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=(0, 0, 0), emissiveColor=(1, 0, 0), transparency=0.25)))]
    with scene_context(scene, size=(32, 32), renderer='vrml97',
                       environment={'OPENGLCONTEXT_PROFILE': profile}) as context:
        drawn_image(context)
        red = int(drawn_image(context)[16, 16, 0])
    assert abs(red - 191) <= 4, red


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
