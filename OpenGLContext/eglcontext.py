"""Offscreen rendering context on EGL.

An EGL context needs no window, no display server and no compositor: it renders
on a device you name and gives you the pixels back.  That makes it the context
to use on a build machine, in a batch renderer, in a service that returns images
over HTTP, or anywhere a window would be a nuisance rather than a feature.

It is a context like any other in this package, so a scenegraph, the render
passes, the caches and the screenshot machinery all work unchanged::

    from OpenGLContext.eglcontext import EGLContext

    class Offscreen(EGLContext):
        def Render(self, mode=None):
            EGLContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    Offscreen.ContextMainLoop(size=(640, 480))

Rendering goes to a pbuffer, which is a real default framebuffer.  Every pass
that draws to framebuffer zero, reads it back or takes a screenshot therefore
behaves as it does on a window, and nothing has to know it is offscreen.

**Which device gets used.**  A machine may offer several EGL devices -- a GPU
and a CPU rasteriser, or several GPUs.  By default the engine renders on the
first hardware device.  Two things change that:

``OPENGLCONTEXT_EGL_DEVICE``
    An index into the device list, which overrides everything else.  Use it to
    pin a run to one GPU of several.
``LIBGL_ALWAYS_SOFTWARE`` / ``GALLIUM_DRIVER``
    When the environment asks for software rendering, a software device is
    chosen.  This is not merely a courtesy: asking Mesa for a display on a
    *hardware* device while software rendering is demanded is a contradiction it
    refuses and then crashes on, so honouring the request is what keeps the
    process alive.

``devices()`` reports what is available and what each one is.

**Where this works.**  EGL is the GL binding on Linux and Android, and this
backend is for those: PyOpenGL reaches EGL through its Linux platform module,
which selects between EGL and GLX at run time.  Windows has no EGL of its own --
an installed ANGLE or Mesa provides one, but ANGLE offers GL ES rather than
desktop GL, so the ``eglBindAPI(EGL_OPENGL_API)`` this backend needs fails
there.  macOS has no EGL at all.

For offscreen rendering on those platforms, use a windowing backend with a
hidden window: ``OPENGLCONTEXT_HIDDEN=1`` renders and reads back identically,
and is what the test suite uses.  What it cannot do is run with no display
server at all, which is the thing this backend is for.

Where EGL is absent, constructing an ``EGLContext`` raises
:class:`EGLContextError` rather than failing obscurely, so an application can
try it and fall back.
"""

import ctypes
import logging
import os

from OpenGL import EGL
from OpenGL.EGL.devices import DeviceInfo, devices
from OpenGL.EGL.EXT.platform_base import eglGetPlatformDisplayEXT
from OpenGL.EGL.EXT.platform_device import EGL_PLATFORM_DEVICE_EXT

from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.interactivecontext import InteractiveContext
from OpenGLContext.move import viewplatformmixin

log = logging.getLogger(__name__)

__all__ = (
    'EGLContext',
    'EGLContextError',
    'chooseDevice',
    'configAttributes',
    'devices',
    'prefersSoftware',
)

#: Values of ``LIBGL_ALWAYS_SOFTWARE`` that mean "no".  Anything else is a yes,
#: because Mesa itself treats the variable as set-or-not.
_OFF = ('', '0', 'false', 'no', 'off')

#: ``GALLIUM_DRIVER`` values that name a CPU rasteriser.
_SOFTWARE_DRIVERS = ('llvmpipe', 'softpipe', 'swr', 'swrast', 'lavapipe')

#: Environment variable pinning the run to one device by index.
DEVICE_VARIABLE = 'OPENGLCONTEXT_EGL_DEVICE'


class EGLContextError(RuntimeError):
    """An offscreen context could not be created, or was misconfigured."""


def prefersSoftware(environ=None) -> bool:
    """Whether this environment is asking for software rendering."""
    if environ is None:
        environ = os.environ
    if environ.get('LIBGL_ALWAYS_SOFTWARE', '').strip().lower() not in _OFF:
        return True
    return environ.get('GALLIUM_DRIVER', '').strip().lower() in _SOFTWARE_DRIVERS


def chooseDevice(available, environ=None):
    """The device to render on, or ``None`` when there are none.

    An explicit ``OPENGLCONTEXT_EGL_DEVICE`` wins.  Otherwise the first device
    of the preferred kind is taken -- hardware normally, software where the
    environment has asked for it -- falling back to the first device of any kind
    rather than refusing to run.
    """
    if environ is None:
        environ = os.environ
    available = tuple(available)
    if not available:
        return None

    pinned = environ.get(DEVICE_VARIABLE, '').strip()
    if pinned:
        try:
            index = int(pinned)
        except ValueError:
            raise EGLContextError(
                '%s must be a device index, got %r; %d device(s) available'
                % (DEVICE_VARIABLE, pinned, len(available))
            ) from None
        if not 0 <= index < len(available):
            raise EGLContextError(
                '%s=%d is out of range; %d device(s) available'
                % (DEVICE_VARIABLE, index, len(available))
            )
        return available[index]

    wantSoftware = prefersSoftware(environ)
    for device in available:
        if device.software == wantSoftware:
            return device
    # Nothing of the preferred kind. Rendering on the wrong sort of device beats
    # not rendering, and the caller can see what it got from the log.
    log.warning(
        'no %s EGL device available; using %r',
        'software' if wantSoftware else 'hardware',
        available[0],
    )
    return available[0]


def configAttributes(
    depthBuffer=24,
    stencilBuffer=8,
    alpha=False,
    rgb=True,
    multisampleSamples=0,
    multisampleBuffer=0,
):
    """The ``eglChooseConfig`` attribute list for these buffer settings.

    Sizes of zero or less are left out rather than requested as zero, so the
    implementation picks; that is what a :class:`ContextDefinition` default of
    ``-1`` means.  The surface type is always a pbuffer: there is no window, so
    it has to be a surface EGL can make on its own.
    """
    attributes = [
        EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT,
        EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT,
        EGL.EGL_COLOR_BUFFER_TYPE, EGL.EGL_RGB_BUFFER,
    ]
    if rgb:
        attributes += [
            EGL.EGL_RED_SIZE, 8,
            EGL.EGL_GREEN_SIZE, 8,
            EGL.EGL_BLUE_SIZE, 8,
        ]
    if alpha:
        attributes += [EGL.EGL_ALPHA_SIZE, 8]
    if depthBuffer > 0:
        attributes += [EGL.EGL_DEPTH_SIZE, int(depthBuffer)]
    if stencilBuffer > 0:
        attributes += [EGL.EGL_STENCIL_SIZE, int(stencilBuffer)]
    if multisampleSamples > 0:
        attributes += [
            EGL.EGL_SAMPLE_BUFFERS, int(multisampleBuffer) or 1,
            EGL.EGL_SAMPLES, int(multisampleSamples),
        ]
    attributes.append(EGL.EGL_NONE)
    return attributes


def _eglArray(values):
    return (EGL.EGLint * len(values))(*[int(value) for value in values])


class EGLContext(
    viewplatformmixin.ViewPlatformMixin,
    InteractiveContext,
    Context,
):
    """A Context that renders offscreen, on an EGL device.

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

    display = None
    surface = None
    context = None
    device = None
    config = None

    def __init__(self, definition=None, **named):
        # Resolved first: the buffer sizes are config-selection parameters, so
        # they have to be known before the EGL context exists, exactly as the
        # windowed backends resolve them before creating a window.
        definition = self.resolveDefinition(definition, **named)
        self.contextDefinition = definition
        width, height = [int(value) for value in definition.size]

        self.device = self._selectDevice()
        self.display = self._openDisplay(self.device)
        # Kept: a pbuffer has a fixed size, so resizing means making another one
        # against the same config.
        self.config = self._chooseConfig(definition)
        self.context = self._createContext(self.config)
        self.surface = self._createSurface(self.config, width, height)
        # The raw make-current, not setCurrent: the scenegraph lock that one
        # also takes is set up by Context.__init__, which has not run yet.
        self._makeCurrent()

        Context.__init__(self, definition)
        self.ViewPort(width, height)

    # -- construction, one step per EGL call that can fail ------------------

    def _selectDevice(self) -> DeviceInfo:
        available = devices()
        if not available:
            raise EGLContextError(
                'no EGL devices; this system cannot create an offscreen EGL '
                'context (EGL_EXT_device_enumeration is missing or reports none)'
            )
        device = chooseDevice(available)
        log.info('EGL offscreen context on %r of %d device(s)', device, len(available))
        return device

    def _openDisplay(self, device):
        display = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, device.handle, None)
        if not display or display == EGL.EGL_NO_DISPLAY:
            raise EGLContextError('eglGetPlatformDisplayEXT gave no display for %r' % (device,))
        major, minor = EGL.EGLint(), EGL.EGLint()
        if not EGL.eglInitialize(display, major, minor):
            raise EGLContextError('eglInitialize failed for %r' % (device,))
        log.debug('EGL %d.%d on %r', major.value, minor.value, device)
        return display

    def _chooseConfig(self, definition):
        if not EGL.eglBindAPI(EGL.EGL_OPENGL_API):
            raise EGLContextError('eglBindAPI(EGL_OPENGL_API) failed; no desktop GL here')
        attributes = configAttributes(
            depthBuffer=definition.depthBuffer if definition.depthBuffer > 0 else 24,
            stencilBuffer=definition.stencilBuffer,
            alpha=bool(definition.alpha),
            rgb=bool(definition.rgb),
            multisampleSamples=max(0, definition.multisampleSamples),
            multisampleBuffer=max(0, definition.multisampleBuffer),
        )
        configs = (EGL.EGLConfig * 1)()
        found = EGL.EGLint()
        if not EGL.eglChooseConfig(
            self.display, _eglArray(attributes), configs, 1, ctypes.byref(found)
        ) or not found.value:
            raise EGLContextError(
                'no EGL config matched the requested buffers '
                '(depth=%s stencil=%s alpha=%s samples=%s)'
                % (
                    definition.depthBuffer,
                    definition.stencilBuffer,
                    definition.alpha,
                    definition.multisampleSamples,
                )
            )
        return configs[0]

    def _createContext(self, config):
        context = EGL.eglCreateContext(self.display, config, EGL.EGL_NO_CONTEXT, None)
        if not context or context == EGL.EGL_NO_CONTEXT:
            raise EGLContextError('eglCreateContext failed')
        return context

    def _createSurface(self, config, width, height):
        attributes = _eglArray([EGL.EGL_WIDTH, width, EGL.EGL_HEIGHT, height, EGL.EGL_NONE])
        surface = EGL.eglCreatePbufferSurface(self.display, config, attributes)
        if not surface or surface == EGL.EGL_NO_SURFACE:
            raise EGLContextError('eglCreatePbufferSurface failed for %dx%d' % (width, height))
        return surface

    # -- the Context contract ----------------------------------------------

    def _makeCurrent(self):
        """Bind the EGL context to this thread, and nothing else."""
        if not EGL.eglMakeCurrent(self.display, self.surface, self.surface, self.context):
            raise EGLContextError('eglMakeCurrent failed')

    def setCurrent(self, blocking=1):
        """Take the context and the scenegraph lock, then bind the EGL context."""
        Context.setCurrent(self, blocking)
        self._makeCurrent()

    def OnResize(self, width, height):
        """Render at a new size.

        An EGL pbuffer is created at a fixed size and cannot be resized, so this
        builds a replacement and drops the old one.  The GL context survives, so
        textures, buffers and programs are all still there afterwards.
        """
        width, height = int(width), int(height)
        if (width, height) <= (0, 0):
            raise EGLContextError('cannot render at %dx%d' % (width, height))
        replacement = self._createSurface(self.config, width, height)
        EGL.eglMakeCurrent(
            self.display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, EGL.EGL_NO_CONTEXT
        )
        EGL.eglDestroySurface(self.display, self.surface)
        self.surface = replacement
        self._makeCurrent()
        self.contextDefinition.size = (width, height)
        self.ViewPort(width, height)
        self.triggerRedraw(1)

    def SwapBuffers(self):
        """Finish the frame.

        A pbuffer has nothing to present to, so this is a flush: it is the point
        at which the rendering commands are guaranteed to have been issued, and
        readback after it sees a complete frame.
        """
        EGL.eglSwapBuffers(self.display, self.surface)

    def MainLoop(self):
        """Render :attr:`frameCount` frames, then release the context."""
        try:
            for _ in range(max(1, int(self.frameCount))):
                # OnDraw takes and releases the context itself, as it does for
                # every other backend.
                self.OnDraw(force=1)
        finally:
            self.stopTelemetry('mainloop-ended')
            self.close()

    def close(self):
        """Release the GL objects, the context, the surface and the display.

        The engine's caches hold GL objects belonging to this context, so they
        are dropped before it goes: a later context handed the same identifiers
        by the driver would otherwise inherit them.
        """
        if self.display is None:
            return
        contextresources.context_lost()
        EGL.eglMakeCurrent(
            self.display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, EGL.EGL_NO_CONTEXT
        )
        if self.surface is not None:
            EGL.eglDestroySurface(self.display, self.surface)
            self.surface = None
        if self.context is not None:
            EGL.eglDestroyContext(self.display, self.context)
            self.context = None
        EGL.eglTerminate(self.display)
        self.display = None

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

    class TestRenderer(EGLContext):
        def Render(self, mode=None):
            EGLContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    TestRenderer.ContextMainLoop()
