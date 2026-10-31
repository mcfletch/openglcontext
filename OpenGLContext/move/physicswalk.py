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

``physics``
    The context's physics service
    (:class:`~OpenGLContext.physics.service.Physics`), which the avatar is a
    :class:`~OpenGLContext.physics.character.Character` of.
``sg``
    The scenegraph, if :meth:`~PhysicsWalkMixin.buildPhysicsWorld` is left to
    make the scene's shapes the world's scenery.  A host with bodies of its own
    overrides that method instead and needs no ``sg`` at all.
``platform`` / ``getViewPlatform()``
    The free-fly camera the avatar takes over from and hands back to.
``movementManager``
    The navigator holding the camera when walking is off.
``contextDefinition``
    Whose ``navigation`` declares the movement modes, and publishes the one
    in force.
``addEventHandler``, ``triggerRedraw``, ``getNavigation``, ``updateNavigation``
    The event and navigation plumbing every ``Context`` has.
``renderQueue``
    Optional.  Where a host has one, the service steps the avatar in the
    frame: the declared mode sets its move before the world steps and the
    camera goes to its eye after.  A host without one calls
    :meth:`~PhysicsWalkMixin.stepPhysics` itself.

See [docs/physics.rst](../../docs/physics.rst) and
``plans/PHYSICS-COLLISION.md`` §Phase 5.
"""
import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

from OpenGLContext.move.modes import (
    FLY_SPEED, RUN_SPEED, WALK_SPEED, walk_fly_modes,
)

if TYPE_CHECKING:
    from OpenGLContext.events.framestep import FrameStep
    from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
    from OpenGLContext.physics.character import Character
    from OpenGLContext.physics.service import Physics
    from OpenGLContext.physics.types import CharacterCapabilities
    from OpenGLContext.physics.x3dcollision import CollisionReporter

__all__ = ['FLOORS', 'HEADROOM', 'PASS', 'PhysicsWalkMixin', 'clearance', 'floor_below', 'floors_below',
           'yaw_from_orientation']

log = logging.getLogger(__name__)

#: World bounds as ``(lo, hi)`` corner arrays.
Bounds = tuple[Any, Any]


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


def _capsule(capabilities: 'CharacterCapabilities') -> Any:
    """The avatar's standing capsule as a :class:`~OpenGLContext.physics.proxy.Proxy`."""
    from OpenGLContext.physics.proxy import Proxy  # noqa: PLC0415 every physics import waits for walking

    radius = float(capabilities.radius)
    return Proxy.capsule(max(float(capabilities.standHeight) - 2.0 * radius, 0.0), radius)


def floor_below(physics: 'Physics', centre: Sequence[float],
                capabilities: 'CharacterCapabilities', skip: Any = None) -> Optional[float]:
    """The height of the floor under a capsule centred at ``centre``, or None.

    The floor is the first surface a ray meets straight down from the
    capsule's centre within one standing height below its feet, and it counts
    only where it is no steeper than ``capabilities.maxSlope`` degrees.
    ``skip`` is the avatar's own body.
    """
    half = 0.5 * float(capabilities.standHeight)
    reach = half + float(capabilities.standHeight)
    hit = physics.raycast(tuple(float(v) for v in centre[:3]), (0.0, -1.0, 0.0), reach, skip=skip)
    if hit is None:
        return None
    steepest = np.cos(np.radians(float(capabilities.maxSlope)))
    if float(hit.normal[1]) < steepest - 1e-6:
        return None
    return float(hit.point[1])


def floors_below(physics: 'Physics', x: float, z: float, top: float, bottom: float,
                 capabilities: 'CharacterCapabilities', skip: Any = None) -> list[float]:
    """The heights of the floors under ``(x, z)`` between ``top`` and ``bottom``, highest first.

    Each is a surface a ray straight down meets that is no steeper than
    ``capabilities.maxSlope`` degrees.  The ray goes on below each surface it
    meets, so the floors of every storey are found; a mesh's underside faces
    away from it and lets it through.  At most :data:`FLOORS` surfaces are met.
    """
    steepest = np.cos(np.radians(float(capabilities.maxSlope)))
    found: list[float] = []
    start = float(top)
    for _ in range(FLOORS):
        if start <= bottom:
            break
        hit = physics.raycast((float(x), start, float(z)), (0.0, -1.0, 0.0),
                              start - float(bottom), skip=skip)
        if hit is None:
            break
        height = float(hit.point[1])
        if float(hit.normal[1]) >= steepest - 1e-6 and float(hit.distance) > 0.0:
            found.append(height)
        start = min(height, start) - PASS
    return found


#: The most surfaces :func:`floors_below` meets on one line.
FLOORS = 16
#: How far below a surface :func:`floors_below` looks on from, metres.
PASS = 1e-3
#: The clear height over a floor :meth:`PhysicsWalkMixin.spawnAvatar` stands
#: the avatar on, in standing heights.  A ray meets the underside of a closed
#: mesh as it meets a floor; the clear height over it tells the two apart for
#: a solid thinner than this.
HEADROOM = 1.25


def clearance(physics: 'Physics', centre: Sequence[float],
              capabilities: 'CharacterCapabilities', skip: Any = None) -> int:
    """How many of the four horizontal directions the avatar has room to go.

    The standing capsule, lifted half a step off the floor, is placed an arm's
    length (its radius and half a metre at scale 1) along each direction and
    counts where it overlaps no body.  Testing the volume rather than the point
    catches a wall the avatar would walk into but whose face its centre line
    misses, so it does not spawn facing one.  It is a placement test, so a
    barrier thinner than the capsule's arm's length is passed over.
    """
    capsule = _capsule(capabilities)
    radius = float(capabilities.radius)
    base = np.asarray(centre, dtype='d')[:3] + (0.0, 0.5 * float(capabilities.stepHeight), 0.0)
    reach = radius + 0.5 * float(capabilities.standHeight) / 1.8
    clear = 0
    for direction in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1)):
        probe = base + np.asarray(direction, dtype='d') * reach
        if not physics.overlap(capsule, tuple(float(v) for v in probe), skip=skip):
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
    #: Whether switching to walking drops in from the camera rather than
    #: spawning where :meth:`spawnAvatar` found room.  True for a *world* --
    #: somewhere you are inside, where the camera is over ground and dropping in
    #: is what "walk from here" means.  False for a *model*, which is looked at
    #: from outside: the camera there is off in space over nothing, and the
    #: spawn's search for a floor is the only sensible answer.
    physicsDropIn: bool = False
    #: The seconds :meth:`ensurePhysicsWorld` waits for the scene's shapes to
    #: be cooked into scenery before it stands the avatar among them.
    physicsCookWait: float = 30.0

    #: The navigator that owns the camera while walking is off, remembered by
    #: :meth:`setupPhysics` so it can be handed the camera back.
    _freeManager: Any = None
    #: When the avatar was last stepped.
    _physicsLast: float = 0.0
    #: Whether the render queue steps the avatar (:meth:`_walkHook`).
    _walkHooked: bool = False
    #: The frame's time step for the declared modes, while the render queue steps the avatar.
    _walkSteps: Optional['FrameStep'] = None

    if TYPE_CHECKING:
        # Supplied by the context this is mixed into; see the module docstring.
        sg: Any
        platform: Any
        movementManager: Any
        contextDefinition: Any
        physics: 'Physics'

        def getViewPlatform(self) -> Any: ...
        def addEventHandler(self, eventType: str, *arguments: Any,
                            **named: Any) -> Any: ...
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
        self._freeManager = self.movementManager
        if self.physicsToggleKey:
            self.addEventHandler('keyboard', name=self.physicsToggleKey,
                                 state=1, function=self.togglePhysics)
        return self.enablePhysics(True) if enable else False

    # -- the world the avatar walks in ------------------------------------
    def buildPhysicsWorld(self) -> Optional[Bounds]:
        """Put what the avatar walks on into :attr:`physics`; its bounds, or None.

        The default makes the scenegraph's shapes the physics service's
        scenery, a static body each (honouring OMI physics bodies and X3D
        ``Collision`` groups as the scenery does), waits up to
        :attr:`physicsCookWait` seconds for their triangles to be cooked, and
        answers the corners ``(low, high)`` of the scene's triangles.  The
        service is switched on where it was off, and a definition whose
        ``colliders`` is ``none`` becomes ``scene``; one of ``explicit``
        keeps the bodies the application added and no others.  The zones
        carrying gravity are placed in the world, as the render pass places
        them each frame afterwards.

        A context with bodies of its own -- a terrain height field, a level
        format that ships its collision -- overrides this, adds them to
        :attr:`physics` and answers their bounds, and never touches ``sg``.
        """
        scene = getattr(self, 'sg', None)
        if scene is None:
            return None
        from OpenGLContext.physics.gltf_world import scene_bounds  # noqa: PLC0415 every physics import waits for walking

        bounds = scene_bounds(scene)
        if bounds is None:
            return None
        physics = self.physics
        definition = physics.definition
        if definition.colliders == 'none' or not definition.enabled:
            physics.set_config(definition.replaced(
                enabled=True,
                colliders='scene' if definition.colliders == 'none' else definition.colliders))
        physics.scenery_changed(scene, object())
        if not physics.wait_cooked(self.physicsCookWait):
            log.warning('the scene is still being cooked after %.0f s; walking starts without it',
                        self.physicsCookWait)
        from OpenGLContext.physics.zones import scene_zones  # noqa: PLC0415 every physics import waits for walking

        physics.zones_changed(scene_zones(scene))
        return bounds

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
        jumping.  A bound NavigationInfo's avatarSize (``navigationAvatar``:
        radius, eye height, step height) sizes it instead, in the world's own
        units.  Override to make the avatar something else.
        """
        from OpenGLContext.physics.types import CharacterCapabilities
        avatar = self.navigationAvatar
        if avatar is not None:
            radius, eye, step = (float(value) for value in avatar)
            return CharacterCapabilities(
                walkSpeed=WALK_SPEED * scale, runSpeed=RUN_SPEED * scale,
                flySpeed=FLY_SPEED * scale,
                jumpHeight=eye * 0.75, stepHeight=step,
                standHeight=eye * 1.125, crouchHeight=eye * 0.625,
                radius=radius, eyeHeight=eye)
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
        The classic navigation stays declared where it was.
        """
        from OpenGLContext.move.navigationdefinition import Navigation

        definition = self.contextDefinition
        if definition.navigation:
            definition.navigation.setMovingModes(walk_fly_modes(scale))
        else:
            definition.navigation = Navigation(modes=walk_fly_modes(scale))

    def physicsAvatar(self, capabilities: 'CharacterCapabilities', scale: float,
                      lo: Any, hi: Any) -> 'Character':
        """The avatar's :class:`~OpenGLContext.physics.character.Character` in :attr:`physics`.

        Made standing at the middle of the floor of the box ``lo`` to ``hi``,
        falling at :attr:`physicsGravity` times ``scale``, and stepped by its
        owner until walking starts (:meth:`onPhysicsModeChanged`).
        """
        middle = ((lo[0] + hi[0]) / 2.0, float(lo[1]), (lo[2] + hi[2]) / 2.0)
        avatar = self.physics.add_character(
            capabilities=capabilities, position=middle, gravity=self.physicsGravity * scale)
        avatar.framed = False
        return avatar

    def ensurePhysicsWorld(self) -> bool:
        """Build the avatar and its world once.

        False if nothing is walkable, and False, with a warning logged, where
        the physics engine is not available.
        """
        if self.physicsPlatform is not None:
            return True
        from OpenGLContext.physics.engine import EngineUnavailable  # noqa: PLC0415 imports the physics package

        try:
            bounds = self.buildPhysicsWorld()
        except EngineUnavailable as error:
            log.warning('walking is not available: %s', error)
            return False
        if bounds is None:
            return False
        lo, hi = bounds
        scale = self.physicsAvatarScale(lo, hi)
        capabilities = self.characterCapabilities(scale)
        from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
        avatar = self.physicsAvatar(capabilities, scale, lo, hi)
        self.physicsPlatform = PhysicsViewPlatform.over(avatar, yaw=self.physicsYaw)
        self.watchCollisionGroups()
        self.applyMovementModes(scale)
        self.spawnAvatar(lo, hi, capabilities, self.physicsSpawnViewpoints())
        self._physicsLast = self.physicsNow()
        self._walkHook()
        self.physicsPlatform.apply(self)
        return True

    def forgetPhysicsWorld(self) -> None:
        """Take the avatar out of the world, for a scene that replaces the one it walked.

        The next :meth:`enablePhysics` builds a new one.
        """
        platform = self.physicsPlatform
        self.physicsPlatform = None
        self.physicsCollisionReporter = None
        if platform is not None and platform.managed is not None:
            platform.managed.remove()

    #: The bound NavigationInfo's avatarSize (radius, eye height, step height),
    #: set by :func:`OpenGLContext.move.navigationinfo.apply`; None for none.
    navigationAvatar: Optional[tuple[float, float, float]] = None
    #: Sends the X3D Collision groups' events from the avatar's touches, or None.
    physicsCollisionReporter: Optional['CollisionReporter'] = None

    def watchCollisionGroups(self) -> None:
        """Send the Collision groups' collideTime and isActive as the avatar touches them

        Where the scenery holds bodies inside enabled X3D ``Collision`` groups,
        :attr:`physicsCollisionReporter` is made for them; each step then asks
        which of them the avatar's capsule touches (:meth:`reportCollisions`).
        """
        from OpenGLContext.physics.x3dcollision import CollisionReporter, collision_group_bodies  # noqa: PLC0415 every physics import waits for walking

        scene = getattr(self, 'sg', None)
        platform = self.physicsPlatform
        if scene is None or platform is None or platform.managed is None:
            return
        groups = collision_group_bodies(self.physics, scene)
        self.physicsCollisionReporter = (
            CollisionReporter(groups, platform.managed) if groups else None)

    def reportCollisions(self) -> None:
        """Tell the Collision groups the avatar touches now, at the scene's time."""
        reporter = self.physicsCollisionReporter
        if reporter is None:
            return
        from OpenGLContext.events import systemtime  # noqa: PLC0415 every physics import waits for walking

        reporter.update(systemtime.systemTime())

    # -- switching --------------------------------------------------------
    def enablePhysics(self, on: bool = True) -> bool:
        """Walk (``on``) or free-fly, leaving the camera where it is.

        Returns False, having changed nothing, if walking was asked for and the
        world has no walkable geometry.
        """
        if on:
            first = self.physicsPlatform is None
            # Read before the world is built: spawning an avatar moves the
            # camera to it, so afterwards the camera no longer says where the
            # user was.
            camera = getattr(getattr(self, 'platform', None), 'position', None)
            eye = None if camera is None else tuple(float(v) for v in camera[:3])
            if first and not self.ensurePhysicsWorld():
                return False
            # Coming back from a flight always resumes where the camera got to.
            # Entering for the first time does too in a world one is inside
            # (`physicsDropIn`), where dropping in is what walking from here
            # means; in a model, the spawn's search for a floor stands, since
            # the camera is outside the thing looking in.  The *heading* is the
            # spawn's on that first entry, because a viewpoint or a host that
            # pinned one meant it.
            if not first or self.physicsDropIn:
                self.syncAvatarToCamera(heading=not first, eye=eye)
                assert self.physicsPlatform is not None, (
                    'ensurePhysicsWorld has built one by here')
                self.physicsPlatform.set_fly(False)
            if self.movementManager is not None and self._freeManager is not None:
                self._freeManager.unbind(self)
                self.movementManager = None
            self.bindPhysicsInput()
            self.physicsWalking = True
        else:
            if self.movementManager is None \
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
        """Have the service step the avatar in the frame while the context walks.

        Only where the render queue steps the avatar (:meth:`_walkHook`); a
        host that calls :meth:`stepPhysics` steps it itself.  In free-fly the
        avatar stays where it was left.
        """
        platform = self.physicsPlatform
        if platform is not None and platform.managed is not None:
            platform.managed.framed = bool(self.physicsWalking and self._walkHooked)

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
        current = navigation.current
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
                    viewpoints: Sequence[Any] = ()) -> None:
        """Stand the avatar somewhere it can actually walk out of.

        Where the *camera* is does not come into it: :meth:`enablePhysics` seats
        the avatar there itself once this has built one, so this only has to
        find a legal place to stand in the meantime.

        The middle of a world is often solid -- a statue, thick walls -- so
        several footprint positions are tried.  At each, the avatar stands on
        the lowest floor no steeper than its slope limit (:func:`floors_below`)
        where its capsule overlaps nothing and :data:`HEADROOM` standing
        heights over it are clear, the ground floor of a building rather than
        its roof; among the positions with one, the most open
        (:func:`clearance`) wins and, among equals, the most central.  Authored viewpoints are tried first, projected
        straight down to the floor: they are elevated as often as not, so only
        their *heading* is borrowed (:meth:`moveAvatarToViewpoint` is how you
        actually go to one).  With no position counting, the avatar stands at
        the middle.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        if viewpoints:
            platform.yaw = yaw_from_orientation(viewpoints[0].orientation)
        cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
        candidates: list[tuple[float, float]] = []
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
        physics = self.physics
        skip = platform.body
        half = 0.5 * float(capabilities.standHeight)
        capsule = _capsule(capabilities)
        lift = 0.5 * float(capabilities.stepHeight)
        headroom = HEADROOM * float(capabilities.standHeight)
        top = float(hi[1]) + float(capabilities.standHeight)
        bottom = float(lo[1]) - float(capabilities.standHeight)
        best: Any = None                    # ((clearance, -distance), x, floor, z)
        for x, z in candidates:
            standing = [floor for floor in floors_below(physics, x, z, top, bottom,
                                                        capabilities, skip=skip)
                        if not physics.overlap(capsule, (x, floor + half + lift, z), skip=skip)
                        and physics.raycast((x, floor + PASS, z), (0.0, 1.0, 0.0), headroom,
                                            skip=skip) is None]
            if not standing:
                continue
            floor = standing[-1]            # the lowest storey
            centre = (x, floor + half, z)
            clear = clearance(physics, centre, capabilities, skip=skip)
            score = (clear, -((x - cx) ** 2 + (z - cz) ** 2))
            if best is None or score > best[0]:
                best = (score, x, floor, z)
            if clear == 4:                  # fully open: good enough
                break
        if best is not None:
            platform.bind((best[1], best[2] + half, best[3]))
        else:
            platform.bind((cx, float(lo[1]) + float(capabilities.standHeight), cz))

    def physicsHasFloor(self) -> bool:
        """Whether the avatar has a floor under it it can stand on (:func:`floor_below`)."""
        platform = self.physicsPlatform
        if platform is None or platform.managed is None:
            return False
        avatar = platform.managed
        return floor_below(self.physics, avatar.position + (0.0, 0.5 * avatar.height, 0.0),
                           avatar.capabilities, skip=avatar.body) is not None

    def moveAvatarToViewpoint(self, viewpoint: Any) -> None:
        """Put the avatar where a ``Viewpoint`` looks from, facing where it faces.

        Seated on the floor under it, so a viewpoint below standing height
        stands the avatar up; and an elevated one starts the avatar flying,
        because there is nothing under an aerial camera to stand on and falling
        out of the shot is not what asking for that view meant.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        platform.yaw = yaw_from_orientation(viewpoint.orientation)
        platform.pitch = 0.0
        platform.bind_eye(tuple(viewpoint.position))
        platform.set_fly(not self.physicsHasFloor())

    def OnViewpointBound(self, viewpoint: Any) -> None:
        """Stand the avatar where a newly bound viewpoint put the camera

        Called by :func:`OpenGLContext.passes.viewpointbinding.bind_scene_viewpoint`
        with the view platform at ``viewpoint``. While walking, the avatar is
        seated there looking the way the camera looks
        (:meth:`syncAvatarToCamera`), and the platform is put at the
        avatar's eye: a viewpoint inside geometry or below standing height
        is not somewhere the avatar can be, and the transition ends where
        it is. In free-fly the avatar stays where it was left.
        """
        if self.physicsWalking and self.physicsPlatform is not None:
            self.syncAvatarToCamera(pitch=True)
            self.physicsPlatform.apply(self)

    def syncAvatarToCamera(self, heading: bool = True,
                           eye: Optional[Sequence[float]] = None,
                           pitch: bool = False) -> None:
        """Seat the avatar at the current free-fly camera pose, on the floor under it.

        Flying is left on when there is nothing underfoot, so a camera in mid
        air does not drop the moment the avatar takes over; a caller that means
        "drop in from here" turns it off (:meth:`enablePhysics` does).

        ``heading`` takes the camera's bearing as well as its position. A caller
        that has just spawned the avatar passes False, leaving the heading the
        spawn chose -- an authored viewpoint's, or one the host pinned.

        ``eye`` seats the avatar there rather than at the camera's current
        position, for a caller that read the camera before something moved it.

        ``pitch`` keeps the camera's look up or down; otherwise the avatar
        looks level.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        if heading:
            platform.yaw = self.yawFromPlatform()
        platform.pitch = self.pitchFromPlatform() if pitch else 0.0
        platform.bind_eye(tuple(self.platform.position[:3]) if eye is None
                          else tuple(eye))
        platform.set_fly(not self.physicsHasFloor())
        self._physicsLast = self.physicsNow()

    def yawFromPlatform(self) -> float:
        """Heading the free-fly camera is currently looking along."""
        forward = self.platform.forward()
        return float(np.arctan2(forward[0], -forward[2]))

    def pitchFromPlatform(self) -> float:
        """How far above the horizon the camera looks, as the avatar's pitch"""
        forward = self.platform.forward()
        return float(-np.arcsin(np.clip(forward[1], -1.0, 1.0)))

    # -- the frame --------------------------------------------------------
    def _walkHook(self) -> None:
        """Take the frame where the host has a render queue: input before the world steps, the camera after.

        The render queue runs these around the physics service's own frame,
        which was registered when :attr:`physics` was first asked for.
        """
        if self._walkHooked:
            return
        queue = getattr(self, 'renderQueue', None)
        if queue is None:
            return
        from OpenGLContext.events.framestep import FrameStep  # noqa: PLC0415 every physics import waits for walking

        self._walkHooked = True
        self._walkSteps = FrameStep(longest=float(self.physicsMaxStep))
        queue.on_frame(self._walkInput, first=True)
        queue.on_frame(self._walkCamera)
        self.onPhysicsModeChanged()

    def _walkMovesToAViewpoint(self) -> bool:
        from OpenGLContext.passes import viewpointbinding  # noqa: PLC0415 cycle: passes import move

        return viewpointbinding.in_transition(self)

    def _walkInput(self) -> None:
        """Give the declared movement mode the frame, so the avatar's move is set before it steps."""
        from OpenGLContext.events import systemtime  # noqa: PLC0415 every physics import waits for walking

        assert self._walkSteps is not None, 'made with the hook'
        dt = self._walkSteps.step(systemtime.systemTime())
        if (not self.physicsWalking or self.physicsPlatform is None
                or self._walkMovesToAViewpoint()):
            return
        self.updateNavigation(dt)

    def _walkCamera(self) -> None:
        """Put the camera at the avatar's eye once the world has stepped it."""
        if (not self.physicsWalking or self.physicsPlatform is None
                or self._walkMovesToAViewpoint()):
            return
        self.resolvePhysicsStep()
        self.reportCollisions()
        self.physicsPlatform.apply(self)

    def stepPhysics(self, dt: Optional[float] = None) -> None:
        """Advance the avatar one frame and put the camera where it ended up.

        For a host without a render queue, which steps the avatar itself: the
        avatar takes ``dt`` seconds, advancing the world with it.  ``dt``
        defaults to the wall-clock since the last step, clamped to
        :attr:`physicsMaxStep`.  Where the render queue steps the avatar, this
        asks for the next frame.  While the camera is in transition to a newly
        bound viewpoint the avatar is not stepped: it stands where the
        transition ends (:meth:`OnViewpointBound`).
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        if self._walkHooked:
            self.triggerRedraw(1)
            return
        now = self.physicsNow()
        if self._walkMovesToAViewpoint():
            # The transition is moving the camera to where the avatar stands
            self._physicsLast = now
            return
        if dt is None:
            dt = min(now - self._physicsLast, self.physicsMaxStep)
        self._physicsLast = now
        self.updateNavigation(dt)
        platform.update(dt)
        self.resolvePhysicsStep()
        self.reportCollisions()
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
