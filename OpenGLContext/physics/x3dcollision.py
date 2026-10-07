"""X3D's Collision outputs from the walker's touches -- no GL

An enabled ``Collision`` group's geometry is a static body of its own in the
walk's world (:func:`OpenGLContext.physics.gltf_world.collision_groups`). A
:class:`CollisionReporter`, told of the world's contact events, sends
``isActive TRUE`` and ``collideTime`` from the group whose body the walker's
capsule begins touching, and from each enabled group around it, and
``isActive FALSE`` when the touch ends.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

__all__ = ['CollisionReporter']


class CollisionReporter:
    """The walker's touches with the Collision groups' bodies, as their events"""

    def __init__(self, groups: Mapping[int, Sequence[Any]], walker: Any) -> None:
        #: The Collision groups of each static body, innermost first.
        self.groups = dict(groups)
        #: The walker's body index.
        self.walker = walker

    def heard(self, event: Any, now: float) -> None:
        """A contact event of the world, at time `now`"""
        a, b = event.a.index, event.b.index
        if self.walker not in (a, b):
            return
        nodes = self.groups.get(b if a == self.walker else a)
        if not nodes:
            return
        if event.phase == 'begin':
            for node in nodes:
                node.isActive = True
                node.collideTime = now
        elif event.phase == 'end':
            for node in nodes:
                node.isActive = False
