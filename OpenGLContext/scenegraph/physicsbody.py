"""``PhysicsBody`` — the scenegraph face of ``OMI_physics_body``.

A body binds a :class:`~omi_physics.model` ``motion`` / ``collider`` /
``trigger`` to a scenegraph :class:`~OpenGLContext.scenegraph.transform.Transform`.
The physics world owns the transform while the body is a *dynamic* awake mover
(world → tree); authoring owns it while *kinematic* or *static* (tree → world).
"""
import numpy as np

from omi_physics import model, mathutil


def vrml_rotation_to_quat(rotation):
    """VRML axis-angle ``(x, y, z, angle)`` → glTF quaternion ``(x, y, z, w)``."""
    x, y, z, a = rotation
    return mathutil.quat_from_axis_angle((x, y, z), a)


def quat_to_vrml_rotation(quat):
    """glTF quaternion ``(x, y, z, w)`` → VRML axis-angle ``(x, y, z, angle)``."""
    q = mathutil.quat_normalize(np.asarray(quat, dtype='d'))
    w = np.clip(q[3], -1.0, 1.0)
    angle = 2.0 * np.arccos(w)
    s = np.sqrt(max(1.0 - w * w, 0.0))
    if s < 1e-9:
        return np.array([0.0, 1.0, 0.0, 0.0])
    axis = q[:3] / s
    return np.array([axis[0], axis[1], axis[2], angle])


class PhysicsBody:
    """Binds an OMI motion/collider/trigger to a Transform in a world."""

    def __init__(self, transform, motion=None, collider=None, trigger=None):
        self.transform = transform
        self.motion = motion if motion is not None else model.Motion()
        self.collider = collider
        self.trigger = trigger
        self.index = None
        self.world = None

    def register(self, world):
        self.world = world
        pos = tuple(self.transform.translation)
        quat = vrml_rotation_to_quat(self.transform.rotation)
        self.index = world.add_body(self.motion, self.collider, self.trigger,
                                    position=pos, orientation=quat, handle=self)
        return self.index

    def push_authored_pose(self):
        """Copy the authored Transform pose into the world (tree → world)."""
        if self.index is None:
            return
        self.world.position[self.index] = self.transform.translation[:3]
        self.world.orientation[self.index] = vrml_rotation_to_quat(self.transform.rotation)

    def sync_to_scene(self, alpha=1.0):
        """Write the (interpolated) world pose back onto the Transform."""
        if self.index is None:
            return
        w = self.world
        i = self.index
        if not w.awake[i] and w.motion_type[i] == 2:
            return                                # sleeping dynamic body: no churn
        pos = w.prev_position[i] * (1 - alpha) + w.position[i] * alpha
        quat = mathutil.quat_normalize(
            w.prev_orientation[i] * (1 - alpha) + w.orientation[i] * alpha)
        self.transform.translation = tuple(float(v) for v in pos)
        self.transform.rotation = tuple(float(v) for v in quat_to_vrml_rotation(quat))
