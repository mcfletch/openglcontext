"""One frozen bundle, several commands

A bundle carries a Python runtime, the engine and every library beneath it,
which is most of its size and is the same whichever command runs. A game that
ships a tool beside it -- a baker, a downloader -- would double that by
freezing each command separately, so instead one bundle holds one copy of
everything and is entered through several small executables, each named after
the command it runs. Which one was run is read from the path it was run under,
the way ``busybox`` does it.

An application declares the commands in the script it freezes::

    from OpenGLContext.packaging.multicall import run

    COMMANDS = {
        'glisteel': 'glisteel.game:main',
        'oglc-bake': 'OpenGLContext_editor.bin.bake:main',
    }

    sys.exit(run(COMMANDS))

and the ``.spec`` builds one executable per key -- all sharing the one
directory of libraries -- and passes :func:`command_modules` to PyInstaller's
``hiddenimports``, since a command named as a string is one a freezer cannot
see. That is the point of naming rather than importing them: the table is the
one place a command is declared, and a bundle imports only the command it was
actually asked for, so the small tool beside a game starts as quickly as it
would on its own.

A command may equally be the function itself, for an application with nothing
to gain from either. Each command sees ``sys.argv`` exactly as it would have if
it had been installed as its own console script.
"""

import importlib
import os
import sys

__all__ = ['command_modules', 'command_name', 'load', 'run']


def command_name(path):
    """The command a bundle run as *path* is being asked for

    The directory and any executable suffix are not part of the name, so
    ``C:\\Games\\Glinting Steel\\glisteel.exe`` and ``/usr/games/glisteel`` both
    ask for ``glisteel``.

    Both separators are read on every platform rather than the running one's:
    a command is named for a shell to type, so it holds neither, and reading
    both means the choice can be checked on a machine that is not the one the
    bundle will run on.
    """
    leaf = path.replace('\\', '/').rpartition('/')[2]
    return os.path.splitext(leaf)[0]


def run(commands, argv=None):
    """Run the command *argv* names, and report the status to exit with

    commands -- the commands this bundle offers, as ``{name: function}``, where
        each function takes no arguments and reads ``sys.argv`` itself
    argv -- the arguments to read the name from, ``sys.argv`` by default. It is
        passed through to the command untouched: a command parses its own
        arguments, and its own name is the first of them.

    A command returning ``None`` -- what a ``main()`` usually returns when it
    has nothing to complain about -- succeeded. A name that is not one of
    *commands* is reported on stderr, with the names that are, and gives the
    exit status a shell reads as a usage error.
    """
    if not commands:
        raise ValueError('A bundle offering no commands can do nothing')
    if argv is None:
        argv = sys.argv
    name = command_name(argv[0])
    command = commands.get(name)
    if command is None:
        sys.stderr.write(
            'This bundle has no command called %r. It offers: %s\n'
            % (name, ', '.join(sorted(commands)))
        )
        return 2
    command = load(command)
    original, sys.argv = sys.argv, list(argv)
    try:
        return command() or 0
    finally:
        sys.argv = original


def load(command):
    """The function *command* stands for

    A command is either the function itself or a ``'module:attribute'`` name of
    one, which is imported here -- when the command is run, rather than when the
    table is declared.
    """
    if callable(command):
        return command
    module, separator, attribute = command.partition(':')
    if not separator or not attribute:
        raise ValueError(
            'A named command is written module:attribute, which %r is not' % (command,)
        )
    return getattr(importlib.import_module(module), attribute)


def command_modules(commands):
    """The modules the named commands live in, as a sorted list

    A freezer follows import statements and so cannot see a command named as a
    string; this is what to tell it about. Commands given as functions are
    already reached by the import that produced them and are not reported.
    """
    modules = set()
    for command in commands.values():
        if not callable(command):
            module = command.partition(':')[0]
            if module:
                modules.add(module)
    return sorted(modules)

