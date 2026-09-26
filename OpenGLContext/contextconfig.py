"""Per-user configuration for :class:`~OpenGLContext.context.Context`.

Resolves the user's app-data directory, and reads and writes the default-font
and preferred-window-system files.  The members are ``classmethod`` /
``staticmethod`` with no per-instance state.

Mixed into ``Context`` as a base, so ``cls`` is the concrete context class.
Everything here reads or writes the user's own application-data directory.
"""

import os
import sys
import logging
import warnings
from typing import TYPE_CHECKING, Any, ClassVar, Optional

from OpenGL.plugins import Plugin

from OpenGLContext import atomicfiles, plugins, renderoptions

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.text.ttfregistry import TTFRegistry

log = logging.getLogger(__name__)


class ContextConfigMixin:
    """Per-user config + backend-factory surface for Context (classmethods)."""

    ### app-framework stuff
    APPLICATION_NAME = "OpenGLContext"

    @classmethod
    def getApplicationName(cls) -> str:
        """Retrieve the application name for configuration purposes"""
        return cls.APPLICATION_NAME

    @classmethod
    def getUserAppDataDirectory(cls) -> str:
        """Retrieve user-specific configuration directory

        Default implementation gives a directory-name in the
        user's (system-specific) "application data" directory
        named
        """
        from OpenGLContext import userpaths

        base = userpaths.appdatadirectory()
        if sys.platform == "win32":
            name = cls.getApplicationName()
        else:
            # use a hidden directory on non-win32 systems
            # as we are storing in the user's home directory
            name = "%s" % (cls.getApplicationName())
        path = os.path.join(
            base,
            name,
        )
        if not os.path.isdir(path):
            os.makedirs(path, mode=0o770)
        return path

    #: The system's TrueType fonts, scanned once for the process and cached
    #: in the user's application-data directory; see :meth:`getTTFFiles`.
    ttfFileRegistry: ClassVar[Optional['TTFRegistry']] = None

    @classmethod
    def getTTFFiles(cls) -> 'TTFRegistry':
        """The TrueType font-file registry, loaded or scanned on first use

        Read from ``font_metadata.cache`` in the user's application-data
        directory where there is one, scanned from the system's fonts and
        saved there where there is not.  One registry serves the process.
        """
        registry = ContextConfigMixin.ttfFileRegistry
        if registry is None:
            registryFile = os.path.join(
                cls.getUserAppDataDirectory(), "font_metadata.cache"
            )
            from OpenGLContext.scenegraph.text import ttfregistry

            registry = ttfregistry.TTFRegistry()
            if os.path.isfile(registryFile):
                log.info("Loading font metadata from cache %r", registryFile)
                registry.load(registryFile)
                if not registry.fonts:
                    log.warning("Re-scanning fonts, no fonts found in cache")
                    registry.scan()
                    registry.save()
                    log.info("Font metadata stored in cache %r", registryFile)
            else:
                log.warning(
                    "Scanning font metadata into cache %r, please wait", registryFile
                )
                registry.scan()
                registry.save(registryFile)
                log.info("Font metadata stored in cache %r", registryFile)
            ContextConfigMixin.ttfFileRegistry = registry
        # The font providers find their fonts through the same registry.
        from OpenGLContext.scenegraph.text import fontprovider
        fontprovider.setTTFRegistry(registry)
        return registry

    @classmethod
    def getDefaultTTFFont(cls, type: str = "sans") -> Optional[str]:
        """Get the current user's preference for a default font"""
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultfont-%s.txt" % (type.lower(),))
        name = None
        try:
            name = open(filename).readline().strip()
        except IOError:
            pass
        if not name:
            name = None
        return name

    @classmethod
    def setDefaultTTFFont(cls, name: Optional[str], type: str = "sans") -> bool:
        """Set the current user's preference for a default font"""
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultfont-%s.txt" % (type.lower(),))
        if not name:
            try:
                os.remove(filename)
            except Exception:
                return False
            else:
                return True
        else:
            try:
                atomicfiles.write_text(filename, name)
            except IOError:
                return False
            return True

    @classmethod
    def getContextTypes(
        cls,
        type: type[plugins.Context] = plugins.InteractiveContext,
    ) -> list[Plugin]:
        """The registered per-window-system context classes, as plug-ins

        Deprecated: a context's window system is its definition's
        ``windowsystem`` field, and :func:`OpenGLContext.windowsystem.registered`
        names the choices.
        """
        warnings.warn(
            'Context.getContextTypes is deprecated; the window systems are '
            'OpenGLContext.windowsystem.registered()',
            DeprecationWarning, stacklevel=2)
        registered: list[Plugin] = type.all()
        return registered

    @classmethod
    def getContextType(
        cls,
        entrypoint: Any = None,
        type: type[plugins.Context] = plugins.InteractiveContext,
    ) -> Any:
        """The context class for a window system, or None where it will not load

        Deprecated: every context is a :class:`~OpenGLContext.context.Context`,
        and its window system is its definition's ``windowsystem`` field.
        What this answers is the class the window system's ``*context``
        module publishes.
        """
        warnings.warn(
            'Context.getContextType is deprecated; subclass Context and name '
            'the window system in the definition\'s windowsystem field',
            DeprecationWarning, stacklevel=2)
        return cls._contextType(entrypoint, type)

    @classmethod
    def _contextType(cls, entrypoint: Any, type: type[plugins.Context]) -> Any:
        if entrypoint is None:
            entrypoint = cls.getDefaultContextType() or "glfw"
        if isinstance(entrypoint, (bytes, str)):
            for ep in type.all():
                if entrypoint == ep.name:
                    return cls._contextType(ep, type)
            return None
        try:
            classObject = entrypoint.load()
        except ImportError:
            return None
        else:
            return classObject

    @classmethod
    def getOffscreenBackendName(cls, platform: Optional[str] = None) -> str:
        """Which window system renders with no window here.

        `platform` defaults to :data:`sys.platform`; pass one to ask about
        another.  See :func:`OpenGLContext.windowsystem.offscreenName`, and
        ``windowsystem='offscreen'``, which asks for it.
        """
        from OpenGLContext import windowsystem

        return windowsystem.offscreenName(platform)

    @classmethod
    def getOffscreenContextType(cls, platform: Optional[str] = None) -> Optional[type]:
        """The context class that renders with no window here, or None.

        The one the offscreen window system's ``*context`` module publishes;
        None where its bindings cannot be loaded -- an EGL with no library
        behind it, say.  ``Context(windowsystem='offscreen')`` asks for the
        same thing without naming a class.
        """
        loaded: Optional[type] = cls._contextType(
            cls.getOffscreenBackendName(platform), plugins.Context
        )
        return loaded

    @classmethod
    def getDefaultContextType(cls) -> Optional[str]:
        """Get the current user's preference for a default window system

        Checks in order:
            1. OPENGLCONTEXT_BACKEND environment variable
            2. the user's defaultcontext.txt (:meth:`getWindowSystemPreference`)
        """
        named = renderoptions.env_text('OPENGLCONTEXT_BACKEND')
        if named:
            return named
        return cls.getWindowSystemPreference()

    @classmethod
    def getWindowSystemPreference(cls) -> Optional[str]:
        """This user's preferred window system, or None where they have none

        Read from ``defaultcontext.txt`` in the user's application-data
        directory, which :meth:`setDefaultContextType` writes.
        """
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultcontext.txt")
        name = None
        if os.path.exists(filename):
            try:
                with open(filename) as preference:
                    name = preference.readline().strip()
            except IOError:
                pass
        else:
            log.debug("No preferred window system in %s", filename)
        return name or None

    @classmethod
    def setDefaultContextType(cls, name: Optional[str]) -> bool:
        """Set the current user's preference for a default backend"""
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultcontext.txt")
        if not name:
            try:
                os.remove(filename)
            except Exception:
                return False
            else:
                return True
        else:
            try:
                atomicfiles.write_text(filename, name)
            except IOError:
                return False
            return True
