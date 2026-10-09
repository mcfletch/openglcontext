"""Box, Sphere, Cone and Cylinder drawn as the meshes their fields build.

Each primitive is a `PBRMesh` (`mesh(level)`) of the arrays it has always
been tessellated into, with tangents for a normal map; the quadrics have one
mesh per level of detail. A mesh is kept until a field it is built from is
set.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes, meshgeometry
from OpenGLContext.testing.memo import check_memo_inputs

PRIMITIVES = [
    (basenodes.Box, {'size': (1, 2, 3)}, ('size', (2, 2, 2))),
    (basenodes.Sphere, {'radius': 2.0}, ('radius', 3.0)),
    (basenodes.Cone, {'height': 2.0, 'bottomRadius': 1.0}, ('bottom', False)),
    (basenodes.Cylinder, {'height': 2.0, 'radius': 1.0}, ('top', False)),
]


@pytest.mark.parametrize('cls, fields, _edit', PRIMITIVES)
def test_a_primitive_is_drawn_as_a_mesh(cls, fields, _edit):
    found = cls(**fields)
    assert isinstance(found, meshgeometry.MeshDrawn)
    mesh = found.mesh()
    assert len(mesh.positions) and len(mesh.normals) == len(mesh.positions)
    assert mesh.texcoords is not None
    assert mesh.tangents is not None
    corners = (mesh.indices if mesh.indices is not None
               else np.arange(len(mesh.positions))).reshape(-1, 3)
    points = mesh.positions[corners]
    area = np.linalg.norm(np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0]),
                          axis=1)
    drawn = np.unique(corners[area > 1e-9])
    assert (np.linalg.norm(mesh.tangents[drawn, :3], axis=1) > 0.5).all()


@pytest.mark.parametrize('cls, fields, edit', PRIMITIVES)
def test_the_mesh_follows_its_fields(cls, fields, edit):
    found = cls(**fields)
    name, value = edit

    def answer(mesh):
        return (mesh.positions.tolist(), None if mesh.indices is None else mesh.indices.tolist())

    check_memo_inputs(lambda: answer(found.mesh()), [
        (name, lambda: setattr(found, name, value)),
    ], fresh=lambda: answer(found.buildMesh()))


@pytest.mark.parametrize('cls, fields, _edit', PRIMITIVES)
def test_solid_false_is_a_two_sided_mesh(cls, fields, _edit):
    assert cls(solid=False, **fields).mesh().solid is False


@pytest.mark.parametrize('cls', [basenodes.Sphere, basenodes.Cone, basenodes.Cylinder])
def test_a_quadric_has_a_coarser_mesh_further_off(cls):
    found = cls()
    near, far = found.mesh(0), found.mesh(3)
    assert len(far.positions) < len(near.positions)
    assert found.mesh(3) is far


def test_the_box_keeps_its_texture_faces():
    """The front face's (0, 0) is its lower left corner"""
    mesh = basenodes.Box(size=(2, 2, 2)).mesh()
    front = np.flatnonzero(np.isclose(mesh.normals[:, 2], 1.0))
    lower_left = [index for index in front
                  if np.allclose(mesh.positions[index], (-1, -1, 1))]
    assert np.allclose(mesh.texcoords[lower_left[0]], (0, 0))


@pytest.mark.parametrize('cls, fields, _edit', PRIMITIVES)
def test_its_triangles_are_its_meshs(cls, fields, _edit):
    found = cls(**fields)
    arrays = found.meshArrays()
    mesh = found.mesh()
    corners = len(mesh.indices) if mesh.indices is not None else len(mesh.positions)
    drawn = (len(arrays.indices) if arrays.indices is not None
             else len(arrays.attributes['POSITION']))
    assert drawn == corners
