"""A path's summary rotation is the rotations of the transforms down it.

A `Viewpoint` inside a rotated `Transform` looks where the transform turns it,
so `Viewpoint.moveTo` needs the path's rotation to place the camera.
"""
import math

import pytest

from OpenGLContext import quaternion
from OpenGLContext.scenegraph.basenodes import Transform, Viewpoint
from OpenGLContext.scenegraph.nodepath import NodePath


def rotated(vector, xyzr):
    """``vector`` turned by a VRML97 rotation (Rodrigues)."""
    x, y, z, angle = xyzr
    dot = x * vector[0] + y * vector[1] + z * vector[2]
    cross = (y * vector[2] - z * vector[1], z * vector[0] - x * vector[2],
             x * vector[1] - y * vector[0])
    return tuple(vector[i] * math.cos(angle) + cross[i] * math.sin(angle)
                 + (x, y, z)[i] * dot * (1 - math.cos(angle)) for i in range(3))


def test_a_rotated_transform_turns_the_path():
    turn = Transform(rotation=(0, 1, 0, math.pi / 2))
    path = NodePath([turn, Viewpoint()])
    assert rotated((1, 0, 0), path.quaternion().XYZR()) == pytest.approx((0, 0, -1), abs=1e-6)


def test_nested_transforms_compose_outer_first():
    outer = Transform(rotation=(0, 1, 0, math.pi / 2))
    inner = Transform(rotation=(0, 0, 1, math.pi / 2))
    path = NodePath([outer, inner])
    # +x tilts up to +y inside, and the outer turn leaves +y where it is.
    assert rotated((1, 0, 0), path.quaternion().XYZR()) == pytest.approx((0, 1, 0), abs=1e-6)


def test_a_path_with_no_rotation_is_the_identity():
    path = NodePath([Transform(translation=(1, 2, 3)), Viewpoint()])
    assert path.quaternion().XYZR()[3] == pytest.approx(0.0)


def test_a_viewpoint_in_a_turned_transform_looks_the_way_it_is_turned():
    turn = Transform(rotation=(0, 1, 0, math.pi / 2))
    eye = Viewpoint(orientation=(0, 0, 1, 0))
    path = NodePath([turn, eye])

    class Platform:
        orientation = None

        def setPosition(self, position):
            pass

        def setOrientation(self, orientation):
            self.orientation = tuple(orientation)

        def setFrustum(self, *arguments, **named):
            pass

    class Context:
        platform = Platform()

    eye.moveTo(path, Context)
    looking = rotated((0, 0, -1), Context.platform.orientation)
    assert looking == pytest.approx((-1, 0, 0), abs=1e-6)
    assert isinstance(path.quaternion(), quaternion.Quaternion)
