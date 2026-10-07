"""BLEND shapes sort into the back-to-front transparent pass, not with opaques.

The appearance's alpha mode decides (`appearance_alpha`), at the Appearance
boundary (Shape.sortKey) and on a PBRMesh drawn with its own appearance.

A transmissive OPAQUE material stays opaque: the transmission pass takes it
from the opaque bucket, captures the backdrop, and draws it back to front.
Marking it transparent would lose that path, so these hold that transmission
alone does not move a material to the blended pass.
"""
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import (
    PhysicalMaterial, appearance_is_transparent,
)


def look(mode='AUTO', **factors):
    return Appearance(material=PhysicalMaterial(**factors), alphaMode=mode)


class TestAppearanceIsTransparent:
    def test_blend_is_transparent(self):
        assert appearance_is_transparent(look('BLEND', transparency=0.5))

    def test_opaque_is_not_transparent(self):
        # OPAQUE ignores the base colour's alpha, as glTF says
        assert not appearance_is_transparent(look('OPAQUE', transparency=0.5))

    def test_mask_is_not_transparent(self):
        assert not appearance_is_transparent(look('MASK'))

    def test_transmission_opaque_stays_opaque(self):
        assert not appearance_is_transparent(look('OPAQUE', transmission=0.7))

    def test_blend_with_transmission_is_transparent(self):
        assert appearance_is_transparent(look('BLEND', transmission=0.7))

    def test_none_is_not_transparent(self):
        assert not appearance_is_transparent(None)

    def test_auto_follows_the_transparency_field(self):
        assert appearance_is_transparent(look(transparency=0.4))
        assert not appearance_is_transparent(look())


class TestAppearanceSortKey:
    def test_blend_sorts_transparent(self):
        assert look('BLEND', transparency=0.5).sortKey(mode=None, matrix=None)[0] is True

    def test_transmissive_opaque_sorts_opaque(self):
        assert look('OPAQUE', transmission=0.6).sortKey(mode=None, matrix=None)[0] is False

    def test_opaque_sorts_opaque(self):
        assert look('OPAQUE').sortKey(mode=None, matrix=None)[0] is False


class TestPBRMeshSortKey:
    TRIANGLE = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]

    def test_blend_mesh_sorts_transparent(self):
        mesh = PBRMesh(positions=self.TRIANGLE, appearance=look('BLEND', transparency=0.5))
        assert mesh.sortKey(mode=None, matrix=None)[0] is True

    def test_transmissive_opaque_mesh_sorts_opaque(self):
        mesh = PBRMesh(positions=self.TRIANGLE, appearance=look('OPAQUE', transmission=0.5))
        assert mesh.sortKey(mode=None, matrix=None)[0] is False

    def test_a_mesh_with_no_appearance_sorts_opaque(self):
        mesh = PBRMesh(positions=self.TRIANGLE)
        assert mesh.sortKey(mode=None, matrix=None)[0] is False
