"""STL, PLY and OFF models, and the 3D Gaussian splat PLY layout.

Each file is written in the test. A model reads as a scene of one ``Shape``
holding a ``PBRMesh``; a splat PLY reads as a ``GaussianSplats`` node.
"""
import gzip
import struct

import numpy as np
import pytest

from OpenGLContext.loaders import formats, meshfiles
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.gaussiansplats import GaussianSplats
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

TRIANGLE = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)


def _only(scene, kind=PBRMesh):
    found, stack = [], list(scene.children)
    while stack:
        node = stack.pop()
        geometry = getattr(node, 'geometry', None)
        if isinstance(geometry, kind):
            found.append(geometry)
        if isinstance(node, kind):
            found.append(node)
        stack.extend(getattr(node, 'children', None) or [])
    assert len(found) == 1, found
    return found[0]


# --------------------------------------------------------------------------- #
# STL
# --------------------------------------------------------------------------- #
ASCII_STL = b"""solid one
  facet normal 0 0 1
    outer loop
      vertex 0 0 0
      vertex 1 0 0
      vertex 0 1 0
    endloop
  endfacet
  facet normal 0 0 0
    outer loop
      vertex 0 0 0
      vertex 0 1 0
      vertex -1 0 0
    endloop
  endfacet
endsolid one
"""


def _binary_stl(triangles, normals=None, header=b'binary'):
    triangles = np.asarray(triangles, np.float32).reshape(-1, 3, 3)
    normals = (np.zeros((len(triangles), 3), np.float32) if normals is None
               else np.asarray(normals, np.float32))
    out = bytearray(header.ljust(80, b' ') + struct.pack('<I', len(triangles)))
    for normal, corners in zip(normals, triangles):
        out += normal.tobytes() + corners.tobytes() + b'\0\0'
    return bytes(out)


class TestSTL:
    def test_ascii_triangles_with_facet_normals(self):
        mesh = meshfiles.read_stl(ASCII_STL)
        assert mesh.positions.shape == (6, 3)
        assert np.allclose(mesh.positions[:3], TRIANGLE)
        assert np.allclose(mesh.normals[:3], [0, 0, 1])

    def test_a_zero_facet_normal_is_computed_from_the_corners(self):
        mesh = meshfiles.read_stl(ASCII_STL)
        assert np.allclose(mesh.normals[3:], [0, 0, 1])

    def test_binary(self):
        data = _binary_stl([TRIANGLE, TRIANGLE + 2], [[0, 0, 1], [0, 0, 1]])
        mesh = meshfiles.read_stl(data)
        assert mesh.positions.shape == (6, 3)
        assert np.allclose(mesh.positions[3:], TRIANGLE + 2)

    def test_binary_whose_header_starts_with_solid(self):
        data = _binary_stl([TRIANGLE], header=b'solid exported by a CAD tool')
        assert np.allclose(meshfiles.read_stl(data).positions, TRIANGLE)

    @pytest.mark.parametrize('data', [b'', b'solid x\nfacet normal 0 0 1\n'
                                      b'outer loop\nvertex 0 0 0\nendloop\nendfacet\n',
                                      b'\0' * 84 + b'\1\2'])
    def test_malformed(self, data):
        with pytest.raises(ValueError):
            meshfiles.read_stl(data)

    def test_loaded_from_a_gzipped_file(self, tmp_path):
        path = tmp_path / 'part.stl.gz'
        path.write_bytes(gzip.compress(ASCII_STL))
        mesh = _only(Loader.load(str(path)))
        assert len(mesh.positions) == 6
        assert mesh.solid


# --------------------------------------------------------------------------- #
# PLY
# --------------------------------------------------------------------------- #
ASCII_PLY = b"""ply
format ascii 1.0
comment made in the test
element vertex 4
property float x
property float y
property float z
property uchar red
property uchar green
property uchar blue
property float s
property float t
element face 1
property list uchar int vertex_indices
end_header
0 0 0 255 0 0 0 0
1 0 0 0 255 0 1 0
1 1 0 0 0 255 1 1
0 1 0 255 255 255 0 1
4 0 1 2 3
"""


def _binary_ply(order='<', faces=((0, 1, 2), (0, 2, 3)), extra_element=True):
    endian = {'<': 'binary_little_endian', '>': 'binary_big_endian'}[order]
    header = ['ply', 'format %s 1.0' % endian, 'element vertex 4',
              'property float x', 'property float y', 'property float z',
              'property float nx', 'property float ny', 'property float nz']
    if extra_element:
        header += ['element material 1', 'property uchar shininess',
                   'property list uchar float tags']
    header += ['element face %d' % len(faces),
               'property list uchar uint vertex_indices', 'end_header']
    body = bytearray()
    corners = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
    for corner in corners:
        body += struct.pack(order + '6f', *corner, 0, 0, 1)
    if extra_element:
        body += struct.pack(order + 'BB2f', 7, 2, 0.5, 0.25)
    for face in faces:
        body += struct.pack(order + 'B%dI' % len(face), len(face), *face)
    return ('\n'.join(header) + '\n').encode() + bytes(body)


class TestPLY:
    def test_ascii_polygon_colours_and_texture_coordinates(self):
        mesh = meshfiles.read_ply(ASCII_PLY)
        assert mesh.indices.tolist() == [0, 1, 2, 0, 2, 3]
        assert np.allclose(mesh.colors[1], [0, 1, 0, 1])
        assert np.allclose(mesh.texcoords[2], [1, 1])
        assert mesh.normals is None

    @pytest.mark.parametrize('order', ['<', '>'])
    def test_binary_with_an_element_it_does_not_use(self, order):
        mesh = meshfiles.read_ply(_binary_ply(order))
        assert mesh.indices.tolist() == [0, 1, 2, 0, 2, 3]
        assert np.allclose(mesh.normals, [0, 0, 1])
        assert np.allclose(mesh.positions[2], [1, 1, 0])

    def test_binary_faces_of_mixed_sizes(self):
        mesh = meshfiles.read_ply(_binary_ply(faces=((0, 1, 2), (0, 1, 2, 3))))
        assert mesh.indices.tolist() == [0, 1, 2, 0, 1, 2, 0, 2, 3]

    def test_points_only(self):
        data = b'ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\n' \
               b'property float y\nproperty float z\nend_header\n0 0 0\n1 1 1\n'
        mesh = meshfiles.read_ply(data)
        assert mesh.indices is None and mesh.points

    @pytest.mark.parametrize('data', [
        b'ply\nformat binary_middle_endian 1.0\nend_header\n',
        b'ply\nformat ascii 1.0\nelement vertex 1\nproperty float y\nend_header\n0\n',
        b'ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\nproperty float y\n'
        b'property float z\nend_header\n0 0 0\n',
        b'ply\nformat ascii 1.0\nelement vertex 1\nproperty quad x\nend_header\n0\n',
        b'not a ply file',
        _binary_ply()[:-3],
    ], ids=['format', 'no-x', 'short-ascii', 'type', 'magic', 'short-binary'])
    def test_malformed(self, data):
        with pytest.raises(ValueError):
            meshfiles.read_ply(data)

    def test_face_index_out_of_range(self):
        with pytest.raises(ValueError, match='out of range'):
            meshfiles.read_ply(_binary_ply(faces=((0, 1, 9),)))


def _splat_ply(count=2, degree=1):
    rest = 3 * ((degree + 1) ** 2 - 1)
    names = (['x', 'y', 'z', 'nx', 'ny', 'nz', 'f_dc_0', 'f_dc_1', 'f_dc_2']
             + ['f_rest_%d' % i for i in range(rest)]
             + ['opacity', 'scale_0', 'scale_1', 'scale_2',
                'rot_0', 'rot_1', 'rot_2', 'rot_3'])
    header = ['ply', 'format binary_little_endian 1.0', 'element vertex %d' % count]
    header += ['property float %s' % name for name in names] + ['end_header']
    rows = np.zeros((count, len(names)), np.float32)
    column = {name: index for index, name in enumerate(names)}
    for splat in range(count):
        rows[splat, column['x']] = splat
        rows[splat, column['f_dc_0']] = 0.5
        rows[splat, column['opacity']] = 0.0              # sigmoid -> 0.5
        rows[splat, column['scale_0']] = np.log(2.0)      # exp -> 2
        rows[splat, column['rot_0']] = 2.0                # w, unnormalised
        for index in range(rest):
            rows[splat, column['f_rest_%d' % index]] = index
    return ('\n'.join(header) + '\n').encode() + rows.tobytes()


class TestSplatPLY:
    def test_read_as_gaussian_splats(self):
        splats = meshfiles.read_ply(_splat_ply())
        assert isinstance(splats, GaussianSplats)
        assert np.allclose(np.asarray(splats.positions)[:, 0], [0, 1])
        assert np.allclose(np.asarray(splats.opacities), 0.5)
        assert np.allclose(np.asarray(splats.scales)[0], [2, 1, 1])
        # (w, x, y, z) unnormalised in the file, (x, y, z, w) unit in the node.
        assert np.allclose(np.asarray(splats.orientations)[0], [0, 0, 0, 1])
        assert np.allclose(np.asarray(splats.sphericalHarmonicsDegree0Coef0)[0],
                           [0.5, 0, 0])

    def test_higher_degrees_are_channel_major_in_the_file(self):
        splats = meshfiles.read_ply(_splat_ply(degree=1))
        # f_rest holds the three degree-1 coefficients of red, then of green,
        # then of blue: coefficient k of channel c is f_rest[c * 3 + k].
        assert np.allclose(np.asarray(splats.sphericalHarmonicsDegree1Coef0)[0], [0, 3, 6])
        assert np.allclose(np.asarray(splats.sphericalHarmonicsDegree1Coef2)[0], [2, 5, 8])

    def test_degree_three(self):
        splats = meshfiles.read_ply(_splat_ply(degree=3))
        assert np.allclose(np.asarray(splats.sphericalHarmonicsDegree3Coef6)[0],
                           [14, 29, 44])

    def test_loaded_as_a_scene(self, tmp_path):
        path = tmp_path / 'room.ply'
        path.write_bytes(_splat_ply())
        _only(Loader.load(str(path)), GaussianSplats)


# --------------------------------------------------------------------------- #
# OFF
# --------------------------------------------------------------------------- #
class TestOFF:
    def test_polygons(self):
        mesh = meshfiles.read_off(b'OFF\n# a square\n4 1 0\n0 0 0\n1 0 0\n1 1 0\n'
                                  b'0 1 0\n4 0 1 2 3\n')
        assert mesh.indices.tolist() == [0, 1, 2, 0, 2, 3]

    def test_vertex_colours(self):
        mesh = meshfiles.read_off(b'COFF\n3 1 0\n0 0 0 255 0 0 255\n1 0 0 0 255 0 255\n'
                                  b'0 1 0 0 0 255 255\n3 0 1 2\n')
        assert np.allclose(mesh.colors[1], [0, 1, 0, 1])

    def test_vertex_normals_and_float_colours(self):
        # Each vertex: position, normal, colour, in that order.
        mesh = meshfiles.read_off(b'CNOFF\n3 1 0\n0 0 0 0 0 1 0.5 0.5 0.5 1\n'
                                  b'1 0 0 0 0 1 0.5 0.5 0.5 1\n0 1 0 0 0 1 0.5 0.5 0.5 1\n'
                                  b'3 0 1 2\n')
        assert np.allclose(mesh.colors[0], [0.5, 0.5, 0.5, 1])
        assert np.allclose(mesh.normals, [0, 0, 1])

    def test_face_colours_give_each_face_its_own_corners(self):
        mesh = meshfiles.read_off(b'OFF\n4 2 0\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n'
                                  b'3 0 1 2 255 0 0\n3 0 2 3 0 0 255\n')
        assert len(mesh.positions) == 6
        assert np.allclose(mesh.colors[:3], [1, 0, 0, 1])
        assert np.allclose(mesh.colors[3:], [0, 0, 1, 1])

    def test_a_face_without_a_colour_among_coloured_ones_is_grey(self):
        mesh = meshfiles.read_off(b'OFF\n4 2 0\n0 0 0\n1 0 0\n1 1 0\n0 1 0\n'
                                  b'3 0 1 2 1.0 0.0 0.0 1.0\n3 0 2 3 7\n')
        assert np.allclose(mesh.colors[:3], [1, 0, 0, 1])
        assert np.allclose(mesh.colors[3:], 0.666)

    def test_the_keyword_is_optional(self):
        mesh = meshfiles.read_off(b'3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n')
        assert mesh.indices.tolist() == [0, 1, 2]

    def test_counts_on_the_keyword_line(self):
        mesh = meshfiles.read_off(b'OFF 3 1 0\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n')
        assert len(mesh.positions) == 3

    def test_texture_coordinates(self):
        mesh = meshfiles.read_off(b'STOFF\n3 1 0\n0 0 0 0 0\n1 0 0 1 0\n0 1 0 0 1\n3 0 1 2\n')
        assert np.allclose(mesh.texcoords[2], [0, 1])

    @pytest.mark.parametrize('data', [b'', b'OFF\n3 1\n', b'OFF\n3 1 0\n0 0 0\n',
                                      b'MESH\n', b'OFF BINARY\n', b'COFF\n1 0 0\n0 0 0\n',
                                      b'4OFF\n1 0 0\n0 0 0 0\n', b'OFF\n3 1 0\n0 0 0\n'
                                      b'1 0 0\n0 1 0\n3 0 1 7\n'])
    def test_malformed(self, data):
        with pytest.raises(ValueError):
            meshfiles.read_off(data)


# --------------------------------------------------------------------------- #
# Scenes and registration
# --------------------------------------------------------------------------- #
class TestScenes:
    def test_a_model_without_colours_is_light_grey(self, tmp_path):
        path = tmp_path / 'part.stl'
        path.write_bytes(ASCII_STL)
        scene = Loader.load(str(path))
        (shape,) = [child for child in scene.children if hasattr(child, 'geometry')]
        assert np.allclose(shape.appearance.material.baseColor, 0.8)

    def test_vertex_colours_are_drawn_unscaled(self, tmp_path):
        path = tmp_path / 'square.ply'
        path.write_bytes(ASCII_PLY)
        scene = Loader.load(str(path))
        (shape,) = [child for child in scene.children if hasattr(child, 'geometry')]
        assert np.allclose(shape.appearance.material.baseColor, 1.0)

    def test_points_draw_as_points(self, tmp_path):
        path = tmp_path / 'cloud.ply'
        path.write_bytes(b'ply\nformat ascii 1.0\nelement vertex 2\nproperty float x\n'
                         b'property float y\nproperty float z\nend_header\n0 0 0\n1 1 1\n')
        assert _only(Loader.load(str(path))).draw_mode == 0

    def test_loads_from_memory(self):
        assert len(_only(Loader.loads(ASCII_STL, 'part.stl')).positions) == 6

    @pytest.mark.parametrize('name, adapter', [
        ('part.stl', 'stl'), ('part.STL', 'stl'), ('part.stl.gz', 'stl'),
        ('scan.ply', 'ply'), ('scan.ply.gz', 'ply'), ('shape.off', 'off'),
        ('avatar.vrm', 'gltf'), ('world.x3djz', 'x3d'), ('model.obj.gz', 'obj'),
    ])
    def test_registered(self, name, adapter):
        assert formats.adapter_for(name).name == adapter

    @pytest.mark.parametrize('content_type, adapter', [
        ('model/stl', 'stl'), ('model/ply', 'ply'), ('model/off', 'off'),
        ('model/vrm', 'gltf')])
    def test_registered_content_types(self, content_type, adapter):
        assert formats.adapter_for('download', content_type).name == adapter
