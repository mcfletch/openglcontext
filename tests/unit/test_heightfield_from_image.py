"""Tests for :meth:`HeightField.from_image` bit-depth handling (no GL context).

The loader must scale each heightmap by a divisor matching the image's real bit
depth. Reading an 8-bit DEM as if it were 16-bit collapses the terrain to a
near-flat 0..0.004 band, and a multi-channel image would hand ``sample``/``mesh``
a 3-D grid. These check that each mode yields a full-relief 0..1 grid and that
sampling lands on the encoded texel value.
"""
import numpy as np
import pytest
from PIL import Image

from OpenGLContext.scenegraph.terrain import HeightField


def _save(tmp_path, name, arr, mode):
    p = tmp_path / name
    Image.fromarray(arr, mode=mode).save(p)
    return str(p)


def test_8bit_ramp_spans_full_relief_not_flat(tmp_path):
    """An 8-bit grayscale ramp must use the full relief, not collapse near zero."""
    R = 16
    row = np.linspace(0, 255, R).astype(np.uint8)
    arr = np.tile(row, (R, 1))
    path = _save(tmp_path, "ramp8.png", arr, "L")
    hf = HeightField.from_image(path, R, 100.0, 50.0)
    z = hf.grid * hf.relief
    assert z.min() == pytest.approx(0.0, abs=1e-6)
    assert z.max() == pytest.approx(50.0, abs=1e-6)     # full black->white uses full relief
    # the /65535 bug would cap the peak near 50*255/65535 ~= 0.19
    assert z.max() > 25.0


def test_16bit_scales_by_65535(tmp_path):
    """A known 16-bit value round-trips as value/65535 in the normalized grid."""
    R = 8
    arr = np.full((R, R), 32768, np.uint16)
    path = _save(tmp_path, "flat16.png", arr, "I;16")
    hf = HeightField.from_image(path, R, 100.0, 50.0)
    np.testing.assert_allclose(hf.grid, 32768 / 65535.0, rtol=1e-6)


def test_16bit_full_range_uses_full_relief(tmp_path):
    R = 16
    row = np.linspace(0, 65535, R).astype(np.uint16)
    arr = np.tile(row, (R, 1))
    path = _save(tmp_path, "ramp16.png", arr, "I;16")
    hf = HeightField.from_image(path, R, 100.0, 40.0)
    z = hf.grid * hf.relief
    assert z.min() == pytest.approx(0.0, abs=1e-4)
    assert z.max() == pytest.approx(40.0, abs=1e-4)


def test_rgb_loads_via_luminance_as_2d(tmp_path):
    """An RGB image folds to a single 2-D luminance channel rather than breaking."""
    R = 8
    rgb = np.zeros((R, R, 3), np.uint8)
    rgb[..., :] = 255                                   # white -> luminance 255 -> 1.0
    path = _save(tmp_path, "white.png", rgb, "RGB")
    hf = HeightField.from_image(path, R, 100.0, 50.0)
    assert hf.grid.ndim == 2
    np.testing.assert_allclose(hf.grid, 1.0, atol=1e-6)


def test_unsupported_mode_raises(tmp_path):
    """A mode with no defined height scaling raises rather than producing garbage."""
    R = 8
    arr = np.zeros((R, R, 4), np.uint8)
    p = tmp_path / "cmyk.tiff"
    Image.fromarray(arr, mode="RGBA").convert("CMYK").save(p)
    with pytest.raises(ValueError):
        HeightField.from_image(str(p), R, 100.0, 50.0)


def test_non_2d_resample_result_raises(tmp_path, monkeypatch):
    """If resampling yields more than one channel the loader refuses it rather than
    passing a 3-D grid downstream. The accepted modes all fold to 2-D, so this
    guard is provoked by forcing resize() to hand back a multi-channel image."""
    R = 8
    arr = np.tile(np.linspace(0, 255, R).astype(np.uint8), (R, 1))
    path = _save(tmp_path, "ramp_guard.png", arr, "L")

    real_resize = Image.Image.resize

    def _rgb_resize(self, *a, **k):
        return real_resize(self, *a, **k).convert("RGB")   # 3 channels -> ndim 3

    monkeypatch.setattr(Image.Image, "resize", _rgb_resize)
    with pytest.raises(ValueError, match="single 2-D channel"):
        HeightField.from_image(path, R, 100.0, 50.0)


def test_sample_at_texel_matches_image_value(tmp_path):
    """sample() at the grid corner returns that texel's encoded height."""
    R = 8
    row = np.linspace(0, 255, R).astype(np.uint8)
    arr = np.tile(row, (R, 1))                          # rises along x (columns)
    path = _save(tmp_path, "ramp8b.png", arr, "L")
    E, relief = 100.0, 50.0
    hf = HeightField.from_image(path, R, E, relief)
    # world x = +E/2 lands on the last column (u = 1.0) -> full relief
    assert hf.height_at(E / 2, 0.0) == pytest.approx(relief, abs=1e-4)
    # world x = -E/2 lands on the first column (u = 0.0) -> zero
    assert hf.height_at(-E / 2, 0.0) == pytest.approx(0.0, abs=1e-4)
    # a middle column matches grid[z_index, x_index] * relief exactly
    mid = R // 2
    x = -E / 2 + mid / (R - 1) * E
    assert hf.height_at(x, 0.0) == pytest.approx(hf.grid[0, mid] * relief, abs=1e-4)


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
