"""How water moves: still, flowing, choppy.

The field is arithmetic over world position and time, so all of it is asserted
directly -- including the two things that make it usable at all: that it is the
same field wherever it is asked from, and that a caller can ask how high the
water is at a point.
"""
import numpy as np
from vrml import node
from vrml.protofunctions import getFields

from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.water.surface import (
    _fine_ripple, _heading, CHOPPY, FLOWING, RIPPLE, STILL, water_surface, WaterStyle, wave_height,
    wave_normal,
)
from OpenGLContext.scenegraph.water import BREEZE, LAKE, mesh_across, MESH_LIMIT, RIPPLE_SCALE


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
        assert tuple(FLOWING.flow) != (0.0, 0.0)
        assert tuple(STILL.flow) == (0.0, 0.0)


class TestAStyleIsANode:
    """How water moves is scene content, held in fields like any other."""

    def test_a_style_is_a_scenegraph_node(self) -> None:
        assert isinstance(CHOPPY, node.Node)
        names = {one.name for one in getFields(CHOPPY)}
        assert {'name', 'amplitude', 'wavelength', 'speed', 'steepness',
                'flow', 'ripple'} <= names

    def test_a_style_writes_itself_out(self) -> None:
        written = CHOPPY.toString()
        assert 'WaterStyle' in written
        assert 'amplitude' in written

    def test_a_mesh_holds_its_style_in_a_field(self) -> None:
        assert 'waveStyle' in {one.name for one in getFields(PBRMesh())}
        assert not PBRMesh().waveStyle

    def test_a_variation_leaves_the_style_it_came_from_alone(self) -> None:
        rough = CHOPPY.varied(amplitude=1.0, name='storm')
        assert rough is not CHOPPY
        assert rough.amplitude == 1.0 and rough.name == 'storm'
        assert rough.wavelength == CHOPPY.wavelength
        assert CHOPPY.amplitude != 1.0 and CHOPPY.name == 'choppy'

    def test_a_ripple_asked_of_a_sheet_does_not_reach_the_preset(self) -> None:
        mesh = water_surface(-5.0, 5.0, -5.0, 5.0, ripple=0.2, on_gpu=True)
        assert mesh.waveStyle.steepness == 0.2
        assert STILL.steepness == RIPPLE

    def test_several_sheets_can_share_one_style(self) -> None:
        """As a VRML97 USE does: change the one node and every sheet
        moving by it follows."""
        mine = WaterStyle(name='mine', amplitude=0.1)
        first = water_surface(0.0, 5.0, 0.0, 5.0, style=mine, on_gpu=True)
        second = water_surface(5.0, 9.0, 0.0, 5.0, style=mine, on_gpu=True)
        assert first.waveStyle is second.waveStyle is mine


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
        assert mesh.waveStyle is CHOPPY
        assert mesh.wave_time == 2.0

    def test_its_normals_start_flat(self) -> None:
        mesh = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY,
                             on_gpu=True)
        assert np.allclose(np.asarray(mesh.normals)[:, 1], 1.0)

    def test_a_processor_sheet_says_nothing_to_the_card(self) -> None:
        """Or it would be moved twice: once here and once there."""
        mesh = water_surface(-20.0, 20.0, -20.0, 20.0, style=CHOPPY)
        assert not mesh.waveStyle

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
        assert LAKE.amplitude > 0.0 and LAKE.wavelength > 0.0

    def test_it_is_gentler_than_weather(self) -> None:
        assert LAKE.amplitude < CHOPPY.amplitude

    def test_but_it_is_not_a_mirror(self) -> None:
        assert LAKE.amplitude > STILL.amplitude

    def test_a_sheet_carries_the_wave_it_is_asked_for(self) -> None:
        """Meshed for the wavelength rather than at a fixed count, so the
        surface actually holds the shape."""
        side = 400.0
        found = water_surface(0.0, side, 0.0, side, level=0.0,
                              resolution=mesh_across(side, LAKE), style=LAKE)
        heights = np.asarray(found.positions)[:, 1]
        assert float(heights.max() - heights.min()) > LAKE.amplitude * 0.5

    def test_and_a_bigger_sheet_gets_more_of_them(self) -> None:
        """Up to the budget: past that a sheet is meshed as finely as it is
        worth meshing and the ripple carries the rest."""
        assert mesh_across(120.0, LAKE) > mesh_across(30.0, LAKE)

    def test_without_asking_for_a_million_of_them(self) -> None:
        assert mesh_across(20000.0, LAKE) <= MESH_LIMIT


class TestTheRippleIsTheStyles:
    """How fine the glitter is belongs to the water, as its swell does.

    A lake a few hundred metres across wants a ripple that repeats over metres,
    or it reads as a mirror; a pond twenty metres across with the same ripple
    shows two or three dark bands across it, which reads as nothing at all.
    """

    def test_a_style_says_how_far_its_ripple_repeats(self) -> None:
        assert STILL.ripple == RIPPLE_SCALE

    def test_the_ripple_is_drawn_at_the_length_the_style_gives(self) -> None:
        """The same pattern, at a fifth of the size, over a fifth of the ground."""
        broad = WaterStyle(name='broad', ripple=10.0)
        fine = WaterStyle(name='fine', ripple=2.0)
        x, z = _grid(half=30.0, steps=13)
        assert np.allclose(wave_normal(fine, x / 5.0, z / 5.0, 0.0),
                           wave_normal(broad, x, z, 0.0))


class TestABreeze:
    """Wind on sheltered water: a surface seen from its own bank."""

    def test_it_is_named(self) -> None:
        assert BREEZE.name == 'breeze'

    def test_its_waves_are_a_stride_across_and_centimetres_high(self) -> None:
        assert BREEZE.wavelength < 2.0
        assert 0.0 < BREEZE.amplitude < 0.05

    def test_its_ripple_is_finer_than_its_waves(self) -> None:
        assert BREEZE.ripple < BREEZE.wavelength

    def test_it_moves(self) -> None:
        assert BREEZE.moving()


class TestTheRippleIsNotALattice:
    """Two crossing cosines tile the surface like hammered metal, and at a
    hand's breadth the tiling is the first thing seen. The ripple is several
    trains of unrelated lengths and headings instead, moving as water moves."""

    @staticmethod
    def _slopes(style, when=0.0, cells=128):
        """The ripple's slope along x over a patch sixteen ripples across."""
        side = style.ripple * 16.0
        axis = np.arange(cells) * side / cells
        x, z = np.meshgrid(axis, axis, indexing='ij')
        slope_x, _slope_z = _fine_ripple(x, z, float(style.steepness),
                                         _heading(style), when, style)
        return slope_x

    def test_it_is_made_of_many_waves(self) -> None:
        """Counted in its spectrum: each train is a pair of peaks, found as
        the local maxima of a windowed transform so that a wave not fitting
        the patch a whole number of times still counts once."""
        slopes = self._slopes(BREEZE)
        window = np.outer(np.hanning(slopes.shape[0]), np.hanning(slopes.shape[1]))
        spectrum = np.abs(np.fft.fft2(slopes * window))
        spectrum[0, 0] = 0.0
        around = np.max([np.roll(np.roll(spectrum, dx, 0), dz, 1)
                         for dx in (-1, 0, 1) for dz in (-1, 0, 1)
                         if dx or dz], axis=0)
        peaks = (spectrum > around) & (spectrum > 0.05 * spectrum.max())
        assert int(peaks.sum()) >= 10

    def test_it_moves_on_water_with_no_current(self) -> None:
        """A breeze on a pond moves the glitter, though the pond goes nowhere."""
        assert not np.allclose(self._slopes(BREEZE, 0.0), self._slopes(BREEZE, 0.5))

    def test_still_water_holds_its_glitter(self) -> None:
        """Nothing about still water changes with time, its light included."""
        x, z = _grid(half=5.0, steps=9)
        assert np.allclose(wave_normal(STILL, x, z, 0.0), wave_normal(STILL, x, z, 3.0))


class TestTheRippleVariesAsWindDoes:
    """Wind on water is not even: it comes in gusts, so the ruffle is patchy,
    calm here and ruffled there, and the patches drift. A ripple of one
    strength everywhere reads as a texture laid over the surface."""

    @staticmethod
    def _patches(style, when=0.0, patch=3.0, across=40):
        """The ripple's strength, as RMS slope, over a grid of patches."""
        side = style.ripple * patch
        cells = 12
        strengths = np.zeros((across, across))
        for i in range(across):
            for j in range(across):
                axis_x = (i + np.arange(cells) / cells) * side
                axis_z = (j + np.arange(cells) / cells) * side
                x, z = np.meshgrid(axis_x, axis_z, indexing='ij')
                sx, sz = _fine_ripple(x, z, float(style.steepness),
                                      _heading(style), when, style)
                strengths[i, j] = np.sqrt(np.mean(sx * sx + sz * sz))
        return strengths

    def test_some_of_the_surface_is_calmer_than_the_rest(self) -> None:
        strengths = self._patches(BREEZE)
        assert strengths.max() > 2.5 * strengths.min()

    def test_the_gusts_move_across_the_water(self) -> None:
        before = self._patches(BREEZE, 0.0, across=12)
        after = self._patches(BREEZE, 8.0, across=12)
        assert not np.allclose(before, after, rtol=0.1)


class TestTheRippleIsFilteredByDistance:
    """A ripple train finer than a couple of pixels cannot be drawn, only
    aliased; far water is a smooth mirror because its ripple is below what
    the eye resolves, and drawing it anyway is what makes far water a grid."""

    @staticmethod
    def _rms(style, footprint):
        axis = np.linspace(0.0, style.ripple * 20.0, 97)
        x, z = np.meshgrid(axis, axis, indexing='ij')
        sx, sz = _fine_ripple(x, z, float(style.steepness), _heading(style),
                              0.0, style, footprint=footprint)
        return float(np.sqrt(np.mean(sx * sx + sz * sz)))

    def test_close_to_the_camera_it_is_all_there(self) -> None:
        assert self._rms(BREEZE, 0.0) == self._rms(BREEZE, BREEZE.ripple * 0.01)

    def test_where_a_pixel_covers_its_waves_it_is_gone(self) -> None:
        assert self._rms(BREEZE, BREEZE.ripple * 2.0) == 0.0

    def test_in_between_the_finest_trains_go_first(self) -> None:
        near = self._rms(BREEZE, 0.0)
        middle = self._rms(BREEZE, BREEZE.ripple * 0.3)
        assert 0.0 < middle < near
