"""Asking for the viewer over a named toolkit (`OpenGLContext.viewer.viewerFor`).

A program that puts a view inside its own window needs the viewer over *that*
toolkit, whatever backend the machine would otherwise choose.  Which is a
question about class composition, so it is answered without opening anything.

See `OpenGLContext/demos/`, which is what asks.
"""
import pytest

from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
from OpenGLContext.multiview.mixin import MultiViewMixin
from OpenGLContext.ui.overlay import OverlayStackMixin
from OpenGLContext.viewer import viewerFor
from OpenGLContext.viewer.sceneviewer import SceneViewerMixin, ViewerContext


class TestWhatComesBack:
    def test_a_named_backend_gives_a_viewer_over_that_backend(self):
        found = viewerFor('tk')
        assert found.windowSystemName == 'tk'
        assert found.resolveDefinition().windowsystem == 'tk'

    def test_it_is_a_viewer(self):
        found = viewerFor('tk')
        assert issubclass(found, SceneViewerMixin)

    def test_a_screen_that_is_up_takes_the_input_before_the_avatar_does(self):
        """The overlay comes ahead of the views and the navigation that move
        the camera, which is the order ``Context`` gives its bases."""
        order = viewerFor('tk').__mro__
        assert order.index(OverlayStackMixin) < order.index(MultiViewMixin) \
            < order.index(ViewPlatformMixin)

    def test_naming_nothing_gives_whatever_the_machine_chose(self):
        assert viewerFor() is ViewerContext

    def test_asking_twice_gives_the_same_class(self):
        """A second window in the same program is the same kind of thing as
        the first, and `isinstance` should say so."""
        assert viewerFor('tk') is viewerFor('tk')


def iblIntensity(definition):
    """The ambient scale the pass draws with, read the way the pass reads it."""
    from OpenGLContext import renderoptions

    return renderoptions.number(
        definition, 'iblIntensity',
        renderoptions.env_number('OPENGLCONTEXT_IBL_INTENSITY', 1.0))


class TestAnEmbeddedViewLooksLikeOglcView:
    """A view inside somebody else's window draws a model as ``oglc-view`` does.

    The program embedding it has no command line to set the renderer up, so
    whatever the viewer needs of the renderer is declared by the viewer class.
    """

    @pytest.fixture(autouse=True)
    def unpinned(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_IBL_INTENSITY', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_SHADOWS', raising=False)

    def test_it_draws_with_the_metallic_roughness_pass(self):
        assert viewerFor('tk').renderer == 'pbr'

    def test_the_ambient_is_held_back_so_the_sun_reads(self):
        from OpenGLContext.viewer.environment import VIEWER_IBL_INTENSITY

        definition = viewerFor('tk').resolveDefinition()
        assert iblIntensity(definition) == pytest.approx(VIEWER_IBL_INTENSITY)
        assert VIEWER_IBL_INTENSITY < 1.0

    def test_the_environment_still_pins_it(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_IBL_INTENSITY', '0.7')
        definition = viewerFor('tk').resolveDefinition()
        assert iblIntensity(definition) == pytest.approx(0.7)

    def test_the_options_choose_it(self):
        from OpenGLContext import renderoptions
        from OpenGLContext.viewer.options import ViewerOptions

        class Chosen(viewerFor('tk')):
            options = ViewerOptions(ibl_intensity=0.2, shadows=False)

        definition = Chosen.resolveDefinition()
        assert iblIntensity(definition) == pytest.approx(0.2)
        assert renderoptions.flag(definition, 'shadows', True) is False

    def test_a_definition_passed_in_outranks_the_viewer(self):
        definition = viewerFor('tk').resolveDefinition({'iblIntensity': 0.9})
        assert iblIntensity(definition) == pytest.approx(0.9)


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

    def test_the_default_reports_what_it_could_not_resolve(self):
        """A program that does want the default and cannot have it is owed the
        reason, at the point it asked: choosing the window system to open."""
        result = self._run(
            'from OpenGLContext.viewer import ViewerContext\n'
            'print("IMPORTED", flush=True)\n'
            'ViewerContext.chooseWindowSystem(ViewerContext.resolveDefinition())',
            OPENGLCONTEXT_BACKEND='nonesuch')
        assert 'IMPORTED' in result.stdout, result.stderr
        assert result.returncode != 0
        assert 'WindowSystemUnavailable' in result.stderr
        assert 'nonesuch' in result.stderr
        assert 'tk' in result.stderr
