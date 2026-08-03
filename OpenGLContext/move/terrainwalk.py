"""Walking a landscape: an avatar on a height field, blocked by trunks, with
camera-following content streamed as it moves.

This is the terrain form of
:class:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin`, and it is the same
capability with a different ground.  The avatar, the declared
:class:`~OpenGLContext.move.modes.MovementMode` nodes and the keys that drive
them are the ones every other program here uses -- so a landscape is walked with
the same controls, the same settings screen and the same key-binding page as a
glTF model or an arena map.  What differs is where the ground and the obstacles
come from: a :class:`~OpenGLContext.scenegraph.terrain.HeightField` and a field
of cylinders, resolved analytically, rather than a cooked collision mesh.  A
landscape spanning kilometres would be millions of triangles as a mesh, and the
height field answers the same question exactly and in constant time.

Mouse-look is the mode a landscape starts in; ``m`` cycles to the walk and fly
modes, ``f`` flies, and ``g`` hands the camera back to the free-fly navigator.

Usage::

    class Scene(TerrainWalkMixin, BaseContext):
        def OnInit(self):
            ...
            self.init_walk(height_field, collider_pos=trunks, collider_radius=trunk_r)
            self.setupPhysics(enable=True)
            self.add_stream(10.0, self._refresh_grass)

Without :meth:`~OpenGLContext.move.physicswalk.PhysicsWalkMixin.setupPhysics`
the free-fly navigator keeps the camera and the mix-in only holds it down: the
viewer is snapped to the height field and pushed out of any collider it walked
into, in :meth:`DoEventCascade` -- not ``OnDraw`` -- because the navigation step
is applied *inside* ``OnDraw`` before the render, and clamping before that step
lets a held key walk the camera straight through the ground.

See [docs/terrain.html](../../docs/terrain.html) and
[docs/navigation.html](../../docs/navigation.html).
"""
import math
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.move.physicswalk import PhysicsWalkMixin

if TYPE_CHECKING:
    from omi_physics.character import CharacterCapabilities

    class _WalkHost:
        """The host-context members the walk mixin relies on, supplied by the
        composed interactive Context (its view platform and event/redraw hooks)."""

        platform: Any

        def triggerRedraw(self, force: int = 0) -> Any: ...
        def DoEventCascade(self) -> Any: ...
        def OnIdle(self, *args: Any) -> Any: ...
else:
    _WalkHost = object


class TerrainWalkMixin(PhysicsWalkMixin, _WalkHost):
    """An avatar that walks a height field, and the streaming that follows it.

    Class attributes (override on the subclass as needed):

    :cvar eye_height: camera height above the ground, world units.
    :cvar player_radius: body radius added to each collider radius.
    :cvar collide_broadphase: half-width of the box pre-filter before the collision
        sqrt (should exceed the largest collider radius + player_radius).
    """
    eye_height = 1.7
    player_radius = 0.25
    collide_broadphase = 3.0

    def init_walk(self, height_field: Any, collider_pos: Any = None,
                  collider_radius: Any = None) -> None:
        """Bind the walker to a height field and (optional) cylinder colliders.

        :param height_field: a :class:`HeightField` giving ground height.
        :param collider_pos: (N, 3) collider (trunk) world positions, or None.
        :param collider_radius: (N,) collider radii (player_radius is added), or None
            for a uniform player-radius collider.
        """
        self._tw_hf = height_field
        self._tw_cpos = None if collider_pos is None else np.asarray(collider_pos, np.float32)
        self._tw_crad = None if collider_radius is None else np.asarray(collider_radius, np.float32)
        self._tw_streams: List[list] = []
        self._tw_pose: Optional[Tuple[float, ...]] = None
        self._tw_build_grid()

    def _tw_build_grid(self) -> None:
        """Bucket the colliders into a uniform (x, z) hash grid for the collision
        broadphase, so :meth:`_push_out` tests a handful of nearby colliders instead
        of the whole field every substep.

        The cell is at least the broadphase box half-width *and* the largest
        collider's reach (its radius plus the player radius). At that size any
        collider able to overlap the player at a query point lies in the point's own
        cell or one of its eight neighbours, so a 3x3 lookup misses nothing and the
        resolution result is identical to a full scan.

        Sets ``_tw_grid`` to a dict mapping ``(cell_x, cell_z)`` to an ascending
        array of collider indices, or ``None`` when there are no colliders.
        """
        self._tw_grid: Optional[Dict[tuple, np.ndarray]] = None
        self._tw_cell = 0.0
        cpos = self._tw_cpos
        if cpos is None or not len(cpos):
            return
        reach = self.player_radius
        if self._tw_crad is not None and len(self._tw_crad):
            reach += float(self._tw_crad.max())
        cell = max(float(self.collide_broadphase), reach, 1e-6)
        cx = np.floor(cpos[:, 0] / cell).astype(np.int64)
        cz = np.floor(cpos[:, 2] / cell).astype(np.int64)
        grid: Dict[tuple, List[int]] = {}
        for idx, key in enumerate(zip(cx.tolist(), cz.tolist(), strict=True)):
            grid.setdefault(key, []).append(idx)
        self._tw_grid = {k: np.asarray(v, np.intp) for k, v in grid.items()}
        self._tw_cell = cell

    def add_stream(self, step: float, fn: Callable[[float, float], Any],
                   turn: Optional[float] = None) -> None:
        """Call ``fn(x, z)`` whenever the viewer has moved ``step`` world units (L1),
        or (if ``turn`` is given) turned ``turn`` radians, since that streamer last
        fired. Fires once immediately on the first frame. Use ``turn`` for fields that
        depend on the *facing* (e.g. a view-frustum cull), not just the position."""
        self._tw_streams.append([float(step), None if turn is None else float(turn), None, fn])

    #: Substep length for swept collision. A single move step must never exceed the
    #: thinnest collider diameter or a fast walk tunnels straight through it, so the
    #: displacement is split into steps no longer than this before resolving trunks.
    collide_substep = 0.35
    #: Cap on swept substeps per frame, so a very fast fly doesn't run the collision
    #: pass hundreds of times (beyond this a step may tunnel; acceptable at that speed).
    collide_max_substeps = 8
    #: Where the last resolved step ended, which is what the next one is swept
    #: from.  None until something has walked, and again after a flight, since
    #: there is no walked path to sweep along.
    _tw_prev: Optional[Tuple[float, float]] = None

    def _tw_xz(self) -> Tuple[float, float]:
        p = self.platform.position
        return float(p[0]), float(p[2])

    def _push_out(self, x: float, z: float) -> Tuple[float, float]:
        """Push (x, z) out of the deepest collider it lies inside (one resolve)."""
        cpos = self._tw_cpos
        grid = self._tw_grid
        if cpos is None or not len(cpos) or grid is None:
            return x, z
        cell = self._tw_cell
        gx = int(math.floor(x / cell))
        gz = int(math.floor(z / cell))
        cand = [grid[key]
                for a in (gx - 1, gx, gx + 1) for b in (gz - 1, gz, gz + 1)
                if (key := (a, b)) in grid]
        if not cand:                              # player outside every occupied cell
            return x, z
        # Ascending order matches a full ``np.where`` scan, so the deepest-penetration
        # argmax below breaks ties on the same collider a whole-field scan would pick.
        idx = np.sort(np.concatenate(cand))
        dx = x - cpos[idx, 0]
        dz = z - cpos[idx, 2]
        bp = self.collide_broadphase
        near = (np.abs(dx) < bp) & (np.abs(dz) < bp)
        if not np.any(near):
            return x, z
        i = idx[near]
        dx = dx[near]
        dz = dz[near]
        if self._tw_crad is not None:
            r = self._tw_crad[i] + self.player_radius
        else:
            r = np.full(len(i), self.player_radius, np.float32)
        d2 = dx * dx + dz * dz
        k = int(np.argmax(r * r - d2))            # deepest penetration
        if r[k] * r[k] > d2[k]:
            d = math.sqrt(d2[k])
            if d < 1e-4:                          # dead-centre: push direction undefined
                x += r[k]                         # eject along +x by the full radius
            else:
                push = (r[k] - d) / d
                x += dx[k] * push
                z += dz[k] * push
        return x, z

    def _tw_sweep(self, x: float, z: float) -> Tuple[float, float]:
        """Resolve the move from the last resolved spot to ``(x, z)``.

        Swept in substeps no longer than :attr:`collide_substep`, because a
        single resolve at the end of a fast step walks straight through a trunk
        thinner than the step: the end point is clear on both sides of it.
        """
        prev = self._tw_prev
        if prev is None:
            x, z = self._push_out(x, z)
        else:
            px, pz = prev
            ddx = x - px
            ddz = z - pz
            dist = math.hypot(ddx, ddz)
            n = min(self.collide_max_substeps, max(1, int(math.ceil(dist / self.collide_substep))))
            sx = ddx / n
            sz = ddz / n
            x, z = px, pz
            for _ in range(n):
                x += sx
                z += sz
                x, z = self._push_out(x, z)
        self._tw_prev = (x, z)
        return x, z

    def collide_and_clamp(self) -> None:
        """Hold the free-fly camera down on the terrain, out of the trunks.

        For the navigator that writes ``context.platform`` directly.  While the
        avatar owns the camera it resolves its own step against the same ground
        (:meth:`resolveTerrain`), and a second clamp here would overwrite the
        height it had just solved -- flattening a jump and grounding a flight.
        """
        if self.physicsWalking or self.platform is None \
                or getattr(self, '_tw_hf', None) is None:
            return
        x, z = self._tw_sweep(*self._tw_xz())
        self.platform.setPosition((x, self._tw_hf.height_at(x, z) + self.eye_height, z))

    def DoEventCascade(self) -> Any:
        changed = super(TerrainWalkMixin, self).DoEventCascade()
        self.collide_and_clamp()
        return changed

    # -- the avatar, and the ground it is not allowed through ----------------
    def buildPhysicsWorld(self) -> Optional[Tuple[Any, Tuple[Any, Any]]]:
        """An empty collision world over the height field's square.

        The ground and the trunks are analytic, and answering "how high is the
        terrain here" from a height field is exact and costs the same wherever
        you stand; cooking a landscape into a collision mesh would be millions
        of triangles for a worse answer.  So the character controller is given
        a world with nothing in it and the surface is resolved in
        :meth:`resolveTerrain`, which is where the trunks are resolved too.

        The bounds are the height field's own extent and relief, which is what
        the avatar and the spawn are sized and placed against.
        """
        field = getattr(self, '_tw_hf', None)
        if field is None:
            return None
        from omi_physics.world import PhysicsWorld
        half = float(field.extent) / 2.0
        heights = np.asarray(field.grid, 'd') * float(field.relief)
        low = np.array([-half, float(heights.min()), -half])
        high = np.array([half, float(heights.max()), half])
        return PhysicsWorld(), (low, high)

    @staticmethod
    def physicsAvatarScale(low: Any, high: Any) -> float:
        """A person is a person: a height field is already in world units.

        The physics form sizes the avatar to the model it is walking, because a
        viewer opens anything from a bolt to a city.  A landscape is not a
        model of unknown size -- its metres are metres -- and scaling to its
        extent would put a forty-metre giant in a four-kilometre forest.
        """
        return 1.0

    def characterCapabilities(self, scale: float = 1.0) -> 'CharacterCapabilities':
        """The avatar's dimensions and speeds, sized by this mix-in's own knobs.

        :attr:`eye_height` and :attr:`player_radius` are what a terrain scene
        is written against -- the camera height it framed its content for, and
        the body the collider radii were measured for -- so they, rather than
        the physics defaults, decide the avatar's eye and girth.  The rest of
        the body keeps its proportions about them: the top of the head stays
        the same distance above the eyes, and a crouch is never taller than a
        stand.
        """
        capabilities = super(TerrainWalkMixin, self).characterCapabilities(scale)
        head = capabilities.standHeight - capabilities.eyeHeight
        capabilities.eyeHeight = float(self.eye_height)
        capabilities.standHeight = capabilities.eyeHeight + head
        capabilities.crouchHeight = min(capabilities.crouchHeight,
                                        capabilities.standHeight)
        capabilities.radius = float(self.player_radius)
        return capabilities

    def applyMovementModes(self, scale: float) -> None:
        """Declare mouse-look, walking and flying -- unless the host already did.

        First-person, because a landscape is a place you are *inside* and
        steering it with the pointer is what anyone arriving expects to find.
        A host that declared its own vocabulary keeps it: those are speeds and
        bindings somebody chose, and there is no scale to re-derive them at.
        """
        definition = self.contextDefinition
        if getattr(definition, 'movementModes', None):
            return
        from OpenGLContext.move.modes import walk_fly_modes
        definition.movementModes = walk_fly_modes(scale, first_person=True)

    def spawnAvatar(self, low: Any, high: Any,
                    capabilities: 'CharacterCapabilities',
                    viewpoints: Sequence[Any] = ()) -> None:
        """Stand the avatar on the terrain under wherever the camera is.

        The physics form searches the world for somewhere open to stand,
        because the middle of a model is as likely as not to be solid.  Every
        point of a height field is standable, so the search has nothing to
        look for: the scene chose where to start by placing its camera, and the
        answer is the ground under it.
        """
        platform = self.physicsPlatform
        if platform is None or getattr(self, '_tw_hf', None) is None:
            return
        platform.yaw = self.yawFromPlatform()
        x, z = self._tw_xz()
        # ``bind`` places the capsule's *centre*, so feet on the ground is half
        # a body above it.
        platform.bind((x, self._tw_hf.height_at(x, z) + capabilities.standHeight * 0.5,
                       z))
        self.standAvatarOnTerrain()

    def syncAvatarToCamera(self) -> None:
        """Seat the avatar on the terrain under the free-fly camera.

        The physics form asks the world whether there is anything underfoot and
        starts the avatar flying when there is not.  A height field always has
        ground under it, so coming back from a flight lands rather than hovers.
        """
        platform = self.physicsPlatform
        if platform is None:
            return
        platform.yaw = self.yawFromPlatform()
        platform.pitch = 0.0
        platform.bind_eye(tuple(self.platform.position[:3]))
        self.standAvatarOnTerrain()
        self._physicsLast = self.physicsNow()

    def standAvatarOnTerrain(self) -> None:
        """Put the avatar's feet on the terrain, wherever it is standing.

        A *placement* rather than a step: it moves the avatar down onto the
        ground as well as up out of it, which is what "walk from here" has to
        mean when here is a camera that was flying over the canopy.  The
        per-frame resolve (:meth:`resolveTerrain`) is a floor instead, so a jump
        rises and an arrival from the air falls.
        """
        platform = self.physicsPlatform
        field = getattr(self, '_tw_hf', None)
        if platform is None or field is None:
            return
        character = platform.character
        x, z = self._push_out(float(character.position[0]),
                              float(character.position[2]))
        character.position[:] = (
            x, float(field.height_at(x, z)) + float(character.height) * 0.5, z)
        character.vy = 0.0
        character.grounded = True
        self._tw_prev = (x, z)

    def resolvePhysicsStep(self) -> None:
        """The ground and the trunks, resolved after the character's own step."""
        self.resolveTerrain()

    def resolveTerrain(self) -> None:
        """Put the avatar on the height field and out of the trunks.

        The surface is a **floor**, not a rail: the avatar is lifted to it when
        it is at or below it and left alone above, so a jump rises and an
        arrival from the air falls.  Landing zeroes what is left of the fall and
        reports the avatar grounded, which is what lets it jump again.

        Trunks are resolved for a walker and not for a flier -- flying is noclip
        in every mode that offers it, and a flight through the canopy that
        bounced off trunks would be unusable.
        """
        platform = self.physicsPlatform
        field = getattr(self, '_tw_hf', None)
        if platform is None or field is None:
            return
        character = platform.character
        x, z = float(character.position[0]), float(character.position[2])
        if character.flying:
            self._tw_prev = (x, z)            # nothing swept: it went over them
        else:
            x, z = self._tw_sweep(x, z)
        half = float(character.height) * 0.5
        ground = float(field.height_at(x, z))
        y = float(character.position[1])
        if y - half <= ground:
            y = ground + half
            if character.vy < 0.0:
                character.vy = 0.0
            if not character.flying:
                character.grounded = True
        character.position[:] = (x, y, z)

    def _tw_forward(self) -> Tuple[float, float]:
        """Horizontal unit forward vector ``(fx, fz)`` from the platform orientation."""
        fx, _fy, fz, _w = self.platform.quaternion * [0.0, 0.0, -1.0, 0.0]
        n = math.hypot(fx, fz) or 1.0
        return fx / n, fz / n

    def _tw_yaw(self) -> float:
        """Horizontal facing angle from the platform orientation (radians)."""
        fx, fz = self._tw_forward()
        return math.atan2(fx, fz)

    def _tw_pose_sig(self) -> Tuple[float, ...]:
        """A signature of the current view that changes iff the rendered image can.

        Position plus orientation quaternion: nothing in a static terrain scene
        animates, so an unchanged signature means an unchanged frame."""
        p = self.platform.position
        return (float(p[0]), float(p[1]), float(p[2])) + tuple(float(v) for v in self.platform.quaternion.internal)

    def OnIdle(self, *args: Any) -> Any:
        if self.platform is not None and getattr(self, '_tw_hf', None) is not None:
            # The avatar first, so the streamers below and the frame they feed
            # see where the walker has got to rather than where it was.
            if self.physicsWalking:
                self.stepPhysics()
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
            # With no avatar to step, redraw only when the view actually changed:
            # a parked free-fly camera in a static scene must not spin the GPU at
            # full rate.  A walking one is a simulation and is drawn every frame,
            # because gravity moves it whether or not anyone touched a key.
            pose = self._tw_pose_sig()
            if pose != self._tw_pose:
                self._tw_pose = pose
                self.triggerRedraw(1)
        sup = super(TerrainWalkMixin, self)
        return sup.OnIdle(*args) if hasattr(sup, 'OnIdle') else None
