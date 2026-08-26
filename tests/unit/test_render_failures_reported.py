"""A scene whose geometry raises says so once, and again as the run ends.

The pure bookkeeping is covered in ``test_render_failures``.  This is the wiring:
that the render passes route their caught exceptions through it, that a node
failing on every frame produces one traceback rather than one per frame, and that
the run's summary reaches the log a person will actually see.
"""
import os

os.environ.setdefault('PYOPENGL_PLATFORM', 'egl')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import logging  # noqa: E402

import pytest  # noqa: E402

pytest.importorskip("glfw")

from OpenGLContext.scenegraph import basenodes  # noqa: E402

pytest_plugins = ['tests.unit.test_passes_render_gl']


class _Exploding(basenodes.Box):
    """A geometry node that cannot draw, which is the case being reported."""

    def render(self, *args, **named):
        raise RuntimeError('this geometry cannot draw')


def failing_scene():
    return [
        basenodes.Shape(geometry=_Exploding(size=(2, 2, 2)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(1, 0, 0)))),
        basenodes.PointLight(location=(0, 5, 5), intensity=1.0),
    ]


@pytest.fixture(autouse=True)
def shader_paths(monkeypatch):
    from tests.unit.test_passes_render_gl import _base_env
    _base_env(monkeypatch)


class TestTheFailureIsRecordedAndCountedOnce:
    def test_the_pass_holds_the_cause_it_could_not_draw(self, render_scene):
        from OpenGLContext.passes import renderpass
        render_scene(failing_scene(), frames=4)
        summary = renderpass.FLAT.failures.summary()
        assert len(summary) == 1
        assert 'this geometry cannot draw' in summary[0].description

    def test_a_node_failing_every_frame_is_logged_once(self, render_scene, caplog):
        with caplog.at_level(logging.ERROR, logger='OpenGLContext.passes._flat'):
            render_scene(failing_scene(), frames=4)
        tracebacks = [record for record in caplog.records
                      if 'this geometry cannot draw' in record.getMessage()]
        assert len(tracebacks) == 1

    def test_a_scene_that_draws_records_nothing(self, render_scene):
        from OpenGLContext.passes import renderpass
        render_scene([
            basenodes.Shape(geometry=basenodes.Box(size=(2, 2, 2)),
                            appearance=basenodes.Appearance(
                                material=basenodes.Material())),
            basenodes.PointLight(location=(0, 5, 5), intensity=1.0),
        ], frames=2)
        assert renderpass.FLAT.failures.summary() == []


class TestTheRunSaysWhatNeverDrew:
    def test_reporting_names_the_failure(self, render_scene, caplog):
        from OpenGLContext.passes import renderpass
        render_scene(failing_scene(), frames=2)
        caplog.clear()
        with caplog.at_level(logging.WARNING):
            renderpass.report_render_failures()
        assert 'this geometry cannot draw' in caplog.text

    def test_reporting_with_no_pass_at_all_is_quiet(self, monkeypatch, caplog):
        from OpenGLContext.passes import renderpass
        monkeypatch.setattr(renderpass, 'FLAT', None)
        with caplog.at_level(logging.DEBUG):
            renderpass.report_render_failures()
        assert caplog.text == ''

    def test_quitting_reports(self, render_scene, monkeypatch):
        """``OnQuit`` calls ``os._exit``, so the report has to happen before it."""
        from OpenGLContext.passes import renderpass
        rendered = render_scene(failing_scene(), frames=2)
        reported = []
        monkeypatch.setattr(renderpass, 'report_render_failures',
                            lambda: reported.append(True))
        monkeypatch.setattr(os, '_exit', lambda code: None)
        rendered.context.OnQuit()
        assert reported == [True]
