"""Per-user configuration and backend selection for :class:`~OpenGLContext.context.Context`.

Resolves the user's app-data directory, reads and writes the default-font and
default-backend preference files, and loads a backend ``Context`` subclass from
setuptools entry points. The members are ``classmethod`` / ``staticmethod`` with
no per-instance state.

Mixed into ``Context`` as a base, so ``cls`` is the concrete context class. The
two members that name the concrete ``Context`` class directly (``getTTFFiles``,
``fromConfig``) live on ``Context`` itself.
"""

import os
import sys
import logging

from OpenGLContext import plugins
from OpenGL._bytes import bytes, unicode

log = logging.getLogger(__name__)


class ContextConfigMixin:
    """Per-user config + backend-factory surface for Context (classmethods)."""

    ### app-framework stuff
    APPLICATION_NAME = "OpenGLContext"

    @classmethod
    def getApplicationName(cls):
        """Retrieve the application name for configuration purposes"""
        return cls.APPLICATION_NAME

    @classmethod
    def getUserAppDataDirectory(cls):
        """Retrieve user-specific configuration directory

        Default implementation gives a directory-name in the
        user's (system-specific) "application data" directory
        named
        """
        from OpenGLContext.browser import homedirectory

        base = homedirectory.appdatadirectory()
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

    @classmethod
    def getDefaultTTFFont(cls, type="sans"):
        """Get the current user's preference for a default font"""
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultfont-%s.txt" % (type.lower(),))
        name = None
        try:
            name = open(filename).readline().strip()
        except IOError as err:
            pass
        if not name:
            name = None
        return name

    @classmethod
    def setDefaultTTFFont(cls, name, type="sans"):
        """Set the current user's preference for a default font"""
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultfont-%s.txt" % (type.lower(),))
        if not name:
            try:
                os.remove(filename)
            except Exception as err:
                return False
            else:
                return True
        else:
            try:
                open(filename, "w").write(name)
            except IOError as err:
                return False
            return True

    @classmethod
    def getContextTypes(cls, type=plugins.InteractiveContext):
        """Retrieve the set of defined context types

        type -- testing type key from setup.py for the registered modules

        returns list of setuptools entry-point objects which can be passed to
        getContextType( name ) to retrieve the actual context type.
        """
        return type.all()

    @classmethod
    def getContextType(
        cls,
        entrypoint=None,
        type=plugins.InteractiveContext,
    ):
        """Load a single context type via entry-point resolution

        returns a Context sub-class *or* None if there is no such
        context defined/available, will have a ContextMainLoop method
        for running the Context top-level loop.
        """
        if entrypoint is None:
            entrypoint = cls.getDefaultContextType() or "glfw"
        log.warning("Default context type: %s", entrypoint)
        if isinstance(entrypoint, (bytes, unicode)):
            for ep in cls.getContextTypes(type):
                if entrypoint == ep.name:
                    return cls.getContextType(ep, type=type)
            return None
        try:
            classObject = entrypoint.load()
        except ImportError as err:
            return None
        else:
            return classObject

    @classmethod
    def getDefaultContextType(cls):
        """Get the current user's preference for a default context type

        Checks in order:
            1. OPENGLCONTEXT_BACKEND environment variable
            2. ~/.OpenGLContext/defaultcontext.txt file

        Valid backend names: glut, pygame, wx, glfw, 
        """
        # First check environment variable
        name = os.environ.get('OPENGLCONTEXT_BACKEND')
        if name:
            return name.strip()

        # Fall back to config file
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultcontext.txt")
        name = None
        if os.path.exists(filename):
            try:
                name = open(filename).readline().strip()
            except IOError as err:
                pass
        else:
            log.warning("No default context type in %s", filename)
        if not name:
            name = None
        return name

    @classmethod
    def setDefaultContextType(cls, name):
        """Set the current user's preference for a default font"""
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join(directory, "defaultcontext.txt")
        if not name:
            try:
                os.remove(filename)
            except Exception as err:
                return False
            else:
                return True
        else:
            try:
                open(filename, "w").write(name)
            except IOError as err:
                return False
            return True
