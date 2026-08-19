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
