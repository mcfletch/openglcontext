"""The asset cache must never expose a partially-written file.

Two callers can fetch the same URL concurrently (the IBL probe and an HDR
background node both loading one panorama). If the cache file were written in
place, a caller finding the path present could read a half-written file. These
tests drive that race with a deliberately slow fake download and assert every
caller gets the complete bytes and no temp file leaks.
"""
import os
import threading
import time

import pytest

from OpenGLContext.loaders import resolver


class _SlowResponse:
    """A fake urlopen response whose body arrives in slow chunks."""

    def __init__(self, data, delay=0.02):
        self._data = data
        self._delay = delay

    def read(self, n=-1):
        # Simulate transfer latency so a concurrent reader would catch a partial
        # in-place write if the writer were not atomic.
        time.sleep(self._delay)
        return self._data

    def close(self):
        pass


@pytest.fixture
def fake_download(monkeypatch, tmp_path):
    payload = bytes(range(256)) * 4096          # 1 MiB, distinctive content
    calls = {'n': 0}

    def _fake_open(url, base_url, timeout=30):
        calls['n'] += 1
        return _SlowResponse(payload)

    monkeypatch.setattr(resolver, '_urlopen_same_origin', _fake_open)
    return payload, str(tmp_path), calls


def test_fetch_writes_complete_file(fake_download):
    payload, cache_dir, _ = fake_download
    url = 'https://example.com/asset.bin'
    path = resolver.fetch_to_cache(url, cache_dir=cache_dir)
    with open(path, 'rb') as f:
        assert f.read() == payload


def test_concurrent_fetch_never_reads_partial(fake_download):
    payload, cache_dir, _ = fake_download
    url = 'https://example.com/panorama.hdr'
    results = []
    errors = []

    def worker():
        try:
            path = resolver.fetch_to_cache(url, cache_dir=cache_dir)
            with open(path, 'rb') as f:
                results.append(f.read())
        except Exception as err:                # pragma: no cover - failure path
            errors.append(err)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not errors, "concurrent fetch raised: %r" % errors
    assert len(results) == 8
    # every caller saw the complete, identical payload -- never a truncated file
    for r in results:
        assert r == payload


def test_concurrent_fetch_downloads_once(fake_download):
    """Single-flight: N concurrent callers for one asset trigger ONE download."""
    payload, cache_dir, calls = fake_download
    url = 'https://example.com/coalesced.hdr'

    def worker():
        resolver.fetch_to_cache(url, cache_dir=cache_dir)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert calls['n'] == 1, ("concurrent fetches were not coalesced (%d downloads)"
                             % calls['n'])


def test_distinct_urls_download_in_parallel(fake_download):
    """Different assets use different locks, so they do not serialize on each other."""
    payload, cache_dir, calls = fake_download

    def worker(i):
        resolver.fetch_to_cache('https://example.com/asset%d.hdr' % i,
                                cache_dir=cache_dir)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert calls['n'] == 5      # each distinct URL downloaded once


def test_inflight_map_is_emptied(fake_download):
    """The single-flight map drops each key once its last waiter leaves."""
    payload, cache_dir, _ = fake_download
    resolver.fetch_to_cache('https://example.com/x.hdr', cache_dir=cache_dir)
    assert resolver._INFLIGHT == {}, "in-flight download slots leaked: %r" % (
        resolver._INFLIGHT,)


def test_no_temp_files_left_behind(fake_download):
    payload, cache_dir, _ = fake_download
    resolver.fetch_to_cache('https://example.com/a.bin', cache_dir=cache_dir)
    leftovers = [n for n in os.listdir(cache_dir) if n.startswith('.dl-')]
    assert leftovers == [], "download temp files not cleaned: %s" % leftovers


def test_cache_hit_skips_second_download(fake_download):
    payload, cache_dir, calls = fake_download
    url = 'https://example.com/once.bin'
    resolver.fetch_to_cache(url, cache_dir=cache_dir)
    resolver.fetch_to_cache(url, cache_dir=cache_dir)   # served from disk cache
    assert calls['n'] == 1, "second sequential fetch should hit the cache"


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
