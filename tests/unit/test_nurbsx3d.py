"""X3D's NURBS nodes, read from documents and built into what they draw -- no GL

Surfaces are drawn as the `PBRMesh` their fields build, curves as an
`IndexedLineSet` of the points along them; the interpolators send what their
curve or surface gives at each fraction.
"""
import math

import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import nurbs, nurbsinterpolators, nurbstrim, nurbsx3d
from OpenGLContext.testing.memo import check_memo_inputs

#: A flat 4 by 4 net, x following u and y following v.
PLANE = ' '.join('%d %d 0' % (x, y) for y in range(4) for x in range(4))
PATCH = ('<NurbsPatchSurface uDimension="4" vDimension="4" uOrder="4" vOrder="4" %s>'
         '<Coordinate containerField="controlPoint" point="' + PLANE + '"/>%s'
         '</NurbsPatchSurface>')


def scene(body):
    document = '<X3D version="4.0"><Scene>%s</Scene></X3D>' % body
    return Loader.loads(document.encode(), 'scene.x3d')


def read(geometry):
    """The geometry node of a one-shape X3D document"""
    return scene('<Shape>%s</Shape>' % geometry).children[0].geometry


def patch(fields='', children=''):
    return read(PATCH % (fields, children))


@pytest.mark.parametrize('name, cls', [
    ('NurbsCurve', nurbsx3d.NurbsCurve),
    ('NurbsCurve2D', nurbsx3d.NurbsCurve2D),
    ('Contour2D', nurbsx3d.Contour2D),
    ('ContourPolyline2D', nurbsx3d.ContourPolyline2D),
    ('NurbsPatchSurface', nurbsx3d.NurbsPatchSurface),
    ('NurbsTrimmedSurface', nurbsx3d.NurbsTrimmedSurface),
    ('NurbsSweptSurface', nurbsx3d.NurbsSweptSurface),
    ('NurbsSwungSurface', nurbsx3d.NurbsSwungSurface),
    ('NurbsSet', nurbsx3d.NurbsSet),
    ('NurbsTextureCoordinate', nurbsx3d.NurbsTextureCoordinate),
    ('NurbsPositionInterpolator', nurbsinterpolators.NurbsPositionInterpolator),
    ('NurbsOrientationInterpolator', nurbsinterpolators.NurbsOrientationInterpolator),
    ('NurbsSurfaceInterpolator', nurbsinterpolators.NurbsSurfaceInterpolator),
])
def test_each_x3d_nurbs_node_is_the_engines(name, cls):
    assert prototypes()[name] is cls


def test_a_vrml97_world_keeps_the_extensions_nodes():
    from OpenGLContext.loaders.vrml97 import vrml97_prototypes  # noqa: PLC0415 kept with its use
    found = vrml97_prototypes()
    assert found['NurbsCurve'] is nurbs.NurbsCurve
    assert found['NurbsCurve2D'] is nurbstrim.NurbsCurve2D
    assert found['Contour2D'] is nurbstrim.Contour2D
    assert found['NurbsPatchSurface'] is nurbsx3d.NurbsPatchSurface


class TestPatchSurface:
    def test_the_tessellation_fields_set_the_lattice(self):
        mesh = patch('uTessellation="6" vTessellation="3"').mesh()
        assert len(mesh.positions) == 7 * 4
        assert len(mesh.indices) == 6 * 3 * 2 * 3

    def test_the_default_lattice(self):
        mesh = patch().mesh()
        per = nurbsx3d.nurbseval.SEGMENTS_PER_SPAN + 1
        assert len(mesh.positions) == per * per

    def test_a_plane_faces_u_cross_v(self):
        assert np.allclose(patch().mesh().normals, (0, 0, 1), atol=1e-6)

    def test_solid_reaches_the_mesh(self):
        assert patch('solid="false"').mesh().solid is False
        assert patch().mesh().solid is True

    def test_texture_coordinates_default_to_the_parameter_square(self):
        mesh = patch('uTessellation="2" vTessellation="2"').mesh()
        assert np.allclose(mesh.positions[:, :2], 3 * np.asarray(mesh.texcoords))

    def test_a_texture_coordinate_net_is_evaluated_like_the_surface(self):
        points = ' '.join('%g %g' % (2 * x / 3.0, 2 * y / 3.0) for y in range(4) for x in range(4))
        mesh = patch('uTessellation="2" vTessellation="2"',
                     '<TextureCoordinate point="%s"/>' % points).mesh()
        assert np.allclose(mesh.positions[:, :2], 1.5 * np.asarray(mesh.texcoords), atol=1e-6)

    def test_a_nurbs_texture_coordinate_has_its_own_net(self):
        mesh = patch('uTessellation="2" vTessellation="2"',
                     '<NurbsTextureCoordinate uDimension="2" vDimension="2" uOrder="2" '
                     'vOrder="2" controlPoint="0 0 4 0 0 4 4 4"/>').mesh()
        assert np.allclose(np.asarray(mesh.texcoords) * 3.0, mesh.positions[:, :2] * 4.0,
                           atol=1e-6)

    def test_a_short_texture_coordinate_falls_back_to_the_parameters(self, caplog):
        mesh = patch('uTessellation="2" vTessellation="2"',
                     '<TextureCoordinate point="0 0 1 1"/>').mesh()
        assert np.allclose(mesh.positions[:, :2], 3 * np.asarray(mesh.texcoords))
        assert 'TextureCoordinate' in caplog.text

    def test_a_generated_texture_coordinate_is_the_shaders(self):
        found = patch('', '<TextureCoordinateGenerator mode="COORD"/>')
        assert found.texGen is not None
        assert found.mesh() is not None

    def test_weights_pull_the_surface(self):
        lifted = PATCH.replace(PLANE, ' '.join('%d %d %d' % (x, y, (x, y) == (1, 1))
                                                for y in range(4) for x in range(4)))
        weight = ['1'] * 16
        weight[5] = '20'
        # a weighted point is given multiplied by its weight
        heavy = lifted.replace(' 1 1 1 ', ' 20 20 20 ')
        plain = read(lifted % ('', '')).mesh().positions[:, 2].max()
        pulled = read(heavy % ('weight="%s"' % ' '.join(weight), '')).mesh().positions[:, 2].max()
        assert pulled > plain

    def test_a_patch_of_an_order_above_its_dimension_draws_nothing(self, caplog):
        assert read(PATCH.replace('uOrder="4"', 'uOrder="5"') % ('', '')).mesh() is None
        assert 'NurbsPatchSurface' in caplog.text

    def test_a_patch_with_no_control_points_draws_nothing(self):
        assert nurbsx3d.NurbsPatchSurface().mesh() is None
        assert nurbsx3d.NurbsPatchSurface().meshArrays() is None

    def test_double_precision_control_points(self):
        found = read(PATCH.replace('Coordinate', 'CoordinateDouble') % ('', ''))
        assert found.mesh() is not None

    def test_a_closed_surface_is_seamless(self):
        ring = []
        for height in (0, 1):
            for step in range(7):
                angle = 2 * math.pi * step / 6
                ring.append('%.12f %.12f %d' % (math.cos(angle), math.sin(angle), height))
        found = read('<NurbsPatchSurface uClosed="true" uDimension="7" vDimension="2" '
                     'uOrder="3" vOrder="2" uTessellation="12" vTessellation="1">'
                     '<Coordinate containerField="controlPoint" point="%s"/>'
                     '</NurbsPatchSurface>' % ' '.join(ring))
        positions = found.mesh().positions.reshape(13, 2, 3)
        assert np.allclose(positions[0], positions[-1])
        assert np.allclose(np.linalg.norm(positions[:, :, :2], axis=-1), 1.0, atol=0.2)

    def test_mesh_arrays(self):
        arrays = patch('uTessellation="2" vTessellation="2"').meshArrays()
        assert len(arrays.attributes['POSITION']) == 9

    def test_the_mesh_follows_every_input(self):
        found = patch('uTessellation="2" vTessellation="2"',
                      '<TextureCoordinate point="%s"/>' % ' '.join(['0 0'] * 16))
        control, texture = found.controlPoint, found.texCoord

        def same(a, b):
            return all(np.array_equal(getattr(a, name), getattr(b, name))
                       for name in ('positions', 'normals', 'texcoords', 'indices')
                       ) and a.solid == b.solid

        check_memo_inputs(found.mesh, [
            ('controlPoint.point', lambda: setattr(control, 'point', [
                (x, y, x * y) for y in range(4) for x in range(4)])),
            ('weight', lambda: setattr(found, 'weight', [1.0] * 5 + [4.0] + [1.0] * 10)),
            ('uTessellation', lambda: setattr(found, 'uTessellation', 3)),
            ('vTessellation', lambda: setattr(found, 'vTessellation', 4)),
            ('uKnot', lambda: setattr(found, 'uKnot', [0, 1, 2, 3, 4, 5, 6, 7])),
            ('texCoord.point', lambda: setattr(texture, 'point', [(1, 1)] * 16)),
            ('solid', lambda: setattr(found, 'solid', False)),
            ('controlPoint', lambda: setattr(found, 'controlPoint', x3d.Coordinate(
                point=[(x, y, 1) for y in range(4) for x in range(4)]))),
        ], fresh=found.buildMesh, same=same)

    def test_a_distant_surface_is_tessellated_coarsely(self):
        found = patch()
        near = found.levelMesh(0)
        far = found.levelMesh(3)
        assert len(far.positions) < len(near.positions)


    def test_a_surfaces_origin_is_known_without_a_mesh(self, monkeypatch):
        """A surface drawn at a distance level is not also built at full detail"""
        found = patch()
        built = []
        original = nurbsx3d.SurfaceDrawn.buildMesh
        monkeypatch.setattr(nurbsx3d.SurfaceDrawn, 'buildMesh',
                            lambda self, level=0: built.append(level) or original(self, level))
        assert found.meshOrigin() is None
        found.levelMesh(2)
        assert built == [2]
        assert found.levelMesh(0).origin is None


    def test_a_surface_is_bounded_by_its_control_net_without_a_mesh(self, monkeypatch):
        found = patch()
        built = []
        original = nurbsx3d.SurfaceDrawn.buildMesh
        monkeypatch.setattr(nurbsx3d.SurfaceDrawn, 'buildMesh',
                            lambda self, level=0: built.append(level) or original(self, level))
        volume = found.boundingVolume()
        assert built == []
        assert np.allclose(volume.center, [1.5, 1.5, 0.0])
        assert np.allclose(volume.size, [3.0, 3.0, 0.0])
        assert found.boundingVolume() is volume

    def test_the_bounds_hold_the_mesh_and_follow_the_control_points(self):
        found = patch()
        found.controlPoint.point = [(x, y, 2.0 if (x, y) == (1, 1) else 0.0)
                                    for y in range(4) for x in range(4)]
        volume = found.boundingVolume()
        low = np.asarray(volume.center) - np.asarray(volume.size) / 2.0
        high = np.asarray(volume.center) + np.asarray(volume.size) / 2.0
        positions = np.asarray(found.mesh().positions)
        assert (positions >= low - 1e-5).all() and (positions <= high + 1e-5).all()
        assert np.allclose(volume.size, [3.0, 3.0, 2.0])

    def test_weighted_points_are_bounded_where_they_are(self):
        """A weighted control point is given multiplied by its weight"""
        found = patch('weight="%s"' % ' '.join(['2'] * 16))
        assert np.allclose(found.boundingVolume().size, [1.5, 1.5, 0.0])

    def test_a_surface_with_nothing_to_draw_has_empty_bounds(self):
        from OpenGLContext.scenegraph import boundingvolume
        found = read('<NurbsPatchSurface/>')
        assert type(found.boundingVolume()) is boundingvolume.BoundingVolume


def _area(mesh):
    p = np.asarray(mesh.positions, dtype=float)
    tri = np.asarray(mesh.indices).reshape(-1, 3)
    a, b, c = p[tri[:, 0]], p[tri[:, 1]], p[tri[:, 2]]
    return float(0.5 * np.linalg.norm(np.cross(b - a, c - a), axis=1).sum())


TRIMMED = ('<NurbsTrimmedSurface uDimension="2" vDimension="2" uOrder="2" vOrder="2" '
           'uKnot="0 0 4 4" vKnot="0 0 4 4">'
           '<Coordinate containerField="controlPoint" point="0 0 0 4 0 0 0 4 0 4 4 0"/>%s'
           '</NurbsTrimmedSurface>')
OUTER = '<Contour2D><ContourPolyline2D controlPoint="0 0 4 0 4 4 0 4 0 0"/></Contour2D>'
HOLE = '<Contour2D><ContourPolyline2D controlPoint="1 1 3 1 3 3 1 3 1 1"/></Contour2D>'


class TestTrimmedSurface:
    def test_an_outer_contour_and_a_hole(self):
        found = read(TRIMMED % (OUTER + HOLE))
        assert _area(found.mesh()) == pytest.approx(12.0, rel=1e-5)

    def test_no_contours_is_the_whole_patch(self):
        assert _area(read(TRIMMED % '').mesh()) == pytest.approx(16.0, rel=1e-5)

    def test_a_contour_of_curves_and_polylines(self):
        # A half disc: a straight edge and a rational quadratic arc, whose
        # corner points are given multiplied by their weights
        root = math.sqrt(0.5)
        contour = ('<Contour2D><ContourPolyline2D controlPoint="0 2 4 2"/>'
                   '<NurbsCurve2D order="3" tessellation="64" knot="0 0 0 1 1 2 2 2" '
                   'weight="1 %g 1 %g 1" controlPoint="4 2 %r %r 2 4 0 %r 0 2"/>'
                   '</Contour2D>') % (root, root, 4 * root, 4 * root, 4 * root)
        found = read(TRIMMED % contour)
        assert _area(found.mesh()) == pytest.approx(math.pi * 2.0, rel=2e-3)

    def test_trimming_contours_can_be_added_and_removed(self):
        found = read(TRIMMED % OUTER)
        hole = scene(HOLE).children[0]
        found.addTrimmingContour = [hole]
        assert _area(found.mesh()) == pytest.approx(12.0, rel=1e-5)
        found.removeTrimmingContour = [hole]
        assert _area(found.mesh()) == pytest.approx(16.0, rel=1e-5)

    def test_a_contours_children_can_be_added_and_removed(self):
        found = read(TRIMMED % (OUTER + '<Contour2D/>'))
        contour = found.trimmingContour[1]
        piece = nurbsx3d.ContourPolyline2D(controlPoint=[(1, 1), (3, 1), (3, 3), (1, 3)])
        contour.addChildren = [piece]
        assert _area(found.mesh()) == pytest.approx(12.0, rel=1e-5)
        contour.removeChildren = [piece]
        assert _area(found.mesh()) == pytest.approx(16.0, rel=1e-5)

    def test_the_mesh_follows_its_contours_points(self):
        found = read(TRIMMED % (OUTER + HOLE))
        piece = found.trimmingContour[1].children[0]
        check_memo_inputs(found.mesh, [
            ('controlPoint', lambda: setattr(piece, 'controlPoint',
                                             [(1, 1), (2, 1), (2, 2), (1, 2), (1, 1)])),
        ], fresh=found.buildMesh, same=lambda a, b: np.array_equal(a.positions, b.positions))


class TestCurve:
    CURVE = ('<NurbsCurve order="3" tessellation="%d">'
             '<Coordinate containerField="controlPoint" point="0 0 0 1 2 0 3 2 0 4 0 0"/>'
             '</NurbsCurve>')

    def test_a_curve_is_drawn_as_a_line_through_its_points(self):
        found = read(self.CURVE % 16)
        lines = found.drawn()
        assert len(lines.coord.point) == 17
        assert list(lines.coordIndex[:3]) == [0, 1, 2]
        assert np.allclose(lines.coord.point[0], (0, 0, 0))
        assert np.allclose(lines.coord.point[-1], (4, 0, 0))

    def test_the_line_follows_the_control_points(self):
        found = read(self.CURVE % 8)
        control = found.controlPoint
        check_memo_inputs(found.drawn, [
            ('controlPoint.point', lambda: setattr(control, 'point',
                                                   [(0, 0, 0), (1, 1, 0), (2, 1, 0), (3, 3, 0)])),
            ('tessellation', lambda: setattr(found, 'tessellation', 4)),
            ('weight', lambda: setattr(found, 'weight', [1, 3, 1, 1])),
        ], same=lambda a, b: np.array_equal(a.coord.point, b.coord.point))

    def test_a_curve_without_enough_points_draws_nothing(self):
        assert nurbsx3d.NurbsCurve().drawn() is None
        assert nurbsx3d.NurbsCurve().render() == 0

    def test_a_closed_curve_meets_itself(self):
        found = read('<NurbsCurve closed="true" order="3" tessellation="20">'
                     '<Coordinate containerField="controlPoint" '
                     'point="1 0 0 0 1 0 -1 0 0 0 -1 0 1 0 0"/></NurbsCurve>')
        points = found.drawn().coord.point
        assert np.allclose(points[0], points[-1])


class TestSweeps:
    def test_a_swept_surface_builds_a_mesh(self):
        found = read('<NurbsSweptSurface solid="false">'
                     '<NurbsCurve2D containerField="crossSectionCurve" order="2" '
                     'controlPoint="-1 -1 1 -1 1 1 -1 1 -1 -1"/>'
                     '<NurbsCurve containerField="trajectoryCurve" order="2">'
                     '<Coordinate containerField="controlPoint" point="0 0 0 0 3 0"/>'
                     '</NurbsCurve></NurbsSweptSurface>')
        mesh = found.mesh()
        assert np.allclose(np.asarray(mesh.positions)[:, 1].max(), 3.0)
        assert mesh.solid is False

    def test_a_swung_surface_builds_a_mesh(self):
        found = read('<NurbsSwungSurface>'
                     '<NurbsCurve2D containerField="profileCurve" order="2" '
                     'controlPoint="0.5 0 0.5 1"/>'
                     '<NurbsCurve2D containerField="trajectoryCurve" order="3" '
                     'controlPoint="-2 0 0 2 2 0"/></NurbsSwungSurface>')
        positions = np.asarray(found.mesh().positions)
        assert positions[:, 1].max() == pytest.approx(1.0)

    def test_a_sweep_missing_a_curve_draws_nothing(self):
        assert nurbsx3d.NurbsSweptSurface().mesh() is None
        assert nurbsx3d.NurbsSwungSurface().mesh() is None

    def test_the_sweep_follows_its_curves(self):
        found = read('<NurbsSweptSurface>'
                     '<NurbsCurve2D containerField="crossSectionCurve" order="2" '
                     'controlPoint="-1 -1 1 -1 1 1 -1 1 -1 -1"/>'
                     '<NurbsCurve containerField="trajectoryCurve" order="2">'
                     '<Coordinate containerField="controlPoint" point="0 0 0 0 3 0"/>'
                     '</NurbsCurve></NurbsSweptSurface>')
        section, trajectory = found.crossSectionCurve, found.trajectoryCurve
        check_memo_inputs(found.mesh, [
            ('crossSectionCurve.controlPoint', lambda: setattr(
                section, 'controlPoint', [(-2, -2), (2, -2), (2, 2), (-2, 2), (-2, -2)])),
            ('trajectoryCurve.controlPoint.point', lambda: setattr(
                trajectory.controlPoint, 'point', [(0, 0, 0), (0, 5, 0)])),
            ('ccw', lambda: setattr(found, 'ccw', False)),
        ], fresh=found.buildMesh, same=lambda a, b: np.array_equal(a.positions, b.positions)
           and np.array_equal(a.normals, b.normals))


class TestNurbsSet:
    DOCUMENT = ('<Shape><NurbsPatchSurface DEF="P" uDimension="4" vDimension="4" uOrder="4" '
                'vOrder="4" uTessellation="4" vTessellation="4"><Coordinate '
                'containerField="controlPoint" point="' + PLANE + '"/></NurbsPatchSurface>'
                '</Shape><NurbsSet tessellationScale="2"><NurbsPatchSurface USE="P" '
                'containerField="geometry"/></NurbsSet>')

    def test_the_set_scales_its_geometrys_tessellation(self):
        loaded = scene(self.DOCUMENT)
        assert len(loaded.children[0].geometry.mesh().positions) == 9 * 9

    def test_a_changed_scale_rebuilds_the_geometry(self):
        loaded = scene(self.DOCUMENT)
        geometry = loaded.children[0].geometry
        geometry.mesh()
        loaded.children[1].tessellationScale = 0.5
        assert len(geometry.mesh().positions) == 3 * 3

    def test_geometry_removed_from_the_set_is_unscaled(self):
        loaded = scene(self.DOCUMENT)
        geometry = loaded.children[0].geometry
        geometry.mesh()
        loaded.children[1].removeGeometry = [geometry]
        assert len(geometry.mesh().positions) == 5 * 5
        loaded.children[1].addGeometry = [geometry]
        assert len(geometry.mesh().positions) == 9 * 9

    def test_the_set_scales_a_curve(self):
        curve = nurbsx3d.NurbsCurve(tessellation=4, controlPoint=x3d.Coordinate(
            point=[(0, 0, 0), (1, 1, 0), (2, 0, 0)]))
        nurbsx3d.NurbsSet(geometry=[curve], tessellationScale=3)
        assert len(curve.drawn().coord.point) == 13


class TestInterpolators:
    def test_a_position_runs_along_the_curve(self):
        found = nurbsinterpolators.NurbsPositionInterpolator(
            order=2, controlPoint=x3d.Coordinate(point=[(0, 0, 0), (2, 0, 0), (2, 2, 0)]))
        found.set_fraction = 0.0
        assert np.allclose(found.value_changed, (0, 0, 0))
        found.set_fraction = 0.25
        assert np.allclose(found.value_changed, (1, 0, 0))
        found.set_fraction = 1.0
        assert np.allclose(found.value_changed, (2, 2, 0))

    def test_an_orientation_turns_z_to_the_tangent(self):
        found = nurbsinterpolators.NurbsOrientationInterpolator(
            order=2, controlPoint=x3d.Coordinate(point=[(0, 0, 0), (2, 0, 0), (2, 2, 0)]))
        found.set_fraction = 0.25
        axis, angle = np.asarray(found.value_changed[:3]), found.value_changed[3]
        assert angle == pytest.approx(math.pi / 2)
        assert np.allclose(axis, (0, 1, 0))
        found.set_fraction = 0.75
        assert np.allclose(_turn(found.value_changed, (0, 0, 1)), (0, 1, 0), atol=1e-9)

    def test_an_orientation_along_minus_z(self):
        found = nurbsinterpolators.NurbsOrientationInterpolator(
            order=2, controlPoint=x3d.Coordinate(point=[(0, 0, 0), (0, 0, -2)]))
        found.set_fraction = 0.5
        assert np.allclose(_turn(found.value_changed, (0, 0, 1)), (0, 0, -1), atol=1e-9)

    def test_a_surface_position_and_normal(self):
        found = nurbsinterpolators.NurbsSurfaceInterpolator(
            uDimension=2, vDimension=2, uOrder=2, vOrder=2,
            controlPoint=x3d.Coordinate(point=[(0, 0, 0), (2, 0, 0), (0, 2, 0), (2, 2, 0)]))
        found.set_fraction = (0.5, 0.25)
        assert np.allclose(found.position_changed, (1, 0.5, 0))
        assert np.allclose(found.normal_changed, (0, 0, 1))

    def test_an_interpolator_with_no_curve_sends_nothing(self):
        found = nurbsinterpolators.NurbsPositionInterpolator()
        assert found.on_set_fraction(0.5) is None

    def test_the_curve_follows_the_control_points(self):
        control = x3d.Coordinate(point=[(0, 0, 0), (2, 0, 0)])
        found = nurbsinterpolators.NurbsPositionInterpolator(order=2, controlPoint=control)
        found.set_fraction = 0.5
        control.point = [(0, 0, 0), (4, 0, 0)]
        found.set_fraction = 0.5
        assert np.allclose(found.value_changed, (2, 0, 0))

    def test_a_routed_fraction_moves_a_transform(self):
        loaded = scene('<NurbsPositionInterpolator DEF="I" order="2"><Coordinate '
                       'containerField="controlPoint" point="0 0 0 4 0 0"/>'
                       '</NurbsPositionInterpolator><Transform DEF="T"/>'
                       '<ROUTE fromNode="I" fromField="value_changed" toNode="T" '
                       'toField="set_translation"/>')
        interpolator, transform = loaded.children[0], loaded.children[1]
        interpolator.set_fraction = 0.5
        assert np.allclose(transform.translation, (2, 0, 0))


def _turn(rotation, vector):
    """`vector` turned by an X3D rotation"""
    axis = np.asarray(rotation[:3], dtype=float)
    angle = float(rotation[3])
    axis = axis / np.linalg.norm(axis)
    v = np.asarray(vector, dtype=float)
    return (v * math.cos(angle) + np.cross(axis, v) * math.sin(angle)
            + axis * np.dot(axis, v) * (1 - math.cos(angle)))
