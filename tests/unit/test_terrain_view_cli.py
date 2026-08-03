"""oglc-terrain viewer: CLI parsing, world resolution, and the non-GL helpers
(surface sampling, spawn search, scatter slicing, view-projection, input handlers,
ground clamp and object collision). OnInit and the OnIdle movement loop drive a live
window + streaming and are covered by the terrain render/subprocess tests, not here."""
import os
import types

import numpy as np
import pytest

# Importing the viewer runs module-level os.environ.setdefault() calls that
# configure the renderer; snapshot/restore so they don't leak into other GL
# subprocess tests (mirrors test_gltf_view_cli.py).
_ENV_KEYS = ('OPENGLCONTEXT_PROFILE', 'OPENGLCONTEXT_RENDERER', 'OPENGLCONTEXT_IBL',
             'OPENGLCONTEXT_BACKEND', 'OPENGLCONTEXT_SHADOWS',
             'OPENGLCONTEXT_SHADOW_CASCADES')
_ENV_SNAPSHOT = {k: os.environ.get(k) for k in _ENV_KEYS}
from OpenGLContext.bin import terrain_view as T  # noqa: E402
from OpenGLContext.loaders.tiles3d import procedural as P  # noqa: E402
from OpenGLContext.loaders.tiles3d.scatter import Scatter  # noqa: E402
for _k, _v in _ENV_SNAPSHOT.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v


def _inst():
    return T.TerrainContext.__new__(T.TerrainContext)


class TestParser:
    def test_defaults(self):
        a = T.build_parser().parse_args([])
        assert a.source is None and a.dem is None
        assert a.extent == 2048.0 and a.levels == 3 and a.tile_res == 33
        assert a.height_scale == 400.0 and a.base == -40.0
        assert a.sse == 16.0 and a.memory == 256 and a.density == 1.0
        assert a.no_vegetation is False and a.fly is False and a.size is None

    def test_representative_flags(self):
        a = T.build_parser().parse_args(
            ['world.json', '--extent', '512', '--levels', '2', '--fly',
             '--no-vegetation', '--density', '0.5', '--size', '640x480'])
        assert a.source == 'world.json' and a.extent == 512.0 and a.levels == 2
        assert a.fly is True and a.no_vegetation is True and a.density == 0.5
        assert a.size == '640x480'


class TestMain:
    def test_tileset_and_dem_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            T.main(['world.json', '--dem', 'height.png'])

    def test_runs_loop_and_publishes_config(self, monkeypatch):
        ran = {}
        monkeypatch.setattr(T.TerrainContext, 'ContextMainLoop',
                            classmethod(lambda cls: ran.setdefault('size', 'default')))
        T.main([])
        assert ran.get('size') == 'default'
        assert T.TerrainContext.config.source is None

    def test_size_flag_is_parsed_into_the_loop(self, monkeypatch):
        seen = {}
        monkeypatch.setattr(T.TerrainContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: seen.setdefault('size', size)))
        T.main(['--size', '800x600'])
        assert seen['size'] == (800, 600)


class TestResolveWorld:
    def test_existing_tileset_json_is_used_as_is_without_a_height_field(self):
        cfg = T.build_parser().parse_args(['world.json'])
        path, height_fn = T._resolve_world(cfg)
        assert path == 'world.json' and height_fn is None

    def test_procedural_world_bakes_a_tileset_and_returns_a_height_fn(self):
        cfg = T.build_parser().parse_args(['--extent', '256', '--levels', '1',
                                           '--tile-res', '9'])
        path, height_fn = T._resolve_world(cfg)
        assert os.path.exists(path) and path.endswith('.json')
        assert height_fn is P.terrain_height

    def test_dem_world_bakes_from_a_heightmap_image(self, tmp_path):
        pytest.importorskip('PIL')
        from PIL import Image
        dem = tmp_path / 'height.png'
        Image.fromarray((np.random.default_rng(0).random((16, 16)) * 255)
                        .astype('uint8'), 'L').save(dem)
        cfg = T.build_parser().parse_args(['--dem', str(dem), '--extent', '256',
                                           '--levels', '1', '--tile-res', '9'])
        path, height_fn = T._resolve_world(cfg)
        assert os.path.exists(path)
        # a DEM world drives collision from its own height function, not the noise one
        assert height_fn is not None and height_fn is not P.terrain_height


class TestSurfaceAndSpawn:
    def test_surface_never_returns_below_the_water_level(self):
        # a point the procedural height field pushes below water clamps to WATER_LEVEL
        vals = [T._surface(P.terrain_height, x, z)
                for x in (-50, 0, 50) for z in (-50, 0, 50)]
        assert all(v >= P.WATER_LEVEL for v in vals)

    def test_walkable_spawn_lands_on_a_gentle_dry_slope(self):
        x, y, z = T._walkable_spawn(P.terrain_height)
        assert y == pytest.approx(T._surface(P.terrain_height, x, z))
        assert y >= P.WATER_LEVEL


class TestWaterAndScatter:
    def test_water_surface_scales_with_extent(self):
        shape = T._water(200.0)
        assert shape.geometry.size[0] == pytest.approx(200.0 * 1.2)
        assert shape.appearance.material.transparency == pytest.approx(0.35)

    def test_slice_scatter_takes_every_nth_placement(self):
        pos = np.arange(30, dtype='d').reshape(10, 3)
        s = Scatter(pos, np.zeros(10), np.ones(10))
        part = T._slice_scatter(s, 1, 3)             # rows 1,4,7
        assert len(part) == 3
        assert np.allclose(part.positions[:, 0], [3.0, 12.0, 21.0])


class TestViewProjection:
    def test_falls_back_to_a_default_heading_without_an_avatar(self):
        inst = _inst()
        inst.avatar = None
        m = inst._view_projection((0.0, 100.0, 0.0))
        assert np.asarray(m).shape == (4, 4)

    def test_uses_the_avatar_heading_when_present(self):
        inst = _inst()
        inst.avatar = types.SimpleNamespace(yaw=1.2, pitch=-0.2)
        m = inst._view_projection((0.0, 50.0, 0.0))
        assert np.asarray(m).shape == (4, 4)
        assert np.isfinite(np.asarray(m)).all()


class TestInputHandlers:
    def test_key_down_records_time_and_key_up_clears_it(self):
        inst = _inst()
        inst._keys = {}
        inst._on_key(types.SimpleNamespace(name='w'))
        assert 'w' in inst._keys
        inst._on_key_up(types.SimpleNamespace(name='w'))
        assert 'w' not in inst._keys

    def test_shift_toggles_sprint(self):
        inst = _inst()
        inst._shift_on(None)
        assert inst._sprint is True
        inst._shift_off(None)
        assert inst._sprint is False

    def test_jump_delegates_to_the_avatar(self):
        inst = _inst()
        jumped = {}
        inst.avatar = types.SimpleNamespace(jump=lambda: jumped.setdefault('j', True))
        inst._on_jump(None)
        assert jumped['j'] is True

    def test_toggle_fly_flips_state_and_updates_the_avatar(self):
        inst = _inst()
        inst._flying = False
        seen = {}
        inst.avatar = types.SimpleNamespace(set_fly=lambda v: seen.setdefault('fly', v))
        inst._toggle_fly(None)
        assert inst._flying is True and seen['fly'] is True

    def test_speed_multiplier_ramps_and_clamps(self):
        inst = _inst()
        inst._mult = 1.0
        for _ in range(10):
            inst._faster(None)
        assert inst._mult == pytest.approx(8.0)        # clamped high
        for _ in range(20):
            inst._slower(None)
        assert inst._mult == pytest.approx(0.25)       # clamped low

    def test_the_multiplier_scales_the_speed_of_each_tier(self):
        inst = _inst()
        inst._speeds = dict(walk=16.0, sprint=90.0, fly=90.0)
        inst._mult = 2.0
        assert inst._moveSpeed('walk') == pytest.approx(32.0)
        assert inst._moveSpeed('fly') == pytest.approx(180.0)

    def test_the_multiplier_does_not_compound_frame_on_frame(self):
        """Scaled from what the avatar was built with, not from what it is
        moving at: the body holds whatever was last asked for, so scaling that
        would double the speed every frame the key stayed as it was."""
        inst = _inst()
        inst._speeds = dict(walk=16.0, sprint=90.0, fly=90.0)
        inst._mult = 2.0
        first = inst._moveSpeed('walk')
        for _ in range(10):
            inst._moveSpeed('walk')
        assert inst._moveSpeed('walk') == pytest.approx(first)


class TestSceneMutation:
    def test_swap_child_replaces_the_existing_node(self):
        inst = _inst()
        old, new = object(), object()
        inst.sg = types.SimpleNamespace(children=[old, 'keep'])
        inst._swap_child(old, new)
        assert new in inst.sg.children and old not in inst.sg.children
        assert 'keep' in inst.sg.children

    def test_swap_child_appends_when_there_is_no_old_node(self):
        inst = _inst()
        inst.sg = types.SimpleNamespace(children=['keep'])
        new = object()
        inst._swap_child(None, new)
        assert inst.sg.children == ['keep', new]

    def test_maybe_refresh_is_a_noop_when_vegetation_is_disabled(self):
        inst = _inst()
        inst._veg = True
        inst._maybe_refresh_vegetation((0.0, 0.0, 0.0))     # must not touch missing attrs

    def test_maybe_refresh_leaves_layers_alone_when_the_camera_barely_moved(self):
        inst = _inst()
        inst._veg = False
        here = np.array([1.0, 1.0])
        inst._grass_center = here
        inst._detail_center = here
        inst._trees_center = here
        inst._ground_center = here
        called = {}
        for name in ('_refresh_grass', '_refresh_detail', '_refresh_trees',
                     '_refresh_ground'):
            setattr(inst, name, lambda *a, n=name: called.setdefault(n, True))
        inst._maybe_refresh_vegetation((1.0, 5.0, 1.0))     # within every threshold
        assert called == {}

    def test_maybe_refresh_restreams_every_layer_after_a_long_walk(self):
        inst = _inst()
        inst._veg = False
        far = np.array([1000.0, 1000.0])            # last refresh was far away
        inst._grass_center = far
        inst._detail_center = far
        inst._trees_center = far
        inst._ground_center = far
        called = {}
        for name in ('_refresh_grass', '_refresh_detail', '_refresh_trees',
                     '_refresh_ground'):
            setattr(inst, name, lambda *a, n=name: called.setdefault(n, True))
        inst._maybe_refresh_vegetation((0.0, 5.0, 0.0))     # exceeds every threshold
        assert called == {'_refresh_grass': True, '_refresh_detail': True,
                          '_refresh_trees': True, '_refresh_ground': True}


def _group():
    from OpenGLContext.scenegraph.group import Group
    return Group()


class TestVegetationRefresh:
    """The camera-following layers restream real Scatter placements into scene
    Groups; drive them with lightweight prototype nodes over the procedural height
    field (no GL upload happens at build time)."""

    def _base(self):
        inst = _inst()
        inst.config = types.SimpleNamespace(density=1.0)
        inst.height_fn = P.terrain_height
        inst.sg = types.SimpleNamespace(children=[])
        inst._spawn_xz = np.array([0.0, 0.0])
        return inst

    def test_refresh_grass_swaps_in_a_new_node_and_records_the_centre(self):
        inst = self._base()
        inst._grass_near = _group()
        inst._grass_far = _group()
        inst._grass_node = None
        inst._refresh_grass((10.0, 0.0, -10.0))
        assert inst._grass_node in inst.sg.children
        assert np.allclose(inst._grass_center, [10.0, -10.0])

    def test_refresh_trees_records_collider_positions(self):
        inst = self._base()
        inst._tree_proto = _group()
        inst._tree_far = _group()
        inst._tree_keep = lambda p: np.ones(len(p), dtype=bool)
        inst._trees_node = None
        inst._refresh_trees((0.0, 0.0, 0.0))
        assert inst._trees_node in inst.sg.children
        assert inst._tree_pos.shape[1] == 2         # (x,z) collider footprints

    def test_refresh_detail_without_rock_prototypes_still_places_flora(self):
        inst = self._base()
        inst._rock_protos = []                      # offline -> no CC0 rock material
        inst._flower_proto = _group()
        inst._branch_proto = _group()
        inst._detail_node = None
        inst._refresh_detail((0.0, 0.0, 0.0))
        assert inst._detail_node in inst.sg.children


class TestStream:
    def test_stream_is_skipped_without_a_streamed_tileset(self):
        inst = _inst()
        inst.terrain = None
        inst._stream((0.0, 0.0, 0.0))               # returns quietly

    def test_stream_forwards_the_viewport_height_and_view_projection(self):
        inst = _inst()
        inst.avatar = types.SimpleNamespace(yaw=0.6, pitch=-0.1)
        inst.getViewPort = lambda: (800, 600)
        seen = {}
        inst.terrain = types.SimpleNamespace(
            update_for_camera=lambda eye, h, view_projection=None: seen.update(
                height=h, vp=view_projection))
        inst._stream((0.0, 100.0, 0.0))
        assert seen['height'] == 600
        assert np.asarray(seen['vp']).shape == (4, 4)


class TestOnIdle:
    def test_returns_zero_before_the_avatar_exists(self):
        inst = _inst()
        assert inst.OnIdle() == 0


class TestGroundAndCollision:
    def test_ground_clamp_is_skipped_for_a_raw_tileset(self):
        inst = _inst()
        inst.height_fn = None
        inst._ground_clamp()                                 # no avatar needed, returns

    def test_ground_clamp_snaps_the_avatar_onto_the_surface(self):
        inst = _inst()
        inst.height_fn = P.terrain_height
        inst._flying = False
        surf = T._surface(P.terrain_height, 0.0, 0.0)
        ch = types.SimpleNamespace(position=np.array([0.0, surf - 5.0, 0.0], 'd'),
                                   height=2.0, vy=-3.0, grounded=False)
        inst.avatar = types.SimpleNamespace(character=ch)
        inst._ground_clamp()
        assert ch.position[1] == pytest.approx(surf + 1.0)   # base sits on the surface
        assert ch.vy == 0.0 and ch.grounded is True

    def test_object_collision_pushes_the_avatar_out_of_a_trunk(self):
        inst = _inst()
        ch = types.SimpleNamespace(
            position=np.array([0.1, 5.0, 0.0], 'd'),
            caps=types.SimpleNamespace(radius=0.3))
        inst.avatar = types.SimpleNamespace(character=ch)
        inst._tree_pos = np.array([[0.0, 0.0]])              # trunk at the origin
        inst._rock_pos = np.zeros((0, 2))
        inst._rock_rad = np.zeros(0)
        inst._object_collision()
        # pushed outward to at least the combined radius (0.45 trunk + 0.3 avatar)
        assert np.hypot(ch.position[0], ch.position[2]) >= 0.74


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
