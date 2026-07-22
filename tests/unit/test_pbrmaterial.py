"""Unit tests for the PBRMaterial node and VRML97->PBR up-conversion (no GL)."""
import pytest

from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture, material_to_pbr


class TestPBRMaterialDefaults:
    def test_glTF_aligned_defaults(self):
        m = PBRMaterial()
        assert tuple(m.baseColor) == (1.0, 1.0, 1.0)
        assert m.metallic == 1.0
        assert m.roughness == 1.0
        assert tuple(m.emissiveColor) == (0.0, 0.0, 0.0)
        assert m.alphaMode == 'OPAQUE'
        assert m.alphaCutoff == 0.5
        assert bool(m.doubleSided) is False
        assert m.textures == {}

    def test_fields_and_textures_set(self):
        t = PBRTexture(image=None, srgb=True)
        m = PBRMaterial(baseColor=(0.1, 0.2, 0.3), metallic=0.5, roughness=0.4,
                        textures={'baseColor': t})
        assert tuple(round(float(x), 2) for x in m.baseColor) == (0.1, 0.2, 0.3)
        assert m.metallic == 0.5 and m.roughness == 0.4
        assert m.texture('baseColor') is t
        assert m.texture('normal') is None

    def test_fits_in_appearance_slot(self):
        from OpenGLContext.scenegraph.basenodes import Appearance
        m = PBRMaterial()
        a = Appearance(material=m)
        assert a.material is m


class TestUpConversion:
    def test_none_material_defaults(self):
        f = material_to_pbr(None)
        assert f['metallic'] == 0.0
        assert 0.0 < f['roughness'] <= 1.0

    def test_shininess_maps_to_roughness(self):
        from OpenGLContext.scenegraph.basenodes import Material
        shiny = material_to_pbr(Material(diffuseColor=(1, 0, 0), shininess=0.9))
        dull = material_to_pbr(Material(diffuseColor=(1, 0, 0), shininess=0.1))
        # higher shininess -> lower roughness
        assert shiny['roughness'] < dull['roughness']
        assert tuple(round(float(x), 2) for x in shiny['base_color']) == (1.0, 0.0, 0.0)
        assert shiny['metallic'] == 0.0

    def test_roughness_clamped(self):
        from OpenGLContext.scenegraph.basenodes import Material
        f = material_to_pbr(Material(shininess=1.0))
        assert f['roughness'] >= 0.04

    def test_null_node_material_defaults(self):
        """A Shape with no material (VRML's NullNode) must up-convert to the
        default grey material, not crash -- so VRML97 geometry with an empty
        appearance still renders under the PBR pass."""
        class NullNode:
            """Mimics vrml's null sentinel: truthy, but no material fields."""
        f = material_to_pbr(NullNode())
        assert f['metallic'] == 0.0
        assert tuple(f['base_color']) == (0.8, 0.8, 0.8)
        assert 0.0 < f['roughness'] <= 1.0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
