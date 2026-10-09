"""X_ITE's material extension nodes, which hold a PhysicalMaterial's glTF extension state

A `PhysicalMaterial`'s glTF material extensions (clearcoat, sheen,
specular, transmission, volume, ...) are nodes in its `extensions` field:
the material extension nodes of X_ITE's component (`vrml.x3d.xite`), one
per glTF extension. Those nodes are where the values are kept. The
material's own names for them (`clearcoat`, `sheenColor`, `ior`, ...) read
the field of the node of that type in `extensions`, or the field's default
where there is none, and setting one sets that node's field, adding the node
where the material has none and the value is not the default. An X3D
document carries them as X_ITE writes them, and an X3D browser with X_ITE's
component reads them back.

`MATERIAL_FIELDS` names, for each of the material's names, the node type
and field it is kept in.
"""
from typing import Any, Optional

from vrml import node, protofunctions
from vrml.x3d import codecs, xite


class AnisotropyMaterialExtension(xite.AnisotropyMaterialExtension):
    """KHR_materials_anisotropy: the specular lobe stretched along a direction"""


class ClearcoatMaterialExtension(xite.ClearcoatMaterialExtension):
    """KHR_materials_clearcoat: a clear varnish layer over the material"""


class DiffuseTransmissionMaterialExtension(xite.DiffuseTransmissionMaterialExtension):
    """KHR_materials_diffuse_transmission: light passing through and diffusing"""


class DispersionMaterialExtension(xite.DispersionMaterialExtension):
    """KHR_materials_dispersion: refraction that varies with wavelength"""


class EmissiveStrengthMaterialExtension(xite.EmissiveStrengthMaterialExtension):
    """KHR_materials_emissive_strength: a multiplier on the emissive colour"""


class IORMaterialExtension(xite.IORMaterialExtension):
    """KHR_materials_ior: the index of refraction of a dielectric"""


class IridescenceMaterialExtension(xite.IridescenceMaterialExtension):
    """KHR_materials_iridescence: thin-film interference colours"""


class RetroreflectionMaterialExtension(xite.RetroreflectionMaterialExtension):
    """KHR_materials_retroreflection: specular light sent back towards its source"""


class SheenMaterialExtension(xite.SheenMaterialExtension):
    """KHR_materials_sheen: the back-scatter of cloth fibres"""


class SpecularMaterialExtension(xite.SpecularMaterialExtension):
    """KHR_materials_specular: the strength and colour of a dielectric's reflection"""


class TransmissionMaterialExtension(xite.TransmissionMaterialExtension):
    """KHR_materials_transmission: light passing through a thin surface"""


class VolumeMaterialExtension(xite.VolumeMaterialExtension):
    """KHR_materials_volume: thickness and absorption of a transmissive volume"""


class VolumeScatterMaterialExtension(xite.VolumeScatterMaterialExtension):
    """KHR_materials_volume_scatter: light scattered beneath the surface"""


#: The engine's class for each of X_ITE's material extension node types.
ENGINE_CLASSES: "dict[type, type]" = {
    cls.__mro__[1]: cls for cls in (
        AnisotropyMaterialExtension, ClearcoatMaterialExtension,
        DiffuseTransmissionMaterialExtension, DispersionMaterialExtension,
        EmissiveStrengthMaterialExtension, IORMaterialExtension, IridescenceMaterialExtension,
        RetroreflectionMaterialExtension, SheenMaterialExtension, SpecularMaterialExtension,
        TransmissionMaterialExtension, VolumeMaterialExtension, VolumeScatterMaterialExtension,
    )
}

#: For each name a PhysicalMaterial gives an extension value, the X_ITE node
#: type and the field the value is kept in. The names are glTF's where the
#: material had them first (`ior`, `iridescenceIor`, ...); a texture's
#: `...Mapping` label follows its texture.
MATERIAL_FIELDS: "dict[str, tuple[type, str]]" = {}


def _register(kind: type, names: "dict[str, str]") -> None:
    for name, field_name in names.items():
        MATERIAL_FIELDS[name] = (kind, field_name)
        if field_name.endswith('Texture'):
            MATERIAL_FIELDS[name + 'Mapping'] = (kind, field_name + 'Mapping')


def _same(names: "list[str]") -> "dict[str, str]":
    return {name: name for name in names}


_register(xite.AnisotropyMaterialExtension, _same([
    'anisotropyStrength', 'anisotropyRotation', 'anisotropyTexture']))
_register(xite.ClearcoatMaterialExtension, _same([
    'clearcoat', 'clearcoatRoughness', 'clearcoatTexture', 'clearcoatRoughnessTexture',
    'clearcoatNormalTexture']))
_register(xite.DiffuseTransmissionMaterialExtension, _same([
        'diffuseTransmission', 'diffuseTransmissionColor', 'diffuseTransmissionTexture',
        'diffuseTransmissionColorTexture']))
_register(xite.DispersionMaterialExtension, {'dispersion': 'dispersion'})
_register(xite.EmissiveStrengthMaterialExtension, {'emissiveStrength': 'emissiveStrength'})
_register(xite.IORMaterialExtension, {'ior': 'indexOfRefraction'})
_register(xite.IridescenceMaterialExtension, {
    'iridescence': 'iridescence', 'iridescenceIor': 'iridescenceIndexOfRefraction',
    'iridescenceThicknessMin': 'iridescenceThicknessMinimum',
    'iridescenceThicknessMax': 'iridescenceThicknessMaximum',
    'iridescenceTexture': 'iridescenceTexture',
    'iridescenceThicknessTexture': 'iridescenceThicknessTexture'})
_register(xite.RetroreflectionMaterialExtension, _same([
    'retroreflection', 'retroreflectionTexture']))
_register(xite.SheenMaterialExtension, _same([
    'sheenColor', 'sheenRoughness', 'sheenColorTexture', 'sheenRoughnessTexture']))
_register(xite.SpecularMaterialExtension, _same([
    'specular', 'specularColor', 'specularStrength', 'specularTexture',
    'specularColorTexture']))
_register(xite.TransmissionMaterialExtension, _same([
    'transmission', 'transmissionTexture']))
_register(xite.VolumeMaterialExtension, _same([
    'thickness', 'attenuationColor', 'attenuationDistance', 'thicknessTexture']))
_register(xite.VolumeScatterMaterialExtension, _same([
    'scatterStrength', 'scatterAnisotropy', 'multiscatterColor', 'scatterStrengthTexture',
    'multiscatterColorTexture']))


def extension_of(material: Any, kind: type) -> Any:
    """The node of type `kind` in `material`'s `extensions`, or None"""
    for found in getattr(material, 'extensions', ()):
        if isinstance(found, kind):
            return found
    return None


def source_of(material: Any, name: str) -> "tuple[Any, Any]":
    """(node, field) holding `material`'s extension value `name`

    The node is None where the material has no extension node of the type.
    Raises KeyError for a name that is not an extension value.
    """
    kind, field_name = MATERIAL_FIELDS[name]
    return extension_of(material, kind), protofunctions.getField(kind, field_name)


def depend(holder: Any, material: Any) -> None:
    """Make `holder` clear when `material`'s extensions, or any field of them, is set"""
    holder.depend(material, 'extensions')
    for found in getattr(material, 'extensions', ()):
        if isinstance(found, node.Node):
            for declared in protofunctions.getFields(found):
                if not declared.name.startswith(' '):
                    holder.depend(found, declared)


class ExtensionValue:
    """A material attribute kept in a field of one of its extension nodes

    Read, it is that field's value, or the field's default where the
    material has no node of the type. Set, it sets the field, adding a node
    of the type to `extensions` where there is none and the value is not
    the default. A node shared between materials is shared in this too.
    """

    def __init__(self, name: str) -> None:
        self.name = name
        self.kind, self.field_name = MATERIAL_FIELDS[name]

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def _declared(self) -> Any:
        return protofunctions.getField(self.kind, self.field_name)

    def __get__(self, client: Any, cls: Any = None) -> Any:
        if client is None:
            return self
        return self.fget(client)

    def __set__(self, client: Any, value: Any) -> None:
        self.fset(client, value)

    def fget(self, client: Any) -> Any:
        """The value: the extension node's field, or its default"""
        declared = self._declared()
        found = extension_of(client, self.kind)
        if found is None:
            return declared.coerce(declared.getDefault())
        return declared.fget(found)

    def fset(self, client: Any, value: Any, notify: bool = True) -> None:
        """Set the extension node's field, adding the node where it is needed"""
        declared = self._declared()
        found = extension_of(client, self.kind)
        if found is None:
            if value is None or codecs.same(declared.coerce(value),
                                            declared.coerce(declared.getDefault())):
                return
            found = ENGINE_CLASSES[self.kind]()
            client.extensions = list(client.extensions) + [found]
        declared.fset(found, value if value is not None else node.NULL, notify=notify)

    def typeName(self) -> str:
        """The field type of the value"""
        return str(self._declared().typeName())


def texture_source(material: Any, name: str) -> "tuple[Any, Optional[Any]]":
    """(node, field) the texture `name` of `material` is read from

    The material's own field, or its extension node's; the node is None where
    the value is an extension's and the material has no node of its type.
    """
    if name in MATERIAL_FIELDS:
        return source_of(material, name)
    return material, protofunctions.getField(material, name)


def depend_texture(holder: Any, material: Any, name: str) -> None:
    """Make `holder` clear when the texture `name` of `material` is set"""
    owner, declared = texture_source(material, name)
    if name in MATERIAL_FIELDS:
        holder.depend(material, 'extensions')
    if owner is not None:
        holder.depend(owner, declared)

