"""Build a Debian package holding an application and the Python that runs it

``oglc-deb`` takes an application that pip can install and a relocatable CPython
to run it with, and writes a ``.deb`` that installs both under ``/opt`` with a
command in ``/usr/games`` and an entry in the desktop menu. Nothing outside the
package is needed to run it: no system Python, no virtual environment for the
player to make, no pip at install time. The only things asked of the machine are
the OpenGL and X11 client libraries, which belong to it and are named as
dependencies (:data:`OpenGLContext.packaging.SYSTEM_LIBRARIES`).

    oglc-deb --project . --runtime cpython-3.12-x86_64-linux-gnu.tar.gz

The runtime is a *relocatable* build -- one that finds its own standard library
beside itself rather than at a path compiled into it, such as the
python-build-standalone distributions ``uv python install`` fetches. That is
what lets the environment be built in one directory and run from another, which
is the whole of what makes an ordinary virtual environment fit to be packaged:
the paths recorded while it is built are rewritten to the ones it will be
installed at
(:func:`OpenGLContext.packaging.appdir.relocate`).

The package is written directly, as the ``ar`` archive of two tarballs that a
``.deb`` is, so a build host needs no ``dpkg``. Where ``dpkg`` is installed the
test suite reads the result back with it.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import lzma
import os
import re
import shutil
import tarfile
import time

__all__ = [
    'control_paragraph', 'debian_architecture', 'debian_name', 'debian_version',
    'describe', 'desktop_entry', 'have_dpkg', 'installed_size', 'maintainer_field',
    'md5sums', 'read_deb', 'summarise', 'write_deb',
]

#: The Debian name for the machine each interpreter platform runs on. Read from
#: the interpreter that will be packaged rather than from the machine building
#: it, so that a package cannot claim an architecture its contents are not for.
ARCHITECTURES = {
    'aarch64': 'arm64',
    'amd64': 'amd64',
    'arm64': 'arm64',
    'armv7l': 'armhf',
    'i386': 'i386',
    'i686': 'i386',
    'ppc64le': 'ppc64el',
    's390x': 's390x',
    'x86_64': 'amd64',
}

#: The order ``dpkg`` writes control fields in. Anything not named here follows
#: the ones that are, and ``Description`` is last because it is the only field
#: that continues onto further lines.
FIELD_ORDER = (
    'Package', 'Source', 'Version', 'Architecture', 'Maintainer',
    'Installed-Size', 'Depends', 'Pre-Depends', 'Recommends', 'Suggests',
    'Conflicts', 'Breaks', 'Replaces', 'Provides', 'Section', 'Priority',
    'Homepage', 'Description',
)

#: Fields ``dpkg`` refuses a package without.
REQUIRED_FIELDS = ('Package', 'Version', 'Architecture', 'Maintainer', 'Description')

#: Files in the control archive that are programs rather than text.
MAINTAINER_SCRIPTS = ('preinst', 'postinst', 'prerm', 'postrm', 'config')

_PUBLIC_VERSION = re.compile(
    r'^\d+(\.\d+)*((a|b|c|rc|alpha|beta)\d*)?(\.post\d+)?(\.dev\d*)?$')
_LOCAL_VERSION = re.compile(r'^[A-Za-z0-9.]+$')
_PRE_RELEASE = re.compile(r'(?<=\d)(alpha|beta|rc|a|b|c)(?=\d|$)')


def have_dpkg():
    """Whether this machine has the Debian tools to read a package back"""
    return bool(shutil.which('dpkg') and shutil.which('dpkg-deb'))


def debian_version(version, revision=1):
    """The Debian version for a Python release *version*

    Debian compares versions its own way, and in that ordering a letter sorts
    *after* nothing at all -- so ``0.1.0a1`` would be newer than ``0.1.0``, and
    a player on the pre-release would never be offered the release. ``~`` is the
    one character that sorts before the empty string, so every pre-release
    marker gets one::

        0.1.0a1  ->  0.1.0~a1-1
        1.0.dev5 ->  1.0~dev5-1

    ``.post`` releases are left as they are: they come after the release they
    follow in both orderings.

    revision -- the packaging of that upstream release, counting from 1. It
        changes when the package is rebuilt without the application changing.

    Raises ``ValueError`` for a version this cannot express, rather than writing
    a package whose upgrade order would be wrong.
    """
    public, _, local = str(version).strip().partition('+')
    if not _PUBLIC_VERSION.match(public):
        raise ValueError('%r is not a version this can turn into a Debian one'
                         % (version,))
    if local and not _LOCAL_VERSION.match(local):
        raise ValueError('%r has a local version Debian could not hold'
                         % (version,))
    upstream = _PRE_RELEASE.sub(r'~\1', public).replace('.dev', '~dev')
    if local:
        upstream = '%s+%s' % (upstream, local)
    return '%s-%s' % (upstream, revision)


def debian_architecture(platform_tag):
    """The Debian architecture for an interpreter's ``sysconfig`` platform

    platform_tag -- what ``sysconfig.get_platform()`` reports, such as
        ``linux-x86_64``

    Raises ``ValueError`` where there is no name for it, since a package that
    said ``all`` about a directory full of compiled extensions would install
    happily onto a machine that cannot run it.
    """
    machine = platform_tag.rpartition('-')[2] or platform_tag
    try:
        return ARCHITECTURES[machine]
    except KeyError:
        raise ValueError(
            'No Debian architecture is known for %r; the ones that are: %s'
            % (machine, ', '.join(sorted(ARCHITECTURES)))
        ) from None


def describe(summary, body=''):
    """A ``Description`` field: a one-line summary, then an indented body

    Every line after the first is indented by a space, and a blank line in the
    body is written as a lone full stop -- in a control file an unindented line
    would end the field and start another.
    """
    lines = [summary.strip()]
    for line in body.strip().splitlines():
        lines.append(' ' + line.rstrip() if line.strip() else ' .')
    return '\n'.join(lines)


#: How many lines of a project's long description a control file carries. A
#: package manager shows this where a user is choosing what to install, so it is
#: a paragraph rather than a manual.
DESCRIPTION_LINES = 12


def summarise(description, lines=DESCRIPTION_LINES):
    """The opening prose of a long description, for a control file

    A project's long description is its README: a title, some paragraphs, then
    code blocks, tables and sections that mean nothing where a package manager
    shows them. What is wanted is the paragraph or two at the top that say what
    the thing is, so the title is dropped -- the package is already named -- and
    the text is taken up to the first heading, fence or table, and to at most
    *lines* lines.
    """
    kept = []
    for line in description.strip().splitlines():
        stripped = line.strip()
        if not kept and (not stripped or stripped.startswith('#')):
            continue  # the title, and the blank line after it
        if stripped.startswith(('#', '```', '~~~', '|', '---', '===')):
            break
        if len(kept) >= lines:
            break
        kept.append(line.rstrip())
    while kept and not kept[-1]:
        kept.pop()
    return '\n'.join(kept)


def maintainer_field(author):
    """A ``Maintainer`` field from a project's author

    Python metadata carries an author through an email header, which quotes a
    name holding a full stop -- and ``"Mike C. Fletcher" <...>`` is not how a
    Debian package names its maintainer.
    """
    import email.utils

    name, address = email.utils.parseaddr(str(author).strip())
    if not (name or address):
        raise ValueError('A package needs a maintainer, and %r is not one'
                         % (author,))
    return '%s <%s>' % (name, address) if name and address else (address or name)


def control_paragraph(fields):
    """Render the control file of a binary package

    fields -- the control fields, of which :data:`REQUIRED_FIELDS` have to be
        there and have a value. Anything empty is left out, so a caller can pass
        ``Homepage`` unconditionally and get a file without one.
    """
    given = {name: value for name, value in fields.items() if str(value).strip()}
    missing = [name for name in REQUIRED_FIELDS if name not in given]
    if missing:
        raise ValueError('A package needs %s' % (', '.join(missing),))
    ordered = [name for name in FIELD_ORDER if name in given]
    ordered += sorted(name for name in given if name not in FIELD_ORDER)
    ordered.append(ordered.pop(ordered.index('Description')))
    return ''.join('%s: %s\n' % (name, given[name]) for name in ordered)


def _files(root):
    """Every regular file and symlink in *root*, as sorted relative paths"""
    found = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            found.append(os.path.relpath(os.path.join(directory, name), root))
    return sorted(found)


def md5sums(root):
    """The ``md5sums`` control file for a tree of installed files

    Symlinks are not listed: what a link points at is summed under its own name,
    and ``dpkg`` checks the contents of files.
    """
    lines = []
    for relative in _files(root):
        path = os.path.join(root, relative)
        if os.path.islink(path):
            continue
        digest = hashlib.md5()
        with open(path, 'rb') as stream:
            for block in iter(lambda: stream.read(1 << 20), b''):
                digest.update(block)
        lines.append('%s  %s\n' % (digest.hexdigest(), relative))
    return ''.join(lines)


def installed_size(root):
    """How much space the package takes once unpacked, in kibibytes

    The number goes in the control file, where a package manager uses it to
    tell a user what an install will cost before it starts.
    """
    total = 0
    for relative in _files(root):
        path = os.path.join(root, relative)
        if not os.path.islink(path):
            total += os.path.getsize(path)
    return max(1, total // 1024)


def _timestamp():
    """The one modification time every entry in the package is given

    ``SOURCE_DATE_EPOCH`` where the caller set it, so that building the same
    input twice gives the same bytes; the moment of the build otherwise.
    """
    given = os.environ.get('SOURCE_DATE_EPOCH', '').strip()
    return int(given) if given.isdigit() else int(time.time())


def _tarball(add, when, compression):
    """A tar archive built by *add*, owned by root, compressed as asked

    add -- called with the open ``tarfile`` to put the entries in
    when -- the modification time to give every entry
    compression -- ``'gz'`` or ``'xz'``
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.GNU_FORMAT) as tar:
        add(_Deterministic(tar, when))
    packed = raw.getvalue()
    if compression == 'gz':
        # mtime=0 rather than now: a gzip header carries a time of its own, and
        # it is the one thing that would differ between two identical builds.
        buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=buffer, mode='wb', mtime=0) as stream:
            stream.write(packed)
        return buffer.getvalue()
    return lzma.compress(packed, format=lzma.FORMAT_XZ, preset=6)


class _Deterministic:
    """A ``tarfile`` that gives every entry root ownership and one timestamp

    Two builds of the same tree should give the same package, and the files in
    a package belong to the system rather than to whoever built it.
    """

    def __init__(self, tar, when):
        self.tar = tar
        self.when = when

    def _stamped(self, info):
        info.uid = info.gid = 0
        info.uname = info.gname = 'root'
        info.mtime = self.when
        return info

    def file(self, name, data, mode=0o644):
        """Add a file with the given bytes"""
        info = tarfile.TarInfo(name)
        info.size = len(data)
        info.mode = mode
        self.tar.addfile(self._stamped(info), io.BytesIO(data))

    def path(self, path, name):
        """Add a file, directory or symlink from the filesystem"""
        info = self.tar.gettarinfo(path, arcname=name)
        if info.isfile():
            with open(path, 'rb') as stream:
                self.tar.addfile(self._stamped(info), stream)
        else:
            self.tar.addfile(self._stamped(info))


def _add_tree(root):
    """Return a function that adds every entry of *root* to a tar archive"""

    def add(tar):
        for directory, dirnames, filenames in os.walk(root):
            dirnames.sort()
            relative = os.path.relpath(directory, root)
            if relative != '.':
                tar.path(directory, './' + relative.replace(os.sep, '/'))
            for name in sorted(filenames):
                path = os.path.join(directory, name)
                inside = os.path.relpath(path, root).replace(os.sep, '/')
                tar.path(path, './' + inside)

    return add


def _ar_member(name, data, when):
    """One member of an ``ar`` archive: a 60-byte header and padded contents"""
    header = '%-16s%-12d%-6d%-6d%-8o%-10d`\n' % (name, when, 0, 0, 0o100644, len(data))
    padding = b'\n' if len(data) % 2 else b''
    return header.encode('ascii') + data + padding


def write_deb(data_root, control_files, path):
    """Write a binary package

    data_root -- the tree to install, laid out as it will appear on the target
        machine: ``usr/games/...``, ``opt/...``
    control_files -- the control archive, as ``{name: text}``. ``control`` is
        the one that has to be there; ``md5sums`` and the maintainer scripts go
        here too, and a script is made executable by being named as one.
    path -- where to write the package

    A ``.deb`` is an ``ar`` archive of exactly three members in exactly this
    order, which is why it is written here rather than by shelling out: there is
    nothing in it that needs a Debian machine to produce.
    """
    when = _timestamp()

    def add_control(tar):
        for name in sorted(control_files):
            text = control_files[name]
            mode = 0o755 if name in MAINTAINER_SCRIPTS else 0o644
            tar.file('./' + name, text.encode('utf-8'), mode=mode)

    members = [
        ('debian-binary', b'2.0\n'),
        ('control.tar.gz', _tarball(add_control, when, 'gz')),
        ('data.tar.xz', _tarball(_add_tree(data_root), when, 'xz')),
    ]
    with open(path, 'wb') as stream:
        stream.write(b'!<arch>\n')
        for name, data in members:
            stream.write(_ar_member(name, data, when))
    return path


def read_deb(path):
    """Read back the members of a package, as ``(name, bytes)`` pairs

    Enough of the ``ar`` format to check what was written, without asking the
    machine to have ``dpkg`` on it.
    """
    with open(path, 'rb') as stream:
        if stream.read(8) != b'!<arch>\n':
            raise ValueError('%s is not an ar archive' % (path,))
        while True:
            header = stream.read(60)
            if len(header) < 60:
                return
            name = header[:16].decode('ascii').strip().rstrip('/')
            size = int(header[48:58].decode('ascii').strip())
            yield name, stream.read(size)
            if size % 2:
                stream.read(1)


_NAME = re.compile(r'^[a-z0-9][a-z0-9+.-]+$')


def debian_name(name):
    """The Debian package name for a Python distribution name

    Debian names are lower case and hold no underscore, so ``twig_bb`` and
    ``OpenGLContext-editor`` become ``twig-bb`` and ``openglcontext-editor``.
    Anything that would still not be a legal name -- one character, a leading
    dash -- is refused rather than mangled further.
    """
    candidate = str(name).strip().lower().replace('_', '-')
    if not _NAME.match(candidate):
        raise ValueError('%r is not a name a Debian package can have' % (name,))
    return candidate


def desktop_entry(name, command, summary, categories='Game;', icon=None):
    """A ``.desktop`` file putting the application in the menu

    icon -- the icon's name in the theme, which for a package that ships one is
        the package name. Without one, a stock name from the icon-naming
        specification is used: it is in every theme, where a name that no
        installed icon answers to would draw as a broken image.
    """
    return (
        '[Desktop Entry]\n'
        'Type=Application\n'
        'Name=%s\n'
        'Comment=%s\n'
        'Exec=%s\n'
        'Icon=%s\n'
        'Terminal=false\n'
        'Categories=%s\n'
    ) % (name, summary, command, icon or 'applications-games', categories)


# ---------------------------------------------------------------------------
# Building one
# ---------------------------------------------------------------------------

#: Where the environment is installed, under a directory named for the package.
DEFAULT_PREFIX = '/opt'

#: Where the commands are linked, which for a game is Debian's own place for one.
DEFAULT_BINDIR = '/usr/games'

#: The section and menu categories of a game. An application that is not one
#: passes ``--section`` and ``--categories``.
DEFAULT_SECTION = 'games'
DEFAULT_CATEGORIES = 'Game;'


def _project_name(project):
    """The distribution name declared in a project directory's ``pyproject.toml``"""
    path = os.path.join(project, 'pyproject.toml')
    if not os.path.isfile(path):
        raise ValueError(
            'No pyproject.toml in %s to read the distribution name from; '
            'name it with --distribution' % (project,))
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10 has no tomllib
        raise ValueError(
            'Reading %s needs Python 3.11 or later; name the distribution with '
            '--distribution instead' % (path,)) from None
    with open(path, 'rb') as stream:
        declared = tomllib.load(stream).get('project', {}).get('name')
    if not declared:
        raise ValueError('%s declares no project name; use --distribution' % (path,))
    return declared


def _copyright_file(environment, distribution, license_expression):
    """The ``copyright`` file, with whatever licence text the wheel carried

    A wheel built to PEP 639 puts its licence files in its ``.dist-info``, so
    the text that travels in the package is the project's own rather than a
    copy made here that could come to disagree with it.
    """
    lines = ['Upstream-Name: %s' % (distribution,)]
    if license_expression:
        lines.append('License: %s' % (license_expression,))
    lines.append('')
    for path in sorted(_license_files(environment, distribution)):
        with open(path, encoding='utf-8', errors='replace') as stream:
            lines.extend([os.path.basename(path), '', stream.read().rstrip(), ''])
    return '\n'.join(lines) + '\n'


def _license_files(environment, distribution):
    """The licence files the distribution's ``.dist-info`` carries"""
    wanted = distribution.replace('-', '_').lower()
    for libraries in _site_packages(environment):
        for name in sorted(os.listdir(libraries)):
            if not name.endswith('.dist-info'):
                continue
            if name.split('-')[0].replace('-', '_').lower() != wanted:
                continue
            licences = os.path.join(libraries, name, 'licenses')
            for directory, _, filenames in os.walk(licences):
                for filename in sorted(filenames):
                    yield os.path.join(directory, filename)


def _site_packages(environment):
    """Every ``site-packages`` in an environment"""
    libraries = os.path.join(environment, 'lib')
    for name in sorted(os.listdir(libraries)) if os.path.isdir(libraries) else []:
        candidate = os.path.join(libraries, name, 'site-packages')
        if os.path.isdir(candidate):
            yield candidate


def _changelog(package, version, maintainer, when):
    """A Debian changelog with the one entry this package is"""
    import email.utils

    return (
        '%s (%s) unstable; urgency=medium\n'
        '\n'
        '  * Built from the upstream release of the same version.\n'
        '\n'
        ' -- %s  %s\n'
    ) % (package, version, maintainer, email.utils.formatdate(when, localtime=False))


def _link(root, at, target):
    """Put a symlink at *at* (inside *root*) pointing at *target*"""
    path = os.path.join(root, at.lstrip('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.lexists(path):
        os.unlink(path)
    os.symlink(target, path)


def _write(root, at, text, mode=0o644):
    """Write a text file at *at* (inside *root*)"""
    path = os.path.join(root, at.lstrip('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as stream:
        stream.write(text)
    os.chmod(path, mode)
    return path


def build(project='.', runtime=None, distribution=None, extras=(), requirements=(),
          commands=(), depends=(), recommends=(), session='either',
          prefix=DEFAULT_PREFIX, bindir=DEFAULT_BINDIR,
          section=DEFAULT_SECTION, categories=DEFAULT_CATEGORIES, revision=1,
          icon=None, menu=None, menu_name=None, maintainer=None,
          output='dist', build_directory=None, unused='prune', quiet=False):
    """Build a Debian package for an application, and return where it was written

    project -- what pip installs: a project directory, an sdist or a wheel
    runtime -- a relocatable CPython, as a directory or a tar archive
    distribution -- the Python distribution name, read from the project's
        ``pyproject.toml`` when it is not given
    extras -- the project's optional dependencies to install with it
    requirements -- requirement files installed before the project, which is
        where a dependency that is not yet on an index is pinned
    commands -- the console scripts to expose in *bindir*; the distribution's
        own by default. A game that ships a tool belonging to another
        distribution -- a world baker, a downloader -- names it here.
    depends -- Debian packages to depend on beyond
        :data:`OpenGLContext.packaging.SYSTEM_LIBRARIES`, which is what the
        engine itself opens and cannot run without
    recommends -- Debian packages an installation is better for having and
        works without, which is where a library reached through ``dlopen`` and
        absent without error belongs -- a sound backend, most often
    session -- which windowing stack to declare, one of
        :data:`OpenGLContext.packaging.SESSIONS`. The default, ``'either'``,
        takes the machine as it finds it: one alternative dependency that a
        desktop of either kind satisfies, since GLFW picks the matching build
        of itself at run time from ``XDG_SESSION_TYPE``. See
        :func:`OpenGLContext.packaging.session_libraries`.
    menu -- which command the desktop menu entry runs; the one named after the
        package by default, and ``''`` for a package with no menu entry
    icon -- a PNG to install as the package's icon and name in the menu entry
    unused -- ``'prune'`` to leave the parts of the interpreter an application
        cannot reach out of the package, or ``'keep'`` for all of it
    quiet -- whether to let pip report what it resolved and installed
    """
    from OpenGLContext import packaging
    from OpenGLContext.packaging import appdir

    if not runtime:
        raise ValueError('A package carries its own interpreter; name one with '
                         '--runtime')
    distribution = distribution or _project_name(project)
    package = debian_name(distribution)
    build_directory = build_directory or os.path.join('build', 'deb', package)
    root = os.path.join(build_directory, 'root')
    if os.path.isdir(build_directory):
        shutil.rmtree(build_directory)
    os.makedirs(root)

    installed = os.path.join(prefix, package)
    requirement = project + ('[%s]' % (','.join(extras),) if extras else '')
    python = appdir.build(
        runtime=runtime,
        staging=os.path.join(root, installed.lstrip('/')),
        installed=installed,
        install=[requirement],
        requirements=list(requirements),
        work=os.path.join(build_directory, 'runtime'),
        unused=unused,
        quiet=quiet,
    )
    described = appdir.metadata(python, distribution)
    architecture = debian_architecture(appdir.interpreter_platform(python))
    version = debian_version(described['version'], revision)
    try:
        maintainer = maintainer_field(maintainer or described['author'])
    except ValueError:
        raise ValueError(
            '%s declares no author to be the package maintainer; give one with '
            '--maintainer' % (distribution,)) from None

    wanted = list(commands) or described['scripts']
    for name in wanted:
        if not os.path.exists(os.path.join(os.path.dirname(python), name)):
            raise ValueError(
                '%s is not a command in the built environment; the ones that '
                'are: %s' % (name, ', '.join(sorted(described['scripts']))))
        _link(root, os.path.join(bindir, name),
              os.path.join(installed, appdir.ENVIRONMENT, 'bin', name))

    _write(root, os.path.join('/usr/share/doc', package, 'copyright'),
           _copyright_file(os.path.join(root, installed.lstrip('/'),
                                        appdir.ENVIRONMENT),
                           distribution, described['license']))
    _compressed(root, os.path.join('/usr/share/doc', package, 'changelog.Debian.gz'),
                _changelog(package, version, maintainer, _timestamp()))

    entry = menu if menu is not None else (package if package in wanted else '')
    if entry:
        icon_name = _install_icon(root, package, icon) if icon else None
        _write(root, os.path.join('/usr/share/applications', package + '.desktop'),
               desktop_entry(name=menu_name or described['name'],
                             command=os.path.join(bindir, entry),
                             summary=described['summary'],
                             categories=categories,
                             icon=icon_name))

    homepage = described['home_page'] or described['urls'].get(
        'Homepage', described['urls'].get('Repository', ''))
    control = control_paragraph({
        'Package': package,
        'Version': version,
        'Architecture': architecture,
        'Maintainer': maintainer,
        'Installed-Size': installed_size(root),
        'Depends': ', '.join(packaging.session_libraries(session) + list(depends)),
        'Recommends': ', '.join(
            packaging.session_recommendations(session) + list(recommends)),
        'Section': section,
        'Priority': 'optional',
        'Homepage': homepage,
        'Description': describe(described['summary'],
                                summarise(described['description'])),
    })

    os.makedirs(output, exist_ok=True)
    path = os.path.join(output, '%s_%s_%s.deb' % (package, version, architecture))
    write_deb(root, {'control': control, 'md5sums': md5sums(root)}, path)
    return path


def _compressed(root, at, text):
    """Write a gzipped text file, as Debian asks a changelog to be"""
    path = os.path.join(root, at.lstrip('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # mtime=0: the timestamp inside a gzip header is the one thing that would
    # differ between two builds of the same input.
    with open(path, 'wb') as stream:
        with gzip.GzipFile(fileobj=stream, mode='wb', mtime=0) as compressed:
            compressed.write(text.encode('utf-8'))
    return path


def _install_icon(root, package, icon):
    """Install a PNG into the icon theme, and return the name to refer to it by

    The icon goes in the directory for its own size, since a theme picks from
    the sizes it finds rather than scaling whatever it is given.
    """
    from PIL import Image

    with Image.open(icon) as image:
        width, height = image.size
    if width != height:
        raise ValueError('An icon is square; %s is %dx%d' % (icon, width, height))
    at = os.path.join('/usr/share/icons/hicolor', '%dx%d' % (width, height),
                      'apps', package + '.png')
    path = os.path.join(root, at.lstrip('/'))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    shutil.copyfile(icon, path)
    return package


def main(argv=None):
    """``oglc-deb``: build a Debian package for an application on the engine"""
    import argparse
    import logging

    from OpenGLContext import packaging

    parser = argparse.ArgumentParser(
        prog='oglc-deb',
        description=__doc__.split('\n\n')[0],
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--project', default='.',
                        help='what pip installs: a project directory, an sdist '
                             'or a wheel')
    parser.add_argument('--distribution', default=None,
                        help="the Python distribution name, read from the "
                             "project's pyproject.toml when not given")
    parser.add_argument('--extras', default='', metavar='A,B',
                        help="the project's optional dependencies to install "
                             'with it')
    parser.add_argument('--runtime', required=True, metavar='PATH',
                        help='a relocatable CPython to package, as a directory '
                             'or a tar archive. `uv python install --install-dir '
                             'DIR VERSION` fetches one.')
    parser.add_argument('--requirement', '-r', action='append', default=[],
                        metavar='FILE',
                        help='a requirements file to install before the project; '
                             'may be given more than once')
    parser.add_argument('--command', action='append', default=[], metavar='NAME',
                        help='a console script to put in the bin directory; the '
                             "distribution's own by default, and repeatable for "
                             'a game that ships a tool of another distribution')
    parser.add_argument('--depends', action='append', default=[], metavar='PKG',
                        help='a Debian package to depend on beyond the OpenGL '
                             'and X11 libraries every bundle needs')
    parser.add_argument('--recommends', action='append', default=[], metavar='PKG',
                        help='a Debian package the installation is better for '
                             'having and works without, such as a sound backend '
                             'opened at run time')
    parser.add_argument('--session', default='either',
                        choices=packaging.SESSIONS,
                        help='which windowing stack to declare. The default '
                             'takes the machine as it finds it -- one '
                             'dependency either kind of desktop satisfies -- '
                             'since GLFW picks the matching build of itself at '
                             'run time from XDG_SESSION_TYPE. Name one to pin '
                             'a fleet, or `both` to install regardless.')
    parser.add_argument('--prefix', default=DEFAULT_PREFIX,
                        help='where the environment is installed, under a '
                             'directory named for the package')
    parser.add_argument('--bindir', default=DEFAULT_BINDIR,
                        help='where the commands are linked')
    parser.add_argument('--section', default=DEFAULT_SECTION,
                        help='the Debian section the package belongs to')
    parser.add_argument('--categories', default=DEFAULT_CATEGORIES,
                        help='the desktop menu categories, semicolon-separated')
    parser.add_argument('--menu', default=None, metavar='COMMAND',
                        help='the command the menu entry runs; the one named '
                             'after the package by default. Empty for no entry.')
    parser.add_argument('--menu-name', default=None, metavar='NAME',
                        help='what the menu entry is called; the distribution '
                             'name by default')
    parser.add_argument('--icon', default=None, metavar='PATH',
                        help='a square PNG to install as the package icon')
    parser.add_argument('--maintainer', default=None, metavar='NAME <EMAIL>',
                        help="the package maintainer; the project's author by "
                             'default')
    parser.add_argument('--revision', default=1, metavar='N',
                        help='the packaging of this upstream release, counting '
                             'from 1')
    parser.add_argument('--output', '-o', default='dist', metavar='DIR',
                        help='where to write the package')
    parser.add_argument('--build-directory', default=None, metavar='DIR',
                        help='where to assemble it; build/deb/<package> by default')
    parser.add_argument('--keep-unused', action='store_true',
                        help='ship the whole interpreter, headers and Tk and '
                             'all, rather than only the parts an application '
                             'can reach')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='report nothing but the package that was written')
    options = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING if options.quiet else logging.INFO,
        format='%(message)s',
    )
    if not options.quiet:
        logging.getLogger(__name__).info(
            'for a %s session, the machine is asked for: %s',
            options.session,
            ', '.join(packaging.session_libraries(options.session)
                      + list(options.depends)))
    path = build(
        project=options.project,
        runtime=options.runtime,
        distribution=options.distribution,
        extras=[part for part in options.extras.split(',') if part],
        requirements=options.requirement,
        commands=options.command,
        depends=options.depends,
        recommends=options.recommends,
        session=options.session,
        prefix=options.prefix,
        bindir=options.bindir,
        section=options.section,
        categories=options.categories,
        revision=options.revision,
        icon=options.icon,
        menu=options.menu,
        menu_name=options.menu_name,
        maintainer=options.maintainer,
        output=options.output,
        build_directory=options.build_directory,
        unused='keep' if options.keep_unused else 'prune',
        quiet=options.quiet,
    )
    print(path)
    return 0
