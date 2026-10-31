"""Which files use a scenegraph node.

The API page of a node class ends with the files that instantiate that node:
Python that imports it from the engine, X3D XML documents with an element of its
name, and ClassicVRML or VRML97 documents with a node of its name.  Each is
found by reading the file's syntax -- ``ast``, ``expat`` and a small lexer for
the VRML encodings -- so a node named in a comment or a string does not count.

    index = build(workspace_root())
    index.uses('Box')        # [FileUse, ...] in the order a page lists them
    sections = class_sections(index, tutorials={'shaders/shader_1'})
    sections(OpenGLContext.scenegraph.box.Box)   # the reST blocks for the page

The projects scanned are the submodules of the workspace; a Python file counts
a name only where its own imports bind the name to the engine, so a variable
called ``Box`` is not the node.  ``build-docs.py`` passes :func:`class_sections`
to PyOpenGL's ``directdocs``.
"""

from __future__ import annotations

import ast
import configparser
import dataclasses
import logging
import os
import re
import warnings
from collections.abc import Callable, Collection, Iterator
from xml.parsers import expat

__all__ = [
    'FileUse',
    'Index',
    'build',
    'class_sections',
    'node_name',
    'node_names',
    'scan_classic',
    'scan_file',
    'scan_python',
    'scan_x3d',
    'section',
    'workspace_root',
]

log = logging.getLogger('nodeusage')

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: Packages whose classes are scenegraph nodes, and from which a Python file
#: imports them.
ENGINE_PACKAGES = frozenset({'OpenGLContext', 'OpenGLContext_editor', 'OpenGLContext_qt', 'vrml'})

#: The branch the links go to.
BRANCH = 'main'

#: Submodules that hold no source anyone writes nodes in.
SKIPPED_PROJECTS = frozenset({'website'})

#: Directories not read: environments, build output, worktrees, the unit
#: tests (assertions about a node, which show nothing about using one) and
#: the reference renders.
SKIPPED_DIRECTORIES = frozenset(
    {
        '.git',
        '.venv',
        '.preflight-venv',
        '.claude',
        '.worktrees',
        '.tox',
        'build',
        'dist',
        'node_modules',
        '__pycache__',
        '_build',
        'reference_images',
        'unit',
        'site-packages',
    }
)

def _is_library(parts: list[str]) -> bool:
    """Whether a file, as its path parts under a project, is a node-defining package's own source.

    That source implements nodes rather than showing them used; the commands
    in a package's ``bin`` are not part of it.
    """
    parts = parts[1:] if parts[0] == 'src' else parts
    return parts[0] in ENGINE_PACKAGES and 'bin' not in parts[:-1]


#: The files read, by extension.
KINDS = {
    '.py': 'python',
    '.x3d': 'x3d',
    '.wrl': 'classic',
    '.x3dv': 'classic',
}

#: Uses listed on a page before the rest are counted.
LISTED = 12

#: Lines named in a file's entry before the rest are elided.
LINES_NAMED = 6


@dataclasses.dataclass(frozen=True)
class FileUse:
    """One file's use of a node."""

    #: The submodule the file is in.
    project: str
    #: The file, relative to its project, with ``/`` separators.
    path: str
    #: The lines the node appears on, in order.
    lines: tuple[int, ...]
    #: The file on the project's GitHub page, at its first line.
    url: str
    #: Where it sorts: the lower, the earlier a page lists it.
    rank: int


class Index:
    """The uses found, by node name."""

    def __init__(self) -> None:
        self._uses: dict[str, list[FileUse]] = {}

    def add(self, node: str, use: FileUse) -> None:
        self._uses.setdefault(node, []).append(use)

    def uses(self, node: str) -> list[FileUse]:
        """The files that use ``node``: tutorials first, then by project and path."""
        return sorted(
            self._uses.get(node, ()), key=lambda use: (use.rank, use.project, use.path)
        )

    def __len__(self) -> int:
        return len(self._uses)


# --------------------------------------------------------------------------- #
# Which classes are nodes
# --------------------------------------------------------------------------- #
def node_name(cls: type) -> str | None:
    """The name a document gives ``cls``, or None where it is not a node of the engine.

    A class is a node of the name it answers to when it is the class that declares
    that name: it is called by it, or sets ``PROTO`` itself.  A subclass that
    only inherits another node's ``PROTO`` is that node's implementation under
    another class name.
    """
    from vrml import node, protofunctions  # noqa: PLC0415 imports the scenegraph, which the build-docs run has loaded in any case

    if not (isinstance(cls, type) and issubclass(cls, node.Node)):
        return None
    if cls.__module__.split('.')[0] not in ENGINE_PACKAGES:
        return None
    name = str(protofunctions.protoName(cls))
    if name == cls.__name__ or cls.__dict__.get('PROTO') == name:
        return name
    return None


def node_names() -> frozenset[str]:
    """Every node name the engine has a class for.

    Imports ``vrml.x3d.nodes`` and every module of ``OpenGLContext.scenegraph``.
    """
    import importlib  # noqa: PLC0415 used only here
    import pkgutil  # noqa: PLC0415 used only here

    from vrml import node  # noqa: PLC0415 imports the scenegraph
    from vrml.x3d import nodes  # noqa: F401, PLC0415 registers the X3D declarations
    import OpenGLContext.scenegraph as scenegraph  # noqa: PLC0415 imports the scenegraph

    for info in pkgutil.iter_modules(scenegraph.__path__):
        try:
            importlib.import_module('%s.%s' % (scenegraph.__name__, info.name))
        except Exception as err:  # noqa: BLE001 a module that will not import here has no nodes to name
            log.warning('node names: could not import %s: %s', info.name, err)
    found: set[str] = set()
    pending = list(node.Node.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        name = node_name(cls)
        if name:
            found.add(name)
    return frozenset(found)


# --------------------------------------------------------------------------- #
# Reading a file
# --------------------------------------------------------------------------- #
def scan_python(source: str, names: Collection[str]) -> dict[str, list[int]]:
    """The lines of ``source`` on which each of ``names`` is used, by name.

    A name counts where the file's imports bind it to a package in
    :data:`ENGINE_PACKAGES`: ``from OpenGLContext... import Box`` (aliased or
    not), ``module.Box`` for a module imported from them, or ``Box`` itself
    when the file star-imports from them and defines no ``Box`` of its own.
    """
    try:
        with warnings.catch_warnings():
            # The files read are other people's source; what they do with a
            # backslash is theirs to answer for.
            warnings.simplefilter('ignore')
            tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return {}
    bound: dict[str, str] = {}
    modules: set[str] = set()
    defined: set[str] = set()
    star = False
    for item in ast.walk(tree):
        if isinstance(item, ast.ImportFrom):
            if item.level or not item.module or item.module.split('.')[0] not in ENGINE_PACKAGES:
                continue
            for alias in item.names:
                if alias.name == '*':
                    star = True
                elif alias.name in names:
                    bound[alias.asname or alias.name] = alias.name
                else:
                    modules.add(alias.asname or alias.name)
        elif isinstance(item, ast.Import):
            for alias in item.names:
                if alias.name.split('.')[0] in ENGINE_PACKAGES:
                    modules.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            defined.add(item.name)
        elif isinstance(item, ast.Name) and isinstance(item.ctx, ast.Store):
            defined.add(item.id)
        elif isinstance(item, ast.arg):
            defined.add(item.arg)
    found: dict[str, set[int]] = {}
    for item in ast.walk(tree):
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load):
            if item.id in bound:
                found.setdefault(bound[item.id], set()).add(item.lineno)
            elif star and item.id in names and item.id not in defined:
                found.setdefault(item.id, set()).add(item.lineno)
        elif (
            isinstance(item, ast.Attribute)
            and isinstance(item.ctx, ast.Load)
            and item.attr in names
        ):
            root: ast.expr = item.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name) and root.id in modules:
                found.setdefault(item.attr, set()).add(item.lineno)
    return {name: sorted(lines) for name, lines in found.items()}


def scan_x3d(source: str, names: Collection[str]) -> dict[str, list[int]]:
    """The lines of an X3D XML document on which an element is one of ``names``.

    A document that does not parse to its end keeps what was read before the
    fault.
    """
    found: dict[str, list[int]] = {}
    parser = expat.ParserCreate()

    def start(tag: str, _attributes: object) -> None:
        if tag in names:
            found.setdefault(tag, []).append(parser.CurrentLineNumber)

    parser.StartElementHandler = start
    try:
        parser.Parse(source, True)
    except expat.ExpatError:
        pass
    return found


_CLASSIC = re.compile(
    r"""
    (?P<comment>\#[^\n]*)
    | (?P<string>"(?:\\.|[^"\\])*")
    | (?P<open>\{)
    | (?P<punctuation>[\[\]},])
    | (?P<word>[^\s{}\[\],"\#]+)
    """,
    re.VERBOSE | re.DOTALL,
)


def scan_classic(source: str, names: Collection[str]) -> dict[str, list[int]]:
    """The lines of a ClassicVRML or VRML97 document on which one of ``names`` opens a node.

    A node is a word followed by ``{``; comments and strings are skipped, and
    the word after ``DEF`` is a name for a node rather than the node.
    """
    words: list[tuple[str, str, int]] = []
    line = 1
    position = 0
    for match in _CLASSIC.finditer(source):
        line += source.count('\n', position, match.start())
        position = match.start()
        kind = match.lastgroup or ''
        if kind != 'comment':
            words.append((kind, match.group(), line))
    found: dict[str, list[int]] = {}
    for index, (kind, text, line) in enumerate(words[:-1]):
        if kind == 'word' and text in names and words[index + 1][0] == 'open':
            if index and words[index - 1][1] == 'DEF':
                continue
            found.setdefault(text, []).append(line)
    return found


_SCANNERS: dict[str, Callable[[str, Collection[str]], dict[str, list[int]]]] = {
    'python': scan_python,
    'x3d': scan_x3d,
    'classic': scan_classic,
}


def scan_file(path: str, names: Collection[str]) -> dict[str, list[int]]:
    """The lines on which each of ``names`` is used in the file at ``path``.

    A file of a kind that is not read, or that cannot be read, has none.
    """
    kind = KINDS.get(os.path.splitext(path)[1].lower())
    if kind is None:
        return {}
    try:
        with open(path, encoding='utf-8', errors='replace') as handle:
            source = handle.read()
    except OSError as err:
        log.warning('node usage: could not read %s: %s', path, err)
        return {}
    return _SCANNERS[kind](source, names)


# --------------------------------------------------------------------------- #
# Reading a workspace
# --------------------------------------------------------------------------- #
def workspace_root(start: str = HERE) -> str | None:
    """The outermost directory holding ``.gitmodules`` at or above ``start``, or None.

    A project has submodules of its own (this one holds the reference
    images), so the nearest is not the workspace.
    """
    found = None
    directory = os.path.abspath(start)
    while True:
        if os.path.isfile(os.path.join(directory, '.gitmodules')):
            found = directory
        parent = os.path.dirname(directory)
        if parent == directory:
            return found
        directory = parent


def projects(root: str) -> list[tuple[str, str]]:
    """The submodules of the workspace at ``root``, each as its path and GitHub page."""
    parser = configparser.ConfigParser(interpolation=None)
    with open(os.path.join(root, '.gitmodules'), encoding='utf-8') as handle:
        parser.read_string(handle.read())
    found = []
    for section_name in parser.sections():
        path = parser.get(section_name, 'path', fallback='')
        url = parser.get(section_name, 'url', fallback='')
        if path and url and path not in SKIPPED_PROJECTS and os.path.isdir(os.path.join(root, path)):
            found.append((path, _page(url)))
    return found


def _page(url: str) -> str:
    """The web page of a repository, from the URL it is cloned from."""
    url = re.sub(r'^git@([^:]+):', r'https://\1/', url)
    return re.sub(r'\.git$', '', url).rstrip('/')


def rank(path: str) -> int:
    """Where a file sorts among a node's uses, from where it is in its project."""
    parts = path.split('/')
    if parts[:2] == ['tests', 'tutorials']:
        return 0
    if parts[:2] == ['docs', 'samples']:
        return 1
    if parts[:2] == ['tests', 'wrls']:
        return 2
    if 'bin' in parts[:-1] or parts[0] == 'scripts':
        return 3
    if parts[0] == 'tests':
        return 5
    return 4


def _files(directory: str) -> Iterator[str]:
    for here, subdirectories, files in os.walk(directory):
        subdirectories[:] = sorted(
            name
            for name in subdirectories
            if name not in SKIPPED_DIRECTORIES
            and not name.startswith('.')
            and not name.endswith('.egg-info')
            and not os.path.islink(os.path.join(here, name))
        )
        for name in sorted(files):
            if os.path.splitext(name)[1].lower() not in KINDS:
                continue
            path = os.path.join(here, name)
            if not _is_library(os.path.relpath(path, directory).split(os.sep)):
                yield path


def build(root: str, names: Collection[str] | None = None) -> Index:
    """The uses of ``names`` in every project of the workspace at ``root``.

    ``names`` is every node the engine has a class for where none are given.
    """
    names = node_names() if names is None else names
    index = Index()
    for project, page in projects(root):
        base = os.path.join(root, project)
        for path in _files(base):
            relative = os.path.relpath(path, base).replace(os.sep, '/')
            for node, lines in scan_file(path, names).items():
                index.add(
                    node,
                    FileUse(
                        project=project,
                        path=relative,
                        lines=tuple(lines),
                        url='%s/blob/%s/%s#L%d' % (page, BRANCH, relative, lines[0]),
                        rank=rank(relative),
                    ),
                )
    return index


# --------------------------------------------------------------------------- #
# Writing a page
# --------------------------------------------------------------------------- #
def _lines(lines: tuple[int, ...]) -> str:
    named = ', '.join(str(line) for line in lines[:LINES_NAMED])
    if len(lines) > LINES_NAMED:
        named += ', ...'
    return '(line %s)' % (named,) if len(lines) == 1 else '(lines %s)' % (named,)


def _walkthrough(use: FileUse, tutorials: Collection[str]) -> str:
    """The reST linking the tutorial page written from ``use``'s script, or ''."""
    parts = use.path.split('/')
    if use.project != 'openglcontext' or parts[:2] != ['tests', 'tutorials'] or len(parts) != 4:
        return ''
    page = '%s/%s' % (parts[2], os.path.splitext(parts[3])[0])
    if page not in tutorials:
        return ''
    return ' -- :doc:`walkthrough </tutorials/%s>`' % (page,)


def section(node: str, uses: list[FileUse], tutorials: Collection[str]) -> list[str]:
    """The reST block listing the files that use ``node``; empty where none do.

    ``tutorials`` names the tutorial pages written (``shaders/shader_1``), so
    a use in one links its walkthrough.
    """
    if not uses:
        return []
    out = ['.. rubric:: Where this node is used', '']
    for use in uses[:LISTED]:
        out.append(
            '* `%s: %s <%s>`__ %s%s'
            % (use.project, use.path, use.url, _lines(use.lines), _walkthrough(use, tutorials))
        )
    rest = len(uses) - LISTED
    if rest > 0:
        out.append('* and %d more file%s' % (rest, '' if rest == 1 else 's'))
    return ['\n'.join(out)]


def class_sections(index: Index, tutorials: Collection[str] = ()) -> Callable[[type], list[str]]:
    """The callable PyOpenGL's ``directdocs`` takes as ``class_sections``.

    It answers the block listing a node's uses for the class of a node that has
    some, and nothing for any other class.
    """

    def sections(cls: type) -> list[str]:
        name = node_name(cls)
        if name is None:
            return []
        return section(name, index.uses(name), tutorials)

    return sections
