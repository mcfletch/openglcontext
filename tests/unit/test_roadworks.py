"""The structures a road needs where the ground does not meet it.

A deck on piers over a valley and a bore through a hill: both are a section
swept along the same centreline the carriageway uses, so both are built from the
road's own frame and land in the same place as the surface they carry.

Geometry only -- what decides *where* a bridge or a tunnel belongs is authoring
and lives in ``OpenGLContext_editor.world.structures``.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.road import RoadProfile
from OpenGLContext.scenegraph.roadworks import (
    BarrierProfile,
    BridgeProfile,
    bore_shade,
    tunnel_lamps,
    TunnelProfile,
    bridge_meshes,
    concrete_material,
    tunnel_meshes,
)

ROAD = RoadProfile()


def _straight(length=200.0, height=40.0, spacing=10.0):
    """A level run of road ``height`` metres up in the air, going east."""
    x = np.arange(0.0, length + spacing, spacing)
    return np.stack([x, np.full(len(x), height), np.zeros(len(x))], axis=-1)


def _valley(x, z):
    """Ground at zero -- a flat valley floor under the deck."""
    return np.zeros(np.broadcast(np.asarray(x), np.asarray(z)).shape)


def _fits(parts):
    """Every mesh is a well-formed indexed triangle mesh."""
    for mesh in parts.values():
        assert len(mesh.indices) % 3 == 0
        assert int(mesh.indices.max()) < len(mesh.positions)
        assert len(mesh.normals) == len(mesh.positions)
        assert np.isfinite(mesh.positions).all()
        assert np.isfinite(mesh.normals).all()


class TestABridge:
    def test_it_produces_geometry(self) -> None:
        meshes = bridge_meshes(_straight(), ROAD, _valley)
        assert meshes and all(len(m.positions) for m in meshes.values())

    def test_every_mesh_is_well_formed(self) -> None:
        _fits(bridge_meshes(_straight(), ROAD, _valley))

    def test_the_deck_hangs_below_the_road(self) -> None:
        bridge = BridgeProfile()
        meshes = bridge_meshes(_straight(height=40.0), ROAD, _valley, bridge)
        deck = meshes['deck']
        assert float(deck.positions[:, 1].min()) == pytest.approx(
            40.0 - bridge.deck_depth, abs=0.5)

    def test_it_does_not_rise_above_the_carriageway(self) -> None:
        """Except the parapets, which are the point of them."""
        meshes = bridge_meshes(_straight(height=40.0), ROAD, _valley)
        deck = meshes['deck']
        assert float(deck.positions[:, 1].max()) <= 40.1

    def test_the_parapets_stand_on_the_edges(self) -> None:
        bridge = BridgeProfile()
        meshes = bridge_meshes(_straight(height=40.0), ROAD, _valley, bridge)
        rails = meshes['parapet']
        assert float(rails.positions[:, 1].max()) == pytest.approx(
            40.0 + bridge.parapet.height, abs=0.5)
        # One each side, out at the deck's edge.
        deck = ROAD.on_structure().total_width / 2.0
        assert float(rails.positions[:, 2].min()) < -deck + 1.0
        assert float(rails.positions[:, 2].max()) > deck - 1.0

    def test_the_piers_reach_the_ground(self) -> None:
        meshes = bridge_meshes(_straight(height=40.0), ROAD, _valley)
        piers = meshes['piers']
        assert float(piers.positions[:, 1].min()) == pytest.approx(0.0, abs=0.5)

    def test_the_piers_reach_the_deck(self) -> None:
        bridge = BridgeProfile()
        meshes = bridge_meshes(_straight(height=40.0), ROAD, _valley, bridge)
        assert float(meshes['piers'].positions[:, 1].max()) \
            >= float(meshes['deck'].positions[:, 1].min()) - 0.01

    def test_a_pier_stands_under_uneven_ground(self) -> None:
        def sloping(x, z):
            # Rising, but staying under the deck for the whole span.
            return np.asarray(x, dtype='d') * 0.08
        meshes = bridge_meshes(_straight(length=400.0), ROAD, sloping)
        piers = meshes['piers']
        low = piers.positions[piers.positions[:, 0] < 50.0]
        high = piers.positions[piers.positions[:, 0] > 350.0]
        assert float(high[:, 1].min()) > float(low[:, 1].min()) + 20.0

    def test_the_piers_are_spaced_along_the_span(self) -> None:
        bridge = BridgeProfile(pier_spacing=50.0)
        meshes = bridge_meshes(_straight(length=400.0), ROAD, _valley, bridge)
        piers = meshes['piers']
        columns = np.unique(np.round(piers.positions[:, 0] / 5.0) * 5.0)
        assert 4 <= len(columns) <= 24

    def test_a_span_too_short_for_a_pier_still_gets_a_deck(self) -> None:
        meshes = bridge_meshes(_straight(length=20.0), ROAD, _valley)
        assert 'deck' in meshes

    def test_it_follows_a_bend(self) -> None:
        angle = np.linspace(0.0, np.pi / 2, 24)
        line = np.stack([300.0 * np.cos(angle), np.full(24, 40.0),
                         300.0 * np.sin(angle)], axis=-1)
        meshes = bridge_meshes(line, ROAD, _valley)
        deck = meshes['deck']
        radius = np.hypot(deck.positions[:, 0], deck.positions[:, 2])
        assert float(radius.min()) > 300.0 - ROAD.total_width
        assert float(radius.max()) < 300.0 + ROAD.total_width

    def test_it_is_as_wide_as_the_road_it_carries(self) -> None:
        meshes = bridge_meshes(_straight(), ROAD, _valley)
        deck = meshes['deck']
        width = float(deck.positions[:, 2].max() - deck.positions[:, 2].min())
        assert width == pytest.approx(ROAD.on_structure().total_width, abs=0.5)

    def test_it_spans_the_run_it_was_given(self) -> None:
        meshes = bridge_meshes(_straight(length=200.0), ROAD, _valley)
        deck = meshes['deck']
        assert float(deck.positions[:, 0].min()) == pytest.approx(0.0, abs=0.1)
        assert float(deck.positions[:, 0].max()) == pytest.approx(200.0, abs=0.1)

    def test_two_points_are_enough(self) -> None:
        line = np.array([(0.0, 40.0, 0.0), (60.0, 40.0, 0.0)])
        _fits(bridge_meshes(line, ROAD, _valley))

    def test_one_point_is_not_a_bridge(self) -> None:
        with pytest.raises(ValueError):
            bridge_meshes(np.array([(0.0, 40.0, 0.0)]), ROAD, _valley)

    def test_it_carries_a_material(self) -> None:
        for mesh in bridge_meshes(_straight(), ROAD, _valley).values():
            assert mesh.material is not None

    def test_a_given_material_is_the_one_used(self) -> None:
        mine = concrete_material()
        for mesh in bridge_meshes(_straight(), ROAD, _valley, material=mine).values():
            assert mesh.material is mine


class TestATunnel:
    def test_it_produces_geometry(self) -> None:
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        assert meshes and all(len(m.positions) for m in meshes.values())

    def test_every_mesh_is_well_formed(self) -> None:
        _fits(tunnel_meshes(_straight(height=0.0), ROAD))

    def test_the_bore_arches_over_the_road(self) -> None:
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        bore = meshes['bore']
        assert float(bore.positions[:, 1].max()) == pytest.approx(
            tunnel.clearance, abs=0.6)

    def test_the_bore_springs_from_under_the_road(self) -> None:
        tunnel = TunnelProfile()
        bore = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)['bore']
        assert float(bore.positions[:, 1].min()) == pytest.approx(
            -tunnel.springing, abs=0.3)

    def test_it_is_wide_enough_for_the_carriageway(self) -> None:
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        bore = meshes['bore']
        width = float(bore.positions[:, 2].max() - bore.positions[:, 2].min())
        assert width >= ROAD.carriageway_width + 2.0

    def test_the_lining_faces_the_road_it_encloses(self) -> None:
        """A driver inside sees the lining, not through it."""
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        bore = meshes['bore']
        # Every normal points back towards the centreline at road height.
        towards = np.stack([np.zeros(len(bore.positions)),
                            -bore.positions[:, 1],
                            -bore.positions[:, 2]], axis=-1)
        towards /= np.maximum(np.linalg.norm(towards, axis=1, keepdims=True), 1e-9)
        inward = np.einsum('ij,ij->i', bore.normals, towards)
        assert float(np.median(inward)) > 0.5

    def test_a_portal_closes_each_end(self) -> None:
        meshes = tunnel_meshes(_straight(length=200.0, height=0.0), ROAD)
        portals = meshes['portals']
        assert float(portals.positions[:, 0].min()) == pytest.approx(0.0, abs=0.1)
        assert float(portals.positions[:, 0].max()) == pytest.approx(200.0, abs=0.1)

    def test_the_portal_surrounds_the_bore(self) -> None:
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        bore = meshes['bore']
        portals = meshes['portals']
        assert float(portals.positions[:, 1].max()) > float(bore.positions[:, 1].max())

    def test_it_follows_a_bend(self) -> None:
        angle = np.linspace(0.0, np.pi / 2, 24)
        line = np.stack([300.0 * np.cos(angle), np.zeros(24),
                         300.0 * np.sin(angle)], axis=-1)
        meshes = tunnel_meshes(line, ROAD)
        bore = meshes['bore']
        radius = np.hypot(bore.positions[:, 0], bore.positions[:, 2])
        assert float(radius.min()) > 300.0 - ROAD.total_width
        assert float(radius.max()) < 300.0 + ROAD.total_width

    def test_two_points_are_enough(self) -> None:
        line = np.array([(0.0, 0.0, 0.0), (60.0, 0.0, 0.0)])
        _fits(tunnel_meshes(line, ROAD))

    def test_one_point_is_not_a_tunnel(self) -> None:
        with pytest.raises(ValueError):
            tunnel_meshes(np.array([(0.0, 0.0, 0.0)]), ROAD)

    def test_it_carries_a_material(self) -> None:
        for mesh in tunnel_meshes(_straight(height=0.0), ROAD).values():
            assert mesh.material is not None


class TestTheMaterial:
    def test_concrete_is_rough_and_pale(self) -> None:
        material = concrete_material()
        assert material.roughness > 0.5
        assert min(material.baseColor) > 0.15
        assert material.metallic == 0.0

    def test_it_is_lit_from_both_sides_in_a_bore(self) -> None:
        """A tunnel lining is a single surface with a driver on one side of it,
        so nothing is gained by drawing its back -- and a bridge soffit is
        closed. Neither wants two-sided lighting."""
        assert not concrete_material().doubleSided


class TestTheyShareTheRoadsFrame:
    """The structures are swept with the same frame the carriageway is, so they
    stay under it through a bend and a climb rather than drifting off it."""

    def test_a_deck_stays_under_a_climbing_road(self) -> None:
        x = np.arange(0.0, 210.0, 10.0)
        line = np.stack([x, 40.0 + x * 0.06, np.zeros(len(x))], axis=-1)
        meshes = bridge_meshes(line, ROAD, _valley)
        deck = meshes['deck']
        top = deck.positions[deck.positions[:, 1] > 40.0]
        rise = np.polyfit(top[:, 0], top[:, 1], 1)[0]
        assert rise == pytest.approx(0.06, abs=0.01)

    def test_a_bore_stays_over_a_climbing_road(self) -> None:
        x = np.arange(0.0, 210.0, 10.0)
        line = np.stack([x, x * 0.06, np.zeros(len(x))], axis=-1)
        meshes = tunnel_meshes(line, ROAD)
        bore = meshes['bore']
        crown = bore.positions[np.abs(bore.positions[:, 2]) < 0.5]
        rise = np.polyfit(crown[:, 0], crown[:, 1], 1)[0]
        assert rise == pytest.approx(0.06, abs=0.01)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestWhereADeckLandsOnRisingGround:
    """A viaduct running into a hillside has its last support *above* the deck,
    where the ground has come up past the soffit. Built anyway it is a block of
    concrete standing across the carriageway."""

    def _into_a_hill(self, x, z):
        """Ground well under the deck, rising past it at the far end."""
        return np.clip((np.asarray(x, 'd') - 120.0) * 0.6, 0.0, 200.0)

    def test_nothing_is_built_where_the_ground_is_over_the_deck(self) -> None:
        meshes = bridge_meshes(_straight(length=200.0, height=40.0), ROAD,
                               self._into_a_hill)
        piers = meshes.get('piers')
        if piers is None:
            return
        assert float(piers.positions[:, 0].max()) < 190.0

    def test_no_pier_reaches_above_the_soffit(self) -> None:
        bridge = BridgeProfile()
        meshes = bridge_meshes(_straight(length=200.0, height=40.0), ROAD,
                               self._into_a_hill, bridge)
        assert float(meshes['piers'].positions[:, 1].max()) \
            <= float(meshes['deck'].positions[:, 1].min()) + 0.01

    def test_the_deck_is_still_built(self) -> None:
        meshes = bridge_meshes(_straight(length=200.0, height=40.0), ROAD,
                               self._into_a_hill)
        assert 'deck' in meshes

    def test_a_span_landing_on_the_ground_at_both_ends_needs_no_piers(self) -> None:
        """Nothing is under it: the deck sits on what it is spanning."""
        def level(x, z):
            return np.full(np.shape(np.asarray(x, 'd')), 40.0)
        meshes = bridge_meshes(_straight(length=200.0, height=40.0), ROAD, level)
        assert 'piers' not in meshes


class TestTheBoreIsClosedAtTheSides:
    """An arch springing exactly at the crown of the carriageway leaves a slot
    between its feet and the road's shoulders, and a driver looks out through
    the hillside."""

    def test_the_lining_reaches_below_the_road(self) -> None:
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        assert float(meshes['bore'].positions[:, 1].min()) \
            <= -tunnel.springing + 0.01

    def test_it_reaches_below_the_shoulder_the_road_actually_has(self) -> None:
        """Whatever the profile's own drop is, the feet are under it."""
        section = ROAD.on_structure().section()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        assert float(meshes['bore'].positions[:, 1].min()) \
            < float(section[:, 1].min())

    def test_the_crown_is_still_where_it_was(self) -> None:
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        assert float(meshes['bore'].positions[:, 1].max()) == pytest.approx(
            tunnel.clearance, abs=0.6)

    def test_the_portal_still_surrounds_it(self) -> None:
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        assert float(meshes['portals'].positions[:, 1].min()) \
            <= float(meshes['bore'].positions[:, 1].min()) + 0.01


class TestTheyFitTheRoadTheyCarry:
    """A deck as wide as the road's grass verge is a deck with metres of nothing
    on each side; the road narrows onto a structure, and the structure is built
    to the narrowed section."""

    def test_the_deck_is_the_width_of_the_road_on_it(self) -> None:
        meshes = bridge_meshes(_straight(), ROAD, _valley)
        deck = meshes['deck']
        width = float(deck.positions[:, 2].max() - deck.positions[:, 2].min())
        assert width == pytest.approx(ROAD.on_structure().total_width, abs=1.0)
        assert width < ROAD.total_width

    def test_the_parapets_stand_on_the_deck_edges(self) -> None:
        meshes = bridge_meshes(_straight(), ROAD, _valley)
        rails = meshes['parapet'].positions
        deck = meshes['deck'].positions
        assert float(rails[:, 2].max()) <= float(deck[:, 2].max()) + 0.01
        assert float(rails[:, 2].min()) >= float(deck[:, 2].min()) - 0.01

    def test_the_bore_is_the_width_of_the_road_in_it(self) -> None:
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        bore = meshes['bore']
        width = float(bore.positions[:, 2].max() - bore.positions[:, 2].min())
        assert width == pytest.approx(
            ROAD.on_structure().total_width + 2 * tunnel.margin, abs=0.1)

    def test_it_is_still_wide_enough_for_the_carriageway(self) -> None:
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        bore = meshes['bore']
        width = float(bore.positions[:, 2].max() - bore.positions[:, 2].min())
        assert width >= ROAD.carriageway_width + 2.0


class TestItIsDarkInThere:
    """A bore lit like an open hillside is a concrete tube in daylight. The
    lining carries its own shade, so a driver goes into the dark and comes out
    the other end."""

    def test_the_lining_is_shaded(self) -> None:
        meshes = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD)
        assert meshes['bore'].colors is not None

    def test_it_is_darkest_in_the_middle(self) -> None:
        """Away from the portals, with the lamps out: what the bore is like
        before anybody hangs a light in it."""
        meshes = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD,
                               TunnelProfile(lamp_spacing=0.0))
        bore = meshes['bore']
        along = bore.positions[:, 0]
        middle = bore.colors[(along > 180.0) & (along < 220.0), 0]
        assert float(middle.mean()) < 0.35

    def test_and_lit_it_is_brighter_than_that(self) -> None:
        dark = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD,
                             TunnelProfile(lamp_spacing=0.0))['bore']
        lit = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD)['bore']
        inside = (dark.positions[:, 0] > 150.0) & (dark.positions[:, 0] < 250.0)
        assert float(lit.colors[inside, 0].mean()) > \
            float(dark.colors[inside, 0].mean())

    def test_it_is_open_daylight_at_the_portals(self) -> None:
        meshes = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD)
        bore = meshes['bore']
        along = bore.positions[:, 0]
        assert float(bore.colors[along < 1.0, 0].mean()) > 0.9
        assert float(bore.colors[along > 399.0, 0].mean()) > 0.9

    def test_a_short_bore_never_gets_fully_dark(self) -> None:
        """Daylight from both ends meets in the middle of a short one."""
        short = tunnel_meshes(_straight(length=30.0, height=0.0), ROAD)
        long = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD)
        assert float(short['bore'].colors[:, 0].min()) \
            > float(long['bore'].colors[:, 0].min())

    def test_the_portals_are_not_shaded(self) -> None:
        """They are the outside of the hill, in the sun like the rest of it."""
        meshes = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD)
        portals = meshes['portals']
        assert portals.colors is None or float(portals.colors[:, 0].min()) > 0.9

    def test_the_shade_is_opaque(self) -> None:
        """A colour with alpha under one would make the lining see-through."""
        meshes = tunnel_meshes(_straight(length=400.0, height=0.0), ROAD)
        assert np.allclose(meshes['bore'].colors[:, 3], 1.0)


class TestABoreIsAClosedTube:
    """The ground a bore runs through has to be cut away for the carriageway to
    pass, which leaves nothing under the road but the lining. A lining open at
    the bottom is a trench either side of the road for a wheel to drop into."""

    def test_the_lining_closes_under_the_road(self) -> None:
        """The section returns to where it started, so the sweep is a tube."""
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        bore = meshes['bore']
        opened = tunnel_meshes(_straight(height=0.0), ROAD,
                               TunnelProfile(floor=False))['bore']
        ring = len(bore.positions) // 21
        assert np.allclose(bore.positions[0], bore.positions[ring - 1])
        assert not np.allclose(opened.positions[0],
                               opened.positions[len(opened.positions) // 21 - 1])

    def test_a_wheel_under_the_road_meets_the_floor(self) -> None:
        """What the tube is for: a ray straight down from the carriageway hits
        the lining rather than going through to the valley."""
        meshes = tunnel_meshes(_straight(length=100.0, height=0.0), ROAD)
        bore = meshes['bore']
        tri = np.asarray(bore.positions, 'd')[np.asarray(bore.indices)
                                              .reshape(-1, 3)]
        origin = np.array([50.0, 1.0, 0.0])
        down = np.array([0.0, -1.0, 0.0])
        e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        h = np.cross(down, e2)
        a = np.einsum('ij,ij->i', e1, h)
        ok = np.abs(a) > 1e-12
        f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
        rel = origin - tri[:, 0]
        u = f * np.einsum('ij,ij->i', rel, h)
        q = np.cross(rel, e1)
        v = f * np.einsum('j,ij->i', down, q)
        t = f * np.einsum('ij,ij->i', e2, q)
        hit = ok & (u >= -1e-6) & (u <= 1) & (v >= -1e-6) & (u + v <= 1) & (t > 0)
        assert hit.any()

    def test_the_floor_is_just_under_the_carriageway(self) -> None:
        """Far enough down to be out of sight, near enough that a wheel leaving
        the road drops a step rather than falling into a pit."""
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        assert float(meshes['bore'].positions[:, 1].min()) \
            == pytest.approx(-tunnel.springing, abs=0.01)
        assert tunnel.springing < 1.0

    def test_the_walls_stand_close_to_the_road(self) -> None:
        """A bore metres wider than the road it carries is a cavern, and the
        ground cut away for it is a canyon."""
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        bore = meshes['bore']
        half = float(bore.positions[:, 2].max())
        assert half < ROAD.on_structure().total_width / 2.0 + 1.0

    def test_a_bore_can_be_left_open_underneath(self) -> None:
        """For a caller putting its own floor in."""
        open_bore = tunnel_meshes(_straight(height=0.0), ROAD,
                                  TunnelProfile(floor=False))['bore']
        closed = tunnel_meshes(_straight(height=0.0), ROAD)['bore']
        assert len(open_bore.positions) < len(closed.positions)

    def test_the_crown_is_where_it_was(self) -> None:
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(height=0.0), ROAD, tunnel)
        assert float(meshes['bore'].positions[:, 1].max()) == pytest.approx(
            tunnel.clearance, abs=0.6)


class TestTheBarrierIsNotTheStructure:
    """A parapet is the thing closest to the camera for the whole length of a
    viaduct. In fresh-concrete white it is a wall beside the road rather than a
    barrier on it."""

    def test_a_parapet_is_darker_than_the_deck(self) -> None:
        from OpenGLContext.scenegraph.roadworks import barrier_material
        assert sum(barrier_material().baseColor) \
            < sum(concrete_material().baseColor)

    def test_the_parapets_wear_it(self) -> None:
        from OpenGLContext.scenegraph.roadworks import barrier_material
        meshes = bridge_meshes(_straight(), ROAD, _valley)
        assert meshes['parapet'].material is not meshes['deck'].material
        assert tuple(meshes['parapet'].material.baseColor) \
            == pytest.approx(tuple(barrier_material().baseColor))

    def test_a_given_material_is_still_the_one_used(self) -> None:
        mine = concrete_material()
        meshes = bridge_meshes(_straight(), ROAD, _valley, material=mine)
        assert all(mesh.material is mine for mesh in meshes.values())

    def test_a_barrier_of_your_own_can_be_given(self) -> None:
        mine = concrete_material()
        meshes = bridge_meshes(_straight(), ROAD, _valley, barrier=mine)
        assert meshes['parapet'].material is mine
        assert meshes['deck'].material is not mine


class TestWhatADriverCanSeePastTheBarrier:
    """A deck is built over a valley because of what is under it. A barrier
    that hides the valley hides the reason the structure exists."""

    #: Where a driver's eye sits above the carriageway, in metres, and how far
    #: the barrier stands to the side of them: a low car in the near lane.
    EYE = 1.31
    OFFSET = 3.6

    def test_a_kerb_and_a_railing_can_be_seen_down_past(self) -> None:
        assert BarrierProfile().sightline(self.EYE, self.OFFSET) > 12.0

    def test_a_wall_at_eye_height_cannot_be(self) -> None:
        wall = BarrierProfile(height=0.95, kerb=0.95)
        assert wall.sightline(self.EYE, self.OFFSET) < 6.0

    def test_a_wall_above_eye_height_shows_nothing_at_all(self) -> None:
        wall = BarrierProfile(height=1.6, kerb=1.6)
        assert wall.sightline(self.EYE, self.OFFSET) == 0.0

    def test_the_railing_above_the_kerb_costs_no_sightline(self) -> None:
        """It is looked through, so how tall it is does not enter into it."""
        low = BarrierProfile(height=1.1, kerb=0.35)
        tall = BarrierProfile(height=1.6, kerb=0.35)
        assert low.sightline(self.EYE, self.OFFSET) == \
            tall.sightline(self.EYE, self.OFFSET)

    def test_standing_further_out_lets_less_be_seen_down_past(self) -> None:
        barrier = BarrierProfile()
        assert barrier.sightline(self.EYE, 8.0) < barrier.sightline(self.EYE, 3.6)

    def test_a_barrier_at_no_offset_at_all_is_looked_straight_down(self) -> None:
        assert BarrierProfile().sightline(self.EYE, 0.0) == 90.0

    def test_a_kerb_as_tall_as_the_barrier_is_a_wall(self) -> None:
        assert BarrierProfile(height=0.8, kerb=0.8).solid

    def test_and_one_below_it_is_not(self) -> None:
        assert not BarrierProfile().solid


class TestTheRailingOnADeck:
    def test_a_deck_gets_a_railing_by_default(self) -> None:
        """Standing over a valley, which is what a deck is for."""
        assert not BridgeProfile().parapet.solid

    def test_it_reaches_the_height_the_barrier_is_built_to(self) -> None:
        bridge = BridgeProfile()
        meshes = bridge_meshes(_straight(height=40.0), ROAD, _valley, bridge)
        assert float(meshes['parapet'].positions[:, 1].max()) == pytest.approx(
            40.0 + bridge.parapet.height, abs=0.2)

    def test_the_bars_run_between_the_kerb_and_the_top(self) -> None:
        barrier = BarrierProfile(height=1.1, kerb=0.35, rails=2)
        from OpenGLContext.scenegraph.roadworks import _rail_heights
        assert _rail_heights(barrier) == pytest.approx([0.725, 1.1])

    def test_the_topmost_bar_is_the_top_of_the_barrier(self) -> None:
        from OpenGLContext.scenegraph.roadworks import _rail_heights
        for count in (1, 2, 3, 5):
            barrier = BarrierProfile(rails=count)
            assert _rail_heights(barrier)[-1] == pytest.approx(barrier.height)

    def test_a_railing_is_mostly_holes(self) -> None:
        """Which is the whole of why it is one: a wall of the same height over
        the same length is a great deal more surface."""
        line = _straight(length=200.0, height=40.0)
        railing = bridge_meshes(line, ROAD, _valley, BridgeProfile())['parapet']
        wall = bridge_meshes(line, ROAD, _valley, BridgeProfile(
            parapet=BarrierProfile(height=1.1, kerb=1.1)))['parapet']
        assert _face_area(railing) < _face_area(wall) * 0.75

    def test_a_solid_barrier_builds_no_railing(self) -> None:
        line = _straight(length=200.0, height=40.0)
        wall = bridge_meshes(line, ROAD, _valley, BridgeProfile(
            parapet=BarrierProfile(height=1.1, kerb=1.1)))['parapet']
        plain = bridge_meshes(line, ROAD, _valley, BridgeProfile(
            parapet=BarrierProfile(height=1.1, kerb=1.1, rails=0)))['parapet']
        assert len(wall.positions) == len(plain.positions)

    def test_a_railing_with_no_posts_still_has_its_bars(self) -> None:
        line = _straight(length=200.0, height=40.0)
        meshes = bridge_meshes(line, ROAD, _valley, BridgeProfile(
            parapet=BarrierProfile(post_spacing=0.0)))
        assert float(meshes['parapet'].positions[:, 1].max()) == pytest.approx(
            40.0 + BarrierProfile().height, abs=0.2)

    def test_every_mesh_is_still_well_formed(self) -> None:
        _fits(bridge_meshes(_straight(), ROAD, _valley))


def _face_area(mesh):
    """The total area of a mesh's triangles."""
    corners = mesh.positions[mesh.indices.reshape(-1, 3)]
    cross = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    return float(np.linalg.norm(cross, axis=1).sum() / 2.0)


class TestTheLampsInABore:
    """A bore a hundred metres in is dark, and a road nobody can see is not a
    road. Real ones are lit, so this one is: fittings along the crown, and the
    pool each throws baked into the lining it falls on.
    """

    def _bore(self, length=300.0, **named):
        return _straight(length=length, height=0.0, spacing=5.0), \
            TunnelProfile(**named)

    def test_a_bore_carries_its_lamps(self):
        line, tunnel = self._bore()
        assert len(tunnel_lamps(line, tunnel))

    def test_they_are_spaced_along_it(self):
        line, tunnel = self._bore(length=300.0, lamp_spacing=25.0)
        lamps = tunnel_lamps(line, tunnel)
        gaps = np.linalg.norm(np.diff(lamps, axis=0), axis=1)
        assert gaps == pytest.approx(25.0, abs=5.0)

    def test_a_wider_spacing_is_fewer_of_them(self):
        line, _ = self._bore(length=300.0)
        assert len(tunnel_lamps(line, TunnelProfile(lamp_spacing=50.0))) < \
            len(tunnel_lamps(line, TunnelProfile(lamp_spacing=20.0)))

    def test_they_hang_below_the_crown(self):
        line, tunnel = self._bore()
        lamps = tunnel_lamps(line, tunnel)
        assert lamps[:, 1] == pytest.approx(
            tunnel.clearance - tunnel.lamp_drop, abs=0.01)

    def test_and_over_the_middle_of_the_road(self):
        line, tunnel = self._bore()
        assert tunnel_lamps(line, tunnel)[:, 2] == pytest.approx(0.0, abs=0.01)

    def test_a_bore_with_no_lamps_asked_for_has_none(self):
        line, _ = self._bore()
        assert len(tunnel_lamps(line, TunnelProfile(lamp_spacing=0.0))) == 0

    def test_a_bore_shorter_than_one_spacing_still_gets_one(self):
        """A short bore is still dark in the middle of it."""
        line = _straight(length=15.0, height=0.0, spacing=5.0)
        assert len(tunnel_lamps(line, TunnelProfile(lamp_spacing=40.0))) == 1


class TestWhatTheLampsDoToTheLining:
    def _shade(self, **named):
        line = _straight(length=400.0, height=0.0, spacing=2.0)
        return line, TunnelProfile(**named)

    def test_the_lining_is_brighter_under_a_lamp_than_between_two(self):
        line, tunnel = self._shade(lamp_spacing=40.0, daylight=1.0)
        shade = bore_shade(line, tunnel)
        lamps = tunnel_lamps(line, tunnel)
        # A lamp well away from either portal, and the point midway to the next.
        under = int(np.argmin(np.abs(line[:, 0] - lamps[4, 0])))
        between = int(np.argmin(np.abs(
            line[:, 0] - (lamps[4, 0] + lamps[5, 0]) / 2.0)))
        assert shade[under] > shade[between]

    def test_with_no_lamps_it_is_the_gloom_all_the_way(self):
        line, tunnel = self._shade(lamp_spacing=0.0, daylight=1.0, gloom=0.14)
        middle = bore_shade(line, tunnel)[len(line) // 2]
        assert middle == pytest.approx(0.14, abs=0.01)

    def test_the_portals_are_still_the_brightest_thing_in_it(self):
        line, tunnel = self._shade(lamp_spacing=40.0)
        shade = bore_shade(line, tunnel)
        assert shade[0] == pytest.approx(1.0, abs=0.01)
        assert shade[0] >= shade.max() - 1e-6

    def test_nothing_is_brighter_than_daylight(self):
        line, tunnel = self._shade(lamp_spacing=10.0, lamp_glow=5.0)
        assert bore_shade(line, tunnel).max() <= 1.0 + 1e-9

    def test_a_brighter_lamp_lifts_the_lining_further(self):
        line, _ = self._shade()
        dim = TunnelProfile(lamp_spacing=40.0, lamp_glow=0.2, daylight=1.0)
        bright = TunnelProfile(lamp_spacing=40.0, lamp_glow=0.8, daylight=1.0)
        under = int(np.argmin(np.abs(line[:, 0] - tunnel_lamps(line, dim)[4, 0])))
        assert bore_shade(line, bright)[under] > bore_shade(line, dim)[under]

    def test_it_never_goes_darker_than_the_gloom(self):
        line, tunnel = self._shade(lamp_spacing=40.0, gloom=0.14, daylight=1.0)
        assert bore_shade(line, tunnel).min() >= 0.14 - 1e-9


class TestTheFittingsThemselves:
    def test_a_bore_is_built_with_lamps_in_it(self):
        meshes = tunnel_meshes(_straight(length=300.0, height=0.0), ROAD)
        assert 'lamps' in meshes and len(meshes['lamps'].positions)

    def test_they_are_well_formed(self):
        _fits(tunnel_meshes(_straight(length=300.0, height=0.0), ROAD))

    def test_a_bore_with_no_lamps_asked_for_is_built_without_them(self):
        meshes = tunnel_meshes(_straight(length=300.0, height=0.0), ROAD,
                               TunnelProfile(lamp_spacing=0.0))
        assert 'lamps' not in meshes

    def test_a_fitting_burns_rather_than_being_lit(self):
        """It is the light in there; nothing else is going to light it."""
        meshes = tunnel_meshes(_straight(length=300.0, height=0.0), ROAD)
        assert max(meshes['lamps'].material.emissiveColor) > 0.5

    def test_they_are_up_at_the_crown_rather_than_on_the_road(self):
        tunnel = TunnelProfile()
        meshes = tunnel_meshes(_straight(length=300.0, height=0.0), ROAD, tunnel)
        assert float(meshes['lamps'].positions[:, 1].min()) > tunnel.clearance / 2.0
