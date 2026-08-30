"""Pictures on the screen, bounded and off the draw call
(:mod:`OpenGLContext.ui.pictures`).

A gallery of a few hundred models is a few hundred pictures, and the overlay
renderer used to decode each one inside the draw call that first showed it and
then keep it for the life of the window.  That is a stutter every time the
selection moves and a texture budget that only ever grows.

So: decode off the render thread, upload on it -- GL is single-threaded -- and
evict the least recently used once a texel budget is reached.  None of that
needs a window, because uploading and deleting are two callables handed in.
"""
import threading

import pytest

from OpenGLContext.ui.pictures import PictureCache


@pytest.fixture
def picture(tmp_path):
    """A real 4x2 PNG on disk, so a real decode has something to read."""
    from PIL import Image

    def make(name, size=(4, 2)):
        path = tmp_path / name
        Image.new('RGBA', size, (10, 20, 30, 255)).save(path)
        return str(path)
    return make


class _GL:
    """Stands in for the two GL calls a picture cache makes."""

    def __init__(self):
        self.uploaded = []
        self.deleted = []
        self._next = 1

    def upload(self, width, height, data):
        self._next += 1
        self.uploaded.append((self._next, width, height))
        return self._next

    def delete(self, texture):
        self.deleted.append(texture)


@pytest.fixture
def gl():
    return _GL()


def _cache(gl, **named):
    named.setdefault('workers', 0)      # decode on request: deterministic
    return PictureCache(upload=gl.upload, delete=gl.delete, **named)


class TestAskingForAPicture:
    def test_the_first_ask_has_nothing_to_give_yet(self, gl, picture):
        """Nothing is decoded inside the call that wanted to draw it."""
        assert _cache(gl).get(picture('a.png')) is None
        assert gl.uploaded == []

    def test_it_arrives_once_the_frame_has_pumped(self, gl, picture):
        cache = _cache(gl)
        path = picture('a.png')
        cache.get(path)
        assert cache.pump() == 1
        assert cache.get(path) == (2, 4, 2)

    def test_a_caller_that_must_have_it_now_can_wait(self, gl, picture):
        """A skin's own artwork is needed for the frame that asks for it."""
        assert _cache(gl).get(picture('a.png'), blocking=True) == (2, 4, 2)

    def test_asking_twice_decodes_once(self, gl, picture):
        cache = _cache(gl)
        path = picture('a.png')
        for _ in range(5):
            cache.get(path)
        cache.pump()
        assert len(gl.uploaded) == 1

    def test_a_picture_that_will_not_load_is_tried_once(self, gl, tmp_path):
        cache = _cache(gl)
        missing = str(tmp_path / 'nope.png')
        for _ in range(3):
            assert cache.get(missing, blocking=True) is None
        assert cache.failures == 1

    def test_nothing_to_load_is_not_a_failure(self, gl):
        assert _cache(gl).get('') is None
        assert _cache(gl).get(None) is None

    def test_only_so_many_uploads_happen_per_frame(self, gl, picture):
        """A whole gallery arriving at once must not cost one long frame."""
        cache = _cache(gl, uploadsPerPump=2)
        for index in range(5):
            cache.get(picture('p%d.png' % index))
        assert cache.pump() == 2
        assert cache.pump() == 2
        assert cache.pump() == 1


class TestTheBudget:
    def test_pictures_are_kept_until_the_budget_is_reached(self, gl, picture):
        cache = _cache(gl, budget=100)          # texels
        for index in range(5):                  # 8 texels each
            cache.get(picture('p%d.png' % index), blocking=True)
        assert gl.deleted == []
        assert cache.resident == 5

    def test_the_least_recently_used_goes_first(self, gl, picture):
        cache = _cache(gl, budget=16)           # room for two 4x2 pictures
        first = cache.get(picture('a.png'), blocking=True)
        cache.get(picture('b.png'), blocking=True)
        cache.get(picture('c.png'), blocking=True)
        assert gl.deleted == [first[0]], 'the one nobody had looked at longest'
        assert cache.resident == 2

    def test_looking_at_one_again_saves_it(self, gl, picture):
        cache = _cache(gl, budget=16)
        a = picture('a.png')
        first = cache.get(a, blocking=True)
        second = cache.get(picture('b.png'), blocking=True)
        cache.get(a)                            # looked at again: now the newest
        cache.get(picture('c.png'), blocking=True)
        assert gl.deleted == [second[0]]
        assert cache.get(a) == first, 'still resident'

    def test_a_picture_larger_than_the_whole_budget_is_still_shown(self, gl, picture):
        """Refusing to draw it would be worse than exceeding the budget once."""
        cache = _cache(gl, budget=4)
        assert cache.get(picture('big.png', size=(64, 64)), blocking=True) is not None


class TestLettingGo:
    def test_clearing_deletes_every_texture(self, gl, picture):
        cache = _cache(gl)
        pictures = [cache.get(picture('p%d.png' % i), blocking=True)
                    for i in range(3)]
        cache.clear()
        assert sorted(gl.deleted) == sorted(entry[0] for entry in pictures)
        assert cache.resident == 0

    def test_a_cleared_cache_still_works(self, gl, picture):
        cache = _cache(gl)
        path = picture('a.png')
        cache.get(path, blocking=True)
        cache.clear()
        assert cache.get(path, blocking=True) is not None


class TestOffTheRenderThread:
    def test_a_worker_decodes_it_and_the_render_thread_uploads_it(self, gl, picture):
        """The one behaviour that needs a real thread: the decode is elsewhere."""
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=1)
        try:
            path = picture('a.png')
            assert cache.get(path) is None
            cache.waitForPending(timeout=10.0)
            assert cache.pump() == 1
            assert cache.get(path) == (2, 4, 2)
            assert gl.uploaded, 'uploaded from the thread that pumped'
        finally:
            cache.close()

    def test_uploading_happens_on_the_pumping_thread(self, gl, picture):
        """GL is single-threaded; a worker must never touch it."""
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=1)
        seen = []
        gl.upload = lambda w, h, data: seen.append(threading.current_thread()) or 1
        cache.upload = gl.upload
        try:
            cache.get(picture('a.png'))
            cache.waitForPending(timeout=10.0)
            cache.pump()
            assert seen == [threading.current_thread()]
        finally:
            cache.close()


class TestRemotePictures:
    def test_an_http_preview_is_fetched_into_the_cache_directory(self, gl, picture,
                                                                 monkeypatch):
        """A library of samples names its pictures by URL, not by path."""
        from OpenGLContext.ui import pictures
        local = picture('remote.png')
        asked = []

        def fetch(url, **named):
            asked.append(url)
            return local
        monkeypatch.setattr(pictures, 'fetch_to_cache', fetch)
        cache = _cache(gl)
        assert cache.get('https://example.com/shot.png', blocking=True) is not None
        assert asked == ['https://example.com/shot.png']

    def test_a_download_that_fails_is_a_missing_picture_not_a_crash(self, gl,
                                                                    monkeypatch):
        from OpenGLContext.ui import pictures

        def fetch(url, **named):
            raise IOError('no route to host')
        monkeypatch.setattr(pictures, 'fetch_to_cache', fetch)
        assert _cache(gl).get('https://example.com/x.png', blocking=True) is None


class TestSayingWhenSomethingArrived:
    """A picture that decoded must cause a frame, or nobody sees it.

    The viewer only draws when something asks it to. A picture arriving on a
    worker thread is exactly such a something and had no way to say so, so a
    scrolled-to preview appeared whenever the *next* unrelated event happened to
    trigger a redraw -- which looked like a ten-second load of a file that takes
    a tenth of a second to fetch.
    """

    def test_it_asks_for_a_frame_when_one_lands(self, gl, picture):
        told = []
        cache = _cache(gl, onReady=lambda: told.append(True))
        cache.get(picture('a.png'))
        assert told == [True]

    def test_it_says_nothing_for_a_picture_that_will_not_load(self, gl, tmp_path):
        """Nothing changed on screen, so there is nothing to redraw for."""
        told = []
        cache = _cache(gl, onReady=lambda: told.append(True))
        cache.get(str(tmp_path / 'missing.png'))
        assert told == []

    def test_it_says_nothing_for_one_already_resident(self, gl, picture):
        told = []
        cache = _cache(gl, onReady=lambda: told.append(True))
        path = picture('a.png')
        cache.get(path, blocking=True)
        told.clear()
        cache.get(path)
        assert told == []

    def test_a_cache_nobody_gave_a_callback_still_works(self, gl, picture):
        cache = _cache(gl)
        cache.get(picture('a.png'))
        assert cache.pump() == 1

    def test_the_worker_is_what_says_so(self, gl, picture):
        """Off the render thread, so it has to be a request and not a draw."""
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=1,
                             onReady=lambda: None)
        try:
            cache.get(picture('a.png'))
            assert cache.waitForPending(timeout=10.0)
        finally:
            cache.close()


class TestFormatsTheImagingLibraryCannotRead:
    """`registerDecoder` is how an application brings its own container.

    Content in a format PIL has never heard of -- a block-compressed game
    texture, say -- would otherwise force the application to convert files
    behind the toolkit's back and hand it paths to the copies.
    """

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        """The registry is process-wide, so a test must not leak into the next."""
        from OpenGLContext.ui import pictures
        saved = dict(pictures._decoders)
        yield
        pictures._decoders.clear()
        pictures._decoders.update(saved)

    def test_a_registered_decoder_reads_a_suffix_pil_cannot(self, gl, tmp_path):
        from PIL import Image

        from OpenGLContext.ui.pictures import registerDecoder
        path = tmp_path / 'texture.madeup'
        path.write_bytes(b'not an image by any reckoning')
        registerDecoder('.madeup', lambda _p: Image.new('RGBA', (3, 5), (1, 2, 3, 4)))
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=0)
        found = cache.get(str(path), blocking=True)
        assert found is not None
        _texture, width, height = found
        assert (width, height) == (3, 5)

    def test_a_decoder_that_declines_leaves_the_picture_undrawn(self, gl, tmp_path):
        """Returning None is an optional dependency being absent, not a crash."""
        from OpenGLContext.ui.pictures import registerDecoder
        path = tmp_path / 'texture.madeup'
        path.write_bytes(b'x')
        registerDecoder('.madeup', lambda _p: None)
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=0)
        assert cache.get(str(path), blocking=True) is None

    def test_a_decoder_that_raises_is_a_failed_picture_and_not_a_failed_frame(
            self, gl, tmp_path):
        from OpenGLContext.ui.pictures import registerDecoder

        def explode(_path):
            raise ValueError('bad container')
        path = tmp_path / 'texture.madeup'
        path.write_bytes(b'x')
        registerDecoder('.madeup', explode)
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=0)
        assert cache.get(str(path), blocking=True) is None
        assert cache.failures == 1

    def test_the_suffix_match_ignores_case(self, gl, tmp_path):
        from PIL import Image

        from OpenGLContext.ui.pictures import registerDecoder
        registerDecoder('.MadeUp', lambda _p: Image.new('RGBA', (2, 2)))
        path = tmp_path / 'texture.MADEUP'
        path.write_bytes(b'x')
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=0)
        assert cache.get(str(path), blocking=True) is not None

    def test_an_ordinary_picture_still_goes_straight_to_the_imaging_library(
            self, gl, picture):
        """The registry is a fallback for the unusual, not a layer over the usual."""
        from OpenGLContext.ui.pictures import decoderFor
        assert decoderFor(picture('plain.png')) is None
        cache = PictureCache(upload=gl.upload, delete=gl.delete, workers=0)
        assert cache.get(picture('plain.png'), blocking=True) is not None
