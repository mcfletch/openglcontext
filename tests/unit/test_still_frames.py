"""A frame of a scene nothing has changed in makes, fills and compiles nothing.

Each scene is drawn until it has settled, and the next frame's GL
allocations, uploads and compiles are counted by
:func:`OpenGLContext.testing.stillframe.check_still_frame`. The scenes are the
ones a game's still moment is made of: VRML97 primitives through both
renderers, a field of shapes drawn as one instanced group, a mirror with
bloom, shadows, text, X3D's line, point and fill properties, X3D's NURBS
geometry, pick sensors and ClipPlanes.
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


def _clipped():
    """Primitives cut by two ClipPlanes"""
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    return [basenodes.Group(children=[x3d.ClipPlane(plane=(0, 1, 0, 0)),
                                      x3d.ClipPlane(plane=(1, 0, 0, 1)), *_primitives()])]


def _shaded():
    """A box drawn by an X3D shader with a field, a light, a texture and an attribute"""
    from tests.unit.test_x3d_shaders import GEOMETRIES, GREEN_HEAT, composed, document, load
    fragment = """<![CDATA[#version 330 core
uniform vec3 colour;
uniform x3d_LightSourceParameters x3d_LightSource[x3d_MaxLights];
uniform sampler2D x3d_Texture2D[x3d_MaxTextures];
out vec4 c;
void main() { c = vec4(colour * x3d_LightSource[0].color, 1.0) * texture(x3d_Texture2D[0], vec2(0.5)); }
]]>"""
    return load(document(
        composed(fragment, fields='<field name="colour" type="SFColor" '
                 'accessType="inputOutput" value="1 0 0"/>'),
        geometry=GEOMETRIES['IndexedTriangleSet'] % GREEN_HEAT,
        texture='<PixelTexture image="1 1 3 0xFFFFFF"/>',
        scene='<DirectionalLight direction="0 0 -1"/>'))


def _nurbs():
    """X3D NURBS surfaces, a sweep and a curve, through the mesh and line paths"""
    from tests.unit.test_mirrored_geometry import _x3d_patch, _x3d_sweep, _x3d_trimmed  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.nurbsx3d import NurbsCurve  # noqa: PLC0415 kept with its use
    curve = NurbsCurve(controlPoint=basenodes.Coordinate(
        point=[(-1, -1, 0), (0, 1, 0), (1, -1, 0)]))
    geometries = [_x3d_patch(), _x3d_trimmed(),
                  _x3d_sweep(basenodes.NurbsSweptSurface, 'crossSectionCurve', 'trajectoryCurve'),
                  curve]
    return [basenodes.Transform(translation=(2.5 * index - 4, 0, -8), children=[
        basenodes.Shape(geometry=geometry, appearance=_look((1, index / 4, 0)))])
        for index, geometry in enumerate(geometries)]


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
    pytest.param(_clipped, dict(PBR, OPENGLCONTEXT_SHADOWS='1'), id='clip-planes'),
    pytest.param(_shaded, PBR, id='x3d-shader-pbr'),
    pytest.param(_shaded, {'OPENGLCONTEXT_RENDERER': 'flat'}, id='x3d-shader-flat'),
    pytest.param(_nurbs, PBR, id='x3d-nurbs-pbr'),
    pytest.param(_nurbs, {'OPENGLCONTEXT_RENDERER': 'flat'}, id='x3d-nurbs-flat'),
])
def test_a_still_frame_asks_nothing_new_of_gl(scene, environment):
    with scene_context(scene(), environment=environment) as context:
        work = check_still_frame(lambda: context.OnDraw(force=1),
                                 warmup=SETTLE_FRAMES + 2)
    assert work.allocations == work.uploads == work.compiles == 0
