"""A hidden GL window for a test that renders in-process.

A test that exercises a pass, a shader or a node directly -- rather than by
running a script in a subprocess -- needs a current GL context and nothing else
of a window. :func:`hidden_window` gives it one and takes it away again::

    from OpenGLContext.testing.glcontext import hidden_window

    with hidden_window('bloom', size=(96, 96)):
        ...                                    # the context is current here

Under pytest, ask for the ``gl_context`` fixture instead and let
:mod:`OpenGLContext.testing.plugin` do this; the plugin turns
:class:`GLUnavailable` into a skip, which is what a machine with no GL target
should get.

**The window is never mapped.** A suite with hundreds of GL tests in it would
otherwise flash hundreds of windows over whatever the person running it is
doing and steal focus while they type. A hidden window renders and reads back
identically -- every ``glReadPixels`` sees the same pixels -- and on Wayland it
is also the only way a swap is guaranteed not to block on a compositor that has
nothing to show.

**The hints are reset first.** GLFW window hints are process-global and sticky,
so without :func:`glfw.default_window_hints` a context asked for as core would
be handed to the next caller who wanted compatibility.

:func:`describe_gl` says what the GL here is -- vendor, renderer, version, and
whether it rasterises on the CPU. It opens one probe window for the process and
remembers the answer, and :func:`gl_available` is the same question asked as a
yes or a no.
"""
from __future__ import annotations

import contextlib
import os
import sys
from typing import Any, Iterator, Mapping, Sequence

from OpenGLContext import contextresources

#: The profile names :func:`hidden_window` accepts. ``'core'`` is the profile
#: the shader passes want; ``'compatibility'`` additionally has the
#: fixed-function state (``GL_LIGHTING`` and friends) the legacy render arms
#: touch; ``'any'`` leaves the choice to the driver, which is what a test that
#: only needs *a* context should ask for.
PROFILES = ('core', 'compatibility', 'any')

#: The GL version asked for by default: the floor for the core-profile passes
#: and for GLSL 330, which is what every shader here is written against.
DEFAULT_VERSION = (3, 3)

#: The default window size. Big enough to read a rendered shape back out of and
#: small enough that a few hundred of them cost nothing.
DEFAULT_SIZE = (64, 64)

#: Substrings that mark a ``GL_RENDERER`` string as a CPU rasteriser: Mesa's
#: three, Google's, Apple's fallback and Microsoft's. Matched case-insensitively,
#: because a renderer appends its version and build details to the name.
SOFTWARE_RENDERER_NAMES = (
    'llvmpipe', 'softpipe', 'swrast', 'swiftshader', 'lavapipe',
    'software', 'gdi generic',
)


class GLUnavailable(RuntimeError):
    """No GL context could be created here.

    Carries the reason -- no ``glfw``, no display, a driver that refused the
    profile -- so a caller can report it rather than a bare failure.
    """


def _glfw() -> Any:
    """The ``glfw`` module, or :class:`GLUnavailable` saying it is not here.

    Imported on use rather than at module import: this module is loaded by a
    pytest plugin, and a project whose tests never touch GL should not pay for
    a windowing library to find that out.
    """
    try:
        import glfw
    except Exception as err:                       # pragma: no cover - needs no glfw
        raise GLUnavailable('glfw is not importable: %s' % (err,)) from err
    return glfw


def _apply_hints(glfw: Any, profile: str, version: Sequence[int],
                 forward_compatible: bool, hints: Mapping[str, int] | None) -> None:
    """Ask for the window this context should be, from a clean slate."""
    if profile not in PROFILES:
        raise ValueError('profile must be one of %r, not %r' % (PROFILES, profile))
    glfw.default_window_hints()
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    if profile != 'any':
        major, minor = version
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, major)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, minor)
        glfw.window_hint(glfw.OPENGL_PROFILE,
                         glfw.OPENGL_CORE_PROFILE if profile == 'core'
                         else glfw.OPENGL_COMPAT_PROFILE)
    # Core implies forward-compatible, which is the pair
    # :mod:`OpenGLContext.glfwcontext` asks a real window for -- so a test gets
    # the context the engine ships rather than one only a test ever sees. It is
    # also the only core context macOS offers: without the flag the driver
    # refuses the request, and every GL test on that platform would skip.
    if forward_compatible or profile == 'core':
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    for name, value in (hints or {}).items():
        glfw.window_hint(getattr(glfw, name), value)


def _check_compatibility(glfw: Any, window: Any) -> None:
    """Refuse a core-only context handed back to a caller who asked for compat.

    A driver may answer a compatibility request with a core context, and the
    fixed-function enums the legacy render arms touch are then invalid -- which
    surfaces much later as an unrelated GL error. ``GL_LIGHTING`` is the cheapest
    thing to ask about, so ask.
    """
    from OpenGL.GL import GL_LIGHTING, glIsEnabled
    try:
        glIsEnabled(GL_LIGHTING)
    except Exception as err:
        glfw.destroy_window(window)
        raise GLUnavailable(
            'the driver gave a core-only context where compatibility was '
            'asked for; GL_LIGHTING is unavailable: %s' % (err,)) from err


#: Which GLFW hint names a buffer CGL also takes, and what CGL calls it.
_CGL_BUFFER_HINTS = {
    'ALPHA_BITS': 'alpha_size',
    'DEPTH_BITS': 'depth_size',
    'STENCIL_BITS': 'stencil_size',
    'SAMPLES': 'samples',
}


def cgl_profile_for(profile: str, version: Sequence[int]) -> str:
    """The CGL profile serving this request, or say why there is none.

    macOS offers a legacy 2.1 profile, a 3.2 core one and a 4.1 core one, and
    no compatibility profile above 2.1 -- so a request for the fixed-function
    pipeline at 3.3 is refused rather than served with a 2.1 context, which
    would let the test pass having exercised something else.
    """
    major, minor = version
    if profile == 'any':
        return 'legacy'
    if profile == 'compatibility':
        raise GLUnavailable(
            'macOS has no compatibility profile above 2.1, and %d.%d was asked '
            'for; the fixed-function paths cannot run here' % (major, minor))
    if (major, minor) >= (4, 1):
        return 'core4'
    if (major, minor) >= (3, 2):
        return 'core3'
    raise GLUnavailable(
        'a core profile below 3.2 does not exist; %d.%d was asked for'
        % (major, minor))


def cgl_buffer_sizes(hints: Mapping[str, int] | None) -> dict:
    """The CGL buffer sizes a caller's GLFW hints ask for.

    A hint CGL has no answer for is refused rather than dropped: a test that
    asked for something and did not get it is a test that passed for the wrong
    reason.
    """
    sizes = {}
    for name, value in (hints or {}).items():
        if name not in _CGL_BUFFER_HINTS:
            raise GLUnavailable(
                'the %s hint has no CGL equivalent, so this window cannot be '
                'made without one' % (name,))
        sizes[_CGL_BUFFER_HINTS[name]] = value
    return sizes


class OffscreenWindow:
    """What :func:`hidden_window` yields where there is no window.

    A CGL context has no drawable and so no framebuffer zero; ``target`` is the
    framebuffer object standing in for one, and is bound while this is current.
    ``size`` is what a caller asks :func:`framebuffer_size` for.
    """

    __slots__ = ('context', 'size', 'target')

    def __init__(self, context: Any, target: Any, size: Sequence[int]) -> None:
        self.context = context
        self.target = target
        self.size = tuple(size)

    def __repr__(self) -> str:
        width, height = self.size
        return '<%s %dx%d>' % (self.__class__.__name__, width, height)


def color_buffer_attachment() -> Any:
    """Which attachment of the drawing framebuffer holds its colour.

    A window's is ``GL_BACK_LEFT``; an offscreen target's is
    ``GL_COLOR_ATTACHMENT0``, since it is a framebuffer object. A test asking
    the framebuffer about its own colour buffer has to name the right one.
    """
    from OpenGL import GL as gl

    if _BACKEND == 'cgl':
        return gl.GL_COLOR_ATTACHMENT0
    return gl.GL_BACK_LEFT


def framebuffer_size(window: Any) -> tuple:
    """How big the framebuffer of ``window`` is, whichever backend made it.

    A test that wants to know should not have to know what made the context.
    """
    if isinstance(window, OffscreenWindow):
        return window.size
    glfw = _glfw()
    return tuple(glfw.get_framebuffer_size(window))


#: 'glfw', 'cgl', or None until something has been created.
_BACKEND: str | None = None


def backend() -> str | None:
    """Which backend made the contexts in this process, once one has been."""
    return _BACKEND


@contextlib.contextmanager
def _cgl_window(size: Sequence[int], profile: str, version: Sequence[int],
                hints: Mapping[str, int] | None) -> Iterator[Any]:
    """A CGL context with an offscreen target bound, current for the body."""
    try:
        from OpenGL import CGL
    except ImportError as err:                     # pragma: no cover - old PyOpenGL
        raise GLUnavailable('this PyOpenGL has no CGL: %s' % (err,)) from err
    cgl_profile = cgl_profile_for(profile, version)
    sizes = cgl_buffer_sizes(hints)
    width, height = size
    # The pixel format is not what a caller reads back from: with no drawable
    # there is nothing behind it, and the target below is the framebuffer that
    # answers.  So a request for no alpha has to reach the target's own format.
    from OpenGL import GL as gl
    color_format = gl.GL_RGB8 if sizes.get('alpha_size') == 0 else gl.GL_RGBA8
    try:
        with CGL.headless_context(profile=cgl_profile, **sizes) as context:
            target = CGL.OffscreenTarget(width, height, color_format=color_format)
            try:
                yield OffscreenWindow(context, target, (width, height))
            finally:
                contextresources.context_lost()
                target.release()
    except CGL.CGLError as err:
        raise GLUnavailable('no CGL %s context here: %s'
                            % (cgl_profile, err)) from err


@contextlib.contextmanager
def hidden_window(title: str = 'OpenGLContext test',
                  size: Sequence[int] = DEFAULT_SIZE,
                  profile: str = 'core',
                  version: Sequence[int] = DEFAULT_VERSION,
                  forward_compatible: bool = False,
                  hints: Mapping[str, int] | None = None) -> Iterator[Any]:
    """An unmapped window, current for the body, gone afterwards.

    ``title`` names the window (a diagnostic; nothing shows it), ``size`` is
    ``(width, height)`` in pixels, and ``profile`` is one of :data:`PROFILES`.
    ``forward_compatible`` asks for a forward-compatible context, which a
    ``'core'`` one is regardless; and ``hints`` is any further ``{GLFW hint
    name: value}`` a caller needs -- for example ``{'ALPHA_BITS': 0}`` for a
    window whose readback should have no alpha.

    Yields the GLFW window handle, or an :class:`OffscreenWindow` where the
    context came from CGL; :func:`framebuffer_size` reads the size of either.
    Raises :class:`GLUnavailable` if there is no ``glfw``, no display, or the
    driver will not give the profile asked for.

    **Where GLFW cannot make a context, CGL is tried.** GLFW asks macOS for an
    accelerated pixel format and nothing else, so on a machine with no
    accelerated renderer it can make none at all; CGL is the layer underneath
    and will. There is no framebuffer zero in one, so an offscreen target is
    bound in its place and drawing and reading back behave as they do on a
    window.
    """
    global _BACKEND
    if _BACKEND != 'cgl':
        try:
            with _glfw_window(title, size, profile, version,
                              forward_compatible, hints) as window:
                _BACKEND = 'glfw'
                yield window
            return
        except GLUnavailable:
            if _BACKEND == 'glfw' or sys.platform != 'darwin':
                raise
    with _cgl_window(size, profile, version, hints) as window:
        _BACKEND = 'cgl'
        yield window


def release_foreign_context() -> bool:
    """Let go of a GL context this process holds; answer whether there was one

    A thread may hold one context, and a platform's binding APIs do not know
    about each other: this GLFW asks EGL for the thread, and a GLX context
    already on it makes that ``EGL_BAD_ACCESS``.  A suite run on any backend
    but GLFW is exactly that arrangement, since these windows are opened
    whichever backend the run is on.

    The context let go of belongs to whatever opened it, and that owner is done
    with it: a test window is made between tests, not during one.
    """
    from OpenGL import platform

    try:
        if not platform.PLATFORM.GetCurrentContext():
            return False
        return bool(platform.PLATFORM.releaseCurrentContext())
    except Exception:                   # pragma: no cover - no GL at all
        return False


@contextlib.contextmanager
def _glfw_window(title: str, size: Sequence[int], profile: str,
                 version: Sequence[int], forward_compatible: bool,
                 hints: Mapping[str, int] | None) -> Iterator[Any]:
    """An unmapped GLFW window, current for the body, gone afterwards."""
    glfw = _glfw()
    # The engine reads this to pick a backend; a test that goes on to build an
    # OpenGLContext context inside the window gets the one that owns it.
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        raise GLUnavailable('glfw.init() failed: no display or no GL driver')
    _apply_hints(glfw, profile, version, forward_compatible, hints)
    width, height = size
    release_foreign_context()
    window = glfw.create_window(width, height, title, None, None)
    if not window:
        raise GLUnavailable('the driver would not create a %dx%d %s window'
                            % (width, height, profile))
    glfw.make_context_current(window)
    if profile == 'compatibility':
        _check_compatibility(glfw, window)
    try:
        yield window
    finally:
        # Still current, so the engine's caches can let go of this context's GL
        # names.  A suite opens hundreds of these in one process, which is the
        # setting in which a driver hands the same address out again.
        contextresources.context_lost()
        glfw.destroy_window(window)


class GLDescription:
    """What the GL implementation in this process calls itself.

    The three strings are ``GL_VENDOR``, ``GL_RENDERER`` and ``GL_VERSION`` as
    the driver gave them. :attr:`software` reads the renderer name, which is
    where an implementation says whether a GPU is doing the work.
    """

    __slots__ = ('renderer', 'vendor', 'version')

    def __init__(self, vendor: str, renderer: str, version: str) -> None:
        self.vendor = vendor
        self.renderer = renderer
        self.version = version

    @property
    def software(self) -> bool:
        """Whether this GL rasterises on the CPU.

        A renderer that names nothing recognisable is reported as hardware:
        that is the safer answer, since calling a GPU software only passes over
        tests that would have run, while the reverse holds a CPU rasteriser to
        a speed no CPU reaches.
        """
        renderer = self.renderer.lower()
        return any(name in renderer for name in SOFTWARE_RENDERER_NAMES)

    def __repr__(self) -> str:
        kind = 'software' if self.software else 'hardware'
        return '<%s %s, %s (%s)>' % (
            self.__class__.__name__, self.renderer, self.version, kind)


#: ``None`` until asked, then the description or ``False`` where there is no GL.
_DESCRIPTION: GLDescription | bool | None = None


def describe_gl() -> GLDescription | None:
    """What the GL here is, or ``None`` where a context cannot be made at all.

    Answered once and remembered: it costs a window, it cannot change while the
    process lives, and a ``skipif`` in every GL test file would otherwise open
    and close a probe window apiece.
    """
    global _DESCRIPTION
    if _DESCRIPTION is None:
        try:
            with hidden_window('probe', profile='any'):
                from OpenGL.GL import (
                    GL_RENDERER, GL_VENDOR, GL_VERSION, glGetString,
                )
                _DESCRIPTION = GLDescription(
                    vendor=_string(glGetString(GL_VENDOR)),
                    renderer=_string(glGetString(GL_RENDERER)),
                    version=_string(glGetString(GL_VERSION)),
                )
        except GLUnavailable:
            _DESCRIPTION = False
        except Exception:                          # pragma: no cover - driver-specific
            _DESCRIPTION = False
    return _DESCRIPTION if isinstance(_DESCRIPTION, GLDescription) else None


def _string(value: Any) -> str:
    """One ``glGetString`` answer as text, however the binding returned it."""
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return str(value)


def gl_available() -> bool:
    """Whether a GL context can be created in this process at all."""
    return describe_gl() is not None
