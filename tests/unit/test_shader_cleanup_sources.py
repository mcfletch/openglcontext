"""Structural checks for the shader-cleanup batch.

These pin the source-level changes; a companion GL test confirms the shaders
still preprocess, compile and render.
"""
import importlib
import os

import pytest

from OpenGLContext.passes import shaderpass

SHADER_DIR = os.path.dirname(shaderpass.__file__).replace('passes', 'shaders')


def _read(name):
    with open(os.path.join(SHADER_DIR, name)) as f:
        return f.read()


class TestSharedObjectId:
    """2b: the RGBA8 id-encode lives in one include, not inlined per shader."""

    def test_objectid_include_exists(self):
        assert os.path.exists(os.path.join(SHADER_DIR, '_objectid_inc.glsl'))

    @pytest.mark.parametrize('shader', [
        'vrml97_unlit.frag', 'vrml97_point.frag',
        'vrml97_line.frag', 'vrml97_vertex_color.frag'])
    def test_shader_uses_helper_not_inline(self, shader):
        src = _read(shader)
        assert 'encodeObjectId(objectId)' in src, '%s should call the shared helper' % shader
        assert '>> 24u) & 0xFFu' not in src, '%s still inlines the bit-unpack' % shader

    def test_lights_inc_pulls_the_shared_helper(self):
        assert '#include "_objectid_inc.glsl"' in _read('_lights_inc.glsl')


class TestVertexColorFold:
    """2a (fold): vertex_color no longer re-declares the shared light block."""

    def test_includes_lights_inc(self):
        assert '#include "_lights_inc.glsl"' in _read('vrml97_vertex_color.frag')

    def test_light_block_not_duplicated(self):
        src = _read('vrml97_vertex_color.frag')
        # the light-uniform array declarations now come from the include
        assert 'uniform int lightType[MAX_LIGHTS];' not in src


class TestNormalMatrix:
    """2e: instancing branch uses the cheap affine 3x3 inverse-transpose."""

    @pytest.mark.parametrize('vert', ['pbr.vert', 'vrml97_lighting.vert'])
    def test_uses_mat3_inverse(self, vert):
        src = _read(vert)
        assert 'mat3(transpose(inverse(mv)))' not in src
        assert 'transpose(inverse(mat3(mv)))' in src


class TestStd140Comments:
    """2c: the stale '192 bytes / 48 words' comments are corrected to 224/56."""

    def test_pbr_frag_comment(self):
        assert '192 bytes' not in _read('pbr.frag')

    def test_pbrpass_comments(self):
        with open(os.path.join(os.path.dirname(shaderpass.__file__), 'pbrpass.py')) as f:
            src = f.read()
        assert '48 words / 192 bytes' not in src
        assert '85 * 192' not in src


class TestGeneratorDeleted:
    """2d: the dead/broken ShaderGenerator module is gone."""

    def test_module_not_importable(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module('OpenGLContext.shaders.generator')
