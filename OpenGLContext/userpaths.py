"""Where this user's files belong on this platform.

One answer to "where does a per-user file go", so that a settings file, a cached
download and anything added later land in the same place and follow the same rule
rather than each inventing one.

The rule is the platform's own convention: ``%APPDATA%`` on Windows,
``$XDG_CONFIG_HOME`` (or ``~/.config``) elsewhere.  Callers add their own
subdirectory -- :meth:`OpenGLContext.contextconfig.ContextConfig.getUserDirectory`
and :func:`OpenGLContext.loaders.resolver._default_cache_dir` both do -- so this
module never creates anything, it only says where.

A file the *user* is meant to find again has its own answer:
:func:`picturesdirectory` is where a screenshot goes, which is the picture
folder the desktop shows them rather than anywhere of ours.
"""
import os
import sys

__all__ = ['appdatadirectory', 'picturesdirectory']


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


def picturesdirectory() -> str:
    """The directory this user's pictures belong in.

    Windows: the Pictures known folder, asked of the shell so that a folder the
    user has moved -- or that a cloud client has redirected -- is followed
    rather than guessed at.
    macOS: ``~/Pictures``, which is the Finder's own.
    Everywhere else: ``$XDG_PICTURES_DIR``, then the ``user-dirs.dirs`` the
    desktop writes when the folder has been renamed, then ``~/Pictures``.

    Raises OSError when there is no home directory to answer from, which a
    caller with somewhere else to fall back to can catch.
    """
    if sys.platform == 'win32':
        known = _knownpicturesfolder()
        if known:
            return known
        profile = os.environ.get('USERPROFILE')
        return os.path.join(profile or _homedirectory(), 'Pictures')
    if sys.platform == 'darwin':
        return os.path.join(_homedirectory(), 'Pictures')
    configured = os.environ.get('XDG_PICTURES_DIR') or _xdguserdir('PICTURES')
    return configured or os.path.join(_homedirectory(), 'Pictures')


def _homedirectory() -> str:
    """This user's home directory, however the platform says so."""
    home = os.environ.get('HOME')
    if home:
        return home
    possible = os.path.abspath(os.path.expanduser('~'))
    if os.path.isdir(possible):
        return possible
    raise OSError("""Unable to determine the user's home directory""")


def _xdguserdir(name: str) -> str:
    """One directory from the desktop's ``user-dirs.dirs``; '' if it says none.

    The file is shell syntax, but only ever as ``NAME="$HOME/Path"`` -- so it is
    read as the data it is rather than run, and a line in any other shape is
    passed over.
    """
    config = os.environ.get('XDG_CONFIG_HOME')
    if not config:
        try:
            config = os.path.join(_homedirectory(), '.config')
        except OSError:
            return ''
    wanted = 'XDG_%s_DIR' % (name,)
    try:
        with open(os.path.join(config, 'user-dirs.dirs')) as source:
            lines = source.readlines()
    except OSError:
        return ''
    for line in lines:
        line = line.strip()
        if line.startswith('#') or '=' not in line:
            continue
        key, _sep, value = line.partition('=')
        if key.strip() != wanted:
            continue
        value = value.strip().strip('"').strip("'")
        if value.startswith('$HOME'):
            value = _homedirectory() + value[len('$HOME'):]
        return value
    return ''


def _knownpicturesfolder():  # pragma: no cover - needs Windows
    """The Pictures known folder, from the Windows shell; None if it will not say."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [('Data1', wintypes.DWORD), ('Data2', wintypes.WORD),
                    ('Data3', wintypes.WORD), ('Data4', ctypes.c_ubyte * 8)]

    # FOLDERID_Pictures, from the Windows known-folder list.
    folder = GUID(0x33E28130, 0x4E1E, 0x4676,
                  (ctypes.c_ubyte * 8)(0x83, 0x5A, 0x98, 0x39,
                                       0x5C, 0x3B, 0xC3, 0xBB))
    path = ctypes.c_wchar_p()
    try:
        result = ctypes.windll.shell32.SHGetKnownFolderPath(
            ctypes.byref(folder), 0, None, ctypes.byref(path))
    except (AttributeError, OSError):
        return None
    if result != 0:
        return None
    try:
        return path.value
    finally:
        ctypes.windll.ole32.CoTaskMemFree(path)
