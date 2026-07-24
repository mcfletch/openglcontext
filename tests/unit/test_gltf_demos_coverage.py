"""Coverage tests for the small derivation helpers on the demo metadata table."""
from OpenGLContext.loaders import gltf_demos
from OpenGLContext.loaders.gltf_demos import SceneSpec


class TestYawAndEnvHelpers:
    def test_yaw_for_reads_scene_spec_yaw(self):
        # DamagedHelmet carries a non-zero facing yaw in the table.
        assert gltf_demos.yaw_for('DamagedHelmet') == gltf_demos.scene_for('DamagedHelmet').yaw
        # An unlisted model uses the default (0.0) yaw.
        assert gltf_demos.yaw_for('NoSuchModelXYZ') == 0.0

    def test_needs_env_background_matches_roster(self):
        assert gltf_demos.needs_env_background('MetalRoughSpheres') is True
        assert gltf_demos.needs_env_background('NoSuchModelXYZ') is False


class TestFindParthenonMissing:
    def test_returns_none_when_no_build_present(self, tmp_path):
        # An empty start dir has no sibling parthenon .glb -> None (not a raise).
        assert gltf_demos.find_parthenon(start=str(tmp_path)) is None


class TestResolveSourceLocalPath:
    def test_non_sentinel_source_is_treated_as_local(self):
        spec = SceneSpec('Custom', source='/models/custom.glb')
        src, is_local = gltf_demos.resolve_source(spec)
        assert src == '/models/custom.glb' and is_local is True
