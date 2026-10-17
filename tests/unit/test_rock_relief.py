"""Bare rock as a surface: scraped into terraces, a function of position, nothing off the rock."""
import numpy as np
import pytest

from OpenGLContext.scenegraph.terrain import RockRelief


def everywhere(x, z):
    return np.ones(np.broadcast(np.asarray(x), np.asarray(z)).shape)


def east_of_zero(x, z):
    return (np.asarray(x) > 0.0).astype(float) * np.ones(np.broadcast(np.asarray(x),
                                                                      np.asarray(z)).shape)


def grid(extent=24.0, step=0.1):
    axis = np.arange(0.0, extent, step)
    return np.meshgrid(axis, axis)


def test_no_rock_where_it_is_not_rocky():
    relief = RockRelief(where=lambda x, z: np.zeros(np.broadcast(x, z).shape))
    x, z = grid(12.0, 0.3)
    assert not relief.displacement(x, z).any()


def test_rock_is_raised_above_the_ground_by_no_more_than_its_height():
    relief = RockRelief(where=everywhere, height=0.8)
    x, z = grid()
    out = relief.displacement(x, z)
    assert out.min() >= relief.lift - 1e-9
    assert out.max() <= relief.height + relief.lift + relief.grain * 2.0
    assert out.max() > 0.3 * relief.height


def test_the_same_place_is_the_same_height_however_it_is_asked_for():
    relief = RockRelief(where=everywhere, seed=4)
    x, z = grid(12.0, 0.25)
    whole = relief.displacement(x, z)
    one = [relief.displacement(np.array([x[3, 5]]), np.array([z[3, 5]]))[0]]
    assert one[0] == pytest.approx(whole[3, 5])
    assert np.array_equal(whole, relief.displacement(x, z))
    assert not np.array_equal(whole, RockRelief(where=everywhere, seed=5).displacement(x, z))


def test_the_surface_is_scraped_flat_in_places_with_steps_between():
    relief = RockRelief(where=everywhere, height=0.8, grain=0.0)
    step = 0.05
    x, z = grid(30.0, step)
    h = relief.displacement(x, z)
    slope_x = np.abs(np.diff(h, axis=1)) / step
    flat = (slope_x <= relief.tilt + 0.05)
    assert flat.mean() > 0.85                              # faces at the tilt the scrapes allow
    assert (np.abs(np.diff(h, axis=1)) > 0.08).sum() > 20  # and a step at the rim of a cut


def test_a_surface_sampled_coarsely_holds_no_scrapes_and_is_smoother():
    relief = RockRelief(where=everywhere, height=0.8, grain=0.0)
    x, z = grid(30.0, 0.2)
    fine, coarse = relief.displacement(x, z, 0.2), relief.displacement(x, z, 4.0)
    assert np.abs(np.diff(coarse, axis=1)).max() < np.abs(np.diff(fine, axis=1)).max()
    assert coarse.std() < fine.std()


def test_rock_gives_way_to_ground_smoothly_where_the_rocky_weight_falls():
    relief = RockRelief(where=lambda x, z: np.clip(np.asarray(x) / 20.0, 0.0, 1.0) * np.ones_like(np.asarray(z)),
                        height=0.8, grain=0.0)
    x = np.linspace(0.0, 20.0, 400)
    out = relief.displacement(x, np.full_like(x, 3.0))
    assert out[0] == 0.0 and out[x < 7.0].max() == 0.0     # none below `begins`
    assert out[-1] > 0.1
    assert out[(x > 7.0) & (x < 7.4)].max() < 0.1          # it grows in, rather than starting at height


def test_a_rock_relief_asks_for_sensible_numbers():
    with pytest.raises(ValueError):
        RockRelief(where=everywhere, height=0.0)
    with pytest.raises(ValueError):
        RockRelief(where=everywhere, begins=0.8, whole=0.5)


def test_rock_relief_lays_itself_over_a_height_function():
    relief = RockRelief(where=everywhere, height=0.8)
    ground = relief.over(lambda x, z: 0.1 * np.asarray(x, dtype=float), spacing=0.5, error=0.1)
    x, z = np.array([3.0, 40.0]), np.array([1.0, 2.0])
    assert ground(x, z) == pytest.approx(0.1 * x + relief.displacement(x, z, 0.5))
    assert relief.no_finer_than(2.0) is relief


def test_reliefs_add_each_over_the_one_before():
    from OpenGLContext.scenegraph.terrain import GROUND_RELIEF, Reliefs
    rock = RockRelief(where=everywhere, height=0.8)
    both = Reliefs((GROUND_RELIEF, rock))
    base = lambda x, z: np.zeros(np.broadcast(x, z).shape)  # noqa: E731 reads best inline
    x, z = np.array([12.5, 80.0]), np.array([3.5, 9.0])
    expected = GROUND_RELIEF.over(base, 0.5, 0.1)(x, z) + rock.displacement(x, z, 0.5)
    assert both.over(base, 0.5, 0.1)(x, z) == pytest.approx(expected)
    assert isinstance(both.no_finer_than(1.0), Reliefs)
