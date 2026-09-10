"""A widget's callback is handed *that* widget, and says so.

``MenuItem(on_activate=lambda w: self.show(w.checked))`` is how a menu is
written, and ``checked`` is a ``MenuItem``'s field rather than every widget's.
A callback declared as taking a ``Widget`` makes that line an error in every
program that writes it, and the answer a caller reaches for -- a cast, or
``getattr`` -- is worse than the line it replaces.

So the declaration is ``Callable[[Self], None]``, and this holds it there: the
concrete widget's own fields have to be readable from its callback, and a
callback that takes something else has to still be refused.

mypy reads the checkout rather than an installed copy (``MYPYPATH``), so the
gate is the same in a developer's editable environment as in a released one.
"""
import os
import subprocess
import sys
import textwrap

import pytest

from OpenGLContext.testing.paths import tests_root

ROOT = tests_root(__file__).parent

#: The scenegraph a widget is a node of. Its declarations have to be readable
#: or a widget inherits from `Any` and every attribute is allowed, which would
#: make the cases below pass without having compared anything. Named as a
#: sibling checkout, which is how a developer environment holds it; an
#: environment that installed it as a package needs nothing here.
SIBLINGS = [ROOT.parent / name for name in ('pyvrml97',)]


def search_path():
    return os.pathsep.join(
        [str(ROOT)] + [str(path) for path in SIBLINGS if path.is_dir()])


def check(source, tmp_path):
    """Run mypy over a snippet against the engine in this checkout."""
    path = tmp_path / 'snippet.py'
    path.write_text(textwrap.dedent(source), encoding='utf-8')
    completed = subprocess.run(
        [sys.executable, '-m', 'mypy', '--no-incremental',
         '--ignore-missing-imports', '--follow-imports', 'silent', str(path)],
        capture_output=True, text=True,
        env=dict(os.environ, MYPYPATH=search_path()),
        cwd=str(tmp_path),
    )
    if 'No module named mypy' in completed.stderr:
        pytest.skip('mypy is not installed in this environment')
    return completed.stdout + completed.stderr


@pytest.fixture(autouse=True)
def the_widget_types_are_readable(tmp_path):
    """Refuse to report a pass from an environment that sees no declarations.

    Every case here turns on what a checker knows a `MenuItem` to be. Where it
    cannot follow the scenegraph the widget derives from, it knows nothing,
    allows everything, and answers Success to all of them.
    """
    answer = check('''
        from OpenGLContext.ui.menu import MenuItem

        item = MenuItem(text='Contours')
        print(item.nosuchfield)
    ''', tmp_path)
    if 'nosuchfield' not in answer:
        pytest.skip(
            'this environment gives a checker no declarations to read for a '
            'widget, so these cases would pass without checking anything')


class TestACallbackReadsItsOwnWidget:
    def test_a_menu_items_check_is_readable_from_its_callback(self, tmp_path):
        answer = check('''
            from OpenGLContext.ui.menu import MenuItem

            item = MenuItem(text='Contours', checkable=True,
                            on_activate=lambda w: print(w.checked))
        ''', tmp_path)
        assert 'error:' not in answer, answer

    def test_a_sliders_value_is_readable_from_its_callback(self, tmp_path):
        answer = check('''
            from OpenGLContext.ui.widgets import Slider

            slider = Slider(on_change=lambda w: print(w.value))
        ''', tmp_path)
        assert 'error:' not in answer, answer

    def test_a_field_no_widget_has_is_still_refused(self, tmp_path):
        """The narrowing must not have turned the parameter into Any."""
        answer = check('''
            from OpenGLContext.ui.menu import MenuItem

            item = MenuItem(text='Contours',
                            on_activate=lambda w: print(w.nosuchfield))
        ''', tmp_path)
        assert 'error:' in answer, answer
        assert 'nosuchfield' in answer, answer

    def test_a_callback_taking_the_wrong_shape_is_refused(self, tmp_path):
        answer = check('''
            from OpenGLContext.ui.menu import MenuItem

            def two(first: int, second: int) -> None:
                pass

            item = MenuItem(text='Contours', on_activate=two)
        ''', tmp_path)
        assert 'error:' in answer, answer
