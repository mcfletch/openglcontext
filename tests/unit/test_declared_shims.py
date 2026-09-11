"""The hand-written ``TYPE_CHECKING`` declarations, held to the real classes.

A mix-in that needs something its sibling supplies declares it under ``if
TYPE_CHECKING`` -- a declaration for a checker and nothing else, since defining
it for real would put a second implementation in the MRO or register a second
copy of a VRML97 field. mypy believes such a declaration outright: rename
``NEED_TRANSPOSE`` on the class it stands for and the checker stays green while
the render breaks.

So the declaration is compared with what supplies it, here, at run time. The
names are read out of the source rather than listed again, so a name added to a
shim is checked from the moment it is written -- there is no second list to keep
up to date.

:func:`declared_names` is the reusable half: a new shim gets a case of three
lines. ``tests/unit/test_basenodes_stub.py`` does the same job for the
*generated* declarations.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest


def declared_names(cls: type) -> set[str]:
    """The names ``cls`` declares inside its own ``if TYPE_CHECKING:`` block.

    Annotations (``image: Any``), stub methods (``def render(...) -> Any: ...``)
    and nested classes alike. Imports are skipped: bringing a name in for an
    annotation is the ordinary use of the block and says nothing about what the
    class needs of anything else.
    """
    source = textwrap.dedent(inspect.getsource(cls))
    definition = ast.parse(source).body[0]
    assert isinstance(definition, ast.ClassDef), cls
    found: set[str] = set()
    for statement in definition.body:
        if isinstance(statement, ast.If) and _is_type_checking(statement.test):
            found |= _members(statement)
    return found


def stand_in_names(module: object, name: str) -> set[str]:
    """What the stand-in class ``name`` declares in ``module``'s source.

    The other shape: a whole class written under ``if TYPE_CHECKING:`` at module
    level, with the real class bound to the same name in the ``else``. The class
    is the declaration, so everything in its body counts -- and it cannot be
    read off the runtime object, which is the real class and knows nothing of
    it.
    """
    tree = ast.parse(inspect.getsource(module))
    for statement in tree.body:
        if not isinstance(statement, ast.If) or not _is_type_checking(statement.test):
            continue
        for declared in statement.body:
            if isinstance(declared, ast.ClassDef) and declared.name == name:
                return _members(declared)
    raise AssertionError('%s declares no stand-in named %r'
                         % (getattr(module, '__name__', module), name))


def _members(definition: ast.stmt) -> set[str]:
    """Every name the body of ``definition`` binds, declared or defined."""
    found: set[str] = set()
    for statement in definition.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef)):
            found.add(statement.name)
        elif isinstance(statement, ast.AnnAssign) and isinstance(
                statement.target, ast.Name):
            found.add(statement.target.id)
    return found


def _is_type_checking(test: ast.expr) -> bool:
    """Whether this ``if`` is the ``TYPE_CHECKING`` one, however it is spelled."""
    if isinstance(test, ast.Name):
        return test.id == 'TYPE_CHECKING'
    if isinstance(test, ast.Attribute):
        return test.attr == 'TYPE_CHECKING'
    return False


def assert_supplied(declared: set[str], supplier: type, describing: str,
                    owned: frozenset[str] = frozenset()) -> None:
    """Every name in ``declared`` is on ``supplier``, or is ``owned``.

    ``owned`` names the attributes the declaring module sets on the object
    itself rather than finding there, which are as much part of the declaration
    and have no counterpart to be compared with.
    """
    missing = sorted(name for name in declared - owned
                     if not hasattr(supplier, name))
    assert not missing, (
        '%s declares %s, which %s does not supply'
        % (describing, ', '.join(missing), supplier.__name__))


### The reader itself
class _Sample:
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        import os                        # an import says nothing about a host
        declared_attribute: int

        def declared_method(self) -> None: ...

        class DeclaredClass:
            pass

    def a_real_method(self) -> None:
        """Not declared: defined."""


def test_every_kind_of_declaration_is_found():
    assert declared_names(_Sample) == {
        'declared_attribute', 'declared_method', 'DeclaredClass'}


def test_what_the_class_really_defines_is_not_a_declaration():
    assert 'a_real_method' not in declared_names(_Sample)


def test_a_class_that_declares_nothing_answers_nothing():
    class Plain:
        pass

    assert declared_names(Plain) == set()


def test_a_missing_name_is_reported_with_both_classes():
    class Supplier:
        pass

    with pytest.raises(AssertionError) as caught:
        assert_supplied(declared_names(_Sample), Supplier, '_Sample')
    assert 'declared_attribute' in str(caught.value)
    assert '_Sample' in str(caught.value) and 'Supplier' in str(caught.value)


def test_an_owned_name_needs_no_counterpart():
    class Supplier:
        declared_method = None
        DeclaredClass = None

    assert_supplied(declared_names(_Sample), Supplier, '_Sample',
                    owned=frozenset({'declared_attribute'}))


### The shims in the engine
def test_the_matrix_uniform_declares_what_its_class_has():
    """The pass binds each of its matrices through one of the uniform classes
    :mod:`OpenGLContext.scenegraph.shaders` builds at import, so a checker
    cannot see the class and the declaration stands in for it."""
    from OpenGLContext.passes import _flat
    from OpenGLContext.scenegraph import shaders

    # NEED_INVERSE is the pass's own: `_flat` sets it per instance to say which
    # way round this matrix is wanted, and no uniform class carries one.
    assert_supplied(stand_in_names(_flat, '_MatrixUniform'),
                    shaders.FloatUniformm4, '_flat._MatrixUniform',
                    owned=frozenset({'NEED_INVERSE'}))


def test_the_matrix_uniform_is_what_the_pass_actually_binds():
    """The declaration and the runtime class are two spellings of one name, and
    only this says they are still the same one."""
    from OpenGLContext.passes import _flat
    from OpenGLContext.scenegraph import shaders

    assert _flat._MatrixUniform is shaders.FloatUniformm4


@pytest.mark.parametrize('node_name', ['ImageTexture', 'PixelTexture'])
def test_the_texture_mixin_declares_fields_its_nodes_have(node_name):
    """``image``, ``repeatS`` and ``repeatT`` are VRML97 fields of the concrete
    texture nodes; declaring them on the mix-in for real would register a
    second copy of each."""
    from OpenGLContext.scenegraph import imagetexture

    assert_supplied(declared_names(imagetexture._Texture),
                    getattr(imagetexture, node_name), 'imagetexture._Texture')


def test_the_context_declares_what_the_event_mixin_supplies():
    """Every context a backend builds mixes :class:`EventHandlerMixin` in ahead
    of :class:`Context`, which is why these are declarations rather than
    do-nothing definitions."""
    from OpenGLContext.context import Context
    from OpenGLContext.events.eventhandlermixin import EventHandlerMixin

    assert_supplied(declared_names(Context), EventHandlerMixin, 'Context')
