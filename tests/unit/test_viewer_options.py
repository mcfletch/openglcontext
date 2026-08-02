"""One options type for the library and the command line
(:mod:`OpenGLContext.viewer.options`).

Embedding a viewer must not mean building an ``argparse`` namespace by hand, and
the command line must not carry a second copy of every default.  ``argparse``
fills in a :class:`ViewerOptions` as its namespace, so there is one type and one
set of defaults; the parity test below is what keeps it that way.
"""
import argparse
import os

import pytest

from OpenGLContext.viewer.options import OPTION_NAMES, ViewerOptions


class TestUsableWithoutACommandLine:
    def test_an_application_gets_a_working_viewer_from_the_defaults(self):
        options = ViewerOptions(source='model.glb')
        assert options.source == 'model.glb'
        assert options.animate is True
        assert options.physics is False
        assert options.lights == 'auto'
        assert options.capture is None

    def test_options_can_be_changed_after_construction(self):
        """A catalogue browser rewrites the framing per model."""
        options = ViewerOptions()
        options.yaw = 1.5
        options.background = 'sky'
        assert (options.yaw, options.background) == (1.5, 'sky')

    def test_replace_leaves_the_original_alone(self):
        options = ViewerOptions(source='a.glb')
        other = options.replace(source='b.glb')
        assert (options.source, other.source) == ('a.glb', 'b.glb')

    def test_the_physics_default_follows_the_environment(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '1')
        assert ViewerOptions().physics is True
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '0')
        assert ViewerOptions().physics is False
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '')
        assert ViewerOptions().physics is False

    def test_the_framing_yaw_default_follows_the_environment(self, monkeypatch):
        monkeypatch.setenv('YAW', '0.25')
        assert ViewerOptions().yaw == pytest.approx(0.25)
        monkeypatch.setenv('YAW', 'sideways')
        assert ViewerOptions().yaw == pytest.approx(-0.62), 'bad value ignored'
        monkeypatch.delenv('YAW')
        assert ViewerOptions().yaw == pytest.approx(-0.62)


class TestTheCommandLineFillsIn:
    """``parse_args`` returns a ``ViewerOptions``, not a bare namespace."""

    def _parsed(self, argv):
        from OpenGLContext.bin import view
        return view.parse_args(argv)

    def test_parsing_yields_the_options_type(self):
        assert isinstance(self._parsed(['m.glb']), ViewerOptions)

    def test_an_unpassed_option_keeps_the_dataclass_default(self):
        """SUPPRESS, not None: the field default has to survive the parse."""
        parsed = self._parsed(['m.glb'])
        default = ViewerOptions()
        for name in OPTION_NAMES:
            if name == 'source':
                continue
            assert getattr(parsed, name) == getattr(default, name), name

    def test_every_field_is_reachable_from_the_command_line(self):
        """A knob the library has and the command line cannot set is a knob
        nobody will find."""
        from OpenGLContext.bin import view
        parser = view.build_parser()
        reachable = set()
        for action in parser._actions:
            if action.dest not in ('help',):
                reachable.add(action.dest)
        assert set(OPTION_NAMES) <= reachable, set(OPTION_NAMES) - reachable

    def test_the_parser_carries_no_defaults_of_its_own(self):
        """Every default is the dataclass's, so the two cannot drift."""
        from OpenGLContext.bin import view
        parser = view.build_parser()
        for action in parser._actions:
            if action.dest == 'help':
                continue
            assert action.default is argparse.SUPPRESS, action.dest

    def test_passing_an_option_overrides_the_default(self):
        parsed = self._parsed(['m.glb', '--yaw', '1.0', '--lights', 'off',
                               '--capture', 'out.png', '--frames', '3'])
        assert parsed.yaw == pytest.approx(1.0)
        assert parsed.lights == 'off'
        assert parsed.capture == 'out.png'
        assert parsed.frames == 3

    def test_a_caller_may_parse_into_options_it_already_has(self):
        """The browser starts from its own defaults and lets the user override."""
        from OpenGLContext.bin import view
        base = ViewerOptions(background='none', turntable=True)
        parsed = view.parse_args(['m.glb', '--yaw', '2.0'], options=base)
        assert parsed is base
        assert parsed.background == 'none' and parsed.turntable is True
        assert parsed.yaw == pytest.approx(2.0)

    def test_the_environment_is_read_when_the_parser_runs(self, monkeypatch):
        """A shell variable pins a default for a run, so it cannot be baked in
        at import time."""
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '1')
        assert self._parsed(['m.glb']).physics is True
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', '0')
        assert self._parsed(['m.glb']).physics is False


class TestSourceIsStillOptional:
    def test_no_source_leaves_it_unset(self):
        from OpenGLContext.bin import view
        assert view.parse_args([]).source is None

    def test_the_env_var_is_not_consumed_by_the_parser(self, monkeypatch):
        """``GLTF=`` is resolved by the viewer, so an explicit path still wins."""
        monkeypatch.setenv('GLTF', 'from-env.glb')
        from OpenGLContext.bin import view
        assert view.parse_args(['given.glb']).source == 'given.glb'
        assert view.parse_args([]).source is None
        assert os.environ['GLTF'] == 'from-env.glb'
