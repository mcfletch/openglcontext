"""A height field over ground that is not at sea level, and one from a function.

The grid a height field holds is normalised 0..1 and scaled by its relief, which
puts the lowest point of a landscape at zero. Real ground does not start there:
a lake bed is below the datum and a valley floor is a long way above it. So a
field carries the world height its grid's zero stands at, and everything that
reads a height adds it.

:meth:`HeightField.from_function` is the other half: a landscape described by a
height function -- which is how one is authored -- sampled into the grid a
renderer and a collider can use, with the datum and the relief taken from what
the function actually does over that square.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain.heightfield import HeightField

EXTENT = 400.0


def _ramp(res=17):
    """A grid running 0 to 1 west to east."""
    return np.tile(np.linspace(0.0, 1.0, res), (res, 1))


def _bowl(x, z):
    """Ground from -60 m in a basin to +140 m on the rim."""
    r = np.hypot(np.asarray(x, 'd'), np.asarray(z, 'd')) / (EXTENT / 2.0)
    return -60.0 + 200.0 * np.clip(r, 0.0, 1.0) ** 2


class TestTheDatum:
    def test_a_field_without_one_starts_at_zero(self) -> None:
        field = HeightField(_ramp(), EXTENT, 100.0)
        assert float(field.sample(-EXTENT / 2, 0.0)) == pytest.approx(0.0)

    def test_a_datum_lifts_the_whole_field(self) -> None:
        field = HeightField(_ramp(), EXTENT, 100.0, base=-60.0)
        assert float(field.sample(-EXTENT / 2, 0.0)) == pytest.approx(-60.0)
        assert float(field.sample(EXTENT / 2, 0.0)) == pytest.approx(40.0)

    def test_the_relief_is_still_the_relief(self) -> None:
        field = HeightField(_ramp(), EXTENT, 100.0, base=-60.0)
        low = float(field.sample(-EXTENT / 2, 0.0))
        high = float(field.sample(EXTENT / 2, 0.0))
        assert high - low == pytest.approx(100.0)

    def test_the_mesh_stands_at_the_datum_too(self) -> None:
        """Or the ground a camera walks on is not the ground it sees."""
        field = HeightField(_ramp(), EXTENT, 100.0, base=-60.0)
        vertices, _indices = field.mesh()
        assert float(vertices[:, 1].min()) == pytest.approx(-60.0, abs=1e-4)

    def test_the_slope_does_not_care_about_the_datum(self) -> None:
        flat = HeightField(_ramp(), EXTENT, 100.0)
        lifted = HeightField(_ramp(), EXTENT, 100.0, base=-60.0)
        assert float(lifted.slope(10.0, 10.0)) == pytest.approx(
            float(flat.slope(10.0, 10.0)))

    def test_it_reads_back_off_the_field(self) -> None:
        assert HeightField(_ramp(), EXTENT, 100.0, base=-60.0).base == -60.0


class TestFromAFunction:
    def test_it_samples_the_function(self) -> None:
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT)
        assert float(field.sample(0.0, 0.0)) == pytest.approx(-60.0, abs=1.0)

    def test_the_rim_comes_out_at_the_rim(self) -> None:
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT)
        assert float(field.sample(EXTENT / 2, 0.0)) == pytest.approx(140.0, abs=1.0)

    def test_the_datum_is_the_lowest_ground_it_found(self) -> None:
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT)
        assert field.base == pytest.approx(-60.0, abs=1.0)

    def test_the_relief_is_what_the_ground_actually_does(self) -> None:
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT)
        assert field.relief == pytest.approx(200.0, abs=1.0)

    def test_the_grid_uses_its_whole_range(self) -> None:
        """Or a landscape is quantised into a fraction of the depth it is
        written to."""
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT)
        assert field.grid.min() == pytest.approx(0.0, abs=1e-9)
        assert field.grid.max() == pytest.approx(1.0, abs=1e-9)

    def test_a_datum_and_relief_can_be_given_instead(self) -> None:
        """Two fields of one landscape have to agree, or they meet in a step."""
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT,
                                          base=-100.0, relief=400.0)
        assert (field.base, field.relief) == (-100.0, 400.0)
        assert float(field.sample(0.0, 0.0)) == pytest.approx(-60.0, abs=1.0)

    def test_ground_outside_a_given_range_is_held_at_its_edge(self) -> None:
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT,
                                          base=0.0, relief=100.0)
        assert float(field.sample(0.0, 0.0)) == pytest.approx(0.0)
        assert float(field.sample(EXTENT / 2, 0.0)) == pytest.approx(100.0)

    def test_level_ground_is_not_a_division_by_zero(self) -> None:
        field = HeightField.from_function(lambda x, z: np.zeros_like(np.asarray(x, 'd')),
                                          res=9, extent=EXTENT)
        assert np.isfinite(field.sample(0.0, 0.0))
        assert float(field.sample(37.0, -12.0)) == pytest.approx(0.0)

    def test_it_is_the_size_it_was_asked_for(self) -> None:
        field = HeightField.from_function(_bowl, res=33, extent=EXTENT)
        assert field.grid.shape == (33, 33)
        assert field.extent == EXTENT

    def test_the_function_sees_the_whole_square(self) -> None:
        seen = []

        def watching(x, z):
            seen.append((np.asarray(x, 'd'), np.asarray(z, 'd')))
            return np.zeros_like(np.asarray(x, 'd'))
        HeightField.from_function(watching, res=9, extent=EXTENT)
        x = np.concatenate([a.ravel() for a, _b in seen])
        z = np.concatenate([b.ravel() for _a, b in seen])
        assert x.min() == pytest.approx(-EXTENT / 2)
        assert x.max() == pytest.approx(EXTENT / 2)
        assert z.min() == pytest.approx(-EXTENT / 2)
        assert z.max() == pytest.approx(EXTENT / 2)

    def test_it_agrees_with_the_function_between_samples(self) -> None:
        """Not exactly -- a grid interpolates -- but a car driving on the field
        must not be driving on a different landscape."""
        field = HeightField.from_function(_bowl, res=257, extent=EXTENT)
        x = np.linspace(-180.0, 180.0, 51)
        z = np.linspace(-150.0, 150.0, 51)
        assert np.abs(np.asarray(field.sample(x, z)) - _bowl(x, z)).max() < 1.0


class TestWritingOneOut:
    def test_a_field_becomes_an_image_and_comes_back(self, tmp_path) -> None:
        field = HeightField.from_function(_bowl, res=129, extent=EXTENT)
        path = str(tmp_path / 'height.png')
        field.save_image(path)
        back = HeightField.from_image(path, 129, EXTENT, field.relief,
                                      base=field.base)
        x = np.linspace(-190.0, 190.0, 41)
        assert np.abs(np.asarray(back.sample(x, x))
                      - np.asarray(field.sample(x, x))).max() < 1.0

    def test_it_is_written_at_sixteen_bits(self) -> None:
        """Eight bits over five hundred metres of relief is two-metre steps,
        which a car drives over as a staircase."""
        from PIL import Image
        import io
        field = HeightField.from_function(_bowl, res=65, extent=EXTENT)
        buffer = io.BytesIO()
        field.save_image(buffer, format='PNG')
        buffer.seek(0)
        assert Image.open(buffer).mode in ('I', 'I;16', 'I;16B')


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
