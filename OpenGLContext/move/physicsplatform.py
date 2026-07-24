"""``PhysicsViewPlatform`` — a walk-with-gravity camera.

A subclass-free companion to the free-fly :class:`ViewPlatform`: it owns a
:class:`~omi_physics.character.CharacterController` capsule and turns
navigation input into desired velocity / jump, then drives a context's camera
from the solved capsule pose.  It also runs **safe viewpoint binding**
(depenetration + ground snap) on bind, so a camera placed low or inside geometry
never leaves the user stuck (see ``plans/PHYSICS-COLLISION.md`` §Phase 5).
"""
from typing import Any, Optional, Tuple

import numpy as np

from OpenGLContext import quaternion
from omi_physics.character import CharacterController, CharacterCapabilities


class PhysicsViewPlatform:
    def __init__(self, world: Any, capabilities: Optional[CharacterCapabilities] = None,
                 position: Any = (0, 0, 0), yaw: float = 0.0,
                 gravity: float = 9.81) -> None:
        self.character = CharacterController(
            world, capabilities or CharacterCapabilities(), position, gravity=gravity)
        self.yaw = yaw
        self.pitch = 0.0

    # -- binding ---------------------------------------------------------
    def bind(self, position: Any) -> Any:
        """Safe-bind the capsule at ``position`` (the capsule *centre*)."""
        return self.character.safe_bind(position)

    def bind_eye(self, eye: Any) -> Any:
        """Safe-bind so the camera eye lands at ``eye`` (used for viewpoints)."""
        c = self.character
        offset = c.height * 0.5 - c.caps.eyeHeight
        return self.bind((eye[0], eye[1] + offset, eye[2]))

    # -- input -----------------------------------------------------------
    def _world_dir(self, forward: float, strafe: float) -> np.ndarray:
        # World-space camera basis for this yaw, derived from viewplatform.render()
        # (glRotate(yaw, Y) then translate): the camera's world forward is
        # R_y(yaw)^T . (0,0,-1) = (sin yaw, 0, -cos yaw), and right = cross(fwd, up)
        # = (cos yaw, 0, sin yaw). Validated against observed forward/back at the
        # east-facing default heading.
        c, s = np.cos(self.yaw), np.sin(self.yaw)
        fwd = np.array([s, 0.0, -c])
        right = np.array([c, 0.0, s])
        return fwd * forward + right * strafe

    def set_move(self, forward: float = 0.0, strafe: float = 0.0, mode: str = 'walk') -> None:
        self.character.set_move(self._world_dir(forward, strafe), mode=mode)

    def set_fly_move(self, forward: float = 0.0, strafe: float = 0.0, up: float = 0.0) -> None:
        d = self._world_dir(forward, strafe) + np.array([0.0, up, 0.0])
        self.character.set_fly_move(d)

    def turn(self, d_yaw: float) -> None:
        self.yaw += d_yaw

    def look(self, d_pitch: float) -> None:
        self.pitch = float(np.clip(self.pitch + d_pitch, -1.4, 1.4))

    def jump(self) -> Any:
        return self.character.jump()

    def set_crouch(self, crouch: bool) -> Any:
        return self.character.set_crouch(crouch)

    def set_fly(self, flying: bool) -> Any:
        return self.character.set_fly(flying)

    @property
    def blocked(self) -> bool:
        return not self.character.grounded and self.character.stuck

    # -- stepping / camera ----------------------------------------------
    def update(self, dt: float) -> None:
        self.character.update(dt)

    def camera_position(self) -> Tuple[float, ...]:
        return tuple(self.character.eye())

    def camera_orientation(self) -> Any:
        # pitch * yaw (not yaw * pitch): this keeps pitch about the *local* right
        # axis, so looking up/down still tilts (not rolls/twists) after you've
        # turned — verified at yaw=90 the gaze pitches instead of rolling.
        return quaternion.fromXYZR(1, 0, 0, self.pitch) \
            * quaternion.fromXYZR(0, 1, 0, self.yaw)

    def apply(self, context: Any) -> None:
        context.platform.setPosition(self.camera_position())
        context.platform.setOrientation(self.camera_orientation())
