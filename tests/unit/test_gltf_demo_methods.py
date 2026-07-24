"""Non-GL logic of the oglc-gltf-demo browser: catalogue preparation, model
selection, the async load handoff and main() dispatch. The scenegraph build, the
reference-thumbnail upload and the overlays need a live GL context and are covered
by the demo render tests, not here."""
import argparse
import os
import types

import pytest

_ENV_KEYS = ('OPENGLCONTEXT_PROFILE', 'OPENGLCONTEXT_BACKEND', 'OPENGLCONTEXT_RENDERER',
             'OPENGLCONTEXT_SHADOWS', 'OPENGLCONTEXT_SHADOW_CASCADES',
             'OPENGLCONTEXT_IBL_INTENSITY', 'OPENGLCONTEXT_ENV_CUBEMAP', 'OPENGLCONTEXT_IBL')
_SNAP = {k: os.environ.get(k) for k in _ENV_KEYS}
from OpenGLContext.bin import gltf_demo as D  # noqa: E402
for _k, _v in _SNAP.items():
    if _v is None:
        os.environ.pop(_k, None)
    else:
        os.environ[_k] = _v


def _inst():
    return D.TestContext.__new__(D.TestContext)


def _catalog(*names):
    return [{'name': n, 'display': n, 'screenshot_url': None} for n in names]


class TestDefaultEnvPrefix:
    def test_env_override_wins(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_CUBEMAP', '/custom/env_')
        assert D.default_env_prefix() == '/custom/env_'

    def test_bundled_prefix_used_without_an_override(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)
        prefix = D.default_env_prefix()
        assert prefix is not None and os.path.exists(prefix + 'UP.jpg')


class TestPrepareSource:
    def test_starts_at_the_named_model_from_the_env(self, monkeypatch):
        monkeypatch.setattr(D.gltf, 'fetch_sample_catalog',
                            lambda: _catalog('Duck', 'Helmet', 'Lantern'))
        monkeypatch.setenv('MODEL', 'Lantern')
        inst = _inst()
        inst._prepare_source()
        assert inst.index == 2 and inst.source is None

    def test_numeric_env_indexes_the_catalogue(self, monkeypatch):
        monkeypatch.setattr(D.gltf, 'fetch_sample_catalog',
                            lambda: _catalog('A', 'B', 'C'))
        monkeypatch.setenv('MODEL', '5')                   # wraps modulo len
        inst = _inst()
        inst._prepare_source()
        assert inst.index == 5 % 3

    def test_unknown_name_starts_at_zero(self, monkeypatch):
        monkeypatch.setattr(D.gltf, 'fetch_sample_catalog',
                            lambda: _catalog('A', 'B'))
        monkeypatch.setenv('MODEL', 'Nope')
        inst = _inst()
        inst._prepare_source()
        assert inst.index == 0

    def test_falls_back_to_the_builtin_list_when_the_catalogue_is_unreachable(
            self, monkeypatch, capsys):
        def boom():
            raise RuntimeError('offline')
        monkeypatch.setattr(D.gltf, 'fetch_sample_catalog', boom)
        monkeypatch.delenv('MODEL', raising=False)
        inst = _inst()
        inst._prepare_source()
        assert len(inst.catalog) == len(D.gltf.SAMPLE_MODELS)
        assert 'Could not fetch' in capsys.readouterr().out


class TestLoadScene:
    def test_successful_load_sets_the_label(self, monkeypatch):
        monkeypatch.setattr(D.gltf, 'load_sample', lambda name: 'SCENE:%s' % name)
        inst = _inst()
        inst.catalog = _catalog('Duck')
        inst.index = 0
        scene = inst._load_scene()
        assert scene == 'SCENE:Duck'
        assert inst._ref_current == 'Duck' and inst.overlay_error is False

    def test_failed_load_flags_the_overlay(self, monkeypatch):
        def boom(name):
            raise RuntimeError('decode error line one\nline two')
        monkeypatch.setattr(D.gltf, 'load_sample', boom)
        inst = _inst()
        inst.catalog = _catalog('Broken')
        inst.index = 0
        assert inst._load_scene() is None
        assert inst.overlay_error is True and 'FAILED' in inst._label


class TestRequestCurrentModel:
    def test_kicks_off_a_background_load_of_the_indexed_model(self, monkeypatch):
        inst = _inst()
        inst.catalog = _catalog('Duck', 'Helmet')
        inst.index = 1
        recorded = {}
        inst._request_scene = lambda produce, label: recorded.update(
            produce=produce, label=label)
        inst._request_current_model()
        assert inst._pending_name == 'Helmet'
        assert 'Helmet' in recorded['label']

    def test_request_initial_scene_pulls_the_current_model(self, monkeypatch):
        inst = _inst()
        called = {}
        inst._request_current_model = lambda: called.setdefault('ran', True)
        inst._request_initial_scene()
        assert called['ran'] is True


class TestNavigation:
    def test_next_model_advances_and_wraps(self):
        inst = _inst()
        inst.catalog = _catalog('A', 'B', 'C')
        inst.index = 2
        requested = {}
        inst._request_current_model = lambda: requested.setdefault('i', inst.index)
        inst._next_model()
        assert inst.index == 0                              # wrapped past the end

    def test_prev_model_wraps_backwards(self):
        inst = _inst()
        inst.catalog = _catalog('A', 'B', 'C')
        inst.index = 0
        inst._request_current_model = lambda: None
        inst._prev_model()
        assert inst.index == 2


class TestApplyLoadedAndFailed:
    def test_apply_loaded_builds_the_scene_and_marks_it_ready(self):
        inst = _inst()
        inst._pending_name = 'Duck'
        inst._pending_label = '[1/1] Duck'
        built = {}
        inst._build_scenegraph = lambda scene: built.setdefault('scene', scene)
        inst._on_scene_ready = lambda: built.setdefault('ready', True)
        inst._apply_loaded('SCENE')
        assert inst._ref_current == 'Duck' and inst.overlay_error is False
        assert built == {'scene': 'SCENE', 'ready': True}

    def test_apply_failed_sets_a_red_overlay(self, capsys):
        inst = _inst()
        inst._pending_name = 'Broken'
        inst._pending_label = '[2/9] Broken'
        inst._apply_failed(RuntimeError('kaboom\ndetail'))
        assert inst.overlay_error is True
        assert 'FAILED: kaboom' in inst.overlay_text
        capsys.readouterr()

    def test_on_scene_ready_marks_loaded_and_applies_the_profile(self):
        inst = _inst()
        applied = {}
        inst._apply_physics_profile = lambda: applied.setdefault('ran', True)
        inst._on_scene_ready()
        assert inst._scene_loaded is True and applied['ran'] is True


class TestApplyPhysicsProfile:
    def test_no_scenegraph_yet_is_a_noop(self):
        inst = _inst()
        inst.sg = None
        inst.config = argparse.Namespace(capture=None)
        inst._apply_physics_profile()                       # returns without touching physics

    def test_capture_run_skips_physics(self):
        inst = _inst()
        inst.sg = object()
        inst.config = argparse.Namespace(capture='shot.png')
        inst._apply_physics_profile()                       # capture -> no physics rebuild


class TestResolveBackgroundCube:
    def test_cube_profile_selects_the_env_skybox(self, monkeypatch):
        monkeypatch.setattr(D, 'profile_for',
                            lambda name: D.ModelProfile(background='cube'))
        cfg = D.demo_config([])
        assert D.resolve_background(cfg, 'Whatever') == 'cube'


class TestBuildAndPhysics:
    def test_build_scenegraph_applies_the_profile_then_delegates(self, monkeypatch):
        inst = _inst()
        inst._ref_current = 'Duck'
        inst._label = '[1/1] Duck'
        inst.config = D.demo_config([])
        parent = {}
        monkeypatch.setattr(D.ViewerContext, '_build_scenegraph',
                            lambda self, scene: parent.setdefault('scene', scene))
        inst._build_scenegraph('SCENE')
        assert parent['scene'] == 'SCENE'
        assert inst.overlay_text == '[1/1] Duck'
        assert os.environ['OPENGLCONTEXT_BLOOM'] in ('0', '1')

    def test_setup_physics_leaves_a_turntable_model_grounded(self, monkeypatch):
        inst = _inst()
        inst._ref_current = 'Duck'                          # default profile: no physics
        inst.config = D.demo_config([])
        inst._physics = None
        monkeypatch.setattr(D.ViewerContext, '_setup_physics', lambda self: None)
        inst._setup_physics()
        assert inst.config.physics is False

    def test_setup_physics_starts_a_flying_scene_in_free_fly(self, monkeypatch):
        inst = _inst()
        inst._ref_current = 'VirtualCity'                   # profile: physics + fly
        inst.config = D.demo_config([])
        inst.sg = object()
        seen = {}
        inst._physics = types.SimpleNamespace(set_fly=lambda v: seen.setdefault('fly', v))
        monkeypatch.setattr(D.ViewerContext, '_setup_physics', lambda self: None)
        inst._setup_physics()
        assert inst.config.physics is True and seen['fly'] is True


class TestReferenceTexture:
    def test_model_without_a_screenshot_url_has_no_reference(self):
        inst = _inst()
        inst._ref_current = 'Duck'
        inst._ref_textures = {}
        inst.catalog = [{'name': 'Duck', 'screenshot_url': None}]
        inst.index = 0
        assert inst._reference_texture() is None
        assert inst._ref_textures['Duck'] is False          # cached the miss

    def test_cached_reference_is_returned_without_refetching(self):
        inst = _inst()
        inst._ref_current = 'Duck'
        sentinel = ('tex', 1.5)
        inst._ref_textures = {'Duck': sentinel}
        assert inst._reference_texture() == sentinel


class TestMain:
    def test_configures_and_enters_the_loop(self, monkeypatch):
        monkeypatch.setattr(D, 'apply_environment', lambda args: None)
        monkeypatch.setattr(D, 'apply_render_env', lambda args: None)
        ran = {}
        monkeypatch.setattr(D.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: ran.setdefault('size', size)))
        D.main([])
        assert D.TestContext.config.no_cameras is True
        assert 'size' in ran

    def test_size_flag_reaches_the_loop(self, monkeypatch):
        monkeypatch.setattr(D, 'apply_environment', lambda args: None)
        monkeypatch.setattr(D, 'apply_render_env', lambda args: None)
        seen = {}
        monkeypatch.setattr(D.TestContext, 'ContextMainLoop',
                            classmethod(lambda cls, size=None: seen.setdefault('size', size)))
        D.main(['--size', '1024x768'])
        assert seen['size'] == (1024, 768)


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))
