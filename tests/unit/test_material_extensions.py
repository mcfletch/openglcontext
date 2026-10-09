"""A PhysicalMaterial's glTF extension values, kept in X_ITE's material extension nodes.

The material's `clearcoat`, `ior`, `sheenColor` and the rest read and set a
field of the extension node of their type in its `extensions`. An X3D
document carries them as those nodes, in X_ITE's component.
"""
import numpy as np
import pytest
from vrml import x3d as vrml_x3d
from vrml.x3d import nodes as x3d
from vrml.x3d import xite
from vrml.x3d.scene import X3DScene

from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import materialextensions
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial


def kinds(material):
    return [type(item).__name__ for item in material.extensions]


def test_a_value_set_adds_the_node_of_its_type():
    material = PhysicalMaterial(clearcoat=0.5)
    assert kinds(material) == ['ClearcoatMaterialExtension']
    assert material.extensions[0].clearcoat == pytest.approx(0.5)
    assert material.clearcoat == pytest.approx(0.5)


def test_a_second_value_of_the_type_shares_its_node():
    material = PhysicalMaterial(clearcoat=0.5, clearcoatRoughness=0.25)
    assert kinds(material) == ['ClearcoatMaterialExtension']
    assert material.extensions[0].clearcoatRoughness == pytest.approx(0.25)


def test_without_a_node_a_value_is_the_fields_default():
    material = PhysicalMaterial()
    assert material.ior == pytest.approx(1.5)
    assert material.iridescenceIor == pytest.approx(1.3)
    assert material.emissiveStrength == pytest.approx(1.0)
    assert list(material.specularColor) == [1.0, 1.0, 1.0]
    assert material.extensions == []


def test_setting_a_default_adds_no_node():
    material = PhysicalMaterial(ior=1.5, transmission=0.0)
    assert material.extensions == []


def test_the_material_names_map_onto_x_ite_s():
    material = PhysicalMaterial(ior=1.33, iridescenceIor=1.8, iridescenceThicknessMin=50.0,
                                iridescenceThicknessMax=600.0)
    ior = materialextensions.extension_of(material, xite.IORMaterialExtension)
    assert ior.indexOfRefraction == pytest.approx(1.33)
    film = materialextensions.extension_of(material, xite.IridescenceMaterialExtension)
    assert film.iridescenceIndexOfRefraction == pytest.approx(1.8)
    assert film.iridescenceThicknessMinimum == pytest.approx(50.0)
    assert film.iridescenceThicknessMaximum == pytest.approx(600.0)


def test_a_node_set_in_extensions_is_read():
    material = PhysicalMaterial(extensions=[
        materialextensions.SheenMaterialExtension(sheenColor=(1, 0, 0), sheenRoughness=0.5)])
    assert list(material.sheenColor) == [1.0, 0.0, 0.0]
    assert material.sheenRoughness == pytest.approx(0.5)


def test_an_edit_to_an_extension_node_moves_the_factor_version():
    sheen = materialextensions.SheenMaterialExtension()
    material = PhysicalMaterial(extensions=[sheen])
    before = material.factorVersion
    sheen.sheenRoughness = 0.75
    assert material.factorVersion != before
    before = material.factorVersion
    material.transmission = 0.5
    assert material.factorVersion != before


def test_an_extension_texture_is_a_channel():
    texture = ImageDataTexture()
    material = PhysicalMaterial(clearcoatTexture=texture, clearcoatTextureMapping='TEXCOORD_1')
    assert material.texture('clearcoat') is texture
    assert material.textureMapping('clearcoat') == 'TEXCOORD_1'
    replacement = ImageDataTexture()
    material.extensions[0].clearcoatTexture = replacement
    assert material.texture('clearcoat') is replacement
    material.setTexture('sheenColor', texture)
    assert material.texture('sheenColor') is texture


def test_every_extension_name_has_its_node_type_and_field():
    for name, (kind, field_name) in materialextensions.MATERIAL_FIELDS.items():
        assert hasattr(kind, field_name), name
        assert isinstance(getattr(PhysicalMaterial, name), materialextensions.ExtensionValue)


def written_and_read(material, encoding='xml'):
    scene = X3DScene(children=[x3d.Shape(appearance=Appearance(material=material),
                                         geometry=x3d.Box())])
    text = vrml_x3d.dumps(scene, encoding=encoding)
    return text, vrml_x3d.loads(text, prototypes=prototypes()).children[0].appearance.material


@pytest.mark.parametrize('encoding', ['xml', 'classic', 'json'])
def test_an_x3d_document_carries_the_extension_nodes(encoding):
    material = PhysicalMaterial(clearcoat=0.75, sheenColor=(0.5, 0.25, 0.0), ior=1.4,
                                lightmapStrength=2.0)
    text, read = written_and_read(material, encoding)
    assert 'ClearcoatMaterialExtension' in text
    assert 'X_ITE' in text
    assert "'clearcoat'" not in text.replace('"', "'")
    assert isinstance(read, PhysicalMaterial)
    assert read.clearcoat == pytest.approx(0.75)
    assert np.allclose(read.sheenColor, (0.5, 0.25, 0.0))
    assert read.ior == pytest.approx(1.4)
    assert read.lightmapStrength == pytest.approx(2.0)
    assert sorted(kinds(read)) == ['ClearcoatMaterialExtension', 'IORMaterialExtension',
                                   'SheenMaterialExtension']


def test_an_x_ite_document_builds_the_engine_classes():
    text = """<X3D profile='Interchange' version='4.0'><head>
        <component name='X_ITE' level='1'/></head><Scene><Shape><Appearance>
        <PhysicalMaterial><TransmissionMaterialExtension transmission='1'/>
        <VolumeMaterialExtension thickness='0.5' attenuationColor='1 0.5 0.5'/>
        </PhysicalMaterial></Appearance><Sphere/></Shape></Scene></X3D>"""
    scene = vrml_x3d.loads(text, prototypes=prototypes())
    assert not [item for item in scene.problems if 'no implementation' in item.message]
    material = scene.children[0].appearance.material
    assert isinstance(material.extensions[0], materialextensions.TransmissionMaterialExtension)
    assert material.transmission == pytest.approx(1.0)
    assert material.thickness == pytest.approx(0.5)
    assert np.allclose(material.attenuationColor, (1.0, 0.5, 0.5))
