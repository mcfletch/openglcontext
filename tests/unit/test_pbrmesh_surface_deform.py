"""Per-frame surface deformation: geometry and UVs that move under a material.

`PBRMesh` already deforms for morph targets and skinning, which are the mesh's
*own* animation. This is the other kind: a **material** that says its surface
moves -- a Quake water shader's `deformVertexes`, a `tcMod turb` churn -- where
the movement belongs to what is painted on the geometry rather than to the
geometry itself.

It rides the same pipeline, which is the point: base arrays, a version counter,
and the dynamic VBO re-upload that morph and skin already use.
"""

import numpy as np

from OpenGLContext.scenegraph.pbrmesh import PBRMesh


def grid(count=4):
    """A flat strip of vertices with normals up and UVs across."""
    positions = np.zeros((count, 3), dtype='f')
    positions[:, 0] = np.arange(count)
    normals = np.tile((0.0, 1.0, 0.0), (count, 1)).astype('f')
    texcoords = np.zeros((count, 2), dtype='f')
    texcoords[:, 0] = np.linspace(0.0, 1.0, count)
    return PBRMesh(positions=positions, normals=normals, texcoords=texcoords)


def lift(height):
    """A deformer that raises every vertex by ``height``."""
    def deform(positions, normals, texcoords):
        moved = positions.copy()
        moved[:, 1] += height
        return moved, normals, texcoords
    return deform


class TestSettingADeformer:
    def test_a_plain_mesh_is_not_deformable(self):
        assert not grid().is_deformable

    def test_setting_a_deformer_makes_it_deformable(self):
        mesh = grid()
        mesh.set_surface_deformer(lift(1.0))
        assert mesh.is_deformable

    def test_setting_a_deformer_applies_it_at_once(self):
        mesh = grid()
        mesh.set_surface_deformer(lift(2.0))
        assert np.allclose(mesh.positions[:, 1], 2.0)

    def test_clearing_the_deformer_restores_the_rest_pose(self):
        mesh = grid()
        rest = mesh.positions.copy()
        mesh.set_surface_deformer(lift(3.0))
        mesh.set_surface_deformer(None)
        assert np.allclose(mesh.positions, rest)
        assert not mesh.is_deformable

    def test_the_rest_pose_is_kept_rather_than_accumulated(self):
        """Two frames of a 1-unit lift is a 1-unit lift, not a 2-unit one."""
        mesh = grid()
        mesh.set_surface_deformer(lift(1.0))
        mesh.refresh_surface()
        mesh.refresh_surface()
        assert np.allclose(mesh.positions[:, 1], 1.0)

    def test_refreshing_re_runs_the_deformer(self):
        """A deformer that reads a clock is re-read, not remembered."""
        mesh = grid()
        state = {'height': 1.0}

        def deform(positions, normals, texcoords):
            moved = positions.copy()
            moved[:, 1] += state['height']
            return moved, normals, texcoords

        mesh.set_surface_deformer(deform)
        state['height'] = 5.0
        mesh.refresh_surface()
        assert np.allclose(mesh.positions[:, 1], 5.0)

    def test_refreshing_without_a_deformer_is_harmless(self):
        mesh = grid()
        rest = mesh.positions.copy()
        mesh.refresh_surface()
        assert np.allclose(mesh.positions, rest)


class TestWhatADeformerMayChange:
    def test_it_may_move_the_normals(self):
        def bend(positions, normals, texcoords):
            return positions, np.tile((1.0, 0.0, 0.0), (len(normals), 1)), texcoords

        mesh = grid()
        mesh.set_surface_deformer(bend)
        assert np.allclose(mesh.normals[:, 0], 1.0)

    def test_normals_are_renormalised(self):
        """A deformer may return any length; the shader wants unit normals."""
        def stretch(positions, normals, texcoords):
            return positions, normals * 7.0, texcoords

        mesh = grid()
        mesh.set_surface_deformer(stretch)
        assert np.allclose(np.linalg.norm(mesh.normals, axis=1), 1.0)

    def test_it_may_move_the_texture_coordinates(self):
        def slide(positions, normals, texcoords):
            return positions, normals, texcoords + 0.25

        mesh = grid()
        base = mesh.texcoords.copy()
        mesh.set_surface_deformer(slide)
        assert np.allclose(mesh.texcoords, base + 0.25)

    def test_a_mesh_with_no_texcoords_is_still_deformable(self):
        mesh = PBRMesh(positions=np.zeros((3, 3), dtype='f'),
                       normals=np.tile((0.0, 1.0, 0.0), (3, 1)).astype('f'))
        mesh.set_surface_deformer(lift(1.0))
        assert np.allclose(mesh.positions[:, 1], 1.0)

    def test_a_deformer_that_returns_nothing_leaves_the_mesh_alone(self):
        """Content is not always well formed; a bad deformer costs an effect."""
        mesh = grid()
        rest = mesh.positions.copy()
        mesh.set_surface_deformer(lambda p, n, t: None)
        assert np.allclose(mesh.positions, rest)


class TestVersioning:
    def test_deforming_bumps_the_version_so_the_gpu_re_uploads(self):
        mesh = grid()
        before = mesh._deform_version
        mesh.set_surface_deformer(lift(1.0))
        assert mesh._deform_version > before

    def test_every_refresh_bumps_it_again(self):
        mesh = grid()
        mesh.set_surface_deformer(lift(1.0))
        before = mesh._deform_version
        mesh.refresh_surface()
        assert mesh._deform_version > before

    def test_the_bounding_volume_follows_the_deformed_positions(self):
        mesh = grid()
        mesh.set_surface_deformer(lift(10.0))
        points = mesh.boundingVolume().getPoints()
        assert float(np.asarray(points)[:, 1].max()) > 5.0


class TestComposingWithMorphAndSkin:
    """A material's deform runs last, on whatever the mesh's own animation left."""

    def test_it_runs_after_a_morph(self):
        target = {'positions': np.tile((0.0, 5.0, 0.0), (4, 1)).astype('f')}
        mesh = PBRMesh(positions=np.zeros((4, 3), dtype='f'),
                       normals=np.tile((0.0, 1.0, 0.0), (4, 1)).astype('f'),
                       morph_targets=[target])
        mesh.set_morph_weights([1.0])
        mesh.set_surface_deformer(lift(1.0))
        assert np.allclose(mesh.positions[:, 1], 6.0)

    def test_a_later_morph_still_includes_the_surface_deform(self):
        target = {'positions': np.tile((0.0, 5.0, 0.0), (4, 1)).astype('f')}
        mesh = PBRMesh(positions=np.zeros((4, 3), dtype='f'),
                       normals=np.tile((0.0, 1.0, 0.0), (4, 1)).astype('f'),
                       morph_targets=[target])
        mesh.set_surface_deformer(lift(1.0))
        mesh.set_morph_weights([1.0])
        assert np.allclose(mesh.positions[:, 1], 6.0)


class TestTexcoordUpload:
    """A mesh whose UVs move has to say so before its GPU buffers are built."""

    def test_a_plain_mesh_does_not_ask_for_dynamic_texcoords(self):
        assert not grid().deforms_texcoords

    def test_a_surface_deformer_asks_for_them(self):
        mesh = grid()
        mesh.set_surface_deformer(lift(1.0))
        assert mesh.deforms_texcoords

    def test_a_morphed_mesh_does_not(self):
        """Skinning and morphing never move UVs; re-uploading them is waste."""
        target = {'positions': np.zeros((4, 3), dtype='f')}
        mesh = PBRMesh(positions=np.zeros((4, 3), dtype='f'),
                       normals=np.tile((0.0, 1.0, 0.0), (4, 1)).astype('f'),
                       texcoords=np.zeros((4, 2), dtype='f'),
                       morph_targets=[target])
        assert not mesh.deforms_texcoords


def test_a_deformer_sees_the_rest_pose_not_the_last_frame():
    """Otherwise a wave would walk the surface away over a few seconds."""
    seen = []

    def record(positions, normals, texcoords):
        seen.append(positions.copy())
        moved = positions.copy()
        moved[:, 1] += 1.0
        return moved, normals, texcoords

    mesh = grid()
    mesh.set_surface_deformer(record)
    mesh.refresh_surface()
    assert np.allclose(seen[0], seen[1])


def test_the_deformer_may_not_write_through_to_the_rest_pose():
    """A deformer handed the base arrays could corrupt them by writing in place."""
    def vandal(positions, normals, texcoords):
        positions += 100.0
        return positions, normals, texcoords

    mesh = grid()
    mesh.set_surface_deformer(vandal)
    first = mesh.positions.copy()
    mesh.refresh_surface()
    assert np.allclose(mesh.positions, first)
