"""The screen is drawn whichever way the world was.

``renderShaderOverlay`` is how the HUD, the developer overlay and any open panel
reach the frame, and it was asked for from **one** of the render pass's paths:
the core/shader one.  So a context in the compatibility profile drew no HUD, no
developer overlay and no panels at all -- which is a viewer whose menu cannot be
seen.

The overlay renderer builds its own program and does not care which path drew
the world below it, so the hook belongs to the *frame* rather than to one way of
filling one.  Both passes have their own ``Render``, so both are checked.
"""
import inspect

import pytest

from OpenGLContext.passes import _flat, flatcompat


def _render_of(module):
    return inspect.getsource(module.FlatPass.Render)


PASSES = pytest.mark.parametrize('module, name', [
    (_flat, 'the core/shader pass'),
    (flatcompat, 'the compatibility pass'),
])


class TestTheOverlayHook:
    @PASSES
    def test_the_frame_asks_for_it(self, module, name):
        assert 'renderShaderOverlay' in _render_of(module), name

    @PASSES
    def test_it_is_asked_for_once_per_frame(self, module, name):
        """Once per frame, not once per rendering path."""
        assert _render_of(module).count('renderShaderOverlay') == 1, name

    @PASSES
    def test_it_happens_before_the_frame_is_presented(self, module, name):
        """Drawn after the swap is drawn into the frame nobody sees."""
        source = _render_of(module)
        assert source.index('renderShaderOverlay') < source.index('presentFrame'), name

    def test_the_core_pass_asks_outside_its_shader_branch(self):
        """Inside it, the legacy path silently draws no screen at all."""
        source = _render_of(_flat)
        assert (source.index('renderShaderOverlay')
                > source.index('Legacy fixed-function rendering path'))

    @PASSES
    def test_a_context_with_no_screen_is_not_an_error(self, module, name):
        """A plain Context has no ScreenMixin; it simply draws no overlay."""
        assert 'getattr(context, \'renderShaderOverlay\', None)' in _render_of(module)
