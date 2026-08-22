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
"""
from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator, Mapping, Sequence

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
    if forward_compatible:
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


@contextlib.contextmanager
def hidden_window(title: str = 'OpenGLContext test',
                  size: Sequence[int] = DEFAULT_SIZE,
                  profile: str = 'core',
                  version: Sequence[int] = DEFAULT_VERSION,
                  forward_compatible: bool = False,
                  hints: Mapping[str, int] | None = None) -> Iterator[Any]:
    """An unmapped GLFW window, current for the body, gone afterwards.

    ``title`` names the window (a diagnostic; nothing shows it), ``size`` is
    ``(width, height)`` in pixels, and ``profile`` is one of :data:`PROFILES`.
    ``forward_compatible`` asks for a forward-compatible context, and ``hints``
    is any further ``{GLFW hint name: value}`` a caller needs -- for example
    ``{'ALPHA_BITS': 0}`` for a window whose readback should have no alpha.

    Yields the GLFW window handle. Raises :class:`GLUnavailable` if there is no
    ``glfw``, no display, or the driver will not give the profile asked for.
    """
    glfw = _glfw()
    # The engine reads this to pick a backend; a test that goes on to build an
    # OpenGLContext context inside the window gets the one that owns it.
    os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
    if not glfw.init():
        raise GLUnavailable('glfw.init() failed: no display or no GL driver')
    _apply_hints(glfw, profile, version, forward_compatible, hints)
    width, height = size
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
        glfw.destroy_window(window)


_AVAILABLE: bool | None = None


def gl_available() -> bool:
    """Whether a GL context can be created in this process at all.

    Answered once and remembered: it cannot change while the process lives, and
    a module-level ``skipif`` in every GL test file would otherwise open and
    close a probe window apiece.
    """
    global _AVAILABLE
    if _AVAILABLE is None:
        try:
            with hidden_window('probe', profile='any'):
                _AVAILABLE = True
        except GLUnavailable:
            _AVAILABLE = False
        except Exception:                          # pragma: no cover - driver-specific
            _AVAILABLE = False
    return _AVAILABLE
