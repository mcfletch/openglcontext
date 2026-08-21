"""How water moves: still, flowing, choppy.

The field is arithmetic over world position and time, so all of it is asserted
directly -- including the two things that make it usable at all: that it is the
same field wherever it is asked from, and that a caller can ask how high the
water is at a point.
"""
import numpy as np

from OpenGLContext.scenegraph.water.surface import (
    CHOPPY,
    FLOWING,
    STILL,
    WaterStyle,
    wave_height,
    wave_normal,
    water_surface,
)


def _grid(half=40.0, steps=17):
    axis = np.linspace(-half, half, steps)
    return np.meshgrid(axis, axis, indexing='ij')


class TestTheThreeMotions:
    def test_all_three_are_there(self) -> None:
        assert STILL.name == 'still'
        assert FLOWING.name == 'flowing'
        assert CHOPPY.name == 'choppy'

    def test_still_water_does_not_move_up_and_down(self) -> None:
        """A pond has a ripple in the light on it and nothing in its height."""
        x, z = _grid()
        assert np.allclose(wave_height(STILL, x, z, 0.0), 0.0)
        assert np.allclose(wave_height(STILL, x, z, 3.0), 0.0)

    def test_still_water_still_glitters(self) -> None:
        """The ripple is in the normals: it is what breaks the highlight up,
        and a mirror-flat lake reads as a sheet of plastic."""
        x, z = _grid()
        normals = wave_normal(STILL, x, z, 0.0)
        assert normals[..., 1].min() < 1.0
        assert not np.allclose(normals[..., 0], 0.0)

    def test_choppy_water_has_real_waves_in_it(self) -> None:
        x, z = _grid()
        assert np.ptp(wave_height(CHOPPY, x, z, 0.0)) > 0.3

    def test_choppy_is_rougher_than_flowing(self) -> None:
        x, z = _grid()
        assert np.ptp(wave_height(CHOPPY, x, z, 0.0)) \
            > np.ptp(wave_height(FLOWING, x, z, 0.0))

    def test_a_river_drifts_and_a_pond_does_not(self) -> None:
        assert FLOWING.flow != (0.0, 0.0)
        assert STILL.flow == (0.0, 0.0)


class TestMovingInTime:
    def test_choppy_water_is_somewhere_else_a_second_later(self) -> None:
        x, z = _grid()
        assert not np.allclose(wave_height(CHOPPY, x, z, 0.0),
                               wave_height(CHOPPY, x, z, 1.0))

    def test_the_same_moment_is_always_the_same_water(self) -> None:
        """A world rendered twice is the same world, and a bake is repeatable."""
        x, z = _grid()
        assert np.array_equal(wave_height(CHOPPY, x, z, 2.5),
                              wave_height(CHOPPY, x, z, 2.5))

    def test_a_rivers_crests_travel_downstream(self) -> None:
        """Not upstream and not across: water going the wrong way reads as a
        tide. The trains cross, so the sum is not a pure translation -- what
        has to be true is that it matches itself better shifted *with* the
        flow than against it."""
        style = WaterStyle(name='east', amplitude=0.4, wavelength=8.0,
                           speed=2.0, steepness=0.1, flow=(1.0, 0.0))
        x = np.linspace(-20.0, 20.0, 401)
        z = np.zeros_like(x)
        now = wave_height(style, x, z, 0.0)
        later = wave_height(style, x, z, 1.0)
        shift = int(round(2.0 / (40.0 / 400)))     # two metres, in samples
        downstream = np.abs(later[shift:] - now[:-shift]).mean()
        upstream = np.abs(later[:-shift] - now[shift:]).mean()
        assert downstream < upstream * 0.5


class TestBeingOneFieldEverywhere:
    def test_two_sheets_that_meet_agree_along_their_seam(self) -> None:
        """It is a function of where a point is in the world, so a lake split
        into tiles has no crease down the join."""
        seam_z = np.linspace(-5.0, 5.0, 21)
        seam_x = np.full_like(seam_z, 12.0)
        left = wave_height(CHOPPY, seam_x, seam_z, 1.25)
        right = wave_height(CHOPPY, seam_x.copy(), seam_z.copy(), 1.25)
        assert np.array_equal(left, right)

    def test_the_answer_is_the_shape_of_the_question(self) -> None:
        x, z = _grid(steps=5)
        assert wave_height(CHOPPY, x, z, 0.0).shape == x.shape
        assert wave_normal(CHOPPY, x, z, 0.0).shape == x.shape + (3,)

    def test_a_single_point_can_be_asked(self) -> None:
        """Which is what floating on it needs: one body, one height."""
        height = wave_height(CHOPPY, np.asarray([3.0]), np.asarray([4.0]), 0.5)
        assert np.shape(height) == (1,)

    def test_the_normals_are_unit_length(self) -> None:
        x, z = _grid()
        lengths = np.linalg.norm(wave_normal(CHOPPY, x, z, 0.7), axis=-1)
        assert np.allclose(lengths, 1.0)

    def test_the_normals_point_up(self) -> None:
        """However choppy: water does not turn over."""
        x, z = _grid()
        assert np.all(wave_normal(CHOPPY, x, z, 0.7)[..., 1] > 0.0)


class TestASheetOfIt:
    def test_it_sits_at_the_level_it_was_given(self) -> None:
        mesh = water_surface(-10.0, 10.0, -10.0, 10.0, level=4.0, style=STILL)
        assert np.allclose(np.asarray(mesh.positions)[:, 1], 4.0)

    def test_choppy_water_leaves_the_plane(self) -> None:
        mesh = water_surface(-30.0, 30.0, -30.0, 30.0, level=0.0,
                             style=CHOPPY, resolution=33)
        assert np.ptp(np.asarray(mesh.positions)[:, 1]) > 0.3

    def test_it_carries_a_normal_for_every_vertex(self) -> None:
        mesh = water_surface(-10.0, 10.0, -10.0, 10.0, style=CHOPPY)
        assert len(mesh.normals) == len(mesh.positions)

    def test_the_default_is_the_water_a_world_already_had(self) -> None:
        """A caller that names no style gets a flat sheet with a ripple, which
        is what every existing world is holding."""
        mesh = water_surface(-10.0, 10.0, -10.0, 10.0, level=2.0)
        assert np.allclose(np.asarray(mesh.positions)[:, 1], 2.0)


class TestHandingItToTheCard:
    """A surface uploaded once and moved by uniforms costs nothing a frame."""

    def test_a_gpu_sheet_is_meshed_flat(self) -> None:
        """The card is going to move it; a mesh built with the wave in it and
        then moved again has the wave applied twice."""
        mesh = water_surface(-20.0, 20.0, -20.0, 20.0, level=3.0,
                             style=CHOPPY, on_gpu=True)
        assert np.allclose(np.asarray(mesh.positions)[:, 1], 3.0)

    def test_it_carries_the_style_the_card_needs(self) -> None:
        mesh = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY,
                             on_gpu=True, when=2.0)
        assert mesh.wave_style is CHOPPY
        assert mesh.wave_time == 2.0

    def test_its_normals_start_flat(self) -> None:
        mesh = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY,
                             on_gpu=True)
        assert np.allclose(np.asarray(mesh.normals)[:, 1], 1.0)

    def test_a_processor_sheet_says_nothing_to_the_card(self) -> None:
        """Or it would be moved twice: once here and once there."""
        mesh = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY)
        assert getattr(mesh, 'wave_style', None) is None

    def test_the_two_agree_about_where_the_water_is(self) -> None:
        """Same field, so a boat floated by one is drawn by the other."""
        flat = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY,
                             on_gpu=True, when=1.5)
        moved = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY,
                              when=1.5)
        points = np.asarray(flat.positions)
        wanted = wave_height(CHOPPY, points[:, 0], points[:, 2], 1.5)
        assert np.allclose(np.asarray(moved.positions)[:, 1], wanted,
                           atol=1e-5)


class TestALakeIsWater:
    """A sheet meshed at nine vertices across a tile is a sheet whose ripple is
    sampled every few hundred metres: the wave aliases into nothing and what is
    left is a flat plate with a strange normal. It reads as concrete.
    """

    def test_a_lake_has_a_style_of_its_own(self) -> None:
        from OpenGLContext.scenegraph.water import LAKE
        assert LAKE.amplitude > 0.0 and LAKE.wavelength > 0.0

    def test_it_is_gentler_than_weather(self) -> None:
        from OpenGLContext.scenegraph.water import CHOPPY, LAKE
        assert LAKE.amplitude < CHOPPY.amplitude

    def test_but_it_is_not_a_mirror(self) -> None:
        from OpenGLContext.scenegraph.water import LAKE, STILL
        assert LAKE.amplitude > STILL.amplitude

    def test_a_sheet_carries_the_wave_it_is_asked_for(self) -> None:
        """Meshed for the wavelength rather than at a fixed count, so the
        surface actually holds the shape."""
        import numpy as np
        from OpenGLContext.scenegraph.water import LAKE, mesh_across
        from OpenGLContext.scenegraph.water.surface import water_surface
        side = 400.0
        found = water_surface(0.0, side, 0.0, side, level=0.0,
                              resolution=mesh_across(side, LAKE), style=LAKE)
        heights = np.asarray(found.positions)[:, 1]
        assert float(heights.max() - heights.min()) > LAKE.amplitude * 0.5

    def test_and_a_bigger_sheet_gets_more_of_them(self) -> None:
        """Up to the budget: past that a sheet is meshed as finely as it is
        worth meshing and the ripple carries the rest."""
        from OpenGLContext.scenegraph.water import LAKE, mesh_across
        assert mesh_across(120.0, LAKE) > mesh_across(30.0, LAKE)

    def test_without_asking_for_a_million_of_them(self) -> None:
        from OpenGLContext.scenegraph.water import LAKE, MESH_LIMIT, mesh_across
        assert mesh_across(20000.0, LAKE) <= MESH_LIMIT
