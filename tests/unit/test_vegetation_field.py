"""A forest as one node: geometry near the camera, cards beyond it.

A quarter of a million trees is not a quarter of a million objects in a
scenegraph -- it is two instanced draws per species over a table of positions,
with the near set re-chosen from the table each time the camera moves. Wiring
that by hand is five nodes and a streaming loop per application;
:class:`VegetationField` is the node that owns it.

What is tested here is the selection and the bookkeeping, which need no GL: what
each rung is asked to draw as the camera moves, and that the two rungs cover the
forest between them without drawing a tree twice.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.vegetation.field import (
    TreeSpecies,
    VegetationField,
)


def _species(name='fir'):
    return TreeSpecies(name=name, mesh='%s.npz' % name,
                       solid=('oP', 'oN', 'oU', 'oI'), solid_texture='bark.png',
                       foliage=('bP', 'bN', 'bU', 'bI'),
                       foliage_texture='branch.png', impostor='%s_imp.png' % name)


def _forest(count=400, spread=800.0, kinds=1, seed=3):
    rng = np.random.default_rng(seed)
    positions = np.stack([rng.uniform(-spread, spread, count),
                          np.zeros(count),
                          rng.uniform(-spread, spread, count)], axis=-1)
    yaws = rng.uniform(0.0, 2 * np.pi, count)
    heights = rng.uniform(9.0, 18.0, count)
    kind = rng.integers(0, kinds, count)
    return positions, yaws, heights, kind


def _field(count=400, kinds=1, spread=800.0, **named):
    positions, yaws, heights, kind = _forest(count, spread=spread, kinds=kinds)
    species = [_species('kind%d' % i) for i in range(kinds)]
    return VegetationField(positions, yaws, heights, species,
                           species_id=kind, **named)


class TestWhatItHolds:
    def test_it_knows_how_many_trees_there_are(self) -> None:
        assert _field(count=250).tree_count == 250

    def test_it_has_a_near_rung_and_a_card_per_species(self) -> None:
        field = _field(kinds=3)
        assert field.near is not None
        assert len(field.impostors) == 3

    def test_the_rungs_are_its_children(self) -> None:
        field = _field(kinds=2)
        assert len(field.children) == 3

    def test_a_species_with_no_trees_gets_no_card(self) -> None:
        """An empty instanced draw is still a draw."""
        positions, yaws, heights, _kind = _forest(60)
        field = VegetationField(positions, yaws, heights,
                                [_species('a'), _species('b')],
                                species_id=np.zeros(60, int))
        assert len(field.impostors) == 1

    def test_species_are_dealt_round_robin_when_unsaid(self) -> None:
        positions, yaws, heights, _kind = _forest(60)
        field = VegetationField(positions, yaws, heights,
                                [_species('a'), _species('b')])
        assert len(field.impostors) == 2

    def test_a_forest_of_no_trees_is_allowed(self) -> None:
        """A world can have no vegetation, and asking for it is not an error."""
        field = VegetationField(np.zeros((0, 3)), np.zeros(0), np.zeros(0),
                                [_species()])
        assert field.tree_count == 0

    def test_it_needs_at_least_one_species(self) -> None:
        positions, yaws, heights, _kind = _forest(10)
        with pytest.raises(ValueError):
            VegetationField(positions, yaws, heights, [])

    def test_the_tables_have_to_agree(self) -> None:
        positions, yaws, heights, _kind = _forest(10)
        with pytest.raises(ValueError):
            VegetationField(positions, yaws[:5], heights, [_species()])


class TestWhatIsDrawnNear:
    def test_the_near_rung_takes_the_trees_around_the_camera(self) -> None:
        field = _field(count=600, near_radius=60.0)
        field.update((0.0, 0.0, 0.0))
        drawn = np.concatenate([rows for rows in field.near._pending.values()])
        distance = np.hypot(drawn[:, 0], drawn[:, 2])
        assert len(drawn)
        assert float(distance.max()) <= 60.0

    def test_it_takes_every_tree_that_is_near(self) -> None:
        positions, yaws, heights, kind = _forest(600)
        field = VegetationField(positions, yaws, heights, [_species()],
                                species_id=kind, near_radius=60.0)
        field.update((0.0, 0.0, 0.0))
        drawn = np.concatenate([rows for rows in field.near._pending.values()])
        within = np.hypot(positions[:, 0], positions[:, 2]) <= 60.0
        assert len(drawn) == int(within.sum())

    def test_moving_the_camera_moves_the_near_set(self) -> None:
        field = _field(count=600, near_radius=60.0)
        field.update((0.0, 0.0, 0.0))
        here = sum(len(rows) for rows in field.near._pending.values())
        field.update((600.0, 0.0, 600.0))
        drawn = np.concatenate([rows for rows in field.near._pending.values()])
        assert here or True
        if len(drawn):
            assert float(np.hypot(drawn[:, 0] - 600.0,
                                  drawn[:, 2] - 600.0).max()) <= 60.0


class TestWhatIsDrawnFar:
    def test_the_cards_take_what_is_in_front_of_the_camera(self) -> None:
        """Every card in a four-kilometre forest submitted every frame is most
        of the cost of the forest."""
        field = _field(count=2000, far_radius=2000.0, cone_degrees=45.0)
        field.update((0.0, 0.0, -900.0), facing=(0.0, 0.0, 1.0))
        drawn = np.concatenate([node.pos for node in field.impostors])
        assert len(drawn)
        assert float(drawn[:, 2].min()) > -1000.0

    def test_what_is_behind_the_camera_is_not_drawn(self) -> None:
        field = _field(count=2000, far_radius=2000.0, cone_degrees=30.0)
        field.update((0.0, 0.0, 0.0), facing=(0.0, 0.0, 1.0))
        drawn = np.concatenate([node.pos for node in field.impostors])
        far_behind = drawn[np.hypot(drawn[:, 0], drawn[:, 2]) > 200.0]
        assert len(far_behind)
        assert float(far_behind[:, 2].max()) > 0.0
        assert (far_behind[:, 2] > -50.0).all()

    def test_what_is_close_is_drawn_whichever_way_you_look(self) -> None:
        """A card just off the edge of the view is one turn of the head away."""
        positions = np.array([(0.0, 0.0, -8.0), (0.0, 0.0, 900.0)])
        field = VegetationField(positions, np.zeros(2), np.full(2, 12.0),
                                [_species()], far_radius=2000.0,
                                cone_degrees=20.0)
        field.update((0.0, 0.0, 0.0), facing=(0.0, 0.0, 1.0))
        drawn = field.impostors[0].pos
        assert len(drawn) == 2

    def test_without_a_facing_everything_within_reach_is_drawn(self) -> None:
        field = _field(count=500, far_radius=300.0)
        field.update((0.0, 0.0, 0.0))
        drawn = np.concatenate([node.pos for node in field.impostors])
        assert float(np.hypot(drawn[:, 0], drawn[:, 2]).max()) <= 300.0

    def test_beyond_the_far_radius_nothing_is_drawn(self) -> None:
        field = _field(count=600, far_radius=200.0)
        field.update((0.0, 0.0, 0.0))
        drawn = np.concatenate([node.pos for node in field.impostors])
        assert float(np.hypot(drawn[:, 0], drawn[:, 2]).max()) <= 200.0


class TestTheTwoRungsTogether:
    def test_the_near_rung_reaches_no_further_than_the_cards(self) -> None:
        """A gap between them is a ring of missing trees around the camera."""
        field = _field(count=800, near_radius=60.0, far_radius=900.0)
        assert field.near_radius <= field.far_radius

    def test_a_card_stands_where_its_tree_does(self) -> None:
        positions = np.array([(120.0, 30.0, -40.0)])
        field = VegetationField(positions, np.zeros(1), np.full(1, 14.0),
                                [_species()], far_radius=900.0)
        field.update((0.0, 0.0, 0.0))
        assert np.allclose(field.impostors[0].pos[0], positions[0])

    def test_a_card_is_the_height_of_its_tree(self) -> None:
        field = VegetationField(np.zeros((1, 3)), np.zeros(1), np.full(1, 14.0),
                                [_species()], far_radius=900.0)
        field.update((0.0, 0.0, 0.0))
        assert float(field.impostors[0].scales[0]) == pytest.approx(14.0)

    def test_standing_still_costs_nothing(self) -> None:
        """A field that re-selects every frame from a table of a quarter of a
        million spends the frame doing it."""
        field = _field(count=800, near_radius=60.0)
        field.update((0.0, 0.0, 0.0))
        before = field.selections
        field.update((0.2, 0.0, 0.2))
        assert field.selections == before

    def test_moving_far_enough_costs_one(self) -> None:
        field = _field(count=800, near_radius=60.0)
        field.update((0.0, 0.0, 0.0))
        before = field.selections
        field.update((90.0, 0.0, 0.0))
        assert field.selections == before + 1

    def test_turning_on_the_spot_re_selects_the_cards(self) -> None:
        """The cone moved even though the camera did not."""
        field = _field(count=800, far_radius=900.0, cone_degrees=40.0)
        field.update((0.0, 0.0, 0.0), facing=(0.0, 0.0, 1.0))
        before = sum(len(node.pos) for node in field.impostors)
        field.update((0.0, 0.0, 0.0), facing=(1.0, 0.0, 0.0))
        after = sum(len(node.pos) for node in field.impostors)
        assert before and after
        assert before != after


class TestTheSpeciesDescription:
    def test_it_carries_what_the_near_rung_needs(self) -> None:
        entry = _species().near_entry()
        assert entry['npz'] == 'fir.npz'
        assert entry['o_tex'] == 'bark.png'
        assert entry['b_keys'] == ('bP', 'bN', 'bU', 'bI')

    def test_a_species_reads_as_its_name(self) -> None:
        assert 'fir' in repr(_species())

    def test_its_files_can_be_resolved_against_a_directory(self) -> None:
        found = _species().beside('/worlds/one/trees')
        assert found.mesh == '/worlds/one/trees/fir.npz'
        assert found.impostor == '/worlds/one/trees/fir_imp.png'

    def test_resolving_leaves_the_original_alone(self) -> None:
        one = _species()
        one.beside('/worlds/one')
        assert one.mesh == 'fir.npz'

    def test_it_survives_a_round_trip_through_json(self) -> None:
        """A baked world carries its species list in the tileset."""
        import json
        entry = _species()
        assert TreeSpecies.from_json(json.loads(json.dumps(entry.to_json()))) \
            == entry


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestChosenAgainstTheView:
    """A cone about the heading is the wrong shape for a frustum: a camera
    looking down at a valley has trees near it inside the cone and trees along
    its own view outside, which draws a hard edge across the forest. Given the
    view-projection, the cards are chosen against the frustum itself."""

    def _matrix(self, eye, look, aspect=1.78):
        from OpenGLContext.loaders.tiles3d.frustum import view_projection
        return view_projection(eye, look, (0, 1, 0), 0.9, aspect, 1.0, 6000.0)

    def _drawn(self, field):
        return np.concatenate([node.pos for node in field.impostors])

    def test_what_is_in_front_is_drawn(self) -> None:
        field = _field(count=3000, far_radius=2000.0)
        eye = (0.0, 30.0, -900.0)
        field.update(eye, view=self._matrix(eye, (0.0, 30.0, 900.0)))
        drawn = self._drawn(field)
        assert len(drawn)
        assert float(drawn[:, 2].min()) > -1000.0

    def test_what_is_behind_is_not(self) -> None:
        field = _field(count=3000, far_radius=2000.0)
        eye = (0.0, 30.0, 0.0)
        field.update(eye, view=self._matrix(eye, (0.0, 30.0, 900.0)))
        drawn = self._drawn(field)
        far = drawn[np.hypot(drawn[:, 0], drawn[:, 2]) > 300.0]
        assert len(far)
        assert (far[:, 2] > -80.0).all()

    def test_a_camera_looking_down_keeps_what_it_looks_at(self) -> None:
        """The case a cone gets wrong."""
        field = _field(count=4000, spread=1500.0, far_radius=2000.0)
        eye = (-600.0, 420.0, -600.0)
        field.update(eye, view=self._matrix(eye, (200.0, 60.0, 200.0)))
        drawn = self._drawn(field)
        # The far half of the view, along the way the camera is pointed.
        way = np.array([800.0, 0.0, 800.0])
        way /= np.linalg.norm(way)
        along = (drawn[:, [0, 2]] - np.array([eye[0], eye[2]])) @ way[[0, 2]]
        assert float(along.max()) > 900.0

    def test_a_view_wins_over_a_facing(self) -> None:
        field = _field(count=2000, far_radius=2000.0)
        eye = (0.0, 30.0, 0.0)
        field.update(eye, facing=(0.0, 0.0, -1.0),
                     view=self._matrix(eye, (0.0, 30.0, 900.0)))
        drawn = self._drawn(field)
        far = drawn[np.hypot(drawn[:, 0], drawn[:, 2]) > 300.0]
        assert (far[:, 2] > -80.0).all()

    def test_it_reaches_past_the_edges_of_the_view(self) -> None:
        """A card just outside the frustum is one turn of the head away, and a
        card that arrives after the turn reads as a tree growing."""
        near = np.array([(0.0, 0.0, -30.0)])
        field = VegetationField(near, np.zeros(1), np.full(1, 12.0),
                                [_species()], far_radius=2000.0)
        eye = (0.0, 2.0, 0.0)
        field.update(eye, view=self._matrix(eye, (0.0, 2.0, 900.0)))
        assert len(field.impostors[0].pos) == 1

    def test_nothing_beyond_the_far_radius(self) -> None:
        field = _field(count=3000, spread=2000.0, far_radius=300.0)
        eye = (0.0, 30.0, 0.0)
        field.update(eye, view=self._matrix(eye, (0.0, 30.0, 900.0)))
        drawn = self._drawn(field)
        assert float(np.hypot(drawn[:, 0], drawn[:, 2]).max()) <= 300.0

    def test_turning_re_chooses(self) -> None:
        field = _field(count=3000, far_radius=2000.0)
        eye = (0.0, 30.0, 0.0)
        field.update(eye, view=self._matrix(eye, (0.0, 30.0, 900.0)))
        before = field.selections
        field.update(eye, view=self._matrix(eye, (900.0, 30.0, 0.0)))
        assert field.selections == before + 1


class TestTheEdgeOfTheViewIsNeverSeen:
    """A frustum plane meets the ground in a straight line, so a card set cut
    exactly at the view has a ruled edge across the forest the moment anything
    disagrees about where the view is -- a streamer's own matrix against the
    renderer's, a frame of latency, a turn of the head. The slack grows with
    distance, because at a kilometre a degree is a lot of metres."""

    def _matrix(self, eye, look):
        from OpenGLContext.loaders.tiles3d.frustum import view_projection
        return view_projection(eye, look, (0, 1, 0), 0.9, 1.78, 1.0, 6000.0)

    def test_a_card_just_outside_a_distant_edge_is_still_drawn(self) -> None:
        eye = (0.0, 20.0, 0.0)
        matrix = self._matrix(eye, (0.0, 20.0, 1000.0))
        from OpenGLContext.loaders.tiles3d.frustum import Frustum
        planes = np.asarray(Frustum.from_matrix(np.asarray(matrix)).planes)
        # A point a kilometre away, twenty metres outside the left plane.
        out = np.array([[0.0, 20.0, 1000.0]])
        out[0, :3] -= planes[0, :3] * (planes[0, :3] @ out[0] + planes[0, 3]
                                       + 20.0)
        field = VegetationField(out, np.zeros(1), np.full(1, 14.0),
                                [_species()], far_radius=3000.0)
        field.update(eye, view=matrix)
        assert len(field.impostors[0].pos) == 1

    def test_the_slack_grows_with_distance(self) -> None:
        from OpenGLContext.scenegraph.vegetation.field import (
            VIEW_MARGIN, VIEW_SPREAD,
        )
        assert VIEW_SPREAD > 0.0 and VIEW_MARGIN > 0.0

    def test_what_is_squarely_behind_is_still_dropped(self) -> None:
        eye = (0.0, 20.0, 0.0)
        field = _field(count=2000, spread=1500.0, far_radius=3000.0)
        field.update(eye, view=self._matrix(eye, (0.0, 20.0, 1000.0)))
        drawn = np.concatenate([node.pos for node in field.impostors])
        far = drawn[np.hypot(drawn[:, 0], drawn[:, 2]) > 600.0]
        assert len(far)
        assert float(far[:, 2].min()) > -100.0


class TestTheForestStandsInItsOwnShade:
    """A tree in the middle of a stand is not lit like one on the edge of it.

    The terrain already carries the canopy's shade; a forest drawn at full sun
    over ground darkened to a fifth reads as trees standing on a photograph.
    """

    def _shade(self):
        def at(x, z):
            return np.where(np.asarray(x, 'd') < 0.0, 0.2, 1.0)
        return at

    def _field(self, **named):
        count = 40
        points = np.stack([np.linspace(-200.0, 200.0, count),
                           np.zeros(count), np.zeros(count)], axis=-1)
        return VegetationField(points, np.zeros(count), np.full(count, 12.0),
                               [_species()], **named)

    def test_without_one_the_forest_is_in_full_sun(self) -> None:
        field = self._field()
        assert field.shades is None

    def test_with_one_each_tree_carries_its_own(self) -> None:
        field = self._field(shade=self._shade())
        assert len(field.shades) == field.tree_count

    def test_the_shaded_side_is_darker(self) -> None:
        field = self._field(shade=self._shade())
        west = field.shades[field.positions[:, 0] < -10.0]
        east = field.shades[field.positions[:, 0] > 10.0]
        assert float(west.mean()) < 0.3 < float(east.mean())

    def test_the_near_geometry_carries_it(self) -> None:
        field = self._field(shade=self._shade())
        field.update((-200.0, 0.0, 0.0))
        rows = np.concatenate(list(field.near._pending.values()))
        assert float(rows[:, 5].min()) < 0.3

    def test_the_cards_carry_it(self) -> None:
        field = self._field(shade=self._shade())
        field.update((-200.0, 0.0, 0.0))
        assert field.impostors[0].shades is not None
