"""Tests for meshdata: a geometry node's triangles as arrays, and a scene's merged

Each geometry family answers `meshArrays()` with glTF-shaped arrays in its own
frame; `merged_arrays` places every shape's arrays by the transforms above it.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes, meshdata


def triangles(arrays):
    """The arrays' triangles as corner positions, (N, 3, 3)"""
    positions = arrays.attributes['POSITION']
    corners = arrays.indices if arrays.indices is not None else np.arange(len(positions))
    return positions[np.asarray(corners).reshape(-1, 3)]


QUAD = basenodes.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)])


@pytest.mark.parametrize('geometry, count', [
    (basenodes.Box(size=(2, 2, 2)), 12),
    (basenodes.IndexedFaceSet(coord=QUAD, coordIndex=[0, 1, 2, 3, -1]), 2),
    (basenodes.IndexedTriangleSet(coord=QUAD, index=[0, 1, 2, 0, 2, 3]), 2),
    (basenodes.IndexedQuadSet(coord=QUAD, index=[0, 1, 2, 3]), 2),
    (basenodes.Rectangle2D(size=(2, 2)), 2),
])
def test_each_family_answers_its_triangles(geometry, count):
    found = meshdata.geometry_arrays(geometry)
    assert len(triangles(found)) == count
    assert len(found.attributes['NORMAL']) == len(found.attributes['POSITION'])


@pytest.mark.parametrize('geometry', [
    basenodes.Sphere(radius=2), basenodes.Cone(), basenodes.Cylinder(),
    basenodes.Extrusion(), basenodes.ElevationGrid(
        xDimension=2, zDimension=2, height=[0, 0, 0, 0]),
    basenodes.Teapot(),
    basenodes.NurbsSurface(
        controlPoint=[(u, v, 0.0) for v in range(4) for u in range(4)],
        uDimension=4, vDimension=4, uKnot=[0, 0, 0, 0, 1, 1, 1, 1],
        vKnot=[0, 0, 0, 0, 1, 1, 1, 1], uOrder=4, vOrder=4),
])
def test_the_curved_and_swept_ones_have_triangles(geometry):
    found = meshdata.geometry_arrays(geometry)
    assert found is not None and len(triangles(found)) >= 2


def test_a_sphere_is_its_radius_out():
    found = meshdata.geometry_arrays(basenodes.Sphere(radius=2))
    distance = np.linalg.norm(found.attributes['POSITION'], axis=1)
    assert np.allclose(distance, 2, atol=1e-4)


def test_lines_and_text_have_no_triangles():
    assert meshdata.geometry_arrays(basenodes.IndexedLineSet(coord=QUAD, coordIndex=[0, 1])) is None
    assert meshdata.geometry_arrays(basenodes.Text(string=['a'])) is None


def test_a_shapes_triangles_are_placed_by_its_transforms():
    shape = basenodes.Shape(geometry=basenodes.IndexedTriangleSet(coord=QUAD, index=[0, 1, 2]))
    turned = basenodes.Transform(translation=(10, 0, 0), rotation=(0, 1, 0, np.pi / 2),
                                 children=[shape])
    found = meshdata.merged_arrays([basenodes.Group(children=[turned])])
    positions = triangles(found).reshape(-1, 3)
    assert np.allclose(positions[:, 0], 10, atol=1e-5)
    assert np.allclose(found.attributes['NORMAL'][found.indices], (1, 0, 0), atol=1e-5)


def test_a_scaled_shapes_normals_stay_unit_length():
    shape = basenodes.Shape(geometry=basenodes.Sphere())
    found = meshdata.merged_arrays([basenodes.Transform(scale=(4, 1, 1), children=[shape])])
    assert np.allclose(np.linalg.norm(found.attributes['NORMAL'], axis=1), 1, atol=1e-5)


def test_shapes_merge_with_the_attributes_they_share():
    """A set with colours beside one without: the other is white"""
    coloured = basenodes.Shape(geometry=basenodes.IndexedTriangleSet(
        coord=QUAD, index=[0, 1, 2], color=basenodes.Color(color=[(1, 0, 0)] * 4)))
    plain = basenodes.Shape(geometry=basenodes.Box())
    found = meshdata.merged_arrays([coloured, plain])
    assert len(triangles(found)) == 13
    colours = found.attributes['COLOR_0']
    assert len(colours) == len(found.attributes['POSITION'])
    assert np.allclose(colours[-1, :3], 1)


def test_a_scene_with_no_triangles_merges_to_nothing():
    assert meshdata.merged_arrays([basenodes.Group()]) is None


def test_flat_normals_are_each_triangles_own():
    found = meshdata.flattened(meshdata.geometry_arrays(basenodes.Sphere()))
    corners = triangles(found)
    normals = found.attributes['NORMAL'].reshape(-1, 3, 3)
    assert np.allclose(normals[:, 0], normals[:, 1]) and np.allclose(normals[:, 1], normals[:, 2])
    faces = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    assert (np.einsum('ij,ij->i', faces, normals[:, 0]) > 0).all()
