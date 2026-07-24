"""oglc-tiles viewer: CLI parsing, source validation, and the non-GL streaming
helpers (leaf descent, look-direction, camera framing, view-projection). The GL
main loop / OnInit residency priming needs a live window and is covered by the
subprocess render tests, not here."""
import argparse
import os
import types

import numpy as np
import pytest

from OpenGLContext import quaternion
from OpenGLContext.bin import tiles_view as T


class TestParser:
    def test_defaults(self):
        a = T.build_parser().parse_args(['scene.json'])
        assert a.source == 'scene.json'
        assert a.sse == 16.0
        assert a.memory == 512
        assert a.fov == 55.0
        assert a.margin == 1.15
        assert a.no_recenter is False
        assert a.cache_dir is None
        assert a.capture is None
        assert a.frames == 16

    def test_representative_flags(self):
        a = T.build_parser().parse_args(
            ['ts.json', '--sse', '8', '--memory', '256', '--fov', '70',
             '--margin', '0.9', '--no-recenter', '--cache-dir', '/tmp/c',
             '--capture', 'shot.png', '--frames', '4'])
        assert a.sse == 8.0 and a.memory == 256 and a.fov == 70.0
        assert a.margin == 0.9 and a.no_recenter is True
        assert a.cache_dir == '/tmp/c'
        assert a.capture == 'shot.png' and a.frames == 4


class TestLeafTile:
    def test_descends_to_first_content_tile(self):
        leaf = types.SimpleNamespace(content_uri='mesh.glb', children=[])
        grouping = types.SimpleNamespace(content_uri=None, children=[leaf])
        root = types.SimpleNamespace(content_uri=None, children=[grouping])
        assert T._leaf_tile(root) is leaf

    def test_stops_at_a_tile_that_has_content(self):
        root = types.SimpleNamespace(content_uri='root.glb',
                                     children=[types.SimpleNamespace(
                                         content_uri='c.glb', children=[])])
        assert T._leaf_tile(root) is root

    def test_stops_at_a_childless_tile(self):
        root = types.SimpleNamespace(content_uri=None, children=[])
        assert T._leaf_tile(root) is root


class TestForward:
    def test_identity_looks_down_negative_z(self):
        fwd = T._forward(quaternion.fromXYZR(0, 1, 0, 0.0))
        assert np.allclose(fwd, [0.0, 0.0, -1.0], atol=1e-6)

    def test_half_turn_looks_down_positive_z(self):
        fwd = T._forward(quaternion.fromXYZR(0, 1, 0, np.pi))
        assert np.allclose(fwd, [0.0, 0.0, 1.0], atol=1e-6)


def _framed_instance(fov=55.0, margin=1.15, radius=10.0, center=(0.0, 0.0, 0.0)):
    inst = T.TilesViewContext.__new__(T.TilesViewContext)
    inst.config = argparse.Namespace(fov=fov, margin=margin)
    inst._radius = radius
    inst._center = np.asarray(center, dtype='d')
    return inst


def _framing_instance(loader, root):
    inst = T.TilesViewContext.__new__(T.TilesViewContext)
    inst.terrain = types.SimpleNamespace(tileset=types.SimpleNamespace(root=root))
    inst._tile_loader = loader
    return inst


def _leaf_loader(center):
    def loader(leaf):
        return types.SimpleNamespace(center=center), None
    return loader


class TestFraming:
    def _root(self, center=(0.0, 0.0, 0.0), radius=10.0):
        return types.SimpleNamespace(
            content_uri='mesh.glb', children=[], world_transform=np.eye(4),
            bounding_volume=types.SimpleNamespace(
                bounding_sphere=lambda: (center, radius)))

    def test_uses_the_leaf_mesh_centre_when_it_lands_inside_the_extent(self):
        root = self._root(center=(0.0, 0.0, 0.0), radius=10.0)
        loader = _leaf_loader((2.0, 0.0, 1.0))
        inst = _framing_instance(loader, root)
        center, radius = T.TilesViewContext._framing(inst)
        assert np.allclose(center, [2.0, 0.0, 1.0])      # aim moved onto the mesh
        assert radius == 10.0

    def test_keeps_the_bounding_centre_when_the_mesh_aim_is_out_of_range(self):
        root = self._root(center=(0.0, 0.0, 0.0), radius=1.0)
        loader = _leaf_loader((100.0, 0.0, 0.0))
        inst = _framing_instance(loader, root)
        center, _ = T.TilesViewContext._framing(inst)
        assert np.allclose(center, [0.0, 0.0, 0.0])      # aim rejected as too far

    def test_falls_back_to_the_bounding_centre_when_the_tile_load_fails(self):
        root = self._root(center=(3.0, 0.0, 0.0), radius=5.0)
        def loader(leaf):
            raise RuntimeError('tile fetch failed')
        inst = _framing_instance(loader, root)
        center, radius = T.TilesViewContext._framing(inst)
        assert np.allclose(center, [3.0, 0.0, 0.0]) and radius == 5.0

    def test_a_zero_radius_bounding_volume_is_clamped_to_one(self):
        root = self._root(center=(0.0, 0.0, 0.0), radius=0.0)
        loader = _leaf_loader((0.0, 0.0, 0.0))
        inst = _framing_instance(loader, root)
        _, radius = T.TilesViewContext._framing(inst)
        assert radius == 1.0


class TestFrameCamera:
    def test_eye0_sits_above_and_back_from_the_centre(self):
        inst = _framed_instance()
        T.TilesViewContext._frame_camera(inst)
        # a small upward offset (r * 0.22) and a positive Z pull-back
        assert inst._eye0[1] == pytest.approx(10.0 * 0.22)
        assert inst._eye0[2] > 10.0

    def test_smaller_margin_pulls_the_camera_in(self):
        near = _framed_instance(margin=0.8)
        far = _framed_instance(margin=1.5)
        T.TilesViewContext._frame_camera(near)
        T.TilesViewContext._frame_camera(far)
        assert near._eye0[2] < far._eye0[2]

    def test_eye_falls_back_to_eye0_without_a_platform(self):
        inst = _framed_instance()
        T.TilesViewContext._frame_camera(inst)
        assert T.TilesViewContext._eye(inst) == tuple(float(v) for v in inst._eye0[:3])

    def test_eye_reads_the_platform_position_when_present(self):
        inst = _framed_instance()
        inst.platform = types.SimpleNamespace(position=np.array([1.0, 2.0, 3.0, 1.0]))
        assert T.TilesViewContext._eye(inst) == (1.0, 2.0, 3.0)

    def test_platform_frustum_and_pose_are_set_when_a_platform_exists(self):
        inst = _framed_instance(radius=20.0)
        rec = {}

        class _Platform:
            def setFrustum(self, *a):
                rec['frustum'] = a

            def setPosition(self, p):
                rec['position'] = p

            def setOrientation(self, o):
                rec['orientation'] = o
        inst.platform = _Platform()
        T.TilesViewContext._frame_camera(inst)
        assert rec['position'] == tuple(float(v) for v in inst._eye0)
        assert rec['orientation'] == (1, 0, 0, 0.10)
        assert rec['frustum'][0] > 0                       # a positive field of view


class TestViewProjectionAndStream:
    def test_view_projection_is_a_4x4_matrix(self):
        inst = _framed_instance()
        inst.platform = types.SimpleNamespace(quaternion=quaternion.fromXYZR(0, 1, 0, 0.0))
        inst.getViewPort = lambda: (800, 600)
        m = T.TilesViewContext._view_projection(inst, (0.0, 2.0, 25.0))
        assert np.asarray(m).shape == (4, 4)

    def test_view_projection_without_platform_aims_at_the_centre(self):
        # No platform: forward is centre - eye (here the -z axis toward origin).
        inst = _framed_instance(center=(0.0, 0.0, 0.0))
        inst.getViewPort = lambda: (800, 600)
        m = T.TilesViewContext._view_projection(inst, (0.0, 0.0, 25.0))
        assert np.asarray(m).shape == (4, 4)

    def test_view_projection_without_platform_degenerate_eye_at_centre(self):
        # Eye exactly at the centre: forward collapses to the -z fallback.
        inst = _framed_instance(center=(1.0, 2.0, 3.0))
        inst.getViewPort = lambda: (800, 600)
        m = T.TilesViewContext._view_projection(inst, (1.0, 2.0, 3.0))
        assert np.asarray(m).shape == (4, 4)

    def test_stream_forwards_the_viewport_height_to_the_terrain(self):
        inst = _framed_instance()
        inst.platform = types.SimpleNamespace(quaternion=quaternion.fromXYZR(0, 1, 0, 0.0))
        inst.getViewPort = lambda: (800, 600)
        seen = {}

        def update(eye, height, view_projection=None):
            seen['eye'] = eye
            seen['height'] = height
            seen['vp'] = view_projection
        inst.terrain = types.SimpleNamespace(update_for_camera=update)
        T.TilesViewContext._stream(inst, (0.0, 2.0, 25.0))
        assert seen['height'] == 600
        assert np.asarray(seen['vp']).shape == (4, 4)


class TestMain:
    def test_missing_local_tileset_errors(self):
        with pytest.raises(SystemExit):
            T.main(['/no/such/tileset.json'])

    def test_capture_sets_auto_exit_env_and_runs_loop(self, tmp_path, monkeypatch):
        ts = tmp_path / 'tileset.json'
        ts.write_text('{}')
        shot = tmp_path / 'sub' / 'frame.png'
        for k in ('OPENGLCONTEXT_AUTO_EXIT_FRAMES', 'OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR',
                  'OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME', 'OPENGLCONTEXT_DISABLE_FPS_DISPLAY'):
            monkeypatch.delenv(k, raising=False)
        ran = {}
        monkeypatch.setattr(T.TilesViewContext, 'ContextMainLoop',
                            classmethod(lambda cls: ran.setdefault('loop', True)))
        T.main([str(ts), '--capture', str(shot), '--frames', '7'])
        assert ran.get('loop') is True
        assert T.TilesViewContext.config.source == str(ts)
        assert os.environ['OPENGLCONTEXT_AUTO_EXIT_FRAMES'] == '7'
        assert os.environ['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME'] == 'frame'
        assert os.environ['OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR'] == os.path.dirname(
            os.path.abspath(str(shot)))
        assert os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] == '1'

    def test_url_source_skips_the_local_existence_check(self, monkeypatch):
        ran = {}
        monkeypatch.setattr(T.TilesViewContext, 'ContextMainLoop',
                            classmethod(lambda cls: ran.setdefault('loop', True)))
        T.main(['https://example.com/tileset.json'])
        assert ran.get('loop') is True
        assert T.TilesViewContext.config.source == 'https://example.com/tileset.json'


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
