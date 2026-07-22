"""BLEND PBR shapes must sort into the back-to-front transparent
pass, not batch with opaques -- and PBRMesh.sortKey used to always report opaque,
so a Shape-less BLEND mesh drew unsorted. These lock the shared
`material_is_transparent` classification at both the Appearance boundary (the
exercised Shape.sortKey path) and PBRMesh itself.

A transmissive OPAQUE material deliberately stays opaque: the dedicated
transmission pass pulls it from the opaque bucket, captures the backdrop, and
draws it back-to-front. Marking it transparent would lose that path -- so these
tests assert transmission alone does NOT flip a material to the blended pass.
"""
import pytest

from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, material_is_transparent
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.appearance import Appearance


class TestMaterialIsTransparent:
    def test_blend_is_transparent(self):
        assert material_is_transparent(PBRMaterial(alphaMode='BLEND', transparency=0.5))

    def test_opaque_is_not_transparent(self):
        # OPAQUE ignores baseColor alpha per the glTF spec
        assert not material_is_transparent(
            PBRMaterial(alphaMode='OPAQUE', transparency=0.5))

    def test_mask_is_not_transparent(self):
        assert not material_is_transparent(PBRMaterial(alphaMode='MASK'))

    def test_transmission_opaque_stays_opaque(self):
        # handled by the dedicated transmission pass, not the blended pass
        assert not material_is_transparent(
            PBRMaterial(alphaMode='OPAQUE', transmission=0.7))

    def test_blend_with_transmission_is_transparent(self):
        assert material_is_transparent(
            PBRMaterial(alphaMode='BLEND', transmission=0.7))

    def test_none_is_not_transparent(self):
        assert not material_is_transparent(None)

    def test_legacy_transparency_field(self):
        # a material with no alphaMode falls back to the transparency field
        class Legacy:
            transparency = 0.4
        assert material_is_transparent(Legacy())


class TestAppearanceSortKey:
    def test_blend_material_sorts_transparent(self):
        app = Appearance(material=PBRMaterial(alphaMode='BLEND', transparency=0.5))
        assert app.sortKey(mode=None, matrix=None)[0] is True

    def test_transmissive_opaque_material_sorts_opaque(self):
        app = Appearance(material=PBRMaterial(alphaMode='OPAQUE', transmission=0.6))
        assert app.sortKey(mode=None, matrix=None)[0] is False

    def test_opaque_material_sorts_opaque(self):
        app = Appearance(material=PBRMaterial(alphaMode='OPAQUE'))
        assert app.sortKey(mode=None, matrix=None)[0] is False


class TestPBRMeshSortKey:
    def test_blend_mesh_sorts_transparent(self):
        mesh = PBRMesh(positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        mesh.material = PBRMaterial(alphaMode='BLEND', transparency=0.5)
        assert mesh.sortKey(mode=None, matrix=None)[0] is True

    def test_transmissive_opaque_mesh_sorts_opaque(self):
        mesh = PBRMesh(positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        mesh.material = PBRMaterial(alphaMode='OPAQUE', transmission=0.5)
        assert mesh.sortKey(mode=None, matrix=None)[0] is False

    def test_opaque_mesh_sorts_opaque(self):
        mesh = PBRMesh(positions=[[0, 0, 0], [1, 0, 0], [0, 1, 0]])
        assert mesh.sortKey(mode=None, matrix=None)[0] is False


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
