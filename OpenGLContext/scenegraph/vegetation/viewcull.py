"""Instanced rows streamed to the GPU as the view sees them.

An instanced draw hands the GPU every plant in its set, and the GPU discards
those outside the view only after fetching, transforming and assembling their
vertices. A field kept around a moving camera has most of its plants beside and
behind it, so most of that work is for nothing, and none of it depends on the
size of the window.

:class:`CulledRows` cuts the rows into clusters of neighbouring rows, tests each
cluster's box against the frustum the pass holds for the view being drawn
(:func:`OpenGLContext.frustum.boxes_outside`, the test the pass's own shapes are
culled by), and streams only the rows of the clusters in view. Rows stored in
spatial order (:func:`OpenGLContext.passes.instancing.morton_order`) make compact
clusters; any order is correct, and a scattered one culls less.
"""
from __future__ import annotations

import math
from typing import Any, Optional, Protocol

import numpy as np
from OpenGL.GL import (
    GL_TRIANGLES, GL_UNSIGNED_INT, glDrawArraysInstanced, glDrawElementsInstanced,
)

from OpenGLContext import frustum as frustums

__all__ = ['CLUSTER_ROWS', 'DISC_MARGIN_METRES', 'MARGIN_METRES', 'MIN_TRIANGLES',
           'CulledRows']

#: How many neighbouring rows are tested as one box. Fewer follow the frustum's
#: edge more closely and cost more to test.
CLUSTER_ROWS = 32

#: How far outside the frustum, in metres, the clusters streamed reach. A camera
#: that has turned or moved less than this since they were chosen sees only
#: clusters already streamed, and chooses and uploads nothing.
MARGIN_METRES = 2.0

#: How far outside a disc, in metres, the clusters streamed reach. A disc that
#: moves less than this since they were chosen is covered by clusters already
#: streamed.
DISC_MARGIN_METRES = 1.0

#: The fewest triangles a set draws before it is worth testing: a set cheaper to
#: draw than to cull is streamed whole. A set limited to a disc is always tested,
#: since the disc is what keeps the rows beyond it off the GPU.
MIN_TRIANGLES = 100_000

#: A disc: the x and z of its centre, and its radius, in metres.
Disc = tuple[float, float, float]


class _Buffer(Protocol):
    """What :class:`CulledRows` streams into: an ``InstanceBuffer``."""

    count: int

    def upload(self, rows: Any) -> None: ...


class CulledRows:
    """A staged set of instance rows, streamed to a buffer as a view sees them.

    ``rows`` are the instanced layers' rows (see
    :data:`~OpenGLContext.scenegraph.instancedgl.INSTANCE_FLOATS`): position,
    yaw, scale and shade. ``reach`` is how far a plant extends sideways from its
    base point, and ``rise`` and ``drop`` how far it extends above and below it,
    each for a scale of one. A cluster's box is its rows' base points widened by
    those for the largest scale in the set, so a plant whose base is out of view
    but whose crown is not is kept. ``triangles`` is what one row draws; a set of
    fewer than :data:`MIN_TRIANGLES` in all is not tested unless it is limited to
    a disc.

    :meth:`stage` takes the whole set. :meth:`show` takes the pass drawing and
    streams into the buffer the rows in clusters its frustum reaches, widened by
    :data:`MARGIN_METRES`; called again for a view that needs only clusters already
    streamed, it uploads nothing. With a ``disc`` it streams only the clusters that
    also reach that disc, widened by :data:`DISC_MARGIN_METRES`: a layer that draws
    the plants within some radius of the camera stages everything it has scattered
    once, and moves the disc with the camera. A pass with no frustum, and a shared
    draw of several views, which sends each instance to each view, are sent every
    row inside the disc, and every row where there is none, as is everything when
    ``enabled`` is False.
    """

    def __init__(self, buffer: _Buffer, reach: float, rise: float,
                 drop: float = 0.0, enabled: bool = True, triangles: int = 1) -> None:
        self.buffer = buffer
        self.reach = float(reach)
        self.rise = float(rise)
        self.drop = float(drop)
        self.enabled = bool(enabled)
        self.triangles = int(triangles)
        self._rows = np.zeros((0, 0), np.float32)
        self._boxes: "Optional[tuple[np.ndarray, np.ndarray]]" = None
        #: What the fused test of a view and a disc reads: each box's centre with a 1 appended,
        #: its half extents, the x and z of its centre, and the radius of the circle about
        #: that centre which holds it on the ground.
        self._fused: "Optional[tuple[np.ndarray, ...]]" = None
        #: Whether the boxes of the staged rows have been looked for yet.
        self._boxed = False
        #: Whether the staged rows draw enough triangles to be worth testing against a frustum.
        self._worth_a_frustum = False
        self._sizes = np.zeros(0, np.int64)
        #: The clusters the buffer was last filled for: None for every row.
        self._shown: Optional[np.ndarray] = None
        #: What the buffer was last filled for besides the clusters: the disc, if any, and
        #: whether a frustum cut it.
        self._shown_disc: Optional[Disc] = None
        self._shown_by_frustum = False
        self._uploaded = False

    def stage(self, rows: np.ndarray) -> None:
        """Take a new set; the next :meth:`show` uploads from it."""
        self._rows = rows
        self._boxes = self._fused = None
        self._boxed = False
        self._uploaded = False

    def _cluster(self, limited: bool) -> None:
        """Cut the staged rows into clusters and box each, once for each staging.

        A set not worth testing, or with rows that are not numbers, has no boxes
        and is streamed whole.
        """
        rows = self._rows
        self._worth_a_frustum = len(rows) * self.triangles >= MIN_TRIANGLES
        if not self.enabled or not len(rows) or not (self._worth_a_frustum or limited):
            return
        with np.errstate(all='ignore'):
            if not np.isfinite(rows[:, :5].sum()):
                return
        starts = np.arange(0, len(rows), CLUSTER_ROWS)
        base = rows[:, :3].astype('d')
        low = np.minimum.reduceat(base, starts, axis=0)
        high = np.maximum.reduceat(base, starts, axis=0)
        size = float(np.abs(rows[:, 4]).max())
        low[:, [0, 2]] -= self.reach * size
        high[:, [0, 2]] += self.reach * size
        low[:, 1] -= self.drop * size
        high[:, 1] += self.rise * size
        self._sizes = np.diff(np.append(starts, len(rows)))
        centres, halves = (low + high) * 0.5, (high - low) * 0.5
        self._boxes = (centres, halves)
        self._fused = (np.concatenate([centres, np.ones((len(centres), 1))], 1), halves,
                       np.ascontiguousarray(centres[:, 0]), np.ascontiguousarray(centres[:, 2]),
                       np.hypot(halves[:, 0], halves[:, 2]))

    def show(self, mode: Any, disc: Optional[Disc] = None) -> int:
        """Stream the rows the view of ``mode`` can see, within ``disc``; the number of them."""
        if not self._boxed:
            self._boxed = True
            self._cluster(disc is not None)
        planes = self._planes(mode)
        if self._uploaded and self._covers(planes, disc):
            return int(self.buffer.count)
        chosen = self._choose(planes, disc)
        if chosen is None:
            self.buffer.upload(self._rows)
        else:
            self.buffer.upload(self._rows[np.repeat(chosen, self._sizes)])
        self._shown = chosen
        self._shown_disc = disc
        self._shown_by_frustum = planes is not None
        self._uploaded = True
        return int(self.buffer.count)

    def draw_arrays(self, copies: int = 1, part: int = 0) -> None:  # noqa: ARG002 one part is drawn
        """Draw the rows streamed as triangles read in order, from the vertex array bound.

        ``copies`` is how many times over each instance is drawn in a shared draw of views.
        """
        glDrawArraysInstanced(GL_TRIANGLES, 0, 3 * self.triangles, int(self.buffer.count) * copies)

    def draw_elements(self, copies: int = 1, part: int = 0) -> None:  # noqa: ARG002 one part is drawn
        """Draw the rows streamed as indexed triangles, from the vertex array bound."""
        glDrawElementsInstanced(GL_TRIANGLES, 3 * self.triangles, GL_UNSIGNED_INT, None,
                                int(self.buffer.count) * copies)

    def release(self) -> None:
        """Let go of what this holds on the GPU, which is nothing: the buffer is its owner's."""

    def _planes(self, mode: Any) -> Optional[np.ndarray]:
        """The planes of the view being drawn, or None where every row is to be sent.

        A set cheaper to draw than to test is not cut by the view.
        """
        held = getattr(mode, 'frustum', None)
        if (self._boxes is None or not self._worth_a_frustum or held is None
                or int(getattr(mode, 'viewCopies', 0) or 0) > 1):
            return None
        planes = np.asarray(held.planes, 'd')
        return planes if len(planes) else None

    def _covers(self, planes: Optional[np.ndarray], disc: Optional[Disc]) -> bool:
        """Whether the clusters streamed already hold every one these planes and this disc reach."""
        if self._shown is None:
            # Every row is up; only a disc that has never been applied has more to cut.
            return disc is None or self._shown_disc is not None
        if planes is None and disc is not None and not self._shown_by_frustum \
                and self._shown_disc is not None:
            # Clusters were streamed within the radius and margin of one centre, so those
            # within a radius of one this near to it are among them.
            x, z, radius = disc
            x0, z0, radius0 = self._shown_disc
            return radius + math.hypot(x - x0, z - z0) <= radius0 + DISC_MARGIN_METRES
        needed = self._wanted(planes, disc, 0.0, 0.0)
        return needed is not None and not bool((needed & ~self._shown).any())

    def _choose(self, planes: Optional[np.ndarray], disc: Optional[Disc]) -> Optional[np.ndarray]:
        """A flag for each cluster within the margins of the planes and the disc, or None for all."""
        chosen = self._wanted(planes, disc, MARGIN_METRES, DISC_MARGIN_METRES)
        return None if chosen is None or chosen.all() else chosen

    def _wanted(self, planes: Optional[np.ndarray], disc: Optional[Disc],
                margin: float, disc_margin: float) -> Optional[np.ndarray]:
        """A flag for each cluster that reaches inside the planes and the disc, widened by the
        margins, or None where neither limits the set.

        The planes keep what :func:`OpenGLContext.frustum.boxes_outside` keeps, found in two
        products: a box is outside when its corner furthest in front of some plane is behind
        it. A disc keeps the clusters whose bounding circle reaches it.
        """
        if self._fused is None or (planes is None and disc is None):
            return None
        centres, halves, x_centres, z_centres, rho = self._fused
        wanted = None
        if planes is not None:
            front = centres @ planes.T + halves @ np.abs(planes[:, :3]).T
            wanted = (front >= -margin).all(axis=1)
        if disc is not None:
            x, z, radius = disc
            near = np.hypot(x_centres - x, z_centres - z) <= rho + (radius + disc_margin)
            wanted = near if wanted is None else wanted & near
        return wanted
