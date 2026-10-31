"""X3D's RigidBodyPhysics nodes, on the engine's clock -- docs/x3d.rst

A `RigidBodyCollection` simulates its bodies on the engine the physics
definition names (:func:`~OpenGLContext.physics.x3djolt.make_rigid_system`),
Jolt by default, and a `CollisionSensor` reports the touches among its
collider's collidables (:func:`~OpenGLContext.physics.x3djolt.make_sensing`).
Where the engine named is the deprecated omi engine and omi_physics is not
installed, a collection or sensor logs that once and stays still. Bound to
contexts, each
steps once a frame through the context's render queue, on the engine's clock
(:class:`~OpenGLContext.scenegraph.x3druntime.EngineTimed`), for as long as
the context draws the scene the node is in, and a collection asks for frames
while any of its bodies is moving.

`CollidableShape` draws its `shape`, and `CollidableOffset` the collidable it
holds, each placed by its `translation` and `rotation`. `RigidBody`,
`CollisionCollection`, `CollisionSpace`, `Contact` and the joints are data
the collection reads.
"""
from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING, Any, Optional

from vrml import cache
from vrml.vrml97 import nodetypes, transformmatrix
from vrml.x3d import nodes as x3d

from OpenGLContext.events.renderqueue import DEFER
from OpenGLContext.physics.engine import EngineUnavailable
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.x3druntime import EngineTimed

if TYPE_CHECKING:
    from OpenGLContext.physics import x3drigid

__all__ = ['CollidableOffset', 'CollidableShape', 'CollisionSensor', 'RigidBodyCollection']

log = logging.getLogger(__name__)


class _Collidable(nodetypes.Transforming):
    """A collidable drawn as what it holds, placed by its translation and rotation"""

    translation: Any
    rotation: Any

    def localMatrices(self, translate: bool = True, scale: bool = True,
                      rotate: bool = True) -> Any:
        """A holder of the collidable's (forward, inverse) matrices, kept until it moves"""
        key = ('local_matrices', translate, rotate)
        holder = cache.CACHE.getHolder(self, key=key)
        if holder is not None and holder.data is not None:
            return holder
        fields = [name for name, wanted in (('translation', translate), ('rotation', rotate))
                  if wanted]
        holder = cache.CACHE.holder(self, None, key=key)
        for name in fields:
            holder.depend(self, name)
        holder.data = transformmatrix.localMatrices(
            **{name: self.__dict__.get(name) for name in fields})
        return holder

    def held(self) -> Any:
        """The node drawn"""
        raise NotImplementedError

    def renderedChildren(self, types: Any = (nodetypes.Children, nodetypes.Rendering)) -> list:
        """What the collidable holds, where it is drawn; nothing for a disabled one"""
        found = self.held()
        return [found] if found is not None and isinstance(found, types) else []

    def localMatrix(self, mode: Any = None) -> Any:  # noqa: ARG002 the bounds protocol passes a mode
        """The collidable's own transform, row-vector"""
        return transformmatrix.transformMatrix(translation=self.translation,
                                               rotation=self.rotation)

    def boundingVolume(self, mode: Any = None) -> Any:
        """What it holds bounds it, where it is placed; unbounded where it holds nothing"""
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        dependencies: list = [(self, 'translation'), (self, 'rotation')]
        held = self.held()
        try:
            if held is None or not hasattr(held, 'boundingVolume'):
                raise boundingvolume.UnboundedObject(self)
            inner = held.boundingVolume(mode)
            dependencies.append((inner, None))
            volume = boundingvolume.BoundingBox.union([inner], self.localMatrix(mode))
        except boundingvolume.UnboundedObject:
            volume = boundingvolume.UnboundedVolume()
        return boundingvolume.cacheVolume(self, volume, dependencies)


class CollidableShape(_Collidable, x3d.CollidableShape):
    """X3D's CollidableShape: its `shape` drawn and collided where it is"""

    def held(self) -> Any:
        """The shape"""
        return self.shape


class CollidableOffset(_Collidable, x3d.CollidableOffset):
    """X3D's CollidableOffset: the collidable it holds, moved within a body"""

    def held(self) -> Any:
        """The collidable it holds"""
        return self.collidable


class _Stepped(EngineTimed):
    """A node stepped once a frame through each context it is bound to

    The render pass binds a node to its context when the node comes into the
    scene the pass draws, and unbinds it when the node leaves that scene or
    the context is given another.
    """

    def bind(self, context: Any) -> bool:
        """Step through `context`'s render queue from its next frame"""
        self.__dict__.setdefault('_contexts', weakref.WeakSet()).add(context)
        queued = self.__dict__.setdefault('_queued', weakref.WeakSet())
        if context not in queued:
            queued.add(context)
            context.renderQueue.call(self.tick, context)
        return True

    def unbindContext(self, context: Any) -> None:
        """Stop stepping through `context`"""
        self.__dict__.setdefault('_contexts', weakref.WeakSet()).discard(context)

    def tick(self, context: Any) -> Any:
        """One frame's step; DEFER while bound, so the next frame steps again"""
        if context not in self.__dict__['_contexts']:
            self.__dict__['_queued'].discard(context)
            return None
        if self.step():
            context.triggerRedraw(1)
        return DEFER

    def step(self) -> bool:
        """Advance to the engine's time; whether a frame should follow"""
        raise NotImplementedError


def _made(node: Any, key: str, make: Any) -> Any:
    """What `make` makes for `node`, kept under `key`; None, logged once, where the engine is unavailable"""
    found = node.__dict__.get(key)
    if found is None and not node.__dict__.get('_unavailable'):
        try:
            found = node.__dict__[key] = make()
        except EngineUnavailable as error:
            node.__dict__['_unavailable'] = True
            log.warning('%s', error)
    return found


class RigidBodyCollection(_Stepped, x3d.RigidBodyCollection):
    """X3D's RigidBodyCollection, simulated on the physics definition's engine

    Steps its bodies once a frame to the engine's time; a scene's capture,
    on a fixed-step clock, steps them the same way every run.
    """

    @property
    def system(self) -> Optional[x3drigid.RigidSystem]:
        """The collection's simulation; None where its engine is unavailable"""
        from OpenGLContext.physics.x3djolt import make_rigid_system  # noqa: PLC0415 pyjoltphysics loads on use

        found: Optional[x3drigid.RigidSystem] = _made(self, '_system', lambda: make_rigid_system(self))
        return found

    def on_set_contacts(self, value: Any) -> None:
        """Contacts to resolve over the next frame"""
        system = self.system
        if system is not None:
            system.contacts = list(value or ())

    def advance(self, seconds: float) -> bool:
        """Step the collection by `seconds`; whether any body is still moving"""
        system = self.system
        return False if system is None else system.advance(seconds)

    def awake(self) -> bool:
        """Whether any body is moving"""
        system = self.system
        return False if system is None else system.awake()

    def step(self) -> bool:
        """Advance to the engine's time"""
        now = self.now()
        last = self.__dict__.get('_steppedAt')
        self.__dict__['_steppedAt'] = now
        return self.advance(0.0 if last is None else now - last)


class CollisionSensor(_Stepped, x3d.CollisionSensor):
    """X3D's CollisionSensor: the touches among its collider's collidables, each frame

    `contacts` is a `Contact` per touching point, `intersections` the
    collidables touching, and `isActive` whether there are any. The contacts
    carry the collider's parameters, and a normal from `geometry1` toward
    `geometry2`. An empty `contacts` is sent once when the touching stops.
    """

    def sense(self) -> None:
        """Find the touches as the collidables stand, and send them"""
        from OpenGLContext.physics import x3drigid  # noqa: PLC0415 kept with the engine's modules
        from OpenGLContext.physics.x3djolt import make_sensing  # noqa: PLC0415 pyjoltphysics loads on use

        sensing = _made(self, '_sensing', make_sensing)
        if sensing is None:
            return
        if not self.enabled or not self.collider:
            touches: list[Any] = []
        else:
            touches = sensing.detect(self.collider)
        pool: list[Any] = self.__dict__.setdefault('_contactPool', [])
        while len(pool) < len(touches):
            pool.append(x3d.Contact())
        contacts = []
        for touch, contact in zip(touches, pool, strict=False):
            for name, value in x3drigid.contact_fields(touch, self.collider).items():
                setattr(contact, name, value)
            contacts.append(contact)
        active = bool(contacts)
        if contacts or self.__dict__.get('_wasTouching'):
            self.intersections = x3drigid.touched(touches)
            self.contacts = contacts
        self.__dict__['_wasTouching'] = active
        if self.__dict__.get('isActive') is not active:
            self.isActive = active

    def step(self) -> bool:
        """Sense once this frame"""
        self.sense()
        return False
