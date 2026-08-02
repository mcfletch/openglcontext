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
        assert s.margin == 1.05 and s.capture_background == 'sky'
        # default camera is level and centred (no elevation/tilt)
        assert s.elevation == 0.0 and s.tilt == 0.0
        assert s.camera_ids() == [None]

    def test_a_scene_with_no_lighting_opinion_captures_against_the_sky(self):
        # An empty `background` is 'no opinion': a capture falls back to the lit
        # gradient sky, while the browser (which defaults to black) leaves it black.
        s = gltf_demos.scene_for('Duck')
        assert s.background == ''
        assert s.capture_background == 'sky'
        assert gltf_demos.scene_for('LightsPunctualLamp').capture_background == 'cube'

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


class TestScenePublishedElsewhere:
    """A scene named by URL: published outside the Khronos catalogue, and not a
    file in this tree either, so it is fetched rather than opened."""

    def test_resolve_source_keeps_a_url_for_the_caller_to_fetch(self):
        s = gltf_demos.SceneSpec('Remote', source='https://example.invalid/s.glb')
        src, is_local = gltf_demos.resolve_source(s)
        assert is_local is False and src == 'https://example.invalid/s.glb'

    def test_the_xr_publisher_scene_uses_its_own_camera_and_has_no_upstream(self):
        s = gltf_demos.scene_for('XRPublisherExampleScene')
        assert s.source and s.source.startswith('https://')
        assert s.upstream is False           # no Khronos reference for it
        assert s.camera_ids() == [0]         # framed by its own authored camera


class TestSharedDerivations:
    def test_demo_env_background_roster_comes_from_shared_module(self):
        from OpenGLContext.bin import gltf_demo
        assert set(gltf_demo._ENV_BACKGROUND) == set(gltf_demos.ENV_BACKGROUND_MODELS)
        # and a representative reflective model still resolves to a lit background
        cfg = gltf_demo.demo_config([])
        assert gltf_demo.resolve_background(cfg, 'MetalRoughSpheres') == 'sky'

    def test_every_scene_that_names_a_backdrop_gets_a_lit_one_in_the_browser(self):
        """The roster is derived from the table, so the browser and the capture
        harness cannot disagree about which models must not be shown on black."""
        for s in gltf_demos.iter_scenes():
            if s.background and s.background != 'none':
                assert gltf_demos.needs_env_background(s.name), s.name

    def test_self_lit_lamp_is_browsed_against_a_lit_background(self):
        # LightsPunctualLamp's own bulb lights only its shade: on black the light
        # meter stops the camera down to near-nothing and the model disappears.
        from OpenGLContext.bin import gltf_demo
        cfg = gltf_demo.demo_config([])
        assert gltf_demo.resolve_background(cfg, 'LightsPunctualLamp') == 'sky'
        # a model with no lighting opinion of its own still browses on black
        assert gltf_demo.resolve_background(cfg, 'Duck') == 'none'

    def test_doc_gallery_framing_comes_from_shared_module(self):
        import importlib.util
        import os
        from OpenGLContext.testing.paths import tests_root
        path = os.path.join(str(tests_root(__file__).parent),
                            'scripts', 'generate_doc_images.py')
        spec = importlib.util.spec_from_file_location('gen_doc_images', path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        by_name = dict(mod.GLTF_DEMOS)
        assert by_name['DamagedHelmet'][0] == gltf_demos.scene_for('DamagedHelmet').yaw


class TestFeatureTests:
    """Which entries are *demos* and which are conformance fixtures.

    Most of the Khronos roster exists to exercise one glTF feature -- a sparse
    accessor, a texture-transform cell grid, a bare triangle.  They belong in a
    conformance run and they are noise on a shelf somebody is browsing to find
    something worth looking at, so the table says which is which and every tool
    reads it from there.
    """

    def test_the_flag_is_on_the_spec(self):
        assert gltf_demos.scene_for('Triangle').feature_test is True

    def test_a_real_demo_is_not_one(self):
        for name in ('DamagedHelmet', 'Sponza', 'BoomBox', 'FlightHelmet',
                     'AntiqueCamera', 'BrainStem', 'ToyCar'):
            assert gltf_demos.scene_for(name).feature_test is False, name

    def test_the_named_fixtures_are_marked(self):
        for name in ('Triangle', 'TriangleWithoutIndices', 'Box', 'BoxAnimated',
                     'BoxTextured', 'BoxVertexColors', 'BoxInterleaved',
                     'Cameras', 'Cube', 'CubeVisibility', 'AnimatedCube',
                     'AnimatedTriangle', 'AnimatedColorsCube',
                     'AnimatedMorphCube', 'AlphaBlendModeTest',
                     'DirectionalLight', 'InterpolationTest',
                     'MeshPrimitiveModes', 'MeshoptCubeTest',
                     'MorphPrimitivesTest', 'MultiUVTest', 'MultipleScenes',
                     'NodePerformanceTest', 'NormalTangentTest',
                     'NormalTangentMirrorTest', 'OrientationTest',
                     'PointLightIntensityTest', 'RiggedSimple', 'SimpleMeshes',
                     'SimpleMorph', 'SimpleSkin', 'SimpleSparseAccessor',
                     'SimpleTexture', 'TextureCoordinateTest',
                     'TextureEncodingTest', 'TextureLinearInterpolationTest',
                     'TextureSettingsTest', 'TextureTransformTest',
                     'TextureTransformMultiTest', 'TwoSidedPlane', 'UnlitTest',
                     'VertexColorTest', 'EmissiveStrengthTest',
                     'XmpMetadataRoundedCube'):
            assert gltf_demos.scene_for(name).feature_test is True, name

    def test_the_swept_parameter_grids_are_ones_too(self):
        """A ``*TestGrid`` is a reference to check a renderer against."""
        grids = [s for s in gltf_demos.iter_scenes()
                 if s.name.endswith('TestGrid')]
        assert grids
        for spec in grids:
            assert spec.feature_test is True, spec.name

    def test_the_smallest_case_of_a_thing_is_one(self):
        for name in ('SimpleMaterial', 'SimpleInstancing', 'NegativeScaleTest',
                     'PrimitiveModeNormalsTest', 'LightVisibility'):
            assert gltf_demos.scene_for(name).feature_test is True, name

    def test_every_comparison_grid_is_one(self):
        """The Compare* set is a side-by-side reference, not a scene."""
        compares = [s for s in gltf_demos.iter_scenes()
                    if s.name.startswith('Compare')]
        assert compares
        for spec in compares:
            assert spec.feature_test is True, spec.name

    def test_the_split_leaves_a_shelf_worth_browsing(self):
        demos = [s for s in gltf_demos.iter_scenes() if not s.feature_test]
        assert len(demos) > 50, 'too many marked; the shelf would be bare'
        tests = [s for s in gltf_demos.iter_scenes() if s.feature_test]
        assert len(tests) > 60, 'too few marked; the shelf stays full of fixtures'

    def test_the_roster_names_only_scenes_that_exist(self):
        """A typo would silently mark nothing, for ever."""
        known = {s.name for s in gltf_demos.iter_scenes()}
        assert set(gltf_demos.FEATURE_TEST_NAMES) <= known, \
            sorted(set(gltf_demos.FEATURE_TEST_NAMES) - known)
