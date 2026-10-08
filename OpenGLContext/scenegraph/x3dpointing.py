"""The pointing-device sensors told of each context's pointer -- no GL

The sensors' behaviour is pyvrml97's (:mod:`vrml.x3d.pointing`). A sensor
bound to a context starts the context's :class:`PointerSensing`, which
observes its picked ``mousemove`` and ``mousebutton`` events
(:meth:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin.observeEvents`):

- The sensors an event reaches are the enabled ones among the children of
  the lowest group on the picked path that has any, with that group itself
  where it is an `Anchor` (:func:`sensors_for`). An Anchor released over its
  geometry follows its url through the context (:meth:`Anchor.follow`).
- The hit is the picked point (:func:`unprojected`) and the ray the pointer's
  bearing (:func:`pointer_ray`), each in the sensors' coordinates. Picking
  gives a point; the hit has no normal or texture coordinate.
- The primary button (0) pressed over sensors activates them, and moving
  while it is held drags them, on or off their geometry, until it is
  released. The scene's and the application's handlers receive the same
  events.
"""
from __future__ import annotations

import weakref
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np
from vrml.x3d import pointing
from vrml.x3d import nodes as x3d
from vrml.x3d.nodes import X3DPointingDeviceSensorNode

from OpenGLContext.scenegraph.anchor import Anchor

__all__ = ['CylinderSensor', 'GeoTouchSensor', 'PlaneSensor', 'PointerSensing', 'SphereSensor', 'TouchSensor',
           'pointer_ray', 'sensing', 'sensors_for', 'unprojected']

#: The button that presses a sensor.
PRIMARY = 0


def unprojected(view: Any, x: float, y: float, depth: float) -> np.ndarray:
    """The world point at window position (x, y) and depth in [0, 1]

    `view` carries the row-vector ``modelViewMatrix`` and ``projectionMatrix``
    and the ``viewport`` (x, y, width, height) a picked event has.
    """
    vx, vy, width, height = (float(value) for value in view.viewport)
    device = np.array([2.0 * (x - vx) / width - 1.0, 2.0 * (y - vy) / height - 1.0,
                       2.0 * depth - 1.0, 1.0])
    combined = np.asarray(view.modelViewMatrix, np.float64) @ np.asarray(view.projectionMatrix,
                                                                           np.float64)
    found = device @ np.linalg.inv(combined)
    return np.asarray(found[:3] / found[3])


def pointer_ray(view: Any, x: float, y: float) -> tuple[np.ndarray, np.ndarray]:
    """(origin, direction): the pointer's bearing through (x, y), from the near plane"""
    near = unprojected(view, x, y, 0.0)
    return near, unprojected(view, x, y, 1.0) - near


def sensors_for(path: Any) -> tuple[list[Any], Any]:
    """(sensors, path to their group): the enabled sensors of the lowest group on `path` with any

    ``([], None)`` where no group on the path has one.
    """
    for index in range(len(path) - 1, -1, -1):
        found = [child for child in getattr(path[index], 'children', ())
                 if isinstance(child, X3DPointingDeviceSensorNode) and child.enabled]
        if isinstance(path[index], x3d.Anchor) and index < len(path) - 1:
            found.append(path[index])
        if found:
            return found, path[:index + 1]
    return [], None


def _local(prefix: Any) -> np.ndarray:
    """The world-to-local matrix of the group `prefix` ends at"""
    found = prefix.transformMatrix()
    return np.identity(4) if found is None else np.linalg.inv(np.asarray(found, np.float64))


def _point_in(matrix: np.ndarray, point: Any) -> np.ndarray:
    return np.asarray((np.append(np.asarray(point, np.float64)[:3], 1.0) @ matrix)[:3])


def _direction_in(matrix: np.ndarray, direction: Any) -> np.ndarray:
    return np.asarray((np.append(np.asarray(direction, np.float64)[:3], 0.0) @ matrix)[:3])


class PointerSensing:
    """The pointing-device sensors of one context and the pointer's effect on them"""

    def __init__(self, context: Any = None) -> None:
        #: The context whose pointer this is, for an Anchor to follow through.
        self.context = None if context is None else weakref.ref(context)
        #: The sensors the pointer is over.
        self.over: list[Any] = []
        #: (sensor, world-to-local) for each sensor a held press activated.
        self.held: list[tuple[Any, np.ndarray]] = []
        #: The view the press was picked through, for drags whose event has none.
        self.view: Any = None

    def _picked(self, event: Any) -> tuple[list[Any], Any, Optional[np.ndarray]]:
        """(sensors, world-to-local, world hit) for the path under `event`'s pointer"""
        paths = event.getObjectPaths() or ()
        path = paths[0] if paths else None
        if not path or not getattr(event, 'viewCoordinate', None):
            return [], None, None
        found, prefix = sensors_for(path)
        if not found:
            return [], None, None
        x, y, depth = event.viewCoordinate
        return found, _local(prefix), unprojected(event, x, y, float(depth))

    def _view(self, event: Any) -> Any:
        if getattr(event, 'modelViewMatrix', None) is not None and \
                getattr(event, 'projectionMatrix', None) is not None:
            return event
        return self.view

    def observe(self, event: Any) -> None:
        """A picked pointer event of the context"""
        found, matrix, hit = self._picked(event)
        if event.type == 'mousebutton':
            if int(getattr(event, 'button', -1)) != PRIMARY:
                return
            if event.state:
                self.press(event, found, matrix, hit)
            else:
                self.release(event, found)
        elif event.type == 'mousemove':
            self.move(event, found, matrix, hit)

    def _point(self, sensors: Sequence[Any], matrix: Any, hit: Any) -> None:
        local = pointing.Hit(_point_in(matrix, hit))
        for sensor in sensors:
            sensor.pointerOver(local)

    def move(self, event: Any, found: list[Any], matrix: Any, hit: Any) -> None:
        """The pointer has moved: over `found` at `hit`, dragging what is held"""
        for sensor in self.over:
            if sensor not in found:
                sensor.pointerOver(None)
        self.over = list(found)
        if found:
            self._point(found, matrix, hit)
        view = self._view(event)
        if not self.held or view is None:
            return
        x, y = event.getPickPoint()[:2]
        origin, direction = pointer_ray(view, x, y)
        for sensor, local in self.held:
            ray = pointing.Ray(_point_in(local, origin), _direction_in(local, direction))
            on = pointing.Hit(_point_in(local, hit)) if sensor in found else None
            sensor.pointerDrag(on, ray)

    def press(self, event: Any, found: list[Any], matrix: Any, hit: Any) -> None:
        """The primary button has gone down over `found` at `hit`"""
        if not found:
            return
        self.view = self._view(event)
        x, y = event.getPickPoint()[:2]
        origin, direction = pointer_ray(self.view, x, y)
        local = pointing.Hit(_point_in(matrix, hit))
        ray = pointing.Ray(_point_in(matrix, origin), _direction_in(matrix, direction))
        self.held = [(sensor, matrix) for sensor in found]
        for sensor in found:
            sensor.pointerPress(local, ray)

    def release(self, _event: Any, found: list[Any]) -> None:
        """The primary button has come up, over `found`"""
        if not self.held:
            return
        context = None if self.context is None else self.context()
        for sensor, _matrix in self.held:
            if isinstance(sensor, Anchor):
                if sensor in found and context is not None:
                    sensor.follow(context)
            else:
                sensor.pointerRelease(sensor in found)
        self.held = []


#: Each context's PointerSensing.
_SENSING: weakref.WeakKeyDictionary[Any, PointerSensing] = weakref.WeakKeyDictionary()


def sensing(context: Any) -> PointerSensing:
    """`context`'s PointerSensing, observing its pointer from the first call"""
    found = _SENSING.get(context)
    if found is None:
        found = _SENSING[context] = PointerSensing(context)
        context.observeEvents('mousemove', found.observe)
        context.observeEvents('mousebutton', found.observe)
    return found


class Pointed:
    """A pointing-device sensor told of the pointer of each context it is bound to"""

    def bind(self, context: Any) -> bool:
        """Have `context`'s pointer reach the scene's sensors"""
        sensing(context)
        return True


class TouchSensor(Pointed, pointing.TouchSensor):
    """X3D's TouchSensor, told of the pointer"""


class GeoTouchSensor(Pointed, pointing.GeoTouchSensor):
    """X3D's GeoTouchSensor, told of the pointer"""


class PlaneSensor(Pointed, pointing.PlaneSensor):
    """X3D's PlaneSensor, told of the pointer"""


class CylinderSensor(Pointed, pointing.CylinderSensor):
    """X3D's CylinderSensor, told of the pointer"""


class SphereSensor(Pointed, pointing.SphereSensor):
    """X3D's SphereSensor, told of the pointer"""
