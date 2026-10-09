"""X_ITE's BlendMode and DepthMode: an appearance's own blending and depth state

An `Appearance`'s `blendMode` names the blend factors and equations its
fragments are combined with the frame by, and makes its shapes blended: they
are drawn with the transparent shapes, back to front. Its `depthMode` names
the depth test, the comparison, whether depth is written, the depth range
and a polygon offset, in whichever pass the shape is drawn. A shape with
either is drawn by itself rather than in an instanced group.

:func:`blend_state` and :func:`depth_state` read the nodes into the GL
values, with no GL: a name OpenGL does not have reads as the field's
default, as X_ITE reads it. :func:`applied` sets them around a draw and puts
back what the pass had.
"""
from __future__ import annotations

import contextlib
from collections.abc import Iterator
from typing import Any, NamedTuple

from OpenGL.GL import (
    GL_ALWAYS, GL_BLEND, GL_CONSTANT_ALPHA, GL_CONSTANT_COLOR, GL_DEPTH_FUNC, GL_DEPTH_TEST,
    GL_DEPTH_WRITEMASK, GL_DST_ALPHA, GL_DST_COLOR, GL_EQUAL, GL_FUNC_ADD,
    GL_FUNC_REVERSE_SUBTRACT, GL_FUNC_SUBTRACT, GL_GEQUAL, GL_GREATER, GL_LEQUAL, GL_LESS,
    GL_MAX, GL_MIN, GL_NEVER, GL_NOTEQUAL, GL_ONE, GL_ONE_MINUS_CONSTANT_ALPHA,
    GL_ONE_MINUS_CONSTANT_COLOR, GL_ONE_MINUS_DST_ALPHA, GL_ONE_MINUS_DST_COLOR,
    GL_ONE_MINUS_SRC_ALPHA, GL_ONE_MINUS_SRC_COLOR, GL_POLYGON_OFFSET_FILL,
    GL_SRC_ALPHA, GL_SRC_ALPHA_SATURATE, GL_SRC_COLOR, GL_ZERO,
    glBlendColor, glBlendEquationSeparate, glBlendFuncSeparate, glDepthFunc, glDepthMask,
    glDepthRange, glDisable, glEnable, glGetBooleanv, glGetIntegerv, glIsEnabled,
    glPolygonOffset,
)
from vrml.x3d import xite

#: OpenGL's blend factors by their X_ITE names (OpenGL's, without `GL_`).
FACTORS = {
    'ZERO': GL_ZERO, 'ONE': GL_ONE, 'SRC_COLOR': GL_SRC_COLOR,
    'ONE_MINUS_SRC_COLOR': GL_ONE_MINUS_SRC_COLOR, 'DST_COLOR': GL_DST_COLOR,
    'ONE_MINUS_DST_COLOR': GL_ONE_MINUS_DST_COLOR, 'SRC_ALPHA': GL_SRC_ALPHA,
    'ONE_MINUS_SRC_ALPHA': GL_ONE_MINUS_SRC_ALPHA, 'DST_ALPHA': GL_DST_ALPHA,
    'ONE_MINUS_DST_ALPHA': GL_ONE_MINUS_DST_ALPHA, 'SRC_ALPHA_SATURATE': GL_SRC_ALPHA_SATURATE,
    'CONSTANT_COLOR': GL_CONSTANT_COLOR, 'ONE_MINUS_CONSTANT_COLOR': GL_ONE_MINUS_CONSTANT_COLOR,
    'CONSTANT_ALPHA': GL_CONSTANT_ALPHA, 'ONE_MINUS_CONSTANT_ALPHA': GL_ONE_MINUS_CONSTANT_ALPHA,
}
#: OpenGL's blend equations by their X_ITE names.
EQUATIONS = {
    'FUNC_ADD': GL_FUNC_ADD, 'FUNC_SUBTRACT': GL_FUNC_SUBTRACT,
    'FUNC_REVERSE_SUBTRACT': GL_FUNC_REVERSE_SUBTRACT, 'MIN': GL_MIN, 'MAX': GL_MAX,
}
#: OpenGL's depth comparisons by DepthMode's names.
COMPARISONS = {
    'NEVER': GL_NEVER, 'LESS': GL_LESS, 'EQUAL': GL_EQUAL, 'LESS_EQUAL': GL_LEQUAL,
    'GREATER': GL_GREATER, 'NOT_EQUAL': GL_NOTEQUAL, 'GREATER_EQUAL': GL_GEQUAL,
    'ALWAYS': GL_ALWAYS,
}


class BlendMode(xite.BlendMode):
    """X_ITE's BlendMode: the blend function an appearance draws with"""


class DepthMode(xite.DepthMode):
    """X_ITE's DepthMode: the depth state an appearance draws with"""


class BlendState(NamedTuple):
    """glBlendFuncSeparate's four factors, glBlendEquationSeparate's two, and the blend colour"""

    source_color: int
    destination_color: int
    source_alpha: int
    destination_alpha: int
    color_equation: int
    alpha_equation: int
    color: "tuple[float, float, float, float]"


class DepthState(NamedTuple):
    """Whether the depth test runs, its comparison, whether depth is written,
    the depth range and the polygon offset's (factor, units)"""

    test: bool
    comparison: int
    write: bool
    near_far: "tuple[float, float]"
    offset: "tuple[float, float]"


def _named(table: "dict[str, int]", value: Any, default: str) -> int:
    return table.get(str(value), table[default])


def blend_state(mode: Any) -> BlendState:
    """The GL blend state a BlendMode node names"""
    color = tuple(float(value) for value in tuple(mode.blendColor)[:4])
    return BlendState(
        _named(FACTORS, mode.sourceColorFactor, 'SRC_ALPHA'),
        _named(FACTORS, mode.destinationColorFactor, 'ONE_MINUS_SRC_ALPHA'),
        _named(FACTORS, mode.sourceAlphaFactor, 'ONE'),
        _named(FACTORS, mode.destinationAlphaFactor, 'ONE_MINUS_SRC_ALPHA'),
        _named(EQUATIONS, mode.colorEquation, 'FUNC_ADD'),
        _named(EQUATIONS, mode.alphaEquation, 'FUNC_ADD'),
        (color[0], color[1], color[2], color[3]),
    )


def depth_state(mode: Any) -> DepthState:
    """The GL depth state a DepthMode node names"""
    near, far = (float(value) for value in tuple(mode.depthRange)[:2])
    factor, units = (float(value) for value in tuple(mode.polygonOffset)[:2])
    return DepthState(bool(mode.depthTest), _named(COMPARISONS, mode.depthFunction, 'LESS_EQUAL'),
                      bool(mode.depthMask), (near, far), (factor, units))


def modes_of(appearance: Any) -> "tuple[Any, Any]":
    """The (BlendMode, DepthMode) nodes `appearance` has, each None where it has none"""
    blend = getattr(appearance, 'blendMode', None) or None
    depth = getattr(appearance, 'depthMode', None) or None
    return blend, depth


def has_modes(appearance: Any) -> bool:
    """Whether `appearance` names a BlendMode or a DepthMode"""
    blend, depth = modes_of(appearance)
    return blend is not None or depth is not None


@contextlib.contextmanager
def applied(appearance: Any) -> Iterator[None]:
    """`appearance`'s blend and depth state for the block, the pass's after it

    The pass blends its transparent shapes with (SRC_ALPHA,
    ONE_MINUS_SRC_ALPHA) and FUNC_ADD, which is what is put back after a
    BlendMode, with blending switched off again where it was off; the depth
    test, its comparison and the depth writes are read before a DepthMode and
    put back as they were, and the range and polygon offset return to (0, 1)
    and none.
    """
    blend, depth = modes_of(appearance)
    if blend is None and depth is None:
        yield
        return
    restore_depth = None
    if depth is not None:
        state = depth_state(depth)
        restore_depth = (bool(glIsEnabled(GL_DEPTH_TEST)), int(glGetIntegerv(GL_DEPTH_FUNC)),
                         bool(glGetBooleanv(GL_DEPTH_WRITEMASK)))
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(*state.offset)
        if state.test:
            glEnable(GL_DEPTH_TEST)
            glDepthFunc(state.comparison)
        else:
            glDisable(GL_DEPTH_TEST)
        glDepthRange(*state.near_far)
        glDepthMask(state.write)
    blending = None
    if blend is not None:
        found = blend_state(blend)
        blending = bool(glIsEnabled(GL_BLEND))
        glEnable(GL_BLEND)
        glBlendColor(*found.color)
        glBlendFuncSeparate(found.source_color, found.destination_color,
                            found.source_alpha, found.destination_alpha)
        glBlendEquationSeparate(found.color_equation, found.alpha_equation)
    try:
        yield
    finally:
        if blending is not None:
            glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
                                GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glBlendEquationSeparate(GL_FUNC_ADD, GL_FUNC_ADD)
            if not blending:
                glDisable(GL_BLEND)
        if restore_depth is not None:
            test, comparison, write = restore_depth
            glDisable(GL_POLYGON_OFFSET_FILL)
            (glEnable if test else glDisable)(GL_DEPTH_TEST)
            glDepthFunc(comparison)
            glDepthRange(0.0, 1.0)
            glDepthMask(write)
