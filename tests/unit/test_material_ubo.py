"""The std140 MaterialBlock packer writes each factor at its block offset.

The per-material factors live in a std140 uniform block in pbr.frag, uploaded
once per material and switched with a single buffer bind (instead of ~20
glUniform calls per shape). These GL-free tests pin the byte layout the shader
depends on; the driver-side offset match is exercised by the PBR render tests.
"""
import numpy as np
import pytest

from OpenGLContext.passes.pbrpass import pack_material_block, MATERIAL_BLOCK_WORDS
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


def test_block_is_224_bytes():
    buf = pack_material_block(None)
    assert buf.dtype == np.dtype('float32')
    # 44 words of base factors + uvTransform + the iridescence vec4, then the
    # later KHR extension factors -> 56 words / 224 bytes.
    assert MATERIAL_BLOCK_WORDS == 56
    assert buf.nbytes == 224            # must match the driver block data size


def test_iridescence_vec4_after_uv_transform():
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
    m = PBRMaterial()
    m.iridescence = 0.7
    m.iridescenceIor = 1.6
    m.iridescenceThicknessMin = 120.0
    m.iridescenceThicknessMax = 500.0
    buf = pack_material_block(m)
    assert abs(buf[44] - 0.7) < 1e-5
    assert abs(buf[45] - 1.6) < 1e-5
    assert abs(buf[46] - 120.0) < 1e-3
    assert abs(buf[47] - 500.0) < 1e-3


def test_pbr_material_factors_land_at_their_offsets():
    m = PBRMaterial()
    m.baseColor = (0.1, 0.2, 0.3)
    m.metallic = 0.4
    m.roughness = 0.55
    m.emissiveColor = (0.6, 0.7, 0.8)
    m.occlusionStrength = 0.9
    m.normalScale = 1.25
    m.alphaCutoff = 0.33
    m.ior = 1.7
    m.thickness = 2.0
    m.attenuationColor = (0.11, 0.22, 0.33)
    m.attenuationDistance = 5.0
    buf = pack_material_block(m)
    assert np.allclose(buf[0:3], (0.1, 0.2, 0.3)); assert np.isclose(buf[3], 0.4)
    assert np.allclose(buf[4:7], (0.6, 0.7, 0.8)); assert np.isclose(buf[7], 0.55)
    assert np.isclose(buf[11], 0.9)      # occlusionStrength (packed after specularColor)
    assert np.isclose(buf[15], 1.25)     # normalScale
    assert np.allclose(buf[16:19], (0.11, 0.22, 0.33))  # attenuationColor
    assert np.isclose(buf[19], 0.33)     # alphaCutoff
    assert np.isclose(buf[25], 1.7)      # ior
    assert np.isclose(buf[26], 2.0)      # thicknessFactor
    assert np.isclose(buf[27], 5.0)      # attenuationDistance


def test_unlit_flag_is_int_at_word_28():
    m = PBRMaterial(); m.unlit = 1
    iv = pack_material_block(m).view(np.int32)
    assert iv[28] == 1
    m.unlit = 0
    assert pack_material_block(m).view(np.int32)[28] == 0


def test_identity_uv_transform_when_absent():
    buf = pack_material_block(PBRMaterial())
    # mat3 columns at words 32.., each padded to 4; identity has 1s on the diagonal
    assert np.isclose(buf[32], 1.0)      # col0.x
    assert np.isclose(buf[37], 1.0)      # col1.y
    assert np.isclose(buf[42], 1.0)      # col2.z
    assert np.isclose(buf[33], 0.0) and np.isclose(buf[34], 0.0)


def test_uv_transform_columns_packed_column_major():
    m = PBRMaterial()
    M = np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]], 'f')
    m.uv_transform = M
    buf = pack_material_block(m)
    assert np.allclose(buf[32:35], M[:, 0])   # column 0
    assert np.allclose(buf[36:39], M[:, 1])   # column 1
    assert np.allclose(buf[40:43], M[:, 2])   # column 2


def test_none_material_is_neutral_grey():
    buf = pack_material_block(None)
    assert np.allclose(buf[0:3], (0.8, 0.8, 0.8))   # default base color
    assert np.isclose(buf[3], 0.0)                  # metallic 0 (dielectric)
    iv = buf.view(np.int32)
    assert iv[28] == 0                              # not unlit


def test_vrml97_material_up_converts():
    from OpenGLContext.scenegraph import basenodes
    vm = basenodes.Material(diffuseColor=(0.2, 0.5, 0.9), shininess=0.0)
    buf = pack_material_block(vm)
    assert np.allclose(buf[0:3], (0.2, 0.5, 0.9))
    assert np.isclose(buf[3], 0.0)                  # metallic 0 for legacy
    assert buf[7] > 0.0                             # roughness derived from shininess


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
