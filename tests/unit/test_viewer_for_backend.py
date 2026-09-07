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


class TestImportingDoesNotChooseAWindowSystem:
    """Naming one backend must not require another one to be installed.

    A bundle carrying only Tk, or a machine whose default backend's toolkit is
    missing, would otherwise be unable to ask for the backend it does have --
    the failure would come from resolving a default nobody asked for.

    In a subprocess, since the question is what an *import* does and this
    process has already done it.
    """

    def _run(self, script, **environment):
        import os
        import subprocess
        import sys

        return subprocess.run(
            [sys.executable, '-c', script],
            capture_output=True, text=True, timeout=180,
            env={**os.environ, **environment},
        )

    def test_importing_the_module_resolves_no_backend(self):
        result = self._run(
            'import OpenGLContext.viewer.sceneviewer as m; print("IMPORTED")',
            OPENGLCONTEXT_BACKEND='nonesuch')
        assert 'IMPORTED' in result.stdout, result.stderr

    def test_a_named_backend_is_had_without_the_default(self):
        result = self._run(
            'from OpenGLContext.viewer import viewerFor;'
            'print(viewerFor("tk").__name__)',
            OPENGLCONTEXT_BACKEND='nonesuch')
        assert 'TkViewerContext' in result.stdout, result.stderr

    def test_the_default_still_reports_what_it_could_not_resolve(self):
        """Lazily, but with the same message: a program that does want the
        default and cannot have it is owed the reason, at the point it asked."""
        result = self._run(
            'from OpenGLContext.viewer import ViewerContext',
            OPENGLCONTEXT_BACKEND='nonesuch')
        assert result.returncode != 0
        assert 'No InteractiveContext is available' in result.stderr
        assert 'tk' in result.stderr
