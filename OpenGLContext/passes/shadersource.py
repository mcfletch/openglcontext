"""Shader source assembly: #include resolution, define injection, shadow budget.

Free functions, no ``self`` coupling: they read ``.glsl`` files under
:data:`SHADER_DIR`, splice ``#include``s, and inject the per-driver
``#define``/``#extension`` lines. This is the shader *text* pipeline;
:mod:`shaderpass` is the GL program object that consumes it. :mod:`shaderpass`
re-exports :data:`SHADER_DIR` and :func:`preprocess_shader`, both imported by
tests and sibling passes.
"""
from __future__ import annotations

import os
import re
import logging
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# Path to shader files
SHADER_DIR: str = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'shaders')

# Legacy marker kept for the shadow-packing source test; live shaders now pull the
# shared shadow code in with a normal `#include "_shadow_inc.glsl"` (below).
SHADOW_INCLUDE_MARKER: str = '//#pragma shadow_include'
SHADOW_INCLUDE_PATH: str = os.path.join(SHADER_DIR, '_shadow_inc.glsl')

# `#include "file.glsl"` on its own line, resolved relative to SHADER_DIR.
_INCLUDE_RE = re.compile(r'^[ \t]*#include[ \t]+"([^"]+)"[ \t]*(?://.*)?$')

# Ceiling on simultaneous shadow-casting lights; the actual count is derived per
# driver from GL_MAX_TEXTURE_IMAGE_UNITS but never exceeds this.
HARD_MAX_SHADOW_LIGHTS: int = 4


def _resolve_includes(src: str, seen: set) -> str:
    """Splice `#include "..."` directives from SHADER_DIR into ``src``.

    Includes are resolved recursively (an include may include another) and each
    file is spliced at most once per translation unit -- an include guard, so a
    shared helper (e.g. _common_inc.glsl) pulled in by several includes is not
    redefined. Anything that is not an include line passes through untouched, so
    a shader with no includes round-trips exactly.
    """
    out = []
    for line in src.split('\n'):
        m = _INCLUDE_RE.match(line)
        if not m:
            out.append(line)
            continue
        path = os.path.normpath(os.path.join(SHADER_DIR, m.group(1)))
        if path in seen:
            continue
        seen.add(path)
        with open(path, 'r') as f:
            inc = f.read()
        out.append('// --- begin include %s ---' % m.group(1))
        out.append(_resolve_includes(inc, seen))
        out.append('// --- end include %s ---' % m.group(1))
    return '\n'.join(out)


def preprocess_shader(filename: str, defines: Optional[list] = None) -> str:
    """Read a shader, resolve its ``#include``s, inject ``defines`` after #version.

    ``defines`` is a list of literal preprocessor lines (``#define`` / ``#extension``)
    spliced immediately after the ``#version`` directive -- the only place
    ``#extension`` is legal -- so the same on-disk source serves every driver tier.
    Included files must NOT carry their own ``#version``; the top-level file owns it.
    """
    with open(os.path.join(SHADER_DIR, filename), 'r') as f:
        src = f.read()
    src = _resolve_includes(src, set())
    if defines:
        lines = src.split('\n')
        for i, line in enumerate(lines):
            if line.lstrip().startswith('#version'):
                lines[i + 1:i + 1] = list(defines)
                break
        src = '\n'.join(lines)
    return src


def shadow_defines(max_shadow_lights: int, cube_array: bool) -> list:
    """Compile-time defines that bake the driver's shadow budget into a shader."""
    defines = []
    if cube_array:
        defines.append('#extension GL_ARB_texture_cube_map_array : require')
    defines.append('#define MAX_SHADOW_LIGHTS %d' % int(max_shadow_lights))
    if cube_array:
        defines.append('#define SHADOW_CUBE_ARRAY 1')
    return defines


def resolve_shadow_config() -> Tuple[int, bool]:
    """(max_shadow_lights, use_cube_array) for the current GL context.

    Derived from the driver's real per-stage GL_MAX_TEXTURE_IMAGE_UNITS so the lit
    program never over-subscribes fragment texture units. Falls back to a
    conservative baseline if no context / detection fails.
    """
    try:
        from OpenGLContext.passes.shadowcaps import ShadowCapabilities
        caps = ShadowCapabilities.detect(None)
        n = max(1, min(HARD_MAX_SHADOW_LIGHTS, caps.max_shadow_lights()))
        return n, bool(caps.has_cube_array)
    except Exception as err:
        log.warning("Shadow config detection failed (%s); using baseline", err)
        return 1, False


def load_fragment_source(filename: str, max_shadow_lights: int,
                         cube_array: bool, extra_defines: Optional[list] = None) -> str:
    """Read a lit fragment shader assembled for the current driver tier.

    Resolves its ``#include``s (the shared shadow / BRDF / colour code) and injects
    the shadow budget defines (``MAX_SHADOW_LIGHTS``, and ``SHADOW_CUBE_ARRAY`` plus
    the enabling ``#extension`` when cube-arrays are available), so the same source
    serves every driver tier. ``extra_defines`` appends further ``#define`` lines
    (e.g. the sampler-budget gate for extension textures)."""
    return preprocess_shader(
        filename, shadow_defines(max_shadow_lights, cube_array) + list(extra_defines or []))
