"""Build a Python environment that runs from somewhere other than where it was made

An application shipped as a native package carries its own interpreter: a
relocatable CPython -- one that finds its standard library beside itself rather
than at a path compiled into it, such as the python-build-standalone builds
``uv python install`` fetches -- with a virtual environment on top holding the
application and everything it imports.

    <prefix>/python/     the interpreter and its standard library
    <prefix>/venv/       the application, its dependencies, its console scripts

The awkward part is that the environment is built somewhere other than where it
will run: a package is assembled in a staging directory by an ordinary user and
unpacked at ``/opt`` by the system. A virtual environment records where it was
made in three places -- ``pyvenv.cfg``, the ``#!`` line of every console script,
and the symlink that is its interpreter -- so :func:`build` writes those paths
as the ones it will be installed at, and the environment it leaves behind does
not run where it stands.

    >>> from OpenGLContext.packaging import appdir           # doctest: +SKIP
    >>> appdir.build(runtime='cpython-3.12.tar.gz',
    ...              staging='build/root/opt/glisteel',
    ...              installed='/opt/glisteel',
    ...              install=['.'])                          # doctest: +SKIP

Nothing here is Debian's: the same tree is what an AppImage, a tarball or a
container image would carry.
"""

from __future__ import annotations

import glob
import logging
import os
import shutil
import stat
import subprocess
import tarfile

log = logging.getLogger(__name__)

__all__ = ['PRUNE', 'build', 'interpreter_platform', 'metadata', 'prune',
           'relocate', 'runtime_directory']

#: What a built environment is made of, under the prefix it is installed at.
RUNTIME = 'python'
ENVIRONMENT = 'venv'

#: What an application has no use for in the interpreter it ships, as glob
#: patterns under the prefix. A relocatable CPython is a complete development
#: installation: the headers and the linker's static library for building
#: extensions against it, Tk and the two applications written in it, the tools
#: for installing more packages, and the manual. None of that can be reached
#: from a shipped application, which imports what it was built with and installs
#: nothing, and together it is some twenty megabytes.
#:
#: `pip` is pruned from the interpreter although the build used it: the
#: environment is populated before this runs, and an application that could
#: install into its own read-only directory is not something to ship.
PRUNE = (
    'python/include',
    'python/share/man',
    'python/lib/pkgconfig',
    'python/lib/itcl*',
    'python/lib/libtcl*',
    'python/lib/libtk*',
    'python/lib/tcl*',
    'python/lib/tdbc*',
    'python/lib/thread*',
    'python/lib/tk*',
    'python/lib/python*/ensurepip',
    'python/lib/python*/idlelib',
    'python/lib/python*/lib2to3',
    'python/lib/python*/pydoc_data',
    'python/lib/python*/test',
    'python/lib/python*/tkinter',
    'python/lib/python*/turtledemo',
    'python/bin/2to3*',
    'python/bin/idle*',
    'python/bin/pip*',
)


def runtime_directory(runtime, unpack_into):
    """The directory of a relocatable interpreter, unpacking an archive first

    runtime -- a directory holding ``bin/python3``, or a tar archive of one.
        The archives these builds are published as hold a single top-level
        directory, which may be named for the build rather than ``python``, so
        it is found by looking for the interpreter rather than by its name.
    unpack_into -- a working directory an archive is unpacked into

    Returns the directory to copy into a package.
    """
    if os.path.isdir(runtime):
        return _with_interpreter(runtime)
    log.info('unpacking the interpreter from %s', runtime)
    os.makedirs(unpack_into, exist_ok=True)
    with tarfile.open(runtime) as archive:
        try:
            archive.extractall(unpack_into, filter='data')
        except TypeError:  # pragma: no cover - Python 3.10 has no filter
            archive.extractall(unpack_into)
    return _with_interpreter(unpack_into)


def _with_interpreter(where):
    """*where*, or the first directory inside it that holds ``bin/python3``

    A directory an interpreter was installed *into* holds one, under a name
    given by the build; ``uv`` adds a second entry beside it, a symlink under a
    name without the patch version, and either answers.
    """
    if os.path.exists(os.path.join(where, 'bin', 'python3')):
        return where
    for name in sorted(os.listdir(where)):
        candidate = os.path.join(where, name)
        if os.path.exists(os.path.join(candidate, 'bin', 'python3')):
            return candidate
    raise ValueError('No bin/python3 under %s: is it a relocatable CPython?'
                     % (where,))


def interpreter_platform(python):
    """What ``sysconfig`` calls the platform an interpreter is built for

    Asked of the interpreter that will be shipped rather than of the machine
    building the package, so that a package cannot claim an architecture its
    contents are not for.
    """
    return _ask(python, 'import sysconfig; print(sysconfig.get_platform())')


def metadata(python, distribution):
    """What an installed distribution says about itself, as a dict

    Read from the environment that was built rather than from the source tree,
    so it describes what is actually in the package: the version that resolved,
    the summary that shipped, and the console scripts that were written.
    """
    import json

    script = (
        'import json, sys\n'
        'from importlib import metadata as m\n'
        'name = sys.argv[1]\n'
        'data = m.metadata(name)\n'
        'get = lambda key, default="": data.get(key) or default\n'
        'scripts = sorted(\n'
        '    entry.name for entry in m.distribution(name).entry_points\n'
        '    if entry.group == "console_scripts")\n'
        'urls = [value.split(",", 1) for value in data.get_all("Project-URL") or []]\n'
        'print(json.dumps({\n'
        '    "name": get("Name", name), "version": get("Version"),\n'
        '    "summary": get("Summary"),\n'
        '    "description": data.get_payload() or get("Description"),\n'
        '    "author": get("Author-email") or get("Maintainer-email")\n'
        '              or get("Author"),\n'
        '    "license": get("License-Expression") or get("License"),\n'
        '    "urls": {key.strip(): value.strip() for key, value in urls},\n'
        '    "home_page": get("Home-page"),\n'
        '    "scripts": scripts,\n'
        '}))\n'
    )
    return json.loads(_ask(python, script, distribution))


def _ask(python, script, *arguments):
    """Run a one-line script in another interpreter and return what it printed"""
    return subprocess.run(
        [python, '-c', script, *arguments],
        check=True, stdout=subprocess.PIPE, text=True,
    ).stdout.strip()


def build(runtime, staging, installed, install=(), requirements=(), work=None,
          unused='prune', quiet=False):
    """Assemble a relocatable environment under *staging* to run from *installed*

    runtime -- a relocatable CPython, as a directory or a tar archive
    staging -- where to build it: the prefix as it appears inside the package,
        such as ``build/root/opt/glisteel``
    installed -- the prefix it will run from, such as ``/opt/glisteel``
    install -- what to install, as pip requirements: the application, usually
        ``['.']`` or ``['.[audio]']``
    requirements -- requirement files to install first, which is where a stack
        that is not yet on an index is pinned
    work -- a directory to unpack an archived interpreter into; *staging*'s
        parent by default
    unused -- ``'prune'`` to leave out the parts of the interpreter an
        application cannot reach (:data:`PRUNE`), or ``'keep'`` for a complete
        installation
    quiet -- whether to let pip report what it resolved and installed

    Returns the path of the environment's interpreter, inside *staging*.
    """
    source = runtime_directory(
        runtime, work or os.path.join(os.path.dirname(staging), '_runtime'))
    python_home = os.path.join(staging, RUNTIME)
    environment = os.path.join(staging, ENVIRONMENT)

    log.info('copying the interpreter into %s', python_home)
    os.makedirs(staging, exist_ok=True)
    shutil.copytree(source, python_home, symlinks=True)
    base = os.path.join(python_home, 'bin', 'python3')

    # `--without-pip`, and installed with the interpreter's own pip pointed at
    # the environment: a shipped game never installs anything, and pip and
    # setuptools are some fifteen megabytes of a package that would only ever
    # be used to break it.
    log.info('creating the environment')
    subprocess.check_call([base, '-m', 'venv', '--without-pip', environment])
    python = os.path.join(environment, 'bin', 'python3')

    arguments = []
    for path in requirements:
        arguments += ['--requirement', path]
    arguments += list(install)
    if arguments:
        log.info('installing %s', ' '.join(arguments))
        subprocess.check_call(
            [base, '-m', 'pip', '--python', python, 'install',
             # Compiled here rather than by pip, so that the path recorded in
             # each `.pyc` is the one the file will be read from once installed.
             '--no-compile', '--no-input', '--disable-pip-version-check']
            + (['--quiet'] if quiet else [])
            + arguments
        )

    removed = prune(staging) if unused == 'prune' else []
    if removed:
        log.info('left out %d unused part%s of the interpreter',
                 len(removed), '' if len(removed) == 1 else 's')

    _compile(base, staging, installed)
    changed = relocate(staging, staging, installed)
    log.info('rewrote %d build-time path%s', len(changed), '' if len(changed) == 1 else 's')
    return python


def prune(prefix, patterns=PRUNE):
    """Remove what a shipped application has no use for, and report what went

    prefix -- a built environment's directory, holding ``python`` and ``venv``
    patterns -- glob patterns relative to it, :data:`PRUNE` by default

    A pattern that matches nothing is not an error: the list covers several
    interpreter builds, and which of them ships Tk or a manual is not something
    to have to know.
    """
    removed = []
    for pattern in patterns:
        for path in sorted(glob.glob(os.path.join(prefix, pattern))):
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
            removed.append(path)
    return removed


def _compile(python, staging, installed):
    """Byte-compile the environment, recording the paths it will be read from

    A package is installed read-only under ``/opt``, so an environment that
    arrives uncompiled is compiled again on every run and never gets to keep
    the result. ``-d`` is what makes the source path in a traceback the
    installed one rather than the staging directory it was compiled in, and
    hash-based ``.pyc`` files stay valid however the package's timestamps land.
    """
    log.info('byte-compiling')
    subprocess.check_call([
        python, '-m', 'compileall', '-q', '-q', '-f',
        '--invalidation-mode', 'unchecked-hash',
        '-d', installed, staging,
    ], stdout=subprocess.DEVNULL)



def relocate(root, source, target):
    """Rewrite the build-time paths in a tree to the ones it will run at

    A virtual environment records where it was made: in ``pyvenv.cfg``, in the
    ``#!`` line of every console script, and in the symlink that is its
    interpreter. Built inside a staging directory, all three point into a
    directory that will not exist on the machine the package is installed on.

    root -- the tree to walk, at or below *source*
    source -- the path the tree was built at, which is the staging directory
    target -- the path it will be installed at. For a staging directory that
        *is* the root of the package, this is the empty string.

    Symlinks that pointed inside *source* are made relative instead of
    rewritten, so the environment survives being moved again -- copied
    somewhere else, or run from a container mount. Files with a NUL byte in
    their first block are left alone: a path inside a shared library is part of
    a structure that a substitution of a different length would break.

    Returns the paths that were changed.
    """
    changed = []
    prefix = source if source.endswith(os.sep) else source + os.sep
    for directory, dirnames, filenames in os.walk(root):
        for name in sorted(dirnames) + sorted(filenames):
            path = os.path.join(directory, name)
            if os.path.islink(path):
                if _relocate_link(path, source, prefix, target):
                    changed.append(path)
            elif name in filenames and os.path.isfile(path):
                if _relocate_text(path, source, target):
                    changed.append(path)
    return changed


def _relocate_link(path, source, prefix, target):
    """Make an absolute symlink into the staging directory a relative one"""
    points_at = os.readlink(path)
    if not os.path.isabs(points_at) or not points_at.startswith(prefix):
        return False
    installed = target + points_at[len(source):]
    here = target + os.path.dirname(path)[len(source):]
    os.unlink(path)
    os.symlink(os.path.relpath(installed, here), path)
    return True


def _relocate_text(path, source, target):
    """Replace the staging path in a text file with the installed one"""
    with open(path, 'rb') as stream:
        head = stream.read(8192)
        if b'\x00' in head:
            return False
        data = head + stream.read()
    wanted = source.encode('utf-8')
    if wanted not in data:
        return False
    mode = stat.S_IMODE(os.lstat(path).st_mode)
    with open(path, 'wb') as stream:
        stream.write(data.replace(wanted, target.encode('utf-8')))
    os.chmod(path, mode)
    return True
