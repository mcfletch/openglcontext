"""The context a test gets where there is no window server: macOS, headless.

GLFW asks macOS for an accelerated pixel format and nothing else, so on a
machine with no accelerated renderer -- a virtual machine, a CI runner, a
session nobody is logged into -- it can create no context at all. CGL is the
layer underneath it and will, so :func:`hidden_window` falls back to that and
the suite runs there instead of skipping its way to green.

What the fallback has to decide is pure and is checked here: which CGL profile
serves a request, and which of a caller's GLFW hints carry across. Making the
context is one call with those answers, and needs a Mac.
"""
import pytest

from OpenGLContext.testing import glcontext
from OpenGLContext.testing.glcontext import GLUnavailable


class TestWhichProfileServesTheRequest:
    """macOS has a legacy 2.1 profile, a 3.2 core one and a 4.1 core one, and
    no compatibility profile above 2.1 at all."""

    def test_the_default_core_request_is_the_3_2_profile(self):
        """``hidden_window`` asks for core 3.3, which is what every shader in
        the package is written against."""
        assert glcontext.cgl_profile_for('core', (3, 3)) == 'core3'

    @pytest.mark.parametrize('version', [(4, 1), (4, 5)])
    def test_a_higher_core_request_is_the_4_1_profile(self, version):
        assert glcontext.cgl_profile_for('core', version) == 'core4'

    def test_any_profile_is_the_legacy_one(self):
        """'any' means a test wants only *a* context, and the legacy profile is
        the one macOS gives without being asked."""
        assert glcontext.cgl_profile_for('any', (3, 3)) == 'legacy'

    def test_compatibility_is_refused_rather_than_quietly_downgraded(self):
        """A test asking for the fixed-function pipeline at 3.3 would pass
        against a 2.1 context having exercised something else."""
        with pytest.raises(GLUnavailable, match='compatibility'):
            glcontext.cgl_profile_for('compatibility', (3, 3))

    def test_a_core_profile_below_3_2_is_refused(self):
        with pytest.raises(GLUnavailable, match='3.2'):
            glcontext.cgl_profile_for('core', (2, 1))


class TestWhichHintsCarryAcross:
    """A GLFW hint names a buffer; CGL takes the same buffers by another name.
    A hint that means nothing to CGL is refused rather than dropped, since a
    test that asked for something and did not get it is a test that passed for
    the wrong reason."""

    def test_no_hints_is_no_change(self):
        assert glcontext.cgl_buffer_sizes(None) == {}

    def test_the_alpha_hint_becomes_the_alpha_size(self):
        assert glcontext.cgl_buffer_sizes({'ALPHA_BITS': 0}) == {'alpha_size': 0}

    def test_depth_and_stencil_carry_too(self):
        assert glcontext.cgl_buffer_sizes({'DEPTH_BITS': 16, 'STENCIL_BITS': 0}) == {
            'depth_size': 16, 'stencil_size': 0,
        }

    def test_a_hint_cgl_has_no_answer_for_is_refused(self):
        with pytest.raises(GLUnavailable, match='RESIZABLE'):
            glcontext.cgl_buffer_sizes({'RESIZABLE': 1})


#: What made the context, as :func:`glcontext.backend` reports it: a hidden
#: GLFW window, a CGL context where GLFW could make none, or the platform's
#: windowless surface where the suite was asked for no window at all.
BACKENDS = ('glfw', 'cgl', 'offscreen')


class TestTheBackendSaysWhichItIs:
    def test_it_names_one_of_them(self):
        assert glcontext.backend() in BACKENDS + (None,)

    def test_a_machine_that_can_render_has_one(self):
        if not glcontext.gl_available():
            pytest.skip('no GL on this machine')
        assert glcontext.backend() in BACKENDS


class TestTheSizeIsReadableWhicheverBackendItIs:
    """A test that wants to know how big its framebuffer is should not have to
    know what made it."""

    def test_it_is_the_size_that_was_asked_for(self):
        try:
            with glcontext.hidden_window('sized', size=(96, 48)) as window:
                assert glcontext.framebuffer_size(window) == (96, 48)
        except GLUnavailable as err:
            pytest.skip(str(err))
