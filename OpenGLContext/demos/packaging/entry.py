#! /usr/bin/env python
"""What a frozen viewer-demo bundle runs

One executable, named after the command it runs and recognised by the name it
was run under -- see :mod:`OpenGLContext.packaging.multicall`.  A single command
does not need any of that, and it is used here because the table is where a
second one is added:

    'oglc-wx-viewer': 'OpenGLContext.demos.wx_viewer:main',

Most of a bundle's size is the interpreter and the libraries, and they are the
same whichever command runs, so an application that ships a tool beside it --
a baker, a downloader, the same viewer in another toolkit -- gets a second
executable for a line here rather than a second bundle.  Whatever is named has
to be importable on the machine doing the freezing, so the wx command is left
out of a bundle built where wxPython is not installed.
"""

import sys

from OpenGLContext.packaging.multicall import command_modules, run

#: Executable name -> the ``module:attribute`` it runs.  ``viewer-demos.spec``
#: builds one executable per key and hands ``command_modules(COMMANDS)`` to
#: PyInstaller, so this table is the only place a command is declared.
COMMANDS = {
    'oglc-tk-viewer': 'OpenGLContext.demos.tk_viewer:main',
}

#: The modules to tell a freezer about, since the table above names them as
#: strings.  Read from the ``.spec``.
MODULES = command_modules(COMMANDS)

if __name__ == '__main__':
    sys.exit(run(COMMANDS))
