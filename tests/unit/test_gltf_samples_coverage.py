"""Coverage tests for the Khronos sample-catalogue helpers.

No real network: ``_fetch_url`` and ``load_gltf_url`` are monkeypatched so the
Models.md parser and the load_sample variant-fallback loop run offline.
"""
import pytest

from OpenGLContext.loaders.gltf import samples


class TestCatalogParsingSkipsNonMatchingRows:
    def test_row_starting_with_bracket_but_no_link_is_skipped(self, monkeypatch):
        # A line that begins with '| [' (so it passes the cheap prefix filter) but
        # does not match the model-link regex must be skipped, not parsed.
        md = (
            "| [NotAModelLink no closing paren | junk |\n"
            "| [Box](Box/README.md)<br>"
            "[![Box](Box/screenshot/screenshot.jpg)](Box/README.md) | a box |\n"
        )
        monkeypatch.setattr(samples, '_fetch_url',
                            lambda url, cache=None: md.encode('utf-8'))
        rows = samples.fetch_sample_catalog()
        assert [r['name'] for r in rows] == ['Box']
        assert rows[0]['screenshot_url'].endswith('Box/screenshot/screenshot.jpg')


class TestLoadSampleVariantFallback:
    def test_first_successful_variant_returned(self, monkeypatch):
        seen = []

        def fake_load(url, cache_dir=None):
            seen.append(url)
            return 'SCENE'

        monkeypatch.setattr('OpenGLContext.loaders.gltf.load_gltf_url', fake_load)
        assert samples.load_sample('Box') == 'SCENE'
        # It tries the self-contained .glb variant first and stops there.
        assert seen == [samples.SAMPLE_MODELS_BASE + '/Box/glTF-Binary/Box.glb']

    def test_all_variants_fail_reraises_last_error(self, monkeypatch):
        attempts = []

        def fake_load(url, cache_dir=None):
            attempts.append(url)
            raise IOError("no such variant: %s" % url)

        monkeypatch.setattr('OpenGLContext.loaders.gltf.load_gltf_url', fake_load)
        with pytest.raises(IOError, match='no such variant'):
            samples.load_sample('Box')
        assert len(attempts) == 3      # glb, gltf, embedded all tried


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
