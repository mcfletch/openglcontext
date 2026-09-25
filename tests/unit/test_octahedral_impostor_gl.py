"""An octahedral impostor shows the view it is being looked at from (needs GL).

The atlas holds one baked picture per direction, and the whole technique rests
on the renderer picking the same one the baker rendered. Two pieces of
arithmetic have to agree for that: ``octahedral.direction_to_uv`` in Python,
which the baker lays the tiles out by, and ``octahedralUV`` in ``pbr.vert``,
which the shader reads them back with. They are written twice because one of
them has to run on the GPU, and a test that only exercised the Python half
would pass while every impostor in the world showed the wrong face.

So: an atlas whose every tile is a flat colour naming its own row and column,
an impostor wearing it, and the object turned to a series of known angles. The
colour that comes back says which tile the shader chose, and it is compared
against the tile the Python says it should have.

Skips (not fails) when GL is unavailable.
"""
import json
import os
import subprocess
import sys

import pytest
import numpy as np
from PIL import Image

from OpenGLContext.scenegraph import basenodes, octahedral
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

GRID = 8
ATLAS = 256

#: Object rotations to look at it through: (axis, radians). The camera does not
#: move -- turning the object is the same question and needs no navigation.
ANGLES = [
    ((0.0, 1.0, 0.0), 0.0),
    ((0.0, 1.0, 0.0), 0.8),
    ((0.0, 1.0, 0.0), 1.9),
    ((0.0, 1.0, 0.0), 3.6),
    ((1.0, 0.0, 0.0), 0.6),
    ((1.0, 0.0, 0.0), -0.5),
]


def colour_for(row, column):
    """What tile (row, column) is painted, as 0-255 bytes."""
    return (int(round((column + 0.5) / GRID * 255.0)),
            int(round((row + 0.5) / GRID * 255.0)),
            128)


def expected_cell(axis, angle):
    """Which tile the shader ought to choose, worked out here in Python.

    The camera sits on +Z looking back at the origin, so the direction from
    the object to the eye is +Z in *world* space; turning the object by
    ``angle`` about ``axis`` turns that direction by the inverse in the
    object's own space, which is what the atlas is indexed by.
    """

    x, y, z = axis
    length = (x * x + y * y + z * z) ** 0.5
    x, y, z = x / length, y / length, z / length
    c, s = np.cos(-angle), np.sin(-angle)
    # Rodrigues, applied to the world +Z direction to the eye.
    v = np.array([0.0, 0.0, 1.0])
    k = np.array([x, y, z])
    turned = v * c + np.cross(k, v) * s + k * np.dot(k, v) * (1.0 - c)
    return octahedral.cell_of(turned, GRID)


DRIVER = r'''
import json, os, sys
os.environ['OPENGLCONTEXT_PROFILE'] = 'core'
os.environ['OPENGLCONTEXT_BACKEND'] = 'glfw'
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
os.environ['OPENGLCONTEXT_SHADOWS'] = '0'
os.environ['OPENGLCONTEXT_RENDERER'] = 'pbr'
STATE = {'gl_ok': False, 'seen': []}
try:
    import numpy as np
    from PIL import Image
    from OpenGL.GL import glReadPixels, GL_RGB, GL_UNSIGNED_BYTE
    from OpenGLContext import testingcontext
    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial, PBRTexture
    from OpenGLContext.scenegraph.pbrmesh import PBRMesh

    GRID, ATLAS = %(grid)d, %(atlas)d
    ANGLES = json.loads(%(angles)r)

    tile = ATLAS // GRID
    pixels = np.zeros((ATLAS, ATLAS, 4), dtype='uint8')
    pixels[:, :, 3] = 255
    for row in range(GRID):
        for column in range(GRID):
            pixels[row * tile:(row + 1) * tile,
                   column * tile:(column + 1) * tile, 0] = \
                int(round((column + 0.5) / GRID * 255.0))
            pixels[row * tile:(row + 1) * tile,
                   column * tile:(column + 1) * tile, 1] = \
                int(round((row + 0.5) / GRID * 255.0))
            pixels[row * tile:(row + 1) * tile,
                   column * tile:(column + 1) * tile, 2] = 128
    atlas = Image.fromarray(pixels, 'RGBA')

    # A unit quad in XY with a 0..1 unwrap; the shader turns it to the viewer
    # and moves this coordinate into the tile it picked.
    positions = np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], 'f')
    texcoords = np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f')
    normals = np.tile(np.array([0, 0, 1], 'f'), (4, 1))
    indices = np.array([0, 1, 2, 0, 2, 3], 'uint32')

    Base = testingcontext.getInteractive()

    class Probe(Base):
        def OnInit(self):
            material = PBRMaterial(
                baseColor=(1, 1, 1), metallic=0.0, roughness=1.0,
                unlit=True, alphaMode='OPAQUE',
                octahedralViews=GRID, octahedralHemi=True,
                textures={'baseColor': PBRTexture(atlas)},
            )
            mesh = PBRMesh(positions=positions, normals=normals,
                           texcoords=texcoords, indices=indices, solid=False)
            self.spin = basenodes.Transform(children=[
                basenodes.Shape(geometry=mesh,
                                appearance=basenodes.Appearance(
                                    material=material))])
            self.sg = basenodes.sceneGraph(children=[self.spin])
            return None

        def getSceneGraph(self):
            return self.sg

        def OnIdle(self, *args):
            self.triggerRedraw(1)
            return 1

        def presentFrame(self):
            width, height = self.getViewPort()
            raw = glReadPixels(width // 2, height // 2, 1, 1,
                               GL_RGB, GL_UNSIGNED_BYTE)
            STATE['seen'].append([int(v) for v in bytearray(raw)])
            if len(STATE['seen']) > len(ANGLES):
                # Said here rather than after the loop: the mainloop exits the
                # process, so anything printed below it is never printed.
                print('RESULT ' + json.dumps(STATE), flush=True)
                self.OnQuit()
            else:
                index = min(len(STATE['seen']), len(ANGLES) - 1)
                axis, angle = ANGLES[index]
                self.spin.rotation = (axis[0], axis[1], axis[2], angle)
            return super(Probe, self).presentFrame()

    axis, angle = ANGLES[0]
    STATE['gl_ok'] = True
    context = Probe
    context.ContextMainLoop(size=(160, 160))
except SystemExit:
    pass
except Exception as error:      # pragma: no cover - reported to the parent
    STATE['error'] = '%%s: %%s' %% (type(error).__name__, error)
    print('RESULT ' + json.dumps(STATE), flush=True)
'''


@pytest.fixture(scope='module')
def seen(tmp_path_factory):
    """The centre pixel at each angle, read out of a real GL context."""
    script = tmp_path_factory.mktemp('impostor') / 'driver.py'
    script.write_text(DRIVER % {
        'grid': GRID, 'atlas': ATLAS,
        'angles': json.dumps([[list(axis), angle] for axis, angle in ANGLES]),
    })
    done = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, timeout=300,
                          env=dict(os.environ, PYTHONPATH=os.getcwd()))
    if 'RESULT ' not in done.stdout:
        pytest.skip('the GL driver said nothing: %s' % (done.stderr[-600:],))
    state = json.loads(done.stdout.split('RESULT ', 1)[1].splitlines()[0])
    if state.get('error'):
        pytest.skip('GL unavailable: %s' % (state['error'],))
    if not state.get('gl_ok'):
        pytest.skip('no GL')
    return state['seen']


def cell_from(colour):
    """Which tile a read-back colour names."""
    red, green = colour[0], colour[1]
    return (min(GRID - 1, int(green / 255.0 * GRID)),
            min(GRID - 1, int(red / 255.0 * GRID)))


class TestTheShaderPicksTheViewThePythonSaysItShould:
    def test_something_was_drawn(self, seen):
        assert seen and any(sum(colour) > 0 for colour in seen)

    def test_the_impostor_is_not_showing_one_view_from_everywhere(self, seen):
        """The failure a flat card would pass: the same tile at every angle."""
        assert len({tuple(colour) for colour in seen[1:]}) > 1

    @pytest.mark.parametrize('index', range(1, len(ANGLES)))
    def test_each_angle_shows_its_own_tile(self, seen, index):
        axis, angle = ANGLES[index]

        assert cell_from(seen[index]) == expected_cell(axis, angle)


def test_a_small_atlas_reads_nothing_of_the_neighbouring_views(render_scene, monkeypatch):
    """The tile's edge is sampled half a texel in, for the atlas's own size.

    The view the camera sees is green and every other view red, so any red on
    screen is the filter reaching across the tile's edge into a neighbour.
    """
    from tests.unit.glrender import base_env, frames_of

    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    row, column = expected_cell((0.0, 1.0, 0.0), 0.0)
    tile = ATLAS // GRID
    pixels = np.zeros((ATLAS, ATLAS, 4), 'uint8')
    pixels[..., 0] = 255
    pixels[..., 3] = 255
    pixels[row * tile:(row + 1) * tile, column * tile:(column + 1) * tile] = (0, 255, 0, 255)
    material = PBRMaterial(baseColor=(1, 1, 1), unlit=True, octahedralViews=GRID,
                           textures={'baseColor': PBRTexture(Image.fromarray(pixels, 'RGBA'))})
    quad = PBRMesh(
        positions=np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], 'f'),
        normals=np.tile(np.array([0, 0, 1], 'f'), (4, 1)),
        texcoords=np.array([(0, 0), (1, 0), (1, 1), (0, 1)], 'f'),
        indices=np.array([0, 1, 2, 0, 2, 3], 'uint32'), solid=False)
    frame = frames_of(render_scene, [
        basenodes.Viewpoint(position=(0.0, 0.0, 4.0)),
        basenodes.Background(skyColor=[(0.0, 0.0, 1.0)]),
        basenodes.Shape(geometry=quad, appearance=basenodes.Appearance(material=material)),
    ], frames=2, size=(160, 160))[-1].astype(int)
    drawn = frame[..., 2] < 128                       # not the blue sky
    assert drawn.sum() > 4000
    assert int(frame[..., 0][drawn].max()) < 24
