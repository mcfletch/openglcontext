"""What a frame of a scene nothing has changed in asks of GL.

A frame drawn again over a scene that has not changed should find every
buffer, texture, program and vertex array already made and already filled:
the first frame builds them, and the next ones only bind and draw. A GL
object made, a buffer filled or a program compiled in the second frame is
work repeated every frame for ever, in every application with a still
moment -- a paused game, a menu over a level, an editor waiting for input.

:func:`check_still_frame` draws the scene's first frames, then counts the GL
calls one more frame makes and fails where the allocations, uploads or
compiles exceed the floor the test gives::

    from OpenGLContext.testing.scenes import scene_context
    from OpenGLContext.testing.stillframe import check_still_frame

    with scene_context(children) as context:
        check_still_frame(lambda: context.OnDraw(force=1), uploads=2)

The count is taken by a shim, :func:`counting_gl`, which replaces each
counted GL entry point, wherever a loaded module or PyOpenGL's buffer
implementation holds it, with a wrapper that counts and calls through, and
puts every one back afterwards. It counts calls made through the Python
bindings from any thread while it is in place, through a module's namespace
or an import made while it is in place; an entry point a function bound to a
local name before the count began is not counted.
"""
from __future__ import annotations

import contextlib
import sys
from collections import Counter
from dataclasses import dataclass, field
from collections.abc import Callable, Iterable, Iterator
from typing import Any

__all__ = ['ALLOCATIONS', 'COMPILES', 'StillFrameWork', 'FrameWork', 'UPLOADS',
           'check_still_frame', 'counting_gl', 'still_frame_work']

#: Entry points that make a GL object.
ALLOCATIONS = (
    'glGenBuffers', 'glGenTextures', 'glGenVertexArrays', 'glGenFramebuffers',
    'glGenRenderbuffers', 'glGenQueries', 'glGenSamplers', 'glGenLists',
    'glCreateProgram', 'glCreateShader',
)
#: Entry points that fill a buffer's or a texture's storage.
UPLOADS = (
    'glBufferData', 'glBufferSubData', 'glTexImage1D', 'glTexImage2D',
    'glTexImage3D', 'glTexSubImage1D', 'glTexSubImage2D', 'glTexSubImage3D',
    'glTexStorage2D', 'glTexStorage3D', 'glCompressedTexImage2D',
    'glGenerateMipmap',
)
#: Entry points that compile or link a program.
COMPILES = ('glCompileShader', 'glLinkProgram')


class StillFrameWork(AssertionError):
    """A frame of an unchanged scene made, filled or compiled more than its floor."""


@dataclass
class FrameWork:
    """The counted GL calls of one frame, by entry point."""

    calls: Counter = field(default_factory=Counter)
    #: The same calls by where they were made: ``(entry point, 'module:line')``
    #: of the nearest caller outside PyOpenGL.
    sites: Counter = field(default_factory=Counter)

    def _total(self, names: Iterable[str]) -> int:
        return sum(self.calls[name] for name in names)

    @property
    def allocations(self) -> int:
        return self._total(ALLOCATIONS)

    @property
    def uploads(self) -> int:
        return self._total(UPLOADS)

    @property
    def compiles(self) -> int:
        return self._total(COMPILES)

    def __str__(self) -> str:
        counted = ', '.join('%s %d' % item for item in sorted(self.calls.items()))
        where = ', '.join('%s at %s x%d' % (name, site, count)
                          for (name, site), count in sorted(self.sites.items()))
        return ('%d allocations, %d uploads, %d compiles (%s)%s'
                % (self.allocations, self.uploads, self.compiles,
                   counted or 'no counted calls', where and ': ' + where))


def _holders() -> list[dict[str, Any]]:
    """Every namespace a GL entry point may be called through."""
    holders = [vars(module) for module in list(sys.modules.values())
               if module is not None and hasattr(module, '__dict__')]
    vbo = sys.modules.get('OpenGL.arrays.vbo')
    chosen = getattr(getattr(vbo, 'Implementation', None), 'CHOSEN', None)
    if chosen is not None:
        holders.append(vars(chosen))
    return holders


def _site(frame: Any) -> str:
    """``module:line`` of the nearest frame outside PyOpenGL."""
    while frame is not None:
        name = frame.f_globals.get('__name__', '') or ''
        if name != 'OpenGL' and not name.startswith('OpenGL.'):
            return '%s:%d' % (name, frame.f_lineno)
        frame = frame.f_back
    return '?'


@contextlib.contextmanager
def counting_gl(names: Iterable[str] = ALLOCATIONS + UPLOADS + COMPILES
                ) -> Iterator[FrameWork]:
    """Count calls of the GL entry points ``names`` while the block runs.

    Yields a :class:`FrameWork`, filled as the calls are made. An entry
    point is found by identity with ``OpenGL.GL``'s, so a module that
    imported it under another name is counted as well.
    """
    from OpenGL import GL
    work = FrameWork()
    counts, sites = work.calls, work.sites
    originals: dict[int, tuple[str, Any]] = {}
    for name in names:
        function = getattr(GL, name, None)
        if function is not None:
            originals[id(function)] = (name, function)
    wrappers: dict[int, Any] = {}
    for key, (name, function) in originals.items():
        def counted(*args: Any, _name: str = name, _function: Any = function,
                    **named: Any) -> Any:
            counts[_name] += 1
            sites[(_name, _site(sys._getframe(1)))] += 1
            return _function(*args, **named)
        wrappers[key] = counted
    replaced: list[tuple[dict[str, Any], str, Any]] = []
    for holder in _holders():
        for attribute, value in list(holder.items()):
            wrapper = wrappers.get(id(value))
            if wrapper is not None and originals[id(value)][1] is value:
                holder[attribute] = wrapper
                replaced.append((holder, attribute, value))
    try:
        yield work
    finally:
        for holder, attribute, value in replaced:
            holder[attribute] = value


def still_frame_work(draw: Callable[[], object], *, warmup: int = 3) -> FrameWork:
    """The counted GL calls of the frame ``draw`` makes after ``warmup`` frames."""
    for _ in range(warmup):
        draw()
    with counting_gl() as work:
        draw()
    return work


def check_still_frame(draw: Callable[[], object], *, allocations: int = 0,
                      uploads: int = 0, compiles: int = 0,
                      warmup: int = 3) -> FrameWork:
    """The :class:`FrameWork` of a still frame; raise where it is over a floor.

    Raises :class:`StillFrameWork` naming the counts where the frame made
    more than ``allocations`` GL objects, filled more than ``uploads``
    buffers or textures, or compiled or linked more than ``compiles``
    times.
    """
    work = still_frame_work(draw, warmup=warmup)
    over = [
        '%s: %d, the floor is %d' % (kind, found, floor)
        for kind, found, floor in (('allocations', work.allocations, allocations),
                                   ('uploads', work.uploads, uploads),
                                   ('compiles', work.compiles, compiles))
        if found > floor]
    if over:
        raise StillFrameWork('a still frame did more than its floor: %s; %s'
                             % ('; '.join(over), work))
    return work
