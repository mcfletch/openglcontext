"""Shared VRML97 material field read.

The legacy glMaterial path, the VRML97 shader path and the PBR up-conversion now
read the raw factors through one helper, so they agree on the numbers before
each applies its own lighting-model derivation.
"""
from OpenGLContext.scenegraph.material_fields import (
    read_material_fields, DEFAULT_MATERIAL_FIELDS,
)
from OpenGLContext.scenegraph.material import Material
from OpenGLContext.scenegraph.pbrmaterial import material_to_pbr


class TestReadMaterialFields:
    def test_reads_node_values(self):
        m = Material(diffuseColor=(0.1, 0.2, 0.3), specularColor=(0.4, 0.5, 0.6),
                     emissiveColor=(0.7, 0.0, 0.0), ambientIntensity=0.5,
                     shininess=0.9, transparency=0.25)
        f = read_material_fields(m)
        assert tuple(round(v, 3) for v in f.diffuseColor) == (0.1, 0.2, 0.3)
        assert tuple(round(v, 3) for v in f.specularColor) == (0.4, 0.5, 0.6)
        assert tuple(round(v, 3) for v in f.emissiveColor) == (0.7, 0.0, 0.0)
        assert round(f.ambientIntensity, 3) == 0.5
        assert round(f.shininess, 3) == 0.9
        assert round(f.transparency, 3) == 0.25

    def test_none_yields_defaults(self):
        assert read_material_fields(None) is DEFAULT_MATERIAL_FIELDS

    def test_node_without_fields_yields_defaults(self):
        class NotAMaterial:
            pass
        assert read_material_fields(NotAMaterial()) is DEFAULT_MATERIAL_FIELDS


class TestConsumersAgreeOnRawRead:
    def test_pbr_upconversion_reads_shared_diffuse_and_shininess(self):
        m = Material(diffuseColor=(0.2, 0.4, 0.6), shininess=0.75,
                     transparency=0.3, emissiveColor=(0.1, 0.0, 0.0))
        f = read_material_fields(m)
        pbr = material_to_pbr(m)
        # base color is the raw diffuse; roughness/emissive/transparency are all
        # derived from the same shared read.
        assert tuple(round(v, 3) for v in pbr['base_color']) == \
            tuple(round(v, 3) for v in f.diffuseColor)
        assert tuple(round(v, 3) for v in pbr['emissive']) == \
            tuple(round(v, 3) for v in f.emissiveColor)
        assert round(pbr['transparency'], 3) == round(f.transparency, 3)
        assert round(pbr['roughness'], 4) == round(max(0.04, 1.0 - min(1.0, f.shininess)), 4)
