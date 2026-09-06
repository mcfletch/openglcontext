"""The transmission backdrop capture must read COLOR_ATTACHMENT0
(not whatever MRT read buffer is current, which could be the object-id target)
and restore the caller's read buffer. GL entry points are monkeypatched.

On the *default* framebuffer there is no colour attachment to name, and which
buffer holds the finished frame depends on whether it has two: the back one on
a window, the front one on a surface nothing presents. Naming a buffer that is
not there is GL_INVALID_OPERATION rather than a quiet fallback, so it is asked
-- and a wrong answer here would take the frame down wherever there is glass in
it, not merely spoil a screenshot.
"""
import pytest

from OpenGLContext import capture
from OpenGLContext.passes import transmission
from OpenGLContext.passes.transmission import TransmissionBuffer


class _GL:
    def __init__(self, monkeypatch, read_fbo, double_buffered=True):
        self.read_buffer_calls = []
        self.state = {
            transmission.GL_READ_BUFFER: 0x8CE7,  # a stand-in "object-id" buffer
            transmission.GL_READ_FRAMEBUFFER_BINDING: read_fbo,
        }
        monkeypatch.setattr(transmission, 'glGetIntegerv', lambda e: self.state[e])
        monkeypatch.setattr(transmission, 'glReadBuffer',
                            lambda b: self.read_buffer_calls.append(b))
        # `presented_buffer` lives in `capture` and asks GL its own question.
        monkeypatch.setattr(capture, 'glGetIntegerv', lambda _e: double_buffered)
        for name in ('glBindTexture', 'glCopyTexSubImage2D', 'glGenerateMipmap'):
            monkeypatch.setattr(transmission, name, lambda *a, **k: None)


def _buffer():
    b = TransmissionBuffer.__new__(TransmissionBuffer)
    b.tex, b.w, b.h = 7, 4, 4
    return b


class TestCaptureReadBuffer:
    def test_reads_color_attachment_when_fbo_bound(self, monkeypatch):
        gl = _GL(monkeypatch, read_fbo=9)
        _buffer().capture()
        # first sets COLOR_ATTACHMENT0, then restores the saved read buffer
        assert gl.read_buffer_calls[0] == transmission.GL_COLOR_ATTACHMENT0
        assert gl.read_buffer_calls[-1] == 0x8CE7

    def test_reads_back_on_a_double_buffered_default_framebuffer(self, monkeypatch):
        gl = _GL(monkeypatch, read_fbo=0, double_buffered=True)
        _buffer().capture()
        # COLOR_ATTACHMENT0 is invalid on the default framebuffer -> GL_BACK
        assert gl.read_buffer_calls[0] == capture.GL_BACK
        assert gl.read_buffer_calls[-1] == 0x8CE7

    def test_reads_front_where_there_is_no_back_buffer(self, monkeypatch):
        """What an offscreen surface has: one colour buffer, holding the frame."""
        gl = _GL(monkeypatch, read_fbo=0, double_buffered=False)
        _buffer().capture()
        assert gl.read_buffer_calls[0] == capture.GL_FRONT
        assert gl.read_buffer_calls[-1] == 0x8CE7

    def test_the_framebuffer_object_case_does_not_ask(self, monkeypatch):
        """A colour attachment is a colour attachment whatever the default
        framebuffer happens to carry."""
        gl = _GL(monkeypatch, read_fbo=9, double_buffered=False)
        _buffer().capture()
        assert gl.read_buffer_calls[0] == transmission.GL_COLOR_ATTACHMENT0


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
