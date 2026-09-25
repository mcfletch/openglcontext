Packaging an application
========================

.. rst-class:: introduction

``OpenGLContext.packaging`` helps deliver an application built on the engine
to people who do not have Python installed. It supports two forms:

- a **frozen bundle** made with PyInstaller: one directory holding an
  interpreter, the engine and the application, started through an
  executable;
- a **Debian package** that installs such a tree under ``/opt``.

The engine supplies the information a packager cannot find on its own: which
engine modules are loaded by name rather than imported, which windowing
toolkits the application does not use, and which system libraries it needs.

For packaging a viewer embedded in a Tk or Qt application, see
:ref:`Shipping an embedded viewer <shipping>`.

.. _freezing:

Freezing with PyInstaller
-------------------------

PyInstaller follows ``import`` statements. The engine loads much of itself by
name instead. Every windowing backend, file-format loader, viewer adapter and
scenegraph node is registered in ``OpenGLContext.plugins`` as a string and
imported when a scene needs it. The same is true of the generated resource
modules that ``res://`` URLs name and of the font atlases text rendering
needs. PyOpenGL chooses its platform module and array format handlers the
same way (``OpenGL.plugins``), and opens GLSL sources, environment maps and
the GLFW library by file path.

An application does not have to list any of these. PyOpenGL and
OpenGLContext both ship PyInstaller hooks, in ``OpenGL/__pyinstaller/`` and
``OpenGLContext/__pyinstaller/``. PyInstaller finds them through the
``pyinstaller40`` entry point, with no configuration. The hooks read the
installed engine's registries, so a node or shader added to the engine is
included in a frozen application automatically.

The application's ``.spec`` file then names the application's own data and
the modules to leave out:

.. code-block:: python

   from PyInstaller.utils.hooks import collect_data_files
   from OpenGLContext import packaging

   analysis = Analysis(
       ['packaging/entry.py'],
       datas=collect_data_files('mygame'),
       excludes=packaging.unused_backend_modules(keep=['glfw']),
   )

``unused_backend_modules()`` makes the largest difference to bundle size.
The engine imports the Qt backend to register it, and names the other
backends in its registries, so a bundle picks up every toolkit installed in
the environment. For an application that opens its window with GLFW, that
can mean a quarter of a gigabyte of Qt. Pass the backends the application
uses as ``keep``, and the rest are excluded. The engine's own
``<name>context`` modules stay: they are a few kilobytes each and report
their backend as unavailable.

``keep`` takes the same names as ``OPENGLCONTEXT_BACKEND``: ``glfw``,
``glut``, ``pygame``, ``qt``, ``tk`` and ``wx``, plus ``egl`` on Linux or
``wgl`` on Windows for a bundle that renders :doc:`offscreen <offscreen>`.
The excluded modules include ``tkinter``, although it is in the standard
library, because following its import brings in all of Tcl/Tk, several
megabytes, for a bundle that opens no Tk window.

One bundle, several commands
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Most of a bundle's size is the interpreter and the libraries, which every
command shares. An application that ships extra tools, such as a world baker
or a downloader, should build them into the same bundle instead of freezing
each one separately. ``OpenGLContext.packaging.multicall`` gives one bundle
several executables. Each executable is named after its command, and the
entry script runs the command matching the name it was started under:

.. code-block:: python

   import sys

   from OpenGLContext.packaging.multicall import command_modules, run

   COMMANDS = {
       'mygame': 'mygame.game:main',
       'glisteel-bake': 'glisteel_editor.bake:main',
   }
   MODULES = command_modules(COMMANDS)   # for the spec's hiddenimports

   if __name__ == '__main__':
       sys.exit(run(COMMANDS))

The ``.spec`` builds one ``EXE`` per key from a single analysis, and
``COLLECT`` places them all beside one ``_internal`` directory. Each command
sees the same ``sys.argv`` it would get as a separately installed console
script, and only the command that was run is imported.

.. _deb:

A Debian package
----------------

``oglc-deb`` builds a ``.deb`` that contains the application and the Python
interpreter that runs it. Nothing outside the package is needed: no system
Python, no virtual environment for the player to create, and no pip at
install time.

.. code-block:: bash

   uv python install --install-dir runtime 3.12
   oglc-deb --project . --runtime runtime --output dist

The package installs under ``/opt/<package>``, links the application's
console scripts into ``/usr/games``, and adds a desktop menu entry:

.. code-block:: text

   /opt/mygame/python/    the interpreter and its standard library
   /opt/mygame/venv/      the application and everything it imports
   /usr/games/mygame      a link to the console script
   /usr/share/applications/mygame.desktop

The interpreter must be a **relocatable** build: one that finds its standard
library relative to itself, not at a path compiled into it. The
python-build-standalone distributions that ``uv python install`` downloads
are relocatable. ``--runtime`` takes the interpreter's directory or a tar
archive of it.

``oglc-deb`` assembles the environment in a staging directory as an ordinary
user, and writes the installed paths into the three places a virtual
environment records its location: ``pyvenv.cfg``, the ``#!`` line of every
console script, and the interpreter symlink
(``OpenGLContext.packaging.appdir``). The environment then runs from
``/opt``.

The package is byte-compiled with the installed paths. ``/opt`` is read-only
to the player, so an uncompiled environment would recompile on every run and
never save the result. Parts of the interpreter an application cannot use
(the C headers, Tk, IDLE, pip and the manual, about twenty megabytes) are
left out. ``--keep-unused`` includes them.

System library dependencies
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The package declares the graphics libraries as dependencies instead of
bundling them. The GL library belongs to the machine's driver, and a bundled
copy would be the wrong one. ``dpkg-shlibdeps`` cannot find these
dependencies either: GLFW loads every one of them with ``dlopen``, so none
appears in an ELF header. The package names are declared in
``OpenGLContext.packaging``.

Only libraries that a graphical session does not already provide need
declaring. A machine running X11 has ``libX11``, and one running Wayland has
``libwayland-client``. Neither is certain to have GLU, which only OpenGL
software uses, or ``libdecor``, without which a Wayland window has no title
bar and cannot be moved or closed.

By default a package accepts **either** windowing stack. GL, EGL and GLU are
named directly. The windowing stack is a single dependency with two
alternatives, which any X11 or Wayland desktop already satisfies:

.. code-block:: text

   Depends: libegl1, libgl1, libglu1-mesa, libwayland-client0 | libx11-6
   Recommends: libdecor-0-0, libdecor-0-plugin-1-gtk | libdecor-0-plugin-1-cairo

On any machine that can run the game, the installed libraries meet that
dependency and nothing extra is installed. Wayland is listed first because
``apt`` installs the first alternative on a machine that has neither, most
often a container built to run the game headless. One library stands for
each stack; on a real desktop the rest of the stack is installed with it.
Naming every library would require both stacks.

These dependencies describe what the package requires, not what it
supports. The bundle carries GLFW builds for both stacks (under 400 KB each)
and picks one at run time from ``XDG_SESSION_TYPE``.

``--session wayland`` or ``--session x11`` declares every library of one
stack, for machines whose session is known. ``--session both`` declares
every library of both stacks. That installs on any machine, but pulls one
desktop's libraries onto the other. The three library sets are
``SYSTEM_LIBRARIES``, ``WAYLAND_LIBRARIES`` and ``X11_LIBRARIES``.

Add dependencies with ``--depends``. Use ``--recommends`` for a library
loaded with ``dlopen`` whose absence degrades the application rather than
stopping it, such as a sound backend or the ``libdecor`` plug-in that draws
the title bar. A full-screen game does not need a title bar, and a
recommendation does not force GTK onto the machine.

Options
~~~~~~~

- ``--command NAME`` (repeatable) - console scripts to link into
  ``/usr/games``. The default is the distribution's own scripts. Name a tool
  from another distribution here to include it.

- ``--extras A,B`` - the project's optional dependencies to install.

- ``--backend NAME`` (repeatable) - a windowing backend the application
  uses, so that the interpreter parts it needs are kept. A Tk application
  must pass ``tk``. Tk is part of CPython rather than a wheel in the
  environment, so without this option it is removed with the other unused
  interpreter parts, and the installed package fails to start. Other
  toolkits install as wheels and are never removed; naming them is allowed
  and has no effect. The table is
  ``OpenGLContext.packaging.appdir.BACKEND_RUNTIME``.

- ``--session either|wayland|x11|both`` - the windowing libraries the
  package declares, as described above. The default is ``either``.

- ``--requirement FILE`` (repeatable) - requirement files installed before
  the project. Use one to pin a dependency that is not on a package index.

- ``--menu-name``, ``--categories``, ``--icon`` - the desktop entry. Without
  ``--icon``, the entry names a stock icon that every icon theme provides.

- ``--revision N`` - the Debian revision for one upstream release, starting
  at 1.

- ``--prefix``, ``--bindir``, ``--section`` - for an application that is not
  a game.

Version numbers and reproducible builds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``oglc-deb`` converts the Python version to a Debian version. Debian sorts a
letter *after* the end of a string, so ``0.1.0a1`` would sort as newer than
``0.1.0``, and a player on the pre-release would never be offered the
release. Each pre-release marker gets a tilde, which sorts before the end of
a string: ``0.1.0a1`` becomes ``0.1.0~a1-1``.

``oglc-deb`` writes the package directly, as the ``ar`` archive of two
tarballs that a ``.deb`` is, so the build host does not need ``dpkg``. Every
file in it is owned by root and has the same timestamp, so building the same
input twice gives the same package. Set ``SOURCE_DATE_EPOCH`` to fix that
timestamp for builds that must be reproducible across days.

.. _packaging-limits:

Limits
------

- PyInstaller builds for the platform it runs on. Build a Windows bundle on
  Windows.

- ``oglc-deb`` builds for the architecture of the interpreter it is given,
  which it reads from that interpreter, not from the build machine. It does
  not cross-build: the wheels installed into the environment are for the
  build machine.

- A package carries no content the application downloads or generates at run
  time, such as worlds or maps. Tell players about that in the application's
  own documentation. See :doc:`Content packs <contentpacks>` for data an
  application fetches.
