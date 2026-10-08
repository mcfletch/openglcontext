"""``oglc-x3d-nurbs``: the X3D NURBS scene, with no window."""
import os

import numpy as np
import pytest

from OpenGLContext.bin import x3d_nurbs
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import nurbsinterpolators, nurbsx3d
from OpenGLContext.scenegraph.scenegraph import X3DScene
from OpenGLContext.testing.scenes import drawn_image, scene_context


@pytest.fixture(scope='module')
def demo(tmp_path_factory):
    found = x3d_nurbs.NurbsScene(str(tmp_path_factory.mktemp('nurbs')))
    assert background.wait_for_idle(20.0)
    return found


def test_it_reads_without_errors(demo):
    assert isinstance(demo.scene, X3DScene)
    assert not [problem for problem in demo.scene.problems if problem.severity == 'error']


def test_the_maps_it_names_are_written_beside_it(demo):
    assert {'x3d_nurbs.x3d', 'marble_base.png', 'brick_normal.png',
            'sandstone_mr.png'} <= set(os.listdir(demo.directory))


def test_it_uses_every_x3d_nurbs_node(demo):
    expected = {nurbsx3d.NurbsPatchSurface, nurbsx3d.NurbsTrimmedSurface,
                nurbsx3d.NurbsSweptSurface, nurbsx3d.NurbsSwungSurface, nurbsx3d.NurbsCurve,
                nurbsx3d.NurbsCurve2D, nurbsx3d.Contour2D, nurbsx3d.ContourPolyline2D,
                nurbsx3d.NurbsTextureCoordinate, nurbsx3d.NurbsSet,
                nurbsinterpolators.NurbsPositionInterpolator,
                nurbsinterpolators.NurbsOrientationInterpolator,
                nurbsinterpolators.NurbsSurfaceInterpolator}
    found, stack = set(), list(demo.scene.children)
    while stack:
        current = stack.pop()
        found.add(type(current))
        for name in ('children', 'geometry', 'trimmingContour', 'texCoord', 'profileCurve',
                     'trajectoryCurve', 'crossSectionCurve'):
            value = getattr(current, name, None)
            if isinstance(value, list | tuple):
                stack.extend(entry for entry in value if entry)
            elif value:
                stack.append(value)
    assert expected <= found


def test_the_t_key_scales_the_tessellation(demo):
    shell = demo.scene.getDEF('Shell')
    before = len(shell.mesh().positions)
    assert demo.press('t') == 'tessellation scale 2'
    assert len(shell.mesh().positions) > before
    assert demo.press('t') == 'tessellation scale 0.25'
    assert demo.press('t') == 'tessellation scale 1'
    assert len(shell.mesh().positions) == before
    assert demo.press('x') == ''


def test_it_draws(gl_context, demo):
    with scene_context(demo.scene, size=(160, 90)) as context:
        for _ in range(3):
            context.OnDraw(force=1)
        image = drawn_image(context).astype(int)
    # gold, brass and brick are all warmer than the sky and the floor's shadow
    warm = (image[:, :, 0] > image[:, :, 2] + 40)
    assert warm.mean() > 0.05
    assert np.isfinite(image).all()
