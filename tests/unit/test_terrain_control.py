"""Deciding which ground material shows where.

A splat terrain blends up to four detail materials by an RGBA control map: red
is how much of the first layer shows at that spot, green the second, and so on.
Painting one by hand is how a landscape artist works; deriving one from the land
is how a generated world gets its ground, and that is what is here -- grass on
the flat, rock where it is too steep for soil to stay, shingle at the waterline,
whatever the rules say.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain.control import LayerRule, control_map
from OpenGLContext.scenegraph.terrain.heightfield import HeightField

EXTENT = 400.0


def _slope_field(res=65, rise=200.0):
    """Level in the west, a one-in-one wall in the east."""
    axis = np.linspace(0.0, 1.0, res)
    grid = np.tile(np.clip((axis - 0.5) * 2.0, 0.0, 1.0) ** 3, (res, 1))
    return HeightField(grid, EXTENT, rise)


def _weights(image, x, z, extent=EXTENT):
    """The RGBA weights the map gives at a world position."""
    pixels = np.asarray(image.convert('RGBA'), dtype='d') / 255.0
    size = pixels.shape[0]
    u = int(np.clip((x + extent / 2) / extent * (size - 1), 0, size - 1))
    v = int(np.clip((z + extent / 2) / extent * (size - 1), 0, size - 1))
    return pixels[v, u]


class TestWhatComesOut:
    def test_it_is_an_rgba_image(self) -> None:
        found = control_map(_slope_field(), [LayerRule()], size=64)
        assert found.mode == 'RGBA'
        assert found.size == (64, 64)

    def test_a_single_rule_covers_everything(self) -> None:
        found = control_map(_slope_field(), [LayerRule()], size=64)
        assert _weights(found, 0.0, 0.0)[0] == pytest.approx(1.0, abs=0.02)

    def test_four_layers_are_the_four_channels(self) -> None:
        rules = [LayerRule(), LayerRule(), LayerRule(), LayerRule()]
        found = control_map(_slope_field(), rules, size=32)
        assert _weights(found, 0.0, 0.0)[:4] == pytest.approx(
            [0.25, 0.25, 0.25, 0.25], abs=0.02)

    def test_the_weights_add_up(self) -> None:
        """Or the ground is dark where they fall short and blown out where they
        overshoot."""
        rules = [LayerRule(slope=(0.0, 0.3)), LayerRule(slope=(0.5, 9.0)),
                 LayerRule(height=(150.0, 400.0))]
        found = control_map(_slope_field(), rules, size=64)
        pixels = np.asarray(found.convert('RGBA'), dtype='d') / 255.0
        assert np.abs(pixels.sum(axis=-1) - 1.0).max() < 0.02

    def test_more_than_four_layers_is_refused(self) -> None:
        with pytest.raises(ValueError):
            control_map(_slope_field(), [LayerRule()] * 5, size=32)

    def test_no_layers_at_all_is_refused(self) -> None:
        with pytest.raises(ValueError):
            control_map(_slope_field(), [], size=32)


class TestTheRules:
    def test_a_slope_rule_shows_on_the_steep_ground(self) -> None:
        rules = [LayerRule(slope=(0.0, 0.2)), LayerRule(slope=(0.6, 20.0))]
        found = control_map(_slope_field(), rules, size=128)
        flat = _weights(found, -150.0, 0.0)
        steep = _weights(found, 180.0, 0.0)
        assert flat[0] > flat[1]
        assert steep[1] > steep[0]

    def test_a_height_rule_shows_at_its_elevation(self) -> None:
        rules = [LayerRule(height=(-100.0, 20.0)), LayerRule(height=(120.0, 400.0))]
        found = control_map(_slope_field(), rules, size=128)
        assert _weights(found, -180.0, 0.0)[0] > 0.8
        assert _weights(found, 190.0, 0.0)[1] > 0.8

    def test_a_band_fades_at_its_edges_rather_than_cutting(self) -> None:
        """A hard edge between two ground materials reads as a painted line."""
        rules = [LayerRule(height=(-100.0, 100.0), feather=40.0),
                 LayerRule(height=(100.0, 400.0), feather=40.0)]
        found = control_map(_slope_field(), rules, size=256)
        pixels = np.asarray(found.convert('RGBA'), dtype='d')[..., 0] / 255.0
        # Somewhere the first layer is neither all nor nothing.
        assert ((pixels > 0.2) & (pixels < 0.8)).any()

    def test_a_rule_can_be_weighted_up(self) -> None:
        rules = [LayerRule(weight=3.0), LayerRule(weight=1.0)]
        found = control_map(_slope_field(), rules, size=32)
        assert _weights(found, 0.0, 0.0)[0] == pytest.approx(0.75, abs=0.02)

    def test_ground_no_rule_wants_falls_to_the_first_layer(self) -> None:
        """Somewhere every rule is out of its band, and unpainted ground is
        worse than ground painted with the wrong thing."""
        rules = [LayerRule(height=(-1000.0, -900.0)),
                 LayerRule(height=(900.0, 1000.0))]
        found = control_map(_slope_field(), rules, size=32)
        assert _weights(found, 0.0, 0.0)[0] == pytest.approx(1.0, abs=0.02)

    def test_the_datum_is_the_height_a_rule_talks_about(self) -> None:
        """A rule saying 'below ten metres' means ten metres above sea level,
        not ten above whatever the lowest point of this map happens to be."""
        grid = np.tile(np.linspace(0.0, 1.0, 65), (65, 1))
        low = HeightField(grid, EXTENT, 100.0, base=-50.0)
        rules = [LayerRule(height=(-100.0, 0.0)), LayerRule(height=(0.0, 100.0))]
        found = control_map(low, rules, size=128)
        assert _weights(found, -180.0, 0.0)[0] > 0.8
        assert _weights(found, 180.0, 0.0)[1] > 0.8


class TestPaintedOver:
    def test_a_mask_forces_a_layer_where_it_is_set(self) -> None:
        """A road's corridor, a lake bed, a clearing: something the rules cannot
        know about, painted over what they decided."""
        field = _slope_field()
        size = 64
        corridor = np.zeros((size, size))
        corridor[:, :size // 4] = 1.0
        found = control_map(field, [LayerRule(), LayerRule()], size=size,
                            painted=[(1, corridor)])
        assert _weights(found, -190.0, 0.0)[1] > 0.95

    def test_it_leaves_the_rest_to_the_rules(self) -> None:
        field = _slope_field()
        size = 64
        corridor = np.zeros((size, size))
        corridor[:, :size // 4] = 1.0
        plain = control_map(field, [LayerRule(), LayerRule()], size=size)
        painted = control_map(field, [LayerRule(), LayerRule()], size=size,
                              painted=[(1, corridor)])
        assert _weights(painted, 190.0, 0.0) == pytest.approx(
            _weights(plain, 190.0, 0.0), abs=0.02)

    def test_a_partial_mask_blends(self) -> None:
        field = _slope_field()
        size = 64
        half = np.full((size, size), 0.5)
        found = control_map(field, [LayerRule(), LayerRule()], size=size,
                            painted=[(1, half)])
        assert _weights(found, 0.0, 0.0)[1] == pytest.approx(0.75, abs=0.03)

    def test_the_weights_still_add_up(self) -> None:
        field = _slope_field()
        size = 64
        blob = np.zeros((size, size))
        blob[16:48, 16:48] = 1.0
        found = control_map(field, [LayerRule(), LayerRule(), LayerRule()],
                            size=size, painted=[(2, blob)])
        pixels = np.asarray(found.convert('RGBA'), dtype='d') / 255.0
        assert np.abs(pixels.sum(axis=-1) - 1.0).max() < 0.02

    def test_a_mask_of_the_wrong_size_is_refused(self) -> None:
        with pytest.raises(ValueError):
            control_map(_slope_field(), [LayerRule(), LayerRule()], size=64,
                        painted=[(1, np.zeros((8, 8)))])

    def test_a_mask_for_a_layer_that_is_not_there_is_refused(self) -> None:
        with pytest.raises(ValueError):
            control_map(_slope_field(), [LayerRule()], size=64,
                        painted=[(3, np.zeros((64, 64)))])


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
