"""The tri-axis handle: three arms at a point, and a drag held to one of them.

Picking answers *what* the pointer is on; a gizmo answers *where the designer
is taking it*. Three arms stand at the point being moved, one per axis, and
grabbing one constrains the whole drag to that axis -- so a control point goes
up, or east, and not somewhere diagonal that the ray happened to sweep through.

The arms are ordinary scenegraph nodes, so the pick finds them the way it finds
anything else and no second hit test is needed::

    gizmo = TranslationGizmo(size=1.5)
    group.children = list(group.children) + [gizmo.node]
    ...
    def OnPress(self, event):
        if gizmo.press(event) is not None:
            return                          # a drag has begun
        ...                                 # otherwise, choose what to attach to

    def OnDrag(self, event):
        moved = gizmo.drag(event)
        if moved is not None:
            net.move(index, moved)          # write it wherever it belongs

A drag runs against the *line* of the grabbed arm rather than against the
depth buffer, because the depth under the cursor during a drag is the thing
being dragged. :func:`axis_parameter` is that arithmetic: the closest approach
of the eye ray to the arm, as a distance along the arm.

**A gizmo works in the coordinates of the group it is put in.** Editors put it
beside what it is moving -- a control net inside a transformed group, say -- and
a point written in that group's units has to come back in them. The gizmo takes
the matrix from the node path the pick handed it (:meth:`~TranslationGizmo.outer_matrix`),
pushes its anchor and its axis out to root coordinates for the arithmetic, and
answers in the units it was asked in.

The arms are a fixed size in world units, so a gizmo far from the camera is
drawn small. ``size`` is that length, in whatever the surrounding group's units
are.
"""
from __future__ import annotations

import math
from typing import Any, List, Optional, Sequence

import numpy as np

from OpenGLContext.edit.surface import ray_from
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.material import Material
from OpenGLContext.scenegraph.nodepath import NodePath
from OpenGLContext.scenegraph.quadrics import Cone, Cylinder
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.scenegraph.transform import Transform

__all__ = ['AXES', 'AXIS_COLOURS', 'TranslationGizmo', 'axis_parameter']

#: The three axes an arm can be, in the order the arms are held in.
AXES = ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0))

#: One colour per axis, in the red-green-blue-for-x-y-z convention every
#: modeller uses. A designer who has used any of them already knows which arm
#: is which.
AXIS_COLOURS = ((0.90, 0.22, 0.22), (0.30, 0.85, 0.30), (0.35, 0.50, 1.00))

#: How much of an arm's own colour it glows with when it is only standing
#: there, and when it is being held. A handle is a control rather than a
#: surface, so it is lit enough to read against whatever is behind it.
IDLE_GLOW, HELD_GLOW = 0.35, 0.9

#: The arrow's proportions, as fractions of ``size``: how thick the shaft is,
#: and how long and how wide the head is.
SHAFT_RADIUS, HEAD_LENGTH, HEAD_RADIUS = 0.035, 0.28, 0.10

#: Below this, the ray and the arm are the same line and every point of the arm
#: is equally near the pointer.
PARALLEL = 1e-9

#: How the arms are turned to point down their axes. A cylinder stands along
#: ``+y``, so the ``y`` arm needs no turning at all.
_ORIENTATIONS = ((0.0, 0.0, 1.0, -math.pi / 2.0), (0.0, 1.0, 0.0, 0.0),
                 (1.0, 0.0, 0.0, math.pi / 2.0))


def axis_parameter(origin: Any, direction: Any, anchor: Any, axis: Any
                   ) -> Optional[float]:
    """How far along ``axis`` from ``anchor`` the ray ``origin``/``direction``
    comes closest to it.

    The answer is in units of the ``axis`` vector's own length, not of distance:
    hand it the axis as some outer transform draws it and the number comes back
    in the units the point being dragged is written in.

    ``None`` where there is no one nearest place -- a ray running along the
    axis, or an axis of no length. Both mean the pointer is not saying where
    to go, and a handle that lurched on the arithmetic would be worse than one
    that held still.
    """
    axis = np.asarray(axis, dtype='d')
    direction = np.asarray(direction, dtype='d')
    offset = np.asarray(anchor, dtype='d') - np.asarray(origin, dtype='d')
    along_axis = float(np.dot(axis, axis))
    between = float(np.dot(axis, direction))
    along_ray = float(np.dot(direction, direction))
    determinant = along_axis * along_ray - between * between
    if determinant <= PARALLEL:
        return None
    return ((between * float(np.dot(direction, offset))
             - along_ray * float(np.dot(axis, offset))) / determinant)


class TranslationGizmo:
    """Three arms at a point, and the drag that moves the point along one.

    ``node`` goes in the scenegraph wherever the thing being moved lives;
    ``attach`` puts the arms at a point and ``detach`` takes them away again.
    Between a :meth:`press` on an arm and the :meth:`release` that ends it,
    :meth:`drag` answers where the point has got to.

    ``position`` is where the gizmo stands, in the coordinates of the group
    ``node`` was put in. Nothing here writes it anywhere: a gizmo moves
    itself and reports, and the application decides what that means -- a
    control point, a light, a waypoint.
    """

    def __init__(self, size: float = 1.0,
                 colours: Sequence[Sequence[float]] = AXIS_COLOURS) -> None:
        #: How long an arm is, in the surrounding group's units.
        self.size = float(size)
        self.materials: List[Material] = []
        self.arms: List[Transform] = [
            self._arm(index, colours[index]) for index in range(3)]
        #: The ``Transform`` to put in the scenegraph. Its children are the
        #: arms while the gizmo is attached and nothing at all while it is
        #: not, so a detached gizmo neither draws nor picks.
        self.node: Any = Transform(children=[])
        self._position = np.zeros(3, dtype='d')
        self._attached = False
        self._axis = -1
        self._grabbed = 0.0
        self._from = np.zeros(3, dtype='d')
        self._anchor = np.zeros(3, dtype='d')
        self._direction = np.zeros(3, dtype='d')

    # -- the arms ----------------------------------------------------------
    def _arm(self, index: int, colour: Sequence[float]) -> Transform:
        """One arrow, built along ``+y`` and turned to point down its axis."""
        material = Material(
            diffuseColor=tuple(colour),
            emissiveColor=tuple(channel * IDLE_GLOW for channel in colour),
        )
        self.materials.append(material)
        appearance = Appearance(material=material)
        shaft = self.size * (1.0 - HEAD_LENGTH)
        return Transform(
            rotation=_ORIENTATIONS[index],
            children=[
                Transform(
                    translation=(0.0, shaft / 2.0, 0.0),
                    children=[Shape(
                        appearance=appearance,
                        geometry=Cylinder(
                            height=shaft,
                            radius=self.size * SHAFT_RADIUS,
                            top=False, bottom=False,
                        ),
                    )],
                ),
                Transform(
                    translation=(0.0, shaft + self.size * HEAD_LENGTH / 2.0, 0.0),
                    children=[Shape(
                        appearance=appearance,
                        geometry=Cone(
                            height=self.size * HEAD_LENGTH,
                            bottomRadius=self.size * HEAD_RADIUS,
                        ),
                    )],
                ),
            ],
        )

    def _glow(self, axis: int, amount: float) -> None:
        material = self.materials[axis]
        material.emissiveColor = tuple(
            channel * amount for channel in material.diffuseColor)

    # -- standing somewhere ------------------------------------------------
    @property
    def attached(self) -> bool:
        """Whether the arms are on screen."""
        return self._attached

    @property
    def position(self) -> np.ndarray:
        """Where the gizmo stands, in the surrounding group's coordinates."""
        return self._position.copy()

    def attach(self, position: Any) -> None:
        """Stand the arms at a point and show them."""
        self._position = np.asarray(position, dtype='d').copy()
        self.node.translation = tuple(float(value) for value in self._position)
        if not self._attached:
            self.node.children = list(self.arms)
            self._attached = True

    def detach(self) -> None:
        """Take the arms away, abandoning any drag."""
        if self._axis >= 0:
            self.release()
        self.node.children = []
        self._attached = False

    # -- what the pick found -----------------------------------------------
    def axis_for(self, paths: Any) -> Optional[int]:
        """Which arm a set of picked node paths went through, if any."""
        for path in paths or ():
            for item in path:
                for axis, arm in enumerate(self.arms):
                    if item is arm:
                        return axis
        return None

    def outer_matrix(self, path: Any) -> np.ndarray:
        """The local-to-root matrix of the group this gizmo was put in.

        Taken from the path the pick handed over, by walking it as far as this
        gizmo's own node: what is above that is the group whose coordinates
        ``position`` is written in, and what is below is the gizmo's own doing.
        """
        nodes = list(path)
        for index, item in enumerate(nodes):
            if item is self.node:
                nodes = nodes[:index]
                break
        return np.asarray(NodePath(nodes).transformMatrix(), dtype='d')

    # -- the drag ----------------------------------------------------------
    @property
    def dragging(self) -> Optional[int]:
        """The axis being held, or ``None`` when nothing is."""
        return self._axis if self._axis >= 0 else None

    def begin(self, axis: int, origin: Any, direction: Any,
              matrix: Optional[Any] = None) -> bool:
        """Grab an arm with the ray ``origin``/``direction``, in root
        coordinates.

        ``matrix`` is the local-to-root transform of the group the gizmo stands
        in; without one the gizmo is taken to stand in root coordinates.

        The point does not move: what is recorded is how far along the arm the
        pointer took hold of it, so the rest of the drag is measured from
        there and the handle does not jump to the cursor.
        """
        if not self._attached:
            return False
        transform = (np.identity(4) if matrix is None
                     else np.asarray(matrix, dtype='d'))
        self._anchor = np.dot(np.append(self._position, 1.0), transform)[:3]
        self._direction = np.dot(np.append(np.asarray(AXES[axis], 'd'), 0.0),
                                 transform)[:3]
        grabbed = axis_parameter(origin, direction, self._anchor,
                                 self._direction)
        if grabbed is None:
            return False
        self._axis = int(axis)
        self._grabbed = grabbed
        self._from = self._position.copy()
        self._glow(self._axis, HELD_GLOW)
        return True

    def drag_to(self, origin: Any, direction: Any) -> Optional[np.ndarray]:
        """Where the point has got to, for a ray in root coordinates.

        ``None`` when no arm is held, or when the pointer is edge-on to the one
        that is and has nothing to say about where along it to go.
        """
        if self._axis < 0:
            return None
        reached = axis_parameter(origin, direction, self._anchor,
                                 self._direction)
        if reached is None:
            return None
        moved = self._from + np.asarray(AXES[self._axis], dtype='d') * (
            reached - self._grabbed)
        self.attach(moved)
        return self.position

    def release(self) -> None:
        """Let go, leaving the point where the drag left it."""
        if self._axis >= 0:
            self._glow(self._axis, IDLE_GLOW)
        self._axis = -1

    def cancel(self) -> np.ndarray:
        """Abandon the drag, putting the point back where it was grabbed."""
        if self._axis >= 0:
            self.attach(self._from)
        self.release()
        return self.position

    # -- from the pick's own events ----------------------------------------
    def press(self, event: Any) -> Optional[int]:
        """Take a button press if it landed on an arm; the axis, or ``None``.

        The matrix comes from the path the pick resolved, so a gizmo standing
        inside a transformed group is dragged in that group's units without the
        application working any of it out.
        """
        for path in event.getObjectPaths() or ():
            axis = self.axis_for([path])
            if axis is None:
                continue
            origin, direction = ray_from(event)
            if self.begin(axis, origin, direction, self.outer_matrix(path)):
                return axis
        return None

    def drag(self, event: Any) -> Optional[np.ndarray]:
        """Where the point has got to, for a mouse-move event."""
        if self._axis < 0:
            return None
        origin, direction = ray_from(event)
        return self.drag_to(origin, direction)
