"""The context class a test script or tutorial builds its window on

``getInteractive()`` answers :class:`~OpenGLContext.context.Context`, whose
window system is chosen when the context is built -- from
``OPENGLCONTEXT_BACKEND``, the user's preference, or the first that imports.
Named, it answers the context class with that window system chosen::

    BaseContext = testingcontext.getInteractive()       # Context
    BaseContext = testingcontext.getInteractive('tk')   # Context on Tk

An application writes ``class Game(Context)`` and names its window system in
its definition; see :mod:`OpenGLContext.windowsystem`.
"""

import warnings
from typing import Optional

from OpenGLContext import plugins, windowsystem
from OpenGLContext.context import Context

#: The context class a test runner has every test context built on, where it
#: names one; None leaves the choice to the window-system preference.
CONFIGURED_BASE: Optional[type[Context]] = None
REQUIRED_EXTENSION_MISSING = 3 # process return-code for a missing extension

__all__ = (
    'CONFIGURED_BASE',
    'REQUIRED_EXTENSION_MISSING',
    'contextClassFor',
    'getInteractive',
    'getVRML',
)


def getInteractive(preference: Optional[str] = None) -> type[Context]:
    """The context class to build a window on

    preference -- the name of a registered window system, or None to leave
        the choice to the definition, the environment and the user's
        configuration as the context is built

    With no preference this is :class:`~OpenGLContext.context.Context`.
    Named, it is the class for that window system (``'glfw'`` answers
    :class:`~OpenGLContext.glfwcontext.GLFWContext`), and raises
    :class:`~OpenGLContext.windowsystem.WindowSystemUnavailable` -- a
    ``RuntimeError`` -- where the name is not registered or its toolkit will
    not import.  What a caller does with the answer is subclass it, and a
    missing base class is reported by Python several frames away from the
    cause, naming neither the window system nor the package to install.
    """
    if CONFIGURED_BASE:
        return CONFIGURED_BASE
    if preference is None:
        return Context
    name = windowsystem.choose(
        preference, registered=windowsystem.registered(), probe=windowsystem.probe)
    return contextClassFor(name)


def contextClassFor(name: str) -> type[Context]:
    """The published context class for the window system ``name``

    The one its ``*context`` module names where there is one, and otherwise
    ``Context`` with ``windowSystemName`` set to ``name``.
    """
    plugin = plugins.InteractiveContext.by_name(name)
    if plugin is not None:
        loaded = plugin.load()
        if isinstance(loaded, type) and issubclass(loaded, Context):
            return loaded
    return type('%sContext' % (name.capitalize(),), (Context,),
                {'windowSystemName': name})


def getVRML(preference: Optional[str] = None) -> type[Context]:
    """:func:`getInteractive`: every Context loads scenes, so there is one
    class to answer"""
    warnings.warn(
        'testingcontext.getVRML is getInteractive: every Context loads scenes',
        DeprecationWarning, stacklevel=2)
    return getInteractive(preference)
