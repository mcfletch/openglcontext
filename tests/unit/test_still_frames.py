"""A frame of a scene nothing has changed in makes, fills and compiles nothing.

Each scene is drawn until it has settled, and the next frame's GL
allocations, uploads and compiles are counted by
:func:`OpenGLContext.testing.stillframe.check_still_frame`. The scenes are the
ones a game's still moment is made of: VRML97 primitives through both
renderers, a field of shapes drawn as one instanced group, a mirror with
bloom, shadows, and text.
"""
import pytest

from OpenGLContext.passes.reflectionplanner import SETTLE_FRAMES
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import scene_context
from OpenGLContext.testing.stillframe import check_still_frame
from tests.unit.test_failing_layers import _mirror_room


@pytest.fixture(autouse=True)
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


def _look(colour):
    return basenodes.Appearance(material=basenodes.Material(diffuseColor=colour))


def _primitives():
    geometries = [basenodes.Box(), basenodes.Sphere(), basenodes.Cone(),
                  basenodes.Cylinder(), basenodes.IndexedFaceSet(
                      coord=basenodes.Coordinate(point=[(0, 0, 0), (1, 0, 0), (1, 1, 0)]),
                      coordIndex=[0, 1, 2, -1])]
    return [basenodes.Transform(translation=(2.5 * index - 5, 0, -8), children=[
        basenodes.Shape(geometry=geometry, appearance=_look((1, index / 4, 0)))])
        for index, geometry in enumerate(geometries)]


def _field():
    ball = basenodes.Shape(geometry=basenodes.Sphere(radius=0.3),
                           appearance=_look((0, 1, 0)))
    return [basenodes.Transform(translation=(x - 5, y - 5, -15), children=[ball])
            for x in range(10) for y in range(10)]


def _text():
    return [basenodes.Transform(translation=(-2, 0, -6), children=[basenodes.Shape(
        geometry=basenodes.Text(string=['still']), appearance=_look((1, 1, 1)))])]


PBR = {'OPENGLCONTEXT_RENDERER': 'pbr'}


@pytest.mark.parametrize('scene, environment', [
    pytest.param(_primitives, PBR, id='primitives-pbr'),
    pytest.param(_primitives, {'OPENGLCONTEXT_RENDERER': 'flat'}, id='primitives-flat'),
    pytest.param(_field, PBR, id='instanced-field'),
    pytest.param(_mirror_room, dict(PBR, OPENGLCONTEXT_PLANAR_REFLECTIONS='1',
                                    OPENGLCONTEXT_BLOOM='1'), id='mirror-bloom'),
    pytest.param(_primitives, dict(PBR, OPENGLCONTEXT_SHADOWS='1'), id='shadows'),
    pytest.param(_text, PBR, id='text'),
])
def test_a_still_frame_asks_nothing_new_of_gl(scene, environment):
    with scene_context(scene(), environment=environment) as context:
        work = check_still_frame(lambda: context.OnDraw(force=1),
                                 warmup=SETTLE_FRAMES + 2)
    assert work.allocations == work.uploads == work.compiles == 0
