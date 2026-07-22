"""glTF loader hardening.

5a: `max_resource_bytes` bounded only *external* references; a large in-memory
    .glb/.gltf (the documented upload path) or a local file was parsed with no
    ceiling. `load_gltf` now size-caps the primary document too.
5c: an unknown accessor `componentType`/`type` raised a bare `KeyError`; it now
    raises the located `ValueError` used elsewhere in the loader.
"""
import types

import pytest

pytest.importorskip("pygltflib")
from OpenGLContext.loaders import gltf


class TestAccessorEnumErrors:
    def test_unknown_component_type_is_valueerror(self):
        with pytest.raises(ValueError) as exc:
            gltf.accessors._component_dtype(9999)
        assert 'componentType' in str(exc.value)

    def test_unknown_accessor_type_is_valueerror(self):
        with pytest.raises(ValueError) as exc:
            gltf.accessors._type_count('VEC7')
        assert 'type' in str(exc.value)

    def test_known_values_still_resolve(self):
        assert gltf.accessors._component_dtype(gltf.accessors._COMPONENT_FLOAT) is not None
        assert gltf.accessors._type_count('VEC3') == 3


class TestPrimaryDocumentSizeCap:
    def test_oversized_bytes_document_rejected(self):
        big = b'{' + b' ' * 5000 + b'}'
        with pytest.raises(ValueError) as exc:
            gltf.load_gltf(big, max_resource_bytes=1000)
        assert 'over the' in str(exc.value) or 'limit' in str(exc.value)

    def test_oversized_local_file_rejected(self, tmp_path):
        p = tmp_path / 'big.gltf'
        p.write_bytes(b'{' + b' ' * 5000 + b'}')
        with pytest.raises(ValueError):
            gltf.load_gltf(str(p), max_resource_bytes=1000)

    def test_size_check_precedes_parsing(self, monkeypatch):
        # The cap must trip before pygltflib touches the (malformed) payload, so a
        # decompression-bomb style document is rejected without being parsed.
        called = {'n': 0}
        real = gltf.loader._require_pygltflib()

        class Guard:
            @staticmethod
            def load_from_bytes(*a, **k):
                called['n'] += 1
                return real.load_from_bytes(*a, **k)

            @staticmethod
            def from_json(*a, **k):
                called['n'] += 1
                return real.from_json(*a, **k)
        monkeypatch.setattr(gltf.loader, '_require_pygltflib', lambda: Guard)
        with pytest.raises(ValueError):
            gltf.load_gltf(b'glTF' + b'\x00' * 4000, max_resource_bytes=100)
        assert called['n'] == 0, "document must be rejected before parsing"
