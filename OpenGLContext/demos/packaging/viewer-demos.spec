# -*- mode: python ; coding: utf-8 -*-
"""Freeze the Tk viewer demo into one directory that needs no Python installed

    pyinstaller OpenGLContext/demos/packaging/viewer-demos.spec

The result is ``dist/viewer-demos/``: the executables named in ``entry.py``
beside an ``_internal`` directory holding Python, the engine and the libraries
under them.  Zip that directory and it runs on a machine with a graphics driver
and nothing else.

Almost nothing about the engine is described here.  PyOpenGL and OpenGLContext
carry their own PyInstaller hooks -- for the plug-in registries, the generated
resource modules, the shader sources and the GLFW library -- which PyInstaller
finds through their ``pyinstaller40`` entry points.  What is left for an
application to say is which commands it offers, which of its own files it opens
at run time, and which backends it does not use.

This is the whole of the difference for an *embedded* viewer, and it is one
word: ``keep=['tk']``.  A view in a Tk window needs Tcl/Tk and needs none of
Qt, wx, pygame or GLFW; a Qt one says ``keep=['qt']`` and gets the opposite.
See ``docs/packaging.html``.
"""

import os
import runpy

from OpenGLContext import packaging

ENTRY = os.path.join(SPECPATH, 'entry.py')  # noqa: F821 -- PyInstaller defines SPECPATH

# The entry script is read rather than imported: it declares the commands, and
# `runpy` leaves its `__main__` guard alone, so the table is not copied here to
# fall out of step with the one the bundle actually dispatches on.
DECLARED = runpy.run_path(ENTRY)

analysis = Analysis(  # noqa: F821
    [ENTRY],
    hiddenimports=DECLARED['MODULES'],
    # The demo opens its window with Tk. The engine registers every backend it
    # knows and imports the Qt one for its registration side effect, so without
    # this a bundle carries the whole of Qt -- a quarter of a gigabyte against
    # an application that never calls it. The engine's own backend modules stay:
    # they are kilobytes, and they report themselves unavailable.
    excludes=packaging.unused_backend_modules(keep=['tk']) + [
        # Development tooling that some library or other imports conditionally.
        'IPython',
        'matplotlib',
        'pytest',
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)  # noqa: F821

# One executable per command, all sharing the single `_internal` directory that
# COLLECT assembles. Console applications: the demos take a scene to open on the
# command line and report what they could not open, and a windowed build on
# Windows would drop those messages on the floor.
executables = [
    EXE(  # noqa: F821
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name=name,
        console=True,
        debug=False,
        strip=False,
        # UPX shrinks a bundle by a third and has a long history of producing
        # one that a virus scanner quarantines or that will not start at all.
        upx=False,
    )
    for name in sorted(DECLARED['COMMANDS'])
]

COLLECT(  # noqa: F821
    *executables,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    name='viewer-demos',
)
