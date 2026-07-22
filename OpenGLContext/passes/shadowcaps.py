"""Detect OpenGL capabilities relevant to shadow mapping.

The shadow subsystem adapts to the driver: hardware PCF on depth textures is
always available on the core-profile 3.3 baseline, while soft-shadow and
single-pass techniques are enabled only when the matching extensions/version are
present. ``ShadowCapabilities`` queries this once and chooses a technique per
light type, degrading gracefully.

The technique-selection logic is a pure function of the detected feature set, so
it can be unit-tested via :meth:`ShadowCapabilities.from_features` without a GL
context.
"""
from __future__ import annotations

import logging
from typing import Optional, Set, Tuple

log = logging.getLogger(__name__)


class ShadowCapabilities:
    """Feature set and chosen techniques for shadow rendering."""

    # Only capabilities the shadow subsystem actually consumes are detected. An
    # earlier version advertised has_geometry_layered / has_float_color (VSM) /
    # has_seamless_cube / has_aniso / max_array_layers / a pcf_kernel size and a
    # 'single' directional technique that no code path implements -- detecting a
    # tier the renderer can't use invites callers to branch on a phantom feature
    #. Those were dropped; the fields below each gate real code.
    def __init__(
        self,
        gl_version: Tuple[int, int] = (3, 3),
        has_texture_gather: bool = False,
        has_cube_shadow: bool = True,
        has_cube_array: bool = False,
        has_depth_clamp: bool = False,
        max_texture_units: int = 16,
        total_vram_mb: int = 0,
    ) -> None:
        self.gl_version = gl_version
        self.has_texture_gather = has_texture_gather   # shadowmixin: PCSS gather hint
        self.has_cube_shadow = has_cube_shadow         # shadowmixin: point shadows at all
        self.has_cube_array = has_cube_array           # shaderpass: packed cube-array path
        self.has_depth_clamp = has_depth_clamp         # shadowmixin: depth-pass clamp
        self.max_texture_units = max_texture_units     # max_shadow_lights budget
        self.total_vram_mb = total_vram_mb  # 0 = unknown (no NVX/ATI meminfo); cascade cap

    # -- chosen techniques -------------------------------------------------
    @property
    def point_technique(self) -> str:
        """How to shadow point lights."""
        if self.has_cube_shadow:
            return 'cube'
        return 'none'

    def max_shadow_lights(self, reserved_units: int = 4) -> int:
        """How many shadow-casting lights the per-stage unit budget allows.

        With the packed layout the fragment-stage cost is
        ``shadowArray`` + ``shadowArrayRaw`` = 2 units always, plus point shadows:
        one ``samplerCubeArrayShadow`` (1 unit, independent of light count) when
        :attr:`has_cube_array`, else one ``samplerCubeShadow`` per shadow light.

        reserved_units -- fragment texture units kept for material maps.
        """
        HARD_MAX = 4
        avail = self.max_texture_units - reserved_units
        if self.has_cube_array:
            capacity = HARD_MAX if avail >= 3 else 1
        else:
            capacity = avail - 2   # two array samplers + one cube sampler per light
        return max(1, min(HARD_MAX, capacity))

    # -- construction ------------------------------------------------------
    @classmethod
    def from_features(cls, extensions: Set[str], gl_version: Tuple[int, int],
                      max_texture_units: int = 16) -> 'ShadowCapabilities':
        """Build from an extension-name set and version (pure, GL-free)."""
        def has(name: str) -> bool:
            return name in extensions or ('GL_' + name) in extensions

        ge = gl_version
        return cls(
            gl_version=gl_version,
            has_texture_gather=has('ARB_texture_gather') or ge >= (4, 0),
            has_cube_shadow=ge >= (3, 0),
            has_cube_array=has('ARB_texture_cube_map_array') or ge >= (4, 0),
            has_depth_clamp=has('ARB_depth_clamp') or ge >= (3, 2),
            max_texture_units=max_texture_units,
        )

    @classmethod
    def detect(cls, context: Optional[object] = None) -> 'ShadowCapabilities':
        """Detect capabilities from the current GL context.

        Falls back to a conservative 3.3 baseline if querying fails (e.g. no
        current context).
        """
        try:
            from OpenGL.GL import (
                glGetString, glGetIntegerv, GL_VERSION,
                GL_MAX_TEXTURE_IMAGE_UNITS,
            )
            version = cls._parse_version(glGetString(GL_VERSION))
            extensions = cls._list_extensions(context)
            try:
                # Per-stage (fragment) limit -- the one the lit program actually
                # spends shadow samplers against, not the combined all-stage total.
                units = int(glGetIntegerv(GL_MAX_TEXTURE_IMAGE_UNITS))
            except Exception:
                units = 16
            caps = cls.from_features(extensions, version, units)
            caps.total_vram_mb = cls._query_vram_mb(extensions)
            log.info(
                "Shadow capabilities: GL %s, gather=%s cube=%s cube_array=%s "
                "depth_clamp=%s units=%s",
                version, caps.has_texture_gather, caps.has_cube_shadow,
                caps.has_cube_array, caps.has_depth_clamp, units,
            )
            return caps
        except Exception as err:
            log.warning("Shadow capability detection failed (%s); using 3.3 baseline", err)
            return cls()

    @staticmethod
    def _query_vram_mb(extensions: Set[str]) -> int:
        """Total dedicated VRAM in MB, or 0 if the GPU exposes no meminfo query.

        Uses GL_NVX_gpu_memory_info (NVIDIA) or GL_ATI_meminfo (AMD). Intel/mesa
        typically report neither, leaving 0 (treated as "unknown -> conservative").
        """
        try:
            from OpenGL.GL import glGetIntegerv
            if 'GL_NVX_gpu_memory_info' in extensions:
                # 0x9048 = TOTAL_AVAILABLE_MEMORY, in KB
                kb = int(glGetIntegerv(0x9048))
                if kb > 0:
                    return kb // 1024
            if 'GL_ATI_meminfo' in extensions:
                # 0x87FC = TEXTURE_FREE_MEMORY_ATI: [total, ...] in KB
                vals = glGetIntegerv(0x87FC)
                kb = int(vals[0]) if hasattr(vals, '__len__') else int(vals)
                if kb > 0:
                    return kb // 1024
        except Exception:
            pass
        return 0

    @staticmethod
    def _parse_version(raw) -> Tuple[int, int]:
        try:
            if isinstance(raw, bytes):
                raw = raw.decode('ascii', 'replace')
            # e.g. "3.3.0 NVIDIA ..." or "4.6 (Core Profile) ..."
            head = raw.strip().split(' ')[0]
            parts = head.split('.')
            return (int(parts[0]), int(parts[1]))
        except Exception:
            return (3, 3)

    @staticmethod
    def _list_extensions(context: Optional[object]) -> Set[str]:
        # Prefer the context's ExtensionManager if available
        if context is not None and hasattr(context, 'extensions'):
            try:
                names = context.extensions.listGL()
                return {n.decode() if isinstance(n, bytes) else n for n in names}
            except Exception:
                pass
        # Fall back to core-profile glGetStringi enumeration
        try:
            from OpenGL.GL import (
                glGetIntegerv, glGetStringi, GL_NUM_EXTENSIONS, GL_EXTENSIONS,
            )
            count = int(glGetIntegerv(GL_NUM_EXTENSIONS))
            out: Set[str] = set()
            for i in range(count):
                name = glGetStringi(GL_EXTENSIONS, i)
                out.add(name.decode() if isinstance(name, bytes) else name)
            return out
        except Exception:
            return set()
