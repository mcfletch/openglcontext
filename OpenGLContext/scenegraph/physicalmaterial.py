"""PhysicalMaterial: the engine's metallic/roughness material, which is X3D's

`PhysicalMaterial` is X3D 4's `PhysicalMaterial` with the glTF material
extensions (clearcoat, sheen, specular, transmission, volume, iridescence,
anisotropy, dispersion, diffuse transmission, emissive strength, ior) and the
engine's own fields (lightmap, baked light, octahedral impostors, planar
reflection) added in X3D's style. It goes in an `Appearance`'s `material`
slot, and the PBR pass draws it with a Cook-Torrance BRDF.

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

    @property
    def textures(self) -> "types.MappingProxyType[str, Any]":
        """The texture nodes by channel name, read from the texture fields"""
        found: "Optional[types.MappingProxyType[str, Any]]" = cache.CACHE.getData(
            self, _TEXTURES_KEY)
        if found is None:
            channels = {}
            holder = cache.CACHE.holder(self, None, _TEXTURES_KEY)
            for channel, name in self.CHANNELS.items():
                declared = protofunctions.getField(self, name)
                holder.depend(self, declared)
                value = declared.fget(self)
                if value:
                    channels[channel] = value
            found = holder.data = types.MappingProxyType(channels)
        return found

    def texture(self, channel: str) -> Any:
        """The texture node of `channel`, or None"""
        return self.textures.get(channel)

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


class PhysicalMaterial(ChannelMaterial, x3d.PhysicalMaterial):
    """X3D's PhysicalMaterial, with the glTF extensions and the engine's fields"""

    PROTO = 'PhysicalMaterial'

    # The glTF material extensions' factors.
    emissiveStrength = field.newField('emissiveStrength', 'SFFloat', 1, 1.0)
    specular = field.newField('specular', 'SFFloat', 1, 1.0)
    specularColor = field.newField('specularColor', 'SFColor', 1, (1.0, 1.0, 1.0))
    clearcoat = field.newField('clearcoat', 'SFFloat', 1, 0.0)
    clearcoatRoughness = field.newField('clearcoatRoughness', 'SFFloat', 1, 0.0)
    sheenColor = field.newField('sheenColor', 'SFColor', 1, (0.0, 0.0, 0.0))
    sheenRoughness = field.newField('sheenRoughness', 'SFFloat', 1, 0.0)
    ior = field.newField('ior', 'SFFloat', 1, 1.5)
    #: The fraction of light transmitted through the surface.
    transmission = field.newField('transmission', 'SFFloat', 1, 0.0)
    #: The volume's thickness and absorption. An `attenuationDistance` of 0 is
    #: no absorption: the transmitted light is tinted by `baseColor` alone.
    thickness = field.newField('thickness', 'SFFloat', 1, 0.0)
    attenuationColor = field.newField('attenuationColor', 'SFColor', 1, (1.0, 1.0, 1.0))
    attenuationDistance = field.newField('attenuationDistance', 'SFFloat', 1, 0.0)
    #: Light passing through and diffusing: leaves, wax, skin. 0 is opaque.
    diffuseTransmission = field.newField('diffuseTransmission', 'SFFloat', 1, 0.0)
    diffuseTransmissionColor = field.newField(
        'diffuseTransmissionColor', 'SFColor', 1, (1.0, 1.0, 1.0))
    #: The specular lobe's stretch, and its direction in radians.
    anisotropyStrength = field.newField('anisotropyStrength', 'SFFloat', 1, 0.0)
    anisotropyRotation = field.newField('anisotropyRotation', 'SFFloat', 1, 0.0)
    #: Wavelength-dependent refraction.
    dispersion = field.newField('dispersion', 'SFFloat', 1, 0.0)
    #: Thin-film interference; thickness in nanometres.
    iridescence = field.newField('iridescence', 'SFFloat', 1, 0.0)
    iridescenceIor = field.newField('iridescenceIor', 'SFFloat', 1, 1.3)
    iridescenceThicknessMin = field.newField('iridescenceThicknessMin', 'SFFloat', 1, 100.0)
    iridescenceThicknessMax = field.newField('iridescenceThicknessMax', 'SFFloat', 1, 400.0)

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

    # The extension and engine channels, in the pattern of X3D's baseTexture
    # and baseTextureMapping.
    lightmapTexture = _texture_field('lightmapTexture')
    lightmapTextureMapping = _mapping_field('lightmapTexture')
    transmissionTexture = _texture_field('transmissionTexture')
    transmissionTextureMapping = _mapping_field('transmissionTexture')
    iridescenceTexture = _texture_field('iridescenceTexture')
    iridescenceTextureMapping = _mapping_field('iridescenceTexture')
    iridescenceThicknessTexture = _texture_field('iridescenceThicknessTexture')
    iridescenceThicknessTextureMapping = _mapping_field('iridescenceThicknessTexture')
    clearcoatTexture = _texture_field('clearcoatTexture')
    clearcoatTextureMapping = _mapping_field('clearcoatTexture')
    clearcoatRoughnessTexture = _texture_field('clearcoatRoughnessTexture')
    clearcoatRoughnessTextureMapping = _mapping_field('clearcoatRoughnessTexture')
    clearcoatNormalTexture = _texture_field('clearcoatNormalTexture')
    clearcoatNormalTextureMapping = _mapping_field('clearcoatNormalTexture')
    thicknessTexture = _texture_field('thicknessTexture')
    thicknessTextureMapping = _mapping_field('thicknessTexture')
    anisotropyTexture = _texture_field('anisotropyTexture')
    anisotropyTextureMapping = _mapping_field('anisotropyTexture')
    specularTexture = _texture_field('specularTexture')
    specularTextureMapping = _mapping_field('specularTexture')
    specularColorTexture = _texture_field('specularColorTexture')
    specularColorTextureMapping = _mapping_field('specularColorTexture')
    sheenColorTexture = _texture_field('sheenColorTexture')
    sheenColorTextureMapping = _mapping_field('sheenColorTexture')
    sheenRoughnessTexture = _texture_field('sheenRoughnessTexture')
    sheenRoughnessTextureMapping = _mapping_field('sheenRoughnessTexture')
    diffuseTransmissionTexture = _texture_field('diffuseTransmissionTexture')
    diffuseTransmissionTextureMapping = _mapping_field('diffuseTransmissionTexture')
    diffuseTransmissionColorTexture = _texture_field('diffuseTransmissionColorTexture')
    diffuseTransmissionColorTextureMapping = _mapping_field('diffuseTransmissionColorTexture')

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
        if isinstance(material, ChannelMaterial):
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
                    emissive=(0.0, 0.0, 0.0), occlusion=1.0, transparency=0.0)
    from OpenGLContext.scenegraph.material_fields import read_material_fields  # noqa: PLC0415 material_fields imports the scenegraph
    f = read_material_fields(material_node)
    return dict(
        base_color=srgb_to_linear(f.diffuseColor),
        metallic=0.0,
        roughness=max(0.04, 1.0 - min(1.0, f.shininess)),
        emissive=srgb_to_linear(f.emissiveColor),
        occlusion=1.0,
        transparency=f.transparency,
    )


#: The key an :class:`AppearanceMaterial` holds its current version under in
#: vrml's global cache, against its appearance.
_VIEW_VERSION_KEY = 'pbr-view-version'
#: The key :func:`pbr_material` keeps an appearance's view under in vrml's
#: global cache, against the appearance.
VIEW_KEY = 'pbr-view'


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
    makes one per appearance, which it refers to weakly.
    """

    def __init__(self, appearance: Any) -> None:
        self._appearance = weakref.ref(appearance)
        self._version = 0

    @property
    def appearance(self) -> Any:
        """The appearance this is the view of, or None once it is collected"""
        return self._appearance()

    @property
    def material(self) -> Any:
        """The appearance's `Material`, or None"""
        return getattr(self.appearance, 'material', None)

    @property
    def textures(self) -> "dict[str, Any]":
        """The maps by channel name: the appearance's texture as the base colour"""
        texture = getattr(self.appearance, 'texture', None)
        return {'baseColor': texture} if texture else {}

    @property
    def transparency(self) -> float:
        """The material's transparency: which pass the appearance sorts into"""
        return float(getattr(self.material, 'transparency', 0.0) or 0.0)

    @property
    def factorVersion(self) -> int:
        """A count that moves whenever a field this view reads from is set"""
        appearance = self.appearance
        if appearance is not None and cache.CACHE.getData(appearance, _VIEW_VERSION_KEY) is None:
            self._version += 1
            self._watch(appearance)
        return self._version

    @staticmethod
    def _watch(appearance: Any) -> None:
        """Hold a version against the fields of the nodes the view reads now"""
        holder = cache.CACHE.holder(appearance, True, _VIEW_VERSION_KEY)
        for name in ('material', 'texture'):
            holder.depend(appearance, name)
        if appearance.material:
            for source_field in protofunctions.getFields(appearance.material):
                holder.depend(appearance.material, source_field)


def pbr_material(appearance: Any) -> Any:
    """The material the PBR pass draws `appearance` with; None for no appearance

    A :class:`PhysicalMaterial` or `UnlitMaterial` carries its own maps and
    is drawn as itself.
    Any other appearance (a VRML97 `Material` with its `texture` and
    `textureTransform` beside it, or no material) is drawn as its
    :class:`AppearanceMaterial`, one per appearance, kept in vrml's cache
    under :data:`VIEW_KEY` for as long as the appearance lives.
    """
    if appearance is None:
        return None
    material = getattr(appearance, 'material', None)
    if isinstance(material, ChannelMaterial):
        return material
    view = cache.CACHE.getData(appearance, VIEW_KEY)
    if view is None:
        view = AppearanceMaterial(appearance)
        cache.CACHE.holder(appearance, view, VIEW_KEY)
    return view
