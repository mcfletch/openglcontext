"""Every geometry the engine draws is the mirror image of itself under a mirroring transform.

:func:`OpenGLContext.testing.mirrored.check_mirrored_render` draws each one
plain and inside ``Transform(scale=(-1, 1, 1))``, through both core-profile
renderers, and compares the second picture with the first turned over. Every
geometry node class the engine registers has a case here or a reason it has
none, so a new one fails :func:`test_every_geometry_is_covered` until it is
given one.
"""
import inspect

import numpy as np
import pytest

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.mirrored import check_mirrored_render, mirrored_render

TRIANGLE = [(-1, -1, 0), (1, -1, 0), (0.5, 1, 0)]
KNOT = [0, 0, 0, 0, 1, 1, 1, 1]


def _nurbs_surface():
    from OpenGLContext.scenegraph import nurbs
    return nurbs.NurbsSurface(
        controlPoint=[[v / 3.0 - 0.3, u / 3.0 - 0.5, 0.0] for v in range(4) for u in range(4)],
        uDimension=4, vDimension=4, uKnot=KNOT, vKnot=KNOT)


def _trimmed_surface():
    from OpenGLContext.scenegraph import nurbs
    return nurbs.TrimmedSurface(surface=_nurbs_surface())


#: A way to make each geometry, by class name.
CASES = {
    'Box': lambda: basenodes.Box(size=(1.5, 1, 1)),
    'Sphere': lambda: basenodes.Sphere(),
    'Cone': lambda: basenodes.Cone(),
    'Cylinder': lambda: basenodes.Cylinder(),
    'Teapot': lambda: basenodes.Teapot(),
    'Gear': lambda: basenodes.Gear(),
    'IndexedFaceSet': lambda: basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=TRIANGLE), coordIndex=[0, 1, 2, -1]),
    'IndexedPolygons': lambda: basenodes.IndexedPolygons(
        coord=basenodes.Coordinate(point=TRIANGLE),
        normal=basenodes.Normal(vector=[(0, 0, 1)] * 3), index=[0, 1, 2],
        polygonSides=3),
    'Extrusion': lambda: basenodes.Extrusion(),
    'PolyCone': lambda: basenodes.PolyCone(path=[(0, -1, 0), (0.4, 1, 0)],
                                          radii=[1.0, 0.3]),
    'PolyCylinder': lambda: basenodes.PolyCylinder(path=[(-1, -1, 0), (1, 0.5, 0)],
                                                  radius=0.4),
    'NurbsSurface': _nurbs_surface,
    'TrimmedSurface': _trimmed_surface,
    'PBRMesh': lambda: PBRMesh(
        positions=np.array(TRIANGLE, 'f'), normals=np.array([(0, 0, 1)] * 3, 'f'),
        indices=np.array([0, 1, 2], np.uint32)),
}

#: The geometry drawn with no faces to turn over, or not drawn at all.
NO_FACES = {
    'IndexedLineSet': 'lines have no winding to turn over',
    'PointSet': 'points have no winding to turn over',
    'NurbsCurve': 'a curve is drawn as a line',
    'ElevationGrid': 'pyvrml97 declares it and the engine registers no drawing of it',
    'Text': ('its glyphs are screen-aligned bitmaps, which a mirror does not turn '
             'over, as glBitmap does not; test_bitmap_text_is_anchored_where_its_'
             'origin_is holds its anchor to the transform'),
}


def _geometry_classes():
    from vrml.vrml97 import nodetypes
    found = {name for name, value in vars(basenodes).items()
             if inspect.isclass(value) and issubclass(value, nodetypes.Geometry)}
    return found | {'PBRMesh'}


def test_every_geometry_is_covered():
    missing = _geometry_classes() - set(CASES) - set(NO_FACES)
    assert not missing, 'geometry with no mirrored-render case: %s' % sorted(missing)
    assert not set(CASES) & set(NO_FACES)


@pytest.fixture(autouse=True)
def core(request):
    if request.node.name == 'test_every_geometry_is_covered':
        return
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


@pytest.mark.parametrize('renderer', ['pbr', 'flat'])
@pytest.mark.parametrize('name', sorted(CASES))
def test_a_mirrored_geometry_is_its_mirror_image(name, renderer):
    found = check_mirrored_render(CASES[name](),
                                  environment={'OPENGLCONTEXT_RENDERER': renderer})
    assert found.drawn > 0.01 and found.differing <= 0.02


def _text_columns(mirror):
    """The columns bitmap text at x = 1 lights, drawn plain or mirrored."""
    from OpenGLContext.testing.scenes import drawn_image, scene_context
    placed = basenodes.Transform(translation=(1.0, 0.0, -4.0), children=[
        basenodes.Shape(geometry=basenodes.Text(string=['FR']),
                        appearance=basenodes.Appearance(material=basenodes.Material()))])
    if mirror:
        placed = basenodes.Transform(scale=(-1.0, 1.0, 1.0), children=[placed])
    with scene_context([basenodes.Viewpoint(position=(0, 0, 0)), placed],
                       size=(96, 96)) as context:
        context.OnDraw(force=1)
        image = drawn_image(context)
    return np.flatnonzero(image.max(axis=(0, 2)) > 60)


def test_bitmap_text_is_anchored_where_its_origin_is():
    """The glyphs start at the node's origin, which the mirror carries across."""
    plain, mirrored = _text_columns(False), _text_columns(True)
    assert len(plain) and len(mirrored)
    assert plain.min() > 96 // 2 + 5, plain
    assert mirrored.min() < 96 // 2 - 5, mirrored
