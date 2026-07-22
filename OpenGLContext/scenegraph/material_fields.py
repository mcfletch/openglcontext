"""One place to read the raw VRML97 ``Material`` factors.

Three renderers consume a VRML97 ``Material``: the legacy fixed-function
``glMaterialfv`` path (``material.Material.compile``), the VRML97 shader path
(``shaderpass.configure_material_from_node``) and the PBR up-conversion
(``pbrmaterial.material_to_pbr``). Each legitimately derives *different* values
(a shader needs a shininess exponent, PBR needs a roughness), but they were each
reaching into the node's fields independently, with no shared source of truth and
nothing pinning them consistent. This module centralises the *read* -- the six
raw factors -- so the three derivations start from identical numbers; each
consumer still applies its own lighting-model semantics on top.
"""
from collections import namedtuple

# The raw factors, as plain Python (tuples/floats) so consumers are decoupled
# from the field storage type.
MaterialFields = namedtuple(
    'MaterialFields',
    'diffuseColor specularColor emissiveColor ambientIntensity shininess transparency')

# VRML97 Material field defaults -- also used when a Shape carries geometry with
# no material node at all.
DEFAULT_MATERIAL_FIELDS = MaterialFields(
    diffuseColor=(0.8, 0.8, 0.8),
    specularColor=(0.0, 0.0, 0.0),
    emissiveColor=(0.0, 0.0, 0.0),
    ambientIntensity=0.2,
    shininess=0.2,
    transparency=0.0,
)


def read_material_fields(material_node):
    """Return the raw VRML97 ``Material`` factors as a :class:`MaterialFields`.

    ``None`` (or any node without material fields -- ``vrml``'s NULL sentinel, or
    a Shape whose ``appearance.material`` is unset) yields the VRML97 defaults, so
    every caller shares one definition of "no material" too.
    """
    if material_node is None or not hasattr(material_node, 'diffuseColor'):
        return DEFAULT_MATERIAL_FIELDS
    return MaterialFields(
        diffuseColor=tuple(material_node.diffuseColor),
        specularColor=tuple(material_node.specularColor),
        emissiveColor=tuple(material_node.emissiveColor),
        ambientIntensity=float(material_node.ambientIntensity),
        shininess=float(material_node.shininess),
        transparency=float(material_node.transparency),
    )
