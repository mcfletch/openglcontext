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
from functools import lru_cache
from typing import Dict, FrozenSet, Optional, Tuple

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

#: A vertex input declaration and the word its own trailing comment leads with:
#: ``layout(location = 3) in vec4 aTangent;   // optional: zero disables ...``
_INPUT_RE = re.compile(
    r'^[ \t]*layout[ \t]*\([ \t]*location[ \t]*=[ \t]*\d+[ \t]*\)'
    r'[ \t]*in[ \t]+\w+[ \t]+(\w+)[ \t]*;'
    r'[ \t]*(?://[ \t]*(\w+))?',
    re.MULTILINE)

#: The marker that says a shader has no meaning for an input's default value.
#: Its counterpart, ``optional``, is what every other input carries: an
#: uber-shader declares more arrays than any one geometry holds, and reads each
#: of them only where a uniform says it is there.
REQUIRED_MARKER: str = 'required'


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


def input_markers(source: str) -> Dict[str, str]:
    """Each vertex input ``source`` declares, and the marker it carries.

    The marker is the first word of the comment on the declaration's own line,
    and ``''`` where there is none.
    """
    return dict(_INPUT_RE.findall(source))


@lru_cache(maxsize=None)
def required_inputs(filename: str) -> FrozenSet[str]:
    """The vertex arrays the shader in ``filename`` cannot be drawn without.

    Everything else it declares has a meaning at the value GL supplies when
    nothing feeds it -- a zero tangent disables normal mapping, an absent skin
    leaves the rest pose -- so a geometry that does not carry it draws correctly
    rather than silently wrongly. The engine's shaders say which is which at the
    declaration (:data:`REQUIRED_MARKER`), and that is what
    :func:`OpenGLContext.scenegraph.geometryarrays.report_missing_inputs`
    reports against.

    Includes are resolved first, so an input a shared block declares (the
    skinning weights) is described where it is declared.
    """
    return frozenset(
        name for name, marker in input_markers(preprocess_shader(filename)).items()
        if marker == REQUIRED_MARKER
    )


def shadow_defines(max_shadow_lights: int, cube_array: bool) -> list:
    """Compile-time defines that bake the driver's shadow budget into a shader."""
    defines = []
    if cube_array:
        defines.append('#extension GL_ARB_texture_cube_map_array : require')
    defines.append('#define MAX_SHADOW_LIGHTS %d' % int(max_shadow_lights))
    if cube_array:
        defines.append('#define SHADOW_CUBE_ARRAY 1')
    return defines


#: The answer, once a real context has given one. A shader compile asks for it
#: and a scene that streams new materials compiles as it goes, so asking the
#: driver each time is a measurable part of the frame.
_SHADOW_CONFIG: "Optional[Tuple[int, bool]]" = None


def reset_shadow_config() -> None:
    """Forget the resolved budget, so the next ask reaches the driver again."""
    global _SHADOW_CONFIG
    _SHADOW_CONFIG = None


def resolve_shadow_config() -> Tuple[int, bool]:
    """(max_shadow_lights, use_cube_array) for the current GL context.

    Derived from the driver's real per-stage GL_MAX_TEXTURE_IMAGE_UNITS so the lit
    program never over-subscribes fragment texture units. Falls back to a
    conservative baseline if no context / detection fails.
    """
    global _SHADOW_CONFIG
    if _SHADOW_CONFIG is not None:
        return _SHADOW_CONFIG
    try:
        from OpenGLContext.passes.shadowcaps import ShadowCapabilities
        caps = ShadowCapabilities.detect(None)
        n = max(1, min(HARD_MAX_SHADOW_LIGHTS, caps.max_shadow_lights()))
        config = (n, bool(caps.has_cube_array))
        if caps.detected:
            _SHADOW_CONFIG = config
        return config
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
