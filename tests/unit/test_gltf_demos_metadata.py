"""The shared demo metadata (OpenGLContext.loaders.gltf_demos) is the single
source of truth for how each glTF demo is framed and lit. These guard its shape
and the derivations the browser demo and doc-image gallery build from it."""
from OpenGLContext.loaders import gltf_demos


class TestSceneSpec:
    def test_every_scene_has_a_name_and_frames_via_camera_ids(self):
        names = [s.name for s in gltf_demos.iter_scenes()]
        assert names, "roster is empty"
        assert len(names) == len(set(names)), "duplicate scene names"
        for s in gltf_demos.iter_scenes():
            # camera_ids is what the runner iterates; a sample yields one auto view.
            assert s.camera_ids(), s.name

    def test_unlisted_model_gets_default_framing(self):
        s = gltf_demos.scene_for('NoSuchModel')
        assert s.name == 'NoSuchModel'
        assert s.margin == 1.05 and s.background == 'sky'
        # default camera is level and centred (no elevation/tilt)
        assert s.elevation == 0.0 and s.tilt == 0.0
        assert s.camera_ids() == [None]

    def test_flagged_models_frame_tighter_than_default(self):
        # the QA 'too small in frame' models get a margin below the 1.15 default
        for name in ('MetalRoughSpheres', 'EnvironmentTest', 'IridescenceSuzanne',
                     'TransmissionRoughnessTest'):
            assert gltf_demos.scene_for(name).margin < 1.15, name

    def test_reflective_models_use_the_cube_environment(self):
        for name in ('MetalRoughSpheres', 'NegativeScaleTest', 'IridescenceMetallicSpheres'):
            assert gltf_demos.scene_for(name).background == 'cube', name

    def test_slug_disambiguates_baked_cameras(self):
        s = gltf_demos.scene_for('Duck')
        assert s.slug() == 'Duck'
        assert gltf_demos.scene_for('Parthenon').slug(3) == 'Parthenon__cam03'


class TestParthenon:
    def test_parthenon_is_local_and_multi_camera_without_upstream(self):
        s = gltf_demos.scene_for('Parthenon')
        assert s.source == '@parthenon'
        assert s.upstream is False           # no Khronos reference for a local build
        assert len(s.camera_ids()) > 1       # one shot per baked camera

    def test_resolve_source_maps_sentinel_to_local_path(self):
        s = gltf_demos.scene_for('Parthenon')
        src, is_local = gltf_demos.resolve_source(s, parthenon='/tmp/p.glb')
        assert is_local is True and src == '/tmp/p.glb'

    def test_resolve_source_maps_sample_to_name(self):
        s = gltf_demos.scene_for('Duck')
        src, is_local = gltf_demos.resolve_source(s)
        assert is_local is False and src == 'Duck'


class TestSharedDerivations:
    def test_demo_env_background_roster_comes_from_shared_module(self):
        from OpenGLContext.bin import gltf_demo
        assert set(gltf_demo._ENV_BACKGROUND) == set(gltf_demos.ENV_BACKGROUND_MODELS)
        # and a representative reflective model still resolves to a lit background
        cfg = gltf_demo.demo_config([])
        assert gltf_demo.resolve_background(cfg, 'MetalRoughSpheres') == 'sky'

    def test_doc_gallery_framing_comes_from_shared_module(self):
        import importlib.util, os
        from OpenGLContext.testing.paths import tests_root
        path = os.path.join(str(tests_root(__file__).parent),
                            'scripts', 'generate_doc_images.py')
        spec = importlib.util.spec_from_file_location('gen_doc_images', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        by_name = dict(mod.GLTF_DEMOS)
        assert by_name['DamagedHelmet'][0] == gltf_demos.scene_for('DamagedHelmet').yaw
