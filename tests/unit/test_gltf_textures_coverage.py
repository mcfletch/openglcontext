"""Coverage tests for glTF image/texture decoding edge paths.

Real Pillow decoding of tiny in-memory PNGs (data-URI and bufferView sources),
plus the None/absent-source/undecodable guards in ``_image_pil``,
``_pil_for_texinfo`` and ``_texture_holder``.
"""
import base64
import io

import pytest

pygltflib = pytest.importorskip("pygltflib")
Image = pytest.importorskip("PIL.Image")
from pygltflib import (  # noqa: E402
    GLTF2, Image as GLTFImage, Sampler, Texture, BufferView, Buffer,
)

from OpenGLContext.loaders.gltf import textures as gtx  # noqa: E402
from OpenGLContext.loaders.gltf.textures import _TexInfo  # noqa: E402


class _R:
    def __init__(self, data=b''):
        self._buffers = {0: data}


def _png_bytes(color=(200, 100, 50), size=(2, 2)):
    buf = io.BytesIO()
    Image.new('RGB', size, color).save(buf, format='PNG')
    return buf.getvalue()


class TestImagePil:
    def test_data_uri_image_decoded_to_rgba(self):
        uri = 'data:image/png;base64,' + base64.b64encode(_png_bytes()).decode()
        g = GLTF2()
        g.images = [GLTFImage(uri=uri)]
        pim = gtx._image_pil(g, 0, _R())
        assert pim is not None and pim.mode == 'RGBA' and pim.size == (2, 2)

    def test_image_with_no_source_returns_none(self):
        # No bufferView and no uri -> nothing to decode.
        g = GLTF2()
        g.images = [GLTFImage()]
        assert gtx._image_pil(g, 0, _R()) is None


class TestPilForTexInfo:
    def _g_with_texture(self, png):
        g = GLTF2()
        g.images = [GLTFImage(bufferView=0, mimeType='image/png')]
        g.textures = [Texture(source=0)]
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=len(png))]
        g.buffers = [Buffer(byteLength=len(png))]
        return g

    def test_none_info_is_none(self):
        assert gtx._pil_for_texinfo(GLTF2(), None, _R()) is None

    def test_info_without_index_is_none(self):
        assert gtx._pil_for_texinfo(GLTF2(), _TexInfo({}), _R()) is None

    def test_texture_without_source_is_none(self):
        g = GLTF2()
        g.textures = [Texture()]         # no source, no webp extension
        assert gtx._pil_for_texinfo(g, _TexInfo({'index': 0}), _R()) is None

    def test_valid_texinfo_decodes_image(self):
        png = _png_bytes()
        g = self._g_with_texture(png)
        pim = gtx._pil_for_texinfo(g, _TexInfo({'index': 0}), _R(png))
        assert pim is not None and pim.size == (2, 2)

    def test_undecodable_image_logged_and_none(self, caplog):
        garbage = b'not a real image'
        g = self._g_with_texture(garbage)
        with caplog.at_level('WARNING'):
            assert gtx._pil_for_texinfo(g, _TexInfo({'index': 0}), _R(garbage)) is None
        assert any('spec/gloss' in r.getMessage() for r in caplog.records)


class TestTextureHolder:
    def test_none_index_is_none(self):
        assert gtx._texture_holder(GLTF2(), None, _R(), srgb=True, cache={}) is None

    def test_texture_without_source_is_none(self):
        g = GLTF2()
        g.textures = [Texture()]
        assert gtx._texture_holder(g, 0, _R(), srgb=True, cache={}) is None

    def test_undecodable_image_logged_and_none(self, caplog):
        garbage = b'still not an image'
        g = GLTF2()
        g.images = [GLTFImage(bufferView=0, mimeType='image/png')]
        g.textures = [Texture(source=0)]
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=len(garbage))]
        g.buffers = [Buffer(byteLength=len(garbage))]
        with caplog.at_level('WARNING'):
            holder = gtx._texture_holder(g, 0, _R(garbage), srgb=True, cache={})
        assert holder is None
        assert any('failed to decode image' in r.getMessage() for r in caplog.records)

    def test_sampler_wrap_filters_passed_through(self):
        png = _png_bytes()
        g = GLTF2()
        g.images = [GLTFImage(bufferView=0, mimeType='image/png')]
        g.samplers = [Sampler(wrapS=10497, wrapT=33071, minFilter=9729, magFilter=9728)]
        g.textures = [Texture(source=0, sampler=0)]
        g.bufferViews = [BufferView(buffer=0, byteOffset=0, byteLength=len(png))]
        g.buffers = [Buffer(byteLength=len(png))]
        cache = {}
        holder = gtx._texture_holder(g, 0, _R(png), srgb=True, cache=cache)
        assert holder is not None
        assert holder.wrap_s == 10497 and holder.mag_filter == 9728
        # The holder is memoised by texture index.
        assert gtx._texture_holder(g, 0, _R(png), srgb=True, cache=cache) is holder


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
