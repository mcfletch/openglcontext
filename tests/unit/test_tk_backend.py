"""The Tk backend: what it asks its context for, and that it renders.

Tkinter ships with CPython, so this is the backend a project can reach for
without adding a GUI toolkit to its dependencies. The window is
`OpenGL.Tk.GLFrame` -- an ordinary `tkinter.Frame` with a GL context of its own
-- so what this backend has to get right is the translation from a
`ContextDefinition` to what that widget is asked for, and the window-level
capabilities every backend offers.

The translation needs no display and is tested outright; the rest runs in a
subprocess with a real X server, which is what Tk needs.

See `plans/BACKEND-PARITY.md`.
"""
import os
import subprocess
import sys

import pytest

from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.testing.paths import tests_root

pytest.importorskip('tkinter')

DRIVER = tests_root(__file__) / 'helpers' / '_tk_backend_drive.py'

needs_display = pytest.mark.skipif(
    not os.environ.get('DISPLAY', '').strip(),
    reason='Tk needs an X display; run under xvfb-run to exercise it')


def _asked(**named):
    from OpenGLContext.tkcontext import attributesFromDefinition

    return attributesFromDefinition(ContextDefinition(**named))


class TestWhatItAsksTheWidgetFor:
    def test_the_profile_is_passed_through(self):
        assert _asked(profile='core').profile == 'core'
        assert _asked(profile='compatibility').profile == 'compatibility'

    def test_the_version_is_passed_through(self):
        assert _asked(profile='core', version=(4, 1)).version == (4, 1)

    def test_a_version_of_zero_leaves_the_choice_to_the_driver(self):
        """Which is what the definition's own "nothing asked for" is."""
        assert _asked(version=(0, 0)).version is None

    def test_the_buffer_sizes_are_passed_through(self):
        asked = _asked(depthBuffer=16, stencilBuffer=8)
        assert asked.depthSize == 16
        assert asked.stencilSize == 8

    def test_a_buffer_nobody_asked_for_is_not_asked_for(self):
        """-1 is the definition's "don't ask", and a stencil buffer asked for
        as -1 bits is a request no driver matches."""
        assert _asked(stencilBuffer=-1).stencilSize == 0

    def test_a_depth_buffer_is_asked_for_by_default(self):
        """Anything with geometry in it needs one, and -1 means "don't ask"."""
        assert _asked(depthBuffer=-1).depthSize == 24

    def test_alpha_is_only_asked_for_when_wanted(self):
        """A compositor that honours destination alpha treats cleared pixels
        as transparent, so a window with an alpha channel shows what is behind
        it."""
        assert _asked(alpha=False).alphaSize == 0
        assert _asked(alpha=True).alphaSize == 8

    def test_multisampling_is_passed_through(self):
        assert _asked(multisampleSamples=4).samples == 4
        assert _asked(multisampleSamples=-1).samples == 0

    def test_double_buffering_follows_the_definition(self):
        assert _asked(doubleBuffer=True).doubleBuffer is True
        assert _asked(doubleBuffer=False).doubleBuffer is False

    def test_an_accumulation_buffer_is_reported_rather_than_ignored(self, caplog):
        """There is none to give: it is absent from a core profile, and a
        caller asking for one is asking for something this window will not
        have."""
        with caplog.at_level('WARNING'):
            _asked(accumulationBuffer=16)
        assert 'accumulation' in caplog.text.lower()

    def test_nothing_is_said_when_none_was_asked_for(self, caplog):
        with caplog.at_level('WARNING'):
            _asked(accumulationBuffer=-1)
        assert 'accumulation' not in caplog.text.lower()


class TestItIsRegistered:
    @pytest.mark.parametrize('kind', ['Context', 'InteractiveContext',
                                      'VRMLContext'])
    def test_the_name_resolves(self, kind):
        from OpenGLContext import plugins
        from OpenGLContext.context import Context

        found = Context.getContextType('tk', getattr(plugins, kind))
        assert found is not None and isinstance(found, type)


def _drive(*steps):
    """Run the driver for the named steps and return what it reported"""
    result = subprocess.run(
        [sys.executable, str(DRIVER)] + list(steps),
        capture_output=True, text=True, timeout=180,
    )
    assert 'DONE' in result.stdout, (
        'the Tk driver did not finish:\n%s\n%s'
        % (result.stdout, result.stderr))
    reported = {}
    for line in result.stdout.splitlines():
        head, _, tail = line.partition(' ')
        reported[head] = tail
    return reported


@needs_display
class TestARealWindow:
    def test_it_renders_the_frame_it_was_asked_for(self):
        reported = _drive('render')
        assert reported['DRAWN'] == 'True'
        assert reported['PIXEL'] == '64 128 191'

    def test_the_context_is_the_profile_the_definition_asked_for(self):
        assert _drive('profile')['CORE'] == 'True'

    def test_a_compatibility_definition_gets_the_old_pipeline(self):
        assert _drive('compatibility')['COMPATIBILITY'] == 'True'

    def test_the_viewport_follows_the_widget(self):
        assert _drive('resize')['VIEWPORT'] == '240 180'

    def test_hidden_takes_the_window_off_the_screen_and_still_renders(self):
        """A capture subprocess should not put a window over the display of
        whoever started it; the frame is read from the back buffer, which a
        withdrawn window still has."""
        reported = _drive('hidden')
        assert reported['MAPPED'] == 'False'
        assert reported['PIXEL'] == '64 128 191'

    def test_the_pointer_can_be_captured_for_mouse_look(self):
        assert _drive('capture')['CAPTURED'] == 'True'

    def test_a_window_can_be_asked_to_fill_the_screen_and_come_back(self):
        """Whether it *does* is the window manager's to decide, and a bare X
        server has none; what the backend owes is the request and an answer."""
        reported = _drive('fullscreen')
        assert reported['ASKEDFULL'] == 'True'
        assert reported['ASKEDBACK'] == 'True'
        assert reported['BACK'] == 'True'

    def test_quitting_releases_the_context(self):
        assert _drive('quit')['RELEASED'] == 'True'

    def test_a_context_can_sit_inside_somebody_elses_window(self):
        """Which is the reason to reach for Tk: a view beside an
        application's own controls."""
        reported = _drive('embedded')
        assert reported['PARENTED'] == 'True'
        assert reported['DRAWN'] == 'True'
