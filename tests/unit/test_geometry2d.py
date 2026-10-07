"""X3D's Geometry2D component: flat shapes in the z=0 plane.

Rectangle2D, TriangleSet2D, Disk2D and ArcClose2D are drawn as meshes facing
+z; Circle2D, Arc2D and Polyline2D as lines; Polypoint2D as points.
"""
import math

import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import composedgeometry as cg
from OpenGLContext.scenegraph import geometry2d
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.testing.scenes import drawn_image, scene_context


class TestTheShapes:
    def test_a_rectangle_is_two_triangles_of_its_size(self):
        points, triangles, texcoords = cg.rectangle((4.0, 2.0))
        assert np.allclose(points.min(axis=0), (-2, -1, 0))
        assert np.allclose(points.max(axis=0), (2, 1, 0))
        assert len(triangles) == 2
        assert np.allclose(texcoords.min(axis=0), (0, 0)) and np.allclose(texcoords.max(axis=0), (1, 1))

    def test_a_disk_without_a_hole_is_a_fan_round_its_centre(self):
        points, triangles, _texcoords = cg.disk(0.0, 1.0, 8)
        assert len(triangles) == 8
        assert np.allclose(np.linalg.norm(points[1:, :2], axis=1), 1.0)

    def test_a_ring_is_two_triangles_a_segment(self):
        points, triangles, _texcoords = cg.disk(0.5, 1.0, 8)
        assert len(triangles) == 16
        radii = np.linalg.norm(points[:, :2], axis=1)
        assert np.allclose(sorted(set(np.round(radii, 6))), (0.5, 1.0))

    def test_a_pie_closes_through_the_centre_and_a_chord_does_not(self):
        pie, pie_triangles, _ = cg.arc_close(1.0, 0.0, math.pi / 2, 'PIE', 4)
        chord, chord_triangles, _ = cg.arc_close(1.0, 0.0, math.pi / 2, 'CHORD', 4)
        assert np.allclose(pie[0], (0, 0, 0)) and len(pie_triangles) == 4
        assert len(chord_triangles) == 3

    def test_a_triangle_set_2d_textures_across_its_bounds(self):
        points, triangles, texcoords = cg.triangle_set_2d([(0, 0), (2, 0), (0, 4)])
        assert len(triangles) == 1
        assert np.allclose(texcoords, [(0, 0), (1, 0), (0, 1)])

    def test_an_arc_runs_from_start_to_end(self):
        points = cg.arc_points(2.0, 0.0, math.pi, 8)
        assert np.allclose(points[0], (2, 0, 0)) and np.allclose(points[-1], (-2, 0, 0), atol=1e-6)

    def test_a_circle_closes(self):
        points = cg.arc_points(1.0, 0.0, 2 * math.pi, 16)
        assert np.allclose(points[0], points[-1], atol=1e-6)

    @pytest.mark.parametrize('start, end, expected', [(0.0, 0.0, 2 * math.pi),
                                                      (1.0, 0.5, 2 * math.pi - 0.5)])
    def test_an_arcs_sweep_follows_x3d(self, start, end, expected):
        assert cg.arc_sweep(start, end) == pytest.approx(expected)


class TestTheNodes:
    def test_each_is_the_engines_in_a_document(self):
        found = prototypes()
        for name in ('Rectangle2D', 'TriangleSet2D', 'Disk2D', 'ArcClose2D', 'Circle2D',
                     'Arc2D', 'Polyline2D', 'Polypoint2D'):
            assert issubclass(found[name], x3d.CONCRETE_NODES[name]), name
            assert found[name].__module__ == geometry2d.__name__, name

    def test_a_rectangle_is_a_mesh_facing_z(self):
        mesh = geometry2d.Rectangle2D(size=(2, 2)).mesh()
        assert np.allclose(mesh.normals, (0, 0, 1))
        assert mesh.solid is False

    def test_a_circle_is_drawn_as_lines(self):
        lines = geometry2d.Circle2D(radius=2).drawn()
        assert len(lines.coord.point) > 8
        assert lines.coordIndex[-1] == -1

    def test_points_are_drawn_as_points(self):
        drawn = geometry2d.Polypoint2D(point=[(0, 0), (1, 1)]).drawn()
        assert np.allclose(drawn.coord.point, [(0, 0, 0), (1, 1, 0)])

    def test_a_disk_follows_its_fields(self):
        disk = geometry2d.Disk2D(outerRadius=1.0)
        check_memo_inputs(disk.mesh, [
            ('outerRadius', lambda: setattr(disk, 'outerRadius', 2.0)),
            ('innerRadius', lambda: setattr(disk, 'innerRadius', 0.5)),
            ('solid', lambda: setattr(disk, 'solid', True)),
        ], fresh=disk.buildMesh,
           same=lambda a, b: np.array_equal(a.positions, b.positions) and a.solid == b.solid)

    def test_a_circle_follows_its_radius(self):
        circle = geometry2d.Circle2D(radius=1.0)
        check_memo_inputs(circle.drawn, [
            ('radius', lambda: setattr(circle, 'radius', 3.0)),
        ], fresh=circle.buildDrawn,
           same=lambda a, b: np.array_equal(a.coord.point, b.coord.point))


def test_a_document_of_2d_shapes_draws(gl_context):
    document = b'''<X3D version="4.0"><Scene><Viewpoint position="0 0 6"/>
      <Shape><Appearance><Material diffuseColor="1 0 0" emissiveColor="1 0 0"/></Appearance>
        <Disk2D outerRadius="1.5"/></Shape></Scene></X3D>'''
    scene = Loader.loads(document, 'scene.x3d')
    with scene_context(scene) as context:
        context.OnDraw(force=1)
        image = drawn_image(context)
    h, w = image.shape[:2]
    red, green, blue = image[h // 2, w // 2].astype(int)
    assert red > 100 and red > 3 * max(green, blue, 1)
