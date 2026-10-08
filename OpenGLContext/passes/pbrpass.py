"""Physically-based render pass and shader program.

``PBRPass`` is a :class:`flatcore.FlatPass` subclass whose ``shader_program`` is a
:class:`PBRShaderProgram` rendering a Cook-Torrance metallic/roughness BRDF. It
inherits the shadow subsystem (shadows on by default) and the whole render flow;
only the bound program and per-shape material configuration differ.

Both ``PhysicalMaterial`` nodes and legacy VRML97 ``Material`` nodes render through the
single PBR program -- the latter via up-conversion -- so existing scenes draw
under the PBR pass without per-shape program switches.
"""
from __future__ import annotations

import logging
import weakref
from types import MappingProxyType
from collections.abc import Iterator, Mapping, Sequence
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGL.GL import (
    GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_TEXTURE0, GL_TEXTURE_2D,
    GL_UNIFORM_BUFFER, GL_STATIC_DRAW, GL_DYNAMIC_DRAW, GL_INVALID_INDEX,
    GL_MAX_TEXTURE_IMAGE_UNITS, GL_FALSE,
    glUseProgram, glActiveTexture, glBindTexture, glGetIntegerv,
    glGenBuffers, glBindBuffer, glBufferData, glBindBufferBase, glDeleteBuffers,
    glGetUniformBlockIndex, glUniformBlockBinding, glUniformMatrix4fv,
    glUniform1fv, glUniform1iv, glUniform4fv,
)
from OpenGL.GL import shaders as GL_shaders
from vrml import cache

from OpenGLContext import contextresources, renderoptions
from OpenGLContext.passes import flatcore
from OpenGLContext.passes.instancing import instance_collapse_is_enabled
from OpenGLContext.passes.shaderpass import (
    VRML97ShaderProgram, link_program, load_fragment_source, resolve_shadow_config,
    preprocess_shader,
)
from OpenGLContext.passes.transmission import TransmissionBuffer
from OpenGLContext.passes import reflection
from OpenGLContext.passes.reflection import REFLECTION_UNIT, REFLECTION_UNITS_NEEDED
from OpenGLContext.scenegraph.physicalmaterial import (
    AppearanceMaterial, ChannelMaterial, PhysicalMaterial, appearance_alpha, source_of,
    two_sided,
    material_to_pbr, pbr_material,
)
from OpenGLContext.scenegraph.material_fields import read_material_fields
from OpenGLContext.scenegraph.texgen import TexGen
from OpenGLContext.scenegraph.texturemapping import TextureMapping, texture_mapping
from OpenGLContext.scenegraph.unlitmaterial import UnlitMaterial
from OpenGLContext import lighting
from OpenGLContext.passes.ibl import IBL_UNITS, _IBL_SAMPLER
from OpenGLContext.passes.zonelayers import MAX_ZONE_LAYERS, ZonePack
from OpenGLContext.scenegraph.skinning import SKIN_PALETTE_UNIT, palette_supported
from OpenGLContext.scenegraph.winding import apply_winding_cull

if TYPE_CHECKING:
    from OpenGLContext.passes.instancing import Batchers

log = logging.getLogger(__name__)

# Sentinel distinct from any real material (including None) so the first shape of
# each frame always reconfigures.
_APPEARANCE_UNSET = object()


class _NoMaterial:
    """The owner of the block drawn for a shape with no material"""


_NO_MATERIAL = _NoMaterial()

#: What a shape with no appearance is drawn with under X3D's rules: unlit white.
_DOCUMENT_UNLIT = UnlitMaterial(emissiveColor=(1.0, 1.0, 1.0))

#: Each material's factor block in each context, as ``{'block': (buffer,
#: version)}``: deleted when the material is collected or the context is lost.
_MATERIAL_BLOCKS = contextresources.ContextNames(
    '_materialBlocks',
    lambda name: glDeleteBuffers(1, np.array([name], dtype=np.uint32)),
    names=lambda entry: (entry[0],))

# Fragment texture-unit budget. GL 3.3 core only guarantees 16 units
# (valid indices 0..15), so every sampler the PBR program uses must fit under 16.
# The shared shadow samplers occupy 4-5 (spot/CSM array + raw view) and 6..6+N-1
# (point-light cubes: one unit for the packed cube-array, up to MAX_SHADOW_LIGHTS
# for the per-slot fallback). That leaves units 0-3 and 10-15 free on every path.
# The PBR-specific samplers are packed into those: material maps below/above the
# shadow block, then transmission + the three IBL probes. Max index stays at 15.
#
# The lightmap takes unit 0 -- the conventional scratch/bind unit -- because every
# other index inside the guaranteed 16 is spoken for and a baked-lighting workflow
# must work on min-spec hardware, not only where the extension budget applies.
# Nothing binds to unit 0 between bind_pbr_textures and the draw, and a material
# without a lightmap clears hasLightmap, so a stray bind there is never sampled.
PBR_UNITS = {
    'baseColor': 1, 'metallicRoughness': 2, 'normal': 3,
    'occlusion': 10, 'emissive': 11, 'lightmap': 0,
}
# IBL probe samplers (transmission is 12). Assigned to distinct units even when
# IBL is analytic/off: the PBR program has both samplerCube and sampler2D uniforms,
# and leaving them at the default unit 0 collides with the 2D material samplers,
# which the driver rejects at draw time (same reason the shadow samplers are
# pre-assigned).
_PBR_SAMPLER = {
    'baseColor': 'baseColorTexture', 'metallicRoughness': 'metallicRoughnessTexture',
    'normal': 'normalTexture', 'occlusion': 'occlusionTexture',
    'emissive': 'emissiveTexture', 'lightmap': 'lightmapTexture',
}
# The shader's name for each map's bit of ``materialTextures``.
_PBR_HAS = {
    'baseColor': 'hasBaseColor', 'metallicRoughness': 'hasMetallicRoughness',
    'normal': 'hasNormal', 'occlusion': 'hasOcclusion', 'emissive': 'hasEmissive',
    'lightmap': 'hasLightmap',
}

# --- Extension material textures, gated by the sampler budget ------------------
# The core material maps + shadows + transmission backdrop + IBL probes fill units
# 0..15 -- the GL 3.3 core *guaranteed* minimum (and what llvmpipe exposes). Any
# extra KHR-extension texture therefore only fits on hardware that reports more
# than 16 fragment samplers (GL_MAX_TEXTURE_IMAGE_UNITS). These are assigned units
# 16+ and are enabled only when the budget allows; on min-spec they are compiled
# out (PBR_EXT_TEXTURES=0) so the shader still fits 16 units.
PBR_EXT_UNITS = {
    'transmission': 16,          # KHR_materials_transmission transmissionTexture (.r)
    'iridescenceThickness': 17,  # KHR_materials_iridescence thickness (.g -> min..max)
    'clearcoat': 18,             # KHR_materials_clearcoat clearcoatTexture (.r)
    'clearcoatRoughness': 19,    # clearcoatRoughnessTexture (.g)
    'thickness': 20,             # KHR_materials_volume thicknessTexture (.g)
    'anisotropy': 21,            # KHR_materials_anisotropy (.rg dir, .b strength)
    'specular': 22,              # KHR_materials_specular specularTexture (.a)
    'specularColor': 23,         # KHR_materials_specular specularColorTexture (.rgb)
    'sheenColor': 24,            # KHR_materials_sheen sheenColorTexture (.rgb)
    'sheenRoughness': 25,        # KHR_materials_sheen sheenRoughnessTexture (.a)
    'iridescence': 26,           # KHR_materials_iridescence iridescenceTexture (.r)
    'clearcoatNormal': 27,       # KHR_materials_clearcoat clearcoatNormalTexture
    'diffuseTransmissionColor': 28,  # KHR_materials_diffuse_transmission colour (.rgb)
    'diffuseTransmission': 29,   # KHR_materials_diffuse_transmission factor (.a)
}
_PBR_EXT_SAMPLER = {
    'transmission': 'transmissionMap', 'iridescenceThickness': 'iridescenceThicknessMap',
    'clearcoat': 'clearcoatMap', 'clearcoatRoughness': 'clearcoatRoughnessMap',
    'thickness': 'thicknessMap', 'anisotropy': 'anisotropyMap',
    'specular': 'specularMap', 'specularColor': 'specularColorMap',
    'sheenColor': 'sheenColorMap', 'sheenRoughness': 'sheenRoughnessMap',
    'iridescence': 'iridescenceMap', 'clearcoatNormal': 'clearcoatNormalMap',
    'diffuseTransmissionColor': 'diffuseTransmissionColorMap',
    'diffuseTransmission': 'diffuseTransmissionMap',
}
_PBR_EXT_HAS = {
    'transmission': 'hasTransmissionMap',
    'iridescenceThickness': 'hasIridescenceThicknessMap',
    'clearcoat': 'hasClearcoatMap', 'clearcoatRoughness': 'hasClearcoatRoughnessMap',
    'thickness': 'hasThicknessMap', 'anisotropy': 'hasAnisotropyMap',
    'specular': 'hasSpecularMap', 'specularColor': 'hasSpecularColorMap',
    'sheenColor': 'hasSheenColorMap', 'sheenRoughness': 'hasSheenRoughnessMap',
    'iridescence': 'hasIridescenceMap', 'clearcoatNormal': 'hasClearcoatNormalMap',
    'diffuseTransmissionColor': 'hasDiffuseTransmissionColorMap',
    'diffuseTransmission': 'hasDiffuseTransmissionMap',
}

#: The bit of the shader's ``materialTextures`` mask that says a map is
#: sampled. The core maps take the bits ``uvFor`` in pbr.frag numbers them by,
#: and the extension maps follow in the order of :data:`PBR_EXT_UNITS`.
PBR_TEXTURE_BITS = {channel: 1 << index for index, channel in
                    enumerate(list(PBR_UNITS) + list(PBR_EXT_UNITS))}

# Highest unit any extension texture wants; the program needs a budget past it.
_EXT_UNITS_MAX = max(PBR_EXT_UNITS.values()) if PBR_EXT_UNITS else 15


def ext_texture_channels(budget: int) -> dict:
    """Extension texture channels that fit in ``budget`` fragment sampler units.

    A channel at unit U is available iff ``U < budget``. On a 16-unit min-spec GPU
    (or llvmpipe) this is empty, so no extension texture is bound or sampled.
    """
    return {c: u for c, u in PBR_EXT_UNITS.items() if u < budget}


def ext_textures_supported(budget: int) -> bool:
    """Whether the sampler budget admits any extension texture at all."""
    return budget > _EXT_UNITS_MAX

# --- MaterialBlock std140 UBO ------------------------------------------------
# The per-material factor block in pbr.frag is a std140 uniform block uploaded
# once per material, so a shape switches materials with a single buffer bind
# instead of ~20 glUniform calls. The word layout below MUST match the block
# declaration in shaders/pbr.frag (validated against the driver in tests).
# 4-byte words; vec3+float pairs share a 16-byte slot in std140. The base factors
# + a reserved mat3 + the iridescence vec4 and later KHR extension factors total
# 56 words / 224 bytes.
MATERIAL_BLOCK_WORDS = 56   # 224 B; must match the Material struct in pbr.frag
MATERIAL_UBO_BINDING = 1        # glUniformBlockBinding / glBindBufferBase point

def _upload_codes(location: int, codes: "tuple[int, ...]") -> None:
    glUniform1iv(location, len(codes), np.asarray(codes, np.int32))


def _upload_rows(location: int, rows: "tuple[float, ...]") -> None:
    glUniform4fv(location, len(rows) // 4, np.asarray(rows, np.float32))


#: The shader's code for each alpha mode.
_ALPHA_MODES = {'OPAQUE': 0, 'MASK': 1, 'BLEND': 2}

# Opacity floor for the cheap (no-backdrop) transmission fallback, so fully
# transmissive glass still shows specular highlights instead of vanishing.
GLASS_MIN_OPACITY = 0.08


#: The factors of a material that sets none of the extensions' fields.
_DEFAULT_FACTORS: "dict[str, Any]" = dict(
    base_color=(1.0, 1.0, 1.0), metallic=0.0, roughness=1.0, emissive=(0.0, 0.0, 0.0),
    occlusion=1.0, normal_scale=1.0, unlit=0, emissive_strength=1.0, specular=1.0,
    specular_color=(1.0, 1.0, 1.0), clearcoat=0.0, clearcoat_roughness=0.0,
    sheen_color=(0.0, 0.0, 0.0), sheen_roughness=0.0, ior=1.5, thickness=0.0,
    attenuation_color=(1.0, 1.0, 1.0), attenuation_distance=0.0,
    flags=0,
    iridescence=0.0, iridescence_ior=1.3,
    iridescence_thick_min=100.0, iridescence_thick_max=400.0,
    anisotropy_strength=0.0, anisotropy_rotation=0.0, dispersion=0.0,
    diffuse_transmission=0.0, diffuse_transmission_color=(1.0, 1.0, 1.0),
    phong_ambient=0.0, phong_shininess=0.0,
)


def phong_factors(material_node: Any) -> dict:
    """The block of an X3D Material drawn by X3D's Phong equation (:data:`PHONG_BIT`)

    The colours are the Material's own, not decoded to linear light, and its
    ``ambientIntensity`` and ``shininess`` have words of their own.
    """
    f = read_material_fields(material_node)
    return dict(_DEFAULT_FACTORS, base_color=tuple(f.diffuseColor)[:3],
                emissive=tuple(f.emissiveColor)[:3],
                specular_color=tuple(f.specularColor)[:3],
                phong_ambient=float(f.ambientIntensity), phong_shininess=float(f.shininess),
                flags=PHONG_BIT)


def _material_factors(material: Any) -> dict:
    """Uniform-ready factors for a PhysicalMaterial, an UnlitMaterial, a VRML97 Material, or None"""
    material = source_of(material)
    if isinstance(material, PhysicalMaterial):
        m = material
        return dict(
            _DEFAULT_FACTORS,
            base_color=tuple(m.baseColor)[:3], metallic=float(m.metallic),
            roughness=float(m.roughness), emissive=tuple(m.emissiveColor)[:3],
            occlusion=float(m.occlusionStrength), normal_scale=float(m.normalScale),
            emissive_strength=float(m.emissiveStrength), specular=float(m.specular),
            specular_color=tuple(m.specularColor)[:3], clearcoat=float(m.clearcoat),
            clearcoat_roughness=float(m.clearcoatRoughness),
            sheen_color=tuple(m.sheenColor)[:3], sheen_roughness=float(m.sheenRoughness),
            ior=float(m.ior), thickness=float(m.thickness),
            attenuation_color=tuple(m.attenuationColor)[:3],
            attenuation_distance=float(m.attenuationDistance),
            flags=BAKED_LIGHT_BIT if m.bakedLight else 0,
            iridescence=float(m.iridescence), iridescence_ior=float(m.iridescenceIor),
            iridescence_thick_min=float(m.iridescenceThicknessMin),
            iridescence_thick_max=float(m.iridescenceThicknessMax),
            anisotropy_strength=float(m.anisotropyStrength),
            anisotropy_rotation=float(m.anisotropyRotation),
            dispersion=float(m.dispersion),
            diffuse_transmission=float(m.diffuseTransmission),
            diffuse_transmission_color=tuple(m.diffuseTransmissionColor)[:3],
        )
    if isinstance(material, UnlitMaterial):
        # The unlit path draws the base colour; X3D calls it the emissive colour.
        return dict(_DEFAULT_FACTORS, base_color=tuple(material.emissiveColor)[:3],
                    normal_scale=float(material.normalScale), unlit=1)
    if isinstance(material, AppearanceMaterial):
        if material.x3dLit:
            if not material.material:
                # X3D: an appearance with no material is unlit, white times its texture
                return dict(_DEFAULT_FACTORS, unlit=1)
            if hasattr(material.material, 'diffuseColor'):
                return phong_factors(material.material)
        material = material.material
    f = material_to_pbr(material)      # None / VRML97 Material -> plausible defaults
    return dict(
        _DEFAULT_FACTORS,
        base_color=f['base_color'], metallic=f['metallic'], roughness=f['roughness'],
        emissive=f['emissive'], occlusion=f['occlusion'], normal_scale=f['normal_scale'],
    )


# Optional PBR lobes that can be compiled out of the uber-shader (the USE_* guards
# in pbr.frag). Each costs register/uniform footprint on every draw even behind a
# coherent uniform branch.
PBR_OPTIONAL_FEATURES = ('CLEARCOAT', 'SHEEN', 'TRANSMISSION')


def pbr_feature_defines(enabled: Optional[Any] = None) -> list:
    """USE_* defines choosing which optional lobes the PBR uber-shader includes.

    FUTURE FEATURE -- not wired into compile() yet. Today the program is always
    built with every lobe ON (see the USE_* fallbacks in pbr.frag), so the whole
    scene keeps using one shader.

    The intended use is a *per-platform / per-settings* decision made ONCE, at
    program-compile time -- NOT per material. A constrained profile (say low-end
    integrated graphics) could drop transmission + clearcoat to shrink the
    uber-shader's register footprint for the entire scene, trading feature support
    for occupancy. Because the choice is global, the scene still binds a single
    program: this never causes per-material shader swapping.

    ``enabled`` is an iterable of names from PBR_OPTIONAL_FEATURES to keep; ``None``
    keeps them all (the default program). Feed the result in at compile time::

        preprocess_shader('pbr.frag', shadow_defines(...) + pbr_feature_defines(cfg))
    """
    keep = set(PBR_OPTIONAL_FEATURES if enabled is None else enabled)
    return ['#define USE_%s %d' % (f, 1 if f in keep else 0)
            for f in PBR_OPTIONAL_FEATURES]


#: The bit of the block's flags word saying the vertex colours are baked light
#: rather than a tint; the fragment shader reads it as ``bakedLightMode``.
BAKED_LIGHT_BIT = 64
#: The bit saying the block is an X3D Material drawn by X3D's Phong equation
#: (:func:`phong_factors`); the fragment shader reads it as ``phongMode``.
PHONG_BIT = 128



#: The key a material's packed block is kept under in vrml's cache, with the
#: ``factorVersion`` and the :data:`_repacks` generation it was packed at.
MATERIAL_BLOCK_KEY = 'material-block'

#: Moved by ``invalidate_material_ubo()`` to have every block packed again.
_repacks = 0


def pack_material_block(material: Any) -> np.ndarray:
    """Pack a material into the std140 MaterialBlock byte layout (float32 array).

    Kept in vrml's cache against the material, its ``factorVersion`` (the
    count every runtime material edit moves) and the generation
    ``invalidate_material_ubo()`` moves: an instanced group repacks its whole
    material table every frame, and a crowd of figures out of one document
    carries a material apiece that nothing is changing. None, the neutral grey
    of a shape with no material, is packed each time.
    """
    if material is None:
        return _pack_material_block(None)
    version = (int(getattr(material, 'factorVersion', 0)), _repacks)
    cached = cache.CACHE.getData(material, MATERIAL_BLOCK_KEY)
    if cached is not None and cached[0] == version:
        return np.asarray(cached[1])
    packed = _pack_material_block(material)
    cache.CACHE.holder(material, (version, packed), MATERIAL_BLOCK_KEY)
    return packed


def _pack_material_block(material: Any) -> np.ndarray:
    d = _material_factors(material)
    buf = np.zeros(MATERIAL_BLOCK_WORDS, dtype=np.float32)
    iv = buf.view(np.int32)
    buf[0:3] = d['base_color']
    buf[3] = d['metallic']
    buf[4:7] = d['emissive']
    buf[7] = d['roughness']
    buf[8:11] = d['specular_color']
    buf[11] = d['occlusion']
    buf[12:15] = d['sheen_color']
    buf[15] = d['normal_scale']
    buf[16:19] = d['attenuation_color']
    # word 19 is reserved: the alpha cutoff is the appearance's, set per draw.
    buf[20] = d['emissive_strength']
    buf[21] = d['specular']
    buf[22] = d['clearcoat']
    buf[23] = d['clearcoat_roughness']
    buf[24] = d['sheen_roughness']
    buf[25] = d['ior']
    buf[26] = d['thickness']
    buf[27] = d['attenuation_distance']
    iv[28] = 1 if d['unlit'] else 0
    iv[29] = int(d.get('flags', 0))
    # words 30, 31 are the std140 padding before the 16-byte-aligned mat3 -- reuse
    # them for two per-instance scalars (anisotropy strength + dispersion) for free.
    buf[30] = d.get('anisotropy_strength', 0.0)
    buf[31] = d.get('dispersion', 0.0)
    # X3D's Phong at words 32..33 (of the 32..35 vec4); 36..43 are unused
    buf[32] = d['phong_ambient']
    buf[33] = d['phong_shininess']
    # iridescence vec4 (factor, ior, thicknessMin, thicknessMax) at words 44..47
    buf[44] = d.get('iridescence', 0.0)
    buf[45] = d.get('iridescence_ior', 1.3)
    buf[46] = d.get('iridescence_thick_min', 100.0)
    buf[47] = d.get('iridescence_thick_max', 400.0)
    # diffuse-transmission vec4 (rgb colour, a factor) at 48..51
    dtc = d.get('diffuse_transmission_color', (1.0, 1.0, 1.0))
    buf[48:51] = dtc
    buf[51] = d.get('diffuse_transmission', 0.0)
    # anisotropy direction (cos, sin) at 52..53 (of the 52..55 vec4)
    import math
    rot = float(d.get('anisotropy_rotation', 0.0))
    buf[52] = math.cos(rot)
    buf[53] = math.sin(rot)
    return buf


def _compile_file(vert_name: str, frag_name: str, validate: bool = True,
                  vertex_defines: Optional[list] = None) -> Any:
    # preprocess_shader resolves the shared #includes: the auxiliary
    # VRML97 shaders the PBR pass reuses (unlit/point/line/vertex_color) now pull
    # encodeObjectId in via `#include "_objectid_inc.glsl"`, which the GLSL
    # compiler rejects unless spliced here first.
    vert = preprocess_shader(vert_name, vertex_defines)
    frag = preprocess_shader(frag_name)
    v = GL_shaders.compileShader(vert, GL_VERTEX_SHADER)
    fr = GL_shaders.compileShader(frag, GL_FRAGMENT_SHADER)
    prog = GL_shaders.compileProgram(v, fr, validate=validate)
    _delete_shaders(v, fr)
    return prog


def _delete_shaders(*shaders: Any) -> None:
    """Flag standalone shader objects for deletion after they are linked."""
    from OpenGL.GL import glDeleteShader
    for sh in shaders:
        try:
            glDeleteShader(sh)
        except Exception:
            pass


def _compile_shadow_frag(vert_name: str, frag_name: str, max_shadow_lights: int,
                         cube_array: bool, validate: bool = False,
                         extra_defines: Optional[list] = None,
                         vertex_defines: Optional[list] = None,
                         views: int = 0, strategy: str = 'geometry') -> int:
    """Compile a program whose fragment shader carries the shared shadow include.

    ``views`` compiles it for a shared draw of that many views, reached by
    ``strategy``; see
    :func:`OpenGLContext.passes.shaderpass.link_program`.
    """
    vert = preprocess_shader(vert_name, vertex_defines)
    frag = load_fragment_source(frag_name, max_shadow_lights, cube_array,
                                extra_defines=extra_defines)
    return link_program(vert, frag, validate, views, strategy)


class PBRShaderProgram(VRML97ShaderProgram):
    """Cook-Torrance metallic/roughness program (+ the inherited shadow machinery)."""

    #: Every material map this program samples, with its unit: the core maps,
    #: and the extension maps :attr:`ext_channels` says the driver has units for.
    texture_units: tuple[tuple[str, int], ...] = tuple(PBR_UNITS.items())
    _ext_channels: Mapping[str, int] = MappingProxyType({})

    @property
    def ext_channels(self) -> Mapping[str, int]:
        """The extension maps this driver has texture units for, by channel."""
        return self._ext_channels

    @ext_channels.setter
    def ext_channels(self, channels: Mapping[str, int]) -> None:
        self._ext_channels = dict(channels)
        self.texture_units = tuple(PBR_UNITS.items()) + tuple(self._ext_channels.items())

    MATERIAL_UBO_BINDING: int = MATERIAL_UBO_BINDING

    #: The lit program is the metallic/roughness one; the helper programs are
    #: the VRML97 ones this inherits, from the same files.
    VERTEX_SOURCES: dict[str, str] = dict(
        VRML97ShaderProgram.VERTEX_SOURCES, program='pbr.vert')

    def __init__(self) -> None:
        super().__init__()
        # Per-instance so two programs (or two passes) never share transmission /
        # material-cache state through the class.
        self.transmission_mode = 'off'
        # Set when the program is compiled, from the driver's texture units.
        self.planar_reflection_supported = False
        self._appearance_material = _APPEARANCE_UNSET
        self._appearance_seen: Any = _APPEARANCE_UNSET
        self._appearance_tmode = None

    def release(self) -> None:
        """Delete the programs; the materials' blocks stay with their materials."""
        self._appearance_material = _APPEARANCE_UNSET
        self._impostor = PBRShaderProgram._impostor
        super().release()

    def compile(self) -> bool:
        if self._compiled:
            return self._ok
        try:
            # Bake the driver's shadow-light budget / cube path into pbr.frag,
            # mirroring the VRML97 program.
            self.MAX_SHADOW_LIGHTS, self.shadow_cube_array = resolve_shadow_config()
            # Sampler-budget gate: extension textures (units 16+) only exist on a GPU
            # reporting more than the 16-unit GL 3.3 minimum (llvmpipe reports 16).
            self.texture_budget = int(glGetIntegerv(GL_MAX_TEXTURE_IMAGE_UNITS))
            self.ext_channels = ext_texture_channels(self.texture_budget)
            # Reflections of the scene are read from a unit past the joint
            # palette; where the fragment stage stops short of it every
            # mirror reflects the environment probe alone.
            self.planar_reflection_supported = (
                self.texture_budget >= REFLECTION_UNITS_NEEDED)
            # A zone's own environment probe is a layer of the cube-map array
            # the scene's probe then lives in, which needs the same GL 4.0 /
            # ARB_texture_cube_map_array support the point-shadow cube arrays
            # do -- and the #extension line that support already enables.
            self.zone_probes_supported = bool(self.shadow_cube_array)
            ext_defines = ['#define PBR_EXT_TEXTURES %d'
                           % (1 if ext_textures_supported(self.texture_budget) else 0),
                           '#define PBR_PLANAR_REFLECTION %d'
                           % (1 if self.planar_reflection_supported else 0),
                           '#define PBR_ZONE_PROBES %d'
                           % (1 if self.zone_probes_supported else 0),
                           '#define MAX_ZONE_LAYERS %d' % (MAX_ZONE_LAYERS,)]
            # Vertex-shader skinning needs a texture unit of its own for the
            # joint palette; a driver whose combined budget does not reach it
            # compiles the skinning out and the deform stays on the CPU.
            self.skinning_supported = palette_supported()
            skin_defines = ['#define PBR_SKINNING %d'
                            % (1 if self.skinning_supported else 0)]
            self._defines = (ext_defines, skin_defines)
            # validate=False: PBR + shadow samplers of several targets default to
            # unit 0 at link time; real units are assigned before drawing.
            self.program = _compile_shadow_frag(
                'pbr.vert', 'pbr.frag', self.MAX_SHADOW_LIGHTS, self.shadow_cube_array,
                extra_defines=ext_defines, vertex_defines=skin_defines)
            # selection + auxiliary geometry reuse the VRML97 helper programs
            self.unlit_program = _compile_file('vrml97_unlit.vert', 'vrml97_unlit.frag')
            # vertex_color now #includes _shadow_inc (2a), so bake the same shadow
            # budget the pbr program uses.
            self.vertex_color_program = _compile_shadow_frag(
                'vrml97_vertex_color.vert', 'vrml97_vertex_color.frag',
                self.MAX_SHADOW_LIGHTS, self.shadow_cube_array)
            self.point_program = _compile_file('vrml97_point.vert', 'vrml97_point.frag')
            self.line_program = _compile_file('vrml97_line.vert', 'vrml97_line.frag')
            # Minimal position-only program for shadow depth passes (22+ per frame
            # with several lights); avoids running the full PBR fragment shader
            # just to write depth.
            self.depth_program = _compile_file('shadow_depth.vert', 'shadow_depth.frag',
                                               vertex_defines=skin_defines)

            self._init_program_set()
            glUseProgram(self.depth_program)
            self._init_skinning(self.depth_program)
            glUseProgram(0)
            self._compiled = True
            self._ok = True
            log.info("PBR shader program compiled successfully")
            return True
        except Exception as err:
            log.error("Failed to compile PBR shader: %s", err)
            self._compiled = True
            self._clear_programs()  # null every handle; leave _ok False
            return False

    #: Whether this driver has the texture unit the joint palette needs; False
    #: until a program has been compiled against a real context.
    skinning_supported: bool = False

    #: Whether zones may have environment probes of their own: the scene's
    #: probe is then a cube-map array, and must be built as one. False until a
    #: program has been compiled against a real context.
    zone_probes_supported: bool = False

    #: The fragment and vertex defines the lit program was compiled with, so a
    #: set compiled for several views is compiled the same way.
    _defines: tuple[list, list] = ([], [])

    def _compile_program_set(self, views: int,
                             strategy: str = 'geometry') -> dict[str, Optional[int]]:
        """The PBR and vertex-colour programs compiled for ``views`` shared views."""
        ext_defines, skin_defines = self._defines
        try:
            return {
                'program': _compile_shadow_frag(
                    'pbr.vert', 'pbr.frag', self.MAX_SHADOW_LIGHTS,
                    self.shadow_cube_array, extra_defines=ext_defines,
                    vertex_defines=skin_defines, views=views, strategy=strategy),
                'vertex_color_program': _compile_shadow_frag(
                    'vrml97_vertex_color.vert', 'vrml97_vertex_color.frag',
                    self.MAX_SHADOW_LIGHTS, self.shadow_cube_array, views=views,
                    strategy=strategy),
            }
        except Exception as err:
            log.error("Failed to compile the PBR programs for %d views: %s", views, err)
            return {}

    def _init_program_set(self) -> None:
        """Shadow and material samplers, the material block and the skin palette."""
        super()._init_program_set()
        glUseProgram(self.program or 0)
        self._init_pbr_samplers()
        self._init_material_block()
        self._init_skinning(self.program)
        glUseProgram(0)

    # Transmission render path for this frame: 'off' | 'full' | 'blend'. Set by
    # the pass before drawing; configure_appearance consults it per shape.
    transmission_mode: str = 'off'

    # Last appearance configured this frame, so repeated shapes of one material
    # (the norm in CAD assemblies -- hundreds of parts, a handful of materials)
    # skip the whole re-box-and-upload. Reset each frame by reset_appearance_cache
    # so per-frame material edits are still picked up.
    _appearance_material: Any = _APPEARANCE_UNSET
    #: The appearance that was configured, whose alpha mode and cutoff are set.
    _appearance_seen: Any = _APPEARANCE_UNSET
    _appearance_tmode: Optional[str] = None

    def reset_appearance_cache(self) -> None:
        """Forget the last-configured material (call once per frame/pass)."""
        self._appearance_material = _APPEARANCE_UNSET

    def _init_pbr_samplers(self) -> None:
        for channel, unit in PBR_UNITS.items():
            self._set_uniform1i(_PBR_SAMPLER[channel], unit, self.program)
        for channel, unit in IBL_UNITS.items():
            self._set_uniform1i(_IBL_SAMPLER[channel], unit, self.program)
        self._set_uniform1i('transmissionTexture', TransmissionBuffer.UNIT, self.program)
        self._set_uniform1i('hasTransmissionBackdrop', 0, self.program)
        if self.planar_reflection_supported:
            self._set_uniform1i('planarReflection', REFLECTION_UNIT, self.program)
            self._set_uniform1i('hasPlanarReflection', 0, self.program)
        # A GLSL uniform starts at zero, which would make every lightmap black;
        # the neutral multiplier has to be uploaded once up front.
        self.set_lightmap_strength(1.0)
        # Extension-texture samplers exist only when the budget admitted them
        # (PBR_EXT_TEXTURES).
        for channel, unit in getattr(self, 'ext_channels', {}).items():
            self._set_uniform1i(_PBR_EXT_SAMPLER[channel], unit, self.program)
        self._set_uniform1i('materialTextures', 0, self.program)

    # -- per-material uniform block (UBO) ----------------------------------
    def _init_material_block(self) -> None:
        """Point the MaterialBlock uniform block at its binding index (once)."""
        program = self.program
        if program is None:
            return                      # nothing compiled, so no block to point
        idx = glGetUniformBlockIndex(program, 'MaterialBlock')
        if idx != GL_INVALID_INDEX:
            glUniformBlockBinding(program, idx, self.MATERIAL_UBO_BINDING)

    def _upload_material_ubo(self, material: Any, buf: Optional[int] = None) -> int:
        """Fill ``buf``, or a new buffer, with ``material``'s block; the buffer filled."""
        data = pack_material_block(material)
        if buf is None:
            buf = int(glGenBuffers(1))
        glBindBuffer(GL_UNIFORM_BUFFER, buf)
        glBufferData(GL_UNIFORM_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
        glBindBuffer(GL_UNIFORM_BUFFER, 0)
        return buf

    def _material_ubo(self, material: Any) -> int:
        """The GL buffer holding ``material``'s factor block in this context.

        Built on first use and shared by every program in the context. A live
        edit (KHR_animation_pointer driving a material factor, a route into a
        VRML97 Material) moves ``material.factorVersion``, and the block is
        packed again into the buffer the material already has; an edit that
        does not needs :meth:`invalidate_material_ubo`.
        """
        owner = _NO_MATERIAL if material is None else material
        entries = _MATERIAL_BLOCKS.entries(owner)
        if entries is None:
            raise TypeError('%r cannot hold a material block' % (material,))
        version = (_repacks, int(getattr(material, 'factorVersion', 0)))
        entry = entries.get('block')
        if entry is None or entry[1] != version:
            buf = self._upload_material_ubo(material, entry[0] if entry is not None else None)
            entries['block'] = (buf, version)
            return buf
        found: int = entry[0]
        return found

    def invalidate_material_ubo(self, material: Any = None) -> None:
        """Have ``material``'s block packed again at its next draw; every block's where None"""
        global _repacks
        if material is None:
            _repacks += 1
            return
        held = cache.CACHE.getHolder(material, MATERIAL_BLOCK_KEY)
        if held is not None:
            held.data = None
        entries = _MATERIAL_BLOCKS.entries(material)
        if entries and 'block' in entries:
            entries['block'] = (entries['block'][0], None)

    def bind_material_block(self, material: Any) -> None:
        """Bind ``material``'s factor block for the shapes that follow."""
        if self.program is None:
            return
        glBindBufferBase(GL_UNIFORM_BUFFER, self.MATERIAL_UBO_BINDING,
                         self._material_ubo(material))

    def bind_transmission_backdrop(self, buffer: TransmissionBuffer) -> None:
        """Make the captured opaque backdrop available to the transmission path."""
        buffer.bind()
        self._set_uniform1i('hasTransmissionBackdrop', 1, self.program)
        self._set_uniform1f('transmissionMaxLod', buffer.max_lod, self.program)

    def set_planar_reflection(self, lookup: Any = None, program: Any = None) -> None:
        """Have the next draws read a mirror's reflection, or none.

        ``lookup`` is a :class:`~OpenGLContext.passes.reflectionplanner.Lookup`:
        the matrix a fragment's world position is projected through, the
        tile it lands in, the mirror's normal, and how the reflection is
        applied. None reads no reflection, which is every shape that is not
        a mirror.
        """
        if not self.planar_reflection_supported:
            return
        target = program if program is not None else self.program
        if lookup is None:
            self._set_uniform1i('hasPlanarReflection', 0, target)
            return
        self._set_uniform1i('hasPlanarReflection', 1, target)
        loc = self._get_location('planarMatrix', target)
        if loc != -1:
            glUniformMatrix4fv(loc, 1, GL_FALSE,
                               np.asarray(lookup.matrix, 'f').reshape(4, 4))
        self._set_uniform4f('planarTile', lookup.transform, target)
        self._set_uniform4f('planarBounds', lookup.bounds, target)
        self._set_uniform3f('planarNormal', lookup.normal, target)
        self._set_uniform1f('planarDistortion', lookup.distortion, target)
        self._set_uniform1i('planarReplace', 1 if lookup.replace else 0, target)
        self._set_uniform1f('planarReflectance', float(lookup.reflectance), target)

    def set_planar_levels(self, levels: float) -> None:
        """How many blurred mip levels of the reflection atlas a rough mirror may read."""
        if self.planar_reflection_supported:
            self._set_uniform1f('planarLevels', float(levels), self.program)

    def clear_transmission_backdrop(self) -> None:
        self._set_uniform1i('hasTransmissionBackdrop', 0, self.program)

    def set_lightmap_strength(self, strength: float = 1.0) -> None:
        """Scale the baked irradiance a lightmap contributes (1.0 = as authored).

        A loose uniform rather than a UBO field, so an instanced draw shares one
        value across the batch; lightmapped geometry is per-surface unique and
        does not instance.
        """
        self._set_uniform1f('lightmapStrength', float(strength), self.program)

    def set_light_grid(self, ambient: Any = None, directional: Any = None,
                       direction: Any = None, program: Any = None) -> None:
        """Light the next draw from a baked grid, or from none.

        Called with nothing, the next draw takes no grid light -- which is what
        a scene with no grid, and every draw of a surface that carries its own
        lightmap, wants.  Otherwise the three are the light at this object's
        own position: the pass has already done the lookup, so the shader is
        handed an answer rather than a grid to search.

        A loose uniform rather than a UBO field, because it belongs to the
        object rather than to the material -- two pickups of one kind are lit
        differently by standing in different places.

        See :class:`OpenGLContext.scenegraph.lightgrid.LightGrid`.
        """
        target = program if program is not None else self.program
        if ambient is None:
            self._set_uniform1i('hasLightGrid', 0, target)
            return
        self._set_uniform1i('hasLightGrid', 1, target)
        self._set_uniform3f('lightGridAmbient', ambient, target)
        self._set_uniform3f('lightGridDirectional', directional, target)
        self._set_uniform3f('lightGridDirection', direction, target)

    def set_zones(self, pack: Optional[ZonePack] = None, program: Any = None) -> None:
        """Hand the next draw the zones reaching it, or none.

        ``pack`` is what :func:`~OpenGLContext.passes.zonelayers.environment_layers`
        worked out for the object. Loose uniforms rather than a block, for the
        reason the light grid's are: they belong to the object, and the pass
        uploads them only when the object's zones differ from the last draw's.
        """
        target = program if program is not None else self.program
        if pack is None or pack.count == 0:
            self._set_uniform1i('zoneLayers', 0, target)
            return
        loc = self._get_location('zoneKind', target)
        if loc != -1:
            glUniform1iv(loc, MAX_ZONE_LAYERS, pack.kinds)
        loc = self._get_location('zoneToLocal', target)
        if loc != -1:
            # Row-vector, as the engine's matrices are, which GL reads as the
            # column-vector matrix the shader multiplies by.
            glUniformMatrix4fv(loc, MAX_ZONE_LAYERS, GL_FALSE, pack.to_local)
        loc = self._get_location('zoneShape', target)
        if loc != -1:
            glUniform4fv(loc, MAX_ZONE_LAYERS, pack.shape)
        loc = self._get_location('zoneLight', target)
        if loc != -1:
            glUniform4fv(loc, MAX_ZONE_LAYERS, pack.light)
        self._set_uniform1i('zoneLayers', pack.count, target)

    def set_vertex_color(self, enabled: bool) -> None:
        """Enable/disable per-vertex color (glTF COLOR_0) modulation of baseColor."""
        self._set_uniform1i('hasVertexColor', 1 if enabled else 0, self.program)

    #: What :meth:`set_impostor` last set, and on which program.
    _impostor: tuple[Optional[int], int, bool] = (None, 0, True)

    def set_impostor(self, views: int, hemi: bool = True) -> None:
        """Draw this material's geometry as an octahedral impostor, or not.

        ``views`` is how many baked views a side its base colour holds, and 0 --
        every ordinary material -- turns the whole thing off. The vertex shader
        does the rest: it turns the quad to the viewer and moves its texture
        coordinate into the tile for the direction it is being seen from.
        Called for every shape drawn, so a run of shapes asking what the
        program already has costs one comparison.
        """
        state = (self.program, int(views), bool(hemi))
        if state == self._impostor:
            return
        self._set_uniform1i('impostorGrid', state[1], self.program)
        self._set_uniform1i('impostorHemi', 1 if state[2] else 0, self.program)
        self._impostor = state

    #: What :meth:`set_texgen` last set, and on which program.
    _texgen: tuple[Optional[int], int, tuple[float, ...]] = (None, 0, ())

    def set_texgen(self, generator: Optional[TexGen], modelview: Any = None) -> None:
        """Make the first texture coordinate set with `generator`, or read it from the arrays

        X3D's TextureCoordinateGenerator, as :mod:`OpenGLContext.scenegraph.texgen`
        numbers its modes; None reads ``aTexCoord``. `modelview` is the
        draw's, which places the camera in the shape's own space for the
        local modes; an instanced draw leaves it None. Called for every shape
        drawn, since the uniform outlives the draw that set it.
        """
        if generator is None:
            state: tuple[Optional[int], int, tuple[float, ...]] = (self.program, 0, ())
        else:
            state = (self.program, generator.mode, generator.parameters)
            if modelview is not None:
                # Row vectors: the eye at the origin, taken back through the model-view
                eye = np.linalg.inv(np.asarray(modelview, dtype=np.float64))[3, :3]
                self._set_uniform3f('texGenLocalEye',
                                    (float(eye[0]), float(eye[1]), float(eye[2])), self.program)
        if state == self._texgen:
            return
        self._set_uniform1i('texGenMode', state[1], self.program)
        if state[2]:
            loc = self._get_location('texGenParameter', self.program)
            if loc != -1:
                glUniform1fv(loc, len(state[2]), np.asarray(state[2], dtype=np.float32))
        self._texgen = state

    # -- skinning ----------------------------------------------------------
    def _init_skinning(self, program: Any) -> None:
        """Point a program's palette sampler at its unit, once at compile time."""
        if not self.skinning_supported or not program:
            return
        self._set_uniform1i('jointPalette', SKIN_PALETTE_UNIT, program)
        self._set_uniform1i('skinningEnabled', 0, program)
        self._set_uniform1i('skinningInstanced', 0, program)

    def set_skinning(self, base: Optional[int], program: Any = None,
                     instanced: bool = False) -> None:
        """Skin the next draw from ``base`` in the joint palette, or not at all.

        ``None`` turns skinning off for the draws that follow, which is what
        every unskinned shape in the scene wants; the uniform is a branch the
        whole draw takes together, so an unskinned mesh pays nothing for the
        skinned one beside it.
        """
        if not self.skinning_supported:
            return
        target = program if program is not None else (
            getattr(self, '_active_program', 0) or self.program)
        if base is None:
            self._set_uniform1i('skinningEnabled', 0, target)
            return
        self._set_uniform1i('skinningInstanced', 1 if instanced else 0, target)
        if not instanced:
            self._set_uniform1i('jointBase', int(base), target)
        self._set_uniform1i('skinningEnabled', 1, target)

    # -- water ------------------------------------------------------------
    def set_wave(self, style: Any, when: float = 0.0,
                 program: Any = None) -> None:
        """Move the next draw as ``style`` says, or not at all.

        ``None`` turns the wave off for the draws that follow, which is what
        every other shape in the scene wants; the uniform is a branch the whole
        draw takes together, so a hillside pays nothing for the lake beside it.

        The mesh is uploaded once and only these uniforms change, which is what
        makes a moving surface cost nothing per frame -- the same arrangement
        skinning uses for a pose.
        """
        target = program if program is not None else (
            getattr(self, '_active_program', 0) or self.program)
        if style is None:
            self._set_uniform1i('waveEnabled', 0, target)
            return
        self._set_uniform1f('waveAmplitude', float(style.amplitude), target)
        self._set_uniform1f('waveLength', float(style.wavelength), target)
        self._set_uniform1f('waveSpeed', float(style.speed), target)
        self._set_uniform1f('waveSteepness', float(style.steepness), target)
        self._set_uniform1f('waveRippleScale', float(style.ripple), target)
        self._set_uniform2f('waveFlow', (float(style.flow[0]),
                                         float(style.flow[1])), target)
        self._set_uniform1f('waveTime', float(when), target)
        self._set_uniform1i('waveEnabled', 1, target)

    # -- material / appearance --------------------------------------------
    def set_alpha(self, alpha: float, alpha_mode: int, cutoff: float = 0.5) -> None:
        """Opacity, alpha mode and cutoff: the appearance's, set per draw"""
        self._set_uniform1f('alphaValue', float(alpha), self.program)
        self._set_uniform1i('alphaMode', int(alpha_mode), self.program)
        self._set_uniform1f('alphaCutoff', float(cutoff), self.program)
        self._alpha = (float(alpha), float(cutoff))

    #: The opacity and cutoff :meth:`set_alpha` last set.
    _alpha: tuple[float, float] = (1.0, 0.5)

    def bind_coverage(self, texture: int) -> None:
        """Draw the next shapes through `texture`, white with the coverage of
        text in its alpha, as their only map, blended

        The material's own maps are put back when the next shape is set up.
        """
        glActiveTexture(GL_TEXTURE0 + PBR_UNITS['baseColor'])
        glBindTexture(GL_TEXTURE_2D, texture)
        glActiveTexture(GL_TEXTURE0)
        self._set_uniform1i('materialTextures', PBR_TEXTURE_BITS['baseColor'], self.program)
        alpha, cutoff = self._alpha
        self.set_alpha(alpha, _ALPHA_MODES['BLEND'], cutoff)
        self._boundTextures = None
        self.reset_appearance_cache()

    def release_coverage(self) -> None:
        """Have the next shape set its material and maps up again"""
        self._boundTextures = None
        self.reset_appearance_cache()

    def bind_pbr_textures(self, material: Any, mode: Any) -> None:
        """Put ``material``'s images on the texture units the shaders read.

        Skipped outright when the units already hold this material's images.
        The render set is sorted by texture, so a level's shapes arrive in runs
        sharing one material; without the memo each channel of each of them
        costs an active-texture, a bind and a uniform whether or not anything
        changed -- a couple of dozen GL calls a draw, hundreds of draws a frame.

        The memo is cleared whenever a program is bound, because the overlay and
        the depth maps bind these units for themselves and what they left is not
        this pass's to assume.
        """
        if not self.program:
            # Nothing compiled to read these units, so there is nothing to put
            # on them. The uniform setters already return on a null program;
            # this is the same rule for the binds and the active-unit reset,
            # which are GL calls whether or not a texture was found for a
            # channel.
            return
        bound = (id(material), self.program)
        if self._boundTextures == bound:
            return
        self._boundTextures = bound
        # Sampler -> texture-unit assignments are constant; they are set once at
        # compile time (see _init_pbr_samplers in compile), so don't re-set them
        # per draw.
        textures = getattr(material, 'textures', {}) or {}
        # Every map is found before any is bound: the first draw of a map
        # uploads it, and an upload binds the new texture on the active unit,
        # which would be the unit of the map bound before it.
        found = []
        for channel, unit in self.texture_units:
            holder = textures.get(channel)
            tex = holder.cached(mode) if holder is not None else None
            if tex is not None and getattr(tex, 'texture', None):
                found.append((channel, unit, tex.texture))
        # Which maps are sampled is one uniform, a bit per map, rather than a
        # uniform per map: a draw of a new material sets one value.
        sampled = 0
        for channel, unit, texture in found:
            glActiveTexture(GL_TEXTURE0 + unit)
            glBindTexture(GL_TEXTURE_2D, texture)
            sampled |= PBR_TEXTURE_BITS[channel]
        self._set_uniform1i('materialTextures', sampled, self.program)
        glActiveTexture(GL_TEXTURE0)

    def set_texture_mapping(self, mapping: TextureMapping) -> None:
        """Each material channel's texture coordinates and transform, for the next draw"""
        self._set_uniform('channelCodes', mapping.codes, self.program, _upload_codes)
        self._set_uniform('uvTransformRows', mapping.rows, self.program,
                          _upload_rows)

    def configure_appearance(self, appearance: Any, mode: Any, geometry: Any = None,
                             back: bool = False) -> None:
        """Configure PBR material + textures from a Shape's appearance.

        Routes both PhysicalMaterial (directly) and a VRML97 appearance -- its
        Material up-converted, its texture as the base colour map -- through
        this single PBR program; :func:`pbr_material` says which. ``geometry``
        is what is drawn with it, whose coordinate sets the appearance's
        mapping labels name. ``back`` configures the back faces' material
        (:func:`~OpenGLContext.scenegraph.physicalmaterial.side_material`).
        A shape with no appearance is drawn unlit white under X3D's lighting
        rules (:mod:`OpenGLContext.lighting`), and in the engine's lit neutral
        grey under its own.
        """
        if appearance:
            material = pbr_material(appearance, back)
        else:
            material = _DOCUMENT_UNLIT if lighting.x3d_lit(geometry) else None
        # The coordinates depend on the geometry as well as the appearance, so
        # they are set before the same-material early-out.
        self.set_texture_mapping(texture_mapping(appearance, geometry, back))
        # An octahedral impostor is a property of the material rather than of
        # the draw, so it is set here beside the rest of it. Before the
        # same-material early-out: the previous shape may have been an ordinary
        # one, and a stale `impostorGrid` would billboard it.
        self.set_impostor(int(getattr(material, 'octahedralViews', 0) or 0),
                          bool(getattr(material, 'octahedralHemi', True)))
        # Same material as the previous shape this frame -> its uniforms and bound
        # textures are already live; skip the re-box entirely. Identity compare is
        # safe within a frame (materials aren't mutated mid-frame) and the cache is
        # cleared each frame, so per-frame edits still take effect.
        if (material is self._appearance_material
                and appearance is self._appearance_seen
                and self.transmission_mode == self._appearance_tmode):
            return
        self._appearance_material = material
        self._appearance_seen = appearance
        self._appearance_tmode = self.transmission_mode
        # Static factors (base color, metallic/roughness, KHR extensions, volume)
        # come from the material's cached UBO -- one bind, no per-shape re-box.
        self.bind_material_block(material)
        alpha_mode, cutoff = appearance_alpha(appearance)
        code = _ALPHA_MODES[alpha_mode]
        alpha = 1.0 - float(getattr(material, 'transparency', 0.0) or 0.0)
        if isinstance(source_of(material), ChannelMaterial):
            tf = float(getattr(material, 'transmission', 0.0) or 0.0)
            if tf > 0.0 and self.transmission_mode == 'blend':
                # Cheap fallback: no backdrop refraction -- approximate the glass
                # as an alpha-blended surface with opacity (1 - transmission). Keep
                # a small floor so fully-transmissive glass still shows highlights.
                alpha, code, tf = max(1.0 - tf, GLASS_MIN_OPACITY), 2, 0.0
            elif self.transmission_mode != 'full':
                tf = 0.0                        # off, or not a transmissive frame
            self.set_alpha(alpha, code, cutoff)
            self.set_transmission(tf)
            self.set_lightmap_strength(
                float(getattr(material, 'lightmapStrength', 1.0) or 0.0))
            # anisotropy / dispersion / diffuse-transmission are per-instance UBO
            # fields (see pack_material_block), so they need no loose-uniform set.
        else:
            self.set_alpha(alpha, code, cutoff)
            self.set_transmission(0.0)
        self.bind_pbr_textures(material, mode)

    def set_ibl_mode(self, mode_code: int, intensity: float = 1.0,
                     fill_scale: float = 1.0) -> None:
        """Set the environment-lighting path (0=off, 1=analytic, 2=full).

        ``fill_scale`` multiplies what the environment gives a non-metal; the
        built-in studio environment is lowered this way (see
        :func:`OpenGLContext.passes.ibl.fill_scale`).
        """
        self._set_uniform1i('iblMode', int(mode_code), self.program)
        self._set_uniform1f('iblIntensity', float(intensity), self.program)
        self._set_uniform1f('iblFill', float(fill_scale), self.program)

    def set_exposure(self, exposure: float = 1.0) -> None:
        """Set the camera exposure multiplier (1.0 = neutral). Scenes lit by
        absolute-unit KHR_lights_punctual lights stop down from here so they don't
        clip to white; everything else stays at 1.0."""
        self._set_uniform1f('exposure', float(exposure), self.program)

    def set_transmission(self, transmission_factor: float, material: Any = None) -> None:
        """Set the frame-gated transmission factor (volume params are in the UBO)."""
        self._set_uniform1f('transmissionFactor', float(transmission_factor), self.program)

    def set_diffuse_transmission(self, factor: float,
                                 color: Sequence[float] = (1.0, 1.0, 1.0)) -> None:
        """Set KHR_materials_diffuse_transmission factor + colour (0 = opaque)."""
        self._set_uniform1f('diffuseTransmissionFactor', float(factor), self.program)
        self._set_uniform3f('diffuseTransmissionColor',
                            (color[0], color[1], color[2]), self.program)

    def set_anisotropy(self, strength: float, rotation: float = 0.0) -> None:
        """Set KHR_materials_anisotropy strength + rotation direction (0 = isotropic).

        The shader wants the rotation as a (cos, sin) tangent-plane direction so it
        needs no trig; the per-fragment anisotropyTexture (if any) rotates it further.
        """
        import math
        self._set_uniform1f('anisotropyStrength', float(strength), self.program)
        self._set_uniform2f('anisotropyDirection',
                            (math.cos(rotation), math.sin(rotation)), self.program)

    def set_hdr_output(self, enabled: bool) -> None:
        """Emit linear HDR (bloom pass) rather than tone-mapping in the shader."""
        self._set_uniform1i('hdrOutput', 1 if enabled else 0, self.program)


def instancing_is_enabled(source: Any = None) -> bool:
    """Whether instanced-geometry batching is on.

    ``ContextDefinition.instancing`` when a pass asks (``source``), otherwise
    ``OPENGLCONTEXT_INSTANCING``. Default on; off forces the per-shape path,
    which is how the performance win is A/B'd. Read per call, so a benchmark or
    a settings screen can toggle it between frames.
    """
    default = renderoptions.env_flag('OPENGLCONTEXT_INSTANCING', True)
    if source is None:
        return default
    return renderoptions.flag(source, 'instancing', default)




class PBRPass(flatcore.FlatPass):
    """Render pass using the PBR metallic/roughness shader."""

    use_shaders: bool = True
    #: No flat fill: the light that is not from a lamp comes from the environment
    #: (:meth:`iblPrepare`), and with the environment off there is none.
    #: ``context.gltf_scene_ambient`` adds one.
    DEFAULT_AMBIENT: tuple[float, float, float] = (0.0, 0.0, 0.0)
    #: The one buffer every instanced group's material array is uploaded to.
    _instance_material_ubo: Optional[int] = None
    #: What :attr:`_instance_material_ubo` was last filled with.
    _instance_material_data: Optional[np.ndarray] = None

    def disposeResources(self) -> None:
        """Release the instanced groups' material buffer, then the rest."""
        buffer, self._instance_material_ubo = self._instance_material_ubo, None
        if buffer is not None:
            try:
                glDeleteBuffers(1, np.array([buffer], dtype=np.uint32))
            except Exception:
                log.debug('deleting the instance material buffer failed', exc_info=True)
        super().disposeResources()

    def instanceMinimum(self) -> int:
        """Smallest group worth collapsing into one instanced draw.

        Overridable for benchmarking and small test scenes with
        OPENGLCONTEXT_INSTANCE_MIN, read once per process rather than at import
        so an application -- or a test -- can still set it.
        """
        return int(renderoptions.env_number_once(
            'OPENGLCONTEXT_INSTANCE_MIN', 4, integer=True))

    @property
    def instancing_enabled(self) -> bool:
        return instancing_is_enabled(self)

    def getShaderProgram(self) -> VRML97ShaderProgram:
        if self._shader_program_instance is None:
            self._shader_program_instance = PBRShaderProgram()
        return self._shader_program_instance

    # Must match MAX_INSTANCE_MATERIALS in pbr.frag (sized to the 16 KB UBO min:
    # 73 * 224 B = 16352 B, within the guaranteed 16384-byte UBO block).
    MAX_INSTANCE_MATERIALS: int = 73   # 224 B/material fits the 16 KB UBO min

    def _instanceable(self, shape: Any) -> bool:
        """Any geometry exposing ``instanceGPU(mode)`` (PBRMesh, Box, Sphere, ...).

        A **skinned** mesh counts where the shader poses it: figures of a build
        then hold the same rest-pose vertices, so they batch on content, and
        each instance carries the place its own joints start in the palette. A
        figure the processor skins does not: its buffers hold its *posed*
        vertices, so no two of them are the same geometry and there is nothing
        to collapse.
        """
        geometry = getattr(shape, 'geometry', None)
        if getattr(geometry, 'skin_joints', None) is not None:
            # Settle where this mesh is skinned before asking, not at its first
            # draw: a mesh that batches has no draw of its own to settle it in,
            # and would have gone on assuming the shader would skin it however
            # the renderer was configured.
            resolve = getattr(geometry, '_resolve_skin_path', None)
            if resolve is not None:
                resolve(self, self.getShaderProgram())
            if not getattr(geometry, 'skin_on_gpu', False):
                return False
        # A mirror is drawn singly: each one reads a reflection of its own.
        if reflection.shape_reflector(shape) is not None:
            return False
        # So is a surface with a back material: it is drawn a side at a time.
        if two_sided(getattr(shape, 'appearance', None)):
            return False
        return hasattr(geometry, 'instanceGPU')

    def batchers(self) -> Batchers:
        """The ``(key, instanceable)`` pair for one grouping, remembered per shape.

        What a shape batches on is read from its geometry and its appearance,
        and they change far less often than a frame is drawn, so the answer is
        kept against what it was made from and asked again only when one of
        them differs: the identities of the geometry, appearance, material and
        texture, the material's
        :meth:`~OpenGLContext.scenegraph.physicalmaterial.PhysicalMaterial.batchingVersion`,
        :func:`~OpenGLContext.passes.reflection.mirror_generation`, which
        moves when any shape may have become a mirror or stopped being one,
        and the appearance's alpha mode and cutoff. A
        geometry that computes its own content key from its fields is asked
        every time. Whether content collapse is on is read once for the
        grouping.
        """
        collapse = instance_collapse_is_enabled()
        mirrors = reflection.mirror_generation()
        memo = self.__dict__.get('_batchMemo')
        if memo is None:
            memo = self.__dict__['_batchMemo'] = weakref.WeakKeyDictionary()
        if len(memo) > 100000:
            memo.clear()

        def answer(shape: Any) -> tuple[Any, bool]:
            geometry = getattr(shape, 'geometry', None)
            appearance = getattr(shape, 'appearance', None)
            material = getattr(appearance, 'material', None)
            drawn_as = pbr_material(appearance)
            version = getattr(drawn_as, 'batchingVersion', None)
            made_from = (geometry, appearance, material,
                         getattr(appearance, 'texture', None))
            stamps = (version() if version is not None
                      else getattr(drawn_as, 'factorVersion', 0), collapse, mirrors,
                      appearance_alpha(appearance))
            held = memo.get(shape)
            if held is not None and held[1] == stamps and all(
                    was is now for was, now in zip(held[0], made_from, strict=True)):
                return held[2], held[3]
            key = self._keyFor(shape, collapse)
            flag = key is not None and bool(self._instanceable(shape))
            if not callable(getattr(geometry, 'instanceContentKey', None)):
                memo[shape] = (made_from, stamps, key, flag)
            return key, flag

        return (lambda shape: answer(shape)[0]), (lambda shape: answer(shape)[1])

    def _keyFor(self, shape: Any, collapse: bool) -> Any:
        from OpenGLContext.passes.instancing import (
            geometry_texture_key, geometry_content_key,
        )
        return geometry_content_key(shape) if collapse else geometry_texture_key(shape)

    def _instanceKey(self, shape: Any) -> Any:
        """Batch by geometry + texture set: materials differing only by FACTORS
        share one instanced draw (each instance indexes the material array). With
        opportunistic collapse on, key geometry by CONTENT so distinct nodes with
        identical vertex data batch too."""
        from OpenGLContext.passes.instancing import (
            geometry_texture_key, geometry_content_key,
        )
        if instance_collapse_is_enabled():
            return geometry_content_key(shape)
        return geometry_texture_key(shape)

    def _material_chunks(self, members: list, materials: list, indices: list,
                         max_mats: int) -> Iterator[tuple]:
        """Split a group so no draw needs more materials than the UBO array holds.

        Yields (members, materials, indices) chunks, each with <= max_mats distinct
        materials and indices re-based to 0..len(chunk_materials)-1. The common
        case (few materials) yields a single chunk.
        """
        if len(materials) <= max_mats:
            yield members, materials, indices
            return
        cm: list = []
        cmat: list = []
        cidx: list = []
        slot: dict = {}
        for member, gi in zip(members, indices, strict=True):
            mat = materials[gi]
            if id(mat) not in slot:
                if len(cmat) >= max_mats:
                    yield cm, cmat, cidx
                    cm, cmat, cidx, slot = [], [], [], {}
                slot[id(mat)] = len(cmat)
                cmat.append(mat)
            cm.append(member)
            cidx.append(slot[id(mat)])
        if cm:
            yield cm, cmat, cidx

    def _bind_material_array(self, materials: list) -> int:
        """Pack N materials into one std140 array UBO and bind it at the material
        binding. Reuses one persistent buffer on the pass, filled (orphaning the
        previous storage) only when the packed materials differ from what it
        holds, so a still frame of one group fills nothing. The array element
        layout matches the single-material block, so the shader indexes
        ``materials[i]`` for instance material i. Returns the buffer."""
        blocks = [pack_material_block(m) for m in materials]
        data = np.ascontiguousarray(np.concatenate(blocks), dtype=np.float32)
        buf = self._instance_material_ubo
        if buf is None:
            buf = int(glGenBuffers(1))
            self._instance_material_ubo = buf
            self._instance_material_data = None
        held = self._instance_material_data
        if held is None or held.shape != data.shape or not np.array_equal(held, data):
            glBindBuffer(GL_UNIFORM_BUFFER, buf)
            # glBufferData (not SubData) orphans the previous storage, so a still-in-
            # flight draw from an earlier chunk this frame keeps its own data.
            glBufferData(GL_UNIFORM_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
            glBindBuffer(GL_UNIFORM_BUFFER, 0)
            self._instance_material_data = data
        glBindBufferBase(GL_UNIFORM_BUFFER, MATERIAL_UBO_BINDING, buf)
        return buf

    def _drawInstanceGroup(self, group: Any, shader: Any, prog: Any,
                           id_map: Optional[dict]) -> None:
        """Draw a whole InstanceGroup with one glDrawElementsInstanced per chunk.

        Instances in a group share geometry and textures but may differ by
        material FACTORS: each instance's material is packed into a per-group
        material-array UBO and selected by a per-instance index. Textures and
        pass-level state (alpha mode, transmission) come from the representative
        appearance (the group key guarantees they agree). Each instance keeps a
        distinct pick id via ``_objectIdFor``; a non-pickable instance packs 0.
        """
        from OpenGLContext.passes.instancing import (
            carries_colours, draw_instanced_mesh, group_material_table, instance_counts,
            instance_joint_bases, instance_matrices, member_joint_bases,
            per_instance,
        )
        geom = group.geometry
        materials, indices = group_material_table(group)

        # Textures + pass uniforms from the representative appearance; the material
        # array (bound below) overrides the single-material factor UBO.
        shader.configure_appearance(group.appearance, self, group.geometry)
        self.renderPath = group.members[0][4]
        self.matrix = group.members[0][1]
        shader.set_matrices(self.matrix, self.projection, program=prog)
        if hasattr(geom, '_apply_draw_state'):
            geom._apply_draw_state(self)
        else:
            # A geometry with no draw state of its own still says how its
            # faces wind and whether its back is ever seen; a single-sided
            # surface (a VRML ``solid FALSE``) is drawn from both sides.
            apply_winding_cull(self, bool(getattr(geom, 'ccw', True)),
                               bool(getattr(geom, 'solid', True)))
        gpu = geom.instanceGPU(self)
        if hasattr(shader, 'set_vertex_color'):
            shader.set_vertex_color(carries_colours(gpu))
        if hasattr(shader, 'set_texgen'):
            shader.set_texgen(getattr(geom, 'texGen', None))

        # The whole group draws as one, reached by the zones any member is.
        apply_zones = getattr(self, 'applyZonesToGroup', None)
        if apply_zones is not None:
            apply_zones(shader, group.members, prog, key=group.key)

        bases = instance_joint_bases(self, group)
        shader.set_instancing(True, program=prog)
        if hasattr(shader, 'set_skinning'):
            shader.set_skinning(0 if bases is not None else None, program=prog,
                                instanced=True)
        try:
            for members, chunk_mats, chunk_idx in self._material_chunks(
                    group.members, materials, indices, self.MAX_INSTANCE_MATERIALS):
                # A member standing for a whole placement set expands to one
                # instance per placement; its pick id and its material go to all
                # of them, since they are one node.
                modelviews = instance_matrices(members, visible=self.visiblePlacements)
                counts = instance_counts(members, visible=self.visiblePlacements)
                if id_map is not None:
                    oids = [self._objectIdFor(rec[4]) if self._shapePickable(rec[5])
                            else 0 for rec in members]
                else:
                    oids = [0] * len(members)
                self._bind_material_array(chunk_mats)
                member_bases = (member_joint_bases(bases, members, counts)
                                if bases is not None else None)
                draw_instanced_mesh(gpu, modelviews,
                                    per_instance(oids, counts),
                                    material_indices=per_instance(chunk_idx, counts),
                                    joint_bases=member_bases,
                                    copies=self.viewCopies)
        finally:
            shader.set_instancing(False, program=prog)
            # The transient array UBO replaced the single-material binding; force
            # the next single shape to rebind its own material block.
            shader._appearance_material = _APPEARANCE_UNSET


_renderer_is_pbr_cache: Optional[bool] = None


def renderer_is_pbr() -> bool:
    """Whether the PBR renderer is selected (``OPENGLCONTEXT_RENDERER=pbr``).

    Cached after the first read: the environment doesn't change within a process
    and this is consulted on the per-frame render-dispatch path.  A test that
    changes the variable calls :func:`reset_renderer_cache` to make the next
    read see it.
    """
    global _renderer_is_pbr_cache
    if _renderer_is_pbr_cache is None:
        _renderer_is_pbr_cache = (
            renderoptions.env_text('OPENGLCONTEXT_RENDERER').lower() == 'pbr')
    return _renderer_is_pbr_cache


def reset_renderer_cache() -> None:
    """Forget the memoised renderer choice, so the next read consults the
    environment again.

    A process-lifetime memo of an environment variable needs one of these or it
    is a one-way door: whichever value happened to be set the first time
    anything rendered is the value for the rest of the session, and a test that
    sets the variable is silently ignored -- or, worse, leaves the memo holding
    *its* answer for every test that follows.
    """
    global _renderer_is_pbr_cache
    _renderer_is_pbr_cache = None
