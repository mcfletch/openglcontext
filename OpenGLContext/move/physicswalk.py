"""Walking with gravity and collision, as a capability of any context.

A context that can show a world can let the user *walk* through it: an avatar
capsule that gravity holds down, that walls stop, and that the camera rides.
:class:`PhysicsWalkMixin` is that capability.  It is mixed into
:class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin`, so every
interactive context has it, and it costs nothing until it is asked for --
every physics import is inside a method, so a context that never calls
:meth:`~PhysicsWalkMixin.enablePhysics` never imports the physics package.

Two navigators want the camera and only one may have it.  While walking, the
avatar owns ``context.platform`` and the free-fly movement manager is unbound;
switching back rebinds it where the avatar left the view standing.  If both ran
at once the camera would snap back on every key release.

Walking is switched on and off at run time (``g`` by default) rather than chosen
at startup, because a viewpoint that drops the avatar inside geometry must never
be a trap: fly out, and resume walking from wherever you got to.

**Mixing it in elsewhere.**  It is self-contained -- it inherits nothing and
overrides nothing -- so it can be added to any class that offers:

``sg``
    The scenegraph, if :meth:`~PhysicsWalkMixin.buildPhysicsWorld` is left to
    cook the collision world from it.  A host with a world of its own overrides
    that method instead and needs no ``sg`` at all.
``platform`` / ``getViewPlatform()``
    The free-fly camera the avatar takes over from and hands back to.
``movementManager``
    The navigator holding the camera when walking is off.
``contextDefinition``
    Where the declared movement modes are published.
``addEventHandler``, ``triggerRedraw``, ``getNavigation``, ``updateNavigation``
    The event and navigation plumbing every ``Context`` has.

See [docs/physics.html](../../docs/physics.html) and
``plans/PHYSICS-COLLISION.md`` §Phase 5.
"""
from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.move.modes import (
    FLY_SPEED, RUN_SPEED, WALK_SPEED, walk_fly_modes,
)

if TYPE_CHECKING:
    from omi_physics.character import CharacterCapabilities, CharacterController
    from omi_physics.world import PhysicsWorld
    from OpenGLContext.move.physicsplatform import PhysicsViewPlatform

__all__ = ['PhysicsWalkMixin', 'yaw_from_orientation']

#: World bounds as ``(lo, hi)`` corner arrays.
Bounds = Tuple[Any, Any]


def yaw_from_orientation(orientation: Sequence[float]) -> float:
    """Heading, in radians about +Y, of a VRML axis/angle ``orientation``.

    A ``Viewpoint``'s orientation says where it looks; an avatar's yaw says
    where it faces.  This is the conversion, and it is the *camera's* sign
    convention (:meth:`ViewPlatform.setOrientation`), not the node's.
    """
    from OpenGLContext import quaternion
    x, y, z, r = orientation
    matrix = np.asarray(quaternion.fromXYZR(x, y, z, -r).matrix())[:3, :3]
    forward = matrix.T @ np.array([0.0, 0.0, -1.0])
    return float(np.arctan2(-forward[0], -forward[2]))


def _clearance(character: 'CharacterController', radius: float) -> int:
    """How many of the four horizontal directions the avatar has room to go.

    The whole capsule is placed an arm's length along each direction and
    depenetrated; the direction counts only if it stayed appreciably out there.
    Testing the volume rather than the point is what catches a wall the avatar
    would walk into but whose face its centre line misses, so it does not spawn
    facing one.  It is a placement test and not a swept move, so a barrier
    thinner than the capsule is transparent to it.
    """
    base = character.position
    reach = radius + 0.5
    clear = 0
    for direction in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)):
        offset = np.asarray(direction, dtype='d')
        resolved, _ = character._push_out(base + offset * reach)
        if float(np.dot(resolved - base, offset)) > 0.5 * reach:
            clear += 1
    return clear


class PhysicsWalkMixin(object):
    """Gives a context an avatar it can hand the camera to."""

    #: The avatar's view platform while walking has ever been built, else None.
    #: Built lazily, on the first :meth:`enablePhysics`, and kept afterwards so
    #: toggling back to walking resumes rather than respawns.
    physicsPlatform: Optional['PhysicsViewPlatform'] = None
    #: Whether the avatar, rather than the free-fly camera, owns the view.
    physicsWalking: bool = False
    #: Downward acceleration at avatar scale 1, in scene units per second squared.
    physicsGravity: float = 9.81
    #: Heading the avatar starts at when no viewpoint supplies one, in radians.
    physicsYaw: float = 0.0
    #: Longest frame the avatar is stepped by.  A stall is not a licence to
    #: teleport it through a wall, so wall-clock is clamped rather than trusted.
    physicsMaxStep: float = 0.05
    #: Key that switches between walking and free-fly; '' binds none.
    physicsToggleKey: str = 'g'
    #: Key that switches the walking avatar between the ground and the air.
    physicsFlyKey: str = 'f'

    #: The navigator that owns the camera while walking is off, remembered by
    #: :meth:`setupPhysics` so it can be handed the camera back.
    _freeManager: Any = None
    #: When the avatar was last stepped.
    _physicsLast: float = 0.0

    if TYPE_CHECKING:
        # Supplied by the context this is mixed into; see the module docstring.
        sg: Any
        platform: Any
        movementManager: Any
        contextDefinition: Any

        def getViewPlatform(self) -> Any: ...
        def addEventHandler(self, kind: str, **named: Any) -> Any: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...
        def getNavigation(self) -> Any: ...
        def updateNavigation(self, dt: float) -> None: ...

    # -- setup ------------------------------------------------------------
    def setupPhysics(self, enable: bool = False) -> bool:
        """Make walking available, and optionally start walking straight away.

        Returns whether the context is now walking -- False when ``enable`` was
        asked for but the world has no walkable geometry, which is not a
        failure: an isolated or floorless model is meant to be looked at from
        the free-fly camera.
        """
        self._freeManager = getattr(self, 'movementManager', None)
        if self.physicsToggleKey:
            self.addEventHandler('keyboard', name=self.physicsToggleKey,
                                 state=1, function=self.togglePhysics)
        return self.enablePhysics(True) if enable else False

    # -- the world the avatar walks in ------------------------------------
    def buildPhysicsWorld(self) -> Optional[Tuple['PhysicsWorld', Bounds]]:
        """The collision world and its bounds, or None if nothing is walkable.

        The default cooks one static collision mesh out of this context's
        scenegraph, honouring OMI physics bodies where the document carries
        them.  A context with a world of its own -- a terrain heightfield, a
        level format that ships its collision -- overrides this and never
        touches ``sg``.
        """
        scene = getattr(self, 'sg', None)
        if scene is None:
            return None
        from OpenGLContext.physics.gltf_world import collision_world_from_scene
        world, bounds = collision_world_from_scene(scene)
        if bounds is None:
            return None
        return world, bounds

    @staticmethod
    def physicsAvatarScale(lo: Any, hi: Any) -> float:
        """How big a person is in this world: the avatar is 1/40 of its longest side.

        A viewer opens anything from a bolt to a city, and neither the avatar's
        stride nor gravity means anything until they are in the same units as
        the model.  Never zero, so a degenerate world still gives a usable
        character rather than a division by nothing.
        """
        return max(float(max(np.asarray(hi) - np.asarray(lo))) / 40.0, 1e-3)

    def characterCapabilities(self, scale: float = 1.0) -> 'CharacterCapabilities':
        """The avatar's dimensions and speeds at ``scale``.

        Roughly a person: 1.8 units tall, eyes at 1.6, stepping 0.4 without
        jumping.  Override to make the avatar something else.
        """
        from omi_physics.character import CharacterCapabilities
        return CharacterCapabilities(
            walkSpeed=WALK_SPEED * scale, runSpeed=RUN_SPEED * scale,
            flySpeed=FLY_SPEED * scale,
            jumpHeight=1.2 * scale, stepHeight=0.4 * scale,
            standHeight=1.8 * scale, crouchHeight=1.0 * scale,
            radius=0.3 * scale, eyeHeight=1.6 * scale)

    def applyMovementModes(self, scale: float) -> None:
        """Declare the movement modes that suit an avatar of this size.

        The modes' speeds have to match the character's, and the character is
        sized to the world, so this happens when the avatar is built rather
        than at startup.  A context that declares its own modes overrides this.
        """
        self.contextDefinition.movementModes = walk_fly_modes(scale)

    def ensurePhysicsWorld(self) -> bool:
        """Build the avatar and its world once.  False if nothing is walkable."""
        if self.physicsPlatform is not None:
            return True
        built = self.buildPhysicsWorld()
        if built is None:
            return False
        world, (lo, hi) = built
        scale = self.physicsAvatarScale(lo, hi)
        capabilities = self.characterCapabilities(scale)
        from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
        self.physicsPlatform = PhysicsViewPlatform(
            world, capabilities, yaw=self.physicsYaw,
            gravity=self.physicsGravity * scale)
        self.applyMovementModes(scale)
        # Where the camera is, so switching to walking drops in here rather than
        # teleporting to the middle of the world.
        camera = getattr(getattr(self, 'platform', None), 'position', None)
        self.spawnAvatar(lo, hi, capabilities, self.physicsSpawnViewpoints(),
                         preferred=None if camera is None else camera[:3])
        self._physicsLast = self.physicsNow()
        self.physicsPlatform.apply(self)
        return True

    # -- switching --------------------------------------------------------
    def enablePhysics(self, on: bool = True) -> bool:
        """Walk (``on``) or free-fly, leaving the camera where it is.

        Returns False, having changed nothing, if walking was asked for and the
        world has no walkable geometry.
        """
        if on:
            first = self.physicsPlatform is None
            if first and not self.ensurePhysicsWorld():
                return False
            # Always from where the camera is -- the first time as much as the
            # tenth.  Walking is entered by dropping in, so gravity takes it
            # down to whatever is underneath rather than leaving it hovering.
            self.syncAvatarToCamera()
            self.physicsPlatform.set_fly(False)
            manager = getattr(self, 'movementManager', None)
            if manager is not None and self._freeManager is not None:
                self._freeManager.unbind(self)
                self.movementManager = None
            self.bindPhysicsInput()
            self.physicsWalking = True
        else:
            if getattr(self, 'movementManager', None) is None \
                    and self._freeManager is not None:
                self._freeManager.bind(self)
                self.movementManager = self._freeManager
            self.physicsWalking = False
        self.onPhysicsModeChanged()
        self.triggerRedraw(1)
        return True

    def togglePhysics(self, event: Any = None) -> None:
        """Switch between walking and free-fly."""
        self.enablePhysics(not self.physicsWalking)

    def onPhysicsModeChanged(self) -> None:
        """Called after walking is switched on or off.  A hook; does nothing here."""

    def getNavigationPlatform(self) -> Any:
        """What the declared movement modes drive.

        The avatar while walking, so a mode moves the character and the camera
        follows it; the view platform otherwise, where the free-fly navigator
        still owns the camera.
        """
        if self.physicsWalking and self.physicsPlatform is not None:
            return self.physicsPlatform
        return self.getViewPlatform()

    def bindPhysicsInput(self) -> None:
        """(Re)bind the keys the declared movement modes name.

        Re-registered on every enable: binding and unbinding the free-fly
        navigator rewrites the shared arrow-key handlers, so walking has to
        reclaim them.  The modes decide what each key *means*; this only
        arranges for the events to arrive, since the sampler is fed by event
        dispatch itself.
        """
        navigation = self.getNavigation()
        if navigation is None:
            return
        for _name, binding in navigation.binding_table():
            for key in binding.keys:
                for state in (1, 0):
                    self.addEventHandler('keyboard', name=key, state=state,
                                         function=self._physicsKey)
        if self.physicsFlyKey:
            self.addEventHandler('keyboard', name=self.physicsFlyKey, state=1,
                                 function=self.togglePhysicsFly)

    def _physicsKey(self, event: Any) -> None:
        """Wake the frame loop; the sampler is fed by event dispatch itself."""
        self.triggerRedraw(1)

    def togglePhysicsFly(self, event: Any = None) -> None:
        """Swap the walking avatar between the ground and the air.

        Flying is a property of the character controller as well as of the
        movement, so the mode change has to reach both.
        """
        navigation = self.getNavigation()
        if navigation is None or self.physicsPlatform is None:
            return
        current = getattr(self.contextDefinition, 'movementMode', None)
        wanted = 'walk' if current is not None and current.name == 'fly' else 'fly'
        if navigation.select(wanted):
            self.physicsPlatform.set_fly(wanted == 'fly')

    # -- placing the avatar -----------------------------------------------
    def physicsSpawnViewpoints(self) -> Sequence[Any]:
        """Viewpoints worth standing near, the preferred one first.

        Authored cameras are curated open spots, which is exactly what a spawn
        wants; the first one also supplies the initial heading.  Empty by
        default -- a context with viewpoints overrides this.
        """
        return ()

    def spawnAvatar(self, lo: Any, hi: Any, capabilities: 'CharacterCapabilities',
                    viewpoints: Sequence[Any] = (),
                    preferred: Optional[Sequence[float]] = None) -> None:
        """Stand the avatar somewhere it can actually walk out of.

        ``preferred`` is where the camera already is, and is taken as soon as
        there is ground under it: switching to walking means dropping in where
        you are looking.  The middle of a *model* is a reasonable place to
        start, which is what the search below falls back to; the middle of a
        city is kilometres from wherever you flew to, and often over water.

        Failing that, the middle of a world is often solid -- a statue, thick
        walls -- so several footprint positions are tried and scored by how open
        they are, preferring the most open and, among equals, the most central.
        Authored viewpoints are tried first, projected straight down to the
        floor: they are elevated as often as not, so only their *heading* is
        borrowed (:meth:`moveAvatarToViewpoint` is how you actually go to one).
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        if viewpoints:
            platform.yaw = yaw_from_orientation(viewpoints[0].orientation)
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        if preferred is not None and (
                lo[0] <= preferred[0] <= hi[0] and lo[2] <= preferred[2] <= hi[2]):
            # Taken as it stands, with whatever is under it left to gravity: a
            # flat ground has no inside to test against, so "is there floor
            # below" cannot be asked here, and falling to it is the answer
            # anyway.  Outside the world there is nothing to fall to, so that
            # case goes to the search below instead.
            platform.bind_eye(tuple(float(v) for v in preferred[:3]))
            if not platform.character.stuck:
                return
        candidates: list[Tuple[float, float]] = []
        for viewpoint in viewpoints:
            position = viewpoint.position
            if lo[0] <= position[0] <= hi[0] and lo[2] <= position[2] <= hi[2]:
                candidates.append((float(position[0]), float(position[2])))
        candidates.append((cx, cz))
        for fraction in (0.25, 0.45, 0.65):        # interior -> mid -> outer rings
            for fx in np.linspace(-fraction, fraction, 5):
                for fz in np.linspace(-fraction, fraction, 5):
                    candidates.append((cx + fx * (hi[0] - lo[0]),
                                       cz + fz * (hi[2] - lo[2])))
        y = lo[1] + capabilities.standHeight
        best: Any = None                    # ((clearance, -distance), x, z)
        for x, z in candidates:
            platform.bind((x, y, z))
            character = platform.character
            if not character.grounded or character.stuck or character.flying:
                continue
            clear = _clearance(character, capabilities.radius)
            score = (clear, -((x - cx) ** 2 + (z - cz) ** 2))
            if best is None or score > best[0]:
                best = (score, x, z)
            if clear == 4:                  # fully open: good enough
                return
        if best is not None:
            platform.bind((best[1], y, best[2]))
        else:
            platform.bind((cx, y, cz))

    def moveAvatarToViewpoint(self, viewpoint: Any) -> None:
        """Put the avatar where a ``Viewpoint`` looks from, facing where it faces.

        Safe-bound, so a viewpoint sunk into geometry pushes out rather than
        wedging; and an elevated one starts the avatar flying, because there is
        nothing under an aerial camera to stand on and falling out of the shot
        is not what asking for that view meant.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        platform.yaw = yaw_from_orientation(viewpoint.orientation)
        platform.pitch = 0.0
        platform.bind_eye(tuple(viewpoint.position))
        platform.set_fly(not platform.character.grounded)

    def syncAvatarToCamera(self) -> None:
        """Seat the avatar at the current free-fly camera pose, safe-bound.

        Flying is left on when there is nothing underfoot, so a camera in mid
        air does not drop the moment the avatar takes over; a caller that means
        "drop in from here" turns it off (:meth:`enablePhysics` does).
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        platform.yaw = self.yawFromPlatform()
        platform.pitch = 0.0
        platform.bind_eye(tuple(self.platform.position[:3]))
        platform.set_fly(not platform.character.grounded)
        self._physicsLast = self.physicsNow()

    def yawFromPlatform(self) -> float:
        """Heading the free-fly camera is currently looking along."""
        forward = self.platform.quaternion * [0.0, 0.0, -1.0, 0.0]
        return float(np.arctan2(forward[0], -forward[2]))

    # -- the frame --------------------------------------------------------
    def stepPhysics(self, dt: Optional[float] = None) -> None:
        """Advance the avatar one frame and put the camera where it ended up.

        ``dt`` defaults to the wall-clock since the last step, clamped to
        :attr:`physicsMaxStep`.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        now = self.physicsNow()
        if dt is None:
            dt = min(now - self._physicsLast, self.physicsMaxStep)
        self._physicsLast = now
        self.updateNavigation(dt)
        platform.update(dt)
        self.resolvePhysicsStep()
        platform.apply(self)
        self.triggerRedraw(1)

    def resolvePhysicsStep(self) -> None:
        """Correct the avatar's pose once the character has solved its own step.

        Between the step and the camera, which is the only moment a correction
        can be made without the view showing the uncorrected pose for a frame.
        A hook, and empty here: a host whose ground or obstacles are not in the
        collision world -- a height field, an analytic surface -- resolves them
        from here.  See
        :meth:`OpenGLContext.move.terrainwalk.TerrainWalkMixin.resolveTerrain`.
        """

    @staticmethod
    def physicsNow() -> float:
        """Wall clock the avatar is stepped against."""
        from time import time
        return time()
