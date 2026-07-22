"""The transmission backdrop capture must read COLOR_ATTACHMENT0
(not whatever MRT read buffer is current, which could be the object-id target)
and restore the caller's read buffer. GL entry points are monkeypatched."""
import pytest

from OpenGLContext.passes import transmission
from OpenGLContext.passes.transmission import TransmissionBuffer


class _GL:
    def __init__(self, monkeypatch, read_fbo):
        self.read_buffer_calls = []
        self.state = {
            transmission.GL_READ_BUFFER: 0x8CE7,  # a stand-in "object-id" buffer
            transmission.GL_READ_FRAMEBUFFER_BINDING: read_fbo,
        }
        monkeypatch.setattr(transmission, 'glGetIntegerv', lambda e: self.state[e])
        monkeypatch.setattr(transmission, 'glReadBuffer',
                            lambda b: self.read_buffer_calls.append(b))
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

    def test_reads_back_on_default_framebuffer(self, monkeypatch):
        gl = _GL(monkeypatch, read_fbo=0)
        _buffer().capture()
        # COLOR_ATTACHMENT0 is invalid on the default framebuffer -> GL_BACK
        assert gl.read_buffer_calls[0] == transmission.GL_BACK
        assert gl.read_buffer_calls[-1] == 0x8CE7


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
