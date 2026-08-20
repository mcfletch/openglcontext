"""VRML97 Level-of-Detail node: which version of a thing to draw at this distance.

An ``LOD`` holds the same object modelled several times over, finest first, and
``range`` gives the distances at which each gives way to the next: ``range[i]``
is where level ``i`` hands over to level ``i + 1``. ``center`` is the point in
the node's own coordinates those distances are measured to, so a figure's
distance is measured to the figure and not to the world origin.

Which level that comes to is settled once a frame by the render pass, which is
the only thing that knows where the viewer is
(:meth:`OpenGLContext.passes._flat.FlatPass.selectLevels`). Changing level
announces itself on the same signal a ``Switch`` uses, because the pass keeps a
flattened scenegraph and a level nobody told it about would not be drawn.
"""
from typing import Any, Sequence

import numpy as np
from pydispatch import dispatcher
from vrml.vrml97 import basenodes, nodetypes

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.switch import SWITCH_CHANGE_SIGNAL

__all__ = ['LOD', 'distance_to_viewer']


def distance_to_viewer(node: Any, modelview: Any) -> float:
    """How far the viewer is from ``node``'s centre, given its modelview.

    The modelview takes the node's own coordinates to eye coordinates, where
    the viewer is the origin -- so the length of the transformed centre is the
    distance, and no separate camera position has to be threaded through.
    """
    centre = np.concatenate([np.asarray(node.center, dtype='d')[:3], [1.0]])
    eye = centre @ np.asarray(modelview, dtype='d')
    return float(np.linalg.norm(eye[:3]))


class LOD(basenodes.LOD):
    """Level-of-Detail node based on VRML 97 LOD.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#LOD
    """

    #: Which level is being drawn. Not a VRML field: the file says what the
    #: levels are and where they change over, and this is what that comes to
    #: for the viewer as it stands.
    whichLevel: int = 0

    def select(self, distance: float) -> bool:
        """Choose the level for a viewer ``distance`` away; True if it changed.

        A node with no ranges keeps its finest level, which is what VRML97
        leaves to the browser: guessing a distance for content that named none
        would draw somebody's model at a detail they never asked for.
        """
        wanted = self.levelFor(distance)
        if wanted == self.whichLevel:
            return False
        self.whichLevel = wanted
        chosen = self.renderedChildren()
        dispatcher.send(sender=self, signal=SWITCH_CHANGE_SIGNAL,
                        value=chosen[0] if chosen else None)
        return True

    def levelFor(self, distance: float) -> int:
        """The level index a viewer ``distance`` away should be shown."""
        # ``range`` is an MFFloat, which arrives as an array: its emptiness has
        # to be asked by length rather than by truth.
        ranges: Sequence[float] = self.range if self.range is not None else ()
        levels = len(self.level)
        if not levels or not len(ranges):
            return 0
        chosen = 0
        for index, edge in enumerate(ranges):
            if distance < float(edge):
                break
            chosen = index + 1
        return min(chosen, levels - 1)

    def renderedChildren(self, types: Any = (nodetypes.Children,
                                             nodetypes.Rendering,)) -> list:
        """The level to render, or nothing where this node has no levels."""
        levels = self.level
        if not levels:
            return []
        node = levels[min(self.whichLevel, len(levels) - 1)]
        return [node] if isinstance(node, types) else []

    def boundingVolume(self, mode: Any = None) -> Any:
        """Bounds of the level being drawn.

        The levels are the same object at different detail, so any of them
        bounds the node; the one on screen is the one whose bounds are wanted,
        and it is what a coarser level's slightly different silhouette should
        be culled by.
        """
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        volumes = []
        dependencies: list = [(self, 'level'), (self, 'range')]
        for child in self.renderedChildren():
            if hasattr(child, 'boundingVolume'):
                child_volume = child.boundingVolume(mode)
                volumes.append(child_volume)
                dependencies.append((child_volume, None))
        try:
            volume: Any = boundingvolume.BoundingBox.union(volumes, None)
        except boundingvolume.UnboundedObject:
            volume = boundingvolume.UnboundedVolume()
        return boundingvolume.cacheVolume(self, volume, dependencies)
