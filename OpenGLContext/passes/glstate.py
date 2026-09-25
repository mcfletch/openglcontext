"""GL state a draw changes and puts back, as context managers.

A draw that switches blending on, binds its own framebuffer or narrows the
scissor has to put each back whether it finishes or raises part way: left
behind, scissoring clips the next view, the offscreen framebuffer takes the
next frame, reversed culling turns the next pass inside out. Each manager here
sets the state on entry and restores what was there before on exit, in a
``finally``::

    from OpenGLContext.passes import glstate

    with glstate.enabled(GL_BLEND), glstate.bound_framebuffer(target):
        draw()

What was there before is asked of GL on entry (``glIsEnabled``,
``glGetIntegerv``), unless the caller already knows it and passes
``restore=``, which a draw issued once per node does to keep the query off its
path.

:func:`frame_baseline` is the other half: the state a frame (or a pass) starts
from, set outright at its start, so that nothing a previous frame left behind
survives into this one.

The OGC151 rule of ``openglcontext-checks`` holds the engine's draw code to
these managers or a ``try/finally`` (see ``docs/checks.rst``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Optional

import numpy as np
from OpenGL.GL import (
    GL_CULL_FACE_MODE,
    GL_CURRENT_PROGRAM,
    GL_DRAW_FRAMEBUFFER,
    GL_DRAW_FRAMEBUFFER_BINDING,
    GL_FRAMEBUFFER,
    GL_READ_FRAMEBUFFER,
    GL_READ_FRAMEBUFFER_BINDING,
    GL_SCISSOR_BOX,
    GL_SCISSOR_TEST,
    glBindFramebuffer,
    glCullFace,
    glDisable,
    glEnable,
    glGetIntegerv,
    glIsEnabled,
    glScissor,
    glUseProgram,
)

__all__ = [
    'bound_framebuffer',
    'cull_face',
    'disabled',
    'enabled',
    'frame_baseline',
    'program',
    'scissor',
    'switched',
]

#: The binding query of each framebuffer target.
_BINDINGS = {
    GL_DRAW_FRAMEBUFFER: GL_DRAW_FRAMEBUFFER_BINDING,
    GL_READ_FRAMEBUFFER: GL_READ_FRAMEBUFFER_BINDING,
}


def _integers(name: int) -> list[int]:
    """The integers ``glGetIntegerv(name)`` answers."""
    return [int(value) for value in np.asarray(glGetIntegerv(name)).ravel()]


def _set(capability: int, on: bool) -> None:
    (glEnable if on else glDisable)(capability)


@contextmanager
def switched(enable: Iterable[int] = (), disable: Iterable[int] = ()) -> Iterator[None]:
    """Capabilities switched on and off for the block, each put back after it."""
    wanted = [(capability, True) for capability in enable]
    wanted += [(capability, False) for capability in disable]
    before = [(capability, bool(glIsEnabled(capability))) for capability, _ in wanted]
    try:
        for capability, on in wanted:
            _set(capability, on)
        yield
    finally:
        for capability, was in reversed(before):
            _set(capability, was)


def enabled(*capabilities: int) -> AbstractContextManager[None]:
    """``capabilities`` on for the block, each put back as it was after it."""
    return switched(enable=capabilities)


def disabled(*capabilities: int) -> AbstractContextManager[None]:
    """``capabilities`` off for the block, each put back as it was after it."""
    return switched(disable=capabilities)


@contextmanager
def bound_framebuffer(framebuffer: int, target: int = GL_FRAMEBUFFER,
                      restore: Optional[int] = None) -> Iterator[None]:
    """``framebuffer`` bound to ``target`` for the block, the previous binding after.

    ``GL_FRAMEBUFFER`` binds both the draw and the read target, and both are
    put back as they were, which may be two different framebuffers.
    ``restore`` names the framebuffer to bind afterwards instead of asking.
    """
    targets = ((GL_DRAW_FRAMEBUFFER, GL_READ_FRAMEBUFFER)
               if target == GL_FRAMEBUFFER else (target,))
    if restore is None:
        before = [(one, _integers(_BINDINGS[one])[0]) for one in targets]
    else:
        before = [(one, int(restore)) for one in targets]
    glBindFramebuffer(target, framebuffer)
    try:
        yield
    finally:
        for one, previous in before:
            glBindFramebuffer(one, previous)


@contextmanager
def program(name: int, restore: Optional[int] = None) -> Iterator[None]:
    """Program ``name`` in use for the block, the previous one after it.

    ``restore`` names the program to use afterwards instead of asking, as a
    node does with the pass's own record of the program it has bound.
    """
    previous = _integers(GL_CURRENT_PROGRAM)[0] if restore is None else int(restore)
    glUseProgram(name)
    try:
        yield
    finally:
        glUseProgram(previous)


@contextmanager
def scissor(x: int, y: int, width: int, height: int) -> Iterator[None]:
    """Drawing clipped to a rectangle for the block; the test and box put back after."""
    was = bool(glIsEnabled(GL_SCISSOR_TEST))
    box = _integers(GL_SCISSOR_BOX)
    glScissor(int(x), int(y), max(0, int(width)), max(0, int(height)))
    glEnable(GL_SCISSOR_TEST)
    try:
        yield
    finally:
        glScissor(*box)
        _set(GL_SCISSOR_TEST, was)


@contextmanager
def cull_face(mode: int) -> Iterator[None]:
    """``glCullFace(mode)`` for the block, the previous face after it."""
    previous = _integers(GL_CULL_FACE_MODE)[0]
    glCullFace(mode)
    try:
        yield
    finally:
        glCullFace(previous)


def frame_baseline(enable: Iterable[int] = (), disable: Iterable[int] = (),
                   cull_face: Optional[int] = None,
                   framebuffer: Optional[int] = None) -> None:
    """Set the state a frame or a pass starts from, outright.

    Nothing puts it back: the next frame sets it again, which is what makes a
    frame independent of whatever the one before it left behind. ``framebuffer``
    binds that framebuffer to both targets.
    """
    if framebuffer is not None:
        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer)
    for capability in enable:
        glEnable(capability)
    for capability in disable:
        glDisable(capability)
    if cull_face is not None:
        glCullFace(cull_face)
