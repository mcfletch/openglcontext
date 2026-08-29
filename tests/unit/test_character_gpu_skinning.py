"""Skinning in the vertex shader, against the CPU deform it replaces.

Against a real driver. The CPU deform is the definition of where a skinned
vertex goes -- it is what every reference image was made with -- so what the
shader has to do is put the figure in the same place: the test renders one
posed figure each way and compares the frames, and separately compares the
joint palette the shader is handed with the matrices the CPU deform applies.
"""
import os
import subprocess
import sys

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from OpenGLContext.testing.paths import tests_root
from tests.unit._character_assets import skinned_bar_glb

TESTS_DIR = str(tests_root(__file__))
HARNESS = os.path.join(TESTS_DIR, 'helpers', '_skinning_harness.py')


def _run(*args, env=None):
    environ = dict(os.environ)
    environ.update(env or {})
    result = subprocess.run(
        [sys.executable, HARNESS, *args], capture_output=True, text=True,
        env=environ, timeout=300)
    if result.returncode != 0:
        raise AssertionError('harness failed:\n%s\n%s'
                             % (result.stdout[-4000:], result.stderr[-4000:]))
    return result.stdout


# -- what the palette holds (no GL) ----------------------------------------

class TestPaletteLayout:
    def test_a_matrix_is_four_rows_of_four_floats(self):
        from OpenGLContext.scenegraph.skinning import MATRIX_FLOATS

        assert MATRIX_FLOATS == 16

    def test_the_palette_unit_is_clear_of_every_material_sampler(self):
        """The palette is bound once and left there, so its unit has to be one
        nothing else in a frame touches."""
        from OpenGLContext.passes.pbrpass import PBR_EXT_UNITS, PBR_UNITS
        from OpenGLContext.passes.ibl import IBL_UNITS
        from OpenGLContext.scenegraph.skinning import SKIN_PALETTE_UNIT

        used = set(PBR_UNITS.values()) | set(PBR_EXT_UNITS.values()) \
            | set(IBL_UNITS.values())

        assert SKIN_PALETTE_UNIT > max(used)


class TestMeshState:
    def test_a_gpu_skinned_mesh_keeps_its_rest_pose_in_its_buffers(self):
        """The point of the shader path: the vertex arrays never change, so
        nothing is re-uploaded per frame."""
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh

        mesh = PBRMesh(positions=np.array([[0, 1, 0], [0, -1, 0]], 'f'),
                       normals=np.array([[0, 0, 1]] * 2, 'f'),
                       skin_joints=np.zeros((2, 4), 'u4'),
                       skin_weights=np.array([[1, 0, 0, 0]] * 2, 'f'))
        rest = mesh.positions.copy()

        mesh.set_skin_matrices(np.tile(np.eye(4) * 2.0, (1, 1, 1)))

        assert mesh.skin_on_gpu
        assert not mesh.deforms_vertices
        assert np.allclose(mesh.positions, rest)

    def test_the_cpu_path_still_deforms_the_arrays(self):
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh

        mesh = PBRMesh(positions=np.array([[0, 1, 0], [0, -1, 0]], 'f'),
                       normals=np.array([[0, 0, 1]] * 2, 'f'),
                       skin_joints=np.zeros((2, 4), 'u4'),
                       skin_weights=np.array([[1, 0, 0, 0]] * 2, 'f'))
        mesh.skin_on_gpu = False
        matrix = np.eye(4)
        matrix[3, :3] = (5.0, 0.0, 0.0)

        mesh.set_skin_matrices(matrix.reshape(1, 4, 4))

        assert mesh.deforms_vertices
        assert np.allclose(mesh.positions[:, 0], 5.0)


# -- against a real driver --------------------------------------------------

class TestAgainstTheDriver:
    def test_the_shader_puts_the_figure_where_the_cpu_deform_does(self, tmp_path):
        """One posed figure, rendered both ways, has to come out the same."""
        model = tmp_path / 'figure.glb'
        model.write_bytes(skinned_bar_glb())
        out = _run('compare', str(model), str(tmp_path))

        report = dict(line.split('=', 1) for line in out.strip().split('\n')
                      if '=' in line)

        assert report['skinning_supported'] == '1'
        assert report['skin_on_gpu'] == '1'
        assert float(report['differing_fraction']) < 0.005, out
        assert report['moved'] == '1', 'the pose did not move the figure at all'

    def test_the_vertex_buffers_are_never_re_uploaded(self, tmp_path):
        """A skinned figure animating for many frames uploads its matrices and
        nothing else; the megabytes of deformed vertices stay at home."""
        model = tmp_path / 'figure.glb'
        model.write_bytes(skinned_bar_glb())
        out = _run('uploads', str(model), str(tmp_path))

        report = dict(line.split('=', 1) for line in out.strip().split('\n')
                      if '=' in line)

        assert report['skin_on_gpu'] == '1'
        assert int(report['vertex_uploads']) == 0, out
        assert int(report['palette_writes']) > 0


class TestComposingSkeletonsOnTheGPU:
    """The compute path against the numpy one it replaces.

    The numpy path is the definition of where a joint ends up, so what the
    compute shader has to do is agree with it -- over a rig deep enough that
    the walk to the root is a real walk, and figures at different points in
    their clips so no two skeletons are alike.
    """

    def _report(self, model, tmp_path):
        path = tmp_path / 'rig.glb'
        path.write_bytes(model)
        out = _run('compute', str(path), str(tmp_path))
        return dict(line.split('=', 1) for line in out.strip().split('\n')
                    if '=' in line)

    def test_the_palettes_match_the_numpy_ones(self, tmp_path):
        from tests.helpers._crowd_asset import crowd_character_glb

        report = self._report(crowd_character_glb(joints=57, vertices=512),
                              tmp_path)

        assert report['compute_available'] == '1'
        assert report['compute_ran'] == '1'
        assert int(report['matrices_checked']) >= 57 * 4
        # Single precision is what the palette is stored in either way, so that
        # is as close as the two can be asked to come.
        assert float(report['worst_difference']) < 1e-5, report

    def test_a_shallow_rig_agrees_too(self, tmp_path):
        report = self._report(skinned_bar_glb(), tmp_path)

        assert report['compute_ran'] == '1'
        assert float(report['worst_difference']) < 1e-5, report


class TestTheProcessorPathCanStillBeChosen:
    def test_turning_the_shader_path_off_reaches_a_mesh_that_would_batch(
            self, tmp_path):
        """Where a mesh is skinned has to be settled before it is batched.

        A mesh drawn in an instanced batch has no draw of its own to settle it
        in, so settling it at its first draw settles it never -- and the
        renderer goes on skinning in the shader whatever it was asked for,
        which would leave a driver that cannot skin there drawing rest poses.
        """
        from tests.helpers._crowd_asset import crowd_character_glb

        path = tmp_path / 'rig.glb'
        path.write_bytes(crowd_character_glb(joints=12, vertices=256))
        out = _run('fallback', str(path), str(tmp_path))
        report = dict(line.split('=', 1) for line in out.strip().split('\n')
                      if '=' in line)

        assert int(report['meshes']) >= 1
        assert report['skin_on_gpu'] == '0', 'the option was not honoured'
        assert report['deforms_vertices'] == '1'
        assert report['moved'] == '1', 'the processor path posed nothing'


class TestBlendingClipsOnTheGPU:
    """The compute blend against the numpy one it replaces.

    The numpy blend is the definition of the pose -- a weighted mean, the
    shortfall taken from where the joint rests -- so what the shader has to do
    is arrive at the same place: over a fifty-seven bone rig, figures on
    different clips at different points, and a cross-fade with the two clips at
    unequal weights.
    """

    def _report(self, tracks, tmp_path, interpolation='LINEAR', equipped=0,
                masked=0):
        from tests.helpers._crowd_asset import crowd_character_glb

        path = tmp_path / 'rig.glb'
        path.write_bytes(crowd_character_glb(
            joints=57, vertices=256, clips=6, interpolation=interpolation))
        out = _run('blend', str(path), str(tmp_path),
                   env={'BLEND_TRACKS': str(tracks),
                        'BLEND_EQUIPPED': str(equipped),
                        'BLEND_MASKED': str(masked)})
        return dict(line.split('=', 1) for line in out.strip().split('\n')
                    if '=' in line)

    @pytest.mark.parametrize('tracks', [1, 2])
    def test_a_layer_masked_to_part_of_the_body_matches_too(self, tracks,
                                                            tmp_path):
        """A figure firing while it runs: the upper layer moves the joints it
        is masked to and leaves the rest doing what the layer below says."""
        report = self._report(tracks, tmp_path, masked=30)

        assert report['blend_ran'] == '1'
        for path in ('translation', 'rotation', 'scale'):
            assert float(report['worst_%s' % path]) < 1e-5, (path, report)

    @pytest.mark.parametrize('interpolation', ['LINEAR', 'CUBICSPLINE'])
    @pytest.mark.parametrize('tracks', [1, 2])
    def test_the_pose_matches_the_numpy_one(self, tracks, interpolation,
                                            tmp_path):
        report = self._report(tracks, tmp_path, interpolation)

        assert report['blend_ran'] == '1'
        assert int(report['joints_checked']) >= 57 * 5
        for path in ('translation', 'rotation', 'scale'):
            # Single precision is what the pose is uploaded in, so that is as
            # close as the two can be asked to come.
            assert float(report['worst_%s' % path]) < 1e-5, (path, report)


class TestAFigureCarryingSomething:
    """A weapon on a hand must not push the whole figure back onto numpy.

    The scenegraph reaches what a figure is holding by walking to it, so that
    hand -- and the joints down to it -- have to say where the pose put them.
    That is a handful of joints, and a handful is worked out here while the
    skeleton stays on the GPU.
    """

    def _report(self, tmp_path, equipped, masked=0):
        from tests.helpers._crowd_asset import crowd_character_glb

        path = tmp_path / 'rig.glb'
        path.write_bytes(crowd_character_glb(joints=57, vertices=256, clips=6))
        out = _run('blend', str(path), str(tmp_path),
                   env={'BLEND_TRACKS': '2', 'BLEND_EQUIPPED': str(equipped),
                        'BLEND_MASKED': str(masked)})
        return dict(line.split('=', 1) for line in out.strip().split('\n')
                    if '=' in line)

    def test_it_keeps_the_gpu_blend(self, tmp_path):
        report = self._report(tmp_path, equipped=40)

        assert report['blend_ran'] == '1'
        assert int(report['writable']) > 0, 'nothing was hung on a joint'

    def test_the_joints_it_writes_are_where_the_whole_blend_puts_them(
            self, tmp_path):
        report = self._report(tmp_path, equipped=40)

        assert int(report['written_joints']) > 0
        # The scenegraph holds these in single precision, so that is as close
        # as the two can be asked to come.
        assert float(report['worst_written']) < 1e-5, report

    def test_a_figure_carrying_nothing_writes_no_joints(self, tmp_path):
        report = self._report(tmp_path, equipped=0)

        assert report['writable'] == '0'
        assert report['written_joints'] == '0'

    def test_a_masked_layer_reaches_the_joints_it_writes(self, tmp_path):
        """The joints written here are worked out from a few of the skeleton,
        and a layer masked to part of the body has to be honoured in that
        narrowed run exactly as it is in the whole one."""
        report = self._report(tmp_path, equipped=40, masked=30)

        assert report['blend_ran'] == '1'
        assert int(report['written_joints']) > 0
        assert float(report['worst_written']) < 1e-5, report


class TestShadowsFollowThePose:
    """A batched crowd casts the shadows a per-shape one does.

    Collapsing figures into one instanced draw is meant to change nothing
    about the picture. The depth pass batches as well as the colour pass, so
    it too has to hand each instance the range of the joint palette its own
    pose is in -- otherwise the bodies move and their shadows stand still in
    the pose the model was built in.
    """

    def test_a_batched_field_and_a_per_shape_one_draw_the_same_frame(
            self, tmp_path):
        model = tmp_path / 'figure.glb'
        model.write_bytes(skinned_bar_glb())
        out = _run('shadows', str(model), str(tmp_path))

        report = dict(line.split('=', 1) for line in out.strip().split('\n')
                      if '=' in line)

        assert int(report['instanced']) >= 2, (
            'nothing batched, so the batched path was never exercised: %s' % out)
        assert float(report['shadowed_fraction']) > 0.02, (
            'no shadow in the frame to disagree about: %s' % out)
        assert float(report['differing_fraction']) < 0.005, out
