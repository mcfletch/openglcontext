"""X_ITE's BlendMode and DepthMode: an appearance's own blend and depth state.

A BlendMode's factors and equations are OpenGL's names; one OpenGL does not
have reads as the field's default. A shape whose appearance has one is drawn
with the blended shapes and by itself; a DepthMode sets the depth test, the
comparison, the writes, the range and the polygon offset for its draw.
"""
import numpy as np
import pytest
from OpenGL import GL

from OpenGLContext.passes.instancing import drawn_alone
from OpenGLContext.scenegraph import rendermodes
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial


def test_the_default_blend_is_x_ite_s():
    state = rendermodes.blend_state(rendermodes.BlendMode())
    assert state[:6] == (GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ONE,
                         GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_FUNC_ADD, GL.GL_FUNC_ADD)
    assert state.color == (0.0, 0.0, 0.0, 0.0)


def test_names_read_as_opengl_s_and_an_unknown_one_as_the_default():
    mode = rendermodes.BlendMode(sourceColorFactor='ONE', destinationColorFactor='ONE',
                                 colorEquation='MAX', alphaEquation='SIDEWAYS',
                                 blendColor=(0.5, 0.25, 0.0, 1.0))
    state = rendermodes.blend_state(mode)
    assert state.source_color == GL.GL_ONE and state.destination_color == GL.GL_ONE
    assert state.color_equation == GL.GL_MAX
    assert state.alpha_equation == GL.GL_FUNC_ADD
    assert state.color == (0.5, 0.25, 0.0, 1.0)


def test_a_depth_mode_reads_its_fields():
    state = rendermodes.depth_state(rendermodes.DepthMode(
        depthFunction='GREATER', depthMask=False, depthTest=False,
        depthRange=(0.0, 0.5), polygonOffset=(1.0, 2.0)))
    assert state == (False, GL.GL_GREATER, False, (0.0, 0.5), (1.0, 2.0))
    assert rendermodes.depth_state(rendermodes.DepthMode(depthFunction='NOPE')).comparison \
        == GL.GL_LEQUAL


def test_a_blend_mode_makes_the_appearance_blended_and_drawn_alone():
    plain = Appearance(material=PhysicalMaterial())
    blended = Appearance(material=PhysicalMaterial(), blendMode=rendermodes.BlendMode())
    depth = Appearance(material=PhysicalMaterial(), depthMode=rendermodes.DepthMode())
    assert not plain.sortKey(None, None)[0]
    assert blended.sortKey(None, None)[0]
    assert not depth.sortKey(None, None)[0]
    assert not drawn_alone(plain)
    assert drawn_alone(blended) and drawn_alone(depth)


QUADS = b'''<X3D version="4.0"><head><component name="X_ITE" level="1"/></head><Scene>
  <Background skyColor="0.5 0.5 0.5"/><Viewpoint position="0 0 4"/>
  <Shape><Appearance><UnlitMaterial emissiveColor="1 0 0"/></Appearance>
    <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
      <Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/></IndexedTriangleSet></Shape>
  <Transform translation="0 0 -0.5"><Shape><Appearance>
    <UnlitMaterial emissiveColor="0 0 1"/>%s</Appearance>
    <IndexedTriangleSet index="0 1 2 0 2 3" solid="false">
      <Coordinate point="-1 -1 0 1 -1 0 1 1 0 -1 1 0"/></IndexedTriangleSet></Shape></Transform>
</Scene></X3D>'''


def centre(appearance):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(QUADS % appearance, 'modes.x3d')
    with scene_context(scene, size=(32, 32)) as context:
        return drawn_image(context)[16, 16].astype(int)


def test_a_depth_mode_with_no_test_draws_over_what_is_in_front(gl_context):
    assert centre(b'')[0] > 200
    over = centre(b'<DepthMode depthTest="false"/>')
    assert over[2] > 200 and over[0] < 50, over


def test_an_additive_blend_mode_adds_to_the_frame(gl_context):
    behind = b'<BlendMode sourceColorFactor="ONE" destinationColorFactor="ONE"/>' \
             b'<DepthMode depthTest="false"/>'
    added = centre(behind)
    assert added[0] > 200 and added[2] > 200, added


def test_the_state_is_put_back_after_the_draw(gl_context):
    appearance = Appearance(blendMode=rendermodes.BlendMode(sourceColorFactor='ONE'),
                            depthMode=rendermodes.DepthMode(depthMask=False,
                                                            depthFunction='ALWAYS'))
    GL.glDisable(GL.GL_BLEND)
    GL.glEnable(GL.GL_DEPTH_TEST)
    GL.glDepthFunc(GL.GL_LESS)
    GL.glDepthMask(True)
    with rendermodes.applied(appearance):
        assert GL.glIsEnabled(GL.GL_BLEND)
        assert int(GL.glGetIntegerv(GL.GL_DEPTH_FUNC)) == GL.GL_ALWAYS
        assert not GL.glGetBooleanv(GL.GL_DEPTH_WRITEMASK)
    assert not GL.glIsEnabled(GL.GL_BLEND)
    assert int(GL.glGetIntegerv(GL.GL_DEPTH_FUNC)) == GL.GL_LESS
    assert GL.glGetBooleanv(GL.GL_DEPTH_WRITEMASK)
    assert np.allclose(GL.glGetFloatv(GL.GL_DEPTH_RANGE), (0.0, 1.0))


@pytest.mark.parametrize('encoding', ['xml', 'classic', 'json'])
def test_the_modes_are_written_and_read_back(encoding):
    from vrml import x3d as vrml_x3d  # noqa: PLC0415 kept with its use
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    from vrml.x3d.scene import X3DScene  # noqa: PLC0415 kept with its use

    from OpenGLContext.loaders.x3d import prototypes  # noqa: PLC0415 kept with its use
    appearance = Appearance(blendMode=rendermodes.BlendMode(colorEquation='MAX'),
                            depthMode=rendermodes.DepthMode(polygonOffset=(1.0, 1.0)))
    scene = X3DScene(children=[x3d.Shape(appearance=appearance, geometry=x3d.Box())])
    read = vrml_x3d.loads(vrml_x3d.dumps(scene, encoding=encoding), prototypes=prototypes())
    found = read.children[0].appearance
    assert isinstance(found.blendMode, rendermodes.BlendMode)
    assert found.blendMode.colorEquation == 'MAX'
    assert list(found.depthMode.polygonOffset) == [1.0, 1.0]


def test_a_depth_mode_is_tested_against_the_rest_of_the_scene(gl_context):
    # GREATER passes only where something nearer is already drawn: the red
    # square in front, drawn first whatever order the shapes come in.
    behind = centre(b'<DepthMode depthFunction="GREATER"/>')
    assert behind[2] > 200 and behind[0] < 50, behind
