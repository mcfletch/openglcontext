"""Level-of-Detail nodes: which version of a thing to draw from where the viewer is.

Two nodes, one mechanism. :class:`LOD` is VRML97's: the same object modelled
several times over, finest first, and ``range`` giving the distances at which
each gives way to the next, so ``range[i]`` is where level ``i`` hands over to
level ``i + 1``. :class:`ScreenCoverageLOD` is what ``MSFT_lod`` asks for: the
levels are chosen by how much of the window the object covers rather than by a
distance, which is the same decision made in the units a viewer actually sees
it in -- a model twice the size, or seen through half the field of view, holds
its detail twice as far out.

``center`` is the point in the node's own coordinates distance is measured to,
so a figure's distance is measured to the figure and not to the world origin.

Which level that comes to is settled once a frame by the render pass, which is
the only thing that knows where the viewers are
(:meth:`OpenGLContext.passes._flat.FlatPass.chooseLevels`). Changing level
announces itself on the same signal a ``Switch`` uses, because the pass keeps a
flattened scenegraph and a level nobody told it about would not be drawn.
"""
import math
from typing import Any, NamedTuple, Optional, Sequence

import numpy as np
from pydispatch import dispatcher
from vrml import field
from vrml.vrml97 import basenodes, nodetypes

from vrml import cache

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.switch import SWITCH_CHANGE_SIGNAL

__all__ = ['LOD', 'ScreenCoverageLOD', 'CULLED', 'Viewer', 'distance_to_viewer',
           'finest', 'level_generation', 'screen_fraction', 'uniform_scale',
           'viewer_for', 'viewer_tangent']

#: ``whichLevel`` for a node that is drawing nothing at all, which is what
#: ``MSFT_lod`` asks for below the coarsest level's screen coverage.
CULLED = -1

#: The vertical field of view a viewer that cannot be asked is taken to have,
#: which is the one :class:`~OpenGLContext.move.viewplatform.ViewPlatform`
#: starts every camera with.
DEFAULT_FIELD_OF_VIEW = 60.0

_TINY = 1e-9

#: The largest ``hysteresis`` a node is held to: a coverage band reaching to
#: zero would never let a node coarsen.
MAXIMUM_HYSTERESIS = 0.9


def viewer_tangent(field_of_view: Optional[float] = None) -> float:
    """Half the window's height one unit in front of a viewer, from its lens.

    ``field_of_view`` is the vertical angle in degrees, as ``gluPerspective``
    and a view platform's ``frustum`` both state it. Everything a screen
    coverage is worked out from is this number and a distance.
    """
    if field_of_view is None:
        field_of_view = DEFAULT_FIELD_OF_VIEW
    return math.tan(math.radians(float(field_of_view)) / 2.0)


class Viewer(NamedTuple):
    """One camera a frame's levels of detail are chosen for.

    ``modelview`` places the world in front of the camera. ``tangent`` is half
    the window's height one unit in front of a perspective camera -- the
    tangent of half its vertical field of view -- and, for an ``orthographic``
    one, half the height of the world it shows, which is the same at every
    distance.
    """

    modelview: Any
    tangent: float
    orthographic: bool = False

    def tangents(self, distances: Any) -> Any:
        """The tangent each node at ``distances`` is seen through.

        What a node's coverage is divided by, over the distance. An
        orthographic view shows a node the same size wherever it stands, so
        its tangent shrinks with distance to leave the product at the view's
        half-height.
        """
        if not self.orthographic:
            return np.full(len(distances), float(self.tangent))
        return float(self.tangent) / np.maximum(np.asarray(distances, 'd'), _TINY)


def viewer_for(camera: Any, modelview: Any, projection: Any) -> Viewer:
    """The :class:`Viewer` a camera is, from its matrices.

    A projection whose last column is ``(0, 0, 0, 1)`` is orthographic, and
    ``1 / projection[1][1]`` is half its height. A perspective camera states
    its field of view where it has a ``frustum`` to state it in, which is the
    figure :func:`viewer_tangent` has always been given; otherwise the same
    element of its projection is the tangent.
    """
    matrix = np.asarray(projection, 'd')
    scale = float(matrix[1, 1]) or _TINY
    if abs(float(matrix[3, 3]) - 1.0) < 1e-6 and abs(float(matrix[2, 3])) < 1e-6:
        return Viewer(modelview, 1.0 / scale, orthographic=True)
    frustum = getattr(camera, 'frustum', None)
    if frustum is not None:
        return Viewer(modelview, viewer_tangent(frustum[0]))
    return Viewer(modelview, 1.0 / scale)


def finest(levels: Sequence[int]) -> int:
    """The most detailed of ``levels``: the lowest index, and :data:`CULLED` last."""
    drawn = [level for level in levels if level != CULLED]
    return min(drawn) if drawn else CULLED


def viewer_distances(centres: Any, modelviews: Any) -> np.ndarray:
    """How far the viewer is from each of ``N`` centres, given ``N`` modelviews.

    ``centres`` is ``(N,3)`` in each node's own coordinates and ``modelviews``
    is ``(N,4,4)``; a modelview takes its node's coordinates to eye coordinates,
    where the viewer is the origin, so the length of the placed centre is the
    distance and no separate camera position has to be threaded through.

    For the whole set at once because a frame chooses a level for every
    level-of-detail node in the scene, and at four-by-four a numpy call costs
    more than the arithmetic inside it.
    """
    centres = np.asarray(centres, dtype='d')
    placed = np.concatenate(
        [centres[:, :3], np.ones((len(centres), 1))], axis=1)
    eye = (placed[:, None, :] @ np.asarray(modelviews, dtype='d'))[:, 0, :3]
    distances: np.ndarray = np.linalg.norm(eye, axis=1)
    return distances


def uniform_scales(modelviews: Any) -> np.ndarray:
    """What each of ``N`` modelviews does to a length, as an ``(N,)`` array.

    The longest a unit axis comes out. A node's radius is in its own
    coordinates and the distance to it is in the viewer's, so one of them has
    to be carried into the other before they can be compared. The view part of
    the matrix is a rotation and a translation and changes no length, which
    leaves the node's own transform -- and the largest of its three axes is
    what settles how big it looks, because that is the one that reaches
    furthest across the window.
    """
    matrices = np.asarray(modelviews, dtype='d')[:, :3, :3]
    largest: np.ndarray = np.sqrt((matrices * matrices).sum(axis=2)).max(axis=1)
    return largest


def screen_fractions(radii: Any, distances: Any, tangent: float) -> np.ndarray:
    """Share of the window's height each of ``N`` spheres covers.

    ``tangent`` is the tangent of half the vertical field of view, so the
    window is ``2 * distance * tangent`` high where an object is and the object
    is ``2 * radius`` of it. A viewer close enough to be inside a sphere covers
    the window, which is where the ratio stops meaning anything.
    """
    radii = np.asarray(radii, dtype='d')
    distances = np.asarray(distances, dtype='d')
    spanned = radii / np.maximum(distances * float(tangent), _TINY)
    fractions: np.ndarray = np.where(distances <= radii, 1.0,
                                     np.minimum(1.0, spanned))
    return fractions


# The three above answer for a whole scene at once and the three below answer
# for one object. Both are wanted, and each is written in the terms that suit
# it: an array expression over several hundred objects costs a handful of numpy
# calls, while the same expression over *one* costs those same calls to do
# arithmetic a float multiply would have done -- and the one-object form is
# asked once per object per frame by :meth:`LOD.selectAt`, which is the hottest
# place either of them appears. What keeps the pairs from drifting is that each
# is tested against the other, in
# ``tests/unit/test_screen_coverage_lod.py::TestTheWholeSceneAtOnce``.


def distance_to_viewer(node: Any, modelview: Any) -> float:
    """How far the viewer is from ``node``'s centre, given its modelview."""
    centre = np.concatenate([np.asarray(node.distanceCentre(), dtype='d')[:3],
                             [1.0]])
    eye = centre @ np.asarray(modelview, dtype='d')
    return float(np.linalg.norm(eye[:3]))


def uniform_scale(modelview: Any) -> float:
    """What ``modelview`` does to a length: the longest a unit axis comes out."""
    matrix = np.asarray(modelview, dtype='d')[:3, :3]
    return float(np.sqrt((matrix * matrix).sum(axis=1)).max())


def screen_fraction(radius: float, distance: float, tangent: float) -> float:
    """Share of the window's height a sphere of ``radius`` covers from ``distance``."""
    radius = float(radius)
    distance = float(distance)
    if distance <= radius:
        return 1.0
    return min(1.0, radius / max(distance * float(tangent), _TINY))


class LOD(basenodes.LOD):
    """Level-of-Detail node based on VRML 97 LOD.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#LOD
    """

    #: Which level is being drawn. Not a VRML field: the file says what the
    #: levels are and where they change over, and this is what that comes to
    #: for the viewer as it stands.
    whichLevel: int = 0

    #: How far past a threshold, as a fraction of it, a viewer has to be before
    #: a coarser level is drawn; the finer level comes back at the threshold
    #: itself. A viewer standing on a threshold, or bobbing across it, then
    #: keeps one level rather than changing every frame. 0 switches at the
    #: thresholds exactly; values are held to [0, :data:`MAXIMUM_HYSTERESIS`].
    #: Not a VRML field, so a node's own setting is not written to a file.
    _hysteresis: float = 0.1

    @property
    def hysteresis(self) -> float:
        """How far past a threshold a viewer goes before a coarser level is drawn.

        A fraction of the threshold; see :meth:`band` for the range it is held
        to. Setting it moves :func:`level_generation`, since a viewer inside
        the old band can be outside the new one.
        """
        return self._hysteresis

    @hysteresis.setter
    def hysteresis(self, value: float) -> None:
        self._hysteresis = value
        _levels_changed()

    #: Whether a level has been chosen yet. The first choice has no level to
    #: hold on to, and is the plain answer.
    _shown: bool = False

    def selectFor(self, modelview: Any, tangent: float) -> bool:
        """Choose a level for the viewer this modelview and field of view are.

        For one node on its own. ``tangent`` is the tangent of half the
        vertical field of view: a VRML97 ``LOD`` names its levels in distances
        and has no use for it, and a node that switches on screen coverage
        does. A render pass with a scene's worth to choose for works the two
        numbers out for the whole set and calls :meth:`selectAt`.
        """
        return self.selectAt(distance_to_viewer(self, modelview),
                             uniform_scale(modelview), tangent)

    def selectAt(self, distance: float, scale: float, tangent: float) -> bool:
        """Choose a level from numbers already worked out; True if it changed.

        What the render pass calls, once a frame, for every level-of-detail
        node in the scene. ``distance`` is how far the viewer is from this
        node's centre and ``scale`` is what the node's own transform does to a
        length; the pass derives both for the whole scene at once, which leaves
        each node the part that is genuinely its own -- which of its thresholds
        the answer falls in, and whether that is a change worth announcing.

        A VRML97 ``LOD`` names its levels in distances, so the scale and the
        lens are nothing to it.
        """
        return self.show(self.levelAt(distance, scale, tangent))

    def levelAt(self, distance: float, scale: float, tangent: float) -> int:
        """The level :meth:`selectAt` would draw for these numbers, without drawing it.

        What a frame drawn through several cameras asks each of them, before
        showing the finest of the answers.
        """
        return self.levelNear(distance)

    def select(self, distance: float) -> bool:
        """Choose the level for a viewer ``distance`` away; True if it changed.

        A node with no ranges keeps its finest level, which is what VRML97
        leaves to the browser: guessing a distance for content that named none
        would draw somebody's model at a detail they never asked for.
        """
        return self.show(self.levelNear(distance))

    def levelNear(self, distance: float) -> int:
        """The level for a viewer ``distance`` away, held by :attr:`hysteresis`."""
        band = self.band()
        return self.held(self.levelFor(distance),
                         lambda: self.levelFor(distance / (1.0 + band)))

    def band(self) -> float:
        """:attr:`hysteresis` as a usable fraction."""
        value = float(self.hysteresis)
        if not math.isfinite(value):
            return 0.0
        return min(max(value, 0.0), MAXIMUM_HYSTERESIS)

    def held(self, plain: int, eased: Any) -> int:
        """The level to draw, given the plain answer and a way to ask with the band.

        ``eased()`` is the level for the measurement moved the band's width
        toward the finer side. A finer or equal ``plain`` is drawn as it is; a
        coarser one only as far as ``eased()`` also reaches, so a viewer inside
        the band keeps the level being drawn.
        """
        if not self._shown:
            return plain
        current = self.whichLevel
        if self._rank(plain) <= self._rank(current):
            return plain
        coarsest: int = max(current, eased(), key=self._rank)
        return coarsest

    def _rank(self, level: int) -> int:
        """How coarse ``level`` is: its index, with :data:`CULLED` past the last."""
        return len(self.level) if level == CULLED else level

    def distanceCentre(self) -> Any:
        """The point, in this node's coordinates, a viewer's distance is measured to."""
        return self.center

    def show(self, level: int) -> bool:
        """Draw level ``level`` from now on; True where that is a change.

        The change is announced rather than assumed, because the pass renders
        from a flattened scenegraph it has to be told to re-walk.
        """
        self._shown = True
        if level == self.whichLevel:
            return False
        self.whichLevel = level
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
        if not levels or self.whichLevel < 0:
            return []
        node = levels[min(self.whichLevel, len(levels) - 1)]
        return [node] if isinstance(node, types) else []

    def boundedChildren(self) -> list:
        """What bounds this node: what it draws, or the finest level if nothing.

        Drawing nothing is not being everywhere. A node past its last screen
        coverage is culled, and a parent group unions the volumes of what it
        holds -- so a culled node still reports where it would be, and the
        group it is in stays as small as its contents.
        """
        drawn = self.renderedChildren()
        return drawn if drawn else list(self.level[:1])

    def boundingVolume(self, mode: Any = None) -> Any:
        """Bounds of the level being drawn.

        The levels are the same object at different detail, so any of them
        bounds the node; the one on screen is the one whose bounds are wanted,
        and it is what a coarser level's slightly different silhouette should
        be culled by. A change of level clears the volume, and with it the
        volumes of the groups holding this node.
        """
        current = boundingvolume.getCachedVolume(self)
        if current is not None:
            return current
        volumes = []
        dependencies: list = [(self, 'level'), (self, 'range')]
        for child in self.boundedChildren():
            if hasattr(child, 'boundingVolume'):
                child_volume = child.boundingVolume(mode)
                volumes.append(child_volume)
                dependencies.append((child_volume, None))
        try:
            volume: Any = boundingvolume.BoundingBox.union(volumes, None)
        except boundingvolume.UnboundedObject:
            volume = boundingvolume.UnboundedVolume()
        volume = boundingvolume.cacheVolume(self, volume, dependencies)
        holder = cache.CACHE.getHolder(self, key='boundingVolume')
        if holder is not None:
            holder.depend_signal(SWITCH_CHANGE_SIGNAL, self)
        return volume


class ScreenCoverageLOD(LOD):
    """Levels of detail chosen by how much of the window the object covers.

    The node ``MSFT_lod`` describes. ``level`` holds the same object modelled
    several times over, finest first; ``screenCoverage`` gives each level the
    coverage at or above which it is the one to draw, in decreasing order, so
    level ``i`` is drawn from ``screenCoverage[i]`` up to ``screenCoverage[i-1]``
    and below the last of them nothing is drawn. A file that wants its coarsest
    level to stay on screen however small it gets says so by ending the list
    with ``0``.

    Coverage is the share of the window's *height* the object's bounding sphere
    spans, so it answers the question a level was measured against: how many
    pixels of this is the viewer actually looking at. ``radius`` is that sphere
    in the node's own coordinates; left at 0 it is measured from the finest
    level, and a transform above the node is accounted for either way. With
    ``radius`` at 0 and ``center`` at the origin, the distance is measured to
    the measured sphere's centre as well.

    Reference:
        https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Vendor/MSFT_lod
    """

    #: The coverage at which each level takes over, finest first, decreasing.
    screenCoverage = field.newField('screenCoverage', 'MFFloat', 1, list)
    #: The object's bounding-sphere radius in its own coordinates; 0 to measure
    #: it from the finest level.
    radius = field.newField('radius', 'SFFloat', 1, 0.0)

    def __init__(self, *args: Any, **named: Any) -> None:
        super(ScreenCoverageLOD, self).__init__(*args, **named)
        self._measured: float = 0.0
        self._measuredCentre: Any = None
        dispatcher.connect(
            self._onLevelsChange,
            signal=('set', self.__class__.level),
            sender=self,
        )

    def _onLevelsChange(self, value: Any = None) -> None:
        """New levels are a new size to judge them by."""
        self._measured = 0.0
        self._measuredCentre = None

    def levelAt(self, distance: float, scale: float, tangent: float) -> int:
        """The level for the coverage this viewer gives the object."""
        radius = self.coverageRadius() * scale
        if radius <= 0:
            # Nothing to measure: the level being drawn stands, which is the
            # finest unless something chose otherwise -- what a reader that had
            # never heard of the extension would draw.
            return self.whichLevel
        coverage = screen_fraction(radius, distance, tangent)
        band = self.band()
        return self.held(self.levelForCoverage(coverage),
                         lambda: self.levelForCoverage(coverage / (1.0 - band)))

    def distanceCentre(self) -> Any:
        """``center``, or the finest level's measured centre where both are unset."""
        if float(self.radius) > 0 or any(float(v) for v in self.center):
            return self.center
        self._measure()
        return self._measuredCentre if self._measuredCentre is not None \
            else self.center

    def levelForCoverage(self, coverage: float) -> int:
        """The level to draw where the object covers ``coverage`` of the window.

        :data:`CULLED` where it has fallen below every threshold the file gave,
        which is the point the coarsest level was said to stop being worth
        drawing at.
        """
        thresholds: Sequence[float] = (
            self.screenCoverage if self.screenCoverage is not None else ())
        levels = len(self.level)
        if not levels or not len(thresholds):
            return 0
        chosen = sum(1 for threshold in thresholds if coverage < float(threshold))
        return CULLED if chosen >= levels else chosen

    def coverageRadius(self) -> float:
        """The object's radius in its own coordinates.

        The file's own figure where it gave one -- it knows the geometry it
        baked -- and otherwise the finest level measured once and kept, since
        a level's size does not change between frames.
        """
        stated = float(self.radius)
        if stated > 0:
            return stated
        self._measure()
        return self._measured

    def _measure(self) -> None:
        """Measure the finest level's sphere, once for each set of levels."""
        if self._measured:
            return
        measured = boundingvolume.boundingSphere(self.level[:1])
        self._measured = float(measured[1]) if measured else 0.0
        self._measuredCentre = measured[0] if measured else None


_level_changes = 0


def level_generation() -> int:
    """A count that moves whenever a field deciding a node's level is set.

    Those are a node's ``level``, ``range``, ``center`` and
    :attr:`~LOD.hysteresis`, and a :class:`ScreenCoverageLOD`'s
    ``screenCoverage`` and ``radius``. A pass that
    remembers the levels it chose keeps them while this, the nodes' places
    and the viewers stay as they were.
    """
    return _level_changes


def _levels_changed(*_args: Any, **_named: Any) -> None:
    global _level_changes
    _level_changes += 1


def _watch_level_fields() -> None:
    for owner, name in ((LOD, 'level'), (LOD, 'range'), (LOD, 'center'),
                        (ScreenCoverageLOD, 'screenCoverage'),
                        (ScreenCoverageLOD, 'radius')):
        dispatcher.connect(_levels_changed, signal=('set', getattr(owner, name)),
                           weak=False)


_watch_level_fields()
