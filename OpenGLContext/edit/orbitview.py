"""A world looked at from an angle: an editor's three-quarter view.

A plan view is the right thing to *draw* on -- a metre is the same number of
pixels wherever it is, so the line drawn is the line the world gets -- and the
wrong thing to *judge* on. A designer who has just raised a hill wants to look
at it, and shading and contours answer "how high is that" rather than "does
that look right".

:class:`OrbitView` is the camera for it: a point on the ground it looks at, and
a heading, a pitch and a distance to look from. The default pitch is the
three-quarter view somebody means by "let me look at it" -- high enough to read
the plan, low enough to read the relief. :class:`OrbitViewPlatform` presents it
to the render pass as an ordinary camera, reading the view rather than copying
it, so orbiting is what moves the camera and there is no second copy of where
the editor is looking.

::

    view = OrbitView(centre=(0.0, 0.0), distance=800.0)
    context.platform = OrbitViewPlatform(view, context.getViewPort())
    ...
    view.orbit(dx * 0.4, dy * 0.4)      # a drag
    view.dolly(1.0 / 1.25)              # a wheel notch
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np

from OpenGLContext.move.viewplatform import ViewPlatform
from OpenGLContext.passes.shadowmath import ortho_matrix, perspective_matrix

__all__ = ['OrbitView', 'OrbitViewPlatform', 'DEFAULT_PITCH', 'DEFAULT_FOV']

#: Degrees above the horizontal the camera sits at by default. Thirty-five is
#: the angle a modelling package opens on and an isometric drawing is made at:
#: enough of the plan to know where you are, enough of the elevation to see
#: what the ground does.
DEFAULT_PITCH = 35.0

#: How wide the lens is, in degrees down the screen. Narrower than a game's,
#: because a wide lens bows the land at the edges and the land is the subject.
DEFAULT_FOV = 40.0

#: How much of the distance the near and far planes stand off it. A camera that
#: is always looking at something a known distance away can fit its planes to
#: that, which is what keeps the depth buffer's precision where the ground is.
NEAR_SHARE = 0.02
FAR_SHARE = 12.0


class OrbitView:
    """Where a three-quarter view is looking, and from how far off.

    ``centre`` is the world ``(x, z)`` it looks at and ``ground`` the height
    there, so the camera keeps its subject in the middle of the screen as the
    land under it changes. ``heading`` is degrees clockwise from north --
    zero puts the camera to the south looking north, which is the way up a map
    is read -- ``pitch`` is degrees above the horizontal, and ``distance`` is
    how far off it stands, in metres. ``nearest`` and ``furthest`` are how
    near and how far it may be dollied, :attr:`NEAREST` and :attr:`FURTHEST`
    unless given; a view of one object rather than of the land wants them
    fitted to that object. ``lowest`` and ``highest`` are the pitches it may
    be orbited between, :attr:`LOWEST` and :attr:`HIGHEST` unless given; a
    view of an object that may be looked up at from below gives a negative
    ``lowest``.
    """

    #: How near and how far the camera may be dollied, in metres.
    NEAREST = 20.0
    FURTHEST = 40000.0

    #: How near overhead and how near the horizontal the pitch may go. Not the
    #: poles themselves: a camera looking straight down has no unique up-vector
    #: and one exactly on the horizon sees the ground edge-on.
    HIGHEST = 89.0
    LOWEST = 1.0

    def __init__(self, centre: tuple[float, float] = (0.0, 0.0),
                 ground: float = 0.0, heading: float = 0.0,
                 pitch: float = DEFAULT_PITCH, distance: float = 800.0,
                 fov: float = DEFAULT_FOV, nearest: float | None = None,
                 furthest: float | None = None,
                 orthographic: bool = False, lowest: float | None = None,
                 highest: float | None = None) -> None:
        self.nearest = float(self.NEAREST if nearest is None else nearest)
        self.furthest = float(self.FURTHEST if furthest is None else furthest)
        self.lowest = float(self.LOWEST if lowest is None else lowest)
        self.highest = float(self.HIGHEST if highest is None else highest)
        self.centre = (float(centre[0]), float(centre[1]))
        #: The height of the ground it is looking at, in metres.
        self.ground = float(ground)
        self.heading = float(heading)
        self.pitch = float(pitch)
        self.distance = float(distance)
        #: How wide the lens is, in degrees down the screen.
        self.fov = float(fov)
        #: Whether the view is drawn flat: the same camera, with distance no
        #: longer making a thing smaller, so two beams of the same size measure
        #: the same on screen wherever they stand. What an editor's *ortho*
        #: view is, as against its perspective one. The height of what is shown
        #: is what the lens takes in at the target, so switching does not jump.
        self.orthographic = bool(orthographic)

    # -- where it is -------------------------------------------------------
    def target(self) -> np.ndarray:
        """The world point the camera is looking at."""
        return np.array([self.centre[0], self.ground, self.centre[1]],
                        dtype='d')

    def position(self) -> np.ndarray:
        """Where the camera stands, in world metres."""
        turn = math.radians(self.heading)
        up = math.radians(self.pitch)
        flat = math.cos(up) * self.distance
        # Heading zero puts the camera south of its subject looking north,
        # which is +z in a world whose north is -z.
        where: np.ndarray = self.target() + np.array(
            [-flat * math.sin(turn), math.sin(up) * self.distance,
             flat * math.cos(turn)], dtype='d')
        return where

    # -- moving about ------------------------------------------------------
    def orbit(self, turn: float, rise: float) -> None:
        """Swing the camera round its subject, in degrees.

        The subject stays where it is: an orbit that moved what it was looking
        at would be a pan, and a designer inspecting a hill would lose it.
        """
        self.heading = (self.heading + float(turn)) % 360.0
        self.pitch = min(max(self.pitch + float(rise), self.lowest),
                         self.highest)

    def dolly(self, factor: float) -> None:
        """Move in or out. Below 1 comes closer; above 1 draws back."""
        self.distance = float(min(max(self.distance * float(factor),
                                      self.nearest), self.furthest))

    def fit_limits(self, radius: float) -> None:
        """Fit how near and how far it may be dollied to a subject of ``radius``.

        Near enough to fill the view with a hundredth of the subject, far
        enough to see a thousand of it.
        """
        radius = max(float(radius), 1e-6)
        self.nearest = radius * 0.01
        self.furthest = radius * 1000.0

    def look_at(self, centre: tuple[float, float],
                ground: float | None = None) -> None:
        """Point the camera at somewhere else on the ground."""
        self.centre = (float(centre[0]), float(centre[1]))
        if ground is not None:
            self.ground = float(ground)

    def stand_at(self, eye: Sequence[float] | np.ndarray,
                 forward: Sequence[float] | np.ndarray,
                 distance: float) -> None:
        """Stand at ``eye`` looking along ``forward``, orbiting a point ``distance`` ahead.

        How a view takes the pose of a camera the scene carries. The point
        ahead is what an orbit then turns about. The camera stays at ``eye``
        whatever the limits make of the rest: the distance is held to
        ``nearest`` and ``furthest``, and the pitch to ``lowest`` and
        ``highest``, by moving the point it orbits. There is no roll, since an
        orbit keeps the world's up the screen's.
        """
        start = np.asarray(eye, dtype='d')[:3]
        along = np.asarray(forward, dtype='d')[:3]
        along = along / max(float(np.linalg.norm(along)), 1e-12)
        rise = math.degrees(math.asin(min(max(-float(along[1]), -1.0), 1.0)))
        self.pitch = min(max(rise, self.lowest), self.highest)
        self.heading = math.degrees(math.atan2(float(along[0]),
                                               -float(along[2]))) % 360.0
        self.distance = float(min(max(float(distance), self.nearest),
                                  self.furthest))
        # Where the target has to be for position() to answer the eye.
        target = start - (self.position() - self.target())
        self.look_at((float(target[0]), float(target[2])), float(target[1]))

    def frame(self, minimum: tuple[float, float], maximum: tuple[float, float],
              viewport: tuple[int, int]) -> None:
        """Look at a region from far enough off to see all of it."""
        self.centre = ((float(minimum[0]) + float(maximum[0])) / 2.0,
                       (float(minimum[1]) + float(maximum[1])) / 2.0)
        across = abs(float(maximum[0]) - float(minimum[0]))
        down = abs(float(maximum[1]) - float(minimum[1]))
        width, height = (int(viewport[0]) or 1), (int(viewport[1]) or 1)
        # Whichever direction needs the greater distance decides, or the other
        # runs off the edge. The lens is quoted down the screen, so the
        # horizontal half-angle is the vertical one scaled by the aspect.
        half = math.radians(self.fov) / 2.0
        vertical = (down / 2.0) / max(math.tan(half), 1e-6)
        horizontal = (across / 2.0) / max(math.tan(half) * width / height, 1e-6)
        self.dolly(max(vertical, horizontal) / max(self.distance, 1e-9))

    def frame_box(self, minimum: Sequence[float] | np.ndarray,
                  maximum: Sequence[float] | np.ndarray,
                  viewport: tuple[int, int]) -> None:
        """Look at the middle of a box from far enough off to see all of it.

        The box is fitted by the sphere around it, so it stays on screen
        whatever the heading and pitch are orbited to afterwards.
        """
        low = np.asarray(minimum[:3], dtype='d')
        high = np.asarray(maximum[:3], dtype='d')
        middle = (low + high) / 2.0
        self.look_at((float(middle[0]), float(middle[2])), float(middle[1]))
        radius = max(float(np.linalg.norm(high - low)) / 2.0, 1e-9)
        width, height = (int(viewport[0]) or 1), (int(viewport[1]) or 1)
        half = math.radians(self.fov) / 2.0
        across = math.atan(math.tan(half) * width / height)
        self.dolly(radius / math.sin(min(half, across)) / max(self.distance, 1e-9))

    # -- the camera --------------------------------------------------------
    def matrices(self, viewport: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
        """``(model-view, projection)`` for this view, row-vector."""
        return (self._model(), self._projection(viewport))

    def _model(self) -> np.ndarray:
        """The world turned so the camera is at the origin looking down -z."""
        eye = self.position()
        forward = self.target() - eye
        forward = forward / max(float(np.linalg.norm(forward)), 1e-9)
        right = np.cross(forward, np.array([0.0, 1.0, 0.0]))
        right = right / max(float(np.linalg.norm(right)), 1e-9)
        up = np.cross(right, forward)
        model = np.zeros((4, 4), dtype='d')
        # Row-vector convention: the basis goes in the columns, so a world
        # point multiplied on the left lands in camera space.
        model[:3, 0] = right
        model[:3, 1] = up
        model[:3, 2] = -forward
        model[3, 3] = 1.0
        model[3, :3] = -(eye @ model[:3, :3])
        return model

    def _projection(self, viewport: tuple[int, int]) -> np.ndarray:
        aspect = (int(viewport[0]) or 1) / (int(viewport[1]) or 1)
        near = max(self.distance, self.nearest) * NEAR_SHARE
        far = max(self.distance * FAR_SHARE, near * 10.0)
        if self.orthographic:
            # As much as the lens takes in at what it is looking at, so the
            # switch leaves the subject the size it was. The depth runs as far
            # behind the camera as in front: a flat view has no eye point for
            # anything to be behind, and clipping there would take away half
            # of what an editor turned the perspective off to see.
            half = max(self.distance, 1e-6) * math.tan(math.radians(self.fov) / 2.0)
            return np.asarray(
                ortho_matrix(-half * aspect, half * aspect, -half, half,
                             -far, far),
                dtype='d')
        return np.asarray(
            perspective_matrix(math.radians(self.fov), aspect, near, far),
            dtype='d')


class OrbitViewPlatform(ViewPlatform):
    """An :class:`OrbitView` presented to the render pass as a camera.

    Reads the view rather than copying it, so orbiting or dollying is what
    moves the camera; there is no second copy of where the editor is looking to
    fall out of step with the first.
    """

    def __init__(self, view: OrbitView,
                 viewport: tuple[int, int] = (1, 1)) -> None:
        # Before the base class, because setting a position on this platform is
        # how the view is told where to stand, and the base sets one.
        self.view = view
        self.viewport = (int(viewport[0]), int(viewport[1]))
        super(OrbitViewPlatform, self).__init__(
            position=tuple(view.position()))

    def setViewport(self, x: float, y: float) -> None:
        self.viewport = (int(x), int(y))

    @property
    def position(self) -> np.ndarray:
        """Where the camera stands."""
        return np.append(self.view.position(), 1.0)

    @position.setter
    def position(self, value: Any) -> None:
        """Stand the camera somewhere, keeping what it is looking at.

        The heading, the pitch and the distance follow from where it was put,
        which is what lets anything that moves a camera by position -- a
        bookmark, a saved viewpoint -- move this one.
        """
        values = np.asarray(value, dtype='d').ravel()
        offset = values[:3] - self.view.target()
        distance = float(np.linalg.norm(offset))
        if distance <= 1e-9:
            return
        self.view.distance = distance
        self.view.pitch = math.degrees(math.asin(
            min(max(float(offset[1]) / distance, -1.0), 1.0)))
        self.view.heading = math.degrees(math.atan2(-float(offset[0]),
                                                    float(offset[2]))) % 360.0

    def setPosition(self, position: Any) -> None:
        self.position = position

    def viewMatrix(self, trimDepth: Any = None,
                   inverse: bool = False) -> np.ndarray:
        projection = self.view.matrices(self.viewport)[1]
        if inverse:
            return np.linalg.inv(projection).astype('f')
        return projection.astype('f')

    def modelMatrix(self, inverse: bool = False) -> np.ndarray:
        model = self.view.matrices(self.viewport)[0]
        if inverse:
            return np.linalg.inv(model).astype('f')
        return model.astype('f')

    def matrix(self, inverse: bool = False) -> np.ndarray:
        model, projection = self.view.matrices(self.viewport)
        if inverse:
            return np.linalg.inv(model @ projection).astype('f')
        combined: np.ndarray = model @ projection
        return combined.astype('f')
