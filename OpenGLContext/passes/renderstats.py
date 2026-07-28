"""What one frame cost, counted where the pass already knows the answer.

A developer looking at a slow frame wants to know how much of it is the scene
and how much is the renderer: how many shapes survived culling, how many of
them collapsed into instanced draws, and how many draw calls came out the far
end.  Those numbers exist inside the render pass for a moment each frame and
are then thrown away, so this is where they are kept.

**Counted, not estimated.**  Every field here is incremented at the place the
pass does the thing it counts.  Triangle counts are deliberately absent: the
pass does not know them -- a geometry node does, and instrumenting every
``render()`` in the system to find out would cost more than the answer is
worth.  A number that is not counted is not reported, rather than guessed at.

Read it through the debug overlay
(:func:`OpenGLContext.ui.debugoverlay.render_provider`), which is what turns
these into rows on screen.
"""

from __future__ import annotations

__all__ = ['RenderStats']


class RenderStats:
    """Counts for the frame currently being drawn.

    One instance per pass, reset at the top of each frame rather than made
    afresh, so a context holding a reference to it keeps reading live numbers.
    """

    __slots__ = ('shapes', 'opaque', 'transparent', 'instanceGroups',
                 'instances', 'draws')

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        """Start a new frame's counts."""
        #: Shapes the pass gathered from the scenegraph, culling included.
        self.shapes = 0
        #: How those divided between the two geometry passes.
        self.opaque = 0
        self.transparent = 0
        #: Instanced draws, and how many shapes they stood in for.
        self.instanceGroups = 0
        self.instances = 0
        #: Draw calls the pass issued for scene geometry -- one per shape it
        #: drew singly, plus one per instance group.
        self.draws = 0

    def __repr__(self) -> str:
        return ('RenderStats(shapes=%d, draws=%d, instances=%d in %d groups)'
                % (self.shapes, self.draws, self.instances,
                   self.instanceGroups))
