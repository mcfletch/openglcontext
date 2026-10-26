"""The image arithmetic behind an OBJ material's maps: channels, packing, bump slopes.

Pure NumPy and PIL; every image here is a few pixels, written by the test.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.loaders.mtlfile import TextureMap
from OpenGLContext.loaders.objimages import (
    alpha_mode, channel_values, combine_metallic_roughness, looks_like_normal_map,
    normal_from_height, with_alpha,
)


def grey(values: list[list[int]]) -> Image.Image:
    return Image.fromarray(np.array(values, dtype=np.uint8), 'L')


def rgb(red: int, green: int, blue: int, size: tuple[int, int] = (4, 4)) -> Image.Image:
    return Image.new('RGB', size, (red, green, blue))


class TestChannelValues:
    def test_default_is_the_luminance(self) -> None:
        values = channel_values(rgb(255, 255, 255), TextureMap('a.png'))
        assert values.shape == (4, 4) and values.dtype == np.float32
        assert np.allclose(values, 1.0)

    def test_a_grey_image_reads_as_itself(self) -> None:
        values = channel_values(grey([[0, 128], [255, 64]]), TextureMap('a.png'))
        assert np.allclose(values, [[0, 128 / 255], [1, 64 / 255]], atol=1 / 255)

    @pytest.mark.parametrize('channel, expected', [('r', 1.0), ('g', 0.0), ('b', 0.5)])
    def test_imfchan_picks_a_colour_channel(self, channel: str, expected: float) -> None:
        values = channel_values(rgb(255, 0, 128), TextureMap('a.png', channel=channel))
        assert np.allclose(values, expected, atol=1 / 255)

    def test_matte_is_the_alpha_channel(self) -> None:
        image = Image.new('RGBA', (2, 2), (255, 255, 255, 64))
        values = channel_values(image, TextureMap('a.png', channel='m'))
        assert np.allclose(values, 64 / 255, atol=1 / 255)

    def test_matte_of_an_image_with_no_alpha_is_opaque(self) -> None:
        assert np.allclose(channel_values(rgb(0, 0, 0), TextureMap('a.png', channel='m')), 1.0)

    def test_mm_remaps_the_range(self) -> None:
        values = channel_values(grey([[0, 255]]), TextureMap('a.png', base=0.25, gain=0.5))
        assert np.allclose(values, [[0.25, 0.75]], atol=1 / 255)

    def test_mm_results_stay_in_range(self) -> None:
        values = channel_values(grey([[0, 255]]), TextureMap('a.png', base=-1.0, gain=4.0))
        assert values.min() >= 0.0 and values.max() <= 1.0


class TestCombineMetallicRoughness:
    def test_roughness_is_green_and_metallic_is_blue(self) -> None:
        rough = np.full((2, 2), 0.25, np.float32)
        metal = np.full((2, 2), 0.75, np.float32)
        pixel = combine_metallic_roughness(rough, metal).getpixel((0, 0))
        assert pixel[1] == pytest.approx(64, abs=1)
        assert pixel[2] == pytest.approx(191, abs=1)

    def test_a_missing_map_leaves_its_channel_at_full(self) -> None:
        rough = np.full((2, 2), 0.5, np.float32)
        pixel = combine_metallic_roughness(rough, None).getpixel((0, 0))
        assert pixel[2] == 255
        pixel = combine_metallic_roughness(None, rough).getpixel((0, 0))
        assert pixel[1] == 255

    def test_maps_of_different_sizes_meet_at_the_larger(self) -> None:
        rough = np.zeros((2, 2), np.float32)
        metal = np.ones((8, 4), np.float32)
        assert combine_metallic_roughness(rough, metal).size == (4, 8)

    def test_neither_map_is_an_error(self) -> None:
        with pytest.raises(ValueError):
            combine_metallic_roughness(None, None)


class TestNormalFromHeight:
    def test_a_flat_height_map_is_a_flat_normal_map(self) -> None:
        image = normal_from_height(np.full((4, 4), 0.5, np.float32), 1.0)
        assert image.mode == 'RGB'
        assert image.getpixel((1, 1)) == (128, 128, 255)

    def test_height_rising_to_the_right_tilts_the_normal_left(self) -> None:
        height = np.tile(np.linspace(0, 1, 8, dtype=np.float32), (8, 1))
        red, green, blue = normal_from_height(height, 1.0).getpixel((4, 4))
        assert red < 128 and abs(green - 128) <= 1 and blue > 128

    def test_height_falling_down_the_image_tilts_the_normal_up(self) -> None:
        # Rows run top to bottom and v runs bottom to top, so height rising down
        # the rows falls with v, and the surface faces toward +v.
        height = np.tile(np.linspace(0, 1, 8, dtype=np.float32)[:, None], (1, 8))
        _, green, _ = normal_from_height(height, 1.0).getpixel((4, 4))
        assert green > 128

    def test_strength_deepens_the_slope(self) -> None:
        height = np.tile(np.linspace(0, 1, 8, dtype=np.float32), (8, 1))
        weak = normal_from_height(height, 0.5).getpixel((4, 4))[0]
        strong = normal_from_height(height, 4.0).getpixel((4, 4))[0]
        assert strong < weak < 128

    def test_the_map_tiles(self) -> None:
        # The edge reads across to the opposite edge rather than stopping.
        height = np.zeros((4, 4), np.float32)
        height[:, 0] = 1.0
        left = normal_from_height(height, 1.0).getpixel((3, 1))
        assert left[0] != 128


class TestLooksLikeNormalMap:
    def test_the_violet_of_a_flat_tangent_space_normal_map(self) -> None:
        assert looks_like_normal_map(rgb(128, 128, 255))

    def test_a_grey_height_map_is_not(self) -> None:
        assert not looks_like_normal_map(rgb(128, 128, 128))
        assert not looks_like_normal_map(grey([[0, 255], [255, 0]]))

    def test_a_colour_photograph_is_not(self) -> None:
        assert not looks_like_normal_map(rgb(200, 120, 40))

    def test_a_bumpy_normal_map_is(self) -> None:
        rng = np.random.default_rng(1)
        data = np.stack([128 + rng.integers(-30, 30, (16, 16)),
                         128 + rng.integers(-30, 30, (16, 16)),
                         np.full((16, 16), 240)], axis=-1).astype(np.uint8)
        assert looks_like_normal_map(Image.fromarray(data, 'RGB'))


class TestAlpha:
    def test_a_mask_of_zeros_and_ones_is_a_cutout(self) -> None:
        assert alpha_mode(np.array([[0.0, 1.0], [1.0, 0.0]], np.float32)) == 'MASK'

    def test_a_gradient_blends(self) -> None:
        assert alpha_mode(np.linspace(0, 1, 100, dtype=np.float32).reshape(10, 10)) == 'BLEND'

    def test_antialiased_edges_still_cut_out(self) -> None:
        alpha = np.ones((32, 32), np.float32)
        alpha[:, :16] = 0.0
        alpha[:, 16] = 0.5
        assert alpha_mode(alpha) == 'MASK'

    def test_an_opaque_mask_needs_no_alpha_mode_change(self) -> None:
        assert alpha_mode(np.ones((4, 4), np.float32)) == 'OPAQUE'


class TestWithAlpha:
    def test_a_colour_image_gains_the_mask_as_alpha(self) -> None:
        image = with_alpha(rgb(10, 20, 30, (2, 2)), np.array([[0.0, 1.0], [0.5, 1.0]], np.float32))
        assert image.mode == 'RGBA'
        assert image.getpixel((0, 0)) == (10, 20, 30, 0)
        assert image.getpixel((1, 0))[3] == 255

    def test_no_colour_image_means_white(self) -> None:
        image = with_alpha(None, np.zeros((2, 2), np.float32))
        assert image.getpixel((0, 0)) == (255, 255, 255, 0)

    def test_a_mask_of_another_size_is_resampled_to_the_image(self) -> None:
        image = with_alpha(rgb(1, 2, 3, (8, 8)), np.ones((2, 2), np.float32))
        assert image.size == (8, 8)
