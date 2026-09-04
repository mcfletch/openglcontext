"""The hidden window a test renders in, and the fixtures built on it.

:mod:`OpenGLContext.testing.glcontext` is what a test asks for a GL context
with, in this project and in one built on it, so what it promises is worth
holding to: the context is current when the body runs, the window is never
mapped, the sticky GLFW hints are reset before each one, and there is exactly
one way to find out that this machine cannot render at all.
"""
import pytest

from OpenGLContext.testing import glcontext
from OpenGLContext.testing.glcontext import (
    GLDescription,
    GLUnavailable,
    describe_gl,
    gl_available,
    hidden_window,
)


class TestAskingForAContextThatCannotBeGiven:
    """Every refusal is one exception with a reason in it."""

    def test_no_glfw_is_a_reason_rather_than_an_import_error(self, monkeypatch):
        import builtins
        real = builtins.__import__

        def refuse(name, *args, **named):
            if name == 'glfw':
                raise ImportError('no glfw here')
            return real(name, *args, **named)

        monkeypatch.setattr(builtins, '__import__', refuse)
        monkeypatch.delitem(__import__('sys').modules, 'glfw', raising=False)
        with pytest.raises(GLUnavailable, match='glfw'):
            with hidden_window('nope'):
                pass                                   # pragma: no cover - never runs

    def test_a_driver_that_will_not_initialise_says_so(self, monkeypatch):
        glfw = pytest.importorskip('glfw')
        monkeypatch.setattr(glfw, 'init', lambda: False)
        with pytest.raises(GLUnavailable, match='init'):
            with hidden_window('nope'):
                pass                                   # pragma: no cover - never runs

    def test_a_window_the_driver_refuses_says_the_size_and_the_profile(
            self, monkeypatch):
        glfw = pytest.importorskip('glfw')
        monkeypatch.setattr(glfw, 'create_window',
                            lambda *args, **named: None)
        with pytest.raises(GLUnavailable, match='32x24 core'):
            with hidden_window('nope', size=(32, 24)):
                pass                                   # pragma: no cover - never runs

    def test_a_profile_nobody_offers_is_a_programming_error(self):
        """Not a skip: a typo in a test's own arguments is not a machine that
        cannot render, and skipping it would hide the test forever."""
        with pytest.raises(ValueError, match='sideways'):
            with hidden_window('nope', profile='sideways'):
                pass                                   # pragma: no cover - never runs


class TestTheWindowItGives:
    def test_the_context_is_current_inside_the_block(self):
        from OpenGL.GL import GL_VERSION, glGetString
        try:
            with hidden_window('current'):
                assert glGetString(GL_VERSION) is not None
        except GLUnavailable as err:
            pytest.skip(str(err))

    def test_it_is_never_mapped(self):
        glfw = pytest.importorskip('glfw')
        try:
            with hidden_window('hidden') as window:
                assert not glfw.get_window_attrib(window, glfw.VISIBLE)
        except GLUnavailable as err:
            pytest.skip(str(err))

    def test_it_is_the_size_that_was_asked_for(self):
        glfw = pytest.importorskip('glfw')
        try:
            with hidden_window('sized', size=(96, 48)) as window:
                assert tuple(glfw.get_framebuffer_size(window)) == (96, 48)
        except GLUnavailable as err:
            pytest.skip(str(err))

    def test_a_hint_the_caller_names_reaches_the_window(self):
        """``hints`` is how a test asks for the one thing the arguments do not
        cover -- here a colour buffer with no alpha in it to read back."""
        from OpenGL.GL import (
            GL_BACK_LEFT,
            GL_FRAMEBUFFER,
            GL_FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE,
            glGetFramebufferAttachmentParameteriv,
        )
        try:
            with hidden_window('alpha', hints={'ALPHA_BITS': 0}):
                bits = glGetFramebufferAttachmentParameteriv(
                    GL_FRAMEBUFFER, GL_BACK_LEFT,
                    GL_FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE)
        except GLUnavailable as err:
            pytest.skip(str(err))
        assert int(bits) == 0

    def test_a_hint_one_window_asked_for_is_not_given_to_the_next(self):
        """GLFW hints are process-global and sticky, so without a reset the
        window a test gets is the one the *previous* test asked for."""
        from OpenGL.GL import (
            GL_BACK_LEFT,
            GL_FRAMEBUFFER,
            GL_FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE,
            glGetFramebufferAttachmentParameteriv,
        )
        try:
            with hidden_window('no-alpha', hints={'ALPHA_BITS': 0}):
                pass
            with hidden_window('plain'):
                bits = glGetFramebufferAttachmentParameteriv(
                    GL_FRAMEBUFFER, GL_BACK_LEFT,
                    GL_FRAMEBUFFER_ATTACHMENT_ALPHA_SIZE)
        except GLUnavailable as err:
            pytest.skip(str(err))
        assert int(bits) > 0

    def test_a_core_context_is_forward_compatible(self):
        """The same context :mod:`OpenGLContext.glfwcontext` opens for a real
        window, which asks for both together -- so a test exercises what ships
        rather than a context only a test ever gets. macOS gives no core context
        at all without it, and would skip every GL test in the suite instead."""
        from OpenGL.GL import (
            GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT,
            GL_CONTEXT_FLAGS,
            glGetIntegerv,
        )
        try:
            with hidden_window('forward'):
                flags = int(glGetIntegerv(GL_CONTEXT_FLAGS))
        except GLUnavailable as err:
            pytest.skip(str(err))
        assert flags & GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT

    def test_a_compatibility_context_is_not(self):
        """Forward-compatible means the deprecated entry points are gone, which
        is the whole of what a compatibility context is asked for."""
        from OpenGL.GL import (
            GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT,
            GL_CONTEXT_FLAGS,
            glGetIntegerv,
        )
        try:
            with hidden_window('compat', profile='compatibility'):
                flags = int(glGetIntegerv(GL_CONTEXT_FLAGS))
        except GLUnavailable as err:
            pytest.skip(str(err))
        assert not flags & GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT

    def test_a_core_context_follows_a_compatibility_one(self):
        """The GLFW hints are process-global and sticky, so a window asked for
        as core after one asked for as compatibility would inherit the profile
        rather than take the one it asked for."""
        from OpenGL.GL import GL_CONTEXT_PROFILE_MASK, glGetIntegerv
        from OpenGL.GL import GL_CONTEXT_CORE_PROFILE_BIT
        try:
            with hidden_window('compat-first', profile='compatibility'):
                pass
            with hidden_window('core-after'):
                mask = int(glGetIntegerv(GL_CONTEXT_PROFILE_MASK))
        except GLUnavailable as err:
            pytest.skip(str(err))
        assert mask & GL_CONTEXT_CORE_PROFILE_BIT


class TestWhetherThisMachineCanRenderAtAll:
    def test_it_is_worked_out_once(self, monkeypatch):
        """Every GL test module used to open a probe window of its own to
        decide whether to skip; the answer cannot change while the process
        lives, so it is asked for once."""
        monkeypatch.setattr(glcontext, '_DESCRIPTION', None)
        opened = []
        real = glcontext.hidden_window

        def counted(*args, **named):
            opened.append(args)
            return real(*args, **named)

        monkeypatch.setattr(glcontext, 'hidden_window', counted)
        first, second = gl_available(), gl_available()
        assert first is second
        assert len(opened) == 1

    def test_a_machine_with_no_gl_answers_no_rather_than_raising(
            self, monkeypatch):
        monkeypatch.setattr(glcontext, '_DESCRIPTION', None)

        def refuse(*args, **named):
            raise GLUnavailable('no GL here')

        monkeypatch.setattr(glcontext, 'hidden_window', refuse)
        assert gl_available() is False


class TestWhatTheRendererIs:
    """A CPU rasteriser draws the same picture as a GPU and takes a thousand
    times as long, so a test that measures speed has nothing to measure on one.
    :func:`describe_gl` is how the suite -- and a game's suite built on it --
    finds out which it has."""

    def _description(self, renderer):
        return GLDescription(vendor='Mesa', renderer=renderer, version='4.5')

    @pytest.mark.parametrize('renderer', [
        'llvmpipe (LLVM 20.1.2, 256 bits)',
        'softpipe',
        'kms_swrast',
        'SwiftShader Device (Subzero)',
        'Apple Software Renderer',
        'GDI Generic',
    ])
    def test_a_cpu_rasteriser_is_recognised(self, renderer):
        assert self._description(renderer).software

    @pytest.mark.parametrize('renderer', [
        'Radeon 8060S Graphics (radeonsi, gfx1151)',
        'NVIDIA GeForce RTX 3060 Ti/PCIe/SSE2',
        'Mesa Intel(R) Iris(R) Xe Graphics',
        'Apple M1 Pro',
    ])
    def test_a_gpu_is_not(self, renderer):
        assert not self._description(renderer).software

    def test_a_renderer_that_says_nothing_is_taken_for_a_gpu(self):
        """The safer answer: treating a GPU as software only skips tests that
        would have run, while the reverse asserts a speed nothing can reach."""
        assert not self._description('').software

    def test_it_names_the_renderer_it_describes(self):
        assert 'llvmpipe' in repr(self._description('llvmpipe (LLVM 20)'))

    def test_this_machine_is_described_or_reported_as_having_no_gl(self):
        description = describe_gl()
        if description is None:
            pytest.skip('no GL on this machine')
        assert description.renderer and description.version

    def test_it_is_worked_out_once(self, monkeypatch):
        """It costs a window, and the answer cannot change while the process
        lives."""
        monkeypatch.setattr(glcontext, '_DESCRIPTION', None)
        opened = []
        real = glcontext.hidden_window

        def counted(*args, **named):
            opened.append(args)
            return real(*args, **named)

        monkeypatch.setattr(glcontext, 'hidden_window', counted)
        first, second = describe_gl(), describe_gl()
        assert first is second
        assert len(opened) == 1

    def test_a_machine_with_no_gl_describes_nothing_rather_than_raising(
            self, monkeypatch):
        monkeypatch.setattr(glcontext, '_DESCRIPTION', None)

        def refuse(*args, **named):
            raise GLUnavailable('no GL here')

        monkeypatch.setattr(glcontext, 'hidden_window', refuse)
        assert describe_gl() is None

    def test_being_able_to_render_is_the_same_question(self, monkeypatch):
        """``gl_available`` and ``describe_gl`` must not disagree, and must not
        open two probe windows to answer the one question."""
        monkeypatch.setattr(glcontext, '_DESCRIPTION', None)
        assert gl_available() is (describe_gl() is not None)


class TestTheFixtures:
    """What a test in another project gets by turning the plugin on."""

    def test_gl_context_is_current(self, gl_context):
        from OpenGL.GL import GL_VERSION, glGetString
        assert glGetString(GL_VERSION) is not None

    def test_gl_window_makes_the_window_it_is_asked_for(self, gl_window):
        glfw = pytest.importorskip('glfw')
        window = gl_window('factory', size=(80, 40))
        assert tuple(glfw.get_framebuffer_size(window)) == (80, 40)

    def test_two_windows_can_be_alive_at_once(self, gl_window):
        """A resource cached against one context must not be handed to the
        next, and a test that proves it needs both windows at the same time."""
        first = gl_window('one')
        second = gl_window('two')
        assert first != second


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
