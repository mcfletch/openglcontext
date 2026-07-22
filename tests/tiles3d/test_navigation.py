"""Physics navigation over procedural terrain (headless).

Validates the walk/fly workflow the terrain must support: gravity settles the avatar
onto the surface, walking follows the terrain, flying moves freely, and switching
from fly back to walk drops the avatar to the surface. Pure numpy physics against the
terrain's static trimesh collider — no GL.
"""
import numpy as np
import pytest

from omi_physics.world import PhysicsWorld
from omi_physics import model
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.loaders.tiles3d import procedural as P


def _terrain_world(extent=400.0, res=81):
    pos, nrm, col, idx = P.terrain_patch(-extent / 2, extent / 2,
                                         -extent / 2, extent / 2, res)
    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    shape = world.add_shape(model.Shape.trimesh(
        pos.astype("d"), idx.reshape(-1, 3)))
    world.add_body(model.Motion(type=model.STATIC),
                   collider=model.Collider(shape=shape))
    return world


def _surface(x, z):
    return max(float(P.terrain_height(np.array([x]), np.array([z]))[0]),
               P.WATER_LEVEL)


def _flat_spot():
    """Find a gentle (walkable) location above water for deterministic walking."""
    best, best_slope = (30.0, 30.0), 1e9
    for x in np.linspace(-120, 120, 13):
        for z in np.linspace(-120, 120, 13):
            h = _surface(x, z)
            if h < P.WATER_LEVEL + 3:
                continue
            dx = _surface(x + 4, z) - _surface(x - 4, z)
            dz = _surface(x, z + 4) - _surface(x, z - 4)
            slope = (dx * dx + dz * dz) ** 0.5
            if slope < best_slope:
                best_slope, best = slope, (float(x), float(z))
    return best


def _step(platform, steps, dt=1.0 / 60.0):
    for _ in range(steps):
        platform.update(dt)


def test_gravity_settles_avatar_onto_the_surface():
    world = _terrain_world()
    x, z = _flat_spot()
    surf = _surface(x, z)
    plat = PhysicsViewPlatform(world, position=(x, surf + 40, z))
    plat.bind((x, surf + 40, z))
    _step(plat, 700)
    base_y = plat.character.base()[1]
    assert plat.character.grounded
    assert abs(base_y - surf) < 2.5, (base_y, surf)


def test_walking_follows_the_terrain_surface():
    world = _terrain_world()
    x, z = _flat_spot()
    surf = _surface(x, z)
    plat = PhysicsViewPlatform(world, position=(x, surf + 5, z))
    plat.bind((x, surf + 5, z))
    _step(plat, 200)                       # settle
    start = plat.character.position.copy()
    plat.set_move(forward=1.0, strafe=0.0, mode="walk")
    _step(plat, 240)                       # walk ~4s
    plat.set_move(0.0, 0.0)
    end = plat.character.position
    horizontal = np.linalg.norm((end - start)[[0, 2]])
    assert horizontal > 3.0, "avatar did not walk"
    # Still on the surface at the new location (grounded, base near terrain height).
    base_y = plat.character.base()[1]
    here = _surface(end[0], end[2])
    assert abs(base_y - here) < 3.0, (base_y, here)
    assert plat.character.grounded


def test_flying_moves_freely_above_the_surface():
    world = _terrain_world()
    x, z = _flat_spot()
    surf = _surface(x, z)
    plat = PhysicsViewPlatform(world, position=(x, surf + 5, z))
    plat.bind((x, surf + 5, z))
    _step(plat, 120)
    y0 = plat.character.position[1]
    plat.set_fly(True)
    plat.set_fly_move(forward=0.0, strafe=0.0, up=1.0)
    _step(plat, 180)
    y1 = plat.character.position[1]
    assert y1 > y0 + 10.0, "fly did not ascend"
    assert not plat.character.grounded


def test_switch_fly_to_walk_drops_to_surface():
    world = _terrain_world()
    x, z = _flat_spot()
    surf = _surface(x, z)
    plat = PhysicsViewPlatform(world, position=(x, surf + 5, z))
    plat.bind((x, surf + 5, z))
    _step(plat, 120)
    # Fly up high.
    plat.set_fly(True)
    plat.set_fly_move(up=1.0)
    _step(plat, 240)
    high = plat.character.position[1]
    assert high > surf + 20
    # Switch to walk: gravity should pull the avatar back down to the surface.
    plat.set_fly_move(0.0, 0.0, 0.0)
    plat.set_fly(False)
    _step(plat, 700)
    base_y = plat.character.base()[1]
    assert base_y < high - 15.0, "did not drop"
    assert abs(base_y - _surface(*plat.character.position[[0, 2]])) < 3.0
    assert plat.character.grounded


def test_avatar_walks_on_streamed_tileset_colliders(tmp_path):
    """Full loop: terrain streams -> per-tile colliders register -> avatar stands on them."""
    import os, json, math
    from OpenGLContext.scenegraph.tilesterrain import TilesTerrain
    from OpenGLContext.loaders.tiles3d import procedural as PR

    world = PhysicsWorld(gravity=model.Gravity(gravity=9.81, direction=(0, -1, 0)))
    path = PR.build_terrain_tileset(str(tmp_path), extent=1024, levels=2, tile_res=33)
    terrain = TilesTerrain(path, fovy=math.radians(50.0), workers=4,
                           physics_world=world, memory_budget=64 * 1024 * 1024)
    try:
        # Stream the tiles near a spot so their colliders enter the world.
        x, z = 0.0, 0.0
        surf = _surface(x, z)
        for _ in range(8):
            terrain.update_for_camera((x, surf + 60, z), 720)
            terrain.wait_for_loads(timeout=6.0)
        assert terrain.colliders.collider_count >= 1
        assert len(world.bodies) >= 1
        # Drop an avatar onto the streamed terrain; gravity should seat it on the surface.
        plat = PhysicsViewPlatform(world, position=(x, surf + 30, z))
        plat.bind((x, surf + 30, z))
        for _ in range(700):
            plat.update(1.0 / 60.0)
        assert plat.character.grounded
        assert abs(plat.character.base()[1] - surf) < 3.0
    finally:
        terrain.shutdown()


def test_walks_a_long_distance_without_getting_stuck():
    """The viewer's collision is one skirt-free surface; walking should travel far,
    not bounce back against skirt walls or overlapping LOD colliders."""
    world = _terrain_world(extent=1200.0, res=161)   # skirt-free (skirt_depth=0)
    x, z = _flat_spot()
    surf = _surface(x, z)
    from omi_physics.character import CharacterCapabilities
    caps = CharacterCapabilities(walkSpeed=16.0, stepHeight=0.7, eyeHeight=1.7)
    plat = PhysicsViewPlatform(world, caps, position=(x, surf + 5, z), yaw=0.0)
    plat.bind((x, surf + 5, z))
    _step(plat, 200)                       # settle
    start = plat.character.position.copy()
    plat.set_move(forward=1.0, mode="walk")
    # Walk ~10 s; at 16 m/s that is a long way across the terrain.
    positions = []
    for _ in range(600):
        plat.update(1.0 / 60.0)
        positions.append(plat.character.position.copy())
    travelled = np.linalg.norm((plat.character.position - start)[[0, 2]])
    # It kept moving (no trap): net displacement is large and it never froze for long.
    assert travelled > 60.0, "avatar got stuck (travelled only %.1f m)" % travelled
    steps = np.linalg.norm(np.diff(positions, axis=0)[:, [0, 2]], axis=1)
    assert (steps > 0.05).mean() > 0.8, "avatar repeatedly stalled"
