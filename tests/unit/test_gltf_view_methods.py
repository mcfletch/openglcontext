"""Non-GL logic of the oglc-gltf viewer that the render/capture subprocess tests
don't reach: light counting, camera/animation resolution, overlay text, background
and light-rig construction, scenegraph assembly and the main() dispatch. The live
render loop, physics walk and GL overlays need a window and are covered elsewhere."""
import argparse
import os
import types

import pytest

# Restore any renderer env vars the module-level setdefault() calls add, so they
# don't leak into unrelated GL subprocess tests.
_ENV_KEYS = ('OPENGLCONTEXT_PROFILE', 'OPENGLCONTEXT_BACKEND', 'OPENGLCONTEXT_RENDERER',
             'OPENGLCONTEXT_SHADOWS', 'OPENGLCONTEXT_IBL_INTENSITY')
_SNAP = {k: os.environ.get(k) for k in _ENV_KEYS}
from OpenGLContext.bin import gltf_view as V  # noqa: E402
from OpenGLContext.scenegraph.light import DirectionalLight  # noqa: E402
from OpenGLContext.scenegraph.background import Background  # noqa: E402
from OpenGLContext.scenegraph.group import Group  # noqa: E402
from OpenGLContext.scenegraph.viewpoint import Viewpoint  # noqa: E402
for _k, _v in _SNAP.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v


def _inst():
    return V.TestContext.__new__(V.TestContext)


def _config(**kw):
    base = dict(source='m.glb', background='none', no_cameras=False, yaw=-0.62,
                lights='off', animation=None, animate=True, anim_time=None,
                turntable=False, capture=None, physics=False, camera=None,
                eye=None, look_at=None, margin=None, elevation=None, tilt=None)
    base.update(kw)
    return argparse.Namespace(**base)


class _Platform:
    def setFrustum(self, *a):
        self.frustum = a

    def setPosition(self, p):
        self.position = p

    def setOrientation(self, o):
        self.orientation = o


class TestCountLights:
    def test_counts_lights_across_the_child_tree_without_recursing_forever(self):
        leaf = DirectionalLight()
        mid = types.SimpleNamespace(children=[leaf, DirectionalLight()])
        root = types.SimpleNamespace(children=[mid])
        root.children.append(root)                        # a cycle must not hang
        assert V._count_lights(root) == 2

    def test_a_scene_with_no_lights_counts_zero(self):
        root = types.SimpleNamespace(children=[types.SimpleNamespace(children=[])])
        assert V._count_lights(root) == 0


class TestResolveCamera:
    def _inst(self):
        inst = _inst()
        inst._camera_names = ['front', 'side']
        inst.viewpoints = ['vp0', 'vp1']
        return inst

    def test_exact_name(self):
        assert V.TestContext._resolve_camera(self._inst(), 'front') == 0

    def test_case_insensitive_name(self):
        assert V.TestContext._resolve_camera(self._inst(), 'SIDE') == 1

    def test_numeric_index(self):
        assert V.TestContext._resolve_camera(self._inst(), '1') == 1

    def test_unknown_returns_none(self):
        assert V.TestContext._resolve_camera(self._inst(), 'nope') is None


class TestResolveAnimation:
    def _inst(self):
        inst = _inst()
        inst._animations = ['a', 'b']
        inst._anim_names = ['walk', 'run']
        return inst

    def test_by_name(self):
        assert V.TestContext._resolve_animation(self._inst(), 'run') == 1

    def test_by_index(self):
        assert V.TestContext._resolve_animation(self._inst(), '0') == 0

    def test_default_is_first(self):
        assert V.TestContext._resolve_animation(self._inst(), None) == 0

    def test_unknown_falls_back_to_first(self, capsys):
        assert V.TestContext._resolve_animation(self._inst(), 'zzz') == 0
        assert 'No animation matching' in capsys.readouterr().err

    def test_no_animations_is_zero(self):
        inst = _inst()
        inst._animations = []
        inst._anim_names = []
        assert V.TestContext._resolve_animation(inst, 'run') == 0


class TestOverlayText:
    def test_pinned_or_prefers_the_configured_time(self):
        inst = _inst()
        inst.config = _config(anim_time=2.5)
        assert V.TestContext._pinned_or(inst, 0.0) == 2.5
        inst.config = _config(anim_time=None)
        assert V.TestContext._pinned_or(inst, 0.4) == 0.4

    def test_loading_label_uses_the_source_basename(self):
        inst = _inst()
        inst.source = '/models/Duck.glb'
        assert V.TestContext._loading_label(inst) == 'Loading Duck.glb ...'

    def test_anim_line_is_empty_without_animations(self):
        inst = _inst()
        inst._animations = []
        assert V.TestContext._anim_line(inst) == ''

    def test_anim_line_names_current_animation_and_state(self):
        inst = _inst()
        inst._animations = ['a', 'b']
        inst._anim_names = ['walk', 'run']
        inst._anim_index = 1
        inst._anim_playing = False
        line = V.TestContext._anim_line(inst)
        assert 'run' in line and 'paused' in line and '[ ]: switch' in line

    def test_mode_line_reflects_walk_vs_freefly(self):
        inst = _inst()
        inst._physics_on = True
        assert 'walk' in V.TestContext._mode_line(inst)
        inst._physics_on = False
        assert 'free-fly' in V.TestContext._mode_line(inst)

    def test_update_overlay_composes_source_camera_and_mode(self):
        inst = _inst()
        inst.source = 'Duck.glb'
        inst.viewpoints = ['vp0', 'vp1']
        inst._camera_names = ['front', 'side']
        inst.cam_index = 0
        inst._animations = []
        inst._anim_names = []
        inst._anim_index = 0
        inst._anim_playing = True
        inst._physics_on = False
        V.TestContext._update_overlay(inst)
        assert 'Duck.glb' in inst.overlay_text
        assert '[1/2] front' in inst.overlay_text
        assert 'free-fly' in inst.overlay_text


class TestYawFromViewpoint:
    def test_identity_orientation_faces_negative_z(self):
        vp = types.SimpleNamespace(orientation=(0.0, 1.0, 0.0, 0.0))
        yaw = V.TestContext._yaw_from_viewpoint(vp)
        assert abs(yaw) < 1e-6

    def test_now_is_a_float(self):
        assert isinstance(V.TestContext._now(), float)


class TestBackgroundAndLights:
    def test_sky_background_has_multiple_sky_colours(self):
        bg = V.TestContext._sky()
        assert isinstance(bg, Background)
        assert len(bg.skyColor) >= 3

    def test_default_light_rig_is_a_sun_plus_fill(self):
        inst = _inst()
        lights = V.TestContext._default_lights(inst, 10.0)
        assert len(lights) == 2

    def test_make_background_none_returns_no_node(self):
        inst = _inst()
        inst.config = _config(background='none')
        assert V.TestContext._make_background(inst) is None

    def test_make_background_sky_returns_a_gradient(self):
        inst = _inst()
        inst.config = _config(background='sky')
        assert isinstance(V.TestContext._make_background(inst), Background)

    def test_make_background_rgb_triple(self):
        inst = _inst()
        inst.config = _config(background='0.1,0.2,0.3')
        bg = V.TestContext._make_background(inst)
        assert isinstance(bg, Background)
        assert list(bg.skyColor[0]) == pytest.approx([0.1, 0.2, 0.3])

    def test_make_background_bad_spec_falls_back_to_sky(self, capsys):
        inst = _inst()
        inst.config = _config(background='1,2')          # not three components
        assert isinstance(V.TestContext._make_background(inst), Background)
        assert 'bad --background' in capsys.readouterr().err

    def test_make_background_cube_without_env_falls_back_to_sky(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        inst = _inst()
        inst.config = _config(background='cube')
        assert isinstance(V.TestContext._make_background(inst), Background)

    def test_env_hdr_background_is_none_without_the_env_var(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        assert V.TestContext._env_hdr_background() is None

    def test_env_cube_background_is_none_without_a_prefix(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        assert V.TestContext._env_cube_background() is None


class TestLightsChildren:
    def _scene(self, lights=0):
        kids = [DirectionalLight() for _ in range(lights)]
        return types.SimpleNamespace(group=types.SimpleNamespace(children=kids))

    def test_off_adds_no_lights(self):
        inst = _inst()
        inst.config = _config(lights='off')
        assert V.TestContext._lights_children(inst, self._scene(), 10.0) == []

    def test_auto_keeps_the_files_own_lights(self):
        inst = _inst()
        inst.config = _config(lights='auto')
        assert V.TestContext._lights_children(inst, self._scene(lights=2), 10.0) == []

    def test_auto_adds_a_rig_when_the_file_is_dark(self):
        inst = _inst()
        inst.config = _config(lights='auto')
        assert len(V.TestContext._lights_children(inst, self._scene(0), 10.0)) == 2

    def test_on_always_adds_a_rig(self):
        inst = _inst()
        inst.config = _config(lights='on')
        assert len(V.TestContext._lights_children(inst, self._scene(lights=5), 10.0)) == 2


def _fake_scene(viewpoints=(), cameras=()):
    return types.SimpleNamespace(
        radius=2.0, exposure=1.0, cameras=list(cameras), viewpoints=list(viewpoints),
        center=(0.0, 0.0, 0.0), group=Group(), animations=[])


class TestBuildScenegraph:
    def _prep(self, inst, **cfg):
        inst.config = _config(**cfg)
        inst.platform = _Platform()
        inst.source = 'Duck.glb'
        inst._physics_on = False
        inst.cam_index = 0
        inst.viewpoints = []

    def test_no_cameras_centres_and_frames_the_model(self):
        inst = _inst()
        self._prep(inst, no_cameras=True)
        inst._build_scenegraph(_fake_scene())
        assert inst.model_xform is not None
        assert inst.viewpoints == []
        assert inst.platform.position is not None          # _frame placed the camera

    def test_embedded_cameras_become_viewpoints(self, capsys):
        inst = _inst()
        self._prep(inst, no_cameras=False)
        vp = Viewpoint()
        scene = _fake_scene(viewpoints=[vp], cameras=[{'name': 'front'}])
        inst._build_scenegraph(scene)
        assert inst.viewpoints == [vp]
        assert 'camera(s)' in capsys.readouterr().out

    def test_sky_background_node_is_added_to_the_scenegraph(self):
        inst = _inst()
        self._prep(inst, no_cameras=True, background='sky')
        inst._build_scenegraph(_fake_scene())
        assert inst.gltf_exposure == 1.0                   # not metered against a sky
        assert inst.sg is not None

    def test_black_background_self_lit_scene_meters_exposure(self):
        inst = _inst()
        self._prep(inst, no_cameras=True, background='none')
        scene = _fake_scene()
        scene.exposure = 0.5
        inst._build_scenegraph(scene)
        assert inst.gltf_exposure == 0.5                   # metered on a black backdrop


class TestSetupAnimation:
    def test_no_animations_leaves_no_player(self):
        inst = _inst()
        inst.config = _config()
        inst._setup_animation(_fake_scene())
        assert inst._player is None and inst._animations == []


class TestSceneReadyAndFailure:
    def test_capture_run_skips_physics_setup(self):
        inst = _inst()
        inst.config = _config(capture='shot.png')
        inst._scene_loaded = False
        inst._on_scene_ready()                              # returns before physics
        assert inst._scene_loaded is True

    def test_interactive_no_physics_marks_scene_loaded(self):
        inst = _inst()
        inst.config = _config(capture=None, physics=False)
        inst._scene_loaded = False
        inst._on_scene_ready()
        assert inst._scene_loaded is True

    def test_apply_failed_sets_an_error_overlay(self, capsys):
        inst = _inst()
        inst.sg = None
        inst._apply_failed(RuntimeError('boom\nsecond line'))
        assert inst.overlay_error is True
        assert inst.overlay_text.startswith('FAILED: boom')
        assert 'Load failed' in capsys.readouterr().err


class TestFrameEyeLookAt:
    def test_frame_routes_to_the_eye_lookat_path_when_both_are_set(self):
        inst = _inst()
        inst.config = _config(eye=(5.0, 1.0, 0.0), look_at=(0.0, 0.0, 0.0))
        inst.platform = _Platform()
        inst._frame(10.0)
        assert tuple(round(v, 3) for v in inst.platform.position) == (5.0, 1.0, 0.0)


class TestMainDispatch:
    def test_list_cameras_prints_names_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, '_load_source', lambda src: types.SimpleNamespace(
            cameras=[{'name': 'front'}, {}]))
        rc = V.main([str(model), '--list-cameras'])
        assert rc == 0
        out = capsys.readouterr().out
        assert '0: front' in out and '1: camera' in out

    def test_missing_source_errors(self, monkeypatch):
        monkeypatch.delenv('GLTF', raising=False)
        with pytest.raises(SystemExit):
            V.main([])

    def test_normal_run_configures_and_enters_the_loop(self, tmp_path, monkeypatch):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, 'apply_render_env', lambda args: None)   # no env leak
        ran = {}
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: ran.setdefault('size', size)))
        V.main([str(model)])
        assert V.TestContext.config.source == str(model)
        assert 'size' in ran

    def test_size_flag_reaches_the_loop(self, tmp_path, monkeypatch):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, 'apply_render_env', lambda args: None)
        seen = {}
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: seen.setdefault('size', size)))
        V.main([str(model), '--size', '640x480'])
        assert seen['size'] == (640, 480)


class TestPrepareAndLoadSource:
    def test_prepare_source_resolves_from_config(self, tmp_path):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        inst = _inst()
        inst._gltf_source = None
        inst.config = _config(source=str(model))
        inst._prepare_source()
        assert inst.source == str(model)

    def test_prepare_source_without_a_source_exits(self, monkeypatch):
        monkeypatch.delenv('GLTF', raising=False)
        inst = _inst()
        inst._gltf_source = None
        inst.config = _config(source=None)
        with pytest.raises(SystemExit):
            inst._prepare_source()

    def test_load_scene_delegates_to_load_source(self, monkeypatch):
        inst = _inst()
        inst.source = '/models/Duck.glb'
        monkeypatch.setattr(V, '_load_source', lambda src: 'SCENE:%s' % src)
        assert inst._load_scene() == 'SCENE:/models/Duck.glb'


class TestAsyncLoading:
    def _inst(self):
        import threading
        inst = _inst()
        inst._load_lock = threading.Lock()
        inst._load_token = 0
        inst._loading = False
        inst._pending = None
        inst.overlay_text = ''
        inst.overlay_error = False
        inst.triggerRedraw = lambda n: None
        return inst

    def test_request_scene_runs_the_producer_off_thread(self):
        import time
        inst = self._inst()
        inst._request_scene(lambda: 'LOADED', 'Loading ...')
        for _ in range(200):
            if inst._pending is not None:
                break
            time.sleep(0.01)
        assert inst._pending == ('LOADED', None)

    def test_poll_applies_a_failed_load_as_an_error_overlay(self, capsys):
        inst = self._inst()
        inst.sg = None
        inst._pending = (None, RuntimeError('bad'))
        assert inst._poll_pending_scene() is True
        assert inst.overlay_error is True
        capsys.readouterr()

    def test_poll_with_nothing_pending_returns_false(self):
        inst = self._inst()
        inst._pending = None
        assert inst._poll_pending_scene() is False


class TestScreenshotQueue:
    def test_request_screenshot_sets_the_pending_flag(self):
        inst = _inst()
        inst._screenshot_pending = False
        inst.triggerRedraw = lambda n: None
        inst._request_screenshot()
        assert inst._screenshot_pending is True


class _Player:
    def __init__(self, duration=2.0):
        self.duration = duration
        self.evaluated = []
        self.node_transforms = {}
        self.node_morph = {}

    def evaluate(self, t):
        self.evaluated.append(t)


class TestAnimationControl:
    def test_setup_animation_binds_a_player_and_shows_the_first_pose(self, capsys):
        inst = _inst()
        inst.config = _config(animate=True, anim_time=None)
        player = _Player()
        scene = types.SimpleNamespace(
            animations=[types.SimpleNamespace(name='clip')],
            player=lambda idx, loop: player)
        inst._setup_animation(scene)
        assert inst._player is player
        assert player.evaluated == [0.0]                 # first frame shown at once

    def test_advance_animation_ticks_the_clock(self):
        inst = _inst()
        inst.config = _config(anim_time=None)
        inst._player = _Player()
        inst._anim_playing = True
        inst._anim_last = None
        inst._anim_clock = 0.0
        assert inst._advance_animation() is True
        assert inst._player.evaluated                    # evaluated at the current clock

    def test_advance_animation_with_a_pinned_time_is_static(self):
        inst = _inst()
        inst.config = _config(anim_time=1.5)
        inst._player = _Player()
        assert inst._advance_animation() is False
        assert inst._player.evaluated == [1.5]

    def test_toggle_animation_flips_play_state(self):
        inst = _inst()
        inst._anim_playing = True
        inst._animations = []
        inst._anim_names = []
        inst._anim_index = 0
        inst.source = 'm.glb'
        inst.viewpoints = []
        inst._camera_names = []
        inst.cam_index = 0
        inst._physics_on = False
        inst.triggerRedraw = lambda n: None
        inst._toggle_animation()
        assert inst._anim_playing is False

    def test_cycle_animation_rebinds_a_player_for_the_new_index(self, monkeypatch):
        from OpenGLContext.loaders.gltf import animation as anim_mod
        monkeypatch.setattr(anim_mod, 'Player',
                            lambda *a, **k: _Player(duration=3.0))
        inst = _inst()
        inst._animations = ['a', 'b']
        inst._anim_names = ['walk', 'run']
        inst._anim_index = 0
        inst._player = _Player()
        inst.source = 'm.glb'
        inst.viewpoints = []
        inst._camera_names = []
        inst.cam_index = 0
        inst._physics_on = False
        inst._anim_playing = True
        inst.triggerRedraw = lambda n: None
        inst._next_animation()
        assert inst._anim_index == 1

    def test_cycle_animation_is_a_noop_without_animations(self):
        inst = _inst()
        inst._animations = []
        inst._prev_animation()                           # must not raise


class TestTurntableToggle:
    def test_toggle_turntable_snaps_back_when_stopped(self):
        inst = _inst()
        inst.config = _config(turntable=True)            # currently spinning
        inst.model_xform = types.SimpleNamespace(rotation=(0, 1, 0, 1.0))
        inst._default_model_rotation = (0, 1, 0, 0.0)
        inst.triggerRedraw = lambda n: None
        inst._toggle_turntable()
        assert inst.config.turntable is False
        assert inst.model_xform.rotation == (0, 1, 0, 0.0)


class TestCameraSelection:
    def _inst(self):
        inst = _inst()
        inst.viewpoints = [Viewpoint(), Viewpoint()]
        inst._camera_names = ['front', 'side']
        inst.cam_index = 0
        inst.config = _config(camera='side')
        return inst

    def test_select_initial_camera_binds_the_named_viewpoint(self):
        inst = self._inst()
        inst._select_initial_camera()
        assert inst.cam_index == 1 and inst.viewpoints[1].isBound is True

    def test_select_initial_camera_warns_on_an_unknown_name(self, capsys):
        inst = self._inst()
        inst.config = _config(camera='missing')
        inst._select_initial_camera()
        assert 'No camera matching' in capsys.readouterr().err

    def test_cycle_viewpoint_advances_and_binds(self):
        inst = self._inst()
        inst._physics = None
        inst._physics_on = False
        inst.source = 'm.glb'
        inst._animations = []
        inst._anim_names = []
        inst._anim_index = 0
        inst._anim_playing = True
        inst.getSceneGraph = lambda: types.SimpleNamespace(boundViewpoint=None)
        inst.triggerRedraw = lambda n: None
        inst._next_cam()
        assert inst.cam_index == 1


class TestPhysicsInputHandlers:
    """Movement itself belongs to the declared modes; these are what is left.

    A key event only has to wake the frame loop -- the modes read the sampled
    input state, not the events -- and ``f`` has to reach the character
    controller, since flying is a property of it and not of the movement.
    """

    def test_a_movement_key_wakes_the_frame_loop(self):
        inst = _inst()
        drawn = []
        inst.triggerRedraw = lambda value=1: drawn.append(value)
        inst._pkey(types.SimpleNamespace(name='w'))
        assert drawn

    def test_the_fly_key_swaps_the_mode_and_tells_the_character(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.bin import gltf_view
        inst = _inst()
        seen = {}
        inst._physics = types.SimpleNamespace(
            jump=lambda: None, character=types.SimpleNamespace(flying=False),
            set_fly=lambda v: seen.setdefault('fly', v), look=lambda d: None,
            submerged=False, turn=lambda d: None,
            set_move=lambda **k: None, set_fly_move=lambda **k: None)
        inst._physics_on = True
        inst.contextDefinition = ContextDefinition(
            movementModes=gltf_view.movement_modes())
        inst.navigation = None
        inst._pfly(None)
        assert seen['fly'] is True
        assert inst.contextDefinition.movementMode.name == 'fly'
        inst._pfly(None)
        assert seen['fly'] is True                        # first answer kept
        assert inst.contextDefinition.movementMode.name == 'walk'

    def test_the_fly_key_does_nothing_before_physics_exists(self):
        inst = _inst()
        inst._physics = None
        inst.navigation = None
        inst._pfly(None)


class TestFrameDegenerate:
    def test_eye_equal_to_target_leaves_the_platform_untouched(self):
        inst = _inst()
        inst.config = _config(eye=(1.0, 1.0, 1.0), look_at=(1.0, 1.0, 1.0))
        inst.platform = _Platform()
        inst._frame(10.0)
        assert not hasattr(inst.platform, 'position')     # degenerate: never placed


class TestCaptureInstall:
    def test_install_capture_builds_a_settle_capture(self):
        inst = _inst()
        inst.config = _config(capture='shot.png', capture_delay=0.3, frames=5)
        inst._settle = None
        inst._install_capture()
        assert inst._settle is not None

    def test_no_capture_leaves_settle_unset(self):
        inst = _inst()
        inst.config = _config(capture=None)
        inst._settle = None
        inst._install_capture()
        assert inst._settle is None


class TestActiveShaderAndViewport:
    def test_active_shader_is_none_without_a_flat_pass(self):
        assert V.TestContext._active_shader() is None

    def test_viewport_reports_dimensions(self):
        inst = _inst()
        inst.getViewPort = lambda: (800, 600)
        assert V.TestContext._viewport(inst) == (800, 600)

    def test_viewport_is_none_when_empty(self):
        inst = _inst()
        inst.getViewPort = lambda: (0, 0)
        assert V.TestContext._viewport(inst) is None


class TestMainListCamerasEdges:
    def test_list_cameras_reports_when_a_model_has_none(self, tmp_path, monkeypatch, capsys):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, '_load_source',
                            lambda src: types.SimpleNamespace(cameras=[]))
        assert V.main([str(model), '--list-cameras']) == 0
        assert 'no cameras defined' in capsys.readouterr().out

    def test_list_cameras_without_a_source_errors(self, monkeypatch):
        monkeypatch.delenv('GLTF', raising=False)
        with pytest.raises(SystemExit):
            V.main(['--list-cameras'])


class TestAdvanceAnimationEdges:
    def test_no_player_needs_no_redraw(self):
        inst = _inst()
        inst._player = None
        assert inst._advance_animation() is False

    def test_paused_animation_needs_no_redraw(self):
        inst = _inst()
        inst.config = _config(anim_time=None)
        inst._player = _Player()
        inst._anim_playing = False
        assert inst._advance_animation() is False

    def test_a_second_tick_accumulates_wall_time(self):
        inst = _inst()
        inst.config = _config(anim_time=None)
        inst._player = _Player()
        inst._anim_playing = True
        inst._anim_last = V.TestContext._now() - 0.02      # a prior tick 20ms ago
        inst._anim_clock = 0.0
        assert inst._advance_animation() is True
        assert inst._anim_clock > 0.0                      # clock moved forward


class TestTurntableStart:
    def test_toggle_turntable_on_starts_spinning_from_now(self):
        inst = _inst()
        inst.config = _config(turntable=False)
        inst.model_xform = types.SimpleNamespace(rotation=(0, 1, 0, 0.0))
        inst._default_model_rotation = (0, 1, 0, 0.0)
        inst.triggerRedraw = lambda n: None
        inst._toggle_turntable()
        assert inst.config.turntable is True
        assert isinstance(inst._start, float)


class TestRequestAndPollExtras:
    def test_request_initial_scene_kicks_off_the_source_load(self):
        inst = _inst()
        inst.source = 'Duck.glb'
        recorded = {}
        inst._request_scene = lambda produce, label: recorded.update(
            produce=produce, label=label)
        inst._request_initial_scene()
        assert recorded['produce'] == inst._load_scene
        assert 'Duck.glb' in recorded['label']

    def test_request_scene_captures_a_producer_failure(self):
        import threading
        import time
        inst = _inst()
        inst._load_lock = threading.Lock()
        inst._load_token = 0
        inst.overlay_text = ''
        inst.overlay_error = False
        inst.triggerRedraw = lambda n: None

        def boom():
            raise RuntimeError('decode failed')
        inst._request_scene(boom, 'Loading ...')
        for _ in range(200):
            if inst._pending is not None:
                break
            time.sleep(0.01)
        scene, error = inst._pending
        assert scene is None and isinstance(error, RuntimeError)

    def test_poll_applies_a_loaded_scene(self):
        import threading
        inst = _inst()
        inst._load_lock = threading.Lock()
        inst.triggerRedraw = lambda n: None
        applied = {}
        inst._apply_loaded = lambda s: applied.setdefault('scene', s)
        inst._pending = ('SCENE', None)
        assert inst._poll_pending_scene() is True
        assert applied['scene'] == 'SCENE'


class TestCycleViewpointPhysics:
    def test_cycle_teleports_the_walking_avatar_to_the_new_viewpoint(self):
        inst = _inst()
        vp0, vp1 = Viewpoint(), Viewpoint()
        inst.viewpoints = [vp0, vp1]
        inst._camera_names = ['front', 'side']
        inst.cam_index = 0
        vp0.isBound = True
        moved = {}
        inst._physics = types.SimpleNamespace(
            yaw=0.0, pitch=0.0,
            character=types.SimpleNamespace(grounded=True),
            bind_eye=lambda pos: moved.setdefault('eye', pos),
            set_fly=lambda v: moved.setdefault('fly', v))
        inst._physics_on = True
        inst.source = 'm.glb'
        inst._animations = []
        inst._anim_names = []
        inst._anim_index = 0
        inst._anim_playing = True
        inst.getSceneGraph = lambda: types.SimpleNamespace(boundViewpoint=vp0)
        inst.triggerRedraw = lambda n: None
        inst._prev_cam()                                   # wraps 0 -> 1
        assert inst.cam_index == 1
        assert 'eye' in moved                              # avatar teleported


class TestPhysicsSeams:
    def test_yaw_from_platform_reads_the_camera_heading(self):
        from OpenGLContext import quaternion
        inst = _inst()
        inst.platform = types.SimpleNamespace(
            quaternion=quaternion.fromXYZR(0, 1, 0, 0.0))
        assert abs(inst._yaw_from_platform()) < 1e-6       # identity faces -Z

    def test_setup_physics_returns_early_for_a_capture_run(self):
        inst = _inst()
        inst.config = _config(capture='shot.png')
        inst.movementManager = 'freefly-manager'
        inst._scene_loaded = False
        inst.sg = None
        inst._setup_physics()
        assert inst._free_manager == 'freefly-manager'     # captured the navigator, then bailed


class TestBackgroundNoneIblOff:
    _KEYS = ('OPENGLCONTEXT_IBL', 'OPENGLCONTEXT_ENV_CUBEMAP', 'OPENGLCONTEXT_ENV_HDR')

    @pytest.fixture(autouse=True)
    def _isolate(self):
        saved = {k: os.environ.get(k) for k in self._KEYS}
        yield
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_black_backdrop_without_an_env_probe_forces_ibl_off(self, monkeypatch):
        for k in self._KEYS:
            monkeypatch.delenv(k, raising=False)
        args = argparse.Namespace(shadows=None, ibl_intensity=None, environment=None,
                                  background='none', capture=None)
        V.apply_render_env(args)
        assert os.environ['OPENGLCONTEXT_IBL'] == 'off'


class TestMakeBackgroundHdr:
    def test_cube_background_uses_the_hdr_skybox_when_configured(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/env/studio.hdr')
        inst = _inst()
        inst.config = _config(background='cube')
        bg = V.TestContext._make_background(inst)
        assert bg is not None and not isinstance(bg, type(None))

    def test_env_hdr_background_builds_a_node_from_the_env_var(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/env/studio.hdr')
        assert V.TestContext._env_hdr_background() is not None


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
