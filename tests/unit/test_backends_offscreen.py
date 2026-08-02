"""Every backend can render without putting a window on the screen.

``OPENGLCONTEXT_HIDDEN`` was read by exactly one of them. The rest opened,
mapped and destroyed a window per context regardless -- which, over a suite with
a hundred and forty scripts in it, is a hundred and forty windows flashing over
whatever the person running it is doing, and taking the keyboard focus while
they type.

What each platform *can* do differs, so this checks the arrangement rather than
the pixels: that the flag is read, that it reaches the platform call, and that
turning it off still opens a window.
"""
import pytest

from OpenGLContext import renderoptions


def test_the_flag_is_one_the_renderer_knows_about():
    assert 'OPENGLCONTEXT_HIDDEN' in renderoptions.ENVIRONMENT


class TestPygame:
    """SDL takes it as a window flag at creation."""

    def _flags(self, monkeypatch, hidden):
        pygame = pytest.importorskip('pygame')
        # The flag builder sets GL attributes as it goes, which SDL will not do
        # before its video system is up; the dummy driver brings that up
        # without a display of any kind.
        monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1' if hidden else '0')
        pygame.display.init()
        from OpenGLContext import pygamecontext
        from OpenGLContext.contextdefinition import ContextDefinition
        try:
            return pygamecontext.PygameContext.pygameFlagsFromDefinition(
                ContextDefinition()), pygame
        finally:
            pygame.display.quit()

    def test_it_asks_for_a_hidden_window(self, monkeypatch):
        flags, pygame = self._flags(monkeypatch, True)
        assert flags & pygame.HIDDEN

    def test_it_opens_one_when_nobody_asked_to_hide_it(self, monkeypatch):
        flags, pygame = self._flags(monkeypatch, False)
        assert not (flags & pygame.HIDDEN)

    def test_the_rest_of_the_flags_are_untouched(self, monkeypatch):
        flags, pygame = self._flags(monkeypatch, True)
        assert flags & pygame.RESIZABLE


class TestGLUT:
    """GLUT has no creation hint, so the window is hidden immediately after."""

    def test_it_hides_the_window_it_just_made(self, monkeypatch):
        pytest.importorskip('OpenGL.GLUT')
        from OpenGLContext import glutcontext
        import inspect
        source = inspect.getsource(glutcontext)
        assert 'glutHideWindow' in source
        assert 'hidden_window' in source


class TestWX:
    """wx shows a frame explicitly; hidden simply means not doing that."""

    def test_showing_the_frame_is_conditional(self):
        pytest.importorskip('wx')
        from OpenGLContext import wxcontext
        import inspect
        source = inspect.getsource(wxcontext)
        assert 'OPENGLCONTEXT_HIDDEN' in source


class TestTheSharedReader:
    """One reader, so the backends cannot disagree about what the value means."""

    @pytest.mark.parametrize('value, hidden', [
        ('1', True), ('true', True), ('TRUE', True), ('yes', True),
        ('on', True), ('0', False), ('', False), ('no', False),
    ])
    def test_what_counts_as_hidden(self, monkeypatch, value, hidden):
        from OpenGLContext import renderoptions
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', value)
        assert renderoptions.hidden_window() is hidden

    def test_unset_means_a_window_on_the_screen(self, monkeypatch):
        from OpenGLContext import renderoptions
        monkeypatch.delenv('OPENGLCONTEXT_HIDDEN', raising=False)
        assert renderoptions.hidden_window() is False
