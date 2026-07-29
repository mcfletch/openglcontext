"""Fetching a large asset: streamed, watchable and abandonable.

A texture pack is hundreds of megabytes.  Reading one in a single call holds
the whole of it in memory before a byte reaches the disk, tells the caller
nothing while it happens, and cannot be stopped once it has started -- which
between them are the three reasons a download cannot be put on screen.

Streaming fixes all three at once, and the memory one matters even for a
caller that wants neither of the others.
"""
import os

import pytest

from OpenGLContext.loaders import resolver


class _ChunkedResponse:
    """A fake urlopen response that hands its body over a chunk at a time."""

    def __init__(self, data, chunk=1024, length=True):
        self._data = data
        self._chunk = chunk
        self._offset = 0
        self.headers = {'Content-Length': str(len(data))} if length else {}
        self.closed = False

    def read(self, n=-1):
        # Never more than this response's own chunk size, so a test can decide
        # how many pieces a body arrives in however large the reader's ask is.
        if n is None or n < 0:
            n = len(self._data) - self._offset
        n = min(n, self._chunk)
        piece = self._data[self._offset:self._offset + n]
        self._offset += len(piece)
        return piece

    def close(self):
        self.closed = True


@pytest.fixture
def payload():
    return bytes(range(256)) * 2048             # 512 KiB, distinctive content


@pytest.fixture
def serve(monkeypatch, payload):
    """Serve ``payload`` from any URL; returns the fake response afterwards."""
    made = {}

    def factory(**named):
        def _open(url, base_url, timeout=30):
            made['response'] = _ChunkedResponse(payload, **named)
            return made['response']
        monkeypatch.setattr(resolver, '_urlopen_same_origin', _open)
        return made
    return factory


class TestStreaming:

    def test_the_bytes_that_land_are_the_bytes_that_were_sent(self, serve, payload,
                                                              tmp_path):
        serve()
        path = resolver.fetch_to_cache('https://example.com/a.bin',
                                       cache_dir=str(tmp_path))
        assert open(path, 'rb').read() == payload

    def test_the_body_is_never_held_whole_in_memory(self, serve, payload, tmp_path):
        """The point of streaming, and the part a progress bar does not prove.

        A 450 MB pack read in one call is 450 MB of process memory before a
        byte reaches the disk.  Asserting on the largest single read is how
        that stays true.
        """
        made = serve(chunk=8192)
        resolver.fetch_to_cache('https://example.com/b.bin', cache_dir=str(tmp_path))
        assert made['response']._chunk <= resolver.DOWNLOAD_CHUNK_BYTES

    def test_a_response_with_no_content_length_still_arrives(self, serve, payload,
                                                             tmp_path):
        """Plenty of servers send none, and a download must not need it."""
        serve(length=False)
        path = resolver.fetch_to_cache('https://example.com/c.bin',
                                       cache_dir=str(tmp_path))
        assert open(path, 'rb').read() == payload

    def test_the_size_cap_is_still_enforced(self, serve, payload, tmp_path):
        serve()
        with pytest.raises(ValueError):
            resolver.fetch_to_cache('https://example.com/d.bin',
                                    cache_dir=str(tmp_path),
                                    max_bytes=len(payload) // 2)

    def test_an_over_size_response_leaves_no_partial_file(self, serve, payload,
                                                          tmp_path):
        serve()
        with pytest.raises(ValueError):
            resolver.fetch_to_cache('https://example.com/e.bin',
                                    cache_dir=str(tmp_path),
                                    max_bytes=len(payload) // 2)
        assert not os.path.exists(resolver.cached_path('https://example.com/e.bin',
                                                       str(tmp_path)))


class TestProgress:

    def test_progress_is_reported_as_it_arrives(self, serve, payload, tmp_path):
        serve(chunk=4096)
        seen = []
        resolver.fetch_to_cache('https://example.com/f.bin', cache_dir=str(tmp_path),
                                progress=lambda done, total: seen.append((done, total)))
        assert len(seen) > 1
        assert [done for done, _ in seen] == sorted(done for done, _ in seen)
        assert seen[-1][0] == len(payload)

    def test_the_total_is_the_content_length(self, serve, payload, tmp_path):
        serve()
        seen = []
        resolver.fetch_to_cache('https://example.com/g.bin', cache_dir=str(tmp_path),
                                progress=lambda done, total: seen.append(total))
        assert seen[-1] == len(payload)

    def test_an_unknown_total_is_reported_as_none(self, serve, payload, tmp_path):
        """A progress bar with no total should show motion, not a false 100%."""
        serve(length=False)
        seen = []
        resolver.fetch_to_cache('https://example.com/h.bin', cache_dir=str(tmp_path),
                                progress=lambda done, total: seen.append(total))
        assert set(seen) == {None}

    def test_a_progress_callback_that_raises_does_not_lose_the_download(
            self, serve, payload, tmp_path):
        """Reporting is the caller's business and its failure is not fatal."""
        serve()

        def broken(done, total):
            raise RuntimeError('the progress bar fell over')

        path = resolver.fetch_to_cache('https://example.com/i.bin',
                                       cache_dir=str(tmp_path), progress=broken)
        assert open(path, 'rb').read() == payload

    def test_a_cache_hit_reports_completion_without_downloading(self, serve, payload,
                                                                tmp_path):
        """A caller showing a bar must see it finish even when nothing was fetched."""
        serve()
        url = 'https://example.com/j.bin'
        resolver.fetch_to_cache(url, cache_dir=str(tmp_path))
        seen = []
        resolver.fetch_to_cache(url, cache_dir=str(tmp_path),
                                progress=lambda done, total: seen.append((done, total)))
        assert seen and seen[-1] == (len(payload), len(payload))


class TestCancelling:

    def test_a_cancelled_download_stops(self, serve, payload, tmp_path):
        serve(chunk=1024)
        with pytest.raises(resolver.FetchCancelled):
            resolver.fetch_to_cache('https://example.com/k.bin',
                                    cache_dir=str(tmp_path),
                                    cancel=lambda: True)

    def test_a_cancelled_download_leaves_nothing_in_the_cache(self, serve, payload,
                                                              tmp_path):
        """Half a texture pack in the cache is worse than none of one."""
        serve(chunk=1024)
        url = 'https://example.com/l.bin'
        with pytest.raises(resolver.FetchCancelled):
            resolver.fetch_to_cache(url, cache_dir=str(tmp_path),
                                    cancel=lambda: True)
        assert not os.path.exists(resolver.cached_path(url, str(tmp_path)))

    def test_a_cancel_partway_through_stops_partway_through(self, serve, payload,
                                                            tmp_path):
        serve(chunk=1024)
        seen = []

        def after_two():
            return len(seen) >= 2

        with pytest.raises(resolver.FetchCancelled):
            resolver.fetch_to_cache('https://example.com/m.bin',
                                    cache_dir=str(tmp_path), cancel=after_two,
                                    progress=lambda done, total: seen.append(done))
        assert seen and seen[-1] < len(payload)

    def test_not_cancelling_downloads_normally(self, serve, payload, tmp_path):
        serve()
        path = resolver.fetch_to_cache('https://example.com/n.bin',
                                       cache_dir=str(tmp_path),
                                       cancel=lambda: False)
        assert open(path, 'rb').read() == payload

    def test_the_response_is_closed_even_when_cancelled(self, serve, payload,
                                                        tmp_path):
        made = serve(chunk=1024)
        with pytest.raises(resolver.FetchCancelled):
            resolver.fetch_to_cache('https://example.com/o.bin',
                                    cache_dir=str(tmp_path), cancel=lambda: True)
        assert made['response'].closed
