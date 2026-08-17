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
    BridgeProfile,
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
            40.0 + bridge.parapet_height, abs=0.5)
        # One each side, out at the deck's edge.
        assert float(rails.positions[:, 2].min()) < -ROAD.total_width / 2.0 + 1.0
        assert float(rails.positions[:, 2].max()) > ROAD.total_width / 2.0 - 1.0

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
            return np.asarray(x, dtype='d') * 0.2
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
        assert width == pytest.approx(ROAD.total_width, abs=0.5)

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

    def test_the_bore_springs_from_the_road(self) -> None:
        meshes = tunnel_meshes(_straight(height=0.0), ROAD)
        bore = meshes['bore']
        assert float(bore.positions[:, 1].min()) == pytest.approx(0.0, abs=0.3)

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
