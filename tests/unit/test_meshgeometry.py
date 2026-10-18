"""X3D's triangle sets and LineSet, read from documents and drawn.

Each set is drawn as the `PBRMesh` its fields build (`mesh()`), kept in vrml's
cache until one of its fields, or a field of its coordinates, normals,
colours or texture coordinates, is set.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import meshgeometry
from OpenGLContext.scenegraph.texturemapping import coordinate_set
from OpenGLContext.testing.memo import check_memo_inputs
from OpenGLContext.testing.scenes import drawn_image, scene_context

QUAD = '<Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/>'


def read(geometry):
    """The geometry node of a one-shape X3D document"""
    document = ('<X3D version="4.0"><Scene><Shape>%s</Shape></Scene></X3D>' % geometry).encode()
    return Loader.loads(document, 'scene.x3d').children[0].geometry


@pytest.mark.parametrize('text, cls, corners', [
    ('<TriangleSet><Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 -1 0 1 1 0 -1 1 0"/>'
     '</TriangleSet>',
     meshgeometry.TriangleSet, 6),
    ('<IndexedTriangleSet index="0 1 2 0 2 3">%s</IndexedTriangleSet>' % QUAD,
     meshgeometry.IndexedTriangleSet, 6),
    ('<TriangleFanSet fanCount="4">%s</TriangleFanSet>' % QUAD, meshgeometry.TriangleFanSet, 6),
    ('<IndexedTriangleFanSet index="0 1 2 3 -1">%s</IndexedTriangleFanSet>' % QUAD,
     meshgeometry.IndexedTriangleFanSet, 6),
    ('<TriangleStripSet stripCount="4">%s</TriangleStripSet>' % QUAD.replace(
        '1 1 0 -1 1 0', '-1 1 0 1 1 0'), meshgeometry.TriangleStripSet, 6),
    ('<IndexedTriangleStripSet index="0 1 3 2">%s</IndexedTriangleStripSet>' % QUAD,
     meshgeometry.IndexedTriangleStripSet, 6),
    ('<QuadSet>%s</QuadSet>' % QUAD, meshgeometry.QuadSet, 6),
    ('<IndexedQuadSet index="0 1 2 3">%s</IndexedQuadSet>' % QUAD,
     meshgeometry.IndexedQuadSet, 6),
])
def test_each_set_is_read_as_the_engines_and_drawn_as_a_mesh(text, cls, corners):
    geometry = read(text)
    assert type(geometry) is cls
    mesh = geometry.mesh()
    drawn = len(mesh.indices) if mesh.indices is not None else len(mesh.positions)
    assert drawn == corners
    assert np.allclose(mesh.normals, (0, 0, 1))


def test_a_quads_colour_is_both_its_triangles():
    """One colour per quad where colorPerVertex is false"""
    quads = read('<IndexedQuadSet colorPerVertex="false" index="0 1 2 3 0 1 2 3">%s'
                 '<Color color="1 0 0 0 1 0"/></IndexedQuadSet>' % QUAD)
    colours = np.asarray(quads.mesh().colors)[:, :3]
    assert len(colours) == 12
    assert np.allclose(colours[:6], (1, 0, 0)) and np.allclose(colours[6:], (0, 1, 0))


def test_an_index_short_of_a_quad_is_left_out():
    quads = read('<IndexedQuadSet index="0 1 2 3 0 1">%s</IndexedQuadSet>' % QUAD)
    assert len(quads.mesh().indices) == 6


def test_double_precision_coordinates_draw():
    geometry = read('<IndexedTriangleSet index="0 1 2 0 2 3"><CoordinateDouble point='
                    '"-1 -1 0 1 -1 0 1 1 0 -1 1 0"/></IndexedTriangleSet>')
    assert len(geometry.mesh().indices) == 6


def test_the_mesh_is_as_solid_as_the_set():
    assert read('<IndexedTriangleSet solid="false" index="0 1 2">%s</IndexedTriangleSet>'
                % QUAD).mesh().solid is False


def test_rgba_colours_reach_the_mesh():
    mesh = read('<IndexedTriangleSet index="0 1 2">%s<ColorRGBA color="%s"/></IndexedTriangleSet>'
                % (QUAD, ' '.join(['1 0 0 0.5'] * 4))).mesh()
    assert np.allclose(mesh.colors, (1, 0, 0, 0.5))


def test_a_second_coordinate_set_and_its_mapping_label():
    geometry = read('''<IndexedTriangleSet index="0 1 2">%s
      <MultiTextureCoordinate>
        <TextureCoordinate mapping="base" point="0 0 1 0 1 1 0 1"/>
        <TextureCoordinate mapping="baked" point="0 0 2 0 2 2 0 2"/>
      </MultiTextureCoordinate></IndexedTriangleSet>''' % QUAD)
    assert np.allclose(geometry.mesh().texcoords1[2], (2, 2))
    assert coordinate_set(geometry, 'baked') == 1
    assert coordinate_set(geometry, 'base') == 0
    assert coordinate_set(geometry, 'TEXCOORD_1') == 1


def test_an_index_past_the_points_is_reported_once(caplog):
    geometry = read('<IndexedTriangleSet index="0 1 2 0 2 7">%s</IndexedTriangleSet>' % QUAD)
    geometry.mesh()
    geometry.mesh()
    assert caplog.text.count('names coordinates it does not have') == 1


def test_a_set_with_no_coordinates_draws_nothing():
    assert meshgeometry.IndexedTriangleSet(index=[0, 1, 2]).mesh() is None


def test_the_mesh_follows_every_input():
    coord = x3d.Coordinate(point=[(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)])
    normal = x3d.Normal(vector=[(0, 0, 1)] * 4)
    color = x3d.Color(color=[(1, 0, 0)] * 4)
    texture = x3d.TextureCoordinate(point=[(0, 0), (1, 0), (1, 1), (0, 1)])
    geometry = meshgeometry.IndexedTriangleSet(index=[0, 1, 2], coord=coord, normal=normal,
                                               color=color, texCoord=texture)

    def ask():
        return geometry.mesh()

    def fresh():
        return geometry.buildMesh()

    def same(a, b):
        return all(np.array_equal(getattr(a, name), getattr(b, name))
                   if getattr(a, name) is not None else getattr(b, name) is None
                   for name in ('positions', 'normals', 'colors', 'texcoords', 'indices')
                   ) and a.solid == b.solid

    check_memo_inputs(ask, [
        ('coord.point', lambda: setattr(coord, 'point', [(0, 0, 0), (2, 0, 0), (2, 2, 0), (0, 2, 0)])),
        ('normal.vector', lambda: setattr(normal, 'vector', [(0, 1, 0), (1, 0, 0),
                                                            (0, 0, 1), (0, 1, 0)])),
        ('color.color', lambda: setattr(color, 'color', [(0, 1, 0)] * 4)),
        ('texCoord.point', lambda: setattr(texture, 'point', [(0, 0), (2, 0), (2, 2), (0, 2)])),
        ('index', lambda: setattr(geometry, 'index', [0, 2, 3])),
        ('ccw', lambda: setattr(geometry, 'ccw', False)),
        ('solid', lambda: setattr(geometry, 'solid', False)),
        ('colorPerVertex', lambda: setattr(geometry, 'colorPerVertex', False)),
        ('normalPerVertex', lambda: setattr(geometry, 'normalPerVertex', False)),
        ('coord', lambda: setattr(geometry, 'coord', x3d.Coordinate(
            point=[(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]))),
    ], fresh=fresh, same=same)


def test_an_elevation_grid_is_drawn_as_a_mesh():
    grid = read('<ElevationGrid xDimension="3" zDimension="2" xSpacing="2" zSpacing="1" '
                'height="0 1 0 0 1 0" creaseAngle="0"/>')
    assert type(grid) is meshgeometry.ElevationGrid
    mesh = grid.mesh()
    assert len(mesh.positions) == 12          # flat: four triangles, three corners each
    assert np.allclose(mesh.positions.max(axis=0), (4, 1, 1))
    assert mesh.texcoords is not None


def test_an_elevation_grid_follows_its_heights():
    grid = meshgeometry.ElevationGrid(xDimension=2, zDimension=2, height=[0, 0, 0, 0])
    check_memo_inputs(grid.mesh, [
        ('height', lambda: setattr(grid, 'height', [0, 1, 1, 0])),
        ('xSpacing', lambda: setattr(grid, 'xSpacing', 3.0)),
        ('creaseAngle', lambda: setattr(grid, 'creaseAngle', 3.0)),
    ], fresh=grid.buildMesh, same=lambda a, b: np.array_equal(a.positions, b.positions)
       and np.array_equal(a.normals, b.normals))


def test_a_line_set_is_drawn_as_its_polylines():
    lines = read('<LineSet vertexCount="3 2"><Coordinate point="0 0 0 1 0 0 1 1 0 2 2 0 3 3 0"/>'
                 '</LineSet>')
    assert type(lines) is meshgeometry.LineSet
    assert list(lines.drawn().coordIndex) == [0, 1, 2, -1, 3, 4, -1]


def test_a_line_set_without_coordinates_is_no_polylines():
    """Basic/development/ProfileExampleInterchange: a LineSet with a colour and nothing else"""
    lines = read('<LineSet><ColorRGBA color="1 1 1 1"/></LineSet>')
    drawn = lines.drawn()
    assert list(drawn.coordIndex) == [] and not drawn.coord


def _centre(image):
    h, w = image.shape[:2]
    return image[h // 2 - 4:h // 2 + 4, w // 2 - 4:w // 2 + 4].reshape(-1, 3).mean(axis=0)


def _drawn(geometry_text, material='<Material diffuseColor="1 0 0" emissiveColor="1 0 0"/>'):
    document = ('<X3D version="4.0"><Scene><Viewpoint position="0 0 4"/><Shape>'
                '<Appearance>%s</Appearance>%s</Shape></Scene></X3D>'
                % (material, geometry_text)).encode()
    scene = Loader.loads(document, 'scene.x3d')
    with scene_context(list(scene.children)) as context:
        context.OnDraw(force=1)
        return drawn_image(context)


def test_an_indexed_triangle_set_draws(gl_context):
    red = _centre(_drawn('<IndexedTriangleSet index="0 1 2 0 2 3">%s</IndexedTriangleSet>' % QUAD))
    assert red[0] > 100 and red[0] > 3 * max(red[1], red[2], 1)


def test_vertex_colours_draw(gl_context):
    green = _centre(_drawn(
        '<IndexedTriangleSet index="0 1 2 0 2 3">%s<Color color="%s"/></IndexedTriangleSet>'
        % (QUAD, ' '.join(['0 1 0'] * 4)), material='<Material diffuseColor="1 1 1"/>'))
    assert green[1] > 40 and green[1] > 3 * max(green[0], green[2], 1)


def test_a_line_set_draws(gl_context):
    image = _drawn('<LineSet vertexCount="2"><Coordinate point="-1 0 0 1 0 0"/></LineSet>')
    assert (image.sum(axis=2) > 60).sum() > 20


def test_a_shapes_bounds_follow_its_sets_points():
    shape = Loader.loads(('<X3D version="4.0"><Scene><Shape><IndexedTriangleSet index="0 1 2">'
                          '%s</IndexedTriangleSet></Shape></Scene></X3D>' % QUAD).encode(),
                         'scene.x3d').children[0]
    before = shape.boundingVolume(None).getPoints()[:, :3].max(axis=0)
    shape.geometry.coord.point = [(-5, -5, 0), (5, -5, 0), (5, 5, 0)]
    after = shape.boundingVolume(None).getPoints()[:, :3].max(axis=0)
    assert np.allclose(before[:2], 1) and np.allclose(after[:2], 5)
