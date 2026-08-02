"""``oglc-view``: one command for every format (:mod:`OpenGLContext.bin.view`).

The command line's whole job is to turn arguments into a
:class:`~OpenGLContext.viewer.options.ViewerOptions` and hand it to the viewer,
so these check that and the two things it does before a window exists: listing a
scene's cameras, and the deprecating aliases that keep the old command names
working.  Nothing here opens a GL context.
"""
import os

import pytest

from OpenGLContext.bin import view as V
from OpenGLContext.testing.paths import tests_root
from OpenGLContext.viewer.options import OPTION_NAMES, ViewerOptions

WRLS = os.path.join(str(tests_root(__file__)), 'wrls')
GLTF_MODEL = os.path.join(WRLS, 'instanced_lattice.gltf')
VRML_WORLD = os.path.join(WRLS, '3shapes.wrl')
VRML_CAMERAS = os.path.join(WRLS, 'viewpoints.wrl')


class TestTheCommandLineFillsInTheOptions:
    def test_a_bare_source_is_all_it_takes(self):
        options = V.parse_args([GLTF_MODEL])
        assert isinstance(options, ViewerOptions)
        assert options.source == GLTF_MODEL

    def test_an_option_nobody_passed_keeps_the_dataclass_default(self):
        """Declared with SUPPRESS, so a default is stated once and only once."""
        assert V.parse_args([GLTF_MODEL]).margin is ViewerOptions().margin

    def test_the_format_can_be_forced(self):
        assert V.parse_args([GLTF_MODEL, '--format', 'vrml97']).format == 'vrml97'

    def test_every_option_lands_in_a_field_of_its_own(self):
        options = V.parse_args([GLTF_MODEL, '--physics', '--turntable',
                                '--size', '640x480', '--yaw', '0.5'])
        assert options.physics is True
        assert options.turntable is True
        assert options.size == (640, 480)
        assert options.yaw == pytest.approx(0.5)

    def test_the_command_line_and_the_dataclass_describe_one_viewer(self):
        """Anything the parser can set has to be somewhere to put it."""
        actions = V.build_parser()._actions
        named = {a.dest for a in actions} - {'help'}
        assert named <= set(OPTION_NAMES), sorted(named - set(OPTION_NAMES))

    def test_a_bad_size_is_refused_by_the_parser(self):
        with pytest.raises(SystemExit):
            V.parse_args([GLTF_MODEL, '--size', 'huge'])

    def test_a_bad_point_is_refused_by_the_parser(self):
        with pytest.raises(SystemExit):
            V.parse_args([GLTF_MODEL, '--eye', '1,2'])


class TestListingCameras:
    def test_a_models_cameras_are_listed_without_opening_a_window(self, capsys):
        assert V.main([GLTF_MODEL, '--list-cameras']) == 0
        assert 'no cameras' in capsys.readouterr().out

    def test_a_worlds_viewpoints_are_listed_too(self, capsys):
        """Every format, because the adapter answers, not the command."""
        assert V.main([VRML_CAMERAS, '--list-cameras']) == 0
        printed = capsys.readouterr().out
        assert '0: cam1' in printed
        assert '4: cam05' in printed


class TestStartingTheViewer:
    def test_the_options_reach_the_context(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(V, 'apply_render_env', lambda options: None)
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: seen.setdefault('size', size)))
        V.main([VRML_WORLD])
        assert V.TestContext.options.source == VRML_WORLD
        assert seen['size'] is None

    def test_a_window_size_reaches_the_loop(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(V, 'apply_render_env', lambda options: None)
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: seen.setdefault('size', size)))
        V.main([VRML_WORLD, '--size', '640x480'])
        assert seen['size'] == (640, 480)

    def test_nothing_to_view_still_opens_the_viewer(self, monkeypatch):
        """It opens its shelf.  A usage message is not what a viewer is for."""
        monkeypatch.delenv('GLTF', raising=False)
        monkeypatch.setattr(V, 'apply_render_env', lambda options: None)
        ran = []
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: ran.append(True)))
        V.main([])
        assert ran == [True]
        assert V.TestContext.options.source is None

    def test_listing_cameras_for_nothing_is_refused(self, monkeypatch):
        monkeypatch.delenv('GLTF', raising=False)
        with pytest.raises(SystemExit):
            V.main(['--list-cameras'])


class TestTheOldCommandNames:
    """``oglc-gltf`` and ``oglc-vrml`` keep working, and say what to type now."""

    @pytest.mark.parametrize('module, source', [
        ('OpenGLContext.bin.gltf_view', GLTF_MODEL),
        ('OpenGLContext.bin.vrml_view', VRML_WORLD),
        ('OpenGLContext.bin.tiles_view', VRML_WORLD),
    ])
    def test_an_alias_runs_the_one_viewer(self, module, source, monkeypatch, capsys):
        import importlib
        alias = importlib.import_module(module)
        seen = {}
        monkeypatch.setattr(V, 'apply_render_env', lambda options: None)
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: seen.setdefault('ran', True)))
        alias.main([source])
        assert seen.get('ran'), 'the alias must actually open the viewer'
        assert 'oglc-view' in capsys.readouterr().err, 'and say what replaced it'
