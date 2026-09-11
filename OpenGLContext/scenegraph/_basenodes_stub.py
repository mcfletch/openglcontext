"""What ``basenodes.pyi`` should say, worked out from the node registry.

:mod:`OpenGLContext.scenegraph.basenodes` fills its namespace at import time
from the plugin registry, so nothing a type checker reads declares the names in
it -- and every scenegraph a caller builds goes through those names.
``basenodes.pyi`` declares them, and this is what writes it:
``scripts/write_basenodes_stub.py`` puts the text on disk and
``tests/unit/test_basenodes_stub.py`` holds the file to the registry, so a node
registered without a stub entry fails the suite rather than reaching a release
as an unknown name.

The registry is read from the ``Node( 'Name', 'module.path.Class' )`` calls in
``OpenGLContext/__init__.py`` rather than by importing it, so the stub can be
written and checked without a GL-capable interpreter, and so a node whose
implementation module will not import on this machine is still declared.
"""

from __future__ import annotations

import ast
import collections
import os
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

#: Where the ``Node(...)`` registrations live, relative to the package root.
REGISTRY_MODULE = '__init__.py'

#: Where the generated stub belongs, relative to the package root.
STUB_PATH = os.path.join('scenegraph', 'basenodes.pyi')

HEADER = '''"""Every registered scenegraph node class, by name.

:mod:`OpenGLContext.scenegraph.basenodes` builds its namespace at import time
from the plugin registry, so this declares what a type checker finds there.
The runtime module is the authority on what is present; this file is generated
from the registrations in ``OpenGLContext/__init__.py`` by
``scripts/write_basenodes_stub.py``, and ``tests/unit/test_basenodes_stub.py``
holds it to them.

A third party's node, registered by importing its own package, is not here and
resolves as ``Any`` -- which is what a checker can say about a name whose class
it has no declaration for.
"""
from typing import Any, Dict

#: Node classes by the name they are registered under, including any a third
#: party added; ``basenodes.NAME`` is the same object.
PROTOTYPES: Dict[str, Any]

'''

#: Node families built at import time rather than written out, as
#: ``(module, name prefix, the base class in that module)``.
#: ``shaders._uniformCls`` makes one class per GLSL type suffix with ``type()``,
#: so there is no ``class FloatUniform1f`` for a checker to find and the stub
#: declares each as the subclass it is.
DYNAMIC_FAMILIES = (
    ('OpenGLContext.scenegraph.shaders', 'FloatUniform', 'FloatUniform'),
    ('OpenGLContext.scenegraph.shaders', 'IntUniform', 'IntUniform'),
)


def _dynamic_base(module: str, attribute: str) -> Optional[Tuple[str, str]]:
    """The ``(module, base)`` a dynamically built node derives from, or None."""
    for family_module, prefix, base in DYNAMIC_FAMILIES:
        if module != family_module or not attribute.startswith(prefix):
            continue
        if attribute == prefix:
            # The base class itself rather than one built over it: it is
            # written out in its module, so a checker reads it already.
            return None
        return family_module, base
    return None


def package_root(start: str) -> str:
    """The ``OpenGLContext/`` directory containing ``start``."""
    here = os.path.abspath(start)
    while os.path.basename(here) != 'OpenGLContext':
        parent = os.path.dirname(here)
        if parent == here:
            raise ValueError('%r is not inside an OpenGLContext package' % (start,))
        here = parent
    return here


def _string(expression: ast.expr, bindings: Dict[str, str]) -> str:
    """The value of a registration argument, or raise ``ValueError``.

    Two forms occur: a literal, and a literal prefix concatenated with the
    variable of an enclosing ``for`` loop, which is how the shader uniform
    nodes are registered one per GLSL type suffix.
    """
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return expression.value
    if isinstance(expression, ast.Name) and expression.id in bindings:
        return bindings[expression.id]
    if isinstance(expression, ast.BinOp) and isinstance(expression.op, ast.Add):
        return _string(expression.left, bindings) + _string(
            expression.right, bindings)
    raise ValueError(ast.dump(expression))


def _literals(expression: ast.expr) -> List[str]:
    """The strings a ``for`` loop's tuple or list iterates, or raise."""
    if isinstance(expression, (ast.Tuple, ast.List)):
        return [_string(element, {}) for element in expression.elts]
    raise ValueError(ast.dump(expression))


def _calls(body: List[ast.stmt], bindings: Dict[str, str]
           ) -> Iterator[Tuple[str, str]]:
    for statement in body:
        if isinstance(statement, ast.For):
            if not isinstance(statement.target, ast.Name):
                continue
            for value in _literals(statement.iter):
                nested = dict(bindings, **{statement.target.id: value})
                yield from _calls(statement.body, nested)
            continue
        for node in ast.walk(statement):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            if not isinstance(function, ast.Name) or function.id != 'Node':
                continue
            if len(node.args) < 2:
                continue
            yield (
                _string(node.args[0], bindings),
                _string(node.args[1], bindings),
            )


def registrations(source: str) -> List[Tuple[str, str]]:
    """The ``(name, import path)`` pairs of every ``Node(...)`` call in *source*.

    Both have to be worked out statically: a name a stub cannot spell is a name
    a checker cannot resolve.  A registration whose arguments are neither
    literals nor a literal joined to an enclosing loop's variable raises
    ``ValueError``, naming the expression that could not be read -- and the
    call raises rather than the iteration, so the fault is reported against the
    registration rather than against whoever consumed the answer.

    Two shapes are passed over instead: a ``Node(`` call short of arguments,
    which could not have registered anything either since both are required,
    and a loop whose target unpacks a tuple, which nothing registers through.
    What catches a node that went missing for any reason is the comparison with
    the running registry in ``tests/unit/test_basenodes_stub.py``, which reads
    what was registered rather than what was written.
    """
    return list(_calls(ast.parse(source).body, {}))


def imports(pairs: Iterable[Tuple[str, str]]) -> Dict[str, List[Tuple[str, str]]]:
    """Group ``(name, import path)`` pairs into module -> [(attribute, name)]."""
    grouped: Dict[str, List[Tuple[str, str]]] = collections.defaultdict(list)
    for name, path in pairs:
        module, _dot, attribute = path.rpartition('.')
        grouped[module].append((attribute, name))
    return {module: sorted(set(entries)) for module, entries in grouped.items()}


def stub_text(source: str) -> str:
    """The whole contents of ``basenodes.pyi`` for the given registry source.

    Three blocks: the bases the dynamically built families derive from, the
    node names themselves, and ``__all__``.  ``__all__`` is spelled out rather
    than declared as a bare ``List[str]``, because ``from basenodes import *``
    is how much of the engine and most callers reach these names and a checker
    can only expand that against a literal.
    """
    lines = [HEADER]
    grouped = imports(registrations(source))
    found = (
        _dynamic_base(module, attribute)
        for module, entries in grouped.items()
        for attribute, _name in entries
    )
    bases = sorted({pair for pair in found if pair is not None})
    if bases:
        for module, base in bases:
            lines.append('from %s import %s as _%s\n' % (module, base, base))
        lines.append('\n')
    names = []
    for module in sorted(grouped):
        for attribute, name in grouped[module]:
            names.append(name)
            dynamic = _dynamic_base(module, attribute)
            if dynamic:
                lines.append('class %s(_%s): ...\n' % (name, dynamic[1]))
            else:
                # ``as`` even where the two agree: a stub re-exports only the
                # names it aliases explicitly.
                lines.append('from %s import %s as %s\n' % (module, attribute, name))
    lines.append('\n__all__ = [\n')
    for name in sorted(names):
        lines.append("    '%s',\n" % (name,))
    lines.append(']\n')
    return ''.join(lines)


def expected(start: str) -> Tuple[str, str]:
    """``(path of the stub, what it should contain)`` for this checkout."""
    root = package_root(start)
    with open(os.path.join(root, REGISTRY_MODULE), encoding='utf-8') as handle:
        source = handle.read()
    return os.path.join(root, STUB_PATH), stub_text(source)
