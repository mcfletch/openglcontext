"""A mesh simulated as a soft body: the weld, the write by version, and the buffers written in place."""
import numpy as np
import pytest

from OpenGLContext.physics.proxy import Proxy
from OpenGLContext.physics.service import Physics
from OpenGLContext.physics.settings import PhysicsDefinition
from OpenGLContext.physics.softbodies import SoftBodySpec
from OpenGLContext.physics.softmesh import transport_tangents, weld
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


def make() -> Physics:
    physics = Physics(PhysicsDefinition(mode='inline', engine='jolt', tickHz=60.0))
    physics.add_static(None, proxy=Proxy.box((40.0, 1.0, 40.0)), translation=(0.0, -0.5, 0.0))
    return physics


def run_for(physics: Physics, seconds: float) -> None:
    for _ in range(int(round(seconds * 60))):
        physics.frame(1.0 / 60.0)


def seamed_cloth(size: float = 1.0, side: int = 9) -> PBRMesh:
    """A cloth mesh whose middle column of vertices is split, as a texture seam splits it."""
    grid = SoftBodySpec.cloth(size, size, side, side)
    positions = list(grid.positions)
    faces = grid.faces.copy()
    middle = side // 2
    copies = {}
    for row in range(side):
        vertex = row * side + middle
        copies[vertex] = len(positions)
        positions.append(grid.positions[vertex])
    # The faces right of the seam use the copies.
    for face in faces:
        if all(grid.positions[v][0] >= grid.positions[middle][0] - 1e-9 for v in face):
            face[:] = [copies.get(int(v), int(v)) for v in face]
    positions = np.array(positions)
    texcoords = positions[:, [0, 2]] + 0.5
    normals = np.tile([0.0, 1.0, 0.0], (len(positions), 1))
    return PBRMesh(positions=positions, normals=normals, texcoords=texcoords,
                   indices=faces.ravel())


def test_weld_joins_the_vertices_a_seam_splits():
    mesh = seamed_cloth(side=9)
    points, index = weld(mesh.positions)
    assert len(mesh.positions) == 81 + 9 and len(points) == 81
    assert np.allclose(points[index], mesh.positions)
    assert np.array_equal(index[:81], np.arange(81))       # the first vertex at a place numbers it
    empty, nothing = weld(np.zeros((0, 3)))
    assert len(empty) == 0 and len(nothing) == 0


def test_a_seamed_cloth_hangs_whole_and_its_copies_move_together():
    physics = make()
    try:
        mesh = seamed_cloth()
        side = 9
        corners = [0, side - 1]
        pins = mesh.positions[corners].astype('d') + (0.0, 2.0, 0.0)
        soft = physics.add_soft_mesh(mesh, position=(0.0, 2.0, 0.0), pins=(corners, pins),
                                     mass=0.4, linear_damping=2.0)
        assert len(soft.soft.spec) == 81
        assert mesh.origin == pytest.approx((0.0, 2.0, 0.0))
        run_for(physics, 3.0)
        world = mesh.positions.astype('d') + mesh.origin
        assert np.abs(world[corners] - pins).max() < 2e-3
        assert world[:, 1].min() < 1.3
        # A vertex and its copy across the seam are the same particle.
        middle = side // 2
        assert np.array_equal(mesh.positions[middle], mesh.positions[81])
        assert np.linalg.norm(mesh.normals, axis=1) == pytest.approx(1.0, abs=1e-3)
        assert physics.deformable_costs()['soft bodies draw ms'] > 0.0
    finally:
        physics.close()


def test_a_still_cloth_is_written_once_and_a_moving_one_each_step():
    physics = make()
    try:
        mesh = PBRMesh(positions=SoftBodySpec.cloth(1.0, 1.0, 7, 7).positions,
                       indices=SoftBodySpec.cloth(1.0, 1.0, 7, 7).faces.ravel())
        soft = physics.add_soft_mesh(mesh, position=(0.0, 0.2, 0.0), mass=0.3,
                                     linear_damping=2.0, friction=0.8)
        assert mesh.normals is None
        version = mesh.deform_version
        assert physics.frame(1 / 60) and soft.writes == 1 and mesh.deform_version == version + 1
        assert mesh.normals is not None
        run_for(physics, 10.0)
        writes = soft.writes
        assert not physics.frame(1 / 60)
        run_for(physics, 0.5)
        assert soft.writes == writes
        soft.soft.set_wind((0.0, 0.0, 2.0))
        run_for(physics, 0.2)
        assert soft.writes > writes
    finally:
        physics.close()


def test_pins_name_the_meshs_own_vertices():
    physics = make()
    try:
        mesh = seamed_cloth()
        soft = physics.add_soft_mesh(mesh, position=(0.0, 2.0, 0.0), mass=0.4)
        copy = 81 + 3           # the seam copy on row 3
        soft.pin([copy], [(0.0, 3.0, 0.0)])
        run_for(physics, 1.0)
        world = mesh.positions.astype('d') + mesh.origin
        assert world[copy] == pytest.approx((0.0, 3.0, 0.0), abs=2e-3)
        soft.remove()
        run_for(physics, 0.1)
        assert not soft.soft.alive
        frozen = mesh.positions.copy()
        run_for(physics, 0.5)
        assert np.array_equal(mesh.positions, frozen)
    finally:
        physics.close()


def tangent_cloth(side: int = 21) -> PBRMesh:
    """A 2 m cloth with texture coordinates and tangents along +x, as a normal-mapped one has"""
    grid = SoftBodySpec.cloth(2.0, 2.0, side, side)
    positions = np.asarray(grid.positions, dtype='d')
    return PBRMesh(positions=positions, normals=np.tile([0.0, 1.0, 0.0], (len(positions), 1)),
                   texcoords=positions[:, [0, 2]] + 0.5,
                   tangents=np.tile([1.0, 0.0, 0.0, -1.0], (len(positions), 1)),
                   indices=grid.faces.ravel())


def test_a_draped_cloths_tangents_turn_with_its_normals():
    physics = make()
    try:
        physics.add_static(None, proxy=Proxy.box((0.6, 0.6, 0.6)), translation=(0.0, 0.3, 0.0))
        mesh = tangent_cloth()
        physics.add_soft_mesh(mesh, position=(0.0, 1.2, 0.0), rotation=(0.0, 0.0, 0.0, 1.0))
        run_for(physics, 4.0)
        normals = np.asarray(mesh.normals, dtype='d')
        normals /= np.linalg.norm(normals, axis=1, keepdims=True)
        assert (np.abs(normals[:, 1]) < 0.7).sum() > 100          # the cloth has folded
        tangents = np.asarray(mesh.tangents, dtype='d')
        assert np.abs(np.sum(tangents[:, :3] * normals, axis=1)).max() < 1e-3
        assert np.linalg.norm(tangents[:, :3], axis=1) == pytest.approx(1.0, abs=1e-4)
        assert np.array_equal(tangents[:, 3], np.full(len(tangents), -1.0))
        # Over the top of the box the cloth lies flat, and the tangent is the rest one.
        flat = normals[:, 1] > 0.9999
        assert flat.any() and np.allclose(tangents[flat, :3], (1.0, 0.0, 0.0), atol=0.02)
    finally:
        physics.close()


def test_a_tangent_turns_by_the_least_rotation_of_its_normal():
    up, tangent = (0.0, 1.0, 0.0), (1.0, 0.0, 0.0, 1.0)
    quarter = transport_tangents([up], [(1.0, 0.0, 0.0)], [tangent])
    assert quarter == pytest.approx(np.array([[0.0, -1.0, 0.0, 1.0]]), abs=1e-12)
    unturned = transport_tangents([up], [(0.0, 0.0, 1.0)], [tangent])
    assert unturned == pytest.approx(np.array([[1.0, 0.0, 0.0, 1.0]]), abs=1e-12)
    # Turned right over, or with nothing square to the normal left, a tangent is still made.
    for normal, given in (((0.0, -1.0, 0.0), tangent), ((0.0, -1.0, 0.0), (0.0, 1.0, 0.0, -1.0)),
                          ((0.0, 2.0, 0.0), (0.0, 1.0, 0.0, 1.0))):
        found = transport_tangents([up], [normal], [given])[0]
        assert abs(float(np.dot(found[:3], normal))) < 1e-12
        assert float(np.linalg.norm(found[:3])) == pytest.approx(1.0)
        assert found[3] == given[3]


def test_a_rotated_cloths_tangents_start_rotated():
    physics = make()
    try:
        mesh = tangent_cloth(side=5)
        quarter = (0.0, 0.0, float(np.sin(np.pi / 4)), float(np.cos(np.pi / 4)))
        physics.add_soft_mesh(mesh, position=(0.0, 3.0, 0.0), rotation=quarter)
        assert np.allclose(mesh.normals, (-1.0, 0.0, 0.0), atol=1e-6)
        assert np.allclose(mesh.tangents, (0.0, 1.0, 0.0, -1.0), atol=1e-6)
    finally:
        physics.close()


def test_a_mesh_simulated_again_starts_from_its_authored_rest_pose():
    """A mesh's first soft body writes its arrays; the next is made from the authored vertices"""
    quarter = (0.0, 0.0, float(np.sin(np.pi / 4)), float(np.cos(np.pi / 4)))
    mesh = tangent_cloth(side=5)
    authored = np.array(mesh.positions, dtype='d')
    for _ in range(2):
        physics = make()
        try:
            soft = physics.add_soft_mesh(mesh, position=(0.0, 3.0, 0.0), rotation=quarter)
            world = mesh.positions.astype('d') + mesh.origin
            turned = np.column_stack([-authored[:, 1], authored[:, 0], authored[:, 2]])
            assert world == pytest.approx(turned + (0.0, 3.0, 0.0), abs=1e-5)
            run_for(physics, 0.5)
            soft.remove()
        finally:
            physics.close()


def test_what_is_not_a_triangle_mesh_is_refused():
    physics = make()
    try:
        with pytest.raises(TypeError, match='PBRMesh'):
            physics.add_soft_mesh(object())
        with pytest.raises(ValueError, match='positions'):
            physics.add_soft_mesh(PBRMesh())
        with pytest.raises(ValueError, match='triangles'):
            physics.add_soft_mesh(PBRMesh(positions=np.zeros((4, 3))))
        mesh = PBRMesh(positions=np.zeros((3, 3)))
        with pytest.raises(ValueError, match='no positions'):
            PBRMesh().set_vertices(np.zeros((3, 3)))
        mesh.set_vertices(np.ones((3, 3)))
        assert mesh.deforms_vertices and mesh.is_deformable
    finally:
        physics.close()


def test_a_shape_drawing_a_mesh_is_taken():
    from OpenGLContext.scenegraph.basenodes import Shape
    physics = make()
    try:
        mesh = seamed_cloth()
        soft = physics.add_soft_mesh(Shape(geometry=mesh), position=(0.0, 1.0, 0.0))
        assert soft.mesh is mesh
    finally:
        physics.close()


def test_writing_moved_vertices_fills_the_buffers_and_makes_none(scene_context):
    """The buffers of a mesh a simulation moves are written in place: no buffer is made again."""
    from OpenGLContext.scenegraph.basenodes import Shape
    from OpenGLContext.testing.stillframe import check_still_frame, still_frame_work
    cloth = SoftBodySpec.cloth(1.0, 1.0, 9, 9)
    mesh = PBRMesh(positions=cloth.positions, indices=cloth.faces.ravel(),
                   normals=np.tile([0.0, 1.0, 0.0], (81, 1)))
    mesh.set_vertices(cloth.positions, origin=(0.0, 0.0, -3.0))
    with scene_context([Shape(geometry=mesh)]) as context:
        step = [0.0]

        def moving():
            step[0] += 0.01
            mesh.set_vertices(cloth.positions + (0.0, step[0], 0.0))
            context.OnDraw(force=1)

        work = still_frame_work(moving)
        assert work.allocations == 0
        assert work.uploads >= 1
        check_still_frame(lambda: context.OnDraw(force=1))


def test_the_frame_cost_of_cloths_grows_with_their_number(check_scaling):
    """A frame reads each soft mesh's vertices once, through one row table a snapshot.

    The count is the frames read and the row tables built in one physics
    frame: at four times the cloths it is four times the reads and still one table.
    """
    def prepare(count):
        physics = make()
        meshes = []
        for k in range(count):
            spec = SoftBodySpec.cloth(0.3, 0.3, 3, 3)
            mesh = PBRMesh(positions=spec.positions, indices=spec.faces.ravel())
            meshes.append(physics.add_soft_mesh(mesh, position=(k * 0.5, 0.5, 0.0)))
        from pyjoltphysics.softbodies import SoftBodyRows
        tables = []
        real = SoftBodyRows.rows

        def counted(rows):
            tables.append(1)
            return real(rows)

        def frame():
            tables.clear()
            reads = 0
            SoftBodyRows.rows = counted
            try:
                physics.frame(1 / 60)
                reads = sum(1 for one in meshes if one.soft.frame() is not None)
            finally:
                SoftBodyRows.rows = real
            assert len(tables) == 1
            return reads + len(tables)
        return frame
    check_scaling(prepare, n=8, most=4.2, measure='count')
