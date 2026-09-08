"""Unit tests for the shared framebuffer-capture helpers (no GL context needed).

``read_back_buffer`` is exercised against monkeypatched GL entry points so the
reshape/flip logic is verified without a live context; ``save_png``/``SettleCapture``
run for real.
"""
import numpy as np
from OpenGL.GL import GL_FRAMEBUFFER_DEFAULT, GL_READ_FRAMEBUFFER

from OpenGLContext import capture


def test_save_png_round_trip(tmp_path):
    arr = np.zeros((4, 6, 3), dtype=np.uint8)
    arr[1, 2] = (10, 20, 30)
    out = tmp_path / 'sub' / 'frame.png'          # nested dir is created
    assert capture.save_png(str(out), arr) is True
    Image = capture.ensure_pillow()
    back = np.array(Image.open(str(out)).convert('RGB'))
    assert np.array_equal(back, arr)


def test_save_png_none_pixels_returns_false(tmp_path):
    assert capture.save_png(str(tmp_path / 'x.png'), None) is False


def _patch_buffers(monkeypatch, has_back_buffer):
    """Report a default framebuffer that does, or does not, carry a back buffer."""
    def attachment(_target, _attachment, _pname):
        return GL_FRAMEBUFFER_DEFAULT if has_back_buffer else capture.GL_NONE

    monkeypatch.setattr(
        capture, 'glGetFramebufferAttachmentParameteriv', attachment)


def _patch_gl(monkeypatch, width, height, fill, has_back_buffer=True):
    """Make capture's GL calls report a `width`x`height` viewport whose bytes are
    `fill(x, y)` in OpenGL's bottom-up order."""
    monkeypatch.setattr(capture, 'glGetIntegerv', lambda _e: (0, 0, width, height))
    _patch_buffers(monkeypatch, has_back_buffer)
    monkeypatch.setattr(capture, 'glReadBuffer', lambda _b: None)
    # Stubbed like the rest: this module states that it needs no live context,
    # and an entry point left unstubbed makes that true only for a run where
    # some earlier test happened to leave one behind.
    monkeypatch.setattr(capture, 'glBindFramebuffer', lambda _t, _f: None)

    def fake_read(x, y, w, h, fmt, typ):
        # emulate glReadPixels honouring the y-offset + height we pass it
        return b''.join(bytes(fill(px, y + py)) for py in range(h) for px in range(w))

    monkeypatch.setattr(capture, 'glReadPixels', fake_read)


def test_read_back_buffer_flips_to_top_down(monkeypatch):
    # bottom row (y=0) is red, next row green -> after flip, row 0 must be the top
    def fill(x, y):
        return (255, 0, 0) if y == 0 else (0, 255, 0)
    _patch_gl(monkeypatch, 3, 2, fill)
    pixels, w, h = capture.read_back_buffer()
    assert (w, h) == (3, 2)
    assert tuple(pixels[0, 0]) == (0, 255, 0)      # top row = GL's upper row
    assert tuple(pixels[-1, 0]) == (255, 0, 0)     # bottom row = GL's y=0


def test_read_back_buffer_excludes_hud(monkeypatch):
    def fill(x, y):
        return (y, 0, 0)
    _patch_gl(monkeypatch, 2, 5, fill)
    pixels, w, h = capture.read_back_buffer(hud_height=2)
    assert h == 3                                   # bottom 2 rows dropped
    # rows captured are GL y in [2..4]; flipped so top is y=4
    assert tuple(pixels[0, 0]) == (4, 0, 0)
    assert tuple(pixels[-1, 0]) == (2, 0, 0)


class TestWhichBufferTheFrameIsIn:
    """A default framebuffer with no back buffer keeps the frame in the front
    one, and ``glReadBuffer(GL_BACK)`` against it is GL_INVALID_OPERATION --
    which the offscreen backends meet, since a surface nothing presents has no
    reason to carry a second colour buffer.
    """

    def test_a_frame_is_in_the_back_buffer_where_there_is_one(self, monkeypatch):
        _patch_buffers(monkeypatch, has_back_buffer=True)
        assert capture.presented_buffer() == capture.GL_BACK

    def test_a_frame_is_in_the_front_buffer_where_there_is_not(self, monkeypatch):
        _patch_buffers(monkeypatch, has_back_buffer=False)
        assert capture.presented_buffer() == capture.GL_FRONT

    def test_it_asks_the_framebuffer_the_caller_named(self, monkeypatch):
        targets = []

        def attachment(target, _attachment, _pname):
            targets.append(target)
            return GL_FRAMEBUFFER_DEFAULT

        monkeypatch.setattr(
            capture, 'glGetFramebufferAttachmentParameteriv', attachment)
        capture.presented_buffer(GL_READ_FRAMEBUFFER)
        assert targets == [GL_READ_FRAMEBUFFER]

    def test_double_buffering_is_not_what_decides_it(self, monkeypatch):
        """An EGL window surface reports ``GL_DOUBLEBUFFER`` false and still
        keeps its only colour buffer in ``GL_BACK``, with no front buffer to
        read.  Deciding from that flag asks for the buffer that is missing.
        """
        def refuse(enum):
            raise AssertionError(
                'presented_buffer asked glGetIntegerv about %s' % (enum,))

        monkeypatch.setattr(capture, 'glGetIntegerv', refuse)
        _patch_buffers(monkeypatch, has_back_buffer=True)
        assert capture.presented_buffer() == capture.GL_BACK

    def test_the_read_asks_for_the_buffer_that_is_there(self, monkeypatch):
        asked = []
        _patch_gl(monkeypatch, 2, 2, lambda x, y: (1, 2, 3),
                  has_back_buffer=False)
        monkeypatch.setattr(capture, 'glReadBuffer', asked.append)
        capture.read_back_buffer()
        assert asked == [capture.GL_FRONT]

    def test_and_the_back_buffer_where_there_is_one(self, monkeypatch):
        asked = []
        _patch_gl(monkeypatch, 2, 2, lambda x, y: (1, 2, 3))
        monkeypatch.setattr(capture, 'glReadBuffer', asked.append)
        capture.read_back_buffer()
        assert asked == [capture.GL_BACK]


def test_capture_to_png_skips_blank(monkeypatch, tmp_path):
    _patch_gl(monkeypatch, 2, 2, lambda x, y: (0, 0, 0))
    out = tmp_path / 'blank.png'
    assert capture.capture_to_png(str(out)) is False
    assert not out.exists()


def test_capture_to_png_writes_content(monkeypatch, tmp_path):
    _patch_gl(monkeypatch, 2, 2, lambda x, y: (5, 5, 5))
    out = tmp_path / 'content.png'
    assert capture.capture_to_png(str(out)) is True
    assert out.exists()


class TestSettleCapture:
    def test_waits_for_min_frames(self, monkeypatch, tmp_path):
        saved = []
        monkeypatch.setattr(capture, 'read_back_buffer',
                            lambda hud=0: (np.ones((1, 1, 3), np.uint8), 1, 1))
        monkeypatch.setattr(capture, 'save_png', lambda p, px: saved.append(p) or True)
        s = capture.SettleCapture(str(tmp_path / 'o.png'), delay=0.0, min_frames=3)
        assert s.tick() is False and s.tick() is False   # frames 1, 2
        assert s.tick() is True                          # frame 3 fires
        assert s.done is True and len(saved) == 1
        assert s.tick() is False                         # no double capture

    def test_waits_for_delay(self, monkeypatch, tmp_path):
        # SettleCapture.tick does `from time import perf_counter` each call, so
        # patching the stdlib clock controls it.
        clock = {'t': 100.0}
        import time as _time
        monkeypatch.setattr(_time, 'perf_counter', lambda: clock['t'])
        monkeypatch.setattr(capture, 'read_back_buffer',
                            lambda hud=0: (np.ones((1, 1, 3), np.uint8), 1, 1))
        monkeypatch.setattr(capture, 'save_png', lambda p, px: True)
        s = capture.SettleCapture(str(tmp_path / 'o.png'), delay=0.5, min_frames=1)
        assert s.tick() is False       # min_frames met but delay not elapsed
        clock['t'] = 100.6
        assert s.tick() is True        # delay elapsed
