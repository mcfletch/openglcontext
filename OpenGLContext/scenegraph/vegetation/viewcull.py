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

from typing import Any, Optional, Protocol

import numpy as np

from OpenGLContext import frustum as frustums

__all__ = ['CLUSTER_ROWS', 'MARGIN_METRES', 'MIN_TRIANGLES', 'CulledRows']

#: How many neighbouring rows are tested as one box. Fewer follow the frustum's
#: edge more closely and cost more to test.
CLUSTER_ROWS = 32

#: How far outside the frustum, in metres, the clusters streamed reach. A camera
#: that has turned or moved less than this since they were chosen sees only
#: clusters already streamed, and chooses and uploads nothing.
MARGIN_METRES = 2.0

#: The fewest triangles a set draws before it is worth testing: a set cheaper to
#: draw than to cull is streamed whole.
MIN_TRIANGLES = 100_000


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
    fewer than :data:`MIN_TRIANGLES` in all is not tested.

    :meth:`stage` takes the whole set. :meth:`show` takes the pass drawing and
    streams into the buffer the rows in clusters its frustum reaches, widened by
    :data:`MARGIN_METRES`; called again for a view that needs only clusters already
    streamed, it uploads nothing. A pass with no frustum, and a shared draw of
    several views, which sends each instance to each view, are sent every row, as
    is everything when ``enabled`` is False.
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
        self._sizes = np.zeros(0, np.int64)
        #: The clusters the buffer was last filled for: None for every row.
        self._shown: Optional[np.ndarray] = None
        self._uploaded = False

    def stage(self, rows: np.ndarray) -> None:
        """Take a new set; the next :meth:`show` uploads from it."""
        self._rows = rows
        self._boxes = None
        self._uploaded = False
        if not self.enabled or len(rows) * self.triangles < MIN_TRIANGLES:
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
        self._boxes = ((low + high) * 0.5, (high - low) * 0.5)

    def show(self, mode: Any) -> int:
        """Stream the rows the view of ``mode`` can see; the number of them."""
        planes = self._planes(mode)
        if self._uploaded and self._covers(planes):
            return int(self.buffer.count)
        chosen = self._choose(planes)
        if chosen is None:
            self.buffer.upload(self._rows)
        else:
            self.buffer.upload(self._rows[np.repeat(chosen, self._sizes)])
        self._shown = chosen
        self._uploaded = True
        return int(self.buffer.count)

    def _planes(self, mode: Any) -> Optional[np.ndarray]:
        """The planes of the view being drawn, or None where every row is to be sent."""
        held = getattr(mode, 'frustum', None)
        if self._boxes is None or held is None or int(getattr(mode, 'viewCopies', 0) or 0) > 1:
            return None
        planes = np.asarray(held.planes, 'd')
        return planes if len(planes) else None

    def _covers(self, planes: Optional[np.ndarray]) -> bool:
        """Whether the clusters streamed already hold every one these planes reach."""
        if self._shown is None:
            return True
        if planes is None or self._boxes is None:
            return False
        needed = ~frustums.boxes_outside(*self._boxes, None, planes)
        return not bool((needed & ~self._shown).any())

    def _choose(self, planes: Optional[np.ndarray]) -> Optional[np.ndarray]:
        """A flag for each cluster within the margin of the planes, or None for all."""
        if planes is None or self._boxes is None:
            return None
        widened = planes.copy()
        widened[:, 3] += MARGIN_METRES
        chosen = ~frustums.boxes_outside(*self._boxes, None, widened)
        return None if chosen.all() else np.asarray(chosen)
