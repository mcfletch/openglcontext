"""Shared winding / face-cull state for VRML97 geometry.

Every legacy geometry type set ``glFrontFace``/``GL_CULL_FACE`` by hand, and none
accounted for a mirrored (negative-determinant) modelview -- only ``pbrmesh`` did.
Under a mirror the triangle winding flips, so the front face must follow it or
solid geometry culls the wrong side (renders inside-out / vanishes). This module
centralises that decision so all geometry types share the mirror-aware logic.
"""
from OpenGL.GL import GL_CCW, GL_CW, GL_CULL_FACE, glFrontFace, glEnable, glDisable


def _det3(mv):
    """Sign-carrying determinant of the modelview's upper-left 3x3.

    Direct 3x3 solve (no LAPACK), matching pbrmesh._front_face.
    """
    a = mv.tolist() if hasattr(mv, 'tolist') else mv
    return (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
            - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
            + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))


def front_face(ccw, mv=None):
    """GL front-face enum for CCW/CW geometry under modelview ``mv``.

    ``ccw`` is the geometry's own winding (True => CCW). A negative-determinant
    ``mv`` flips it so culling stays correct under mirrored transforms.
    """
    base = GL_CCW if ccw else GL_CW
    if mv is None:
        return base
    try:
        det = _det3(mv)
    except Exception:
        return base
    if det < 0:
        return GL_CW if base == GL_CCW else GL_CCW
    return base


def apply_winding_cull(mode, ccw, solid):
    """Set mirror-aware front face and back-face culling for a geometry draw."""
    glFrontFace(front_face(ccw, getattr(mode, 'matrix', None)))
    if solid:
        glEnable(GL_CULL_FACE)
    else:
        glDisable(GL_CULL_FACE)
