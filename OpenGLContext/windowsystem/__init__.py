"""The window systems a context opens on, and the choice between them

A :class:`~OpenGLContext.context.Context` holds a :class:`WindowSystem` rather
than deriving from one.  Which one is a field of its definition,
``ContextDefinition.windowsystem``, naming a registered window system:

    glfw, glut, pygame, tk, wx    a window, through that toolkit
    egl, wgl                      no window: a pbuffer on Linux or Windows
    offscreen                     whichever of egl and wgl this platform has
    ''                            the default, settled by :func:`choose`

One module per window system lives in this package, and each is imported only
when a context asks for it, so a program pays for the toolkit it uses and no
other.  The Qt one ships in the separate ``OpenGLContext-qt`` distribution and
registers itself through the ``openglcontext.windowsystems`` entry-point group,
as a third party's does.  See ``docs/backends.rst``.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Callable, Iterable, Sequence
from typing import Optional

from OpenGL.plugins import importByName

from OpenGLContext import plugins
from OpenGLContext.windowsystem.base import WindowSystem

log = logging.getLogger(__name__)

__all__ = (
    'ENTRY_POINT_GROUP',
    'OFFSCREEN',
    'PLATFORM_ORDER',
    'WindowSystem',
    'WindowSystemUnavailable',
    'choose',
    'load',
    'offscreenName',
    'probe',
    'registered',
)

#: The entry-point group a distribution names its window systems in, as
#: ``name = "package.module:ClassName"``.
ENTRY_POINT_GROUP = 'openglcontext.windowsystems'

#: The name that asks for whichever window system renders with no window here.
OFFSCREEN = 'offscreen'

#: The order an empty request tries the windowed systems in.  GLFW first: it
#: makes a core-profile context everywhere and is what the engine is tested on.
#: A registered system missing from this list is tried after these, in the
#: order it was registered.
PLATFORM_ORDER = ('glfw', 'glut', 'pygame', 'qt', 'tk', 'wx')

#: Platforms whose windowless system is not EGL, by the prefix
#: ``sys.platform`` starts with.
OFFSCREEN_BY_PLATFORM = (
    ('win32', 'wgl'),
    ('cygwin', 'wgl'),
)

#: What every other platform renders with no window on: EGL, which needs
#: neither a window nor a display server.
DEFAULT_OFFSCREEN = 'egl'

#: The windowless systems, which an empty request never falls back to: a
#: program that asked for nothing in particular is asking for a window.
OFFSCREEN_SYSTEMS = frozenset(['egl', 'wgl'])


class WindowSystemUnavailable(RuntimeError):
    """The window system asked for is not registered, or will not import."""


#: A probe answers None where the named window system imports, and the error
#: that stopped it where it does not.
Probe = Callable[[str], Optional[BaseException]]


def offscreenName(platform: Optional[str] = None) -> str:
    """The window system that renders with no window on ``platform``.

    ``platform`` defaults to :data:`sys.platform`.
    """
    if platform is None:
        platform = sys.platform
    for prefix, name in OFFSCREEN_BY_PLATFORM:
        if platform.startswith(prefix):
            return name
    return DEFAULT_OFFSCREEN


def choose(
    requested: str = '',
    *,
    environment: Optional[str] = None,
    preference: Optional[str] = None,
    platform: Optional[str] = None,
    registered: Sequence[str],
    probe: Probe,
) -> str:
    """The name of the window system a context should open on.

    requested -- the definition's ``windowsystem`` field
    environment -- ``OPENGLCONTEXT_BACKEND``, or None where it is unset
    preference -- the user's ``defaultcontext.txt``, or None where there is none
    platform -- ``sys.platform``, which decides what ``'offscreen'`` means
    registered -- the registered names, in registration order
    probe -- answers None for a name that imports, else the error

    A name that was asked for -- by the definition or by the environment --
    has to be usable, and :class:`WindowSystemUnavailable` says why it is not.
    A preference that is not usable is reported and passed over, because a
    stale file must not stop every program on the machine from opening a
    window.  With nothing asked for, the windowed systems are tried in
    :data:`PLATFORM_ORDER`.
    """
    for asked in (requested, environment):
        if asked:
            return _usable(asked, platform, registered, probe)
    if preference:
        try:
            return _usable(preference, platform, registered, probe)
        except WindowSystemUnavailable as err:
            log.warning('The preferred window system is not usable: %s', err)
    ordered = [name for name in PLATFORM_ORDER if name in registered]
    ordered += [name for name in registered
                if name not in ordered and name not in OFFSCREEN_SYSTEMS]
    failures = []
    for name in ordered:
        error = probe(name)
        if error is None:
            return name
        failures.append('%s (%s)' % (name, error))
    raise WindowSystemUnavailable(
        'No window system with a window is available; registered: %s; '
        'unavailable: %s'
        % (', '.join(registered) or 'none', '; '.join(failures) or 'none'))


def _usable(name: str, platform: Optional[str], registered: Sequence[str],
            probe: Probe) -> str:
    """``name``, or ``'offscreen'`` made concrete, if it can be opened."""
    if name == OFFSCREEN:
        name = offscreenName(platform)
    if name not in registered:
        raise WindowSystemUnavailable(
            'No window system is registered as %r; registered: %s'
            % (name, ', '.join(registered) or 'none'))
    error = probe(name)
    if error is not None:
        raise WindowSystemUnavailable(
            'The %r window system will not import: %s' % (name, error))
    return name


def registered() -> tuple[str, ...]:
    """The registered window-system names, in registration order.

    The engine's own are registered as :mod:`OpenGLContext` loads; those
    other distributions declare in :data:`ENTRY_POINT_GROUP` are added the
    first time this is asked, from their metadata, without importing them.
    """
    plugins.discover(plugins.WindowSystem, ENTRY_POINT_GROUP)
    return tuple(plugin.name for plugin in plugins.WindowSystem.all())


def _plugin(name: str) -> plugins.WindowSystem:
    if name not in registered():
        raise WindowSystemUnavailable(
            'No window system is registered as %r; registered: %s'
            % (name, ', '.join(registered()) or 'none'))
    plugin = plugins.WindowSystem.by_name(name)
    assert isinstance(plugin, plugins.WindowSystem)
    return plugin


def load(name: str) -> type[WindowSystem]:
    """The :class:`WindowSystem` subclass registered as ``name``.

    Raises :class:`WindowSystemUnavailable` naming the registered set where
    ``name`` is not one of them, and carrying the import error where its
    toolkit is not installed.
    """
    path = _plugin(name).import_path
    try:
        loaded = importByName(path)
    except ImportError as err:
        raise WindowSystemUnavailable(
            'The %r window system will not import (%s): %s' % (name, path, err)
        ) from err
    if not (isinstance(loaded, type) and issubclass(loaded, WindowSystem)):
        raise WindowSystemUnavailable(
            '%s, registered as the %r window system, is not a WindowSystem'
            % (path, name))
    return loaded


def probe(name: str) -> Optional[BaseException]:
    """None where ``name`` loads, else the error that stopped it."""
    try:
        load(name)
    except WindowSystemUnavailable as err:
        return err.__cause__ or err
    return None
