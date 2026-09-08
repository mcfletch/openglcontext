"""Non-GL logic of the oglc-gltf viewer that the render/capture subprocess tests
don't reach: light counting, camera/animation resolution, overlay text, background
and light-rig construction, scenegraph assembly and the main() dispatch. The live
render loop, physics walk and GL overlays need a window and are covered elsewhere."""
import argparse
import os
import types

import pytest

from OpenGLContext.testing.gl_env import import_unconfigured

# The viewer settles the renderer as it is imported, being a program; these
# tests read its logic, so the settling is put back.
V = import_unconfigured('OpenGLContext.bin.view')

from OpenGLContext.viewer import environment  # noqa: E402
from OpenGLContext.viewer.options import ViewerOptions  # noqa: E402
from OpenGLContext.scenegraph.light import DirectionalLight  # noqa: E402
from OpenGLContext.scenegraph.background import Background  # noqa: E402
from OpenGLContext.scenegraph.group import Group  # noqa: E402
from OpenGLContext.scenegraph.viewpoint import Viewpoint  # noqa: E402


def _inst():
    return V.TestContext.__new__(V.TestContext)


def _config(**kw):
    """The viewer's own options type, so these cannot drift out of step with it."""
    base = dict(source='m.glb', background='none', lights='off')
    base.update(kw)
    return ViewerOptions(**base)


class _StubAdapter:
    """An adapter that opens nothing and reports the cameras it was told to."""

    def __init__(self, cameras):
        self.cameras = cameras

    def load(self, source):
        return types.SimpleNamespace(cameras=self.cameras)


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
        assert environment.count_lights(root) == 2

    def test_a_scene_with_no_lights_counts_zero(self):
        root = types.SimpleNamespace(children=[types.SimpleNamespace(children=[])])
        assert environment.count_lights(root) == 0


class TestResolveCamera:
    def _inst(self):
        inst = _inst()
        inst._cameraNames = ['front', 'side']
        inst.viewpoints = ['vp0', 'vp1']
        return inst

    def test_exact_name(self):
        assert V.TestContext.resolveCamera(self._inst(), 'front') == 0

    def test_case_insensitive_name(self):
        assert V.TestContext.resolveCamera(self._inst(), 'SIDE') == 1

    def test_numeric_index(self):
        assert V.TestContext.resolveCamera(self._inst(), '1') == 1

    def test_unknown_returns_none(self):
        assert V.TestContext.resolveCamera(self._inst(), 'nope') is None


class TestResolveAnimation:
    def _inst(self):
        inst = _inst()
        inst._animations = ['a', 'b']
        inst._animationNames = ['walk', 'run']
        return inst

    def test_by_name(self):
        assert V.TestContext.resolveAnimation(self._inst(), 'run') == 1

    def test_by_index(self):
        assert V.TestContext.resolveAnimation(self._inst(), '0') == 0

    def test_default_is_first(self):
        assert V.TestContext.resolveAnimation(self._inst(), None) == 0

    def test_unknown_falls_back_to_first(self, capsys):
        assert V.TestContext.resolveAnimation(self._inst(), 'zzz') == 0
        assert 'No animation matching' in capsys.readouterr().err

    def test_no_animations_is_zero(self):
        inst = _inst()
        inst._animations = []
        inst._animationNames = []
        assert V.TestContext.resolveAnimation(inst, 'run') == 0


class TestOverlayText:
    def test_pinned_or_prefers_the_configured_time(self):
        inst = _inst()
        inst.options = _config(anim_time=2.5)
        assert V.TestContext.pinnedOr(inst, 0.0) == 2.5
        inst.options = _config(anim_time=None)
        assert V.TestContext.pinnedOr(inst, 0.4) == 0.4

    def test_loading_label_uses_the_source_basename(self):
        inst = _inst()
        inst.source = '/models/Duck.glb'
        assert V.TestContext.loadingLabel(inst) == 'Loading Duck.glb ...'

    def test_anim_line_is_empty_without_animations(self):
        inst = _inst()
        inst._animations = []
        assert V.TestContext._animationLine(inst) == ''

    def test_anim_line_names_current_animation_and_state(self):
        inst = _inst()
        inst._animations = ['a', 'b']
        inst._animationNames = ['walk', 'run']
        inst._animationIndex = 1
        inst._animationPlaying = False
        line = V.TestContext._animationLine(inst)
        assert 'run' in line and 'paused' in line and '[ ]: switch' in line

    def test_mode_line_reflects_walk_vs_freefly(self):
        inst = _inst()
        inst.physicsWalking = True
        assert 'walk' in V.TestContext._modeLine(inst)
        inst.physicsWalking = False
        assert 'free-fly' in V.TestContext._modeLine(inst)

    def test_update_overlay_composes_source_camera_and_mode(self):
        inst = _inst()
        inst.source = 'Duck.glb'
        inst.viewpoints = ['vp0', 'vp1']
        inst._cameraNames = ['front', 'side']
        inst.cameraIndex = 0
        inst._animations = []
        inst._animationNames = []
        inst._animationIndex = 0
        inst._animationPlaying = True
        inst.physicsWalking = False
        V.TestContext.updateOverlay(inst)
        assert 'Duck.glb' in inst.overlayText
        assert '[1/2] front' in inst.overlayText
        assert 'free-fly' in inst.overlayText


class TestViewerClock:
    def test_now_is_a_float(self):
        assert isinstance(V.TestContext._now(), float)


class TestBackgroundAndLights:
    def test_sky_background_has_multiple_sky_colours(self):
        bg = environment.sky_background()
        assert isinstance(bg, Background)
        assert len(bg.skyColor) >= 3

    def test_default_light_rig_is_a_sun_plus_fill(self):
        lights = V.TestContext.defaultLights(10.0)
        assert len(lights) == 2

    def test_make_background_none_returns_no_node(self):
        inst = _inst()
        inst.options = _config(background='none')
        assert environment.background_for(inst.options.background) is None

    def test_make_background_sky_returns_a_gradient(self):
        inst = _inst()
        inst.options = _config(background='sky')
        assert isinstance(environment.background_for(inst.options.background), Background)

    def test_make_background_rgb_triple(self):
        inst = _inst()
        inst.options = _config(background='0.1,0.2,0.3')
        bg = environment.background_for(inst.options.background)
        assert isinstance(bg, Background)
        assert list(bg.skyColor[0]) == pytest.approx([0.1, 0.2, 0.3])

    def test_make_background_bad_spec_falls_back_to_sky(self):
        said = []
        background = environment.background_for('1,2', said.append)   # not three
        assert isinstance(background, Background)
        assert said and 'bad background' in said[0]

    def test_make_background_cube_without_env_falls_back_to_sky(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        inst = _inst()
        inst.options = _config(background='cube')
        assert isinstance(environment.background_for(inst.options.background), Background)

    def test_env_hdr_background_is_none_without_the_env_var(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
        assert environment.hdr_background() is None

    def test_env_cube_background_is_none_without_a_prefix(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        assert environment.cube_background() is None


class TestLightsChildren:
    def _scene(self, lights=0):
        kids = [DirectionalLight() for _ in range(lights)]
        return types.SimpleNamespace(group=types.SimpleNamespace(children=kids))

    def test_off_adds_no_lights(self):
        inst = _inst()
        inst.options = _config(lights='off')
        assert V.TestContext.lightsFor(inst, self._scene()) == []

    def test_auto_keeps_the_files_own_lights(self):
        inst = _inst()
        inst.options = _config(lights='auto')
        assert V.TestContext.lightsFor(inst, self._scene(lights=2)) == []

    def test_auto_adds_a_rig_when_the_file_is_dark(self):
        inst = _inst()
        inst.options = _config(lights='auto')
        assert len(V.TestContext.lightsFor(inst, self._scene(0))) == 2

    def test_on_always_adds_a_rig(self):
        inst = _inst()
        inst.options = _config(lights='on')
        assert len(V.TestContext.lightsFor(inst, self._scene(lights=5))) == 2


def _fake_scene(viewpoints=(), cameras=()):
    return types.SimpleNamespace(
        radius=2.0, exposure=1.0, cameras=list(cameras), viewpoints=list(viewpoints),
        center=(0.0, 0.0, 0.0), group=Group(), animations=[])


class TestBuildScenegraph:
    def _prep(self, inst, **cfg):
        inst.options = _config(**cfg)
        inst.platform = _Platform()
        inst.source = 'Duck.glb'
        inst.physicsWalking = False
        inst.cameraIndex = 0
        inst.viewpoints = []

    def test_no_cameras_centres_and_frames_the_model(self):
        inst = _inst()
        self._prep(inst, no_cameras=True)
        inst.buildScenegraph(_fake_scene())
        assert inst.modelTransform is not None
        assert inst.viewpoints == []
        assert inst.platform.position is not None          # frameModel placed the camera

    def test_embedded_cameras_become_viewpoints(self, capsys):
        inst = _inst()
        self._prep(inst, no_cameras=False)
        vp = Viewpoint()
        scene = _fake_scene(viewpoints=[vp], cameras=[{'name': 'front'}])
        inst.buildScenegraph(scene)
        assert inst.viewpoints == [vp]
        assert 'camera(s)' in capsys.readouterr().out

    def test_sky_background_node_is_added_to_the_scenegraph(self):
        inst = _inst()
        self._prep(inst, no_cameras=True, background='sky')
        inst.buildScenegraph(_fake_scene())
        assert inst.gltf_exposure == 1.0                   # not metered against a sky
        assert inst.sg is not None

    def test_black_background_self_lit_scene_meters_exposure(self):
        inst = _inst()
        self._prep(inst, no_cameras=True, background='none')
        scene = _fake_scene()
        scene.exposure = 0.5
        inst.buildScenegraph(scene)
        assert inst.gltf_exposure == 0.5                   # metered on a black backdrop


class TestSetupAnimation:
    def test_no_animations_leaves_no_player(self):
        inst = _inst()
        inst.options = _config()
        inst.setupAnimation(_fake_scene())
        assert inst._player is None and inst._animations == []


class TestSceneReadyAndFailure:
    def test_capture_run_skips_physics_setup(self):
        inst = _inst()
        inst.options = _config(capture='shot.png')
        inst.sceneLoaded = False
        inst.onSceneReady()                              # returns before physics
        assert inst.sceneLoaded is True

    def test_interactive_no_physics_marks_scene_loaded(self):
        inst = _inst()
        inst.options = _config(capture=None, physics=False)
        inst.sceneLoaded = False
        inst.onSceneReady()
        assert inst.sceneLoaded is True

    def test_apply_failed_sets_an_error_overlay(self, capsys):
        inst = _inst()
        inst.sg = None
        inst.applyFailedLoad(RuntimeError('boom\nsecond line'))
        assert inst.overlayError is True
        assert inst.overlayText.startswith('FAILED: boom')
        assert 'Load failed' in capsys.readouterr().err


class TestFrameEyeLookAt:
    def test_frame_routes_to_the_eye_lookat_path_when_both_are_set(self):
        inst = _inst()
        inst.options = _config(eye=(5.0, 1.0, 0.0), look_at=(0.0, 0.0, 0.0))
        inst.platform = _Platform()
        inst.frameModel(10.0)
        assert tuple(round(v, 3) for v in inst.platform.position) == (5.0, 1.0, 0.0)


class TestMainDispatch:
    def test_list_cameras_prints_names_and_exits_zero(self, tmp_path, monkeypatch, capsys):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, 'adapter_for', lambda src: _StubAdapter(
            [{'name': 'front'}, {}]))
        rc = V.main([str(model), '--list-cameras'])
        assert rc == 0
        out = capsys.readouterr().out
        assert '0: front' in out and '1: camera' in out

    def test_missing_source_opens_the_shelf(self, monkeypatch):
        """``oglc-view`` on its own is a program, not a usage message."""
        monkeypatch.delenv('GLTF', raising=False)
        monkeypatch.setattr(V, 'apply_render_env', lambda args: None)
        ran = []
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: ran.append(True)))
        V.main([])
        assert ran == [True]

    def test_normal_run_configures_and_enters_the_loop(self, tmp_path, monkeypatch):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, 'apply_render_env', lambda args: None)   # no env leak
        ran = {}
        monkeypatch.setattr(V.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: ran.setdefault('size', size)))
        V.main([str(model)])
        assert V.TestContext.options.source == str(model)
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
        inst.options = _config(source=str(model))
        inst.prepareSource()
        assert inst.source == str(model)

    def test_prepare_source_without_a_source_opens_the_shelf(self, monkeypatch):
        """``oglc-view`` on its own is a program, not a usage message."""
        monkeypatch.delenv('GLTF', raising=False)
        inst = _inst()
        inst._gltf_source = None
        inst.options = _config(source=None)
        inst.prepareSource()
        assert inst.source is None

    def test_prepare_source_exits_for_a_source_that_is_not_there(self, monkeypatch):
        monkeypatch.delenv('GLTF', raising=False)
        inst = _inst()
        inst.options = _config(source='/no/such/model.glb')
        with pytest.raises(SystemExit):
            inst.prepareSource()

    def test_load_scene_delegates_to_the_adapter(self, monkeypatch):
        from OpenGLContext.viewer.adapters import gltf
        inst = _inst()
        inst.source = '/models/Duck.glb'
        inst.adapter = gltf.GLTFAdapter()
        monkeypatch.setattr(gltf, 'load_gltf_source', lambda src: 'SCENE:%s' % src)
        assert inst.loadScene() == 'SCENE:/models/Duck.glb'


class TestAsyncLoading:
    def _inst(self):
        import threading
        inst = _inst()
        inst._loadLock = threading.Lock()
        inst._loadToken = 0
        inst._loading = False
        inst._pendingScene = None
        inst.overlayText = ''
        inst.overlayError = False
        inst.triggerRedraw = lambda n: None
        return inst

    def test_request_scene_runs_the_producer_off_thread(self):
        import time
        inst = self._inst()
        inst.requestScene(lambda: 'LOADED', 'Loading ...')
        for _ in range(200):
            if inst._pendingScene is not None:
                break
            time.sleep(0.01)
        assert inst._pendingScene == ('LOADED', None)

    def test_poll_applies_a_failed_load_as_an_error_overlay(self, capsys):
        inst = self._inst()
        inst.sg = None
        inst._pendingScene = (None, RuntimeError('bad'))
        assert inst.pollPendingScene() is True
        assert inst.overlayError is True
        capsys.readouterr()

    def test_poll_with_nothing_pending_returns_false(self):
        inst = self._inst()
        inst._pendingScene = None
        assert inst.pollPendingScene() is False


class TestScreenshotQueue:
    def test_request_screenshot_sets_the_pending_flag(self):
        inst = _inst()
        inst._screenshotPending = False
        inst.triggerRedraw = lambda n: None
        inst.requestScreenshot()
        assert inst._screenshotPending is True


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
        inst.options = _config(animate=True, anim_time=None)
        player = _Player()
        scene = types.SimpleNamespace(
            animations=[types.SimpleNamespace(name='clip')],
            player=lambda idx, loop: player)
        inst.setupAnimation(scene)
        assert inst._player is player
        assert player.evaluated == [0.0]                 # first frame shown at once

    def test_advance_animation_ticks_the_clock(self):
        inst = _inst()
        inst.options = _config(anim_time=None)
        inst._player = _Player()
        inst._animationPlaying = True
        inst._animationLast = None
        inst._animationClock = 0.0
        assert inst.advanceAnimation() is True
        assert inst._player.evaluated                    # evaluated at the current clock

    def test_advance_animation_with_a_pinned_time_is_static(self):
        inst = _inst()
        inst.options = _config(anim_time=1.5)
        inst._player = _Player()
        assert inst.advanceAnimation() is False
        assert inst._player.evaluated == [1.5]

    def test_toggle_animation_flips_play_state(self):
        inst = _inst()
        inst._animationPlaying = True
        inst._animations = []
        inst._animationNames = []
        inst._animationIndex = 0
        inst.source = 'm.glb'
        inst.viewpoints = []
        inst._cameraNames = []
        inst.cameraIndex = 0
        inst.physicsWalking = False
        inst.triggerRedraw = lambda n: None
        inst.toggleAnimation()
        assert inst._animationPlaying is False

    def test_cycle_animation_rebinds_a_player_for_the_new_index(self, monkeypatch):
        from OpenGLContext.loaders.gltf import animation as anim_mod
        monkeypatch.setattr(anim_mod, 'Player',
                            lambda *a, **k: _Player(duration=3.0))
        inst = _inst()
        inst._animations = ['a', 'b']
        inst._animationNames = ['walk', 'run']
        inst._animationIndex = 0
        inst._player = _Player()
        # The scene is what builds a player, so it keeps the skins wired.
        inst.scene = types.SimpleNamespace(
            player=lambda index=0, loop=True: _Player())
        inst.source = 'm.glb'
        inst.viewpoints = []
        inst._cameraNames = []
        inst.cameraIndex = 0
        inst.physicsWalking = False
        inst._animationPlaying = True
        inst.triggerRedraw = lambda n: None
        inst.nextAnimation()
        assert inst._animationIndex == 1

    def test_cycle_animation_is_a_noop_without_animations(self):
        inst = _inst()
        inst._animations = []
        inst.previousAnimation()                           # must not raise


class TestTurntableToggle:
    def test_toggle_turntable_snaps_back_when_stopped(self):
        inst = _inst()
        inst.options = _config(turntable=True)            # currently spinning
        inst.modelTransform = types.SimpleNamespace(rotation=(0, 1, 0, 1.0))
        inst._defaultModelRotation = (0, 1, 0, 0.0)
        inst.triggerRedraw = lambda n: None
        inst.toggleTurntable()
        assert inst.options.turntable is False
        assert inst.modelTransform.rotation == (0, 1, 0, 0.0)


class TestCameraSelection:
    def _inst(self):
        inst = _inst()
        inst.viewpoints = [Viewpoint(), Viewpoint()]
        inst._cameraNames = ['front', 'side']
        inst.cameraIndex = 0
        inst.options = _config(camera='side')
        return inst

    def test_select_initial_camera_binds_the_named_viewpoint(self):
        inst = self._inst()
        inst.selectInitialCamera()
        assert inst.cameraIndex == 1 and inst.viewpoints[1].isBound is True

    def test_select_initial_camera_warns_on_an_unknown_name(self, capsys):
        inst = self._inst()
        inst.options = _config(camera='missing')
        inst.selectInitialCamera()
        assert 'No camera matching' in capsys.readouterr().err

    def test_cycle_viewpoint_advances_and_binds(self):
        inst = self._inst()
        inst.physicsPlatform = None
        inst.physicsWalking = False
        inst.source = 'm.glb'
        inst._animations = []
        inst._animationNames = []
        inst._animationIndex = 0
        inst._animationPlaying = True
        inst.getSceneGraph = lambda: types.SimpleNamespace(boundViewpoint=None)
        inst.triggerRedraw = lambda n: None
        inst.nextCamera()
        assert inst.cameraIndex == 1


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
        inst._physicsKey(types.SimpleNamespace(name='w'))
        assert drawn

    def test_the_fly_key_swaps_the_mode_and_tells_the_character(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        from OpenGLContext.move.modes import walk_fly_modes
        inst = _inst()
        seen = {}
        inst.physicsPlatform = types.SimpleNamespace(
            jump=lambda: None, character=types.SimpleNamespace(flying=False),
            set_fly=lambda v: seen.setdefault('fly', v), look=lambda d: None,
            submerged=False, turn=lambda d: None,
            set_move=lambda **k: None, set_fly_move=lambda **k: None)
        inst.physicsWalking = True
        inst.contextDefinition = ContextDefinition(
            movementModes=walk_fly_modes())
        inst.navigation = None
        inst.togglePhysicsFly(None)
        assert seen['fly'] is True
        assert inst.contextDefinition.movementMode.name == 'fly'
        inst.togglePhysicsFly(None)
        assert seen['fly'] is True                        # first answer kept
        assert inst.contextDefinition.movementMode.name == 'walk'

    def test_the_fly_key_does_nothing_before_physics_exists(self):
        inst = _inst()
        inst.physicsPlatform = None
        inst.navigation = None
        inst.togglePhysicsFly(None)


class TestFrameDegenerate:
    def test_eye_equal_to_target_leaves_the_platform_untouched(self):
        inst = _inst()
        inst.options = _config(eye=(1.0, 1.0, 1.0), look_at=(1.0, 1.0, 1.0))
        inst.platform = _Platform()
        inst.frameModel(10.0)
        assert not hasattr(inst.platform, 'position')     # degenerate: never placed


class TestCaptureInstall:
    def test_a_capture_path_arranges_a_settled_grab(self):
        inst = _inst()
        inst.setupCapture('shot.png', 0.3, 5)
        assert inst.settleCapture is not None
        assert inst.capturing is True

    def test_no_capture_path_leaves_the_run_interactive(self):
        inst = _inst()
        inst.setupCapture(None)
        assert inst.settleCapture is None
        assert inst.capturing is False


class TestTheCaptionIsDrawnLikeEverythingElse:
    """It reached for the flat pass's shader and measured its own text; it is a
    HUD layer now, so the shader and the viewport are the screen's business."""

    def test_the_viewer_no_longer_draws_its_own_text(self):
        for gone in ('activeShader', 'viewportSize', 'drawOverlays',
                     'drawOverlayText'):
            assert not hasattr(V.TestContext, gone), gone

    def test_the_caption_is_a_hud_layer_on_the_context(self):
        from OpenGLContext.viewer.caption import CaptionLayer
        inst = _inst()
        assert isinstance(inst.captionLayer, CaptionLayer)


class TestMainListCamerasEdges:
    def test_list_cameras_reports_when_a_model_has_none(self, tmp_path, monkeypatch, capsys):
        model = tmp_path / 'm.glb'
        model.write_bytes(b'x')
        monkeypatch.setattr(V, 'adapter_for', lambda src: _StubAdapter([]))
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
        assert inst.advanceAnimation() is False

    def test_paused_animation_needs_no_redraw(self):
        inst = _inst()
        inst.options = _config(anim_time=None)
        inst._player = _Player()
        inst._animationPlaying = False
        assert inst.advanceAnimation() is False

    def test_a_second_tick_accumulates_wall_time(self):
        inst = _inst()
        inst.options = _config(anim_time=None)
        inst._player = _Player()
        inst._animationPlaying = True
        inst._animationLast = V.TestContext._now() - 0.02      # a prior tick 20ms ago
        inst._animationClock = 0.0
        assert inst.advanceAnimation() is True
        assert inst._animationClock > 0.0                      # clock moved forward


class TestTurntableStart:
    def test_toggle_turntable_on_starts_spinning_from_now(self):
        inst = _inst()
        inst.options = _config(turntable=False)
        inst.modelTransform = types.SimpleNamespace(rotation=(0, 1, 0, 0.0))
        inst._defaultModelRotation = (0, 1, 0, 0.0)
        inst.triggerRedraw = lambda n: None
        inst.toggleTurntable()
        assert inst.options.turntable is True
        assert isinstance(inst._turntableStart, float)


class TestRequestAndPollExtras:
    def test_request_initial_scene_kicks_off_the_source_load(self):
        inst = _inst()
        inst.source = 'Duck.glb'
        recorded = {}
        inst.requestScene = lambda produce, label: recorded.update(
            produce=produce, label=label)
        inst.requestInitialScene()
        assert recorded['produce'] == inst.loadScene
        assert 'Duck.glb' in recorded['label']

    def test_request_scene_captures_a_producer_failure(self):
        import threading
        import time
        inst = _inst()
        inst._loadLock = threading.Lock()
        inst._loadToken = 0
        inst.overlayText = ''
        inst.overlayError = False
        inst.triggerRedraw = lambda n: None

        def boom():
            raise RuntimeError('decode failed')
        inst.requestScene(boom, 'Loading ...')
        for _ in range(200):
            if inst._pendingScene is not None:
                break
            time.sleep(0.01)
        scene, error = inst._pendingScene
        assert scene is None and isinstance(error, RuntimeError)

    def test_poll_applies_a_loaded_scene(self):
        import threading
        inst = _inst()
        inst._loadLock = threading.Lock()
        inst.triggerRedraw = lambda n: None
        applied = {}
        inst.applyLoadedScene = lambda s: applied.setdefault('scene', s)
        inst._pendingScene = ('SCENE', None)
        assert inst.pollPendingScene() is True
        assert applied['scene'] == 'SCENE'


class TestCycleViewpointPhysics:
    def test_cycle_teleports_the_walking_avatar_to_the_new_viewpoint(self):
        inst = _inst()
        vp0, vp1 = Viewpoint(), Viewpoint()
        inst.viewpoints = [vp0, vp1]
        inst._cameraNames = ['front', 'side']
        inst.cameraIndex = 0
        vp0.isBound = True
        moved = {}
        inst.physicsPlatform = types.SimpleNamespace(
            yaw=0.0, pitch=0.0,
            character=types.SimpleNamespace(grounded=True),
            bind_eye=lambda pos: moved.setdefault('eye', pos),
            set_fly=lambda v: moved.setdefault('fly', v))
        inst.physicsWalking = True
        inst.source = 'm.glb'
        inst._animations = []
        inst._animationNames = []
        inst._animationIndex = 0
        inst._animationPlaying = True
        inst.getSceneGraph = lambda: types.SimpleNamespace(boundViewpoint=vp0)
        inst.triggerRedraw = lambda n: None
        inst.previousCamera()                                   # wraps 0 -> 1
        assert inst.cameraIndex == 1
        assert 'eye' in moved                              # avatar teleported


class TestPhysicsSeams:
    def test_yaw_from_platform_reads_the_camera_heading(self):
        from OpenGLContext import quaternion
        inst = _inst()
        inst.platform = types.SimpleNamespace(
            quaternion=quaternion.fromXYZR(0, 1, 0, 0.0))
        assert abs(inst.yawFromPlatform()) < 1e-6       # identity faces -Z

    def test_setup_physics_returns_early_for_a_capture_run(self):
        inst = _inst()
        inst.options = _config(capture='shot.png')
        inst.movementManager = 'freefly-manager'
        inst.sceneLoaded = False
        inst.sg = None
        inst.setupWalking()
        assert inst._freeManager == 'freefly-manager'     # captured the navigator, then bailed


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
        inst.options = _config(background='cube')
        bg = environment.background_for(inst.options.background)
        assert bg is not None and not isinstance(bg, type(None))

    def test_env_hdr_background_builds_a_node_from_the_env_var(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/env/studio.hdr')
        assert environment.hdr_background() is not None


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))


class TestSwitchingAnimations:
    """A skinned model must still be skinned after the animation changes.

    Switching built a bare ``Player`` from the animation and the node
    transforms, dropping the skins and the world-matrix hook the scene wires in
    for it.  Its ``update_skins`` then had nothing to update, so a skinned model
    -- Fox, CesiumMan, BrainStem -- froze in whatever pose it was last left in
    while the caption said the new animation was playing.
    """

    class _Scene:
        def __init__(self):
            self.asked = []
            self.animations = ['a', 'b', 'c']

        def player(self, index=0, loop=True):
            self.asked.append((index, loop))
            return types.SimpleNamespace(duration=1.0, node_transforms={},
                                         node_morph={}, evaluate=lambda t: None)

    def _viewer(self, scene):
        inst = _inst()
        inst.scene = scene
        inst._animations = list(scene.animations)
        inst._animationNames = ['Survey', 'Walk', 'Run']
        inst._animationIndex = 0
        inst._animationPlaying = True
        inst._animationClock = 5.0
        inst._animationLast = 1.0
        inst._player = None
        inst.source = 'fox.glb'
        inst.viewpoints = []
        inst._cameraNames = []
        inst.cameraIndex = 0
        inst.physicsWalking = False
        inst.triggerRedraw = lambda n=1: None
        return inst

    def test_the_scene_is_what_makes_the_new_player(self):
        scene = self._Scene()
        viewer = self._viewer(scene)
        viewer.cycleAnimation(1)
        assert scene.asked == [(1, True)], 'built its own player instead'

    def test_it_wraps_round_the_animations(self):
        scene = self._Scene()
        viewer = self._viewer(scene)
        viewer.cycleAnimation(-1)
        assert scene.asked == [(2, True)]

    def test_the_clock_starts_again(self):
        scene = self._Scene()
        viewer = self._viewer(scene)
        viewer.cycleAnimation(1)
        assert viewer._animationClock == 0.0
        assert viewer._animationLast is None

    def test_a_model_with_no_animations_is_left_alone(self):
        scene = self._Scene()
        viewer = self._viewer(scene)
        viewer._animations = []
        viewer.cycleAnimation(1)
        assert scene.asked == []

    def test_a_viewer_with_no_scene_does_not_raise(self):
        """A host that produced its own scene may not have handed one over."""
        viewer = self._viewer(self._Scene())
        viewer.scene = None
        viewer.cycleAnimation(1)
