"""A collected test module does not configure the renderer as it is imported.

pytest imports every test module while it collects, long before it runs
anything, so a module-scope ``os.environ`` write lands in the environment the
whole session shares -- and in every child process the suite launches
afterwards. What ran is then decided by collection order, and a module that
renders under a profile of its own has quietly chosen it for everything.

That is not a hypothetical. Ten modules set ``PYOPENGL_PLATFORM='egl'`` this
way, each reasonably enough for its own context; on Windows, where there is no
EGL, the value reached all 161 scripts the suite launches and made every GL
entry point undefined, so 148 of them failed with ``NullFunctionError`` from
the first call and none of the tracebacks mentioned a variable.

What to do instead:

* the **PyOpenGL platform** and the **windowing backend** are settled once, for
  the run, from the machine -- :func:`OpenGLContext.testing.gl_env.settle_gl_platform`
  and :func:`~OpenGLContext.testing.gl_env.settle_gl_backend`, called by
  :mod:`OpenGLContext.testing.plugin` before anything imports ``OpenGL``;
* a test **about one kind of context** says so and is skipped where that kind
  cannot be had::

      @pytest.mark.gl_context(profile='compatibility')
      def test_the_old_pipeline_still_lights(...):

* anything else a single test needs goes on the same marker, or through
  ``monkeypatch.setenv``; both are put back afterwards.

The source of every module is held to this by OGC161 of
``openglcontext-checks`` (``oglc-check``, one of the gates of
``tools/preflight.py``), which reports an environment read or write at import
anywhere in the project except in the programs its ``script`` scope names: the
demos and drivers in ``tests/`` that run in a process of their own and
configure it as they start. What no reading of source can see is a module that
imports a program, which is what this module checks.
"""

from OpenGLContext.testing import plugin
from OpenGLContext.viewer.environment import VIEWER_DEFAULTS


def test_what_collection_changed_is_only_what_a_program_settled():
    """The other half of the rule, which no reading of a test module can check.

    A module that *imports a program* -- ``OpenGLContext.bin.view``,
    ``gltf_demo`` -- gets that program's choice of renderer where the program
    settles one as it loads, as the viewer does through
    :func:`~OpenGLContext.viewer.environment.viewer_defaults`. Nothing in the
    importing module's own source says so.

    The plugin puts the configuration back to what the run settled before any
    of that, so the choice reaches nothing, and records what it undid. This
    names what is still doing it, so the list is a decision rather than a
    surprise. Emptying it means moving those settings out of the programs'
    import and into their startup, or importing them through
    :func:`~OpenGLContext.testing.gl_env.import_unconfigured`.
    """

    #: What the viewer settles as it is imported.
    expected = set(VIEWER_DEFAULTS)
    unexpected = set(plugin.collection_changed()) - expected
    assert not unexpected, (
        'importing the test modules settled %s, which nothing here accounts '
        'for. A test module must not configure the renderer as it is imported '
        '-- see this module\'s docstring -- and a program it imports should be '
        'reached through gl_env.import_unconfigured.'
        % (', '.join(sorted(unexpected)),))
