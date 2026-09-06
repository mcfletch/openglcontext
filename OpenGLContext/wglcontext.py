"""Offscreen rendering context on Windows.

A WGL context on a pbuffer needs no window on screen, no compositor and nobody
logged in looking at it: it renders on the display driver's own memory and gives
you the pixels back.  That makes it the context to use on a build machine, in a
batch renderer, in a service that returns images over HTTP, or anywhere a window
would be a nuisance rather than a feature.  It is the Windows counterpart of
:mod:`OpenGLContext.eglcontext`, which does the same on Linux.

It is a context like any other in this package, so a scenegraph, the render
passes, the caches, the screenshot machinery and the H.264 recorder all work
unchanged::

    from OpenGLContext.wglcontext import WGLContext

    class Offscreen(WGLContext):
        def Render(self, mode=None):
            WGLContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    Offscreen.ContextMainLoop(size=(640, 480))

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
offers none of them.  Constructing a :class:`WGLContext` there raises
:class:`WGLContextError` naming what is missing rather than failing obscurely,
so an application can try it and fall back to a hidden window
(``OPENGLCONTEXT_HIDDEN=1`` on any windowing backend renders and reads back
identically; what it cannot do is run with no desktop).
"""

import logging
import os

from OpenGL.WGL import offscreen

from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.interactivecontext import InteractiveContext
from OpenGLContext.move import viewplatformmixin

log = logging.getLogger(__name__)

__all__ = (
    'WGLContext',
    'WGLContextError',
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


def acceleration(environ=None) -> str:
    """Which pixel formats this environment will accept, for `offscreen`.

    ``'accelerated'`` normally, and ``'any'`` where the environment has asked
    for it.  A format the GPU does not draw is slow rather than wrong, so this
    is the difference between rendering and refusing on an adapter that
    advertises no fully-accelerated pbuffer format.
    """
    if environ is None:
        environ = os.environ
    if environ.get(ACCELERATION_VARIABLE, '').strip().lower() not in _OFF:
        return 'any'
    return 'accelerated'


def available(profile: str = 'core'):
    """The WGL extensions this machine lacks before it can render offscreen.

    Empty means yes.  Answers without creating anything, so an application can
    choose between this and a window before committing to either.
    """
    return offscreen.available(profile)


def bufferSizes(definition):
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


def profileFor(definition):
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


class WGLContext(
    viewplatformmixin.ViewPlatformMixin,
    InteractiveContext,
    Context,
):
    """A Context that renders offscreen, on a WGL pbuffer.

    The windowed backends split the bare context from the camera-and-events
    class built on it, because a window can be useful without navigation.  An
    offscreen context cannot: a frame needs a viewpoint, and there is no user to
    steer one.  So the camera is here, and there is no separate interactive
    variant to choose.

    Nothing *outside* delivers a keystroke or a mouse move, but the event
    machinery is fully present and can be driven:
    :func:`OpenGLContext.events.synthetic.dispatch` puts an input record through
    the route the platform would have used, so a test can pick an object, walk
    the camera or dismiss a dialogue with no window and no user::

        from OpenGLContext.events import synthetic
        synthetic.dispatch(context, {'type': 'keyboard', 'key': 'w', 'state': 1})
        synthetic.dispatch(context, {
            'type': 'mousebutton', 'button': 0, 'state': 1,
            'x': 160, 'y': 120, 'pick': True,
        })
        context.OnDraw(force=1)     # a picked event arrives with the pass

    That is the vocabulary telemetry replay and the out-of-process event
    injector already speak, so a script written for one drives the others.

    The time manager drives ``TimeSensor`` as usual, so an animation can be
    rendered frame by frame even though no one is watching it happen.

    A subclass overrides ``Render`` and gets a frame.  ``MainLoop`` renders
    :attr:`frameCount` frames and returns, rather than waiting for a user who is
    not there.
    """

    #: How many frames ``MainLoop`` renders before returning.  One is the
    #: common case -- render an image, read it back -- and an animation that
    #: wants a sequence sets it higher.
    frameCount = 1

    #: The :class:`OpenGL.WGL.offscreen.OffscreenContext` this draws on, or
    #: ``None`` once it has been closed.
    surface = None

    def __init__(self, definition=None, **named):
        # Resolved first: the buffer sizes and the profile are context-creation
        # parameters, so they have to be known before the GL context exists,
        # exactly as the windowed backends resolve them before creating a
        # window.
        definition = self.resolveDefinition(definition, **named)
        self.contextDefinition = definition
        width, height = [int(value) for value in definition.size]
        profile, version = profileFor(definition)

        try:
            self.surface = offscreen.OffscreenContext(
                width=width, height=height, profile=profile, version=version,
                acceleration=acceleration(), **bufferSizes(definition)
            )
        except offscreen.WGLError as error:
            # Raised as this package's own class so a caller catches one thing
            # whichever offscreen backend it asked for.  The module's advice is
            # to try it and fall back, so a failure is an expected outcome.
            raise WGLContextError(str(error)) from error
        log.info('WGL offscreen context: %r', self.surface)

        try:
            Context.__init__(self, definition)
        except BaseException:
            # Not context_lost(): no cache ever saw this context, and announcing
            # its loss would drop another context's objects.
            self.surface.release()
            self.surface = None
            raise
        self.ViewPort(width, height)

    # -- the Context contract ----------------------------------------------

    def setCurrent(self, blocking=1):
        """Take the context and the scenegraph lock, then bind the GL context."""
        Context.setCurrent(self, blocking)
        self.surface.make_current()
        self.bindContextResources(self._glHandle())

    def _glHandle(self):
        """The GL context handle the caches and PyOpenGL key on."""
        return contextresources.context_key()

    def OnResize(self, width, height):
        """Render at a new size.

        A pbuffer is created at a fixed size and cannot be resized, so this
        builds a replacement and drops the old one.  The GL context survives, so
        textures, buffers and programs are all still there afterwards.
        """
        try:
            self.surface.resize(width, height)
        except offscreen.WGLError as error:
            raise WGLContextError(str(error)) from error
        self.contextDefinition.size = (self.surface.width, self.surface.height)
        self.ViewPort(self.surface.width, self.surface.height)
        self.triggerRedraw(1)

    def SwapBuffers(self):
        """Finish the frame.

        A pbuffer has nothing to present to, so this is a flush: the point at
        which this frame's commands are guaranteed to have been issued to the
        driver, which is what a readback, a capture or an encode after it
        depends on.
        """
        from OpenGL.GL import glFlush

        glFlush()

    def MainLoop(self):
        """Render frames until nothing wants another, then release the context.

        :attr:`frameCount` is the floor -- one frame, for the common case of
        rendering an image and reading it back -- and
        :meth:`~OpenGLContext.context.Context.wantsMoreFrames` is what carries
        the loop past it. A settle capture waits out a delay and a frame count
        that are both more than one, and neither is known when the loop starts.
        """
        try:
            frames = max(1, int(self.frameCount))
            drawn = 0
            while drawn < frames or self.wantsMoreFrames():
                # OnDraw takes and releases the context itself, as it does for
                # every other backend.
                self.OnDraw(force=1)
                drawn += 1
        finally:
            self.stopTelemetry('mainloop-ended')
            self.close()

    def close(self):
        """Release the GL objects, the context and the pbuffer.

        The engine's caches hold GL objects belonging to this context, so they
        are dropped before it goes: a later context handed the same identifiers
        by the driver would otherwise inherit them.
        """
        if self.surface is None:
            return
        # With the context still current, which is the only moment the caches
        # holding its GL names can delete them rather than merely forget them.
        self.releaseContextResources(self._glHandle())
        surface, self.surface = self.surface, None
        surface.release()

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
        return False

    @classmethod
    def ContextMainLoop(cls, *args, **named):
        instance = cls(*args, **named)
        if instance.contextDefinition.profileFile:
            import cProfile
            return cProfile.runctx(
                'instance.MainLoop()', globals(), locals(),
                instance.contextDefinition.profileFile,
            )
        return instance.MainLoop()


if __name__ == '__main__':
    from OpenGL.GL import (
        GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor,
    )

    class TestRenderer(WGLContext):
        def Render(self, mode=None):
            WGLContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    TestRenderer.ContextMainLoop()
