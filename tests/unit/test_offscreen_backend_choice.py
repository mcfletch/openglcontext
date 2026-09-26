"""Which backend renders with no window, on whichever machine is asking.

A batch renderer, a build machine or a service returning images wants a context
and no window.  Two backends provide one -- a WGL pbuffer on Windows, EGL
elsewhere -- and both are registered everywhere, so a caller that named one
directly would be naming the wrong one half the time.
:meth:`OpenGLContext.contextconfig.ContextConfigMixin.getOffscreenContextType`
is the question asked instead.

The mapping is pure, so every platform's answer is checked here whatever this
one is.  Loading the class needs the bindings behind it and so answers for this
machine only.
"""

import sys

import pytest

from OpenGLContext import windowsystem
from OpenGLContext.context import Context


class TestTheNameIsChosenByPlatform:
    @pytest.mark.parametrize('platform', ['win32', 'cygwin'])
    def test_windows_renders_on_a_pbuffer(self, platform):
        assert Context.getOffscreenBackendName(platform) == 'wgl'

    @pytest.mark.parametrize('platform', ['linux', 'freebsd14', 'darwin'])
    def test_everywhere_else_renders_on_egl(self, platform):
        """Including macOS, which has no backend of its own yet: EGL is what
        it would be asked for, and answering None there is the loader's job
        rather than the mapping's."""
        assert Context.getOffscreenBackendName(platform) == 'egl'

    def test_this_machine_is_asked_by_default(self):
        assert (Context.getOffscreenBackendName()
                == Context.getOffscreenBackendName(sys.platform))


class TestLoadingTheClass:
    def test_it_is_a_context_or_nothing(self):
        """Nothing loadable is an answer -- an EGL with no library behind it
        says the same thing as a platform with no backend at all."""
        offscreen = Context.getOffscreenContextType()
        if offscreen is None:
            pytest.skip('nothing here renders without a window')
        assert issubclass(offscreen, Context)

    def test_a_platform_with_no_bindings_answers_nothing(self):
        """Asked about a machine this is not, the class cannot be loaded and
        None is what comes back rather than an ImportError from the import."""
        other = 'linux' if sys.platform.startswith('win32') else 'win32'
        loaded = Context.getOffscreenContextType(other)
        assert loaded is None or issubclass(loaded, Context)


class TestAskingForOffscreenByName:
    """``windowsystem='offscreen'`` in a definition is the same question, asked
    of the window-system registry as the context is built."""

    @pytest.mark.parametrize('platform, expected', [
        ('win32', 'wgl'), ('cygwin', 'wgl'), ('linux', 'egl'), ('darwin', 'egl'),
    ])
    def test_it_names_the_platforms_windowless_system(self, platform, expected):
        chosen = windowsystem.choose(
            'offscreen', platform=platform,
            registered=('glfw', 'egl', 'wgl'), probe=lambda _name: None)
        assert chosen == expected
        assert chosen == Context.getOffscreenBackendName(platform)

    def test_an_empty_request_never_falls_back_to_it(self):
        """A program that asked for nothing in particular is asking for a
        window, so a machine with only the windowless systems says so."""
        with pytest.raises(windowsystem.WindowSystemUnavailable):
            windowsystem.choose(
                '', registered=('egl', 'wgl'), probe=lambda _name: None)
