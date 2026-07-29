"""Reference screenshots are disk-cached through the same sha1-keyed cache as the
model files, so the regression report can embed the upstream Khronos image
offline after the first run (no network on rerun)."""
import os

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders import resolver


CATALOG = [
    {'name': 'Widget', 'display': 'Widget',
     'screenshot_url': 'https://example.invalid/Widget/screenshot/x.jpg'},
]


def test_returns_deterministic_cache_path_and_fetches_once(monkeypatch, tmp_path):
    reads = []
    monkeypatch.setattr(gltf.samples, 'fetch_sample_catalog',
                        lambda cache_dir=None: CATALOG)

    class _Resp:
        """Serves its body once and is then exhausted, as a real one is."""

        def __init__(self):
            self._left = b'\x89PNG'

        def read(self, n=-1):
            if self._left:
                reads.append(1)
            data, self._left = self._left, b''
            return data

        def close(self):
            pass

    class _Opener:
        def open(self, url, timeout=None):
            return _Resp()
    monkeypatch.setattr(resolver.urllib.request, 'build_opener',
                        lambda *a, **k: _Opener())

    url = CATALOG[0]['screenshot_url']
    path = gltf.cache_reference_screenshot('Widget', cache_dir=str(tmp_path))
    # the resolver owns the cache-path formula; the caller must not re-derive it
    assert path == resolver.cached_path(url, str(tmp_path))
    assert os.path.exists(path)
    # a second call is served from the cache -- no new network read
    gltf.cache_reference_screenshot('Widget', cache_dir=str(tmp_path))
    assert len(reads) == 1


def test_unknown_model_returns_none(monkeypatch, tmp_path):
    monkeypatch.setattr(gltf.samples, 'fetch_sample_catalog', lambda cache_dir=None: CATALOG)
    assert gltf.cache_reference_screenshot('Nope', cache_dir=str(tmp_path)) is None


def test_reference_screenshot_url_lookup(monkeypatch):
    monkeypatch.setattr(gltf.samples, 'fetch_sample_catalog', lambda cache_dir=None: CATALOG)
    assert gltf.reference_screenshot_url('Widget') == CATALOG[0]['screenshot_url']
    assert gltf.reference_screenshot_url('Nope') is None
