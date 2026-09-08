"""A scene whose geometry raises says so once, and again as the run ends.

The pure bookkeeping is covered in ``test_render_failures``.  This is the wiring:
that the render passes route their caught exceptions through it, that a node
failing on every frame produces one traceback rather than one per frame, and that
the run's summary reaches the log a person will actually see.
"""
import os


import logging

import pytest

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

    def test_ordinary_geometry_feeding_the_uber_shader_records_nothing(
            self, render_scene):
        """The PBR program reads more arrays than a box or a sphere carries.

        A tangent, a colour, a second UV set and a skin are read only where a
        uniform says the geometry brought them, so a shape that has none of them
        draws correctly and is not a failure to report.
        """
        from OpenGLContext.passes import renderpass
        geometry = [basenodes.Box(size=(1, 1, 1)), basenodes.Sphere(radius=1.0),
                    basenodes.Cylinder(radius=0.5), basenodes.Cone()]
        render_scene([
            basenodes.Transform(translation=(index * 3.0, 0, -8), children=[
                basenodes.Shape(geometry=shape,
                                appearance=basenodes.Appearance(
                                    material=basenodes.Material()))])
            for index, shape in enumerate(geometry)
        ] + [basenodes.PointLight(location=(0, 5, 5), intensity=1.0)], frames=2)
        assert renderpass.FLAT.failures.summary() == []


class TestAGeometryThatCannotFeedTheShader:
    """The other half of the check: an array the shader has no default for."""

    def test_a_mesh_without_normals_is_named(self, render_scene, caplog):
        from OpenGLContext.passes import renderpass
        with caplog.at_level(logging.ERROR, logger='OpenGLContext.passes._flat'):
            render_scene(unlit_normals_scene(), frames=2)
        summary = renderpass.FLAT.failures.summary()
        assert len(summary) == 1
        assert 'aNormal' in summary[0].description
        # Nothing raised, so there is no traceback to print; the message is what
        # there is to say and it has to reach the log.
        assert 'aNormal' in caplog.text
        assert 'NoneType: None' not in caplog.text


def unlit_normals_scene():
    """A mesh the PBR program has nothing to shade: no normals at all."""
    import numpy as np
    from types import SimpleNamespace

    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    positions = np.array([
        [-4, -4, -20], [4, -4, -20], [4, 4, -20],
    ], 'f')
    mesh = mesh_from_primitive(
        SimpleNamespace(attributes={'POSITION': positions}, indices=None),
        material=PBRMaterial(baseColor=(0.8, 0.1, 0.1)))
    return [basenodes.Shape(geometry=mesh),
            basenodes.PointLight(location=(0, 5, 5), intensity=1.0)]


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
