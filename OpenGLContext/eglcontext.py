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
    An index into the device list.  Use it to pin a run to one GPU of several.
``LIBGL_ALWAYS_SOFTWARE`` / ``GALLIUM_DRIVER``
    When the environment asks for software rendering, a software device is
    chosen.  This is not merely a courtesy: asking Mesa for a display on a
    *hardware* device while software rendering is demanded is a contradiction it
    refuses and then crashes on, so honouring the request is what keeps the
    process alive.

The two have to agree.  Where they do not -- a pinned GPU, or a machine with no
software device on it, while software rendering is demanded -- the request is
refused with an :class:`EGLContextError` naming both settings, rather than
served with the device that would take the process down.  Every other mismatch
falls back: wanting a GPU and finding only a CPU rasteriser is slow, not fatal,
so it renders and says so in the log.

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
from typing import Any, Iterable, List, Literal, Mapping, Optional, Sequence

from OpenGL import EGL
from OpenGL.GL import glFlush
from OpenGL.EGL.devices import DeviceInfo, devices
from OpenGL.EGL.EXT.platform_base import eglGetPlatformDisplayEXT
from OpenGL.EGL.EXT.platform_device import EGL_PLATFORM_DEVICE_EXT

from OpenGLContext import contextresources
from OpenGLContext.context import Context
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.interactivecontext import InteractiveContext
from OpenGLContext.move import viewplatformmixin

log = logging.getLogger(__name__)

__all__ = (
    'EGLContext',
    'EGLContextError',
    'PROFILES',
    'PbufferContext',
    'chooseConfig',
    'chooseDevice',
    'closeDisplay',
    'configAttributes',
    'contextAttributes',
    'createContext',
    'createPbufferSurface',
    'devices',
    'openDisplay',
    'prefersSoftware',
    'selectDevice',
)

#: The profiles :func:`contextAttributes` accepts.  ``'any'`` names neither a
#: profile nor a version, which is the only thing to ask for below GL 3.2,
#: where the profile mask does not exist.
PROFILES = ('core', 'compatibility', 'any')

#: Values of ``LIBGL_ALWAYS_SOFTWARE`` that mean "no".  Anything else is a yes,
#: because Mesa itself treats the variable as set-or-not.
_OFF = ('', '0', 'false', 'no', 'off')

#: ``GALLIUM_DRIVER`` values that name a CPU rasteriser.
_SOFTWARE_DRIVERS = ('llvmpipe', 'softpipe', 'swr', 'swrast', 'lavapipe')

#: Environment variable pinning the run to one device by index.
DEVICE_VARIABLE = 'OPENGLCONTEXT_EGL_DEVICE'

#: Said when the environment asks for software rendering and only a GPU is on
#: offer.  Mesa refuses to force software rasterisation onto a display built on
#: a hardware device, and having refused it dereferences the screen it declined
#: to build -- so this pair is not a slow render but a lost process, and the
#: caller is told which of the two settings to drop.
_CONTRADICTION = (
    'software rendering is demanded (LIBGL_ALWAYS_SOFTWARE / GALLIUM_DRIVER) '
    'but %s, which is a hardware device.  Mesa crashes rather than forcing '
    'software rasterisation onto one, so drop one of the two settings.'
)


class EGLContextError(RuntimeError):
    """An offscreen context could not be created, or was misconfigured."""


def prefersSoftware(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Whether this environment is asking for software rendering."""
    if environ is None:
        environ = os.environ
    if environ.get('LIBGL_ALWAYS_SOFTWARE', '').strip().lower() not in _OFF:
        return True
    return environ.get('GALLIUM_DRIVER', '').strip().lower() in _SOFTWARE_DRIVERS


def chooseDevice(
    available: Iterable[DeviceInfo],
    environ: Optional[Mapping[str, str]] = None,
) -> Optional[DeviceInfo]:
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
        device = available[index]
        if prefersSoftware(environ) and not device.software:
            raise EGLContextError(_CONTRADICTION % (
                '%s=%d names %r' % (DEVICE_VARIABLE, index, device),
            ))
        return device

    wantSoftware = prefersSoftware(environ)
    for device in available:
        if device.software == wantSoftware:
            return device
    if wantSoftware:
        raise EGLContextError(_CONTRADICTION % (
            'the only device(s) here are %s'
            % ', '.join(repr(device) for device in available),
        ))
    # Wanting a GPU and being offered only a CPU rasteriser is merely slow, so
    # it runs; the caller can see what it got from the log.
    log.warning('no hardware EGL device available; using %r', available[0])
    return available[0]


def configAttributes(
    depthBuffer: int = 24,
    stencilBuffer: int = 8,
    alpha: bool = False,
    rgb: bool = True,
    multisampleSamples: int = 0,
    multisampleBuffer: int = 0,
) -> List[int]:
    """The ``eglChooseConfig`` attribute list for these buffer settings.

    Sizes of zero or less are left out rather than requested as zero, so the
    implementation picks; that is what a :class:`ContextDefinition` default of
    ``-1`` means.  The surface type is always a pbuffer: there is no window, so
    it has to be a surface EGL can make on its own.
    """
    attributes: List[int] = [
        EGL.EGL_SURFACE_TYPE, EGL.EGL_PBUFFER_BIT,
        EGL.EGL_RENDERABLE_TYPE, EGL.EGL_OPENGL_BIT,
        # ``rgb`` picks the kind of colour buffer, not merely how many bits of
        # one: asking for RGB and then declining to say how wide each channel is
        # would leave the parameter with nothing to do.
        EGL.EGL_COLOR_BUFFER_TYPE,
        EGL.EGL_RGB_BUFFER if rgb else EGL.EGL_LUMINANCE_BUFFER,
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


def _eglArray(values: Sequence[int]) -> Any:
    return (EGL.EGLint * len(values))(*[int(value) for value in values])


def contextAttributes(
    profile: str = 'core',
    version: Sequence[int] = (3, 3),
    forwardCompatible: bool = False,
) -> List[int]:
    """The ``eglCreateContext`` attribute list for this profile and version.

    ``profile`` is one of :data:`PROFILES`.  ``'any'`` asks for nothing at all,
    which is what gets the context the implementation makes by default -- below
    GL 3.2 there is no profile mask to ask about.  A context asked for as core
    is additionally forward-compatible where ``forwardCompatible`` says so,
    which is the pair the windowed backends ask for.
    """
    if profile not in PROFILES:
        # A ValueError rather than an EGLContextError: the name came from the
        # caller's own source, so this is a typo to fix and not a machine that
        # cannot render.  Callers turn the latter into a skip.
        raise ValueError(
            'no EGL profile named %r (expected one of %s)'
            % (profile, ', '.join(PROFILES)))
    if profile == 'any':
        return [EGL.EGL_NONE]
    major, minor = version
    attributes: List[int] = [
        EGL.EGL_CONTEXT_MAJOR_VERSION, int(major),
        EGL.EGL_CONTEXT_MINOR_VERSION, int(minor),
        EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK,
        (EGL.EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT if profile == 'core'
         else EGL.EGL_CONTEXT_OPENGL_COMPATIBILITY_PROFILE_BIT),
    ]
    if forwardCompatible:
        attributes += [EGL.EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE, EGL.EGL_TRUE]
    attributes.append(EGL.EGL_NONE)
    return attributes


def selectDevice(environ: Optional[Mapping[str, str]] = None) -> DeviceInfo:
    """The EGL device to render on, or say that this system offers none."""
    available = devices()
    # chooseDevice answers None only for an empty list, so the two questions --
    # are there any, and which -- are one question here.
    device = chooseDevice(available, environ) if available else None
    if device is None:
        raise EGLContextError(
            'no EGL devices; this system cannot create an offscreen EGL '
            'context (EGL_EXT_device_enumeration is missing or reports none)'
        )
    log.info('EGL offscreen context on %r of %d device(s)', device, len(available))
    return device


#: How many live contexts each initialised EGL display has.
#: ``eglGetPlatformDisplayEXT`` answers the *same* display for the same device,
#: and ``eglTerminate`` invalidates every context and surface on it, so a
#: context that terminated on its way out would take its siblings with it.
#: Keyed by the handle rather than by the wrapper, which is a new object each
#: call.  A process holds one or two of these, so the map never grows.
_DISPLAY_USES: dict = {}


def _displayKey(display: Any) -> int:
    """The address the display wrapper carries, which is its identity."""
    return ctypes.cast(display, ctypes.c_void_p).value or 0


def openDisplay(device: DeviceInfo) -> Any:
    """An initialised EGL display for ``device``, counted as one more user.

    :func:`closeDisplay` gives it back.  Initialising a display that is already
    initialised is EGL's own idempotent call, so the count is what decides when
    it may be terminated rather than the initialisation.
    """
    display = eglGetPlatformDisplayEXT(EGL_PLATFORM_DEVICE_EXT, device.handle, None)
    if not display or display == EGL.EGL_NO_DISPLAY:
        raise EGLContextError('eglGetPlatformDisplayEXT gave no display for %r' % (device,))
    major, minor = EGL.EGLint(), EGL.EGLint()
    if not EGL.eglInitialize(display, major, minor):
        raise EGLContextError('eglInitialize failed for %r' % (device,))
    key = _displayKey(display)
    _DISPLAY_USES[key] = _DISPLAY_USES.get(key, 0) + 1
    log.debug('EGL %d.%d on %r, %d user(s)', major.value, minor.value,
              device, _DISPLAY_USES[key])
    return display


def closeDisplay(display: Any) -> bool:
    """Give back one use of ``display``; terminate it on the last.

    Answers whether it was terminated, which is what a test asking "did that
    one take the display down with it" wants to know.
    """
    key = _displayKey(display)
    remaining = _DISPLAY_USES.get(key, 0) - 1
    if remaining > 0:
        _DISPLAY_USES[key] = remaining
        return False
    _DISPLAY_USES.pop(key, None)
    EGL.eglTerminate(display)
    return True


def chooseConfig(display: Any, attributes: Sequence[int], asked: str = '') -> Any:
    """The first EGL config on ``display`` matching ``attributes``.

    ``asked`` describes the request in the error raised where nothing matches,
    since the attribute list itself is a flat array of enum values and tells a
    reader very little.
    """
    if not EGL.eglBindAPI(EGL.EGL_OPENGL_API):
        raise EGLContextError('eglBindAPI(EGL_OPENGL_API) failed; no desktop GL here')
    configs = (EGL.EGLConfig * 1)()
    found = (EGL.EGLint * 1)()
    if not EGL.eglChooseConfig(
        display, _eglArray(attributes), configs, 1, found
    ) or not found[0]:
        raise EGLContextError('no EGL config matched the requested buffers %s' % (asked,))
    return configs[0]


def createContext(display: Any, config: Any,
                  attributes: Optional[Sequence[int]] = None) -> Any:
    """A GL context on ``display``, sharing with nothing.

    ``attributes`` of None asks for no profile and no version, which is the
    context the implementation makes by default; :func:`contextAttributes`
    builds one that names them.
    """
    context = EGL.eglCreateContext(
        display, config, EGL.EGL_NO_CONTEXT,
        None if attributes is None else _eglArray(attributes))
    if not context or context == EGL.EGL_NO_CONTEXT:
        raise EGLContextError('eglCreateContext failed')
    return context


def createPbufferSurface(display: Any, config: Any, width: int, height: int) -> Any:
    """A pbuffer surface of this size: the drawable there is no window for."""
    attributes = _eglArray([EGL.EGL_WIDTH, width, EGL.EGL_HEIGHT, height, EGL.EGL_NONE])
    surface = EGL.eglCreatePbufferSurface(display, config, attributes)
    if not surface or surface == EGL.EGL_NO_SURFACE:
        raise EGLContextError('eglCreatePbufferSurface failed for %dx%d' % (width, height))
    return surface


class PbufferContext:
    """A GL context on an EGL pbuffer, current from construction to release.

    The surface alone, with no scenegraph, no event loop and no engine caches
    behind it: what a caller wanting a windowless context outside the engine's
    own Context classes builds on, and what
    :mod:`OpenGLContext.testing.glcontext` renders on where a run asks for no
    window.  :class:`EGLContext` is the same surface driven as an OpenGLContext
    context.

    ``width`` and ``height`` stay readable afterwards, so a caller can ask how
    big the framebuffer is without having kept the numbers itself::

        with PbufferContext(width=96, height=48) as gl:
            glReadPixels(0, 0, gl.width, gl.height, GL_RGB, GL_UNSIGNED_BYTE)

    A pbuffer is single-buffered, so the frame just drawn is in the front
    buffer rather than waiting on a swap; ``glFlush`` is what makes it
    readable, and :meth:`flush` is that call named.
    """

    #: The device this was built on; a caller reporting what it got reads it.
    device: Optional[DeviceInfo] = None
    display: Any = None
    context: Any = None
    surface: Any = None

    def __init__(self, width: int = 256, height: int = 256,
                 profile: str = 'core',
                 version: Sequence[int] = (3, 3),
                 forwardCompatible: bool = False,
                 depthBuffer: int = 24, stencilBuffer: int = 8,
                 alpha: bool = False,
                 environ: Optional[Mapping[str, str]] = None) -> None:
        self.width = int(width)
        self.height = int(height)
        try:
            self.device = selectDevice(environ)
            self.display = openDisplay(self.device)
            config = chooseConfig(
                self.display,
                configAttributes(depthBuffer=depthBuffer,
                                 stencilBuffer=stencilBuffer, alpha=alpha),
                'depth=%s stencil=%s alpha=%s' % (depthBuffer, stencilBuffer, alpha))
            self.context = createContext(
                self.display, config,
                contextAttributes(profile, version, forwardCompatible))
            self.surface = createPbufferSurface(
                self.display, config, self.width, self.height)
            self.make_current()
        except Exception:
            # A half-built context still holds a display and perhaps a surface,
            # and a caller that only ever sees the exception has no handle to
            # give them back with.
            self.release()
            raise

    def make_current(self) -> None:
        """Bind this context and its surface to the calling thread.

        Named as :class:`OpenGL.WGL.offscreen.OffscreenContext` names it: a
        caller holding a windowless context of whichever platform it is on
        drives it through the same two calls.
        """
        if not EGL.eglMakeCurrent(
            self.display, self.surface, self.surface, self.context
        ):
            raise EGLContextError('eglMakeCurrent failed')

    def flush(self) -> None:
        """Finish the frame so its pixels can be read back."""
        glFlush()

    def release(self) -> None:
        """Give back the EGL objects this holds.  Safe to call twice.

        Callable part-way through construction, where some of them do not exist
        yet.
        """
        if self.display is None:
            return
        EGL.eglMakeCurrent(
            self.display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, EGL.EGL_NO_CONTEXT
        )
        if self.surface is not None:
            EGL.eglDestroySurface(self.display, self.surface)
            self.surface = None
        if self.context is not None:
            EGL.eglDestroyContext(self.display, self.context)
            self.context = None
        closeDisplay(self.display)
        self.display = None

    def __enter__(self) -> 'PbufferContext':
        return self

    def __exit__(self, *exception: Any) -> Literal[False]:
        self.release()
        return False

    def __repr__(self) -> str:
        return '<%s %dx%d>' % (self.__class__.__name__, self.width, self.height)


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

    #: The EGL objects this context owns, or None before they are made and
    #: after they have been given back.
    display: Any = None
    surface: Any = None
    context: Any = None
    device: Optional[DeviceInfo] = None
    config: Any = None
    #: Settled by the constructor before the EGL context exists, so it is never
    #: None for a context that was built.
    contextDefinition: ContextDefinition

    def __init__(self, definition: Any = None, **named: Any) -> None:
        # Resolved first: the buffer sizes are config-selection parameters, so
        # they have to be known before the EGL context exists, exactly as the
        # windowed backends resolve them before creating a window.
        definition = self.resolveDefinition(definition, **named)
        self.contextDefinition = definition
        width, height = [int(value) for value in definition.size]

        self.device = self._selectDevice()
        # Each step raises EGLContextError on failure, and every one of them can:
        # no config matches the requested buffers, no desktop GL on this device.
        # The module's own advice is to try EGL and fall back, so a failure is an
        # expected outcome -- and an initialised display left behind is a leak
        # per attempt, for an application that tries several devices or reduces
        # its buffer request and tries again.
        try:
            self.display = self._openDisplay(self.device)
            # Kept: a pbuffer has a fixed size, so resizing means making another
            # one against the same config.
            self.config = self._chooseConfig(definition)
            self.context = self._createContext(self.config)
            self.surface = self._createSurface(self.config, width, height)
            # The raw make-current, not setCurrent: the scenegraph lock that one
            # also takes is set up by Context.__init__, which has not run yet.
            self._makeCurrent()
        except BaseException:
            # Not context_lost(): no cache ever saw this context, and announcing
            # its loss would drop another context's objects.
            self._releaseEGL()
            raise

        Context.__init__(self, definition)
        self.ViewPort(width, height)

    # -- construction, one step per EGL call that can fail ------------------

    def _selectDevice(self) -> DeviceInfo:
        return selectDevice()

    def _openDisplay(self, device: DeviceInfo) -> Any:
        return openDisplay(device)

    def _chooseConfig(self, definition: Any) -> Any:
        attributes = configAttributes(
            depthBuffer=definition.depthBuffer if definition.depthBuffer > 0 else 24,
            stencilBuffer=definition.stencilBuffer,
            alpha=bool(definition.alpha),
            rgb=bool(definition.rgb),
            multisampleSamples=max(0, definition.multisampleSamples),
            multisampleBuffer=max(0, definition.multisampleBuffer),
        )
        return chooseConfig(
            self.display, attributes,
            '(depth=%s stencil=%s alpha=%s samples=%s)'
            % (
                definition.depthBuffer,
                definition.stencilBuffer,
                definition.alpha,
                definition.multisampleSamples,
            ),
        )

    def _createContext(self, config: Any) -> Any:
        return createContext(self.display, config)

    def _createSurface(self, config: Any, width: int, height: int) -> Any:
        return createPbufferSurface(self.display, config, width, height)

    # -- the Context contract ----------------------------------------------

    def _makeCurrent(self) -> None:
        """Bind the EGL context to this thread, and nothing else."""
        if not EGL.eglMakeCurrent(self.display, self.surface, self.surface, self.context):
            raise EGLContextError('eglMakeCurrent failed')

    def setCurrent(self, blocking: int = 1) -> None:
        """Take the context and the scenegraph lock, then bind the EGL context."""
        Context.setCurrent(self, blocking)
        self._makeCurrent()
        self.bindContextResources(self._glHandle())

    def _glHandle(self) -> Any:
        """The GL context handle the caches and PyOpenGL key on."""
        return contextresources.context_key()

    def OnResize(self, width: int, height: int) -> None:
        """Render at a new size.

        An EGL pbuffer is created at a fixed size and cannot be resized, so this
        builds a replacement and drops the old one.  The GL context survives, so
        textures, buffers and programs are all still there afterwards.
        """
        width, height = int(width), int(height)
        if width <= 0 or height <= 0:
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

    def SwapBuffers(self) -> None:
        """Finish the frame.

        A pbuffer has nothing to present to, so this is a flush: the point at
        which this frame's commands are guaranteed to have been issued to the
        driver, which is what a readback, a capture or an encode after it
        depends on.

        ``eglSwapBuffers`` is not what does it.  The EGL specification gives it
        no effect on any surface that is not a back-buffered window, so on a
        pbuffer it returns EGL_TRUE and issues nothing.
        """
        glFlush()

    def MainLoop(self) -> None:
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

    def OnQuit(self, event: Any = None) -> Any:
        """Let go of the EGL objects, then end the application.

        The release happens **here** rather than after the loop because
        :meth:`Context.OnQuit` ends the process with ``os._exit``: nothing
        after it runs, no ``finally`` and no ``atexit`` hook, and a bounded
        capture run quits from inside ``OnDraw``.
        """
        self.close()
        return Context.OnQuit(self, event)

    def releaseWindow(self) -> None:
        """Let this context's GL objects and its EGL objects go

        The name every backend answers to; this one has no window, so it is
        :meth:`close`.
        """
        self.close()

    def close(self) -> None:
        """Release the GL objects, the context, the surface and the display.

        The engine's caches hold GL objects belonging to this context, so they
        are dropped before it goes: a later context handed the same identifiers
        by the driver would otherwise inherit them.
        """
        if self.display is None:
            return
        # This context current first: it is the only moment the caches holding
        # its GL names can delete them rather than merely forget them, and the
        # caches are told which context is going by asking which one is
        # current -- so closing one of two would otherwise retire the wrong.
        try:
            self._makeCurrent()
        except Exception:               # pragma: no cover - needs a lost display
            pass
        self.releaseContextResources(self._glHandle())
        self._releaseEGL()

    def _releaseEGL(self) -> None:
        """Give back whatever EGL objects this context has taken.

        Written to be callable part-way through construction, where some of them
        do not exist yet, as well as from :meth:`close`.  It touches no engine
        cache, because on the construction path no cache ever saw this context.
        """
        if self.display is None:
            return
        EGL.eglMakeCurrent(
            self.display, EGL.EGL_NO_SURFACE, EGL.EGL_NO_SURFACE, EGL.EGL_NO_CONTEXT
        )
        if self.surface is not None:
            EGL.eglDestroySurface(self.display, self.surface)
            self.surface = None
        if self.context is not None:
            EGL.eglDestroyContext(self.display, self.context)
            self.context = None
        closeDisplay(self.display)
        self.display = None

    def __enter__(self) -> 'EGLContext':
        return self

    def __exit__(self, *exception: Any) -> Literal[False]:
        self.close()
        return False

    @classmethod
    def ContextMainLoop(cls, *args: Any, **named: Any) -> Any:
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
        def Render(self, mode: Any = None) -> None:
            EGLContext.Render(self, mode)
            glClearColor(0.2, 0.3, 0.3, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    TestRenderer.ContextMainLoop()
