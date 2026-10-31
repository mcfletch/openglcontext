"""Walking a landscape: an avatar on a height field, blocked by trunks and rocks, with
camera-following content streamed as it moves.

This is the terrain form of
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`. The avatar, the
declared :class:`~OpenGLContext.move.modes.MovementMode` nodes and the keys that
drive them are the ones every other program here uses, so a landscape is walked
with the same controls, the same settings screen and the same key-binding page as
a glTF model or an arena map.

The ground, the trunks and the rocks are bodies in the context's
:attr:`~OpenGLContext.context.Context.physics` world
(:class:`~OpenGLContext.physics.landscape.Landscape`): the ground is the height
field the terrain node draws, answered from the field itself instead of from a
mesh, the trunks are cylinders standing on it, and the rocks are made as the
walker nears them and dropped as it leaves. The avatar is a
:class:`~OpenGLContext.physics.character.Character` in that world, stepped by the
service in the frame, so a rigid body added to the context lands on the ground,
rolls against the trunks and is pushed by the walker.

Mouse-look is the mode a landscape starts in; ``m`` cycles to the walk and fly
modes, ``f`` flies, and ``g`` hands the camera back to the free-fly navigator.

Usage::

    class Scene(TerrainWalkMixin, BaseContext):
        def OnInit(self):
            ...
            self.init_walk(height_field, collider_pos=trunks, collider_radius=trunk_r)
            self.add_collider_source(rocks.mounds_near)
            self.setupPhysics(enable=True)
            self.add_stream(10.0, self._refresh_grass)

A standing walker asks for no frame: the service asks for one while the
character moves, falls or has a move held, and the pose of the view is compared
in :meth:`~TerrainWalkMixin.OnIdle` for the pointer turning it.

Without :meth:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin.setupPhysics` the
free-fly navigator keeps the camera and the mix-in only holds it down: the viewer
is seated on the height field and pushed out of any collider it walked into, in
:meth:`DoEventCascade` -- not ``OnDraw`` -- because the navigation step is applied
*inside* ``OnDraw`` before the render, and clamping before that step lets a held
key walk the camera straight through the ground.

See [docs/terrain.rst](../../docs/terrain.rst#heightfield) and
[docs/navigation.rst](../../docs/navigation.rst).
"""
from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from OpenGLContext.move.physicswalk import PhysicsWalkMixin
from OpenGLContext.physics.landscape import Landscape, NearbyColliders

if TYPE_CHECKING:
    from OpenGLContext.physics.character import Character
    from OpenGLContext.physics.types import CharacterCapabilities

    class _WalkHost:
        """The host-context members the walk mixin relies on, supplied by the
        composed interactive Context (its view platform, physics and event hooks)."""

        platform: Any
        physics: Any
        renderQueue: Any

        def triggerRedraw(self, force: int = 0) -> Any: ...
        def DoEventCascade(self) -> Any: ...
        def OnIdle(self, *arguments: Any) -> Any: ...
else:
    _WalkHost = object

#: What a collider source answers: ``(positions, radii)``, or with ``rims`` and
#: ``tops`` as well for domes.
ColliderAnswer = Callable[[float, float, float], tuple[Any, ...]]


class TerrainWalkMixin(PhysicsWalkMixin, _WalkHost):
    """An avatar that walks a height field, and the streaming that follows it.

    Class attributes (override on the subclass as needed):

    :cvar eye_height: camera height above the ground, world units.
    :cvar player_radius: the avatar's radius.
    :cvar step_height: the tallest step the avatar climbs, in metres.
    :cvar max_slope: the steepest ground the avatar stands on, in degrees.
    :cvar collider_reach: how far from the avatar, in metres, the rocks of a
        collider source are bodies in the world.
    """
    eye_height = 1.7
    player_radius = 0.25
    #: The tallest step the walker climbs, in metres: a rock whose surface rises this
    #: much or less above the walker's feet is walked onto, and a taller one is a wall.
    step_height = 0.5
    #: The steepest ground the walker stands on, in degrees. A mountainside is walked,
    #: not slid down.
    max_slope = 75.0
    #: How far from the walker, in metres, the rocks a source answers for are bodies
    #: in the world. A body thrown further off than this meets the ground and the
    #: trunks but not the rocks.
    collider_reach = 24.0
    #: The longest stretch of a free-fly camera's move seated at once, in metres. A
    #: move longer than a trunk is wide is seated in pieces, or it would step over
    #: the trunk: the end of it is clear on both sides.
    collide_substep = 0.35
    #: The most pieces a free-fly move is seated in; a faster move may pass a trunk.
    collide_max_substeps = 8
    #: How far from a point the rocks under it are asked for, in metres.
    _SUPPORT_REACH = 3.0

    #: The height field the walker is bound to.
    _tw_hf: Any = None
    #: The ground and trunks of that field as bodies.
    _tw_landscape: Landscape | None = None
    #: The walker in the physics world, once made.
    _tw_character: Character | None = None
    #: The callables the colliders that come and go are asked of, for the rocks the
    #: avatar stands on.
    _tw_sources: Sequence[ColliderAnswer] = ()
    #: What the free-fly camera was last held down at, so a parked one is not seated
    #: again and a move is seated from where the last one ended.
    _tw_clamped: tuple[float, ...] | None = None

    def init_walk(self, height_field: Any, collider_pos: Any = None,
                  collider_radius: Any = None) -> None:
        """Bind the walker to a height field and (optional) cylinder colliders.

        The field becomes the ground of the context's physics world and each
        collider a cylinder standing on it. The world makes no static body of
        the scene's own shapes: the walker's colliders are the ones it is given.
        Walking is the physics service's, so the service is switched on.

        :param height_field: a ground, such as a :class:`HeightField`, that
            answers ``sample(x, z)`` for arrays of metres.
        :param collider_pos: (N, 3) collider (trunk) world positions, or None.
            A trunk stands on the ground under its x and z; its y is not read.
        :param collider_radius: (N,) collider radii in metres, or None for posts of
            the thinnest radius. The avatar's own radius is its capsule's.
        """
        if self._tw_landscape is not None:
            self._tw_landscape.remove()
        physics = self.physics
        if physics.definition.colliders == 'scene' or not physics.definition.enabled:
            physics.set_config(physics.definition.replaced(colliders='explicit', enabled=True))
        self._tw_hf = height_field
        self._tw_streams: list[list[Any]] = []
        self._tw_pose: tuple[float, ...] | None = None
        self._tw_clamped = None
        self._tw_landscape = Landscape(physics, height_field, collider_pos, collider_radius)
        self._tw_landscape.follow(self._tw_focus)
        if self.physicsPlatform is not None:
            self.standAvatarOnTerrain()

    def add_stream(self, step: float, fn: Callable[[float, float], Any],
                   turn: float | None = None) -> None:
        """Call ``fn(x, z)`` whenever the viewer has moved ``step`` world units (L1),
        or (if ``turn`` is given) turned ``turn`` radians, since that streamer last
        fired. Fires once immediately on the first frame. Use ``turn`` for fields that
        depend on the *facing* (e.g. a view-frustum cull), not just the position."""
        self._tw_streams.append([float(step), None if turn is None else float(turn), None, fn])

    def add_collider_source(self, source: ColliderAnswer) -> Any:
        """Add colliders that come and go as the walker moves, such as streamed rocks.

        ``source(x, z, reach)`` answers ``(positions, radii)``, an ``(N, 3)`` array and an
        ``(N,)`` array, for the colliders within ``reach`` metres of ``(x, z)``: cylinders
        standing on their positions, which the walker is pushed out of at any height.

        It may answer ``(positions, radii, rims, tops)`` instead, with two more ``(N,)``
        arrays, for mounds the walker can climb. Each is a dome over a circle of its radius
        about its position, ``rims`` metres high at the edge and ``tops`` at the middle, both
        above the position. The walker walks onto a mound where its surface rises at most
        :attr:`step_height` above the walker's feet, stands on the surface, and is pushed out
        of the mound where it rises more.

        The colliders within :attr:`collider_reach` metres of the walker are bodies in
        the world (:class:`~OpenGLContext.physics.landscape.NearbyColliders`), and are
        dropped as the walker leaves them. The source is asked once the walker has moved a
        couple of metres, so it should answer from what it has kept, and it may be called
        from the thread the world is stepped on.

        Returns the :class:`~OpenGLContext.physics.sources.SourceHandle`, whose ``remove()``
        takes the source and its bodies out.
        """
        self._tw_sources = [*self._tw_sources, source]
        return self.physics.add_collider_source(
            NearbyColliders(source, reach=self.collider_reach), focus=self._tw_focus)

    def _tw_focus(self) -> Sequence[float] | np.ndarray:
        """Where the colliders that come and go are kept about: the walker, else the camera."""
        walker = self._tw_character
        if walker is not None and walker.alive:
            return walker.position
        if self.platform is None:
            return (0.0, 0.0, 0.0)
        return tuple(float(v) for v in self.platform.position[:3])

    def _tw_xz(self) -> tuple[float, float]:
        p = self.platform.position
        return float(p[0]), float(p[2])

    # -- what is underfoot, apart from the ground ----------------------------
    @staticmethod
    def _mound_surface(distance: Any, positions: Any, radii: Any, rims: Any, tops: Any) -> Any:
        """The height of each mound's surface at ``distance`` from its middle: its rim at
        its edge and its top at the middle, along a dome, and -inf beyond the edge."""
        reach = np.asarray(radii, np.float64)
        across = np.asarray(distance, np.float64) / reach
        inside = across < 1.0
        rim = np.asarray(rims, np.float64)
        rise = (np.asarray(tops, np.float64) - rim) * np.sqrt(np.clip(1.0 - across * across, 0.0, 1.0))
        return np.where(inside, np.asarray(positions, np.float64)[:, 1] + rim + rise, -np.inf)

    def _tw_support(self, x: float, z: float) -> float:
        """The highest mound surface under ``(x, z)``, or -inf where there is none."""
        best = -math.inf
        for source in self._tw_sources:
            answer = source(x, z, self._SUPPORT_REACH)
            if len(answer) < 4 or not len(answer[0]):
                continue
            positions, radii, rims, tops = answer[:4]
            positions = np.asarray(positions, np.float32)
            distance = np.hypot(x - positions[:, 0], z - positions[:, 2])
            best = max(best, float(self._mound_surface(distance, positions, radii, rims, tops).max()))
        return best

    def _tw_ground(self, x: float, z: float) -> float:
        """The height of the ground under ``(x, z)``, the mounds on it counted."""
        return max(float(self._tw_hf.height_at(x, z)), self._tw_support(x, z))

    # -- the free-fly camera -------------------------------------------------
    def collide_and_clamp(self) -> None:
        """Hold the free-fly camera down on the terrain, out of the trunks and rocks.

        For the navigator that writes ``context.platform`` directly.  While the
        avatar owns the camera it is stepped against the same world (by the
        physics service), and a second clamp here would overwrite the pose it had
        just solved.  The avatar is put where the camera is, its feet on the
        ground and out of anything it overlaps, and the camera goes to its eye.

        A move is seated from where the last one ended, in pieces no longer than
        :attr:`collide_substep`, because a move that crosses a trunk narrower than
        itself ends clear of it on the far side.
        """
        if self.physicsWalking or self.platform is None or self._tw_hf is None:
            return
        position = tuple(float(v) for v in self.platform.position[:3])
        previous = self._tw_clamped
        if position == previous:
            return
        walker = self._tw_walker()
        x, z = position[0], position[2]
        if previous is None:
            pieces, along = 1, (0.0, 0.0)
        else:
            along = (x - previous[0], z - previous[2])
            pieces = min(self.collide_max_substeps,
                         max(1, math.ceil(math.hypot(*along) / self.collide_substep)))
            x, z = previous[0], previous[2]
        for _ in range(pieces):
            x += along[0] / pieces
            z += along[1] / pieces
            walker.teleport((x, self._tw_ground(x, z), z))
            x, z = float(walker.position[0]), float(walker.position[2])
        self.platform.setPosition(tuple(float(v) for v in walker.eye))
        self._tw_clamped = tuple(float(v) for v in self.platform.position[:3])

    def DoEventCascade(self) -> Any:
        changed = super(TerrainWalkMixin, self).DoEventCascade()
        self.collide_and_clamp()
        return changed

    # -- the avatar, and the world it is in -------------------------------------
    def walkBounds(self) -> tuple[np.ndarray, np.ndarray]:
        """The corners ``(low, high)`` of the box the height field fills, in metres."""
        from OpenGLContext.physics.landscape import ground_figures  # noqa: PLC0415 imported with the landscape it measures

        extent, (low, high), _ = ground_figures(self._tw_hf)
        (x0, z0), (x1, z1) = extent if extent is not None else ((0.0, 0.0), (0.0, 0.0))
        return np.array([x0, low, z0]), np.array([x1, high, z1])

    @staticmethod
    def physicsAvatarScale(low: Any, high: Any) -> float:
        """A person is a person: a height field is already in world units.

        The physics form sizes the avatar to the model it is walking, because a
        viewer opens anything from a bolt to a city.  A landscape is not a
        model of unknown size -- its metres are metres -- and scaling to its
        extent would put a forty-metre giant in a four-kilometre forest.
        """
        return 1.0

    def characterCapabilities(self, scale: float = 1.0) -> CharacterCapabilities:
        """The avatar's dimensions and speeds, sized by this mix-in's own knobs.

        :attr:`eye_height` and :attr:`player_radius` are what a terrain scene
        is written against -- the camera height it framed its content for, and
        the body its colliders were measured for -- so they, rather than
        the physics defaults, decide the avatar's eye and girth.  The rest of
        the body keeps its proportions about them: the top of the head stays
        the same distance above the eyes, and a crouch is never taller than a
        stand.  :attr:`step_height` and :attr:`max_slope` are the steps it
        climbs and the ground it stands on.
        """
        capabilities = super(TerrainWalkMixin, self).characterCapabilities(scale)
        head = capabilities.standHeight - capabilities.eyeHeight
        capabilities.eyeHeight = float(self.eye_height)
        capabilities.standHeight = capabilities.eyeHeight + head
        capabilities.crouchHeight = min(capabilities.crouchHeight,
                                        capabilities.standHeight)
        capabilities.radius = float(self.player_radius)
        capabilities.stepHeight = float(self.step_height)
        capabilities.maxSlope = float(self.max_slope)
        return capabilities

    def applyMovementModes(self, scale: float) -> None:
        """Declare mouse-look, walking and flying -- unless the host already did.

        First-person, because a landscape is a place you are *inside* and
        steering it with the pointer is what anyone arriving expects to find.
        A host that declared its own vocabulary keeps it: those are speeds and
        bindings somebody chose, and there is no scale to re-derive them at.
        """
        definition = self.contextDefinition
        declared = definition.navigation
        if declared and declared.movingModes():
            return
        from OpenGLContext.move.modes import walk_fly_modes
        if declared:
            declared.setMovingModes(walk_fly_modes(scale, first_person=True))
        else:
            from OpenGLContext.move.navigationdefinition import Navigation
            definition.navigation = Navigation(
                modes=walk_fly_modes(scale, first_person=True))

    def _tw_walker(self) -> Character:
        """The avatar's character, made at the camera's position on first use.

        The service steps it only while the context is walking.
        """
        walker = self._tw_character
        if walker is None or not walker.alive:
            x, z = self._tw_xz()
            walker = self._tw_character = self.physics.add_character(
                capabilities=self.characterCapabilities(self.physicsAvatarScale(None, None)),
                position=(x, float(self._tw_hf.height_at(x, z)), z))
            walker.framed = False
        return walker

    def buildPhysicsWorld(self) -> tuple[np.ndarray, np.ndarray] | None:
        """The bounds of the height field, whose ground and trunks :meth:`init_walk` put in the world.

        None until a height field is bound and the context has a camera.
        """
        if self._tw_hf is None or self.platform is None:
            return None
        return self.walkBounds()

    def physicsAvatar(self, capabilities: CharacterCapabilities, scale: float,
                      lo: Any, hi: Any) -> Character:
        """The walker the free-fly camera is held down by, which becomes the avatar."""
        return self._tw_walker()

    def watchCollisionGroups(self) -> None:
        """Nothing: the walker's world is the landscape, and the scene's shapes are not bodies in it."""

    def onPhysicsModeChanged(self) -> None:
        """Seat the free-fly camera afresh after a switch, as well as framing the avatar."""
        self._tw_clamped = None
        super(TerrainWalkMixin, self).onPhysicsModeChanged()

    def spawnAvatar(self, low: Any, high: Any,
                    capabilities: CharacterCapabilities,
                    viewpoints: Sequence[Any] = ()) -> None:
        """Stand the avatar on the terrain under wherever the camera is.

        The physics form searches the world for somewhere open to stand,
        because the middle of a model is as likely as not to be solid.  Every
        point of a height field is standable, so the search has nothing to
        look for: the scene chose where to start by placing its camera, and the
        answer is the ground under it.
        """
        platform = self.physicsPlatform
        if platform is None or self._tw_hf is None:
            return
        platform.yaw = self.yawFromPlatform()
        self.standAvatarOnTerrain(self._tw_xz())

    def syncAvatarToCamera(self, heading: bool = True,
                           eye: Sequence[float] | None = None,
                           pitch: bool = False) -> None:
        """Seat the avatar on the terrain under the free-fly camera.

        The physics form asks the world whether there is anything underfoot and
        starts the avatar flying when there is not.  A height field always has
        ground under it, so coming back from a flight lands rather than hovers.

        ``heading`` takes the camera's bearing along with its position, as in
        the physics form; a freshly spawned avatar keeps the heading it was
        spawned with.  ``eye`` seats it at a pose read before the spawn moved
        the camera.  ``pitch`` keeps the camera's look up or down.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        if heading:
            platform.yaw = self.yawFromPlatform()
        platform.pitch = self.pitchFromPlatform() if pitch else 0.0
        where = tuple(self.platform.position[:3]) if eye is None else tuple(eye)
        self.standAvatarOnTerrain((float(where[0]), float(where[2])))

    def standAvatarOnTerrain(self, at: tuple[float, float] | None = None) -> None:
        """Put the avatar's feet on the terrain, at ``at`` or wherever it is standing.

        A *placement*: it moves the avatar down onto the ground as well as up
        out of it, which is what "walk from here" has to mean when here is a
        camera that was flying over the canopy. The avatar is put out of any
        trunk or rock it was placed in, and the ground is found again where it
        ended up.
        """
        platform = self.physicsPlatform
        if platform is None or self._tw_hf is None:
            return
        walker = platform.managed
        x, z = at if at is not None else (float(walker.position[0]), float(walker.position[2]))
        for _ in range(2):
            walker.teleport((x, self._tw_ground(x, z), z))
            x, z = float(walker.position[0]), float(walker.position[2])

    def resolvePhysicsStep(self) -> None:
        """The ground as a floor under a flying avatar, after the world has stepped it."""
        self.resolveTerrain()

    def resolveTerrain(self) -> None:
        """Keep a flying avatar above the ground.

        Flying is noclip in every mode that offers it, so the world's ground and
        trunks do not stop a flier, and a flight through the canopy is not
        bounced off trunks. The ground is still a floor: the avatar is lifted to
        it when it is at or below it, with the rocks standing on it counted.
        """
        platform = self.physicsPlatform
        if platform is None or self._tw_hf is None:
            return
        controller = platform.character
        if not controller.flying:
            return
        x, z = float(controller.position[0]), float(controller.position[2])
        half = float(controller.height) * 0.5
        ground = self._tw_ground(x, z)
        if controller.position[1] - half <= ground:
            place = getattr(controller, 'place', None)
            if place is not None:           # a Jolt character is moved by a command
                place((x, ground + half, z))
            else:
                controller.position[1] = ground + half
            if controller.vy < 0.0:
                controller.vy = 0.0

    def _tw_forward(self) -> tuple[float, float]:
        """Horizontal unit forward vector ``(fx, fz)`` from the platform orientation."""
        fx, _fy, fz = self.platform.forward()
        n = math.hypot(fx, fz) or 1.0
        return fx / n, fz / n

    def _tw_yaw(self) -> float:
        """Horizontal facing angle from the platform orientation (radians)."""
        fx, fz = self._tw_forward()
        return math.atan2(fx, fz)

    def _tw_pose_sig(self) -> tuple[float, ...]:
        """A signature of the current view that changes iff the rendered image can.

        Position plus orientation quaternion: nothing in a static terrain scene
        animates, so an unchanged signature means an unchanged frame."""
        p = self.platform.position
        return (float(p[0]), float(p[1]), float(p[2])) + tuple(float(v) for v in self.platform.quaternion.internal)

    def OnIdle(self, *arguments: Any) -> Any:
        if self.platform is not None and self._tw_hf is not None:
            x, z = self._tw_xz()
            yaw = self._tw_yaw()
            for st in self._tw_streams:
                step, turn, last, fn = st
                moved = last is None or abs(x - last[0]) + abs(z - last[1]) > step
                turned = turn is not None and last is not None and \
                    abs((yaw - last[2] + math.pi) % (2 * math.pi) - math.pi) > turn
                if moved or turned:
                    st[2] = (x, z, yaw)
                    fn(x, z)
            # Ask for a frame only when the view changed: the service asks for
            # one while the avatar moves, and a parked camera in a static scene
            # must not spin the GPU at full rate.
            pose = self._tw_pose_sig()
            if pose != self._tw_pose:
                self._tw_pose = pose
                self.triggerRedraw(1)
        sup = super(TerrainWalkMixin, self)
        return sup.OnIdle(*arguments) if hasattr(sup, 'OnIdle') else None
