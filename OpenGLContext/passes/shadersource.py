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
from typing import Dict, FrozenSet, List, NamedTuple, Optional, Tuple

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
    return inject_defines(_resolve_includes(src, set()), defines)


def inject_defines(source: str, defines: Optional[list] = None) -> str:
    """``source`` with ``defines`` spliced in immediately after its ``#version``."""
    if not defines:
        return source
    lines = source.split('\n')
    for i, line in enumerate(lines):
        if line.lstrip().startswith('#version'):
            lines[i + 1:i + 1] = list(defines)
            break
    return '\n'.join(lines)


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


# -- the geometry stage of a shared multi-view draw ---------------------------

#: A vertex output declared at the top level: ``flat out uint vObjectId;``.
_OUTPUT_RE = re.compile(
    r'(?:^|(?<=;))[ \t]*(flat[ \t]+)?out[ \t]+(\w+)[ \t]+(\w+)[ \t]*;', re.MULTILINE)

#: The prefix a vertex output is renamed with when a geometry stage reads it.
GEOMETRY_INPUT_PREFIX = 'gs_'


class VertexOutput(NamedTuple):
    """One value the vertex stage hands on: its GLSL type, name and qualifier."""

    type: str
    name: str
    flat: bool


#: What the multi-view routing itself declares, which is never handed on.
_ROUTING_OUTPUTS = frozenset(('vView',))


def vertex_outputs(source: str) -> List[VertexOutput]:
    """Every ``out`` the vertex shader ``source`` hands on to be shaded, in order.

    ``vView``, which the vertex strategy's routing declares for itself, is not
    among them: a geometry stage writes its own.
    """
    return [VertexOutput(kind, name, bool(flat))
            for flat, kind, name in _OUTPUT_RE.findall(source)
            if name not in _ROUTING_OUTPUTS]


def vertex_routing_source(vertex_source: str, views: int, extension: str) -> str:
    """``vertex_source`` compiled to route each instanced copy to its view.

    GLSL 4.10 with the extension that gives the vertex stage
    ``gl_ViewportIndex``, and ``MULTIVIEW_VERTEX`` switching on the
    ``routeToView`` call each lit vertex shader ends with.
    """
    lines = vertex_source.split('\n')
    for index, line in enumerate(lines):
        if line.lstrip().startswith('#version'):
            lines[index] = '#version 410 core'
            break
    return inject_defines('\n'.join(lines), [
        '#extension %s : require' % extension,
        '#define MULTIVIEW_VIEWS %d' % int(views),
        '#define MULTIVIEW_VERTEX 1',
    ])


def geometry_input_defines(source: str) -> List[str]:
    """``#define`` lines renaming each vertex output for a geometry stage to read.

    Spliced into the vertex shader after its ``#version``, they rename the
    declaration and every write to it, so the geometry stage can read
    ``gs_vNormal`` and write ``vNormal`` -- the name the fragment shader reads.
    """
    return ['#define %s %s%s' % (output.name, GEOMETRY_INPUT_PREFIX, output.name)
            for output in vertex_outputs(source)]


def geometry_stage_source(vertex_source: str, views: int,
                          gl_version: Tuple[int, int],
                          position: str = 'vPosition') -> str:
    """A geometry shader sending each triangle to the views in ``viewMask``.

    Generated from the vertex shader it follows, so the two agree about what
    passes between them. It is invoked once per view; an invocation whose view
    is not in the draw's mask emits nothing, and one whose view is emits the
    triangle with its ``gl_ViewportIndex`` and with ``gl_Position`` taken from
    ``position`` -- an eye-space position in the reference camera's space --
    through that view's ``refToClip``. ``vView`` tells the fragment shader
    which view it is shading.

    ``gl_version`` picks the header: GLSL 4.10 has both the invocations and the
    viewport index; 4.00 asks for viewport arrays; 3.30 asks for both.
    """
    from OpenGLContext.multiview.strategy import MAX_VIEWS
    if not 2 <= int(views) <= MAX_VIEWS:
        raise ValueError('a shared draw reaches 2 to %d views, not %r'
                         % (MAX_VIEWS, views))
    if tuple(gl_version) >= (4, 1):
        header = ['#version 410 core']
    elif tuple(gl_version) >= (4, 0):
        header = ['#version 400 core',
                  '#extension GL_ARB_viewport_array : require']
    else:
        header = ['#version 330 core',
                  '#extension GL_ARB_gpu_shader5 : require',
                  '#extension GL_ARB_viewport_array : require']
    outputs = vertex_outputs(vertex_source)
    if not any(output.name == position for output in outputs):
        raise ValueError('the vertex stage declares no %r to project' % (position,))
    lines = header + [
        '#define MULTIVIEW_VIEWS %d' % int(views),
        '#include "_multiview_inc.glsl"',
        'layout(triangles, invocations = %d) in;' % int(views),
        'layout(triangle_strip, max_vertices = 3) out;',
        'uniform uint viewMask;',
    ]
    for output in outputs:
        flat = 'flat ' if output.flat else ''
        lines.append('%sin %s %s%s[];' % (
            flat, output.type, GEOMETRY_INPUT_PREFIX, output.name))
        lines.append('%sout %s %s;' % (flat, output.type, output.name))
    lines += [
        'flat out int vView;',
        'void main() {',
        '    int view = gl_InvocationID;',
        '    if (((viewMask >> uint(view)) & 1u) == 0u) return;',
        '    for (int i = 0; i < 3; ++i) {',
    ]
    for output in outputs:
        lines.append('        %s = %s%s[i];' % (
            output.name, GEOMETRY_INPUT_PREFIX, output.name))
    lines += [
        '        vView = view;',
        '        gl_ViewportIndex = view;',
        '        gl_Position = views[view].refToClip * vec4(%s%s[i], 1.0);'
        % (GEOMETRY_INPUT_PREFIX, position),
        '        EmitVertex();',
        '    }',
        '    EndPrimitive();',
        '}',
    ]
    return _resolve_includes('\n'.join(lines), set())
