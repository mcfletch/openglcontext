"""OpenEXR panoramas, and the one rule for which files are panoramas.

The EXR files are written here with the OpenEXR bindings themselves, so the
test reads what that library writes rather than a fixture of unknown origin.
"""
import sys

import numpy as np
import pytest

from OpenGLContext.loaders import panorama

OpenEXR = pytest.importorskip('OpenEXR')


def _write_exr(path, channels, compression=None):
    header = {'compression': compression or OpenEXR.ZIP_COMPRESSION,
              'type': OpenEXR.scanlineimage}
    with OpenEXR.File(header, channels) as out:
        out.write(str(path))
    return str(path)


def _gradient(height=4, width=8):
    """Radiance well above 1, distinct per channel and per pixel."""
    y, x = np.mgrid[0:height, 0:width].astype(np.float32)
    return np.stack([x * 10.0, y * 100.0, x + y + 0.5], axis=-1)


class TestLoadExr:
    def test_rgb_channels_load_as_linear_float32_top_row_first(self, tmp_path):
        rgb = _gradient()
        path = _write_exr(tmp_path / 'sky.exr', {'RGB': rgb})
        image = panorama.load_panorama(path)
        assert image.dtype == np.float32
        assert image.shape == (4, 8, 3)
        np.testing.assert_array_equal(image, rgb)

    def test_alpha_is_dropped(self, tmp_path):
        rgb = _gradient()
        rgba = np.concatenate([rgb, np.ones(rgb.shape[:2] + (1,), np.float32)], -1)
        path = _write_exr(tmp_path / 'sky.exr', {'RGBA': rgba})
        np.testing.assert_array_equal(panorama.load_panorama(path), rgb)

    def test_half_float_channels_are_widened(self, tmp_path):
        rgb = _gradient().astype(np.float16)
        path = _write_exr(tmp_path / 'sky.exr', {'RGB': rgb})
        image = panorama.load_panorama(path)
        assert image.dtype == np.float32
        np.testing.assert_array_equal(image, rgb.astype(np.float32))

    def test_piz_compression_is_read(self, tmp_path):
        rgb = _gradient(16, 32)
        path = _write_exr(tmp_path / 'sky.exr', {'RGB': rgb},
                          compression=OpenEXR.PIZ_COMPRESSION)
        np.testing.assert_array_equal(panorama.load_panorama(path), rgb)

    def test_a_luminance_image_is_grey(self, tmp_path):
        luminance = _gradient()[..., 1].copy()
        path = _write_exr(tmp_path / 'sky.exr', {'Y': luminance})
        image = panorama.load_panorama(path)
        for channel in range(3):
            np.testing.assert_array_equal(image[..., channel], luminance)

    def test_an_image_with_no_colour_channels_is_refused(self, tmp_path):
        path = _write_exr(tmp_path / 'depth.exr', {'Z': _gradient()[..., 0].copy()})
        with pytest.raises(panorama.PanoramaError, match='Z'):
            panorama.load_panorama(path)

    def test_a_file_that_is_not_exr_is_refused(self, tmp_path):
        path = tmp_path / 'sky.exr'
        path.write_bytes(b'not an image at all')
        with pytest.raises(panorama.PanoramaError):
            panorama.load_panorama(str(path))

    def test_without_the_bindings_the_error_names_the_extra(self, tmp_path,
                                                            monkeypatch):
        path = _write_exr(tmp_path / 'sky.exr', {'RGB': _gradient()})
        monkeypatch.setitem(sys.modules, 'OpenEXR', None)
        with pytest.raises(ImportError, match=r'OpenGLContext\[exr\]'):
            panorama.load_panorama(path)


class TestWhichFilesArePanoramas:
    @pytest.mark.parametrize('spec', [
        '/x/sky.hdr', 'foo.pic', 'sky.EXR', '/x/186_hdrmaps_com_free_2K.exr',
        'https://ex.com/a/sky.exr?token=1', 'https://ex.com/a/sky.hdr#frag'])
    def test_panoramas(self, spec):
        assert panorama.is_panorama(spec)

    @pytest.mark.parametrize('spec', ['', '/env/pimbackground_', 'sky.png',
                                      'sky.exr.txt'])
    def test_not_panoramas(self, spec):
        assert not panorama.is_panorama(spec)

    def test_the_probe_decodes_an_exr(self, tmp_path):
        from OpenGLContext.passes import ibl
        rgb = _gradient()
        path = _write_exr(tmp_path / 'sky.exr', {'RGB': rgb})
        np.testing.assert_array_equal(ibl.load_equirect_hdr(path), rgb)

    def test_the_probe_still_decodes_radiance(self, tmp_path):
        from OpenGLContext.passes import ibl
        from tests.unit.test_hdr_loader import encode_new_rle, float_to_rgbe
        rgb = _gradient()
        path = tmp_path / 'sky.hdr'
        path.write_bytes(encode_new_rle(rgb))
        from OpenGLContext.loaders.hdr import rgbe_to_float
        np.testing.assert_allclose(ibl.load_equirect_hdr(str(path)),
                                   rgbe_to_float(float_to_rgbe(rgb)))
