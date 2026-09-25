"""One options type for the library and the command line
(:mod:`OpenGLContext.viewer.options`).

Embedding a viewer must not mean building an ``argparse`` namespace by hand, and
the command line must not carry a second copy of every default.  ``argparse``
fills in a :class:`ViewerOptions` as its namespace, so there is one type and one
set of defaults; the parity test below is what keeps it that way.
"""
import argparse
import os
import dataclasses
import re

import pytest

from OpenGLContext.viewer.options import OPTION_NAMES, ViewerOptions
from OpenGLContext.bin import view
from OpenGLContext.bin.view import build_parser, parse_args
from tests.unit.test_multiview_mixin import HIGH, LOW, _Window


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
        monkeypatch.setenv('OPENGLCONTEXT_VIEW_YAW', '0.25')
        assert ViewerOptions().yaw == pytest.approx(0.25)
        monkeypatch.setenv('OPENGLCONTEXT_VIEW_YAW', 'sideways')
        assert ViewerOptions().yaw == pytest.approx(-0.62), 'bad value ignored'
        monkeypatch.delenv('OPENGLCONTEXT_VIEW_YAW')
        assert ViewerOptions().yaw == pytest.approx(-0.62)

    def test_an_unnamespaced_yaw_is_not_read(self, monkeypatch):
        """A bare name belongs to whoever else set it, not to the viewer.

        ``YAW`` is a plausible variable in a robotics or CAD shell, and one
        that turned the camera would rotate every framed capture made there.
        """
        monkeypatch.setenv('YAW', '1.4')
        assert ViewerOptions().yaw == pytest.approx(-0.62)

    @pytest.mark.parametrize('spelling', ['off', 'no', 'false', 'FALSE'])
    def test_a_spelled_out_no_turns_physics_off(self, monkeypatch, spelling):
        """Every accepted spelling of "no", not only ``0``.

        These variables are how a feature is pinned for a capture or a CI run,
        so a spelling that silently reverses the pin makes the result a lie.
        """
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', spelling)
        assert ViewerOptions().physics is False

    def test_a_value_that_is_neither_a_yes_nor_a_no_is_reported(
            self, monkeypatch, caplog):
        monkeypatch.setenv('OPENGLCONTEXT_PHYSICS', 'perhaps')
        assert ViewerOptions().physics is False
        assert 'OPENGLCONTEXT_PHYSICS' in caplog.text


class TestTheWindow:
    """What ``oglc-view`` asks of the window it opens."""

    @pytest.fixture(autouse=True)
    def _no_fullscreen_pin(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_FULLSCREEN', raising=False)

    def test_an_interactive_viewer_fills_the_screen(self):
        window = ViewerOptions(source='m.glb').window()
        assert window['fullscreen'] is True

    def test_leaving_full_screen_goes_to_a_1080p_window(self):
        assert ViewerOptions().window()['size'] == (1920, 1080)

    def test_a_size_asks_for_a_window_of_that_size(self):
        window = ViewerOptions(size=(1280, 720)).window()
        assert window == {'size': (1280, 720), 'fullscreen': False}

    def test_a_size_can_still_be_full_screen_when_asked(self):
        window = ViewerOptions(size=(1280, 720), fullscreen=True).window()
        assert window == {'size': (1280, 720), 'fullscreen': True}

    def test_full_screen_can_be_turned_off(self):
        window = ViewerOptions(fullscreen=False).window()
        assert window == {'size': (1920, 1080), 'fullscreen': False}

    def test_the_environment_pins_the_default(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_FULLSCREEN', '0')
        assert ViewerOptions().window()['fullscreen'] is False
        monkeypatch.setenv('OPENGLCONTEXT_FULLSCREEN', '1')
        assert ViewerOptions(size=(640, 480)).window()['fullscreen'] is True

    @pytest.mark.parametrize('output', [
        {'capture': 'shot.png'}, {'capture_video': 'walk.mp4'},
    ])
    def test_a_capture_keeps_the_size_it_was_given(self, output):
        """Its output's resolution is the size, and a reference image is
        compared at the size it was made at."""
        assert ViewerOptions(**output).window() == {}
        assert ViewerOptions(size=(640, 480), **output).window() == {
            'size': (640, 480)}

    def test_the_command_line_says_whether_to_fill_the_screen(self):
        assert view.parse_args(['m.glb', '--no-fullscreen']).fullscreen is False
        assert view.parse_args(['m.glb', '--fullscreen']).fullscreen is True
        assert view.parse_args(['m.glb']).fullscreen is None


class TestTheCommandLineFillsIn:
    """``parse_args`` returns a ``ViewerOptions``, not a bare namespace."""

    def _parsed(self, argv):
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
        parser = view.build_parser()
        reachable = set()
        for action in parser._actions:
            if action.dest not in ('help',):
                reachable.add(action.dest)
        assert set(OPTION_NAMES) <= reachable, set(OPTION_NAMES) - reachable

    def test_the_parser_carries_no_defaults_of_its_own(self):
        """Every default is the dataclass's, so the two cannot drift."""
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
        assert view.parse_args([]).source is None

    def test_the_env_var_is_not_consumed_by_the_parser(self, monkeypatch):
        """``GLTF=`` is resolved by the viewer, so an explicit path still wins."""
        monkeypatch.setenv('GLTF', 'from-env.glb')
        assert view.parse_args(['given.glb']).source == 'given.glb'
        assert view.parse_args([]).source is None
        assert os.environ['GLTF'] == 'from-env.glb'


class TestTheArrangementAViewerOpensIn:
    """A viewer class that declares four views opens in four unless the
    command line says otherwise (the Tk and wx embedding demos declare it)."""

    def window(self, declared):
        class Declared(_Window):
            multiViewArrangement = declared

        return Declared, (LOW, HIGH)

    def test_a_class_that_declares_quad_opens_in_quad(self):
        Declared, bounds = self.window('quad')
        window = Declared()
        window.startViews(bounds=bounds, arrangement=ViewerOptions().views)
        assert window.views.mode == 'quad'

    def test_the_command_line_outranks_the_class(self):
        Declared, bounds = self.window('quad')
        window = Declared()
        options = ViewerOptions(views='single')
        window.startViews(bounds=bounds, arrangement=options.views)
        assert window.views.mode == 'single'

    def test_an_unpassed_views_option_is_none(self):
        assert parse_args(['model.glb']).views is None
        assert parse_args(['model.glb', '--views', 'quad']).views == 'quad'


class TestWhatTheCommandLineRefuses:
    """Refused by the parser, before a window opens, rather than inside it."""

    @pytest.mark.parametrize('argv', [
        ['--video-fps', '0'], ['--video-fps', '-5'], ['--video-fps', 'x'],
        ['--video-seconds', '0'], ['--video-seconds', '-2'],
        ['--video-seconds', 'nan'],
    ])
    def test_a_recording_of_no_length_or_rate(self, argv):
        with pytest.raises(SystemExit):
            parse_args(['model.glb'] + argv)

    def test_a_positive_one_is_taken(self):
        options = parse_args(['model.glb', '--video-fps', '24',
                              '--video-seconds', '2.5'])
        assert (options.video_fps, options.video_seconds) == (24, 2.5)


class TestOneOptionOneEntry:
    def test_capture_and_capture_image_are_one_option(self):
        spelled = [action.option_strings for action in build_parser()._actions
                   if 'capture' == action.dest]
        assert spelled == [['--capture', '--capture-image']]

    def test_the_recording_length_says_it_also_times_a_fly_through(self):
        action, = [action for action in build_parser()._actions
                   if action.dest == 'video_seconds']
        assert 'fly-through' in action.help


class TestTheViewerPageListsEveryField:
    def test_every_field_is_named_on_the_viewer_page(self):
        here = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        with open(os.path.join(here, 'docs', 'viewer.rst'),
                  encoding='utf-8') as handle:
            page = handle.read()
        start = page.index('The fields, by group:')
        listed = set(re.findall(r'``([a-z_]+)``',
                                page[start:page.index('\n\n', start + 30)]))
        assert [field.name for field in dataclasses.fields(ViewerOptions)
                if field.name not in listed] == []
