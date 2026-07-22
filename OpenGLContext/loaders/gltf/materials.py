"""glTF material -> PBRMaterial construction, including the KHR extension stack.

Assembles a :class:`~OpenGLContext.scenegraph.pbrmaterial.PBRMaterial` from a glTF
material: base metallic/roughness factors and textures, then every supported KHR
material extension (specular, clearcoat, sheen, iridescence, transmission, volume,
anisotropy, ior, emissive strength, unlit, dispersion). The extensions are
table-driven -- one small handler per extension in ``_MATERIAL_EXT_HANDLERS`` reads
its factor block and registers its textures -- so :func:`_build_material` stays a
readable sequence rather than a wall of near-identical blocks.

``_TextureCollector`` accumulates a material's texture holders, its UV-set mask and
any shared ``KHR_texture_transform`` while the handlers run. The archived
spec/gloss workflow is converted to metallic/roughness in the sibling
:mod:`specular_glossiness` module; texture decoding lives in :mod:`textures`.
"""
from __future__ import annotations

from OpenGLContext.scenegraph.pbrmaterial import (
    PBRMaterial, PBRTexture, uv_transform_matrix,
)
from OpenGLContext.loaders.gltf.textures import _info, _texture_holder, _pil_for_texinfo
from OpenGLContext.loaders.gltf.specular_glossiness import (
    _specgloss_to_metalrough, _specgloss_textures_to_metalrough,
)


_ALPHA_MODE = {None: 'OPAQUE', 'OPAQUE': 'OPAQUE', 'MASK': 'MASK', 'BLEND': 'BLEND'}
# Per-channel bit for the material's texCoord mask (which textures sample UV set 1).
# Must match PBRMaterial.texCoordMask / the pbr.frag texCoordMask decode.
_TEXCOORD_BIT = {'baseColor': 1, 'metallicRoughness': 2, 'normal': 4,
                 'occlusion': 8, 'emissive': 16}


class _TextureCollector:
    """Accumulates a material's texture holders and KHR_texture_transform state.

    Replaces the closure-over-``[0]``-lists pattern that ``_build_material`` used:
    ``add()`` records a channel's texture holder, its UV set bit, and -- when the
    textureInfo carries KHR_texture_transform -- the shared transform matrix/params
    and the high ``texCoordMask`` bits that mark which channels it applies to.
    """

    def __init__(self, g, resolver, tex_cache):
        self._g = g
        self._resolver = resolver
        self._tex_cache = tex_cache
        self.textures = {}
        self.tex_coord_mask = 0
        self.uv_transform = None
        self.uv_params = None

    def add(self, channel, info, srgb):
        if info is None or getattr(info, 'index', None) is None:
            return
        holder = _texture_holder(self._g, info.index, self._resolver, srgb, self._tex_cache)
        if holder is None:
            return
        self.textures[channel] = holder
        tt = (getattr(info, 'extensions', None) or {}).get('KHR_texture_transform')
        # UV set: the texture's texCoord, unless KHR_texture_transform overrides it.
        tex_coord = int(getattr(info, 'texCoord', 0) or 0)
        if tt and tt.get('texCoord') is not None:
            tex_coord = int(tt.get('texCoord'))
        if tex_coord == 1:
            self.tex_coord_mask |= _TEXCOORD_BIT.get(channel, 0)
        if tt:
            self.uv_params = {
                'offset': list(tt.get('offset', [0, 0])),
                'rotation': float(tt.get('rotation', 0.0)),
                'scale': list(tt.get('scale', [1, 1]))}
            self.uv_transform = uv_transform_matrix(
                offset=tuple(self.uv_params['offset']),
                rotation=self.uv_params['rotation'],
                scale=tuple(self.uv_params['scale']))
            self.tex_coord_mask |= (_TEXCOORD_BIT.get(channel, 0) << 8)


# --- KHR material-extension handlers ----------------------------
# Each handler reads one extension's factor block into PBRMaterial kwargs and adds
# its textures via the collector; the table below drives them so _build_material
# no longer inlines ~15 near-identical blocks. Absent extensions fall back to
# _MATERIAL_EXT_DEFAULTS.

def _ext_unlit(ext, add):
    return {'unlit': True}


def _ext_emissive_strength(ext, add):
    return {'emissiveStrength': float(ext.get('emissiveStrength', 1.0))}


def _ext_ior(ext, add):
    return {'ior': float(ext.get('ior', 1.5))}


def _ext_dispersion(ext, add):
    return {'dispersion': float(ext.get('dispersion', 0.0))}


def _ext_specular(ext, add):
    add('specular', _info(ext.get('specularTexture')), srgb=False)          # .a
    add('specularColor', _info(ext.get('specularColorTexture')), srgb=True)  # .rgb
    return {'specular': float(ext.get('specularFactor', 1.0)),
            'specularColor': tuple(ext.get('specularColorFactor', [1, 1, 1]))}


def _ext_clearcoat(ext, add):
    add('clearcoat', _info(ext.get('clearcoatTexture')), srgb=False)
    add('clearcoatRoughness', _info(ext.get('clearcoatRoughnessTexture')), srgb=False)
    add('clearcoatNormal', _info(ext.get('clearcoatNormalTexture')), srgb=False)
    return {'clearcoat': float(ext.get('clearcoatFactor', 0.0)),
            'clearcoatRoughness': float(ext.get('clearcoatRoughnessFactor', 0.0))}


def _ext_sheen(ext, add):
    add('sheenColor', _info(ext.get('sheenColorTexture')), srgb=True)          # .rgb
    add('sheenRoughness', _info(ext.get('sheenRoughnessTexture')), srgb=False)  # .a
    return {'sheenColor': tuple(ext.get('sheenColorFactor', [0, 0, 0])),
            'sheenRoughness': float(ext.get('sheenRoughnessFactor', 0.0))}


def _ext_iridescence(ext, add):
    add('iridescence', _info(ext.get('iridescenceTexture')), srgb=False)
    add('iridescenceThickness', _info(ext.get('iridescenceThicknessTexture')), srgb=False)
    return {'iridescence': float(ext.get('iridescenceFactor', 0.0)),
            'iridescenceIor': float(ext.get('iridescenceIor', 1.3)),
            'iridescenceThicknessMin': float(ext.get('iridescenceThicknessMinimum', 100.0)),
            'iridescenceThicknessMax': float(ext.get('iridescenceThicknessMaximum', 400.0))}


def _ext_transmission(ext, add):
    add('transmission', _info(ext.get('transmissionTexture')), srgb=False)
    return {'transmission': float(ext.get('transmissionFactor', 0.0))}


def _ext_diffuse_transmission(ext, add):
    # Colour texture (.rgb, sRGB) tints transmitted light; factor texture (.a)
    # modulates the factor.
    add('diffuseTransmissionColor',
        _info(ext.get('diffuseTransmissionColorTexture')), srgb=True)
    add('diffuseTransmission',
        _info(ext.get('diffuseTransmissionTexture')), srgb=False)
    return {'diffuseTransmission': float(ext.get('diffuseTransmissionFactor', 0.0)),
            'diffuseTransmissionColor': tuple(
                ext.get('diffuseTransmissionColorFactor', [1.0, 1.0, 1.0]))[:3]}


def _ext_volume(ext, add):
    add('thickness', _info(ext.get('thicknessTexture')), srgb=False)
    ad = ext.get('attenuationDistance')
    # attenuationDistance defaults to +inf (no absorption); 0.0 is our sentinel.
    return {'thickness': float(ext.get('thicknessFactor', 0.0)),
            'attenuationColor': tuple(ext.get('attenuationColor', [1, 1, 1])),
            'attenuationDistance': float(ad) if ad is not None else 0.0}


def _ext_anisotropy(ext, add):
    add('anisotropy', _info(ext.get('anisotropyTexture')), srgb=False)
    return {'anisotropyStrength': float(ext.get('anisotropyStrength', 0.0)),
            'anisotropyRotation': float(ext.get('anisotropyRotation', 0.0))}


_MATERIAL_EXT_HANDLERS = {
    'KHR_materials_unlit': _ext_unlit,
    'KHR_materials_emissive_strength': _ext_emissive_strength,
    'KHR_materials_specular': _ext_specular,
    'KHR_materials_ior': _ext_ior,
    'KHR_materials_clearcoat': _ext_clearcoat,
    'KHR_materials_sheen': _ext_sheen,
    'KHR_materials_iridescence': _ext_iridescence,
    'KHR_materials_transmission': _ext_transmission,
    'KHR_materials_diffuse_transmission': _ext_diffuse_transmission,
    'KHR_materials_volume': _ext_volume,
    'KHR_materials_anisotropy': _ext_anisotropy,
    'KHR_materials_dispersion': _ext_dispersion,
}

_MATERIAL_EXT_DEFAULTS = dict(
    unlit=False, emissiveStrength=1.0, specular=1.0, specularColor=(1.0, 1.0, 1.0),
    ior=1.5, clearcoat=0.0, clearcoatRoughness=0.0, sheenColor=(0.0, 0.0, 0.0),
    sheenRoughness=0.0, iridescence=0.0, iridescenceIor=1.3,
    iridescenceThicknessMin=100.0, iridescenceThicknessMax=400.0,
    transmission=0.0, diffuseTransmission=0.0, diffuseTransmissionColor=(1.0, 1.0, 1.0),
    thickness=0.0, attenuationColor=(1.0, 1.0, 1.0), attenuationDistance=0.0,
    anisotropyStrength=0.0, anisotropyRotation=0.0, dispersion=0.0,
)


def _read_material_extensions(exts, add):
    """Merge every present KHR material extension into PBRMaterial kwargs (5d)."""
    kwargs = dict(_MATERIAL_EXT_DEFAULTS)
    for name, handler in _MATERIAL_EXT_HANDLERS.items():
        if name in exts:
            kwargs.update(handler(exts[name] or {}, add))
    return kwargs


def _build_material(g, material_index, resolver, tex_cache):
    if material_index is None:
        return PBRMaterial(baseColor=(0.8, 0.8, 0.8), metallic=0.0, roughness=0.7)
    mat = g.materials[material_index]
    pbr = mat.pbrMetallicRoughness
    base = list(pbr.baseColorFactor) if (pbr and pbr.baseColorFactor) else [1, 1, 1, 1]
    metallic = pbr.metallicFactor if (pbr and pbr.metallicFactor is not None) else 1.0
    roughness = pbr.roughnessFactor if (pbr and pbr.roughnessFactor is not None) else 1.0
    emissive = list(mat.emissiveFactor) if mat.emissiveFactor else [0, 0, 0]

    # Per-texture UV-set bit + KHR_texture_transform state accumulate on the
    # collector; ``add`` records a channel's holder.
    collector = _TextureCollector(g, resolver, tex_cache)
    add = collector.add
    textures = collector.textures

    exts = mat.extensions or {}

    # KHR_materials_pbrSpecularGlossiness: convert the legacy spec/gloss workflow
    # to an approximate metallic/roughness so it renders through the same shader.
    sg = exts.get('KHR_materials_pbrSpecularGlossiness')
    if sg:
        diffuse = sg.get('diffuseFactor', [1, 1, 1, 1])
        gloss = sg.get('glossinessFactor', 1.0)
        spec_rgb = sg.get('specularFactor', [1, 1, 1])
        base_rgb, metallic, roughness = _specgloss_to_metalrough(diffuse, spec_rgb, gloss)
        # keep the diffuse alpha; only RGB is remapped by the conversion
        base = list(base_rgb) + [diffuse[3] if len(diffuse) > 3 else 1.0]
        # Texture-driven spec/gloss carries its metalness in the spec/gloss image,
        # not the factors -- convert per pixel into baseColor + metallicRoughness
        # maps so it renders as metal. Factors then just pass the maps through.
        sgt = sg.get('specularGlossinessTexture')
        dift = sg.get('diffuseTexture')
        converted = False
        if sgt is not None:
            diffuse_pil = _pil_for_texinfo(g, _info(dift), resolver) if dift else None
            sg_pil = _pil_for_texinfo(g, _info(sgt), resolver)
            if sg_pil is not None:
                base_img, mr_img = _specgloss_textures_to_metalrough(
                    diffuse_pil, sg_pil, diffuse, spec_rgb + [1.0], gloss)
                textures['baseColor'] = PBRTexture(base_img, srgb=True)
                textures['metallicRoughness'] = PBRTexture(mr_img, srgb=False)
                base = [1.0, 1.0, 1.0, diffuse[3] if len(diffuse) > 3 else 1.0]
                metallic, roughness = 1.0, 1.0
                converted = True
        if not converted and 'diffuseTexture' in sg:
            add('baseColor', _info(sg['diffuseTexture']), srgb=True)

    if pbr:
        add('baseColor', pbr.baseColorTexture, srgb=True)
        add('metallicRoughness', pbr.metallicRoughnessTexture, srgb=False)
    add('normal', mat.normalTexture, srgb=False)
    add('occlusion', mat.occlusionTexture, srgb=False)
    add('emissive', mat.emissiveTexture, srgb=True)

    # KHR material extensions -> PBRMaterial kwargs, table-driven.
    ext_kwargs = _read_material_extensions(exts, add)

    # KHR_texture_transform is captured per texture by the collector (uv_transform
    # + the high texCoordMask bits mark which channels it applies to), so a
    # material that transforms only one map transforms just that channel.
    uv_transform = collector.uv_transform

    # Per the glTF spec, baseColor alpha only produces transparency in BLEND mode;
    # for OPAQUE/MASK the alpha is ignored (MASK is a shader-side cutoff, not a
    # blended-transparency pass), so an OPAQUE material must not be routed through
    # the transparent pass just because its baseColor alpha is < 1.
    alpha_mode = _ALPHA_MODE.get(mat.alphaMode, 'OPAQUE')
    base_alpha = base[3] if len(base) > 3 else 1.0
    transparency = float(1.0 - base_alpha) if alpha_mode == 'BLEND' else 0.0

    result = PBRMaterial(
        baseColor=tuple(base[:3]),
        metallic=float(metallic),
        roughness=float(roughness),
        emissiveColor=tuple(emissive[:3]),
        transparency=transparency,
        alphaMode=alpha_mode,
        alphaCutoff=float(mat.alphaCutoff if mat.alphaCutoff is not None else 0.5),
        doubleSided=bool(mat.doubleSided),
        normalScale=float(getattr(mat.normalTexture, 'scale', 1.0) or 1.0)
        if mat.normalTexture else 1.0,
        occlusionStrength=float(getattr(mat.occlusionTexture, 'strength', 1.0) or 1.0)
        if mat.occlusionTexture else 1.0,
        textures=collector.textures, uv_transform=uv_transform,
        texCoordMask=collector.tex_coord_mask,
        **ext_kwargs,   # KHR extension factors
    )
    result._uv_params = collector.uv_params   # for live KHR_animation_pointer UV edits
    result._tex_coord_mask = collector.tex_coord_mask
    return result
