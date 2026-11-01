"""The modules, classes and functions a tutorial's code imports, as links.

A tutorial's code is highlighted by Sphinx into HTML.  :func:`imports` reads
the script's import statements and :func:`link_code` rewrites that HTML so the
name of each imported thing points at the page that documents it::

    from OpenGLContext.loaders import sceneloader
         ~~~~~~~~~~~~~ ~~~~~~~ ~~~~~~~~~~~~~~~~~~~~
         |             |       the module the name is
         |             the package
         the package

Each package in a module path is a link of its own, the dots between them stay
text, and every later use of an imported name in the code links the same way.

Which page a name belongs to is the documentation build's to say, so
:func:`link_code` is given a function from a dotted name to an address, or
``None`` where nothing documents it; ``docs/_ext/oglc_tutorials.py`` supplies
the one that asks Sphinx's Python domain and the intersphinx inventories.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import re
from collections.abc import Callable
from types import ModuleType
from typing import Any

__all__ = [
    'Imports',
    'candidates',
    'declare',
    'imports',
    'link_code',
    'read_declaration',
]

#: A dotted name to the address of the page that documents it, or ``None``.
Resolver = Callable[[str], 'str | None']

#: ``from module import *`` in a declaration, where a name would be.
STAR = '*'

#: The third word of a declaration line for a name an ``as`` renames.
AS = 'as'


@dataclasses.dataclass(frozen=True)
class Imports:
    """What a script's import statements bind.

    ``names`` maps a name the code uses to the dotted name it stands for
    (``BaseContext`` to ``OpenGLContext.context.Context``).  ``stars`` are the
    modules imported with ``*``: they bind every public name they export, which
    :meth:`target` asks the module itself.
    """

    names: dict[str, str] = dataclasses.field(default_factory=dict)
    stars: tuple[str, ...] = ()
    #: Names an ``as`` renames, to what they stand for.  The name is bound to
    #: nothing in the code; it is linked where the import writes it, before
    #: its ``as``.
    originals: dict[str, str] = dataclasses.field(default_factory=dict)

    def target(self, name: str) -> str | None:
        """The dotted name ``name`` stands for in the code, or ``None``."""
        if name in self.names:
            return self.names[name]
        if name.startswith('_'):
            return None
        for package in self.stars:
            module = _module(package)
            if module is None or not hasattr(module, name):
                continue
            exported = getattr(module, '__all__', None)
            if exported is None or name in exported:
                return '%s.%s' % (package, name)
        return None

    def __bool__(self) -> bool:
        return bool(self.names or self.stars or self.originals)


def imports(source: str) -> Imports:
    """The names the import statements in ``source`` bind.

    Statements anywhere in the file count, including those under
    ``if typing.TYPE_CHECKING``.  A relative import names something only the
    script's own package can say, and is left out.
    """
    names: dict[str, str] = {}
    originals: dict[str, str] = {}
    stars: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    names[alias.asname] = alias.name
                else:
                    package = alias.name.split('.')[0]
                    names[package] = package
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            for alias in node.names:
                if alias.name == STAR:
                    if node.module not in stars:
                        stars.append(node.module)
                else:
                    target = '%s.%s' % (node.module, alias.name)
                    names[alias.asname or alias.name] = target
                    if alias.asname:
                        originals[alias.name] = target
    return Imports(names=names, stars=tuple(stars), originals=originals)


def _module(name: str) -> ModuleType | None:
    """The module ``name``, or ``None`` where the machine cannot import it.

    A package that needs a library the machine lacks (GLUT with no freeglut)
    is as unlinkable as one that does not exist; the rest of the page still
    links.
    """
    try:
        return importlib.import_module(name)
    except (ImportError, OSError):
        return None


def _object(dotted: str) -> Any:
    """What ``dotted`` names, imported, or ``None``."""
    module = _module(dotted)
    if module is not None:
        return module
    package, _, name = dotted.rpartition('.')
    module = _module(package) if package else None
    return getattr(module, name, None) if module is not None else None


def candidates(dotted: str) -> list[str]:
    """The names ``dotted`` might be documented under, best first.

    The name as the code wrote it comes first, since a package that documents
    what it re-exports documents it there.  Behind it is the name the class,
    function or module reports for itself: ``OpenGLContext.loaders.gltf``
    exports ``sample_model_url`` that ``...gltf.samples`` defines and
    documents.
    """
    found = [dotted]
    thing = _object(dotted)
    if isinstance(thing, ModuleType):
        home = thing.__name__
    else:
        module = getattr(thing, '__module__', None)
        qualified = getattr(thing, '__qualname__', None)
        home = '%s.%s' % (module, qualified) if module and qualified else dotted
    if home not in found:
        found.append(home)
    return found


def declare(found: Imports) -> str:
    """``found`` as the lines of a ``tutorial-imports`` directive's body."""
    lines = ['%s %s' % (name, target) for name, target in found.names.items()]
    lines.extend('%s %s' % (STAR, package) for package in found.stars)
    lines.extend(
        '%s %s %s' % (name, target, AS) for name, target in found.originals.items()
    )
    return '\n'.join(lines)


def read_declaration(text: str) -> Imports:
    """The :class:`Imports` that :func:`declare` wrote ``text`` from."""
    names: dict[str, str] = {}
    originals: dict[str, str] = {}
    stars: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        name, target, *renamed = line.split()
        if renamed:
            originals[name] = target
        elif name == STAR:
            stars.append(target)
        else:
            names[name] = target
    return Imports(names=names, stars=tuple(stars), originals=originals)


#: A name or a module path in Pygments' HTML.  ``nn`` is a module path in an
#: import statement; ``n`` is any other name.
_TOKEN = re.compile(r'<span class="(?P<kind>nn|n)">(?P<text>[\w.]+)</span>')

#: What Pygments writes between ``as`` and the name that follows it.
_AFTER_AS = re.compile(r'<span class="k">as</span><span class="w"> </span>$')

#: What Pygments writes after a name that an ``as`` renames.
_BEFORE_AS = '<span class="w"> </span><span class="k">as</span>'
_BEFORE_AS_SPACED = ' <span class="k">as</span>'

#: The attribute dot in ``obj.name``: that ``name`` is the object's, not the
#: import's.
_AFTER_DOT = '<span class="o">.</span>'

#: Longest stretch before a token that the two checks above need to see.
_LOOKBEHIND = 64


def _anchor(address: str, kind: str, text: str) -> str:
    return '<a class="code-link" href="%s"><span class="%s">%s</span></a>' % (
        address,
        kind,
        text,
    )


def link_code(html: str, found: Imports, resolve: Callable[[str], str | None]) -> str:
    """``html``, Pygments' highlighting of code, with imported names as links.

    ``resolve`` is asked for each distinct name once.  A name it has no page for
    is left as the highlighter wrote it.
    """
    asked: dict[str, str | None] = {}

    def address(dotted: str) -> str | None:
        if dotted not in asked:
            asked[dotted] = resolve(dotted)
        return asked[dotted]

    def package_path(text: str) -> str:
        if text.startswith('.'):
            return text
        parts = text.split('.')
        pieces: list[str] = []
        for number, part in enumerate(parts):
            dotted = '.'.join(parts[: number + 1])
            target = address(dotted)
            pieces.append(
                _anchor(target, 'nn', part)
                if target
                else '<span class="nn">%s</span>' % (part,)
            )
        return '<span class="nn">.</span>'.join(pieces)

    def replace(match: re.Match[str]) -> str:
        kind, text = match.group('kind'), match.group('text')
        before = match.string[max(0, match.start() - _LOOKBEHIND) : match.start()]
        if before.endswith(_AFTER_DOT):
            return match.group(0)
        if kind == 'nn' and not _AFTER_AS.search(before):
            return package_path(text)
        if '.' in text:
            return match.group(0)
        if match.string.startswith((_BEFORE_AS, _BEFORE_AS_SPACED), match.end()):
            dotted = found.originals.get(text)
        else:
            dotted = found.target(text)
        target = address(dotted) if dotted else None
        return _anchor(target, kind, text) if target else match.group(0)

    return _TOKEN.sub(replace, html)
