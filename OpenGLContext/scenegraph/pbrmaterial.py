"""Physically-based (metallic/roughness) material node, glTF 2.0 aligned.

A ``PBRMaterial`` drops into an ``Appearance.material`` slot just like a VRML97
``Material``; the PBR render pass renders it with a Cook-Torrance BRDF. Scalar
and colour factors are VRML fields; texture maps are held as light-weight
``PBRTexture`` holders in the ``textures`` dict (keyed by glTF channel name:
``baseColor``, ``metallicRoughness``, ``normal``, ``occlusion``, ``emissive``)
so PIL-backed images need not be squeezed into VRML field types.
"""
from typing import Any

from vrml import node, field


class PBRTexture(object):
    """A texture map for a PBR material, backed by a PIL image.

    Builds and caches a GL ``Texture`` per context on first use, so it works the
    same way the scenegraph's texture nodes do (``cached(mode)`` -> Texture).
    """

    def __init__(self, image: Any, srgb: bool = False, wrap_s: Any = None,
                 wrap_t: Any = None, min_filter: Any = None,
                 mag_filter: Any = None) -> None:
        self.image = image          # PIL.Image
        self.srgb = srgb            # base-color/emissive are sRGB, others linear
        # glTF sampler enums == GL enums, so they are applied directly.
        self.wrap_s = wrap_s
        self.wrap_t = wrap_t
        self.min_filter = min_filter
        self.mag_filter = mag_filter
        self._per_context: dict[int, Any] = {}      # id(context) -> Texture

    def cached(self, mode: Any) -> Any:
        ctx = getattr(mode, 'context', None)
        key = id(ctx)
        tex = self._per_context.get(key)
        if tex is None:
            from OpenGLContext import texture as texture_module
            tex = texture_module.Texture(image=self.image)
            self._apply_sampler(tex)
            self._per_context[key] = tex
        return tex

    def _apply_sampler(self, tex: Any) -> None:
        """Apply the glTF sampler's wrap modes and filters (+ mipmaps)."""
        from OpenGL.GL import (
            glBindTexture, glTexParameteri, glGenerateMipmap, GL_TEXTURE_2D,
            GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
            GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER,
            GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR,
        )
        glBindTexture(GL_TEXTURE_2D, tex.texture)
        if self.wrap_s:
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, int(self.wrap_s))
        if self.wrap_t:
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, int(self.wrap_t))
        try:
            glGenerateMipmap(GL_TEXTURE_2D)
            min_f = int(self.min_filter) if self.min_filter else GL_LINEAR_MIPMAP_LINEAR
        except Exception:
            min_f = GL_LINEAR
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, min_f)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER,
                        int(self.mag_filter) if self.mag_filter else GL_LINEAR)


class PBRMaterial(node.Node):
    """Metallic/roughness PBR material (glTF 2.0)."""
    PROTO = 'PBRMaterial'

    baseColor = field.newField('baseColor', 'SFColor', 1, (1.0, 1.0, 1.0))
    metallic = field.newField('metallic', 'SFFloat', 1, 1.0)
    roughness = field.newField('roughness', 'SFFloat', 1, 1.0)
    emissiveColor = field.newField('emissiveColor', 'SFColor', 1, (0.0, 0.0, 0.0))
    occlusionStrength = field.newField('occlusionStrength', 'SFFloat', 1, 1.0)
    normalScale = field.newField('normalScale', 'SFFloat', 1, 1.0)
    transparency = field.newField('transparency', 'SFFloat', 1, 0.0)
    alphaMode = field.newField('alphaMode', 'SFString', 1, 'OPAQUE')
    alphaCutoff = field.newField('alphaCutoff', 'SFFloat', 1, 0.5)
    doubleSided = field.newField('doubleSided', 'SFBool', 1, False)
    # KHR material extensions
    # Per-texture UV-set selector (KHR: each textureInfo has its own texCoord 0/1).
    # Bit per channel: 1=baseColor 2=metallicRoughness 4=normal 8=occlusion
    # 16=emissive; a set bit means "sample TEXCOORD_1 instead of TEXCOORD_0".
    texCoordMask = field.newField('texCoordMask', 'SFInt32', 1, 0)
    unlit = field.newField('unlit', 'SFBool', 1, False)               # KHR_materials_unlit
    emissiveStrength = field.newField('emissiveStrength', 'SFFloat', 1, 1.0)  # KHR_materials_emissive_strength
    specular = field.newField('specular', 'SFFloat', 1, 1.0)          # KHR_materials_specular factor
    specularColor = field.newField('specularColor', 'SFColor', 1, (1.0, 1.0, 1.0))
    clearcoat = field.newField('clearcoat', 'SFFloat', 1, 0.0)        # KHR_materials_clearcoat
    clearcoatRoughness = field.newField('clearcoatRoughness', 'SFFloat', 1, 0.0)
    sheenColor = field.newField('sheenColor', 'SFColor', 1, (0.0, 0.0, 0.0))  # KHR_materials_sheen
    sheenRoughness = field.newField('sheenRoughness', 'SFFloat', 1, 0.0)
    ior = field.newField('ior', 'SFFloat', 1, 1.5)                    # KHR_materials_ior
    # KHR_materials_transmission: fraction of light transmitted through the surface.
    transmission = field.newField('transmission', 'SFFloat', 1, 0.0)
    # KHR_materials_volume: attenuation of transmitted light through the medium.
    # attenuationDistance == 0.0 means "infinite" (no volume absorption); the
    # transmitted light is then tinted only by baseColor, per the glTF spec.
    thickness = field.newField('thickness', 'SFFloat', 1, 0.0)
    attenuationColor = field.newField('attenuationColor', 'SFColor', 1, (1.0, 1.0, 1.0))
    attenuationDistance = field.newField('attenuationDistance', 'SFFloat', 1, 0.0)
    # KHR_materials_diffuse_transmission: light passing through the surface and
    # diffusing (thin translucency -- leaves, wax, skin). Factor 0 = opaque.
    diffuseTransmission = field.newField('diffuseTransmission', 'SFFloat', 1, 0.0)
    diffuseTransmissionColor = field.newField(
        'diffuseTransmissionColor', 'SFColor', 1, (1.0, 1.0, 1.0))

    # KHR_materials_anisotropy: directional stretch of the specular lobe.
    anisotropyStrength = field.newField('anisotropyStrength', 'SFFloat', 1, 0.0)
    anisotropyRotation = field.newField('anisotropyRotation', 'SFFloat', 1, 0.0)

    # KHR_materials_dispersion: wavelength-dependent refraction (chromatic fringe).
    dispersion = field.newField('dispersion', 'SFFloat', 1, 0.0)

    # KHR_materials_iridescence: thin-film interference. Thickness in nanometres.
    iridescence = field.newField('iridescence', 'SFFloat', 1, 0.0)
    iridescenceIor = field.newField('iridescenceIor', 'SFFloat', 1, 1.3)
    iridescenceThicknessMin = field.newField('iridescenceThicknessMin', 'SFFloat', 1, 100.0)
    iridescenceThicknessMax = field.newField('iridescenceThicknessMax', 'SFFloat', 1, 400.0)

    # Fields whose in-place edit must invalidate the pbr pass's cached std140
    # block: the pass keys its cache on `_ubo_version`, and nothing
    # otherwise bumped it, so `material.roughness = 0.3` served a stale UBO.
    _UBO_FIELDS = frozenset({
        'baseColor', 'metallic', 'roughness', 'emissiveColor', 'occlusionStrength',
        'normalScale', 'transparency', 'alphaMode', 'alphaCutoff', 'doubleSided',
        'texCoordMask', 'unlit', 'emissiveStrength', 'specular', 'specularColor',
        'clearcoat', 'clearcoatRoughness', 'sheenColor', 'sheenRoughness', 'ior',
        'transmission', 'thickness', 'attenuationColor', 'attenuationDistance',
        'diffuseTransmission', 'diffuseTransmissionColor', 'anisotropyStrength',
        'anisotropyRotation', 'dispersion', 'iridescence', 'iridescenceIor',
        'iridescenceThicknessMin', 'iridescenceThicknessMax',
        'uv_transform', 'textures',
    })

    def __init__(self, **named: Any) -> None:
        textures = named.pop('textures', None)
        uv_transform = named.pop('uv_transform', None)
        super(PBRMaterial, self).__init__(**named)
        # plain attributes (not VRML fields) keyed by glTF channel name
        self.textures = dict(textures) if textures else {}
        # 3x3 row-major UV transform (KHR_texture_transform), or None for identity
        self.uv_transform = uv_transform

    def __setattr__(self, name: str, value: Any) -> None:
        super(PBRMaterial, self).__setattr__(name, value)
        if name in self._UBO_FIELDS:
            object.__setattr__(
                self, '_ubo_version',
                int(self.__dict__.get('_ubo_version', 0)) + 1)

    def texture(self, channel: str) -> Any:
        return self.textures.get(channel)


def material_is_transparent(material: Any) -> bool:
    """Whether a material sorts into the back-to-front blended transparent pass.

    True for an explicit ``BLEND`` alphaMode or, for a legacy material with no
    alphaMode, any non-zero ``transparency``. ``OPAQUE``/``MASK``
    stay opaque -- baseColor alpha is ignored in those modes per the glTF spec.

    A transmission factor is deliberately *not* treated as transparent here: a
    transmissive (glass) OPAQUE surface is routed through the dedicated
    transmission pass (``FlatPass.shaderRenderTransmissive`` /
    ``transmissiveRecords``), which pulls it from the opaque bucket, captures the
    opaque backdrop, and draws it back-to-front. Marking it transparent would take
    it out of the opaque bucket and lose that backdrop-refraction path.
    """
    if material is None:
        return False
    alpha_mode = getattr(material, 'alphaMode', None)
    if alpha_mode is not None:
        return alpha_mode == 'BLEND'
    return bool(getattr(material, 'transparency', 0.0))


def uv_transform_matrix(offset: tuple[float, float] = (0.0, 0.0), rotation: float = 0.0,
                        scale: tuple[float, float] = (1.0, 1.0)) -> list[list[float]]:
    """Build a 3x3 UV transform (KHR_texture_transform): uv' = uv * S * R * T.

    Returns a row-major 3x3 list suitable for a GLSL mat3 (uploaded transposed).
    """
    import math
    # glTF defines the rotation CCW about the texture origin with V pointing DOWN
    # (image top-left origin). We sample with the texcoords as authored, so the
    # rotation sense is inverted relative to the spec matrix; negate the angle so
    # the Rotation/All cells of TextureTransformTest land on "Correct" not "Error".
    c, s = math.cos(-rotation), math.sin(-rotation)
    sx, sy = scale
    ox, oy = offset
    # glTF: translation * rotation * scale, applied to (u, v, 1)
    return [
        [sx * c, sy * -s, ox],
        [sx * s, sy * c, oy],
        [0.0, 0.0, 1.0],
    ]


def material_to_pbr(material_node: Any) -> dict[str, Any]:
    """Up-convert a VRML97 Material to plausible metallic/roughness PBR inputs.

    Lets a PBR pass draw legacy materials through the single PBR program:
    diffuse -> baseColor, shininess -> roughness (inverted), specular folds into
    the dielectric response, emissive carried across. Returns a dict of factors.
    """
    # None, VRML's NullNode sentinel, or any node without material fields (a Shape
    # may carry geometry with no material) -> the default grey material. Keying on
    # the field rather than the type also covers appearance.material being unset.
    if material_node is None or not hasattr(material_node, 'diffuseColor'):
        return dict(base_color=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.6,
                    emissive=(0.0, 0.0, 0.0), occlusion=1.0, transparency=0.0)
    from OpenGLContext.scenegraph.material_fields import read_material_fields
    f = read_material_fields(material_node)   # shared raw read
    return dict(
        base_color=f.diffuseColor,
        metallic=0.0,
        roughness=max(0.04, 1.0 - min(1.0, f.shininess)),
        emissive=f.emissiveColor,
        occlusion=1.0,
        transparency=f.transparency,
    )
