"""Offscreen rendering on Windows: a WGL pbuffer and no window

A WGL context on a pbuffer needs no window on screen, no compositor and nobody
logged in looking at it: it renders on the display driver's own memory and gives
you the pixels back.  That makes it the context to use on a build machine, in a
batch renderer, in a service that returns images over HTTP, or anywhere a window
would be a nuisance rather than a feature.  It is the Windows counterpart of
:mod:`OpenGLContext.windowsystem.egl`, which does the same on Linux, and what
``windowsystem='offscreen'`` opens on Windows.

A context on it is a context like any other, so a scenegraph, the render
passes, the caches, the screenshot machinery and the H.264 recorder all work
unchanged::

    from OpenGLContext.context import Context

    class Offscreen(Context):
        def Render(self, mode=None):
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    Offscreen.ContextMainLoop(windowsystem='wgl', size=(640, 480))

Rendering goes to a pbuffer, which is a real default framebuffer.  Every pass
that draws to framebuffer zero, reads it back or takes a screenshot therefore
behaves as it does on a window, and nothing has to know it is offscreen.

**One window is created and never shown.**  The WGL calls that build a pbuffer
are extensions, and an extension entry point on Windows is resolved through a
context that already exists -- so there is a chicken and egg, and a hidden 1x1
window is the way out of it.  ``OpenGL.WGL.offscreen`` makes one per process,
never shows it and never gives it a message loop, and the pbuffer outlives it.
The consequence worth knowing is that this needs a window station and a desktop,
which a service running in session 0 has; what it does not need is anything on
screen, a compositor, or a remote-desktop connection that stays open.

**Which driver renders.**  Windows has no device enumeration to choose from as
EGL does: the pbuffer is created on the display driver bound to the process.
``OPENGLCONTEXT_WGL_ANY_ACCELERATION`` accepts a pixel format that does not call
itself fully accelerated, which is what an unusual or virtualised adapter may
need; by default only an accelerated format is taken.

**Where this works.**  ``WGL_ARB_pbuffer``, ``WGL_ARB_pixel_format`` and
``WGL_ARB_create_context`` are what the driver has to offer, and every hardware
OpenGL driver for Windows has offered them for well over a decade.  Microsoft's
fallback rasteriser -- what a machine with no vendor driver installed has --
offers none of them.  Opening a context there raises
:class:`WGLContextError` naming what is missing rather than failing obscurely,
so an application can try it and fall back to a hidden window
(``OPENGLCONTEXT_HIDDEN=1`` on any windowing backend renders and reads back
identically; what it cannot do is run with no desktop).
"""

import logging
from collections.abc import Hashable, Mapping, Sequence
from typing import Any, Optional

from OpenGL.WGL import offscreen as wgloffscreen

from OpenGLContext import renderoptions
from OpenGLContext.windowsystem.base import WindowSystem

log = logging.getLogger(__name__)

__all__ = (
    'WGLContextError',
    'WGLWindowSystem',
    'ACCELERATION_VARIABLE',
    'acceleration',
    'available',
    'bufferSizes',
)

#: Environment variable accepting a pixel format that is not fully accelerated.
ACCELERATION_VARIABLE = 'OPENGLCONTEXT_WGL_ANY_ACCELERATION'

#: Values of :data:`ACCELERATION_VARIABLE` that mean "no".  An unset variable
#: and an empty one agree, because that is what an unexported shell variable
#: expands to.
_OFF = ('', '0', 'false', 'no', 'off')


class WGLContextError(RuntimeError):
    """An offscreen context could not be created, or was misconfigured."""


def acceleration(environ: Optional[Mapping[str, str]] = None) -> str:
    """Which pixel formats this environment will accept, for `offscreen`.

    ``'accelerated'`` normally, and ``'any'`` where the environment has asked
    for it.  A format the GPU does not draw is slow rather than wrong, so this
    is the difference between rendering and refusing on an adapter that
    advertises no fully-accelerated pbuffer format.
    """
    if environ is None:
        environ = renderoptions.environment()
    if environ.get(ACCELERATION_VARIABLE, '').strip().lower() not in _OFF:
        return 'any'
    return 'accelerated'


def available(profile: str = 'core') -> Sequence[str]:
    """The WGL extensions this machine lacks before it can render offscreen.

    Empty means yes.  Answers without creating anything, so an application can
    choose between this and a window before committing to either.
    """
    missing: Sequence[str] = wgloffscreen.available(profile)
    return missing


def bufferSizes(definition: Any) -> dict[str, Any]:
    """The buffer request a :class:`ContextDefinition` becomes.

    Split out because it is the whole of the translation between this package's
    settings and WGL's, and it is worth being able to read what a definition
    asked for without a Windows machine to ask.  Sizes of zero or less are left
    out rather than requested as zero, so the driver picks; that is what a
    definition default of ``-1`` means.

    The colour buffer is eight bits a channel and the definition's ``rgb`` field
    does not reach here: its other value asks for a colour-index buffer, which
    is ``WGL_TYPE_COLORINDEX_ARB``, and no driver has offered a pbuffer format
    with one for many years.  Asking for it would be a request that cannot be
    met rather than a setting.
    """
    return {
        'color_bits': 24,
        'alpha_bits': 8 if definition.alpha else 0,
        'depth_bits': definition.depthBuffer if definition.depthBuffer > 0 else 24,
        'stencil_bits': max(0, definition.stencilBuffer),
        'samples': max(0, definition.multisampleSamples),
        # Nothing presents a pbuffer, so a back buffer nobody swaps is memory
        # spent on nothing -- SwapBuffers below is a flush.
        'double_buffer': False,
    }


def profileFor(definition: Any) -> tuple[str, tuple[int, ...]]:
    """``(profile, version)`` for ``offscreen``, from a context definition.

    The profile mask arrived with GL 3.2 and a driver refuses a request below
    that which carries one, so a definition asking for an older version gets
    ``'legacy'`` -- no profile named, which is the fixed-function pipeline.
    """
    version = tuple(int(value) for value in definition.version)
    profile = (definition.profile or 'compatibility').lower()
    if version < (3, 2):
        return 'legacy', version if version > (0, 0) else (1, 1)
    return ('core' if profile == 'core' else 'compatibility'), version


class WGLWindowSystem(WindowSystem):
    """A pbuffer on the display driver, and no window on screen.

    Nothing *outside* delivers a keystroke or a mouse move, but the context's
    event machinery is fully present and can be driven through
    :func:`OpenGLContext.events.synthetic.dispatch`, exactly as on
    :class:`~OpenGLContext.windowsystem.egl.EGLWindowSystem`.  The main loop
    renders the context's ``frameCount`` frames and returns.
    ``context.window`` is the :class:`OpenGL.WGL.offscreen.OffscreenContext`.
    """

    name = 'wgl'
    offscreen = True
    pollsEvents = False

    #: The :class:`OpenGL.WGL.offscreen.OffscreenContext` this draws on, or
    #: ``None`` once it has been closed.
    window: Optional[wgloffscreen.OffscreenContext] = None

    def open(self, definition: Any, parent: Any = None) -> bool:
        width, height = [int(value) for value in definition.size]
        profile, version = profileFor(definition)
        try:
            self.window = wgloffscreen.OffscreenContext(
                width=width, height=height, profile=profile, version=version,
                acceleration=acceleration(), **bufferSizes(definition)
            )
        except wgloffscreen.WGLError as error:
            # Raised as this package's own class so a caller catches one thing
            # whichever offscreen window system it asked for.  The advice is to
            # try it and fall back, so a failure is an expected outcome.
            raise WGLContextError(str(error)) from error
        log.info('WGL offscreen context: %r', self.window)
        return True

    def makeCurrent(self) -> Optional[Hashable]:
        if self.window is None:
            return None
        self.window.make_current()
        return self.glHandle()

    def drawableSize(self) -> tuple[int, int]:
        assert self.window is not None
        return int(self.window.width), int(self.window.height)

    def resize(self, width: int, height: int) -> tuple[int, int]:
        """Render at a new size.

        A pbuffer is created at a fixed size and cannot be resized, so this
        builds a replacement and drops the old one.  The GL context survives, so
        textures, buffers and programs are all still there afterwards.
        """
        surface = self.window
        if surface is None:
            raise WGLContextError('this context has been closed')
        try:
            surface.resize(width, height)
        except wgloffscreen.WGLError as error:
            raise WGLContextError(str(error)) from error
        return int(surface.width), int(surface.height)

    def swap(self) -> None:
        """Finish the frame.

        A pbuffer has nothing to present to, so this is a flush: the point at
        which this frame's commands are guaranteed to have been issued to the
        driver, which is what a readback, a capture or an encode after it
        depends on.
        """
        from OpenGL.GL import glFlush

        glFlush()

    def mainLoop(self) -> Any:
        """Render frames until nothing wants another, then let the pbuffer go.

        The context's ``frameCount`` is the floor, and
        :meth:`~OpenGLContext.context.Context.wantsMoreFrames` is what carries
        the loop past it.
        """
        context = self.context
        try:
            frames = max(1, int(context.frameCount))
            drawn = 0
            while self.running() and (drawn < frames or context.wantsMoreFrames()):
                context.OnDraw(force=1)
                drawn += 1
        finally:
            context.stopTelemetry('mainloop-ended')
            self.release()

    def release(self) -> None:
        """Release the GL objects, the context and the pbuffer.

        The engine's caches hold GL objects belonging to this context, so they
        are dropped before it goes: a later context handed the same identifiers
        by the driver would otherwise inherit them.
        """
        surface = self.window
        if surface is None:
            return
        # This context current first: it is the only moment the caches holding
        # its GL names can delete them rather than merely forget them.
        try:
            surface.make_current()
        except Exception:               # pragma: no cover - needs a lost surface
            pass
        self.context.releaseContextResources(self.glHandle())
        self.abandon()

    def abandon(self) -> None:
        """Give back the pbuffer without telling any cache"""
        surface, self.window = self.window, None
        if surface is not None:
            surface.release()
