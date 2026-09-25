"""The ground drawn through a real context: which layer lands where.

A tile of a streamed world is placed by the tileset's transform, and the blend
of layers is read from world XZ through the ``uModel`` the patch is given. These
draw one small patch of ground, placed by a tile's transform, looking straight
down at it, and read back which layer's colour it came out as.
"""
import types

import numpy as np
import pytest
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_RGB, GL_UNSIGNED_BYTE,
    glClear, glClearColor, glGetUniformfv, glGetUniformLocation, glReadPixels,
    glViewport,
)
from PIL import Image
from OpenGL import GL

from OpenGLContext.scenegraph.terrain import ground
from OpenGLContext.scenegraph.terrain.ground import (
    GROUND_MATERIAL, GroundPatch, GroundShading,
)
from OpenGLContext.loaders.tiles3d.gltf_uploader import GLTileUploader
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.shape import Shape

EXTENT = 100.0
SIZE = 32


@pytest.fixture
def gl_context(gl_window):
    return gl_window('ground', size=(SIZE, SIZE))


def _solid(tmp_path, name, colour):
    path = tmp_path / ('%s.png' % (name,))
    Image.new('RGBA', (4, 4), colour).save(path)
    return str(path)


def _shading(tmp_path):
    """Red ground on the western half of the world, green on the eastern."""
    red = _solid(tmp_path, 'red', (255, 0, 0, 255))
    green = _solid(tmp_path, 'green', (0, 255, 0, 255))
    control = np.zeros((4, 4, 4), 'u1')
    control[:, :2, 0] = 255                   # layer 0, west
    control[:, 2:, 1] = 255                   # layer 1, east
    return GroundShading(
        extent=EXTENT, layers=['west', 'east'],
        control=Image.fromarray(control, 'RGBA'),
        shading=np.ones((4, 4), 'f'), sun=(0.0, -1.0, 0.0),
        material_fn=lambda name, res: {'color': red if name == 'west' else green})


def _quad():
    """A metre of flat ground about the origin, facing up, drawn from both sides."""
    corners = np.array([[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]], 'f')
    vertices = np.concatenate([corners, np.tile([0, 1, 0], (4, 1))], 1).astype('f')
    return vertices, np.array([0, 1, 2, 0, 2, 3, 0, 2, 1, 0, 3, 2], np.uint32)


def _looking_down(eye_x):
    """A modelview, in the scenegraph's row-vector form, from above ``eye_x``."""
    view = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0],
                     [0, 0, 0, 1]], 'd')
    view[3, :3] = (-eye_x, 0.0, -10.0)
    return view


def _ortho():
    near, far, half = 0.1, 100.0, 2.0
    projection = np.diag([1 / half, 1 / half, -2 / (far - near), 1.0])
    projection[2, 3] = -(far + near) / (far - near)
    return projection.T                       # as GL reads the bytes


def _draw(patch, model):
    mode = types.SimpleNamespace(
        matrix=model @ _looking_down(25.0), projection=_ortho(),
        visible=True, shadow_pass=False, current_program=lambda: 0)
    glViewport(0, 0, SIZE, SIZE)
    glClearColor(0, 0, 0, 1)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    patch.render(mode)
    pixels = glReadPixels(SIZE // 2, SIZE // 2, 1, 1, GL_RGB, GL_UNSIGNED_BYTE)
    return np.frombuffer(pixels, 'u1')[:3].astype(int)


def test_a_patch_placed_east_is_drawn_with_the_eastern_layer(gl_context, tmp_path):
    shading = _shading(tmp_path)
    model = np.eye(4)
    model[3, :3] = (25.0, 0.0, 0.0)           # row-vector, as mode.matrix is
    vertices, indices = _quad()
    patch = GroundPatch(shading, vertices, indices, model=model)
    try:
        red, green, _blue = _draw(patch, model)
        assert green > 40 and green > 2 * red
    finally:
        patch.dispose()
        shading.dispose()


def test_a_tile_placed_by_its_transform_reads_the_ground_there(gl_context, tmp_path):
    """The uploader is handed the tile's column-vector transform, as the
    tileset states it, and the ground drawn under it is read where it lands."""
    shading = _shading(tmp_path)
    vertices, indices = _quad()
    material = PBRMaterial(baseColor=(1.0, 1.0, 1.0))
    mesh = PBRMesh(positions=vertices[:, :3], normals=vertices[:, 3:],
                   indices=indices, material=material)
    group = Group(children=[Shape(geometry=mesh,
                                  appearance=Appearance(material=material))])
    placed = np.eye(4)
    placed[:3, 3] = (25.0, 0.0, 0.0)          # column-vector: M . p
    uploader = GLTileUploader()
    uploader.ground = shading
    uploader.upload(types.SimpleNamespace(content_transform=placed),
                    (types.SimpleNamespace(group=group,
                                           materials={GROUND_MATERIAL: material}), 0))
    patch = group.children[0].geometry
    assert isinstance(patch, GroundPatch)
    try:
        red, green, _blue = _draw(patch, placed.T)
        assert green > 40 and green > 2 * red
    finally:
        patch.dispose()
        shading.dispose()


def test_the_constants_are_sent_once_not_per_patch(gl_context, tmp_path):
    """What does not change from patch to patch is set when the program is
    made; a patch sends only where it is and how it is seen."""
    shading = _shading(tmp_path)
    vertices, indices = _quad()
    patch = GroundPatch(shading, vertices, indices)
    sent = []
    original = GL.glUniform1f

    def counting(*args):
        sent.append(args)
        return original(*args)
    try:
        _draw(patch, np.eye(4))
        ground.glUniform1f, before = counting, ground.glUniform1f
        try:
            _draw(patch, np.eye(4))
        finally:
            ground.glUniform1f = before
        assert sent == []
        program = shading._gl['prog']
        found = np.zeros(1, 'f')
        glGetUniformfv(program, glGetUniformLocation(program, 'detailScale'), found)
        assert found[0] == pytest.approx(ground.DETAIL_SCALE)
    finally:
        patch.dispose()
        shading.dispose()
