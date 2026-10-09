"""PhysicalMaterial: the engine's metallic/roughness material, which is X3D's

`PhysicalMaterial` is X3D 4's `PhysicalMaterial` with the glTF material
extensions (clearcoat, sheen, specular, transmission, volume, iridescence,
anisotropy, dispersion, diffuse transmission, emissive strength, ior,
retroreflection, volume scatter) and the engine's own fields (lightmap, baked
light, octahedral impostors, planar reflection). The extensions' values are
kept in X_ITE's material extension nodes in its `extensions` field, and read
and set under the material's own names
(:mod:`~OpenGLContext.scenegraph.materialextensions`); the engine's fields
are fields of the material, which an X3D document carries in an
`OpenGLContext` metadata set. It goes in an `Appearance`'s `material` slot,
and the PBR pass draws it with a Cook-Torrance BRDF.

Each texture is an `SFNode` field holding an X3D texture node (an
`ImageTexture`, or an `ImageDataTexture` for an image already decoded), with a
`...TextureMapping` field naming the texture coordinates it reads. The core
channels are X3D's fields (`baseTexture`, `metallicRoughnessTexture`,
`normalTexture`, `occlusionTexture`, `emissiveTexture`); `CHANNEL_FIELDS`
gives the field for every channel the pass binds.
"""
import types
import weakref
from typing import Any, Optional

import numpy as np

from vrml import cache, field, node, protofunctions
from vrml.x3d import nodes as x3d
from vrml.x3d import xite

from OpenGLContext import lighting
from OpenGLContext.scenegraph import materialextensions
from OpenGLContext.scenegraph.materialextensions import ExtensionValue

#: The texture field of each channel the PBR pass binds, by channel name.
CHANNEL_FIELDS = {
    'baseColor': 'baseTexture',
    'metallicRoughness': 'metallicRoughnessTexture',
    'normal': 'normalTexture',
    'occlusion': 'occlusionTexture',
    'emissive': 'emissiveTexture',
    'lightmap': 'lightmapTexture',
    'transmission': 'transmissionTexture',
    'iridescence': 'iridescenceTexture',
    'iridescenceThickness': 'iridescenceThicknessTexture',
    'clearcoat': 'clearcoatTexture',
    'clearcoatRoughness': 'clearcoatRoughnessTexture',
    'clearcoatNormal': 'clearcoatNormalTexture',
    'thickness': 'thicknessTexture',
    'anisotropy': 'anisotropyTexture',
    'specular': 'specularTexture',
    'specularColor': 'specularColorTexture',
    'sheenColor': 'sheenColorTexture',
    'sheenRoughness': 'sheenRoughnessTexture',
    'diffuseTransmission': 'diffuseTransmissionTexture',
    'diffuseTransmissionColor': 'diffuseTransmissionColorTexture',
    'retroreflection': 'retroreflectionTexture',
    'scatterStrength': 'scatterStrengthTexture',
    'multiscatterColor': 'multiscatterColorTexture',
}

#: The keys the material's versions are held under in vrml's global cache.
_FIELDS_KEY = 'physicalmaterial-fields'
_TEXTURES_KEY = 'physicalmaterial-textures'


class _Moved:
    """A name a material does not have, saying where X3D puts it

    Reading or setting it raises AttributeError with the place to use, so code
    written for glTF's material layout fails where it is wrong rather than
    setting an attribute nothing reads.
    """

    def __init__(self, where: str) -> None:
        self.where = where
        self.name = ''

    def __set_name__(self, owner: type, name: str) -> None:
        self.name = name

    def __get__(self, client: Any, cls: Any = None) -> Any:
        raise AttributeError('%s is not a material field; %s' % (self.name, self.where))

    def __set__(self, client: Any, value: Any) -> None:
        raise AttributeError('%s is not a material field; %s' % (self.name, self.where))


def _texture_field(name: str) -> Any:
    return field.newField(name, 'SFNode', 1, node.NULL,
                          requiredTypes=(x3d.X3DSingleTextureNode,))


def _mapping_field(name: str) -> Any:
    return field.newField(name + 'Mapping', 'SFString', 1, '')


class ChannelMaterial:
    """What the PBR pass reads from the engine's material nodes

    A view of the texture fields by channel name, and a version that moves
    whenever a field is set. `CHANNELS` maps each channel the material has to
    its texture field.
    """

    CHANNELS: "dict[str, str]" = {}
    #: The metadata set an X3D document carries the fields X3D's node lacks
    #: in (`vrml.x3d.extension`).
    x3dExtension = 'OpenGLContext'

    @property
    def textures(self) -> "types.MappingProxyType[str, Any]":
        """The texture nodes by channel name, read from the texture fields"""
        found: "Optional[types.MappingProxyType[str, Any]]" = cache.CACHE.getData(
            self, _TEXTURES_KEY)
        if found is None:
            channels = {}
            holder = cache.CACHE.holder(self, None, _TEXTURES_KEY)
            for channel, name in self.CHANNELS.items():
                materialextensions.depend_texture(holder, self, name)
                value = getattr(self, name)
                if value:
                    channels[channel] = value
            found = holder.data = types.MappingProxyType(channels)
        return found

    def texture(self, channel: str) -> Any:
        """The texture node of `channel`, or None"""
        return self.textures.get(channel)

    def textureMapping(self, channel: str) -> str:
        """The mapping label of `channel`'s map: its `...TextureMapping` field"""
        return str(getattr(self, self.CHANNELS[channel] + 'Mapping', '') or '')

    def setTexture(self, channel: str, texture: Any) -> None:
        """Set the texture field of `channel` (a key of `CHANNELS`)

        NULL or None clears it. Raises KeyError for an unknown channel.
        """
        setattr(self, self.CHANNELS[channel], texture if texture is not None else node.NULL)

    @property
    def factorVersion(self) -> int:
        """A count that moves whenever a field of the material is set

        Setting a field moves it, and so does :meth:`factorsChanged`. The
        pass repacks the material's uniform block when it has moved since the
        last pack.
        """
        if cache.CACHE.getData(self, _FIELDS_KEY) is None:
            self.factorsChanged()
            holder = cache.CACHE.holder(self, True, _FIELDS_KEY)
            for declared in protofunctions.getFields(self):
                if not declared.name.startswith(' '):
                    holder.depend(self, declared)
            if hasattr(self, 'extensions'):
                materialextensions.depend(holder, self)
        return int(self.__dict__.get('_version', 0))

    def factorsChanged(self) -> None:
        """Move the version, for an edit made in place rather than by a set

        A component written into a colour field's array, say.
        """
        self.__dict__['_version'] = int(self.__dict__.get('_version', 0)) + 1

    def batchingVersion(self) -> int:
        """A value that changes whenever something deciding how this batches does"""
        return self.factorVersion

    def legacyTexture(self, mode: Any) -> Any:
        """The base colour map's GL texture, or None: what the fixed-function pass draws"""
        base = self.texture('baseColor')
        return base.cached(mode) if base is not None else None


class PhysicalMaterial(ChannelMaterial, xite.PhysicalMaterial):
    """X3D's PhysicalMaterial, with the glTF extensions and the engine's fields"""

    PROTO = 'PhysicalMaterial'

    # The glTF material extensions' values, kept in the extension nodes.
    emissiveStrength = ExtensionValue('emissiveStrength')
    specular = ExtensionValue('specular')
    specularColor = ExtensionValue('specularColor')
    #: A multiplier on `specularColor` (X_ITE's), which may then exceed 1.
    specularStrength = ExtensionValue('specularStrength')
    clearcoat = ExtensionValue('clearcoat')
    clearcoatRoughness = ExtensionValue('clearcoatRoughness')
    #: The strength of `clearcoatNormalTexture`, as `normalScale` is of the
    #: base normal map: its x and y are multiplied by it. glTF's
    #: `clearcoatNormalTexture.scale`; X_ITE's clearcoat node has no such
    #: field, so it is the material's own.
    clearcoatNormalScale = field.newField('clearcoatNormalScale', 'SFFloat', 1, 1.0)
    sheenColor = ExtensionValue('sheenColor')
    sheenRoughness = ExtensionValue('sheenRoughness')
    ior = ExtensionValue('ior')
    #: The fraction of light transmitted through the surface.
    transmission = ExtensionValue('transmission')
    #: The volume's thickness and absorption: light falls to `attenuationColor`
    #: after `attenuationDistance` metres inside it. 0 is no absorption, as
    #: is the default, which stands for glTF's infinite distance.
    thickness = ExtensionValue('thickness')
    attenuationColor = ExtensionValue('attenuationColor')
    attenuationDistance = ExtensionValue('attenuationDistance')
    #: Light passing through and diffusing: leaves, wax, skin. 0 is opaque.
    diffuseTransmission = ExtensionValue('diffuseTransmission')
    diffuseTransmissionColor = ExtensionValue('diffuseTransmissionColor')
    #: The specular lobe's stretch, and its direction in radians.
    anisotropyStrength = ExtensionValue('anisotropyStrength')
    anisotropyRotation = ExtensionValue('anisotropyRotation')
    #: Wavelength-dependent refraction.
    dispersion = ExtensionValue('dispersion')
    #: Thin-film interference; thickness in nanometres.
    iridescence = ExtensionValue('iridescence')
    iridescenceIor = ExtensionValue('iridescenceIor')
    iridescenceThicknessMin = ExtensionValue('iridescenceThicknessMin')
    iridescenceThicknessMax = ExtensionValue('iridescenceThicknessMax')
    #: The blend from ordinary to retroreflective specular, 0 to 1.
    retroreflection = ExtensionValue('retroreflection')
    #: Subsurface scattering: the colour light scattered many times takes,
    #: and the phase function's anisotropy, -1 to 1.
    multiscatterColor = ExtensionValue('multiscatterColor')
    scatterAnisotropy = ExtensionValue('scatterAnisotropy')
    scatterStrength = ExtensionValue('scatterStrength')

    CHANNELS = CHANNEL_FIELDS

    alphaMode = _Moved("it is the Appearance's alphaMode")
    alphaCutoff = _Moved("it is the Appearance's alphaCutoff")
    doubleSided = _Moved("a geometry that is not solid is drawn from both sides")
    unlit = _Moved('an unlit surface is an UnlitMaterial')

    texCoordMask = _Moved("a channel's coordinates are named by its ...TextureMapping field")
    uv_transform = _Moved("a texture transform is the Appearance's textureTransform")

    #: Multiplier on the baked-irradiance `lightmapTexture`. Baked lighting
    #: comes from level formats whose lightmaps are authored against an
    #: engine-specific exposure.
    lightmapStrength = field.newField('lightmapStrength', 'SFFloat', 1, 1.0)
    #: An octahedral impostor: the base texture holds this many views a side
    #: of the model, and the quad wearing it is turned to the viewer and
    #: shows the one matching the direction it is seen from. 0 is every
    #: ordinary material. See `OpenGLContext.scenegraph.octahedral`.
    octahedralViews = field.newField('octahedralViews', 'SFInt32', 1, 0)
    #: Whether that atlas holds the upper hemisphere only.
    octahedralHemi = field.newField('octahedralHemi', 'SFBool', 1, True)
    #: Whether `COLOR_0` is light baked when the world was built rather than a
    #: tint: added as emission, with the surface keeping its own colour.
    bakedLight = field.newField('bakedLight', 'SFBool', 1, False)
    #: A `PlanarReflector`: every surface drawn with this material mirrors the
    #: scene in its own plane. Without one a smooth surface reflects the
    #: environment probe.
    reflector = field.newField('reflector', 'SFNode', 1, node.NULL)

    # The engine's lightmap channel, in the pattern of X3D's baseTexture and
    # baseTextureMapping, and the extensions' maps, kept in their nodes.
    lightmapTexture = _texture_field('lightmapTexture')
    lightmapTextureMapping = _mapping_field('lightmapTexture')
    transmissionTexture = ExtensionValue('transmissionTexture')
    transmissionTextureMapping = ExtensionValue('transmissionTextureMapping')
    iridescenceTexture = ExtensionValue('iridescenceTexture')
    iridescenceTextureMapping = ExtensionValue('iridescenceTextureMapping')
    iridescenceThicknessTexture = ExtensionValue('iridescenceThicknessTexture')
    iridescenceThicknessTextureMapping = ExtensionValue('iridescenceThicknessTextureMapping')
    clearcoatTexture = ExtensionValue('clearcoatTexture')
    clearcoatTextureMapping = ExtensionValue('clearcoatTextureMapping')
    clearcoatRoughnessTexture = ExtensionValue('clearcoatRoughnessTexture')
    clearcoatRoughnessTextureMapping = ExtensionValue('clearcoatRoughnessTextureMapping')
    clearcoatNormalTexture = ExtensionValue('clearcoatNormalTexture')
    clearcoatNormalTextureMapping = ExtensionValue('clearcoatNormalTextureMapping')
    thicknessTexture = ExtensionValue('thicknessTexture')
    thicknessTextureMapping = ExtensionValue('thicknessTextureMapping')
    anisotropyTexture = ExtensionValue('anisotropyTexture')
    anisotropyTextureMapping = ExtensionValue('anisotropyTextureMapping')
    specularTexture = ExtensionValue('specularTexture')
    specularTextureMapping = ExtensionValue('specularTextureMapping')
    specularColorTexture = ExtensionValue('specularColorTexture')
    specularColorTextureMapping = ExtensionValue('specularColorTextureMapping')
    sheenColorTexture = ExtensionValue('sheenColorTexture')
    sheenColorTextureMapping = ExtensionValue('sheenColorTextureMapping')
    sheenRoughnessTexture = ExtensionValue('sheenRoughnessTexture')
    sheenRoughnessTextureMapping = ExtensionValue('sheenRoughnessTextureMapping')
    diffuseTransmissionTexture = ExtensionValue('diffuseTransmissionTexture')
    diffuseTransmissionTextureMapping = ExtensionValue('diffuseTransmissionTextureMapping')
    diffuseTransmissionColorTexture = ExtensionValue('diffuseTransmissionColorTexture')
    diffuseTransmissionColorTextureMapping = ExtensionValue('diffuseTransmissionColorTextureMapping')
    retroreflectionTexture = ExtensionValue('retroreflectionTexture')
    retroreflectionTextureMapping = ExtensionValue('retroreflectionTextureMapping')
    scatterStrengthTexture = ExtensionValue('scatterStrengthTexture')
    scatterStrengthTextureMapping = ExtensionValue('scatterStrengthTextureMapping')
    multiscatterColorTexture = ExtensionValue('multiscatterColorTexture')
    multiscatterColorTextureMapping = ExtensionValue('multiscatterColorTextureMapping')

    #: What a glTF document's `extras` said of the material; the glTF writer
    #: writes it back.
    extras: "dict[str, Any]"
    #: An `OGLC_hook` block: what an application was told to make of the surface.
    hook: "dict[str, Any]"

    def render(self, mode: Any = None) -> float:
        """Set the fixed-function material from the factors; the alpha it draws with

        The compatibility profile's pass calls this through `Appearance`, as
        it calls `Material.render`. The base colour is the diffuse and
        ambient colour, a metal's highlight takes the base colour and a
        dielectric's is a dim grey, roughness widens the highlight, and the
        emissive colour at its strength is the emission. Of the texture maps,
        only the base colour map
        is drawn by this pipeline, bound by `Appearance` through
        :meth:`legacyTexture`.
        """
        from OpenGL import GL  # noqa: PLC0415 GL only when the fixed-function pass draws
        alpha = 1.0 - float(self.transparency)
        if alpha <= 0.0:
            return 0.0
        base = np.asarray(self.baseColor, 'f')[:3]
        emission = np.asarray(self.emissiveColor, 'f')[:3] * float(self.emissiveStrength)
        metallic = min(max(float(self.metallic), 0.0), 1.0)
        roughness = min(max(float(self.roughness), 0.0), 1.0)
        # A metal has almost no diffuse term; a quarter is kept so that a
        # metal lit without an environment to reflect is still seen.
        diffuse = base * (1.0 - 0.75 * metallic)
        dielectric = np.full(3, DIELECTRIC_SPECULAR, 'f')
        specular = (dielectric + (base - dielectric) * metallic) * (1.0 - 0.5 * roughness)
        shininess = 128.0 * (1.0 - roughness) ** 2
        face = GL.GL_FRONT_AND_BACK
        GL.glMaterialfv(face, GL.GL_DIFFUSE, np.append(diffuse, alpha).astype('f'))
        GL.glMaterialfv(face, GL.GL_AMBIENT,
                        np.append(diffuse * AMBIENT_SHARE, alpha).astype('f'))
        GL.glMaterialfv(face, GL.GL_SPECULAR, np.append(specular, alpha).astype('f'))
        GL.glMaterialfv(face, GL.GL_EMISSION, np.append(emission, alpha).astype('f'))
        GL.glMaterialf(face, GL.GL_SHININESS, float(shininess))
        return alpha


#: The attenuation distance glTF's infinite default is held as: the
#: VolumeMaterialExtension field's default.
NO_ATTENUATION = 1000000.0

#: The reflectance of a surface that is not a metal, seen head on: what glTF's
#: metallic/roughness model gives every dielectric.
DIELECTRIC_SPECULAR = 0.04

#: How much of the diffuse colour the fixed-function ambient term is, as a VRML97
#: `Material`'s default `ambientIntensity`.
AMBIENT_SHARE = 0.2


def appearance_alpha(appearance: Any) -> "tuple[str, float]":
    """The alpha mode ('OPAQUE', 'MASK' or 'BLEND') and cutoff an appearance draws with

    An appearance's `alphaMode` says; `AUTO`, the default, blends a material
    with a `transparency` above 0 or a base colour texture with an alpha
    channel (X3D 4, 12.4.2). An appearance without the field (or none at all)
    is treated as `AUTO`.

    A transmission factor does not make a material blend: a transmissive
    surface is drawn by the transmission pass
    (`FlatPass.shaderRenderTransmissive`), which captures the opaque backdrop
    and draws it back to front.
    """
    mode = str(getattr(appearance, 'alphaMode', 'AUTO') or 'AUTO')
    cutoff = float(getattr(appearance, 'alphaCutoff', 0.5))
    if mode == 'AUTO':
        material = getattr(appearance, 'material', None)
        if isinstance(material, ChannelMaterial) and material.texture('baseColor') is not None:
            base = material.texture('baseColor')
        else:
            base = getattr(appearance, 'texture', None)
        has_alpha = getattr(base, 'hasAlpha', None)
        blends = (float(getattr(material, 'transparency', 0.0) or 0.0) > 0.0
                  or (callable(has_alpha) and has_alpha()))
        mode = 'BLEND' if blends else 'OPAQUE'
    return mode, cutoff


def appearance_is_transparent(appearance: Any) -> bool:
    """Whether an appearance sorts into the back-to-front blended pass"""
    return appearance_alpha(appearance)[0] == 'BLEND'


def uv_transform_matrix(offset: "tuple[float, float]" = (0.0, 0.0), rotation: float = 0.0,
                        scale: "tuple[float, float]" = (1.0, 1.0)) -> "list[list[float]]":
    """A 3x3 texture coordinate transform (KHR_texture_transform): T * R * S

    Row-major, for a GLSL mat3 (uploaded transposed).
    """
    import math  # noqa: PLC0415 kept with its one use
    # glTF defines the rotation counter-clockwise about the texture origin with
    # V pointing down (image top-left origin). Coordinates are sampled as
    # authored, so the rotation sense is inverted relative to the matrix the
    # extension gives; the angle is negated.
    c, s = math.cos(-rotation), math.sin(-rotation)
    sx, sy = scale
    ox, oy = offset
    return [
        [sx * c, sy * -s, ox],
        [sx * s, sy * c, oy],
        [0.0, 0.0, 1.0],
    ]


def srgb_to_linear(colour: Any) -> "tuple[float, float, float]":
    """A display-referred RGB colour as the linear light the PBR shader works in

    VRML97 colours are the numbers its lighting equation multiplies and the
    display shows, so they are encoded; the PBR program lights in linear space
    and encodes its result, which makes an unconverted 0.5 come out at 0.73.
    """
    out = []
    for value in tuple(colour)[:3]:
        value = min(max(float(value), 0.0), 1.0)
        out.append(value / 12.92 if value <= 0.04045
                   else ((value + 0.055) / 1.055) ** 2.4)
    return (out[0], out[1], out[2])


def material_to_pbr(material_node: Any) -> "dict[str, Any]":
    """A VRML97 Material as metallic/roughness factors

    Diffuse colour becomes the base colour, shininess becomes roughness
    (inverted), the emissive colour is carried across, and the colours are
    decoded from the display encoding VRML97 states them in
    (:func:`srgb_to_linear`).
    """
    # No node, NULL, or a node without material fields: the default grey.
    if material_node is None or not hasattr(material_node, 'diffuseColor'):
        return dict(base_color=srgb_to_linear((0.8, 0.8, 0.8)), metallic=0.0, roughness=0.6,
                    emissive=(0.0, 0.0, 0.0), occlusion=1.0, normal_scale=1.0,
                    transparency=0.0)
    from OpenGLContext.scenegraph.material_fields import read_material_fields  # noqa: PLC0415 material_fields imports the scenegraph
    f = read_material_fields(material_node)
    return dict(
        base_color=srgb_to_linear(f.diffuseColor),
        metallic=0.0,
        roughness=max(0.04, 1.0 - min(1.0, f.shininess)),
        emissive=srgb_to_linear(f.emissiveColor),
        occlusion=float(getattr(material_node, 'occlusionStrength', 1.0)),
        normal_scale=float(getattr(material_node, 'normalScale', 1.0)),
        transparency=f.transparency,
    )


#: The key an :class:`AppearanceMaterial` holds its current version under in
#: vrml's global cache, against its appearance.
_VIEW_VERSION_KEY = 'pbr-view-version'
#: The key :func:`pbr_material` keeps an appearance's view under in vrml's
#: global cache, against the appearance.
VIEW_KEY = 'pbr-view'


class BackFields(object):
    """A TwoSidedMaterial's `back...` fields under the names a Material gives them"""

    #: Each Material field name, to the TwoSidedMaterial field the back reads.
    NAMES: "dict[str, str]" = {
        'ambientIntensity': 'backAmbientIntensity', 'diffuseColor': 'backDiffuseColor',
        'emissiveColor': 'backEmissiveColor', 'shininess': 'backShininess',
        'specularColor': 'backSpecularColor', 'transparency': 'backTransparency',
    }

    def __init__(self, material: Any) -> None:
        self.source = material

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self.source, self.NAMES.get(name, name))


def side_material(appearance: Any, back: bool = False) -> Any:
    """The material `appearance`'s front or back faces are drawn with

    The back is `backMaterial` where there is one, a TwoSidedMaterial's back
    fields (:class:`BackFields`) where its `separateBackColor` is true, and
    otherwise the front's material.
    """
    material = getattr(appearance, 'material', None)
    if not back:
        return material
    found = getattr(appearance, 'backMaterial', None)
    if found:
        return found
    if isinstance(material, x3d.TwoSidedMaterial) and material.separateBackColor:
        return BackFields(material)
    return material


def two_sided(appearance: Any) -> bool:
    """Whether `appearance`'s back faces are drawn with a material of their own"""
    return side_material(appearance, back=True) is not side_material(appearance)


class AppearanceMaterial(object):
    """The metallic/roughness material a VRML97-style `Appearance` is drawn as

    The PBR program reads a material's maps from `textures` and its factors
    from a packed block. A VRML97 appearance keeps the same information in
    three nodes, and this reads it from them: `texture` is the base colour
    map and `material` gives the factors, converted by :func:`material_to_pbr`.
    The appearance's `textureTransform` is read by
    :mod:`~OpenGLContext.scenegraph.texturemapping` as for any appearance.

    :attr:`factorVersion` moves when a field any of those is read from is
    set, as :attr:`PhysicalMaterial.factorVersion` does. :func:`pbr_material`
    makes one per appearance and side, which it refers to weakly; the back's
    reads the back material (:func:`side_material`).
    """

    def __init__(self, appearance: Any, back: bool = False) -> None:
        self._appearance = weakref.ref(appearance)
        self._back = back
        self._version = 0
        self._x3d: Optional[bool] = None

    @property
    def appearance(self) -> Any:
        """The appearance this is the view of, or None once it is collected"""
        return self._appearance()

    @property
    def material(self) -> Any:
        """The appearance's `Material` for this side, or None"""
        return side_material(self.appearance, self._back)

    #: The channels an X3D 4 `Material` has maps for, and their fields.
    CHANNELS: "dict[str, str]" = {
        'baseColor': 'diffuseTexture', 'emissive': 'emissiveTexture',
        'normal': 'normalTexture', 'occlusion': 'occlusionTexture',
    }
    #: The maps only X3D's Phong equation reads, on the channels a Phong draw
    #: has no other use for: the ambient colour's (``.rgb``), the shininess
    #: (``.a``) and the specular colour's (``.rgb``).
    PHONG_CHANNELS: "dict[str, str]" = {
        'lightmap': 'ambientTexture', 'metallicRoughness': 'shininessTexture',
        'specularColor': 'specularTexture',
    }

    def channels(self) -> "dict[str, str]":
        """The texture field of each channel the appearance is drawn with:
        :data:`PHONG_CHANNELS` too where it is lit by X3D's rules"""
        if self.x3dLit:
            return dict(self.CHANNELS, **self.PHONG_CHANNELS)
        return self.CHANNELS

    @property
    def textures(self) -> "dict[str, Any]":
        """The maps by channel name, from the material's texture fields

        Without a `diffuseTexture`, the appearance's `texture` is the base
        colour map.
        """
        material = self.material
        found = {}
        for channel, name in self.channels().items():
            texture = getattr(material, name, None) if material else None
            if texture:
                found[channel] = texture
        if 'baseColor' not in found:
            texture = getattr(self.appearance, 'texture', None)
            if texture:
                found['baseColor'] = texture
        return found

    def textureMapping(self, channel: str) -> str:
        """The mapping label of `channel`'s map: the material's `...TextureMapping`"""
        material = self.material
        name = self.channels().get(channel)
        if not material or name is None or not getattr(material, name, None):
            return ''
        return str(getattr(material, name + 'Mapping', '') or '')

    @property
    def transparency(self) -> float:
        """The material's transparency: which pass the appearance sorts into"""
        return float(getattr(self.material, 'transparency', 0.0) or 0.0)

    @property
    def factorVersion(self) -> int:
        """A count that moves whenever a field this view reads from is set, or
        the rules the appearance is lit by change (:attr:`x3dLit`)"""
        appearance = self.appearance
        key = _VIEW_VERSION_KEY + ('-back' if self._back else '')
        if appearance is not None and cache.CACHE.getData(appearance, key) is None:
            self._version += 1
            self._watch(appearance, key)
        x3d = self.x3dLit
        if x3d != self._x3d:
            self._x3d = x3d
            self._version += 1
        return self._version

    @property
    def x3dLit(self) -> bool:
        """Whether the appearance is lit by X3D's rules (:mod:`OpenGLContext.lighting`):
        its Material by the Phong equation, and unlit where it has none"""
        return lighting.x3d_lit(self.appearance)

    @staticmethod
    def _watch(appearance: Any, key: str) -> None:
        """Hold a version against the fields of the nodes the view reads now"""
        holder = cache.CACHE.holder(appearance, True, key)
        for name in ('material', 'backMaterial', 'texture'):
            holder.depend(appearance, name)
        for material in (appearance.material, getattr(appearance, 'backMaterial', None)):
            if material:
                for source_field in protofunctions.getFields(material):
                    holder.depend(material, source_field)


#: Where :func:`pbr_material` keeps an appearance's :class:`AppearanceTextured`.
TEXTURED_VIEW_KEY = 'pbr-textured-view'


class AppearanceTextured(object):
    """A PhysicalMaterial or UnlitMaterial drawn with its appearance's `texture`

    X3D 4 (ISO/IEC 19775-1, 17.2.2.4 and 17.2.2.6): where the material's own
    base map (`baseTexture`, or an UnlitMaterial's `emissiveTexture`) is
    NULL, the appearance's `texture` is used in its place. This is the
    material with that map; every other field is read from the material
    (:attr:`material`). :func:`pbr_material` makes one per appearance.
    """

    def __init__(self, appearance: Any, back: bool = False) -> None:
        self._appearance = weakref.ref(appearance)
        self._back = back
        self._version = 0
        self._seen: Any = None

    @property
    def appearance(self) -> Any:
        """The appearance this is the view of, or None once it is collected"""
        return self._appearance()

    @property
    def material(self) -> Any:
        """The appearance's PhysicalMaterial or UnlitMaterial for this side"""
        return side_material(self.appearance, self._back)

    @property
    def textures(self) -> "dict[str, Any]":
        """The material's maps, with the appearance's texture as the base colour map"""
        found = dict(self.material.textures)
        texture = getattr(self.appearance, 'texture', None)
        if 'baseColor' not in found and texture:
            found['baseColor'] = texture
        return found

    def texture(self, channel: str) -> Any:
        """The texture node of `channel`, or None"""
        return self.textures.get(channel)

    def textureMapping(self, channel: str) -> str:
        """The mapping label of `channel`'s map; the appearance's texture has none"""
        if channel == 'baseColor' and self.material.texture('baseColor') is None:
            return ''
        found: str = self.material.textureMapping(channel)
        return found

    @property
    def factorVersion(self) -> int:
        """A count that moves when the material's factors or the appearance's texture do"""
        material = self.material
        seen = (material, getattr(material, 'factorVersion', 0),
                getattr(self.appearance, 'texture', None))
        if self._seen is None or any(
                was is not now and was != now for was, now in zip(self._seen, seen)):
            self._version += 1
            self._seen = seen
        return self._version

    def batchingVersion(self) -> int:
        """A value that changes whenever something deciding how this batches does"""
        return self.factorVersion

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self.material, name)


def source_of(material: Any) -> Any:
    """The PhysicalMaterial or UnlitMaterial a drawn material is, through any view of it"""
    if isinstance(material, AppearanceTextured):
        return material.material
    return material


def pbr_material(appearance: Any, back: bool = False) -> Any:
    """The material the PBR pass draws `appearance`'s front or back faces with

    None for no appearance. `back` asks for the back faces' material
    (:func:`side_material`); each side has its own view.

    A :class:`PhysicalMaterial` or `UnlitMaterial` carries its own maps and
    is drawn as itself, or, where its base map is NULL and the appearance has
    a `texture`, as its :class:`AppearanceTextured`, kept in vrml's cache
    under :data:`TEXTURED_VIEW_KEY`.
    Any other appearance (a VRML97 `Material` with its `texture` and
    `textureTransform` beside it, or no material) is drawn as its
    :class:`AppearanceMaterial`, one per appearance, kept in vrml's cache
    under :data:`VIEW_KEY` for as long as the appearance lives.
    """
    if appearance is None:
        return None
    material = side_material(appearance, back)
    side = '-back' if back else ''
    if isinstance(material, ChannelMaterial):
        if material.texture('baseColor') is not None or not getattr(appearance, 'texture', None):
            return material
        textured = cache.CACHE.getData(appearance, TEXTURED_VIEW_KEY + side)
        if textured is None:
            textured = AppearanceTextured(appearance, back)
            cache.CACHE.holder(appearance, textured, TEXTURED_VIEW_KEY + side)
        return textured
    view = cache.CACHE.getData(appearance, VIEW_KEY + side)
    if view is None:
        view = AppearanceMaterial(appearance, back)
        cache.CACHE.holder(appearance, view, VIEW_KEY + side)
    return view
