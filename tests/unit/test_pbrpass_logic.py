"""Headless tests for PBR-pass logic that needs no GL context.

The instancing/collapse env toggles, the pass's instance predicate and batch-key
choice, the material-array chunking that keeps a draw under the UBO capacity, and
the material-UBO cache invalidation bookkeeping.
"""
from OpenGLContext.passes import pbrpass
from OpenGLContext.passes.pbrpass import PBRPass, PBRShaderProgram
from OpenGLContext.passes import instancing


class Geom:
    def __init__(self, instanceable=True, content=('g',)):
        if instanceable:
            self.instanceGPU = lambda mode: None
        self.instanceContentKey = lambda: content


class Mat:
    """A weakref-able stand-in material (WeakKeyDictionary keys need this)."""


class Shape:
    def __init__(self, geometry, material=None, texture=None):
        self.geometry = geometry
        self.appearance = type('A', (), {'material': material,
                                         'texture': texture})()


class TestInstancingEnvToggles:
    def test_instancing_default_on(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_INSTANCING', raising=False)
        assert pbrpass.instancing_is_enabled() is True

    def test_instancing_off(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCING', 'off')
        assert pbrpass.instancing_is_enabled() is False

    def test_collapse_default_on(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', raising=False)
        assert pbrpass.instance_collapse_is_enabled() is True

    def test_collapse_off(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', '0')
        assert pbrpass.instance_collapse_is_enabled() is False


class TestPassInstancing:
    def test_instancing_enabled_property_reads_env(self, monkeypatch):
        p = PBRPass.__new__(PBRPass)
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCING', '1')
        assert p.instancing_enabled is True
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCING', 'false')
        assert p.instancing_enabled is False

    def test_get_shader_program_builds_and_caches_pbr_program(self):
        p = PBRPass.__new__(PBRPass)
        p._shader_program_instance = None
        prog = p.getShaderProgram()
        assert isinstance(prog, PBRShaderProgram)
        assert p.getShaderProgram() is prog     # cached, same instance

    def test_instanceable_requires_instance_gpu(self):
        p = PBRPass.__new__(PBRPass)
        assert p._instanceable([Shape(Geom(instanceable=True))]) is True
        assert p._instanceable([Shape(Geom(instanceable=False))]) is False

    def test_instance_key_uses_content_when_collapse_on(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', '1')
        p = PBRPass.__new__(PBRPass)
        pth = [Shape(Geom(content=('C', 2.0)))]
        assert p._instanceKey(pth) == instancing.geometry_content_key(pth)

    def test_instance_key_uses_texture_when_collapse_off(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_INSTANCE_COLLAPSE', 'off')
        p = PBRPass.__new__(PBRPass)
        pth = [Shape(Geom(content=('C', 2.0)))]
        assert p._instanceKey(pth) == instancing.geometry_texture_key(pth)


class TestMaterialChunks:
    def _chunks(self, members, materials, indices, max_mats):
        p = PBRPass.__new__(PBRPass)
        return list(p._material_chunks(members, materials, indices, max_mats))

    def test_single_chunk_when_under_capacity(self):
        mats = [object(), object()]
        members = ['a', 'b', 'c']
        indices = [0, 1, 0]
        chunks = self._chunks(members, mats, indices, max_mats=4)
        assert chunks == [(members, mats, indices)]

    def test_splits_and_rebases_indices_over_capacity(self):
        m0, m1, m2, m3 = object(), object(), object(), object()
        materials = [m0, m1, m2, m3]
        # members reference materials 0,1,2,3,0 in order
        members = ['A', 'B', 'C', 'D', 'E']
        indices = [0, 1, 2, 3, 0]
        chunks = self._chunks(members, materials, indices, max_mats=2)
        # Every member appears exactly once across chunks.
        seen = [m for cm, _, _ in chunks for m in cm]
        assert sorted(seen) == sorted(members)
        # Each chunk holds at most max_mats distinct materials, indices rebased.
        for cm, cmat, cidx in chunks:
            assert len(cmat) <= 2
            assert max(cidx) < len(cmat)
            # the rebased index resolves back to the original material
            for member, gi in zip(cm, cidx, strict=True):
                original = members.index(member)
                assert cmat[gi] is materials[indices[original]]

    def test_repeated_material_stays_in_same_chunk(self):
        m0, m1 = object(), object()
        materials = [m0, m1]
        members = ['A', 'B', 'C']
        indices = [0, 1, 0]     # only two distinct materials
        chunks = self._chunks(members, materials, indices, max_mats=2)
        assert len(chunks) == 1


class TestMaterialUBOInvalidation:
    def test_invalidate_all_clears_cache_and_default(self):
        prog = PBRShaderProgram()
        marker = Mat()
        prog._material_ubos[marker] = (7, 0)
        prog._default_material_ubo = 42
        prog.invalidate_material_ubo(None)
        assert len(prog._material_ubos) == 0
        assert prog._default_material_ubo is None

    def test_invalidate_one_material_leaves_others(self):
        prog = PBRShaderProgram()
        a, b = Mat(), Mat()
        prog._material_ubos[a] = (1, 0)
        prog._material_ubos[b] = (2, 0)
        prog.invalidate_material_ubo(a)
        assert a not in prog._material_ubos
        assert b in prog._material_ubos
