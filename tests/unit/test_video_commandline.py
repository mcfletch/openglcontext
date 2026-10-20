"""The options a program offers to record itself, and the codec names they take."""
import argparse
import sys

import pytest

from OpenGLContext.video import codecs
from OpenGLContext.video.commandline import (
    RecordingRequest, add_recording_arguments, require_recording,
)


def parser(**defaults):
    found = argparse.ArgumentParser(prog='game')
    add_recording_arguments(found, **defaults)
    return found


@pytest.mark.parametrize('spelling, name', [
    ('h264', 'h264'), ('H264', 'h264'), ('avc', 'h264'), ('h.264', 'h264'),
    ('hevc', 'hevc'), ('h265', 'hevc'), ('H.265', 'hevc'),
    ('vp9', 'vp9'), ('av1', 'av1'),
])
def test_a_codec_is_known_by_the_spellings_people_use(spelling, name):
    assert codecs.canonical(spelling) == name


def test_the_codecs_are_the_four_the_muxer_stores():
    assert codecs.CODECS == ('h264', 'hevc', 'vp9', 'av1')


def test_a_codec_nothing_encodes_is_refused_with_the_ones_that_exist():
    with pytest.raises(ValueError, match=r'h264, hevc, vp9, av1'):
        codecs.canonical('theora')


def test_recording_is_off_unless_a_path_is_given():
    options = parser().parse_args([])
    assert RecordingRequest.from_namespace(options) is None


def test_a_path_alone_records_with_the_defaults_the_program_chose():
    options = parser(seconds=12, fps=30, delay=2.5).parse_args(['--record', 'run.mp4'])
    request = RecordingRequest.from_namespace(options)
    assert request == RecordingRequest(
        path='run.mp4', codec='h264', seconds=12.0, fps=30, delay=2.5, bitrate=0)


@pytest.mark.parametrize('codec', ['h264', 'hevc', 'vp9', 'av1'])
def test_each_codec_can_be_asked_for_by_name(codec):
    options = parser().parse_args(['--record', 'a.mp4', '--record-codec', codec])
    assert RecordingRequest.from_namespace(options).codec == codec


def test_an_alias_is_turned_into_the_codecs_name():
    options = parser().parse_args(['--record', 'a.mp4', '--record-codec', 'h265'])
    assert RecordingRequest.from_namespace(options).codec == 'hevc'


def test_an_unknown_codec_is_a_usage_error_naming_the_choices(capsys):
    with pytest.raises(SystemExit) as stopped:
        parser().parse_args(['--record', 'a.mp4', '--record-codec', 'theora'])
    assert stopped.value.code == 2
    assert 'h264, hevc, vp9, av1' in capsys.readouterr().err


@pytest.mark.parametrize('flag, value', [
    ('--record-seconds', '0'), ('--record-seconds', '-3'),
    ('--record-fps', '0'), ('--record-fps', 'fast'),
    ('--record-delay', '-1'), ('--record-bitrate', '-5'),
])
def test_a_number_that_cannot_be_a_recording_is_a_usage_error(flag, value):
    with pytest.raises(SystemExit) as stopped:
        parser().parse_args(['--record', 'a.mp4', flag, value])
    assert stopped.value.code == 2


def test_the_encoder_is_given_only_what_was_asked_for():
    request = RecordingRequest(path='a.mp4', codec='av1', seconds=8.0, fps=24,
                               delay=1.0, bitrate=0)
    assert request.options() == dict(codec='av1', fps=24, seconds=8.0, start_after=1.0)


def test_a_bitrate_is_passed_on_when_it_is_set():
    request = RecordingRequest(path='a.mp4', bitrate=6_000_000)
    assert request.options()['bitrate'] == 6_000_000


def test_the_request_is_checked_before_a_window_opens(monkeypatch, capsys):
    """A machine without the encoder package says so as a usage error."""
    monkeypatch.setitem(sys.modules, 'pyopengl_video', None)
    found = parser()
    options = found.parse_args(['--record', 'a.mp4'])
    with pytest.raises(SystemExit) as stopped:
        require_recording(found, RecordingRequest.from_namespace(options))
    assert stopped.value.code == 2
    assert 'OpenGLContext[video]' in capsys.readouterr().err


def test_no_request_needs_nothing_checked():
    assert require_recording(parser(), None) is None
