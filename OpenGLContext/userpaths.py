"""Where this user's files belong on this platform.

One answer to "where does a per-user file go", so that a settings file, a cached
download and anything added later land in the same place and follow the same rule
rather than each inventing one.

The rule is the platform's own convention: ``%APPDATA%`` on Windows,
``$XDG_CONFIG_HOME`` (or ``~/.config``) elsewhere.  Callers add their own
subdirectory -- :meth:`OpenGLContext.contextconfig.ContextConfig.getUserDirectory`
and :func:`OpenGLContext.loaders.resolver._default_cache_dir` both do -- so this
module never creates anything, it only says where.
"""
import os
import sys

__all__ = ['appdatadirectory']


def appdatadirectory() -> str:
    """The directory for this user's application-specific files.

    Windows: ``%APPDATA%``, the roaming application-data directory.
    Everywhere else: ``$XDG_CONFIG_HOME``, or ``~/.config`` when it is unset --
    the XDG Base Directory default, so OpenGLContext's files sit beside every
    other application's rather than as one more dotfile in ``$HOME``.

    Raises OSError when no such directory can be determined, which a caller that
    has somewhere else to fall back to can catch (the asset cache drops to the
    system temp directory).
    """
    if sys.platform == 'win32':
        appdata = os.environ.get('APPDATA')
        if appdata:
            return appdata
    else:
        xdg = os.environ.get('XDG_CONFIG_HOME')
        if xdg:
            return xdg
        home = os.environ.get('HOME')
        if home:
            return os.path.join(home, '.config')

    # No environment to go on -- fall back to whatever ~ expands to, which on a
    # service account or a stripped container may still be a real directory.
    possible = os.path.abspath(os.path.expanduser('~'))
    if os.path.isdir(possible):
        return possible if sys.platform == 'win32' else os.path.join(possible, '.config')
    raise OSError("""Unable to determine the user's application-data directory""")
