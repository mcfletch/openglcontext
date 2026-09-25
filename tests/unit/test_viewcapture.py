"""A child that hangs, fails or draws nothing fails the test that ran it."""

import sys

import numpy as np
import pytest
from PIL import Image

from tests.unit import viewcapture


@pytest.fixture(autouse=True)
def a_gl_target(monkeypatch):
    """These children draw nothing, so whether this machine can is not asked."""
    monkeypatch.setattr(viewcapture, 'gl_available', lambda: True)


def _python(source):
    return [sys.executable, '-c', source]


def test_the_frame_written_is_the_one_read(tmp_path):
    out = tmp_path / 'frame.png'
    Image.new('RGB', (3, 2), (10, 20, 30)).save(out)
    frame = viewcapture.run_to_frame(_python('pass'), str(out))
    assert frame.shape == (2, 3, 3)
    assert (frame == np.array([10, 20, 30])).all()


def test_a_child_that_runs_past_its_timeout_fails(tmp_path):
    with pytest.raises(pytest.fail.Exception, match=r'ran past 0\.5s'):
        viewcapture.run_to_frame(
            _python('import time; print("started", flush=True); time.sleep(30)'),
            str(tmp_path / 'frame.png'), timeout=0.5)


def test_a_child_that_exits_with_an_error_fails_with_its_output(tmp_path):
    with pytest.raises(pytest.fail.Exception, match='exited 3') as failed:
        viewcapture.run_to_frame(
            _python('import sys; sys.stderr.write("no model"); sys.exit(3)'),
            str(tmp_path / 'frame.png'))
    assert 'no model' in str(failed.value)


def test_a_child_that_writes_no_frame_fails(tmp_path):
    with pytest.raises(pytest.fail.Exception, match='wrote no frame'):
        viewcapture.run_to_frame(_python('pass'), str(tmp_path / 'frame.png'))


def test_no_gl_target_is_a_skip_before_anything_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(viewcapture, 'gl_available', lambda: False)
    marker = tmp_path / 'ran'
    with pytest.raises(pytest.skip.Exception, match='no GL target'):
        viewcapture.run_child(_python('open(%r, "w")' % (str(marker),)))
    assert not marker.exists()


def test_the_viewer_is_asked_to_capture_to_the_frame_read(monkeypatch):
    ran = []
    monkeypatch.setattr(viewcapture, 'run_to_frame',
                        lambda command, out, **_named: ran.append((command, out)))
    viewcapture.view_frame(['model.glb', '--size', 64], 'shot.png')
    ((command, out),) = ran
    assert command[1:] == ['-m', 'OpenGLContext.bin.view', 'model.glb', '--size',
                           '64', '--capture', 'shot.png']
    assert out == 'shot.png'
