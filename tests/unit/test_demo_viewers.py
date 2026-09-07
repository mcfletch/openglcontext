"""The embedding demos: a view as one widget in somebody else's window.

The demos in :mod:`OpenGLContext.demos` are read as much as run, which is a
reason to hold them to the suite rather than an excuse not to: a sample that
has stopped working teaches the wrong thing to everybody who copies it.

The parts that need no window are tested outright.  The rest runs in a
subprocess with a real X server and a real GL context, one process per step,
because a Tk application is a process with one interpreter in it.

wx is not here: wxPython will not build in this container, and its demo says so
in its own docstring.  Qt's is in ``openglcontext-qt/tests/``.

See `plans/EMBEDDING-EXAMPLES.md`.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root

pytest.importorskip('tkinter')

DRIVER = tests_root(__file__) / 'helpers' / '_tk_viewer_drive.py'

needs_display = pytest.mark.skipif(
    not os.environ.get('DISPLAY', '').strip(),
    reason='Tk needs an X display; run under xvfb-run to exercise it')


def _drive(*steps):
    """Run the driver for the named steps and return what it reported"""
    result = subprocess.run(
        [sys.executable, str(DRIVER)] + list(steps),
        capture_output=True, text=True, timeout=600,
    )
    assert 'DONE' in result.stdout, (
        'the Tk viewer driver did not finish:\n%s\n%s'
        % (result.stdout, result.stderr))
    reported = {}
    for line in result.stdout.splitlines():
        head, _, tail = line.partition(' ')
        reported[head] = tail
    return reported


class TestTheRowIds:
    """Which outline row a tree item stands for, which needs no window."""

    def test_a_path_survives_the_round_trip(self):
        from OpenGLContext.demos.tk_viewer import pathOf, rowId

        for path in ((), (0,), (3, 1, 4)):
            assert pathOf(rowId(path)) == path

    def test_an_item_that_is_not_a_row_stands_for_no_path(self):
        """The placeholder under a closed row, and Tk's own "nothing"."""
        from OpenGLContext.demos.tk_viewer import pathOf

        assert pathOf('') is None
        assert pathOf('I001') is None


@needs_display
class TestTheTkDemo:
    def test_the_loaded_scene_reaches_the_tree(self):
        reported = _drive('tree')
        assert reported['LOADED'] == 'True'
        assert int(reported['ROWS']) > 1
        assert reported['HASROOT'] == 'True'
        assert reported['MATCHES'] == 'True', (
            'the tree should show the outline row for row')

    def test_opening_a_row_opens_it_in_the_model(self):
        reported = _drive('expanding')
        assert reported['EXPANDED'] == 'True'
        assert reported['GREW'] == 'True'
        assert reported['COLLAPSED'] == 'True'
        assert reported['BACK'] == 'True'

    def test_selecting_a_row_names_a_node_and_follows_it(self):
        reported = _drive('selecting')
        assert reported['SELECTED'] == 'True'
        assert reported['WATCHING'] == 'True'
        assert reported['DETAIL']

    def test_a_change_to_the_watched_node_reaches_the_panel(self):
        """Which is what pydispatcher is doing in there: the panel and the
        tree both follow the scene rather than being redrawn on a guess."""
        reported = _drive('watching')
        assert reported['TOLD'] == 'True'
        assert reported['RENAMED'] == 'True'

    def test_the_menu_opens_a_scene_through_the_engine(self):
        reported = _drive('opening')
        assert reported['EMPTY'] == 'True'
        assert reported['OPENED'] == 'True'
        assert reported['LOADED'] == 'True'
        assert reported['STATUS'] == 'instanced_lattice.gltf'

    def test_quitting_releases_the_context_and_the_window(self):
        reported = _drive('quitting')
        assert reported['RELEASED'] == 'True'
        assert reported['WATCHING'] == 'True'
        assert reported['OUTLINE'] == 'True'
        assert reported['WINDOW'] == 'True'

    def test_a_view_that_finishes_takes_the_host_window_with_it(self):
        """A view inside somebody else's window never ends their process, so
        the host is the one that decides; here the view is why the window is
        there."""
        assert _drive('viewfinished')['WINDOW'] == 'True'
