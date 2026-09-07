"""Asking for the viewer over a named toolkit (`OpenGLContext.viewer.viewerFor`).

A program that puts a view inside its own window needs the viewer over *that*
toolkit, whatever backend the machine would otherwise choose.  Which is a
question about class composition, so it is answered without opening anything.

See `OpenGLContext/demos/`, which is what asks.
"""
import pytest

from OpenGLContext.ui.overlay import OverlayMixin
from OpenGLContext.viewer import viewerFor
from OpenGLContext.viewer.sceneviewer import SceneViewerMixin, ViewerContext


class TestWhatComesBack:
    def test_a_named_backend_gives_a_viewer_over_that_backend(self):
        from OpenGLContext.tkcontext import TkContext

        assert issubclass(viewerFor('tk'), TkContext)

    def test_it_is_a_viewer(self):
        found = viewerFor('tk')
        assert issubclass(found, SceneViewerMixin)

    def test_a_screen_that_is_up_takes_the_input_before_the_avatar_does(self):
        """Which is what the mixin order says, and the reason it is stated."""
        order = viewerFor('tk').__mro__
        assert order.index(OverlayMixin) < order.index(SceneViewerMixin)

    def test_naming_nothing_gives_whatever_the_machine_chose(self):
        assert viewerFor() is ViewerContext

    def test_asking_twice_gives_the_same_class(self):
        """A second window in the same program is the same kind of thing as
        the first, and `isinstance` should say so."""
        assert viewerFor('tk') is viewerFor('tk')


class TestWhenItCannot:
    def test_a_backend_nobody_registered_says_so(self):
        with pytest.raises(RuntimeError) as raised:
            viewerFor('nonesuch')
        assert 'nonesuch' in str(raised.value)

    def test_it_names_the_backends_there_are(self):
        with pytest.raises(RuntimeError) as raised:
            viewerFor('nonesuch')
        assert 'glfw' in str(raised.value)
