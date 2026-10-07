"""Each material's factor block, as a GL uniform buffer.

The block is the material's: every PBR program in a context draws a material
from the one buffer, which is filled again when the material is edited and
deleted when the material is collected or the context is torn down.
"""
import gc

from OpenGL import GL

from OpenGLContext import contextresources
from OpenGLContext.passes.pbrpass import PBRShaderProgram
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial


class Material:
    """A material with nothing but the version an edit moves"""

    factorVersion = 0


def recording(monkeypatch):
    """The materials each upload packed, in order"""
    packed = []

    def upload(self, material, buf=None):
        packed.append(material)
        return buf if buf is not None else len(packed)
    monkeypatch.setattr(PBRShaderProgram, '_upload_material_ubo', upload)
    return packed


class TestRepacking:
    def test_a_block_is_packed_once(self, monkeypatch):
        packed = recording(monkeypatch)
        material = Material()
        program = PBRShaderProgram()
        assert program._material_ubo(material) == program._material_ubo(material)
        assert packed == [material]

    def test_an_edit_repacks_into_the_same_buffer(self, monkeypatch):
        packed = recording(monkeypatch)
        material = Material()
        program = PBRShaderProgram()
        first = program._material_ubo(material)
        material.factorVersion = 1
        assert program._material_ubo(material) == first
        assert packed == [material, material]

    def test_invalidating_one_material_repacks_only_it(self, monkeypatch):
        packed = recording(monkeypatch)
        a, b = Material(), Material()
        program = PBRShaderProgram()
        program._material_ubo(a), program._material_ubo(b)
        program.invalidate_material_ubo(a)
        program._material_ubo(a), program._material_ubo(b)
        assert packed == [a, b, a]

    def test_invalidating_all_repacks_every_material_and_the_default(self, monkeypatch):
        packed = recording(monkeypatch)
        a = Material()
        program = PBRShaderProgram()
        program._material_ubo(a), program._material_ubo(None)
        program.invalidate_material_ubo()
        program._material_ubo(a), program._material_ubo(None)
        assert packed == [a, None, a, None]

    def test_programs_share_a_materials_block(self, monkeypatch):
        packed = recording(monkeypatch)
        material = Material()
        first = PBRShaderProgram()._material_ubo(material)
        assert PBRShaderProgram()._material_ubo(material) == first
        assert packed == [material]


class TestTheBuffer:
    def test_a_collected_materials_buffer_is_deleted(self, gl_context):
        program = PBRShaderProgram()
        kept, material = PhysicalMaterial(), PhysicalMaterial(baseColor=(1, 0, 0))
        program._material_ubo(kept)
        buffer = program._material_ubo(material)
        assert GL.glIsBuffer(buffer)
        del material
        gc.collect()
        # A block already made, so no new buffer can take the deleted name.
        program._material_ubo(kept)
        assert not GL.glIsBuffer(buffer)

    def test_a_released_program_leaves_a_live_materials_buffer(self, gl_context):
        material = PhysicalMaterial()
        first = PBRShaderProgram()
        buffer = first._material_ubo(material)
        first.release()
        assert GL.glIsBuffer(buffer)
        assert PBRShaderProgram()._material_ubo(material) == buffer

    def test_a_lost_context_deletes_every_block(self, gl_context):
        material = PhysicalMaterial()
        program = PBRShaderProgram()
        buffers = [program._material_ubo(material), program._material_ubo(None)]
        contextresources.context_lost()
        assert not any(GL.glIsBuffer(buffer) for buffer in buffers)
        assert GL.glIsBuffer(program._material_ubo(material))
