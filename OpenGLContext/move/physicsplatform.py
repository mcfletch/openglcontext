"""``PhysicsViewPlatform`` — a walk-with-gravity camera.

A subclass-free companion to the free-fly :class:`ViewPlatform`: it owns a
:class:`~omi_physics.character.CharacterController` capsule and turns
navigation input into desired velocity / jump, then drives a context's camera
from the solved capsule pose.  It also runs **safe viewpoint binding**
(depenetration + ground snap) on bind, so a camera placed low or inside geometry
never leaves the user stuck (see ``plans/PHYSICS-COLLISION.md`` §Phase 5).

How fast a move goes is the caller's to say.  Each of the ``set_*_move``
methods takes the speed with the move, and a
:class:`~OpenGLContext.move.modes.MovementMode` passes its own declared figure
every frame -- so the mode is what a player is moving at, and editing it on the
settings screen is felt on the next step.  A caller with no opinion passes none
and the body keeps whatever it was built with.
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

    #: Which of the body's speeds each move tier is measured by.  Unknown tiers
    #: fall through to walking, as :meth:`CharacterController.speed` does.
    TIER_SPEEDS = {'walk': 'walkSpeed', 'run': 'runSpeed',
                   'sprint': 'sprintSpeed', 'crouch': 'crouchSpeed'}

    def _moveAt(self, capability: str, speed: Optional[float]) -> None:
        """Put the speed the caller asked for onto the body that will move at it.

        A move is scaled by the *character's* capability, so a
        :class:`~OpenGLContext.move.modes.MovementMode` declaring a walking
        speed can only mean it if the figure reaches the body.  It arrives with
        the move, once a frame, which is what makes the number on the settings
        screen take effect on the next step rather than on the next launch.

        ``None`` means the caller has no opinion -- a game driving this platform
        directly, rather than through a mode -- and the body keeps whatever it
        was built with.
        """
        if speed is not None:
            setattr(self.character.caps, capability, float(speed))

    def set_move(self, forward: float = 0.0, strafe: float = 0.0, mode: str = 'walk',
                 speed: Optional[float] = None) -> None:
        self._moveAt(self.TIER_SPEEDS.get(mode, 'walkSpeed'), speed)
        self.character.set_move(self._world_dir(forward, strafe), mode=mode)

    def set_fly_move(self, forward: float = 0.0, strafe: float = 0.0, up: float = 0.0,
                     speed: Optional[float] = None) -> None:
        self._moveAt('flySpeed', speed)
        d = self._world_dir(forward, strafe) + np.array([0.0, up, 0.0])
        self.character.set_fly_move(d)

    def _gaze_dir(self, forward: float, strafe: float) -> np.ndarray:
        """The move basis for swimming: forward follows the **pitch** too.

        Walking flattens the move to the ground plane, and rightly — leaning
        forward should not push a player into the floor.  Under water that is
        exactly wrong: it would leave the surface and the bottom reachable
        only by the dedicated keys, which is walking with the gravity turned
        off rather than swimming.

        Strafing stays level whatever the gaze, because sidling should not
        sink you; it is the one axis a swimmer expects to stay flat.
        """
        # `pitch` is positive *downward* (see `look`), so the gaze's vertical
        # component is its negative sine.
        cos_pitch = np.cos(self.pitch)
        c, s = np.cos(self.yaw), np.sin(self.yaw)
        gaze = np.array([s * cos_pitch, -np.sin(self.pitch), -c * cos_pitch])
        right = np.array([c, 0.0, s])
        return gaze * forward + right * strafe

    def set_swim_move(self, forward: float = 0.0, strafe: float = 0.0,
                      up: float = 0.0, speed: Optional[float] = None) -> None:
        """Swim along the gaze, plus whatever the up/down keys ask for.

        Normalised, because the character takes a *direction* and scales it by
        its own swim speed; looking down and holding forward must not swim
        more slowly than looking level does.
        """
        self._moveAt('swimSpeed', speed)
        direction = self._gaze_dir(forward, strafe) + np.array([0.0, up, 0.0])
        length = float(np.linalg.norm(direction))
        if length > 1e-9:
            direction = direction / length
        self.character.set_fly_move(direction)

    def turn(self, d_yaw: float) -> None:
        """Swing the gaze about the vertical axis.  **Positive turns right.**

        Take that from here rather than deriving it.  These angles rotate the
        *world* rather than the camera, and the two obvious derivations give
        opposite answers: ``_world_dir`` reads a rising yaw as swinging toward
        +X while the quaternion in :meth:`camera_orientation` reads it the
        other way, depending entirely on whether you apply the matrix as
        ``v @ M`` or ``M @ v``.  Whichever you assume, assume the other one.

        The sense above is *measured*, through
        :func:`twig_bb.viewer.gaze` -- the orientation applied to the
        viewing axis -- and it is measured again in
        ``tests/unit/test_movementmodes.py``, which asserts on where the gaze
        ends up rather than on the sign of a number.  A test that restated the
        sign would agree with whatever this line happens to say.
        """
        self.yaw += d_yaw

    def look(self, d_pitch: float) -> None:
        """Tilt the gaze.  **Positive looks down**, and the clamp is +/-1.4 rad.

        Down, not up -- the same inversion as :meth:`turn`, for the same
        reason, and a mode that wants "look up" therefore passes a *negative*
        pitch.  Measured, not derived; see :meth:`turn`.
        """
        self.pitch = float(np.clip(self.pitch + d_pitch, -1.4, 1.4))

    def jump(self) -> Any:
        return self.character.jump()

    def apply_impulse(self, velocity: Any) -> None:
        """Launch the capsule at ``velocity`` in world metres/second.

        The world-space form is what map features want: a jump pad or a blast
        aims in world terms and does not care which way the camera is facing.
        """
        self.character.apply_impulse(velocity)

    def set_crouch(self, crouch: bool) -> Any:
        return self.character.set_crouch(crouch)

    def set_fly(self, flying: bool) -> Any:
        return self.character.set_fly(flying)

    def set_swim(self, swimming: bool, buoyancy: float = 0.9) -> Any:
        return self.character.set_swim(swimming, buoyancy=buoyancy)

    @property
    def blocked(self) -> bool:
        return not self.character.grounded and self.character.stuck

    # -- stepping / camera ----------------------------------------------
    def update(self, dt: float) -> None:
        self.character.update(dt)

    def camera_position(self) -> Tuple[float, ...]:
        return tuple(self.character.eye())

    def feet_position(self) -> Tuple[float, ...]:
        """Where the body ends, which is not where it looks from.

        A game asking whether the avatar is standing in something -- water, a
        trigger volume, a patch of mud -- is asking about the body, and the eye
        is the one part of it that is regularly outside whatever the feet are
        in.  Both readings are published so a caller can use each where it
        belongs.
        """
        return tuple(self.character.base())

    def camera_orientation(self) -> Any:
        # pitch * yaw (not yaw * pitch): this keeps pitch about the *local* right
        # axis, so looking up/down still tilts (not rolls/twists) after you've
        # turned — verified at yaw=90 the gaze pitches instead of rolling.
        return quaternion.fromXYZR(1, 0, 0, self.pitch) \
            * quaternion.fromXYZR(0, 1, 0, self.yaw)

    def apply(self, context: Any) -> None:
        context.platform.setPosition(self.camera_position())
        context.platform.setOrientation(self.camera_orientation())
