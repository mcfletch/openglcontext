"""Which GL a test run gets, and what a child process is told about it.

Two questions with one answer between them: the *configuration* -- which
context kind a program is given -- belongs to the run, and the
*infrastructure* -- the display, the driver, the paths -- belongs to the
machine. A child that inherits one test's configuration renders something
another test asked for, and a parent that settles the wrong platform for its
own OS renders nothing at all.

See :mod:`OpenGLContext.testing.gl_env`.
"""

import os

import pytest

from OpenGLContext.testing import gl_env


class TestThePlatformThisMachineWants:
    """``PYOPENGL_PLATFORM`` names which of PyOpenGL's platform modules loads,
    and each names a different library to find ``glViewport`` in. A run that
    picks one the OS does not have gets a ``NullFunctionError`` from the first
    GL call, which says nothing about the variable that caused it."""

    @pytest.mark.parametrize('platform,wanted', [
        ('linux', 'egl'),
        ('linux2', 'egl'),
        ('win32', None),
        ('cygwin', None),
        ('darwin', None),
        ('freebsd14', None),
    ])
    def test_each_os_gets_the_one_it_has(self, platform, wanted):
        """Linux is asked for EGL, which renders with no X display and is what
        a headless runner has. Everywhere else PyOpenGL's own default is the
        only right answer -- WGL on Windows, the framework on macOS -- and
        naming one would be naming the wrong one."""
        assert gl_env.gl_platform_for(platform) == wanted

    def test_it_is_settled_where_nothing_has_settled_it(self):
        environ = {}
        assert gl_env.settle_gl_platform(environ, 'linux') == 'egl'
        assert environ['PYOPENGL_PLATFORM'] == 'egl'

    def test_a_choice_already_made_is_left_alone(self):
        """A run that named a platform means it: `PYOPENGL_PLATFORM=osmesa` is
        how a machine with neither a display nor EGL renders at all."""
        environ = {'PYOPENGL_PLATFORM': 'osmesa'}
        assert gl_env.settle_gl_platform(environ, 'linux') == 'osmesa'
        assert environ['PYOPENGL_PLATFORM'] == 'osmesa'

    def test_an_os_with_no_answer_is_left_unset(self):
        """Rather than set to the empty string, which PyOpenGL would read as a
        platform named badly rather than as one not named."""
        environ = {}
        assert gl_env.settle_gl_platform(environ, 'win32') is None
        assert 'PYOPENGL_PLATFORM' not in environ


class TestTheBackendThisMachineWants:
    """Which windowing toolkit builds the context. Left unnamed, the engine
    takes the first backend registered, which is whichever package happens to
    be installed -- so two machines run different code and a suite is not
    reproducible. Named here, it is the first one that will actually import."""

    def test_the_preferred_one_is_taken_where_it_imports(self):
        environ = {}
        assert gl_env.settle_gl_backend(environ, available=lambda n: True) \
            == gl_env.GL_BACKENDS[0]
        assert environ['OPENGLCONTEXT_BACKEND'] == gl_env.GL_BACKENDS[0]

    def test_the_next_one_is_taken_where_it_does_not(self):
        """A machine without GLFW still has a suite to run."""
        environ = {}
        wanted = gl_env.GL_BACKENDS[1]
        assert gl_env.settle_gl_backend(
            environ, available=lambda n: n == wanted) == wanted

    def test_a_choice_already_made_is_left_alone(self):
        environ = {'OPENGLCONTEXT_BACKEND': 'glut'}
        assert gl_env.settle_gl_backend(environ, available=lambda n: True) == 'glut'
        assert environ['OPENGLCONTEXT_BACKEND'] == 'glut'

    def test_nothing_is_named_where_none_will_import(self):
        """Rather than pin one that cannot be built: the engine's own error
        names the backend and the package to install, and this would hide it
        behind a choice nobody made."""
        environ = {}
        assert gl_env.settle_gl_backend(environ, available=lambda n: False) is None
        assert 'OPENGLCONTEXT_BACKEND' not in environ


class TestWhatAChildIsTold:
    """A GL child is given the machine it runs on, the configuration the run
    settled, and what its caller names -- and nothing of what some other test
    happened to leave in the parent."""

    @pytest.fixture(autouse=True)
    def a_run_that_settled_nothing(self, monkeypatch):
        """These are about the rule, not about this session's own choices."""
        monkeypatch.setattr(gl_env, '_RUN', {})

    def test_no_configuration_reaches_it_unasked(self):
        """The defect this exists for: a test module that sets a rendering
        variable at import time changes the environment for the whole session,
        and a child launched afterwards renders under it."""
        parent = {
            'PATH': '/usr/bin',
            'OPENGLCONTEXT_PROFILE': 'compatibility',
            'OPENGLCONTEXT_SHADOWS': '0',
            'PYOPENGL_PLATFORM': 'egl',
            'PYOPENGL_ERROR_CHECKING': '0',
        }
        child = gl_env.gl_subprocess_env(parent)
        assert child['PATH'] == '/usr/bin'
        for name in ('OPENGLCONTEXT_PROFILE', 'OPENGLCONTEXT_SHADOWS',
                     'PYOPENGL_PLATFORM', 'PYOPENGL_ERROR_CHECKING'):
            assert name not in child, name

    def test_what_the_run_settled_does_reach_it(self):
        """The platform and backend chosen for this machine, and whatever the
        session was set up with: a child that renders needs all of it, and it
        is not one test's answer."""
        gl_env.settle_run({'OPENGLCONTEXT_HIDDEN': '1', 'PYOPENGL_PLATFORM': 'egl'})
        child = gl_env.gl_subprocess_env({'OPENGLCONTEXT_PROFILE': 'compatibility'})
        assert child['OPENGLCONTEXT_HIDDEN'] == '1'
        assert child['PYOPENGL_PLATFORM'] == 'egl'
        assert 'OPENGLCONTEXT_PROFILE' not in child

    def test_settling_answers_what_it_remembered(self):
        settled = gl_env.settle_run({'PATH': '/usr/bin', 'OPENGLCONTEXT_IBL': 'off'})
        assert settled == {'OPENGLCONTEXT_IBL': 'off'}
        assert gl_env.run_configuration() == settled

    def test_what_this_test_declared_reaches_it(self):
        """A test marked as being about one kind of context launches children
        that are about it too, without repeating itself at each call."""
        before = gl_env.asking({'OPENGLCONTEXT_PROFILE': 'compatibility'})
        try:
            child = gl_env.gl_subprocess_env({'PATH': '/usr/bin'})
            assert child['OPENGLCONTEXT_PROFILE'] == 'compatibility'
        finally:
            gl_env.asking(before)

    def test_asking_answers_what_was_there_before(self):
        gl_env.asking({'OPENGLCONTEXT_IBL': 'off'})
        assert gl_env.asking(None) == {'OPENGLCONTEXT_IBL': 'off'}
        assert gl_env.asked_configuration() == {}

    def test_what_the_caller_asks_for_does_reach_it(self):
        child = gl_env.gl_subprocess_env(
            {'PATH': '/usr/bin'}, OPENGLCONTEXT_PROFILE='core',
            OPENGLCONTEXT_AUTO_EXIT_FRAMES=4)
        assert child['OPENGLCONTEXT_PROFILE'] == 'core'
        assert child['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] == '4'

    def test_the_machine_reaches_it(self):
        """The display, the driver's own variables and the interpreter's paths
        are what the child needs to be the same machine as the parent."""
        parent = {'DISPLAY': ':0', 'XDG_RUNTIME_DIR': '/run/user/1000',
                  'LIBGL_ALWAYS_SOFTWARE': '1', 'MESA_LOADER_DRIVER_OVERRIDE': 'zink',
                  'PYTHONPATH': '/src', 'VIRTUAL_ENV': '/venv'}
        child = gl_env.gl_subprocess_env(parent)
        assert child == parent

    def test_nothing_else_comes_along(self):
        """An allow-list, so a variable nobody thought about is dropped rather
        than passed on."""
        child = gl_env.gl_subprocess_env({'SOME_TOOLS_CACHE': '/tmp/x'})
        assert child == {}


class TestImportingAProgramWithoutTakingItsChoices:
    """A program settles the renderer as it is imported, which is right for a
    program. A test that imports one to call a function of it must not take
    that settling for the whole session."""

    def test_what_it_settled_does_not_outlive_the_import(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)
        gl_env.import_unconfigured(
            'tests.unit.fixtures_a_program_that_configures')
        assert 'OPENGLCONTEXT_RENDERER' not in os.environ

    def test_what_the_run_already_had_is_still_there(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'chosen-by-the-run')
        gl_env.import_unconfigured(
            'tests.unit.fixtures_a_program_that_configures')
        assert os.environ['OPENGLCONTEXT_RENDERER'] == 'chosen-by-the-run'

    def test_the_module_is_answered(self):
        module = gl_env.import_unconfigured(
            'tests.unit.fixtures_a_program_that_configures')
        assert module.WHAT_IT_ASKED_FOR == 'pbr'


class TestTellingConfigurationFromInfrastructure:
    """One rule, so the child environment, the guard and the restore agree
    about what a test may leave behind."""

    @pytest.mark.parametrize('name', [
        'OPENGLCONTEXT_PROFILE', 'OPENGLCONTEXT_BACKEND', 'PYOPENGL_PLATFORM',
        'PYOPENGL_ERROR_CHECKING',
    ])
    def test_the_rendering_variables_are_configuration(self, name):
        assert gl_env.is_configuration(name)

    @pytest.mark.parametrize('name', [
        'PATH', 'DISPLAY', 'WAYLAND_DISPLAY', 'LIBGL_ALWAYS_SOFTWARE',
        'MESA_GL_VERSION_OVERRIDE', 'XDG_RUNTIME_DIR',
    ])
    def test_the_machine_variables_are_not(self, name):
        assert not gl_env.is_configuration(name)

    def test_it_is_the_engine_s_own_rule(self):
        """One question, one answer: a suite that disagreed with the engine
        about which variables decide a render would build children the
        engine's own tools would not."""
        from OpenGLContext import renderoptions

        assert gl_env.CONFIGURATION_PREFIXES is \
            renderoptions.CONFIGURATION_PREFIXES

    def test_everything_the_engine_reads_is_covered_by_it(self):
        """``renderoptions.ENVIRONMENT`` names what the engine reads; the rule
        has to cover all of it, or a variable would be dropped by one and kept
        by the other."""
        from OpenGLContext import renderoptions

        missed = [name for name in renderoptions.ENVIRONMENT
                  if not gl_env.is_configuration(name)]
        assert not missed, missed

    def test_the_configuration_in_an_environment_is_answered_whole(self):
        found = gl_env.configuration({
            'PATH': '/usr/bin', 'OPENGLCONTEXT_IBL': 'off',
            'PYOPENGL_PLATFORM': 'egl',
        })
        assert found == {'OPENGLCONTEXT_IBL': 'off', 'PYOPENGL_PLATFORM': 'egl'}
