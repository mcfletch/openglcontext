"""First-person terrain walking: clamp the viewer to the ground, block trunks,
and stream camera-following content.

Mix into an interactive Context. Each rendered frame, after the movement step and
before the scene is drawn, the viewer is snapped to the height field and pushed out
of any collider it walked into. The clamp runs in :meth:`DoEventCascade` — not
``OnDraw`` — because the navigation step is applied *inside* ``OnDraw`` before the
render; clamping before that step lets a held key walk the camera straight through
the ground. Register streamers to refresh camera-following fields (grass, near-mesh
trees) as the viewer moves.

Usage::

    class Scene(TerrainWalkMixin, BaseContext):
        def OnInit(self):
            ...
            self.init_walk(height_field, collider_pos=trunks, collider_radius=trunk_r)
            self.add_stream(10.0, self._refresh_grass)
"""
import math
import numpy as np


class TerrainWalkMixin:
    """Ground-clamp + trunk-collision + move-triggered streaming for a walker.

    Class attributes (override on the subclass as needed):

    :cvar eye_height: camera height above the ground, world units.
    :cvar player_radius: body radius added to each collider radius.
    :cvar collide_broadphase: half-width of the box pre-filter before the collision
        sqrt (should exceed the largest collider radius + player_radius).
    """
    eye_height = 1.7
    player_radius = 0.25
    collide_broadphase = 3.0

    def init_walk(self, height_field, collider_pos=None, collider_radius=None):
        """Bind the walker to a height field and (optional) cylinder colliders.

        :param height_field: a :class:`HeightField` giving ground height.
        :param collider_pos: (N, 3) collider (trunk) world positions, or None.
        :param collider_radius: (N,) collider radii (player_radius is added), or None
            for a uniform player-radius collider.
        """
        self._tw_hf = height_field
        self._tw_cpos = None if collider_pos is None else np.asarray(collider_pos, np.float32)
        self._tw_crad = None if collider_radius is None else np.asarray(collider_radius, np.float32)
        self._tw_streams = []
        self._tw_pose = None
        self._tw_build_grid()

    def _tw_build_grid(self):
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
        self._tw_grid = None
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
        grid = {}
        for idx, key in enumerate(zip(cx.tolist(), cz.tolist())):
            grid.setdefault(key, []).append(idx)
        self._tw_grid = {k: np.asarray(v, np.intp) for k, v in grid.items()}
        self._tw_cell = cell

    def add_stream(self, step, fn, turn=None):
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

    def _tw_xz(self):
        p = self.platform.position
        return float(p[0]), float(p[2])

    def _push_out(self, x, z):
        """Push (x, z) out of the deepest collider it lies inside (one resolve)."""
        cpos = self._tw_cpos
        grid = self._tw_grid
        if cpos is None or not len(cpos) or grid is None:
            return x, z
        cell = self._tw_cell
        gx = int(math.floor(x / cell)); gz = int(math.floor(z / cell))
        cand = [grid[key]
                for a in (gx - 1, gx, gx + 1) for b in (gz - 1, gz, gz + 1)
                if (key := (a, b)) in grid]
        if not cand:                              # player outside every occupied cell
            return x, z
        # Ascending order matches a full ``np.where`` scan, so the deepest-penetration
        # argmax below breaks ties on the same collider a whole-field scan would pick.
        idx = np.sort(np.concatenate(cand))
        dx = x - cpos[idx, 0]; dz = z - cpos[idx, 2]
        bp = self.collide_broadphase
        near = (np.abs(dx) < bp) & (np.abs(dz) < bp)
        if not np.any(near):
            return x, z
        i = idx[near]; dx = dx[near]; dz = dz[near]
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
                x += dx[k] * push; z += dz[k] * push
        return x, z

    def collide_and_clamp(self):
        """Sweep the viewer from its previous spot to the new one, resolving trunk
        collisions along the way (so a fast step can't tunnel through a thin trunk),
        then set its height to the terrain."""
        if self.platform is None or getattr(self, '_tw_hf', None) is None:
            return
        x, z = self._tw_xz()
        prev = getattr(self, '_tw_prev', None)
        if prev is None:
            x, z = self._push_out(x, z)
        else:
            px, pz = prev
            ddx = x - px; ddz = z - pz
            dist = math.hypot(ddx, ddz)
            n = min(self.collide_max_substeps, max(1, int(math.ceil(dist / self.collide_substep))))
            sx = ddx / n; sz = ddz / n
            x, z = px, pz
            for _ in range(n):
                x += sx; z += sz
                x, z = self._push_out(x, z)   # resolve at each substep -> no tunnelling
        self._tw_prev = (x, z)
        self.platform.setPosition((x, self._tw_hf.height_at(x, z) + self.eye_height, z))

    def DoEventCascade(self):
        changed = super(TerrainWalkMixin, self).DoEventCascade()
        self.collide_and_clamp()
        return changed

    def _tw_forward(self):
        """Horizontal unit forward vector ``(fx, fz)`` from the platform orientation."""
        fx, _fy, fz, _w = self.platform.quaternion * [0.0, 0.0, -1.0, 0.0]
        n = math.hypot(fx, fz) or 1.0
        return fx / n, fz / n

    def _tw_yaw(self):
        """Horizontal facing angle from the platform orientation (radians)."""
        fx, fz = self._tw_forward()
        return math.atan2(fx, fz)

    def _tw_pose_sig(self):
        """A signature of the current view that changes iff the rendered image can.

        Position plus orientation quaternion: nothing in a static terrain scene
        animates, so an unchanged signature means an unchanged frame."""
        p = self.platform.position
        return (float(p[0]), float(p[1]), float(p[2])) + tuple(float(v) for v in self.platform.quaternion.internal)

    def OnIdle(self, *args):
        if self.platform is not None and getattr(self, '_tw_hf', None) is not None:
            x, z = self._tw_xz(); yaw = self._tw_yaw()
            for st in self._tw_streams:
                step, turn, last, fn = st
                moved = last is None or abs(x - last[0]) + abs(z - last[1]) > step
                turned = turn is not None and last is not None and \
                    abs((yaw - last[2] + math.pi) % (2 * math.pi) - math.pi) > turn
                if moved or turned:
                    st[2] = (x, z, yaw); fn(x, z)
            # Redraw only when the view actually changed (or a field just restreamed):
            # a parked camera in a static scene must not spin the GPU at full rate.
            pose = self._tw_pose_sig()
            if pose != self._tw_pose:
                self._tw_pose = pose
                self.triggerRedraw(1)
        sup = super(TerrainWalkMixin, self)
        return sup.OnIdle(*args) if hasattr(sup, 'OnIdle') else None
