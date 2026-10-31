"""X3D's Collision outputs from the walker's touches -- no GL

Each shape inside an enabled ``Collision`` group is a static body of the
physics service's scenery (:mod:`OpenGLContext.physics.colliders`).
:func:`collision_group_bodies` finds those bodies and the groups around each.
A :class:`CollisionReporter` asks, once a step, which of them the walker's
capsule touches: the capsule, :data:`TOUCH` of its radius and :data:`SKIN`
metres wider, overlapping the body (:meth:`Physics.overlap <OpenGLContext.physics.service.Physics.overlap>`).
A body the walker begins touching sends ``isActive TRUE`` and ``collideTime``
from its group and from each enabled group around it, and ``isActive FALSE``
when the last body of a group is no longer touched.

The touches are asked of the world rather than heard as contact events,
since a walker's capsule moving against static bodies makes no contact
event on the Jolt engine.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.character import Character
    from OpenGLContext.physics.service import Physics

__all__ = ['SKIN', 'TOUCH', 'CollisionReporter', 'collision_group_bodies']

#: How much wider than the walker's capsule a touch reaches, as a part of its radius.
TOUCH = 0.1
#: And in metres besides: a Jolt character stops 0.02 m short of what it walks
#: into, and standing against a wall touches it.
SKIN = 0.03


def collision_group_bodies(physics: Physics, scene: Any) -> dict[Body, list[Any]]:
    """The scenery bodies of ``scene`` inside enabled X3D Collision groups, with those groups.

    By body: the group the shape is in, then each enabled group around it.
    Empty for a scene with none, and for shapes that have no scenery body yet.
    """
    from OpenGLContext.physics.gltf_world import iter_meshes  # noqa: PLC0415 imports the scenegraph walk

    found: dict[Body, list[Any]] = {}
    derived = physics.scenery.derived
    for site in iter_meshes(scene):
        if not site.groups:
            continue
        body = derived.get(site.node)
        if body is not None and body.alive:
            found[body] = list(site.groups)
    return found


class CollisionReporter:
    """The walker's touches with the Collision groups' bodies, as their events"""

    def __init__(self, groups: Mapping[Body, Sequence[Any]], walker: Character) -> None:
        #: The Collision groups of each static body, innermost first.
        self.groups = {body: list(nodes) for body, nodes in groups.items()}
        #: The walking character.
        self.walker = walker
        #: The bodies the walker touched at the last :meth:`update`.
        self.touching: set[Body] = set()

    def touched(self) -> set[Body]:
        """The groups' bodies the walker's capsule touches now."""
        from OpenGLContext.physics.proxy import Proxy  # noqa: PLC0415 kept with the physics package

        walker = self.walker
        radius = float(walker.radius)
        height = float(walker.height)
        reach = radius * (1.0 + TOUCH) + SKIN
        capsule = Proxy.capsule(max(height - 2.0 * radius, 0.0), reach)
        centre = walker.position + (0.0, 0.5 * height, 0.0)
        found = walker.physics.overlap(capsule, tuple(float(v) for v in centre), skip=walker.body)
        return {body for body in found if body in self.groups}

    def update(self, now: float) -> None:
        """Send the groups' events for the touches begun and ended since the last update, at time ``now``."""
        if not self.walker.alive:
            return
        touching = self.touched()
        for body in touching - self.touching:
            for node in self.groups[body]:
                node.isActive = True
                node.collideTime = now
        still = [node for body in touching for node in self.groups[body]]
        for body in self.touching - touching:
            for node in self.groups[body]:
                if not any(node is other for other in still):
                    node.isActive = False
        self.touching = touching
