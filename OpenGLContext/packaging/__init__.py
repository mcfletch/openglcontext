"""Shipping an application built on the engine

An application is delivered as a frozen bundle -- one directory holding a
Python runtime, the engine and the game, with no interpreter to install -- or
as a native package that puts such a bundle in a system directory. Both need
answers the engine is the one that has:

    which windowing backends this application does not use
    which shared libraries the ones it does use need from the operating system
    which of the engine's modules are reached by name rather than by import

The last of those is answered by the PyInstaller hooks in
``OpenGLContext/__pyinstaller``, which PyInstaller finds by itself. The two
above are here, for a ``.spec`` file and for :mod:`OpenGLContext.packaging.deb`
to read.

    >>> from OpenGLContext import packaging
    >>> packaging.unused_backend_modules(keep=['glfw'])
    ['OpenGLContext_qt', 'PySide6', 'pygame', 'shiboken6', 'tkinter', 'wx']

Nothing in this package is imported by the engine at run time, and nothing in
it draws anything.
"""

__all__ = ['BACKEND_MODULES', 'SESSIONS', 'SESSION_ALTERNATIVE', 'SYSTEM_LIBRARIES',
           'WAYLAND_DECORATIONS', 'WAYLAND_LIBRARIES', 'X11_LIBRARIES',
           'session_libraries', 'session_recommendations',
           'unused_backend_modules']

#: The modules each windowing backend needs, keyed by the name the backend is
#: selected with (``OPENGLCONTEXT_BACKEND``, and the name its plug-ins are
#: registered under in :mod:`OpenGLContext.plugins`).
#:
#: The engine's own ``<name>context`` modules are deliberately not listed: they
#: are a few kilobytes of Python that report the backend as unavailable when
#: their toolkit is missing, which is what a bundle wants, while the toolkits
#: themselves are tens to hundreds of megabytes. GLUT has no entry of its own
#: because its bindings come from PyOpenGL, which every bundle already carries,
#: and neither do the two offscreen backends -- ``egl`` on Linux and ``wgl`` on
#: Windows -- which have no toolkit and no window between them. They are listed
#: so that a bundle rendering without one can say so.
#:
#: ``tkinter`` is the standard library rather than a third-party package, and is
#: named anyway: a freezer follows the import and brings the whole of Tcl/Tk
#: with it, which is megabytes a bundle that opens no Tk window has no use for.
BACKEND_MODULES = {
    'egl': (),
    'glfw': ('glfw',),
    'glut': (),
    'pygame': ('pygame',),
    'qt': ('OpenGLContext_qt', 'PySide6', 'shiboken6'),
    'tk': ('tkinter',),
    'wgl': (),
    'wx': ('wx',),
}

#: The Debian packages holding the shared libraries an installed bundle loads
#: whatever kind of desktop it is running on: the GL and GLU the bindings
#: themselves open, and the EGL the Wayland path creates its context through.
#: They are named as run-time dependencies rather than bundled: a driver's GL
#: library belongs to the machine, and a copy carried in a package would be the
#: wrong one. ``libglu1-mesa`` is the one of the three a desktop does not
#: already have -- nothing but OpenGL software wants GLU.
SYSTEM_LIBRARIES = (
    'libegl1',
    'libgl1',
    'libglu1-mesa',
)

#: What GLFW opens on a Wayland session, over the above. ``libdecor`` is how a
#: Wayland window gets a titlebar at all: the compositor draws none, so GLFW
#: draws its own through that library.
WAYLAND_LIBRARIES = (
    'libdecor-0-0',
    'libwayland-client0',
    'libwayland-cursor0',
    'libwayland-egl1',
    'libxkbcommon0',
)

#: What GLFW opens on an X11 session, over the common set.
X11_LIBRARIES = (
    'libx11-6',
    'libx11-xcb1',
    'libxcursor1',
    'libxext6',
    'libxi6',
    'libxinerama1',
    'libxrandr2',
    'libxrender1',
    'libxxf86vm1',
)

#: ``libdecor`` draws a titlebar through a plug-in, and finds none unless one is
#: installed -- the window then comes up with no way to move or close it. Either
#: plug-in does. A *recommendation* rather than a requirement: without one the
#: game still runs, and a game played full-screen never wanted a titlebar and
#: should not drag GTK in to be told so.
WAYLAND_DECORATIONS = (
    'libdecor-0-0',
    'libdecor-0-plugin-1-gtk | libdecor-0-plugin-1-cairo',
)

#: One dependency standing for "a desktop of either kind", as Debian's own
#: alternative. A machine logged into X11 has ``libX11`` already and one logged
#: into Wayland has ``libwayland-client`` already, so on any machine that can
#: run the game this is satisfied by what is there and installs nothing.
#: Wayland is named first because that is what apt reaches for on a machine
#: that has neither -- a container being built to run the game headless, most
#: often.
#:
#: One library stands for its whole stack. The rest of each set travels with it
#: on any real desktop, and naming them all would turn "either" back into
#: "both", which is the thing that pulls one desktop's libraries onto the other.
SESSION_ALTERNATIVE = 'libwayland-client0 | libx11-6'

#: What a package can be built for. ``either`` is the default and takes the
#: machine as it finds it; the two pinned choices are for a fleet whose session
#: is known, and ``both`` for one that has to install regardless -- see
#: :func:`session_libraries`.
SESSIONS = ('either', 'wayland', 'x11', 'both')

def unused_backend_modules(keep=('glfw',)):
    """Report the toolkit modules an application keeping only *keep* can leave out

    A frozen bundle picks up every toolkit that happens to be installed
    alongside the engine, because the engine imports the Qt backend for its
    registration side effect and names the others in its plug-in registries.
    An application drives one backend and pays for the rest in download size,
    so a ``.spec`` file passes this to PyInstaller's ``excludes``.

    keep -- the backend names the application can open a window with, from
        :data:`BACKEND_MODULES`

    Raises ``ValueError`` for a name that is not a backend, since a typo would
    otherwise quietly excise the toolkit the application actually runs on, and
    for an empty *keep*, which describes an application that cannot draw.
    """
    keep = list(keep)
    if not keep:
        raise ValueError(
            'An application needs a windowing backend; keep one of %s'
            % (', '.join(sorted(BACKEND_MODULES)),)
        )
    unknown = [name for name in keep if name not in BACKEND_MODULES]
    if unknown:
        raise ValueError(
            'Not a windowing backend: %s; known backends are %s'
            % (', '.join(unknown), ', '.join(sorted(BACKEND_MODULES)))
        )
    kept = set()
    for name in keep:
        kept.update(BACKEND_MODULES[name])
    unused = set()
    for name, modules in BACKEND_MODULES.items():
        if name not in keep:
            unused.update(modules)
    return sorted(unused - kept)


def _checked(session):
    """*session*, or a ValueError naming what there is"""
    if session not in SESSIONS:
        raise ValueError(
            'Not a windowing system this can build for: %r; the ones that are: %s'
            % (session, ', '.join(SESSIONS))
        )
    return session


def session_libraries(session='either'):
    """The libraries a package built for *session* asks the machine for

    GLFW opens every windowing library through ``dlopen`` rather than linking
    it, so a package's dependencies cannot be derived from its binaries the way
    ``dpkg-shlibdeps`` would: the names are the ones GLFW asks for, and they are
    declared here.

    What is worth declaring is what a graphical session does not already imply.
    A machine logged into X11 has ``libX11`` by definition, and one logged into
    Wayland has ``libwayland-client`` -- but neither is guaranteed to have GLU,
    which nothing but OpenGL software wants.

    session -- one of :data:`SESSIONS`:

        ``'either'``
            the default. The windowing stack is one dependency
            (:data:`SESSION_ALTERNATIVE`) that either kind of desktop satisfies,
            so the package takes the machine as it finds it and installs nothing
            it does not already have. GLFW picks the matching build of itself at
            run time from ``XDG_SESSION_TYPE``.
        ``'wayland'``, ``'x11'``
            that stack named in full, for a fleet whose session is known.
        ``'both'``
            every library either stack could want, for a package that has to
            install whatever else is true, at the cost of pulling one desktop's
            libraries onto the other.

    Whichever is chosen, the bundle carries GLFW's builds for both: this is what
    the package declares, not what it can do.
    """
    asked = set(SYSTEM_LIBRARIES)
    if _checked(session) == 'either':
        asked.add(SESSION_ALTERNATIVE)
    if session in ('wayland', 'both'):
        asked.update(WAYLAND_LIBRARIES)
    if session in ('x11', 'both'):
        asked.update(X11_LIBRARIES)
    return sorted(asked)


def session_recommendations(session='either'):
    """What a package built for *session* is better for having

    Only Wayland has any: X11 decorations are the window manager's business,
    and on Wayland they are the application's. A package that could meet a
    Wayland session -- which is any package not pinned to X11 -- recommends
    them, so that a player on Wayland gets a window they can move.
    """
    if _checked(session) == 'x11':
        return []
    # A stack named in full already requires libdecor itself; what is left to
    # recommend is the plug-in that makes it draw something.
    required = set(session_libraries(session))
    return [name for name in WAYLAND_DECORATIONS if name not in required]
