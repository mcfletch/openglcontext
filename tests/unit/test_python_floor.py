"""The package imports on the oldest Python its metadata admits.

`requires-python` names 3.10, so a module that imports a 3.11 name from the
standard library at run time fails on import there. Names used only in
annotations belong under `TYPE_CHECKING`, where `from __future__ import
annotations` leaves them unevaluated.
"""
import ast
import pathlib

import OpenGLContext

#: Standard-library names and modules added after 3.10, by module.
ADDED_AFTER_3_10 = {
    'typing': {
        'Self', 'LiteralString', 'Never', 'assert_never', 'assert_type',
        'reveal_type', 'Required', 'NotRequired', 'Unpack', 'TypeVarTuple',
        'dataclass_transform', 'get_overloads', 'clear_overloads',
    },
    'enum': {'StrEnum', 'ReprEnum', 'verify', 'member', 'nonmember'},
    'itertools': {'batched'},
}
MODULES_ADDED_AFTER_3_10 = {'tomllib'}


def unguarded_imports(tree):
    """Imports in `tree` that run at import time, as (line, source) pairs."""
    found = []

    def visit(statements, guarded):
        for statement in statements:
            if isinstance(statement, ast.If):
                test = ast.unparse(statement.test)
                visit(statement.body, guarded or 'TYPE_CHECKING' in test
                      or 'version_info' in test)
                visit(statement.orelse, guarded or 'version_info' in test)
            elif isinstance(statement, ast.Try):
                visit(statement.body, True)
                for handler in statement.handlers:
                    visit(handler.body, guarded)
                visit(statement.orelse, guarded)
                visit(statement.finalbody, guarded)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef,
                                        ast.ClassDef, ast.With, ast.For,
                                        ast.While)):
                visit(statement.body, guarded)
            elif not guarded and isinstance(statement, ast.ImportFrom):
                added = ADDED_AFTER_3_10.get(statement.module or '', ())
                if (statement.module in MODULES_ADDED_AFTER_3_10
                        or any(alias.name in added for alias in statement.names)):
                    found.append((statement.lineno, ast.unparse(statement)))
            elif not guarded and isinstance(statement, ast.Import):
                if any(alias.name in MODULES_ADDED_AFTER_3_10
                       for alias in statement.names):
                    found.append((statement.lineno, ast.unparse(statement)))

    visit(tree.body, False)
    return found


def test_the_scan_finds_a_runtime_import_of_a_newer_name():
    tree = ast.parse('from typing import Any, Self\nimport tomllib\n')
    assert [source for _, source in unguarded_imports(tree)] == [
        'from typing import Any, Self', 'import tomllib']


def test_the_scan_passes_names_under_type_checking_and_try():
    tree = ast.parse(
        'from typing import TYPE_CHECKING\n'
        'if TYPE_CHECKING:\n'
        '    from typing import Self\n'
        'try:\n'
        '    import tomllib\n'
        'except ImportError:\n'
        '    tomllib = None\n')
    assert unguarded_imports(tree) == []


def test_no_module_imports_a_name_newer_than_the_declared_floor():
    root = pathlib.Path(OpenGLContext.__file__).parent
    offences = []
    for path in sorted(root.rglob('*.py')):
        tree = ast.parse(path.read_text(encoding='utf-8'), str(path))
        offences += ['%s:%d  %s' % (path.relative_to(root), line, source)
                     for line, source in unguarded_imports(tree)]
    assert offences == []
