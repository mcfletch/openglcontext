"""Opening on the whole screen, and coming back off it.

A game is normally played full-screen and a tool normally is not, so the choice
belongs to the application rather than to whoever launches it: it is a
:class:`ContextDefinition` field, set by the program, defaulted from
``OPENGLCONTEXT_FULLSCREEN``, and offered on the settings screen so a player can
change their mind without a restart.

The one thing that outranks all of that is ``OPENGLCONTEXT_HIDDEN``.  A window
that is not meant to appear cannot be full-screen -- GLFW ignores the visibility
hint for a full-screen window, so a capture subprocess that honoured both would
take over the screen of whoever ran the suite.
"""

import pytest

from OpenGLContext import renderoptions
from OpenGLContext.context import Context
from OpenGLContext.contextdefinition import ContextDefinition


@pytest.fixture
def visible(monkeypatch):
    """A window that is meant to appear.

    The suite renders hidden (``tests/conftest.py``), and a hidden window is
    never full-screen -- so a case about filling the screen has to say that
    this one shows.
    """
    monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '0')


class TestTheField:
    """What a definition says about full-screen, and where it got it."""

    def test_a_context_is_windowed_unless_it_asks(self):
        assert not ContextDefinition().fullscreen

    def test_the_environment_settles_the_default(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_FULLSCREEN', '1')
        assert ContextDefinition().fullscreen

    def test_the_field_outranks_the_environment(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_FULLSCREEN', '1')
        assert not ContextDefinition(fullscreen=False).fullscreen

    def test_the_settings_screen_offers_it(self):
        assert 'fullscreen' in ContextDefinition.UI_HINTS
        assert 'fullscreen' in ContextDefinition.INTERFACE_FIELDS

    def test_a_capture_does_not_inherit_it(self, monkeypatch):
        """A subprocess that inherited it would open full-screen on a desktop."""
        monkeypatch.setenv('OPENGLCONTEXT_FULLSCREEN', '1')
        assert 'OPENGLCONTEXT_FULLSCREEN' not in renderoptions.clean_environment()


class TestReadingADefinitionDirectly:
    """``renderoptions`` answers about a definition it is handed.

    A backend applies the window-level settings while it is building the
    window, which is before there is a context to ask -- so the definition
    itself has to be an acceptable source, or every one of those settings falls
    back to its environment default and the field the application set is lost.
    """

    def test_a_definition_answers_for_itself(self):
        assert renderoptions.definition(ContextDefinition()) is not None

    def test_a_field_that_was_set_is_read(self):
        definition = ContextDefinition(vsync=False)
        assert renderoptions.flag(definition, 'vsync', True) is False

    def test_a_field_nobody_set_leaves_the_default(self):
        definition = ContextDefinition()
        assert renderoptions.flag(definition, 'vsync', False) is False
        assert renderoptions.flag(definition, 'vsync', True) is True


class TestTheQuestionEveryBackendAsks:
    """``renderoptions.fullscreen_window`` is the single reader.

    Each backend spells "fill the screen" differently -- a monitor handle, a
    display-mode flag, a method on a frame -- but none of them decides *whether*
    to, or they would drift apart on the one case that matters.
    """

    def test_a_definition_that_asks_gets_it(self, visible):
        assert renderoptions.fullscreen_window(
            ContextDefinition(fullscreen=True)) is True

    def test_a_definition_that_does_not_ask_does_not(self, visible):
        assert renderoptions.fullscreen_window(ContextDefinition()) is False

    def test_hidden_outranks_the_request(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1')
        assert renderoptions.fullscreen_window(
            ContextDefinition(fullscreen=True)) is False

    def test_the_environment_reaches_a_definition_nobody_configured(
            self, visible, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_FULLSCREEN', 'yes')
        assert renderoptions.fullscreen_window(ContextDefinition()) is True

    def test_a_context_is_an_acceptable_source(self, visible):
        class Windowed:
            contextDefinition = ContextDefinition(fullscreen=True)
        assert renderoptions.fullscreen_window(Windowed()) is True


class TestTheBackendCapability:
    """Switching a live window between full-screen and windowed."""

    def test_a_backend_that_cannot_says_so(self):
        """The base answer is False, so a caller can offer the key or not."""
        assert Context.setFullscreen(Context.__new__(Context), True) is False


glfw = pytest.importorskip('glfw')


class TestChoosingTheMonitor:
    """Which monitor GLFW is asked to fill, if any."""

    def _monitor(self, definition):
        from OpenGLContext import glfwcontext
        return glfwcontext.fullscreenMonitor(definition)

    def test_a_windowed_context_names_no_monitor(self):
        assert self._monitor(ContextDefinition()) is None

    def test_a_hidden_window_is_never_full_screen(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1')
        assert self._monitor(ContextDefinition(fullscreen=True)) is None

    def test_a_full_screen_context_names_one(self, visible):
        glfw.init()
        if not glfw.get_primary_monitor():
            pytest.skip('no monitor to fill')
        assert self._monitor(ContextDefinition(fullscreen=True)) is not None


class TestThePygameDisplayMode:
    """SDL takes it as a creation flag, so the definition has to reach it."""

    def _flags(self, definition):
        pygame = pytest.importorskip('pygame')
        pygame.display.init()
        from OpenGLContext.pygamecontext import PygameContext
        return PygameContext.pygameFlagsFromDefinition(definition)

    def test_a_windowed_context_asks_for_no_fullscreen_flag(self):
        import pygame
        assert not self._flags(ContextDefinition()) & pygame.FULLSCREEN

    def test_a_full_screen_context_asks_for_the_flag(self, visible):
        import pygame
        flags = self._flags(ContextDefinition(fullscreen=True))
        assert flags & pygame.FULLSCREEN
        assert flags & pygame.NOFRAME

    def test_a_hidden_window_keeps_the_desktop(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_HIDDEN', '1')
        import pygame
        flags = self._flags(ContextDefinition(fullscreen=True))
        assert not flags & pygame.FULLSCREEN
        assert flags & pygame.HIDDEN
