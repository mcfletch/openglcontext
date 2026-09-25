"""Which of a material's maps a draw samples: one bitmask uniform.

The PBR shader reads each material map only where the material has it and
the image has loaded. That is one ``int`` uniform, ``materialTextures``, a bit
per map, set once a draw, rather than a ``bool`` uniform per map.

The pass side runs with a stand-in program handle and records what would have
reached GL.
"""
import os
import re
import types

import pytest

from OpenGLContext.passes import pbrpass
from OpenGLContext.passes.shaderpass import SHADER_DIR


def _source():
    with open(os.path.join(SHADER_DIR, 'pbr.frag')) as handle:
        return handle.read()


class _Holder:
    def __init__(self, texture):
        self.texture = texture

    def cached(self, mode):
        return None if self.texture is None else types.SimpleNamespace(texture=self.texture)


class _Material:
    def __init__(self, **textures):
        self.textures = {name: _Holder(tid) for name, tid in textures.items()}


@pytest.fixture
def program(monkeypatch):
    p = pbrpass.PBRShaderProgram()
    p.program = 7
    p.ext_channels = {'clearcoat': pbrpass.PBR_EXT_UNITS['clearcoat']}
    bound = []
    uniforms = []
    monkeypatch.setattr(pbrpass, 'glActiveTexture', lambda unit: None)
    monkeypatch.setattr(pbrpass, 'glBindTexture', lambda target, tid: bound.append(tid))
    monkeypatch.setattr(p, '_set_uniform1i',
                        lambda name, value, program=None: uniforms.append((name, value)))
    p.bound, p.uniforms = bound, uniforms
    return p


class TestTheShader:
    def test_the_maps_are_one_mask(self):
        source = _source()
        assert 'uniform int materialTextures;' in source
        assert not re.search(r'uniform bool has(BaseColor|MetallicRoughness|Normal|'
                             r'Occlusion|Emissive|Lightmap)\b', source)
        assert not re.search(r'uniform bool has\w+Map\b', source)

    def test_each_name_reads_its_bit(self):
        source = _source()
        for channel, name in pbrpass._PBR_HAS.items():
            bit = pbrpass.PBR_TEXTURE_BITS[channel]
            assert '#define %s ((materialTextures & %d) != 0)' % (name, bit) in source
        for channel, name in pbrpass._PBR_EXT_HAS.items():
            bit = pbrpass.PBR_TEXTURE_BITS[channel]
            assert '#define %s ((materialTextures & %d) != 0)' % (name, bit) in source

    def test_the_core_bits_are_the_uv_bits(self):
        """``uvFor`` already numbers the core maps; the mask uses the same bits."""
        assert [pbrpass.PBR_TEXTURE_BITS[c] for c in
                ('baseColor', 'metallicRoughness', 'normal', 'occlusion',
                 'emissive', 'lightmap')] == [1, 2, 4, 8, 16, 32]

    def test_every_bit_is_its_own(self):
        bits = list(pbrpass.PBR_TEXTURE_BITS.values())
        assert len(set(bits)) == len(bits) and all(b & (b - 1) == 0 for b in bits)


class TestTheDraw:
    def test_one_uniform_says_which_maps_are_there(self, program):
        bits = pbrpass.PBR_TEXTURE_BITS
        program.bind_pbr_textures(_Material(baseColor=11, normal=12, clearcoat=13), None)
        assert program.uniforms == [
            ('materialTextures', bits['baseColor'] | bits['normal'] | bits['clearcoat'])]
        assert sorted(program.bound) == [11, 12, 13]

    def test_a_map_still_loading_is_not_sampled(self, program):
        program.bind_pbr_textures(_Material(baseColor=None, emissive=5), None)
        assert program.uniforms == [('materialTextures', pbrpass.PBR_TEXTURE_BITS['emissive'])]

    def test_a_material_with_no_maps_samples_none(self, program):
        program.bind_pbr_textures(_Material(), None)
        assert program.uniforms == [('materialTextures', 0)]

    def test_an_extension_map_past_the_budget_is_not_sampled(self, program):
        program.bind_pbr_textures(_Material(sheenColor=9), None)
        assert program.uniforms == [('materialTextures', 0)]
        assert program.bound == []
