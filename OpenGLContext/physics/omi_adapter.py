"""The service's values as :mod:`omi_physics` takes them, and omi_physics's answers as the service's own.

Everything the public modules of :mod:`OpenGLContext.physics` hand the
engine passes through here: materials, collision filters, characters'
capabilities and state, a proxy's shape, gravity, a body's motion and the
description of the engine. The modules that step and query the omi_physics
world (:mod:`~OpenGLContext.physics.runtime`,
:mod:`~OpenGLContext.physics.worker`, :mod:`~OpenGLContext.physics.replica`,
:mod:`~OpenGLContext.physics.queries`) work in omi's types throughout and
convert with these functions where a value crosses to or from the service.
"""
from __future__ import annotations

import dataclasses
import logging
import threading
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any

import numpy as np
import omi_physics
from omi_physics import model
from omi_physics.character import CharacterCapabilities as OmiCapabilities
from omi_physics.character import CharacterState as OmiState
from omi_physics.contactevents import PairPreview, Verdict
from omi_physics.gravity import GravityVolume

from OpenGLContext.physics.filters import Approach
from OpenGLContext.physics.records import Motion
from OpenGLContext.physics.types import (
    CharacterCapabilities, CharacterState, CollisionFilter, EngineInfo, GravityZone, Material,
)

if TYPE_CHECKING:
    from OpenGLContext.physics.body import Body
    from OpenGLContext.physics.proxy import Proxy

log = logging.getLogger(__name__)

__all__ = ['NAME', 'ContactFilter', 'character_state', 'engine_info', 'gravity', 'gravity_volume',
           'material_from_omi', 'motion', 'omi_capabilities', 'omi_filter', 'omi_material',
           'omi_shape', 'proxy_from_shape']

#: The engine's name, as :attr:`EngineInfo.name` gives it.
NAME = 'omi_physics'

#: Held while a proxy's engine shape is made, so every thread is given the same object.
_SHAPING = threading.Lock()


def engine_info(tick_hz: float, compute: str = '') -> EngineInfo:
    """omi_physics as an :class:`EngineInfo` stepping at ``tick_hz`` on the ``compute`` backend, in double precision."""
    return EngineInfo(NAME, str(omi_physics.__version__), float(tick_hz), 'double', compute)


# -- materials and filters ---------------------------------------------------

def omi_material(material: Any) -> model.Material:
    """``material``, a :class:`Material` or an object with its fields, as omi's."""
    given = Material.coerce(material)
    return model.Material(**{field.name: getattr(given, field.name)
                             for field in dataclasses.fields(Material)})


def material_from_omi(material: model.Material) -> Material:
    """omi's ``material`` as a :class:`Material`."""
    return Material.coerce(material)


def omi_filter(given: Any) -> model.CollisionFilter:
    """``given``, a :class:`CollisionFilter` or an object with its fields, as omi's."""
    found = CollisionFilter.coerce(given)
    return model.CollisionFilter(found.collisionSystems, found.collideWithSystems,
                                 found.notCollideWithSystems)


# -- characters ----------------------------------------------------------------

def omi_capabilities(capabilities: Any) -> OmiCapabilities:
    """``capabilities``, :class:`CharacterCapabilities` or an object with its fields, as omi's."""
    found = CharacterCapabilities.coerce(capabilities)
    return OmiCapabilities(**{field.name: getattr(found, field.name)
                              for field in dataclasses.fields(CharacterCapabilities)})


def character_state(state: OmiState) -> CharacterState:
    """omi's character ``state`` as a :class:`CharacterState`."""
    return CharacterState[state.name]


# -- shapes ----------------------------------------------------------------------

def omi_shape(proxy: Proxy) -> model.Shape:
    """The omi shape of ``proxy``, made on the first call and the same object after."""
    found = proxy._engine_shape
    if found is None:
        with _SHAPING:
            found = proxy._engine_shape
            if found is None:
                found = proxy._engine_shape = _make_shape(proxy.kind, proxy.params)
    return found


def _make_shape(kind: str, params: Any) -> model.Shape:
    if kind == 'box':
        return model.Shape.box(tuple(float(v) for v in params['size']))
    if kind == 'sphere':
        return model.Shape.sphere(float(params['radius']))
    if kind == 'capsule':
        return model.Shape.capsule(float(params['height']), float(params['radius']))
    if kind == 'cylinder':
        made = model.Shape.cylinder(float(params['height']), float(params['radius']))
        made.radiusTop = float(params['radius_top'])
        return made
    if kind == 'convex':
        return model.Shape.convex(params['points'])
    if kind == 'trimesh':
        return model.Shape.trimesh(params['points'], params['indices'])
    if kind == 'compound':
        return model.Shape.compound([(omi_shape(part), tuple(position), tuple(orientation))
                                     for part, position, orientation in params['parts']])
    if kind == 'heightfield':
        return model.Shape.heightfield(**params)
    raise ValueError('no engine shape is made for a proxy of kind %r' % (kind,))


def proxy_from_shape(shape: model.Shape) -> Proxy:
    """A :class:`Proxy` of omi's ``shape``, whose engine shape is ``shape`` itself.

    A heightfield made by omi_physics carries no parameters: its ground is in
    the engine's surface object, which the proxy keeps as its engine shape.
    """
    from OpenGLContext.physics.proxy import Proxy  # noqa: PLC0415 proxy converts through this module

    kind = str(shape.type)
    params: dict[str, Any]
    if kind == 'box':
        params = {'size': tuple(float(v) for v in shape.size)}
    elif kind == 'sphere':
        params = {'radius': float(shape.radius)}
    elif kind == 'capsule':
        params = {'height': float(shape.height), 'radius': float(shape.radiusBottom)}
    elif kind == 'cylinder':
        params = {'height': float(shape.height), 'radius': float(shape.radiusBottom),
                  'radius_top': float(shape.radiusTop)}
    elif kind == 'convex':
        params = {'points': np.asarray(shape.points, dtype='d')}
    elif kind == 'trimesh':
        params = {'points': np.asarray(shape.points, dtype='d'),
                  'indices': np.asarray(shape.indices, dtype='i')}
    elif kind == 'compound':
        params = {'parts': tuple((proxy_from_shape(part.shape), tuple(part.position),
                                  tuple(part.orientation)) for part in shape.parts or ())}
    else:
        params = {}
    made = Proxy(kind, params)
    made._engine_shape = shape
    return made


# -- gravity and motion ----------------------------------------------------------

def gravity(vector: Iterable[float]) -> model.Gravity:
    """An acceleration in metres a second squared as omi's magnitude and direction."""
    x, y, z = (float(v) for v in vector)
    strength = (x * x + y * y + z * z) ** 0.5
    if strength == 0.0:
        return model.Gravity(gravity=0.0, direction=(0.0, -1.0, 0.0))
    return model.Gravity(gravity=strength, direction=(x / strength, y / strength, z / strength))


def gravity_volume(zone: GravityZone) -> GravityVolume:
    """``zone`` as omi's gravity volume over the same region."""
    if zone.toward is not None:
        field = model.Gravity(type=model.POINT, gravity=zone.gravity, center=zone.toward,
                              priority=zone.priority, replace=zone.replace, stop=zone.stop)
    else:
        field = model.Gravity(gravity=zone.gravity, direction=zone.direction,
                              priority=zone.priority, replace=zone.replace, stop=zone.stop)
    return GravityVolume(field, zone.region)


#: omi's motion type for each kind of body.
_MOTION_TYPES = {'dynamic': model.DYNAMIC, 'kinematic': model.KINEMATIC}


def motion(kind: str, mass: float = 1.0, linear_damping: float = 0.0,
           angular_damping: float = 0.0, gravity_factor: float = 1.0) -> model.Motion:
    """omi's motion for a body of ``kind`` (``'static'``, ``'dynamic'``, ``'kinematic'``, ``'trigger'``).

    A static body or a trigger is omi's static motion, whatever the rest says.
    """
    if kind not in _MOTION_TYPES:
        return model.Motion(type=model.STATIC)
    return model.Motion(type=_MOTION_TYPES.get(kind, model.STATIC), mass=float(mass),
                        linearDamping=float(linear_damping),
                        angularDamping=float(angular_damping),
                        gravityFactor=float(gravity_factor))


# -- the contact filter ------------------------------------------------------------

class ContactFilter:
    """The worker's contact filter: the application's function, given handles in place of slots.

    ``body_of(slot)`` gives the body in a world slot. The function's answer:
    True or None solves the pair, False lets the two through until they part.
    A function that raises is logged once and the pair is solved.
    """

    def __init__(self, function: Callable[[Approach], Any],
                 body_of: Callable[[Any], Body | None]) -> None:
        self.function = function
        self._body_of = body_of
        self._failed = False

    def __call__(self, pair: PairPreview) -> Verdict:
        approach = Approach(self._body_of(pair.a), self._body_of(pair.b), float(pair.approach),
                            float(pair.impulse), pair.point, pair.normal)
        try:
            answer = self.function(approach)
        except Exception:
            if not self._failed:
                self._failed = True
                log.exception('the contact filter %r failed; the pair is solved', self.function)
            return Verdict.SOLVE
        return Verdict.IGNORE_PAIR if answer is False else Verdict.SOLVE
