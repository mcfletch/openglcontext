"""X3D's TextureCoordinateGenerator: texture coordinates made in the vertex shader.

A composed geometry whose first texture coordinate set is a generator draws
with the generator's mode (``scenegraph.texgen``): from the vertex's own
position or normal (COORD, SPHERE_LOCAL, NOISE, SPHERE_REFLECT_LOCAL) or from
its position or normal in the camera's space (the others).
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import texgen


@pytest.mark.parametrize('mode', [
    'SPHERE', 'CAMERA_SPACE_NORMAL', 'CAMERA_SPACE_POSITION', 'CAMERA_SPACE_REFLECTION_VECTOR',
    'SPHERE_LOCAL', 'COORD', 'COORD_EYE', 'NOISE', 'NOISE_EYE', 'SPHERE_REFLECT',
    'SPHERE_REFLECT_LOCAL',
])
def test_every_mode_has_a_number_the_shader_knows(mode):
    assert texgen.MODES[mode] > 0


def test_the_shader_numbers_the_modes_as_texgen_does():
    import os  # noqa: PLC0415 kept with its use
    import re  # noqa: PLC0415 kept with its use

    from OpenGLContext.passes.shadersource import SHADER_DIR  # noqa: PLC0415 kept with its use
    with open(os.path.join(SHADER_DIR, '_texgen_inc.glsl'), encoding='utf-8') as stream:
        source = stream.read()
    found = {name: int(number) for name, number in
             re.findall(r'#define TEXGEN_([A-Z_]+)\s+(\d+)', source)}
    assert found == texgen.MODES
    assert not re.search(r'texGenMode == \d', source)


def test_a_generator_gives_its_mode_and_parameters():
    generator = x3d.TextureCoordinateGenerator(mode='NOISE', parameter=[2, 2, 2, 0.5, 0, 0])
    found = texgen.texgen_of(generator)
    assert found.mode == texgen.MODES['NOISE']
    assert found.parameters == pytest.approx((2, 2, 2, 0.5, 0, 0, 0, 0))


def test_a_coordinate_node_is_no_generator():
    assert texgen.texgen_of(x3d.TextureCoordinate(point=[(0, 0)])) is None
    assert texgen.texgen_of(None) is None


def test_a_composed_geometry_with_a_generator_carries_it():
    from OpenGLContext.scenegraph.basenodes import IndexedTriangleSet  # noqa: PLC0415 kept with its use
    geometry = IndexedTriangleSet(
        index=[0, 1, 2], coord=x3d.Coordinate(point=[(0, 0, 0), (1, 0, 0), (0, 1, 0)]),
        texCoord=x3d.TextureCoordinateGenerator(mode='COORD'))
    assert geometry.texGen.mode == texgen.MODES['COORD']
    assert geometry.buildMesh() is not None


CHECKER = b'''<PixelTexture repeatS="false" repeatT="false" image="2 1 3 0xFF0000 0x00FF00"/>'''


def drawn(mode, eye=b'0.5 0.5 2'):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(b'''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint position="''' + eye + b'''"/>
      <Shape><Appearance><Material diffuseColor="1 1 1"/>''' + CHECKER + b'''</Appearance>
        <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
          <Coordinate point="0 0 0 1 0 0 1 1 0 0 1 0"/>
          <TextureCoordinateGenerator mode="''' + mode + b'''"/>
        </IndexedTriangleSet></Shape>
    </Scene></X3D>''', 'scene.x3d')
    with scene_context(scene, size=(64, 64)) as context:
        return drawn_image(context).astype(int)


def test_coord_maps_the_texture_across_the_geometry(gl_context):
    image = drawn(b'COORD')
    left, right = image[32, 22], image[32, 42]
    assert left[0] > left[1] + 100
    assert right[1] > right[0] + 100


def test_a_camera_space_mode_draws_the_texture(gl_context):
    # Seen from x=0, the quad's camera-space x runs from 0 to 1 across it.
    image = drawn(b'CAMERA_SPACE_POSITION', eye=b'0 0.5 2')
    # Lit by the headlight: each colour of the texture appears somewhere.
    assert image.reshape(-1, 3).max(axis=0)[:2].min() > 100


def test_the_local_modes_are_given_the_camera_in_the_shapes_space(gl_context):
    """Worked out once a draw from its model-view, as the camera at the
    origin taken back into the shape's own space"""
    import ctypes  # noqa: PLC0415 kept with its use

    from OpenGL.GL import glGetUniformfv, glGetUniformLocation, glUseProgram  # noqa: PLC0415 GL
    from OpenGLContext.passes.pbrpass import PBRShaderProgram  # noqa: PLC0415 GL
    shader = PBRShaderProgram()
    assert shader.compile()
    glUseProgram(shader.program)
    modelview = np.identity(4)
    modelview[3, :3] = (1.0, -2.0, -5.0)          # the shape 5 ahead, 1 right, 2 down
    shader.set_texgen(texgen.TexGen(texgen.MODES['SPHERE_LOCAL'], (0.0,) * 8), modelview)
    value = (ctypes.c_float * 3)()
    glGetUniformfv(shader.program, glGetUniformLocation(shader.program, 'texGenLocalEye'), value)
    assert list(value) == pytest.approx([-1.0, 2.0, 5.0])
