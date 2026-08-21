"""Water faces up (:mod:`OpenGLContext.scenegraph.water.surface`).

A sheet's triangles have to be wound counter-clockwise seen from above, to
agree with the upward normals the same builder stores.  Where they disagree
the surface renders back-facing, and the PBR shader flips the normal on a
back-facing fragment -- correct for a two-sided surface, and ruinous here:
the flipped normal faces away from the camera, ``dot(N, V)`` goes negative
and clamps to nearly zero, and a near-zero ``NdotV`` is grazing incidence,
where Fresnel reaches 1.

The surface then reflects the whole environment like a mirror whatever it is
made of, which is why a lake reads as pale plastic rather than water. Nothing
about the wave field changes, so it looks like a material problem and is not.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.water import STILL, CHOPPY, water_ribbon, water_surface


def _facing(mesh):
    """(up, total) triangle counts for a mesh, by winding seen from above."""
    points = np.asarray(mesh.positions)
    triangles = np.asarray(mesh.indices).reshape(-1, 3)
    a, b, c = points[triangles[:, 0]], points[triangles[:, 1]], points[triangles[:, 2]]
    up = np.cross(b - a, c - a)[:, 1]
    return int((up > 0).sum()), len(triangles)


class TestASheetFacesUp:
    @pytest.mark.parametrize('style', [STILL, CHOPPY])
    def test_every_triangle_is_wound_counter_clockwise(self, style):
        up, total = _facing(water_surface(-8, 8, -8, 8, level=0.0,
                                          resolution=5, style=style))
        assert up == total, '%d of %d triangles face down' % (total - up, total)

    def test_it_holds_at_a_finer_mesh(self):
        up, total = _facing(water_surface(-20, 20, -20, 20, level=0.0,
                                          resolution=17, style=STILL))
        assert up == total, '%d of %d triangles face down' % (total - up, total)

    def test_the_stored_normals_agree_with_the_winding(self):
        """The builder stores upward normals; the winding must say the same."""
        sheet = water_surface(-8, 8, -8, 8, level=0.0, resolution=5, style=STILL)
        assert np.asarray(sheet.normals)[:, 1].min() > 0
        up, total = _facing(sheet)
        assert up == total


class TestARiverFacesUp:
    def test_every_triangle_is_wound_counter_clockwise(self):
        course = [(0.0, 0.0, float(z)) for z in range(0, 40, 4)]
        ribbon = water_ribbon(course, 6.0, style=STILL)
        if ribbon is None:
            pytest.skip('no ribbon built for this course')
        up, total = _facing(ribbon)
        assert up == total, '%d of %d triangles face down' % (total - up, total)


class TestGlintsFaceUp:
    """A glint is a patch on the surface, and faces the way the surface does."""

    def test_every_triangle_is_wound_counter_clockwise(self):
        from OpenGLContext.scenegraph.water import water_glints
        course = [(0.0, 0.0, float(z)) for z in range(0, 40, 4)]
        glints = water_glints(course, 6.0, spacing=5.0, style=STILL)
        if glints is None:
            pytest.skip('no glints built for this course')
        up, total = _facing(glints)
        assert up == total, '%d of %d triangles face down' % (total - up, total)
