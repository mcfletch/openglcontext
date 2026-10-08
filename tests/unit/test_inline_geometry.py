"""Tests for InlineGeometry, a geometry node drawing the triangles of a file

The file is any format an Inline reads; its shapes are placed by their
transforms and joined into one mesh, drawn with the holding Shape's
appearance.
"""
import numpy as np

from OpenGLContext.loaders import background
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.inlinegeometry import InlineGeometry

PATIENCE = 20.0

OBJ = b'''v -1 -1 0
v 1 -1 0
v 1 1 0
v -1 1 0
f 1 2 3 4
'''

MOVED = (b'<X3D version="4.0"><Scene><Transform translation="10 0 0"><Shape>'
         b'<IndexedTriangleSet index="0 1 2"><Coordinate point="0 0 0 1 0 0 0 1 0"/>'
         b'</IndexedTriangleSet></Shape></Transform></Scene></X3D>')


def world(url, fields=''):
    return ('<X3D version="4.0"><Scene><Viewpoint position="0 0 4"/><Shape><Appearance>'
            '<UnlitMaterial emissiveColor="1 1 1"/></Appearance>'
            '<InlineGeometry url=\'"%s"\' %s/></Shape></Scene></X3D>' % (url, fields)).encode()


def read_world(tmp_path, name, data, fields=''):
    """A world naming `name`, and its InlineGeometry, once its read has finished"""
    (tmp_path / name).write_bytes(data)
    (tmp_path / 'world.x3d').write_bytes(world(name, fields))
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    assert background.wait_for_idle(PATIENCE)
    found = scene.children[1].geometry
    assert isinstance(found, InlineGeometry)
    return scene, found


def read(tmp_path, name, data, fields=''):
    """The InlineGeometry of a world naming `name`, once its read has finished"""
    return read_world(tmp_path, name, data, fields)[1]


def test_an_obj_files_faces_are_its_triangles(tmp_path):
    found = read(tmp_path, 'quad.obj', OBJ)
    mesh = found.mesh()
    assert len(mesh.indices) == 6
    assert np.allclose(mesh.positions[:, 2], 0)


def test_a_documents_shapes_are_placed_by_their_transforms(tmp_path):
    mesh = read(tmp_path, 'part.x3d', MOVED).mesh()
    assert np.allclose(mesh.positions[:, 0].min(), 10)


def test_solid_is_the_nodes_own(tmp_path):
    assert read(tmp_path, 'quad.obj', OBJ).mesh().solid is False
    assert read(tmp_path, 'quad.obj', OBJ, 'solid="true"').mesh().solid is True


def test_smooth_false_gives_each_triangle_its_own_normal(tmp_path):
    mesh = read(tmp_path, 'quad.obj', OBJ, 'smooth="false"').mesh()
    assert mesh.indices is None and len(mesh.positions) == 6


def test_nothing_is_drawn_before_the_read_or_where_load_is_false(tmp_path):
    _scene, found = read_world(tmp_path, 'quad.obj', OBJ, 'load="false"')
    assert found.mesh() is None
    found.load = True
    assert background.wait_for_idle(PATIENCE)
    assert found.mesh() is not None


def test_a_file_that_does_not_read_draws_nothing(tmp_path, caplog):
    (tmp_path / 'world.x3d').write_bytes(world('missing.obj'))
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    assert background.wait_for_idle(PATIENCE)
    assert scene.children[1].geometry.mesh() is None
    assert 'no triangles' in caplog.text


def test_the_shapes_bounds_follow_the_read(tmp_path):
    scene, found = read_world(tmp_path, 'quad.obj', OBJ, 'load="false"')
    (tmp_path / 'moved.x3d').write_bytes(MOVED)
    shape = scene.children[1]
    empty = shape.boundingVolume(None)
    found.url = ['moved.x3d']
    assert background.wait_for_idle(PATIENCE)
    found.load = True
    assert background.wait_for_idle(PATIENCE)
    assert shape.boundingVolume(None) is not empty
    assert np.allclose(shape.boundingVolume(None).getPoints()[:, 0].min(), 10)


def test_a_world_draws_the_files_triangles(gl_context, tmp_path):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    (tmp_path / 'quad.obj').write_bytes(OBJ)
    (tmp_path / 'world.x3d').write_bytes(world('quad.obj'))
    scene = Loader.load(str(tmp_path / 'world.x3d'))
    with scene_context(scene, size=(48, 48)) as context:
        context.OnDraw(force=1)
        assert background.wait_for_idle(PATIENCE)
        for _ in range(3):
            context.OnDraw(force=1)
        image = drawn_image(context)
    assert image[24, 24].min() > 200
