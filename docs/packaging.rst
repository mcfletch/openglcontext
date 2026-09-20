Packaging an application
========================

.. rst-class:: introduction

An application built on the engine is delivered to somebody who has no Python:
a **frozen bundle** — one directory holding an interpreter, the engine and the
application, entered through an executable — or a **native package** that
installs such a tree into a system directory. The engine supplies what neither
can work out for itself: which of its modules are reached by name rather than
by import, which windowing toolkits an application is not using, and which
libraries it asks the machine for.

.. _freezing:

Freezing with PyInstaller
-------------------------

PyInstaller follows import statements, and the engine reaches a great deal of
itself by name: every windowing backend, every file-format loader, every
viewer adapter and every scenegraph node is declared in
``OpenGLContext.plugins`` as a string and imported when a scene asks for it.
So are the generated resource modules a ``res://`` URL names and the font
atlas a size of text needs. Beneath that, PyOpenGL chooses its platform module
and its array format handlers the same way (``OpenGL.plugins``), and opens the
GLSL sources, the environment maps and the GLFW library by path.

None of that is anything an application should have to list. Both packages
ship **PyInstaller hooks** — in ``OpenGL/__pyinstaller/`` and
``OpenGLContext/__pyinstaller/`` — which PyInstaller finds by itself through
the ``pyinstaller40`` entry point, with nothing to switch on. They read the
registries of the installed engine rather than a list written out by hand, so
a node or a shader added to the engine reaches a frozen application without an
edit anywhere.

A ``.spec`` then names the application's own data and what to leave out:

.. code-block:: python

   from PyInstaller.utils.hooks import collect_data_files
   from OpenGLContext import packaging

   analysis = Analysis(
       ['packaging/entry.py'],
       datas=collect_data_files('mygame'),
       excludes=packaging.unused_backend_modules(keep=['glfw']),
   )

``unused_backend_modules()`` is the one that saves real weight. The engine
imports the Qt backend for its registration side effect and names the others
in its registries, so a bundle picks up whichever toolkits happen to be
installed beside it — a quarter of a gigabyte of Qt against an application
that opens its window with GLFW. Naming the backends the application does use
leaves the rest out. The engine's own ``<name>context`` modules stay: they are
kilobytes, and they report the backend as unavailable, which is what a bundle
wants. The names it takes are the ones ``OPENGLCONTEXT_BACKEND`` takes —
``glfw``, ``glut``, ``pygame``, ``qt``, ``tk``, ``wx``, and, for a bundle that
renders offscreen, ``egl`` on Linux or ``wgl`` on Windows. ``tkinter`` is
among what it excludes although it is the standard library: a freezer follows
the import and brings the whole of Tcl/Tk, which is megabytes for a bundle
that opens no Tk window.

One bundle, several commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Most of a bundle's size is the interpreter and the libraries, and they are the
same whichever command runs, so an application that ships a tool beside it — a
world baker, a downloader — should not freeze each command separately.
``OpenGLContext.packaging.multicall`` gives one bundle several executables,
each named after the command it runs and recognised by the name it was run
under:

.. code-block:: python

   from OpenGLContext.packaging.multicall import command_modules, run

   COMMANDS = {
       'mygame': 'mygame.game:main',
       'glisteel-bake': 'glisteel_editor.bake:main',
   }
   MODULES = command_modules(COMMANDS)   # for the spec's hiddenimports

   if __name__ == '__main__':
       sys.exit(run(COMMANDS))

The ``.spec`` builds one ``EXE`` per key from the one analysis, and
``COLLECT`` puts them all beside a single ``_internal``. A command sees
``sys.argv`` exactly as it would have if it had been installed as its own
console script, and a bundle imports only the command it was actually asked
for.

.. _deb:

A Debian package
----------------

``oglc-deb`` builds a ``.deb`` holding the application *and* the Python that
runs it. Nothing outside the package is needed: no system Python, no virtual
environment for the player to make, no pip at install time.

.. code-block:: bash

   uv python install --install-dir runtime 3.12
   oglc-deb --project . --runtime runtime --output dist

The result installs under ``/opt/<package>``, with the application's console
scripts linked into ``/usr/games`` and a desktop menu entry:

.. code-block:: python

   /opt/mygame/python/    the interpreter and its standard library
   /opt/mygame/venv/      the application and everything it imports
   /usr/games/mygame      a link to the console script
   /usr/share/applications/mygame.desktop

The interpreter has to be a **relocatable** build — one that finds its
standard library beside itself rather than at a path compiled into it. The
python-build-standalone distributions that ``uv python install`` fetches are
such a build; ``--runtime`` takes the directory or a tar archive of one. That
is what lets the environment be assembled in a staging directory by an
ordinary user and run from ``/opt``: the three places a virtual environment
records where it was made — ``pyvenv.cfg``, the ``#!`` line of every console
script, and the symlink that is its interpreter — are written as the paths it
will be installed at (``OpenGLContext.packaging.appdir``).

The package is byte-compiled with the installed paths recorded, since ``/opt``
is read-only to the player and an environment that arrives uncompiled would
compile itself again on every run and never keep the result. The parts of the
interpreter an application cannot reach — the C headers, Tk, IDLE, pip, the
manual — are left out, some twenty megabytes; ``--keep-unused`` ships them.

What the machine is asked for
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The graphics libraries are named as dependencies rather than bundled: a
driver's GL library belongs to the machine, and a copy carried in a package
would be the wrong one. They cannot be derived from the binaries the way
``dpkg-shlibdeps`` would, either — GLFW opens every one of them through
``dlopen`` rather than linking it, so nothing about them appears in an ELF
header. The names are declared, in ``OpenGLContext.packaging``.

What is worth declaring is what a graphical session does not already imply. A
machine logged into X11 has ``libX11`` by definition, and one logged into
Wayland has ``libwayland-client``. Neither is guaranteed to have GLU, which
nothing but OpenGL software wants, or ``libdecor``, without which a Wayland
window comes up with no titlebar — no way to move it and no way to close it.

So a package asks for **either** stack rather than both, and takes the machine
as it finds it. GL, EGL and GLU belong to no session and are named outright;
the windowing stack is one dependency that a desktop of either kind already
satisfies:

.. code-block:: python

   Depends: libegl1, libgl1, libglu1-mesa, libwayland-client0 | libx11-6
   Recommends: libdecor-0-0, libdecor-0-plugin-1-gtk | libdecor-0-plugin-1-cairo

On any machine that can run the game, that alternative is met by what is
already installed and nothing is pulled in. Wayland is named first because
that is what ``apt`` reaches for on a machine that has neither — a container
being built to run the game headless, most often. One library stands for its
whole stack: the rest travels with it on any real desktop, and naming them all
would turn "either" back into "both".

This is what the package *asks the machine for*, not what it can do. The
bundle carries GLFW's builds for both — they are under 400 KB each — and picks
between them at run time from ``XDG_SESSION_TYPE``, because the session
belongs to whoever is playing rather than to whoever built the package.

``--session`` names a stack in full instead, for a fleet whose session is
known, and ``--session both`` asks for every library either stack could want —
which installs regardless of what is true of a machine, at the cost of pulling
one desktop's libraries onto the other. The three sets are
``SYSTEM_LIBRARIES``, ``WAYLAND_LIBRARIES`` and ``X11_LIBRARIES``.

An application adds to the list with ``--depends``. A library reached through
``dlopen`` whose absence is a degraded result rather than a failure belongs in
``--recommends`` instead: a sound backend, or the ``libdecor`` plug-in that
draws the titlebar, which a full-screen game never wants and should not drag
GTK in to be told so.

Options worth knowing
~~~~~~~~~~~~~~~~~~~~~

- ``--command NAME``, repeatable — which console scripts to put in
  ``/usr/games``. The distribution's own by default; a game that ships a tool
  belonging to another distribution names it here.

- ``--extras A,B`` — the project's optional dependencies to install with it.

- ``--backend NAME``, repeatable — a windowing backend the application uses, so
  that what it needs from the interpreter is kept. A Tk application must name
  ``tk``: Tk is part of CPython rather than a wheel in the environment, so it
  goes with everything else the pruning above leaves out, and a package that did
  not say so installs and then fails to start. Every other toolkit arrives as a
  wheel and is never pruned, so naming it changes nothing and is allowed anyway.
  ``OpenGLContext.packaging.appdir.BACKEND_RUNTIME`` is the table.

- ``--session either|wayland|x11|both`` — which windowing stack the package
  declares, as above. ``either`` by default, which takes the machine as it finds
  it.

- ``--requirement FILE``, repeatable — requirement files installed before the
  project, which is where a dependency that is not yet on an index is pinned.

- ``--menu-name``, ``--categories``, ``--icon`` — the desktop entry. Without an
  icon of its own the entry names a stock one, which every theme answers to.

- ``--revision N`` — the packaging of one upstream release, counting from 1.

- ``--prefix``, ``--bindir``, ``--section`` — for an application that is not a
  game.

A Python version becomes a Debian one on the way in: Debian sorts a letter
*after* nothing at all, so ``0.1.0a1`` would be newer than ``0.1.0`` and a
player on the pre-release would never be offered the release. Every
pre-release marker gets a tilde, which is the one character that sorts before
the empty string: ``0.1.0~a1-1``.

The package is written directly, as the ``ar`` archive of two tarballs that a
``.deb`` is, so a build host needs no ``dpkg``. Every file in it is owned by
root and carries one timestamp, so building the same input twice gives the
same package; ``SOURCE_DATE_EPOCH`` fixes that timestamp where a build has to
be reproducible across days.

.. _packaging-limits:

Limits
------

- **PyInstaller builds for the machine it runs on.** A Windows bundle is built
  on Windows.

- ``oglc-deb`` builds for the architecture of the interpreter it is given, which
  it reads from that interpreter rather than from the build machine. There is no
  cross-architecture build: the wheels installed into the environment are the
  build machine's.

- **No world, no map, no content.** What an application fetches or generates at
  run time is not something a package can carry, and the application's own
  documentation is where a player is told so.
