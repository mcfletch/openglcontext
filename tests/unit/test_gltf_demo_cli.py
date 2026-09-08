"""Config tests for the oglc-gltf-demo browser (pure arg massaging, no GL)."""
import os

import pytest

from OpenGLContext.testing.gl_env import import_unconfigured

# The demo pulls in the viewer, which settles the renderer as it is imported
# because it is a program about to draw. This imports it to read its argument
# parsing, so the settling is put back.
gltf_demo = import_unconfigured('OpenGLContext.bin.gltf_demo')


class TestDemoConfig:
    def test_defaults_to_no_physics(self):
        """The turntable browser has no ground to walk; physics is off by default
        so the avatar doesn't fall out of view."""
        args = gltf_demo.demo_config([])
        assert args.physics is False

    def test_browser_framing_defaults(self):
        args = gltf_demo.demo_config([])
        assert args.no_cameras is True
        assert args.turntable is True
        # default is black; per-model profiles inject a lit/cube background where needed
        assert args.background == 'none'

    def test_explicit_physics_flag_honoured(self):
        assert gltf_demo.demo_config(['--physics']).physics is True

    def test_explicit_no_physics_flag_honoured(self):
        assert gltf_demo.demo_config(['--no-physics']).physics is False


class TestDemoCaptureFreezesRotation:
    """A --capture run must be a fixed, reference-comparable orientation (the
    turntable would otherwise spin the model away from the reference pose)."""

    def test_browse_turntables_by_default(self):
        assert gltf_demo.demo_config([]).turntable is True

    def test_capture_freezes_turntable(self):
        assert gltf_demo.demo_config(['--capture', 'shot.png']).turntable is False

    def test_capture_honours_explicit_turntable(self):
        args = gltf_demo.demo_config(['--capture', 'shot.png', '--turntable'])
        assert args.turntable is True


class TestModelProfiles:
    def test_unknown_model_uses_default(self):
        p = gltf_demo.profile_for('NoSuchModel')
        assert p.turntable is True
        assert p.physics is False
        assert p.fly is False

    def test_sponza_walks_no_rotate(self):
        p = gltf_demo.profile_for('Sponza')
        assert p.physics is True
        assert p.turntable is False

    def test_city_flies_inside(self):
        p = gltf_demo.profile_for('VirtualCity')
        assert p.physics is True
        assert p.fly is True
        assert p.turntable is False

    def test_object_uses_default_facing_and_rotation(self):
        # DamagedHelmet is correct at the default yaw 0 (visor toward camera), so it
        # keeps the default profile: face-on, slow turntable, no physics.
        p = gltf_demo.profile_for('DamagedHelmet')
        assert p.turntable is True
        assert p.physics is False
        assert p.yaw == 0.0


class TestResolveView:
    def test_default_profile_turntables(self):
        cfg = gltf_demo.demo_config([])
        yaw, turntable = gltf_demo.resolve_view(cfg, 'Duck')
        assert turntable is True

    def test_no_rotate_forces_fixed(self):
        cfg = gltf_demo.demo_config(['--no-rotate'])
        assert cfg.no_rotate is True
        _, turntable = gltf_demo.resolve_view(cfg, 'Duck')
        assert turntable is False

    def test_sponza_profile_disables_turntable(self):
        cfg = gltf_demo.demo_config([])
        _, turntable = gltf_demo.resolve_view(cfg, 'Sponza')
        assert turntable is False

    def test_explicit_turntable_overrides_profile(self):
        cfg = gltf_demo.demo_config(['--turntable'])
        _, turntable = gltf_demo.resolve_view(cfg, 'Sponza')   # profile says off
        assert turntable is True

    def test_explicit_yaw_overrides_profile(self):
        cfg = gltf_demo.demo_config(['--yaw', '1.234'])
        yaw, _ = gltf_demo.resolve_view(cfg, 'DamagedHelmet')
        assert abs(yaw - 1.234) < 1e-6


class TestResolveBackground:
    def test_default_model_is_black(self):
        cfg = gltf_demo.demo_config([])
        assert gltf_demo.resolve_background(cfg, 'Duck') == 'none'

    def test_transmissive_model_gets_lit_background(self):
        cfg = gltf_demo.demo_config([])
        # glass needs a lit backdrop to refract (black -> opaque rough glass)
        assert gltf_demo.resolve_background(cfg, 'TransmissionRoughnessTest') == 'sky'

    def test_reflective_model_gets_lit_background(self):
        cfg = gltf_demo.demo_config([])
        assert gltf_demo.resolve_background(cfg, 'MetalRoughSpheres') == 'sky'

    def test_explicit_background_overrides_profile(self):
        cfg = gltf_demo.demo_config(['--background', '0,0,0'])
        assert gltf_demo.resolve_background(cfg, 'TransmissionRoughnessTest') == '0,0,0'

    def test_bundled_env_faces_exist(self):
        # the 'cube' background must have faces to show out of the box
        prefix = gltf_demo.default_env_prefix()
        assert prefix is not None
        import os
        for suffix in ('RT', 'LF', 'UP', 'DN', 'FR', 'BK'):
            assert os.path.exists(prefix + suffix + '.jpg')


class TestEnvironmentReflection:
    def test_apply_environment_loads_env_and_full_ibl(self, monkeypatch):
        # so metals reflect a real environment (SpecularTest/MetalRoughSpheres/...)
        for k in ('OPENGLCONTEXT_ENV_CUBEMAP', 'OPENGLCONTEXT_IBL',
                  'OPENGLCONTEXT_IBL_INTENSITY'):
            monkeypatch.delenv(k, raising=False)
        gltf_demo.apply_environment(gltf_demo.demo_config([]))
        import os
        assert os.environ.get('OPENGLCONTEXT_ENV_CUBEMAP')
        assert os.environ['OPENGLCONTEXT_IBL'] == 'full'
        assert float(os.environ['OPENGLCONTEXT_IBL_INTENSITY']) > 0.4  # brighter than the shadow default

    def test_explicit_ibl_intensity_wins(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_IBL_INTENSITY', raising=False)
        gltf_demo.apply_environment(gltf_demo.demo_config(['--ibl-intensity', '0.3']))
        import os
        # apply_environment must not clobber an explicit flag (apply_render_env sets it)
        assert os.environ.get('OPENGLCONTEXT_IBL_INTENSITY') != '0.9'


class TestResolveBloom:
    def test_default_no_bloom(self):
        assert gltf_demo.resolve_bloom('Duck') is False

    def test_emissive_strength_gets_bloom(self):
        assert gltf_demo.resolve_bloom('EmissiveStrengthTest') is True


class TestResolvePhysics:
    def test_default_no_physics(self):
        cfg = gltf_demo.demo_config([])
        physics, fly = gltf_demo.resolve_physics(cfg, 'Duck')
        assert physics is False

    def test_sponza_enables_physics(self):
        cfg = gltf_demo.demo_config([])
        physics, fly = gltf_demo.resolve_physics(cfg, 'Sponza')
        assert physics is True and fly is False

    def test_city_enables_fly(self):
        cfg = gltf_demo.demo_config([])
        physics, fly = gltf_demo.resolve_physics(cfg, 'VirtualCity')
        assert physics is True and fly is True

    def test_capture_disables_physics(self):
        cfg = gltf_demo.demo_config(['--capture', 'x.png'])
        physics, _ = gltf_demo.resolve_physics(cfg, 'Sponza')
        assert physics is False

    def test_explicit_no_physics_overrides_profile(self):
        cfg = gltf_demo.demo_config(['--no-physics'])
        physics, _ = gltf_demo.resolve_physics(cfg, 'Sponza')
        assert physics is False


class TestDemoNavigationKeys:
    """Model paging must not steal the arrow keys (they drive the camera)."""

    def test_arrows_not_bound_to_model_paging(self):
        keys = (gltf_demo.TestContext.NEXT_MODEL_KEYS
                + gltf_demo.TestContext.PREV_MODEL_KEYS)
        for arrow in ('<left>', '<right>', '<up>', '<down>'):
            assert arrow not in keys

    def test_paging_keys_present(self):
        assert 'n' in gltf_demo.TestContext.NEXT_MODEL_KEYS
        assert '<pagedown>' in gltf_demo.TestContext.NEXT_MODEL_KEYS
        assert 'p' in gltf_demo.TestContext.PREV_MODEL_KEYS
        assert '<pageup>' in gltf_demo.TestContext.PREV_MODEL_KEYS
