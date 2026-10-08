"""A frame of a scene nothing has changed in makes, fills and compiles nothing.

Each scene is drawn until it has settled, and the next frame's GL
allocations, uploads and compiles are counted by
:func:`OpenGLContext.testing.stillframe.check_still_frame`. The scenes are the
ones a game's still moment is made of: VRML97 primitives through both
renderers, a field of shapes drawn as one instanced group, a mirror with
bloom, shadows, text, X3D's line, point and fill properties, and X3D's pick
sensors.
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


def _styled():
    """Lines, points and a polygon drawn by X3D's line, point and fill properties"""
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    points = basenodes.Coordinate(point=[(-2, -1, -6), (2, -1, -6), (2, 1, -6), (-2, 1, -6)])
    look = basenodes.Appearance(
        material=basenodes.Material(diffuseColor=(1, 0, 0), emissiveColor=(1, 1, 1)),
        lineProperties=x3d.LineProperties(linetype=2, linewidthScaleFactor=3),
        pointProperties=x3d.PointProperties(pointSizeScaleFactor=6, pointSizeMaxValue=6),
        fillProperties=x3d.FillProperties(hatchStyle=5, hatchColor=(0, 1, 0)))
    return [basenodes.Shape(geometry=basenodes.IndexedLineSet(coord=points,
                                                              coordIndex=[0, 1, 2, 3, 0]),
                            appearance=look),
            basenodes.Shape(geometry=basenodes.PointSet(coord=points), appearance=look),
            basenodes.Shape(geometry=basenodes.IndexedFaceSet(coord=points,
                                                              coordIndex=[0, 1, 2, 3, -1]),
                            appearance=look)]


def _picked():
    """Primitives that a line and a sphere pick each frame"""
    from vrml.x3d import picking  # noqa: PLC0415 kept with its use
    group = basenodes.Group(children=_primitives())
    line = basenodes.IndexedLineSet(coord=basenodes.Coordinate(point=[(-6, 0, -8), (6, 0, -8)]),
                                    coordIndex=[0, 1])
    return [group,
            picking.LinePickSensor(pickingGeometry=line, pickTarget=[group],
                                   intersectionType='GEOMETRY', sortOrder='ALL'),
            picking.PrimitivePickSensor(pickingGeometry=basenodes.Sphere(radius=3),
                                        pickTarget=[group], intersectionType='GEOMETRY')]


PBR = {'OPENGLCONTEXT_RENDERER': 'pbr'}


@pytest.mark.parametrize('scene, environment', [
    pytest.param(_primitives, PBR, id='primitives-pbr'),
    pytest.param(_primitives, {'OPENGLCONTEXT_RENDERER': 'flat'}, id='primitives-flat'),
    pytest.param(_field, PBR, id='instanced-field'),
    pytest.param(_mirror_room, dict(PBR, OPENGLCONTEXT_PLANAR_REFLECTIONS='1',
                                    OPENGLCONTEXT_BLOOM='1'), id='mirror-bloom'),
    pytest.param(_primitives, dict(PBR, OPENGLCONTEXT_SHADOWS='1'), id='shadows'),
    pytest.param(_text, PBR, id='text'),
    pytest.param(_styled, PBR, id='line-point-fill-properties'),
    pytest.param(_picked, PBR, id='pick-sensors'),
])
def test_a_still_frame_asks_nothing_new_of_gl(scene, environment):
    with scene_context(scene(), environment=environment) as context:
        work = check_still_frame(lambda: context.OnDraw(force=1),
                                 warmup=SETTLE_FRAMES + 2)
    assert work.allocations == work.uploads == work.compiles == 0
