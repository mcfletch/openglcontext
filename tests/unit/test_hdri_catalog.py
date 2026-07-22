"""The bundled CC0 HDRI catalogue: name resolution + provenance."""
import pytest

from OpenGLContext.loaders import hdri


def test_catalog_names_resolve_to_urls():
    for name, entry in hdri.CATALOG.items():
        url = hdri.resolve(name)
        assert url.startswith('https://')
        assert url.lower().endswith('.hdr')
        assert entry.license == 'CC0'          # only freely-licensed sources bundled
        assert entry.url == url


def test_resolve_passes_through_urls_and_paths():
    assert hdri.resolve('https://example.com/foo.hdr') == 'https://example.com/foo.hdr'
    assert hdri.resolve('/local/thing.hdr') == '/local/thing.hdr'


def test_resolve_accepts_provider_prefixed_name():
    # "polyhaven:studio_small_03" and bare "studio_small_03" both resolve.
    bare = hdri.resolve('studio_small_03')
    pref = hdri.resolve('polyhaven:studio_small_03')
    assert bare == pref
    assert 'studio_small_03' in bare


def test_unknown_name_is_an_error():
    with pytest.raises(KeyError):
        hdri.resolve('no_such_hdri_name')


def test_default_name_is_in_catalog():
    assert hdri.DEFAULT in hdri.CATALOG
    assert hdri.default_url() == hdri.CATALOG[hdri.DEFAULT].url


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
