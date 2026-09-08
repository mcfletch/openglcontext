"""A collected test module does not configure the renderer as it is imported.

pytest imports every test module while it collects, long before it runs
anything, so a module-scope ``os.environ`` write lands in the environment the
whole session shares -- and in every child process the suite launches
afterwards. What ran is then decided by collection order, and a module that
renders under a profile of its own has quietly chosen it for everything.

That is not a hypothetical. Ten modules set ``PYOPENGL_PLATFORM='egl'`` this
way, each reasonably enough for its own context; on Windows, where there is no
EGL, the value reached all 161 scripts the suite launches and made every GL
entry point undefined, so 148 of them failed with ``NullFunctionError`` from
the first call and none of the tracebacks mentioned a variable.

What to do instead:

* the **PyOpenGL platform** and the **windowing backend** are settled once, for
  the run, from the machine -- :func:`OpenGLContext.testing.gl_env.settle_gl_platform`
  and :func:`~OpenGLContext.testing.gl_env.settle_gl_backend`, called by
  :mod:`OpenGLContext.testing.plugin` before anything imports ``OpenGL``;
* a test **about one kind of context** says so and is skipped where that kind
  cannot be had::

      @pytest.mark.gl_context(profile='compatibility')
      def test_the_old_pipeline_still_lights(...):

* anything else a single test needs goes on the same marker, or through
  ``monkeypatch.setenv``; both are put back afterwards.

A **script** in ``tests/`` is a program, not a collected module: it runs in a
process of its own and configures it at import, which is right and is why only
``test_*.py`` is examined here.
"""

import ast
import pathlib

import pytest

from OpenGLContext.testing import gl_env

#: The suite this rule covers: every module pytest imports during collection.
TESTS = pathlib.Path(__file__).resolve().parent.parent

#: ``conftest.py`` is not a test module. It configures the session on purpose,
#: it is imported before any test module, and what it sets is what the run puts
#: back after every test -- so it is where a session-wide setting belongs.
COLLECTED = sorted(
    path for path in TESTS.rglob('test_*.py')
    if '__pycache__' not in path.parts
)


def configuration_writes(source: str) -> list[tuple[str, int]]:
    """Writes to a configuration variable that happen on import: (name, line).

    Read from the syntax rather than by searching the text, so the two kinds of
    ``os.environ`` line this suite is full of are not mistaken for one that
    runs at import: one inside the source of a child process, held in a string,
    and one inside a function or a fixture, which runs when it is called and is
    where such a write belongs.

    A module-scope ``if``, ``try`` or ``with`` **is** descended into, since its
    body runs as the module is imported; a ``def`` is not.
    """
    found = []
    for node in _executed_on_import(ast.parse(source)):
        for name in _written_by(node):
            if name is None or gl_env.is_configuration(name):
                found.append((name or '<computed>', node.lineno))
    return found


def _executed_on_import(node: ast.AST):
    """Every node that runs while the module is being imported.

    Everything but the body of a function and the body of ``if __name__ ==
    '__main__'``: a class body runs, a conditional body runs, a ``def`` records
    itself and runs nothing, and the main block runs only when the file is
    started as a program -- which several of these are, and where configuring
    the renderer is exactly right.
    """
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(child, ast.If) and _is_main_guard(child.test):
            continue
        yield child
        yield from _executed_on_import(child)


def _is_main_guard(test: ast.AST) -> bool:
    """Whether ``test`` is the ``__name__ == '__main__'`` comparison."""
    return (isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == '__name__'
            and len(test.comparators) == 1
            and getattr(test.comparators[0], 'value', None) == '__main__')


def _written_by(node: ast.AST):
    """Every environment variable ``node`` writes, as names; None if computed."""
    if isinstance(node, ast.Assign):
        for target in node.targets:
            if _is_environ(getattr(target, 'value', None)):
                yield getattr(getattr(target, 'slice', None), 'value', None)
    elif isinstance(node, ast.Call):
        function = node.func
        if (isinstance(function, ast.Attribute)
                and _is_environ(function.value)
                and function.attr in ('setdefault', 'update', 'pop', '__setitem__')):
            if function.attr == 'update':
                for keyword in node.keywords:
                    yield keyword.arg
                for argument in node.args:
                    yield None if not isinstance(argument, ast.Dict) else None
            elif node.args:
                yield getattr(node.args[0], 'value', None)


def _is_environ(node: ast.AST | None) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == 'environ'


def test_there_are_modules_to_examine():
    """A rule nobody is held to is a rule that has stopped being checked."""
    assert len(COLLECTED) > 100, COLLECTED


def test_what_collection_changed_is_only_what_a_program_settled():
    """The other half of the rule, which no reading of a test module can check.

    A module that *imports a program* -- ``OpenGLContext.bin.terrain_view``,
    ``gltf_demo`` -- gets that program's choice of renderer, because a program
    settles one as it loads: it is about to draw. Nothing in the importing
    module's own source says so.

    The plugin puts the configuration back to what the run settled before any
    of that, so the choice reaches nothing, and records what it undid. This
    names what is still doing it, so the list is a decision rather than a
    surprise. Emptying it means moving those settings out of the programs'
    import and into their startup, or importing them through
    :func:`~OpenGLContext.testing.gl_env.import_unconfigured`.
    """
    from OpenGLContext.testing import plugin

    #: Programs whose import-time settings are known to be undone this way.
    expected = {
        'OPENGLCONTEXT_RENDERER', 'OPENGLCONTEXT_SHADOWS',
        'OPENGLCONTEXT_SHADOW_CASCADES', 'OPENGLCONTEXT_IBL',
        'OPENGLCONTEXT_IBL_INTENSITY', 'OPENGLCONTEXT_ENV_CUBEMAP',
        'OPENGLCONTEXT_BACKEND',
    }
    unexpected = set(plugin.collection_changed()) - expected
    assert not unexpected, (
        'importing the test modules settled %s, which nothing here accounts '
        'for. A test module must not configure the renderer as it is imported '
        '-- see this module\'s docstring -- and a program it imports should be '
        'reached through gl_env.import_unconfigured.'
        % (', '.join(sorted(unexpected)),))


@pytest.mark.parametrize('path', COLLECTED, ids=lambda p: p.name)
def test_it_sets_no_configuration_as_it_is_imported(path):
    written = configuration_writes(path.read_text(encoding='utf-8'))
    assert not written, (
        '%s writes %s at module scope, which happens while pytest is still '
        'collecting and so decides what every later test renders. See this '
        "module's own docstring for where each of them belongs instead."
        % (path.name,
           ', '.join('%s (line %d)' % (name, line) for name, line in written)))
