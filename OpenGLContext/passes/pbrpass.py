"""Physically-based render pass and shader program.

``PBRPass`` is a :class:`flatcore.FlatPass` subclass whose ``shader_program`` is a
:class:`PBRShaderProgram` rendering a Cook-Torrance metallic/roughness BRDF. It
inherits the shadow subsystem (shadows on by default) and the whole render flow;
only the bound program and per-shape material configuration differ.

Both ``PBRMaterial`` nodes and legacy VRML97 ``Material`` nodes render through the
single PBR program -- the latter via up-conversion -- so existing scenes draw
under the PBR pass without per-shape program switches.
"""
from __future__ import annotations

import os
import logging
import weakref
from typing import Any, Iterator, Optional, Sequence

import numpy as np

from OpenGL.GL import (
    GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_TEXTURE0, GL_TEXTURE_2D,
    GL_UNIFORM_BUFFER, GL_STATIC_DRAW, GL_DYNAMIC_DRAW, GL_INVALID_INDEX,
    GL_MAX_TEXTURE_IMAGE_UNITS,
    glUseProgram, glActiveTexture, glBindTexture, glGetIntegerv,
    glGenBuffers, glBindBuffer, glBufferData, glBindBufferBase,
    glGetUniformBlockIndex, glUniformBlockBinding,
)
from OpenGL.GL import shaders as GL_shaders

from OpenGLContext.passes import flatcore
from OpenGLContext.passes.shaderpass import (
    VRML97ShaderProgram, load_fragment_source, resolve_shadow_config,
    preprocess_shader,
)
from OpenGLContext.passes.transmission import TransmissionBuffer
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, material_to_pbr
from OpenGLContext.passes.ibl import IBL_UNITS, _IBL_SAMPLER
from OpenGLContext.scenegraph.skinning import SKIN_PALETTE_UNIT, palette_supported

log = logging.getLogger(__name__)

# Sentinel distinct from any real material (including None) so the first shape of
# each frame always reconfigures.
_APPEARANCE_UNSET = object()

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
# + uvTransform mat3 + the iridescence vec4 and later KHR extension factors total
# 56 words / 224 bytes.
MATERIAL_BLOCK_WORDS = 56   # 224 B; must match the Material struct in pbr.frag
MATERIAL_UBO_BINDING = 1        # glUniformBlockBinding / glBindBufferBase point

# Opacity floor for the cheap (no-backdrop) transmission fallback, so fully
# transmissive glass still shows specular highlights instead of vanishing.
GLASS_MIN_OPACITY = 0.08


def _material_factors(material: Any) -> dict:
    """Uniform-ready factors for a PBRMaterial, a VRML97 Material, or None."""
    if isinstance(material, PBRMaterial):
        m = material
        return dict(
            base_color=tuple(m.baseColor)[:3], metallic=float(m.metallic),
            roughness=float(m.roughness), emissive=tuple(m.emissiveColor)[:3],
            occlusion=float(m.occlusionStrength), normal_scale=float(m.normalScale),
            alpha_cutoff=float(m.alphaCutoff), unlit=1 if m.unlit else 0,
            emissive_strength=float(m.emissiveStrength), specular=float(m.specular),
            specular_color=tuple(m.specularColor)[:3], clearcoat=float(m.clearcoat),
            clearcoat_roughness=float(m.clearcoatRoughness),
            sheen_color=tuple(m.sheenColor)[:3], sheen_roughness=float(m.sheenRoughness),
            ior=float(m.ior), thickness=float(m.thickness),
            attenuation_color=tuple(m.attenuationColor)[:3],
            attenuation_distance=float(m.attenuationDistance),
            uv_transform=getattr(m, 'uv_transform', None),
            tex_coord_mask=(int(getattr(m, 'texCoordMask', 0) or 0)
                            | (BAKED_LIGHT_BIT
                               if getattr(m, 'bakedLight', False) else 0)),
            iridescence=float(getattr(m, 'iridescence', 0.0)),
            iridescence_ior=float(getattr(m, 'iridescenceIor', 1.3)),
            iridescence_thick_min=float(getattr(m, 'iridescenceThicknessMin', 100.0)),
            iridescence_thick_max=float(getattr(m, 'iridescenceThicknessMax', 400.0)),
            anisotropy_strength=float(getattr(m, 'anisotropyStrength', 0.0) or 0.0),
            anisotropy_rotation=float(getattr(m, 'anisotropyRotation', 0.0) or 0.0),
            dispersion=float(getattr(m, 'dispersion', 0.0) or 0.0),
            diffuse_transmission=float(getattr(m, 'diffuseTransmission', 0.0) or 0.0),
            diffuse_transmission_color=tuple(
                getattr(m, 'diffuseTransmissionColor', (1.0, 1.0, 1.0)))[:3],
        )
    f = material_to_pbr(material)      # None / VRML97 Material -> plausible defaults
    return dict(
        base_color=f['base_color'], metallic=f['metallic'], roughness=f['roughness'],
        emissive=f['emissive'], occlusion=f['occlusion'], normal_scale=1.0,
        alpha_cutoff=0.5, unlit=0, emissive_strength=1.0, specular=1.0,
        specular_color=(1.0, 1.0, 1.0), clearcoat=0.0, clearcoat_roughness=0.0,
        sheen_color=(0.0, 0.0, 0.0), sheen_roughness=0.0, ior=1.5, thickness=0.0,
        attenuation_color=(1.0, 1.0, 1.0), attenuation_distance=0.0, uv_transform=None,
        tex_coord_mask=0, iridescence=0.0, iridescence_ior=1.3,
        iridescence_thick_min=100.0, iridescence_thick_max=400.0,
        anisotropy_strength=0.0, anisotropy_rotation=0.0, dispersion=0.0,
        diffuse_transmission=0.0, diffuse_transmission_color=(1.0, 1.0, 1.0),
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


#: Which bit of the texture-coordinate mask says the vertex colours are
#: baked light rather than a tint. Above the per-channel UV-set bits (1 to
#: 32), and read by the fragment shader as ``bakedLightMode``.
BAKED_LIGHT_BIT = 64


def pack_material_block(material: Any) -> np.ndarray:
    """Pack a material into the std140 MaterialBlock byte layout (float32 array).

    Kept on the material against its own ``_ubo_version``, the counter every
    runtime material edit already bumps: an instanced group repacks its whole
    material table every frame, and a crowd of figures out of one document
    carries a material apiece that nothing is changing.
    """
    version = int(getattr(material, '_ubo_version', 0))
    cached = getattr(material, '_packed_block', None)
    if cached is not None and cached[0] == version:
        return cached[1]
    packed = _pack_material_block(material)
    try:
        material._packed_block = (version, packed)
    except Exception:       # pragma: no cover - a material that refuses attributes
        pass
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
    buf[19] = d['alpha_cutoff']
    buf[20] = d['emissive_strength']
    buf[21] = d['specular']
    buf[22] = d['clearcoat']
    buf[23] = d['clearcoat_roughness']
    buf[24] = d['sheen_roughness']
    buf[25] = d['ior']
    buf[26] = d['thickness']
    buf[27] = d['attenuation_distance']
    iv[28] = 1 if d['unlit'] else 0
    iv[29] = int(d.get('tex_coord_mask', 0))
    # words 30, 31 are the std140 padding before the 16-byte-aligned mat3 -- reuse
    # them for two per-instance scalars (anisotropy strength + dispersion) for free.
    buf[30] = d.get('anisotropy_strength', 0.0)
    buf[31] = d.get('dispersion', 0.0)
    uvt = d['uv_transform']
    M = np.identity(3, np.float32) if uvt is None else np.asarray(uvt, np.float32).reshape(3, 3)
    for c in range(3):                 # mat3: each column padded to a 16-byte slot
        base = 32 + 4 * c
        buf[base:base + 3] = M[:, c]
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
    """Flag standalone shader objects for deletion after they are linked (3.4)."""
    from OpenGL.GL import glDeleteShader
    for sh in shaders:
        try:
            glDeleteShader(sh)
        except Exception:
            pass


def _compile_shadow_frag(vert_name: str, frag_name: str, max_shadow_lights: int,
                         cube_array: bool, validate: bool = False,
                         extra_defines: Optional[list] = None,
                         vertex_defines: Optional[list] = None) -> Any:
    """Compile a program whose fragment shader carries the shared shadow include."""
    vert = preprocess_shader(vert_name, vertex_defines)
    frag = load_fragment_source(frag_name, max_shadow_lights, cube_array,
                                extra_defines=extra_defines)
    v = GL_shaders.compileShader(vert, GL_VERTEX_SHADER)
    fr = GL_shaders.compileShader(frag, GL_FRAGMENT_SHADER)
    prog = GL_shaders.compileProgram(v, fr, validate=validate)
    _delete_shaders(v, fr)
    return prog


class PBRShaderProgram(VRML97ShaderProgram):
    """Cook-Torrance metallic/roughness program (+ the inherited shadow machinery)."""

    MATERIAL_UBO_BINDING: int = MATERIAL_UBO_BINDING

    def __init__(self) -> None:
        super().__init__()
        # One GL uniform buffer per material, uploaded once and reused across
        # frames. Weak keys so a buffer's bookkeeping drops when its material is
        # collected (the GL buffer itself is reclaimed at context teardown).
        self._material_ubos: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()
        self._default_material_ubo: Optional[int] = None
        # Per-instance so two programs (or two passes) never share transmission /
        # material-cache state through the class.
        self.transmission_mode = 'off'
        self._appearance_material = _APPEARANCE_UNSET
        self._appearance_tmode = None

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
            ext_defines = ['#define PBR_EXT_TEXTURES %d'
                           % (1 if ext_textures_supported(self.texture_budget) else 0)]
            # Vertex-shader skinning needs a texture unit of its own for the
            # joint palette; a driver whose combined budget does not reach it
            # compiles the skinning out and the deform stays on the CPU.
            self.skinning_supported = palette_supported()
            skin_defines = ['#define PBR_SKINNING %d'
                            % (1 if self.skinning_supported else 0)]
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

            glUseProgram(self.program)
            self.init_shadow_samplers()
            self._init_pbr_samplers()
            self._init_material_block()
            self._init_skinning(self.program)
            glUseProgram(0)
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
            self._clear_programs()  # null every handle; leave _ok False (3.4)
            return False

    #: Whether this driver has the texture unit the joint palette needs; False
    #: until a program has been compiled against a real context.
    skinning_supported: bool = False

    # Transmission render path for this frame: 'off' | 'full' | 'blend'. Set by
    # the pass before drawing; configure_appearance consults it per shape.
    transmission_mode: str = 'off'

    # Last appearance configured this frame, so repeated shapes of one material
    # (the norm in CAD assemblies -- hundreds of parts, a handful of materials)
    # skip the whole re-box-and-upload. Reset each frame by reset_appearance_cache
    # so per-frame material edits are still picked up.
    _appearance_material: Any = _APPEARANCE_UNSET
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
        # A GLSL uniform starts at zero, which would make every lightmap black;
        # the neutral multiplier has to be uploaded once up front.
        self.set_lightmap_strength(1.0)
        # Extension-texture samplers exist only when the budget admitted them
        # (PBR_EXT_TEXTURES). Assign each to its unit and clear its presence flag.
        for channel, unit in getattr(self, 'ext_channels', {}).items():
            self._set_uniform1i(_PBR_EXT_SAMPLER[channel], unit, self.program)
            self._set_uniform1i(_PBR_EXT_HAS[channel], 0, self.program)

    # -- per-material uniform block (UBO) ----------------------------------
    def _init_material_block(self) -> None:
        """Point the MaterialBlock uniform block at its binding index (once)."""
        idx = glGetUniformBlockIndex(self.program, 'MaterialBlock')
        if idx != GL_INVALID_INDEX:
            glUniformBlockBinding(self.program, idx, self.MATERIAL_UBO_BINDING)

    def _upload_material_ubo(self, material: Any) -> int:
        data = pack_material_block(material)
        buf = int(glGenBuffers(1))
        glBindBuffer(GL_UNIFORM_BUFFER, buf)
        glBufferData(GL_UNIFORM_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
        glBindBuffer(GL_UNIFORM_BUFFER, 0)
        return buf

    def _material_ubo(self, material: Any) -> int:
        """The GL buffer holding ``material``'s factor block, built on first use.

        Cached across frames: PBR materials are static, so the block is packed and
        uploaded once. Mutating a material in place needs invalidate_material_ubo.
        """
        if material is None:
            if self._default_material_ubo is None:
                self._default_material_ubo = self._upload_material_ubo(None)
            return self._default_material_ubo
        # Cache (buffer, version). A live edit (KHR_animation_pointer driving a
        # material factor / texture transform) bumps material._ubo_version, so the
        # block is re-packed on the next draw instead of staying stale.
        entry = self._material_ubos.get(material)
        version = int(getattr(material, '_ubo_version', 0))
        if entry is None or entry[1] != version:
            buf = self._upload_material_ubo(material)
            self._material_ubos[material] = (buf, version)
            return buf
        return entry[0]

    def invalidate_material_ubo(self, material: Any = None) -> None:
        """Drop a cached block so the next draw re-packs it (after a material edit).

        ``material=None`` clears every cached block. The GL buffers are left for
        context teardown to reclaim; only the bookkeeping is dropped.
        """
        if material is None:
            self._material_ubos.clear()
            self._default_material_ubo = None
        else:
            self._material_ubos.pop(material, None)

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

    def clear_transmission_backdrop(self) -> None:
        self._set_uniform1i('hasTransmissionBackdrop', 0, self.program)

    def set_lightmap_strength(self, strength: float = 1.0) -> None:
        """Scale the baked irradiance a lightmap contributes (1.0 = as authored).

        A loose uniform rather than a UBO field, so an instanced draw shares one
        value across the batch; lightmapped geometry is per-surface unique and
        does not instance.
        """
        self._set_uniform1f('lightmapStrength', float(strength), self.program)

    def set_vertex_color(self, enabled: bool) -> None:
        """Enable/disable per-vertex color (glTF COLOR_0) modulation of baseColor."""
        self._set_uniform1i('hasVertexColor', 1 if enabled else 0, self.program)

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
        self._set_uniform2f('waveFlow', (float(style.flow[0]),
                                         float(style.flow[1])), target)
        self._set_uniform1f('waveTime', float(when), target)
        self._set_uniform1i('waveEnabled', 1, target)

    # -- material / appearance --------------------------------------------
    def set_alpha(self, alpha: float, alpha_mode: int) -> None:
        """Opacity + alpha mode (frame/pass-dependent; the rest is in the UBO)."""
        self._set_uniform1f('alphaValue', float(alpha), self.program)
        self._set_uniform1i('alphaMode', int(alpha_mode), self.program)

    def bind_pbr_textures(self, material: Any, mode: Any) -> None:
        # Sampler -> texture-unit assignments are constant; they are set once at
        # compile time (see _init_pbr_samplers in compile), so don't re-set them
        # per draw.
        textures = getattr(material, 'textures', {}) or {}
        for channel, unit in PBR_UNITS.items():
            holder = textures.get(channel)
            tex = holder.cached(mode) if holder is not None else None
            if tex is not None and getattr(tex, 'texture', None):
                glActiveTexture(GL_TEXTURE0 + unit)
                glBindTexture(GL_TEXTURE_2D, tex.texture)
                self._set_uniform1i(_PBR_HAS[channel], 1, self.program)
            else:
                self._set_uniform1i(_PBR_HAS[channel], 0, self.program)
        # Extension textures, only on a GPU whose budget admitted their units.
        for channel, unit in getattr(self, 'ext_channels', {}).items():
            holder = textures.get(channel)
            tex = holder.cached(mode) if holder is not None else None
            has = tex is not None and getattr(tex, 'texture', None)
            if has:
                assert tex is not None
                glActiveTexture(GL_TEXTURE0 + unit)
                glBindTexture(GL_TEXTURE_2D, tex.texture)
            self._set_uniform1i(_PBR_EXT_HAS[channel], 1 if has else 0, self.program)
        glActiveTexture(GL_TEXTURE0)

    def configure_appearance(self, appearance: Any, mode: Any) -> None:
        """Configure PBR material + textures from a Shape's appearance.

        Routes both PBRMaterial (directly) and VRML97 Material (up-converted)
        through this single PBR program.
        """
        material = getattr(appearance, 'material', None) if appearance else None
        # Publish the material's double-sidedness to the geometry's cull decision
        #: a hand-built PBRMaterial(doubleSided=True) must disable
        # back-face culling even when the mesh itself is marked solid. Set before
        # the early-out so it stays correct for repeated same-material shapes.
        if mode is not None:
            mode._appearance_double_sided = bool(getattr(material, 'doubleSided', False))
        # Same material as the previous shape this frame -> its uniforms and bound
        # textures are already live; skip the re-box entirely. Identity compare is
        # safe within a frame (materials aren't mutated mid-frame) and the cache is
        # cleared each frame, so per-frame edits still take effect.
        if (material is self._appearance_material
                and self.transmission_mode == self._appearance_tmode):
            return
        self._appearance_material = material
        self._appearance_tmode = self.transmission_mode
        # Static factors (base color, metallic/roughness, KHR extensions, uvTransform,
        # volume) come from the material's cached UBO -- one bind, no per-shape re-box.
        self.bind_material_block(material)
        _ALPHA = {'OPAQUE': 0, 'MASK': 1, 'BLEND': 2}
        if isinstance(material, PBRMaterial):
            alpha = 1.0 - float(material.transparency)
            alpha_mode = _ALPHA.get(str(material.alphaMode), 0)
            tf = float(getattr(material, 'transmission', 0.0) or 0.0)
            if tf > 0.0 and self.transmission_mode == 'blend':
                # Cheap fallback: no backdrop refraction -- approximate the glass
                # as an alpha-blended surface with opacity (1 - transmission). Keep
                # a small floor so fully-transmissive glass still shows highlights.
                alpha, alpha_mode, tf = max(1.0 - tf, GLASS_MIN_OPACITY), 2, 0.0
            elif self.transmission_mode != 'full':
                tf = 0.0                        # off, or not a transmissive frame
            self.set_alpha(alpha, alpha_mode)
            self.set_transmission(tf)
            self.set_lightmap_strength(
                float(getattr(material, 'lightmapStrength', 1.0) or 0.0))
            # anisotropy / dispersion / diffuse-transmission are per-instance UBO
            # fields (see pack_material_block), so they need no loose-uniform set.
            self.bind_pbr_textures(material, mode)
        else:
            f = material_to_pbr(material)
            self.set_alpha(1.0 - f['transparency'], 0)
            self.set_transmission(0.0)
            self.bind_pbr_textures(None, mode)  # clears has* flags

    def set_ibl_mode(self, mode_code: int, intensity: float = 1.0) -> None:
        """Set the environment-lighting path (0=off, 1=analytic, 2=full)."""
        self._set_uniform1i('iblMode', int(mode_code), self.program)
        self._set_uniform1f('iblIntensity', float(intensity), self.program)

    def set_exposure(self, exposure: float = 1.0) -> None:
        """Set the camera exposure multiplier (1.0 = neutral). Scenes lit by
        absolute-unit KHR_lights_punctual lights stop down from here so they don't
        clip to white; everything else stays at 1.0."""
        self._set_uniform1f('exposure', float(exposure), self.program)

    def set_fog(self, density: float = 0.0,
                color: Sequence[float] = (0.6, 0.7, 0.85),
                mode: int = 1) -> None:
        """Set the frame's fog: a curve, its scale, and its colour.

        ``mode`` is one of the codes in :mod:`OpenGLContext.scenegraph.fog` --
        aerial-perspective density, or either of VRML97's two curves, which are
        different fades to the same range and not approximations of each other.
        Density 0 (the default) disables it whatever the mode, leaving a scene
        with no fog in it unchanged.
        """
        self._set_uniform1i('fogMode', int(mode), self.program)
        self._set_uniform1f('fogDensity', float(density), self.program)
        self._set_uniform3f('fogColor', (color[0], color[1], color[2]), self.program)

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
    from OpenGLContext import renderoptions
    default = renderoptions.env_flag('OPENGLCONTEXT_INSTANCING', True)
    if source is None:
        return default
    return renderoptions.flag(source, 'instancing', default)


def instance_collapse_is_enabled() -> bool:
    """Whether to collapse distinct-node but identical-content geometry into one
    instanced draw (``OPENGLCONTEXT_INSTANCE_COLLAPSE``, default on).

    On: batch by geometry CONTENT (a cached per-mesh hash), so glTF repeated
    meshes and re-authored primitives instance even when they are separate nodes.
    Off: batch only by shared geometry-node identity (USE/DEF), avoiding the
    one-time content hash on scenes of all-unique meshes.
    """
    return os.environ.get('OPENGLCONTEXT_INSTANCE_COLLAPSE', '1').strip().lower() \
        not in ('0', 'off', 'false', 'no')


class PBRPass(flatcore.FlatPass):
    """Render pass using the PBR metallic/roughness shader."""

    use_shaders: bool = True

    def instanceMinimum(self) -> int:
        """Smallest group worth collapsing into one instanced draw.

        Overridable for benchmarking and small test scenes with
        OPENGLCONTEXT_INSTANCE_MIN, read once per process rather than at import
        so an application -- or a test -- can still set it.
        """
        from OpenGLContext import renderoptions
        return int(renderoptions.env_number_once(
            'OPENGLCONTEXT_INSTANCE_MIN', 4, integer=True))

    # The base _flat.FlatPass declares instancing_enabled as a writeable class
    # attribute; the shader passes intentionally compute it as a read-only property.
    @property
    def instancing_enabled(self) -> bool:  # type: ignore[override]
        return instancing_is_enabled(self)

    def getShaderProgram(self) -> VRML97ShaderProgram:
        if self._shader_program_instance is None:
            self._shader_program_instance = PBRShaderProgram()
        return self._shader_program_instance

    # Must match MAX_INSTANCE_MATERIALS in pbr.frag (sized to the 16 KB UBO min:
    # 73 * 224 B = 16352 B, within the guaranteed 16384-byte UBO block).
    MAX_INSTANCE_MATERIALS: int = 73   # 224 B/material fits the 16 KB UBO min

    def _instanceable(self, path: Any) -> bool:
        """Any geometry exposing ``instanceGPU(mode)`` (PBRMesh, Box, Sphere, ...).

        A **skinned** mesh counts where the shader poses it: figures of a build
        then hold the same rest-pose vertices, so they batch on content, and
        each instance carries the place its own joints start in the palette. A
        figure the processor skins does not: its buffers hold its *posed*
        vertices, so no two of them are the same geometry and there is nothing
        to collapse.
        """
        geometry = getattr(path[-1], 'geometry', None)
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
        return hasattr(geometry, 'instanceGPU')

    def _instanceKey(self, path: Any) -> Any:
        """Batch by geometry + texture set: materials differing only by FACTORS
        share one instanced draw (each instance indexes the material array). With
        opportunistic collapse on, key geometry by CONTENT so distinct nodes with
        identical vertex data batch too."""
        from OpenGLContext.passes.instancing import (
            geometry_texture_key, geometry_content_key,
        )
        if instance_collapse_is_enabled():
            return geometry_content_key(path)
        return geometry_texture_key(path)

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
        binding. Reuses one persistent buffer on the pass (orphan + re-upload each
        call) instead of gen/deleting a UBO per group per frame. The array element
        layout matches the single-material block, so the shader indexes
        ``materials[i]`` for instance material i. Returns the buffer."""
        blocks = [pack_material_block(m) for m in materials]
        data = np.ascontiguousarray(np.concatenate(blocks), dtype=np.float32)
        buf = getattr(self, '_instance_material_ubo', None)
        if buf is None:
            buf = int(glGenBuffers(1))
            self._instance_material_ubo = buf
        glBindBuffer(GL_UNIFORM_BUFFER, buf)
        # glBufferData (not SubData) orphans the previous storage, so a still-in-
        # flight draw from an earlier chunk this frame keeps its own data.
        glBufferData(GL_UNIFORM_BUFFER, data.nbytes, data, GL_DYNAMIC_DRAW)
        glBindBuffer(GL_UNIFORM_BUFFER, 0)
        glBindBufferBase(GL_UNIFORM_BUFFER, MATERIAL_UBO_BINDING, buf)
        return buf

    def _instanceJointBases(self, group: Any) -> Optional[dict]:
        """Where each member of a skinned group reads its joints, by geometry.

        Also what puts each figure's matrices into the palette: the per-shape
        draw does that on its way past, and an instanced group has no per-shape
        draw to do it on.
        """
        if getattr(group.geometry, 'skin_joints', None) is None:
            return None
        from OpenGLContext.scenegraph.skinning import palette_for
        bases: dict = {}
        pending: list = []
        for record in group.members:
            geometry = record[4][-1].geometry
            claimed = geometry.skin_claim(self)
            if claimed is None:
                return None
            base, matrices = claimed
            bases[id(geometry)] = base
            if matrices is not None:
                pending.append((base, matrices))
        if pending:
            palette = palette_for(self)
            if palette is not None:
                palette.write_runs(pending)
        return bases

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
            draw_instanced_mesh, group_material_table, instance_counts,
            instance_matrices, per_instance,
        )
        geom = group.geometry
        materials, indices = group_material_table(group)

        # Textures + pass uniforms from the representative appearance; the material
        # array (bound below) overrides the single-material factor UBO.
        shader.configure_appearance(group.appearance, self)
        self.renderPath = group.members[0][4]
        self.matrix = group.members[0][1]
        shader.set_matrices(self.matrix, self.projection, program=prog)
        if hasattr(geom, '_apply_draw_state'):
            geom._apply_draw_state(self)
        if hasattr(shader, 'set_vertex_color'):
            shader.set_vertex_color(getattr(geom, 'colors', None) is not None)

        gpu = geom.instanceGPU(self)
        bases = self._instanceJointBases(group)
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
                modelviews = instance_matrices(members)
                counts = instance_counts(members)
                if id_map is not None:
                    oids = [self._objectIdFor(rec[4]) if self._shapePickable(rec[4])
                            else 0 for rec in members]
                else:
                    oids = [0] * len(members)
                self._bind_material_array(chunk_mats)
                member_bases = (per_instance(
                    [bases[id(rec[4][-1].geometry)] for rec in members], counts)
                    if bases is not None else None)
                draw_instanced_mesh(gpu, modelviews,
                                    per_instance(oids, counts),
                                    material_indices=per_instance(chunk_idx, counts),
                                    joint_bases=member_bases)
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
            os.environ.get('OPENGLCONTEXT_RENDERER', '').strip().lower() == 'pbr')
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
