"""Bounding volume implementation

Based on code from:
    http://www.markmorley.com/opengl/frustumculling.html

Notes regarding general implementation:

    BoundingVolume objects are generally created by Grouping
    and/or Shape nodes (or rather, the geometry nodes of Shape
    nodes).  Grouping nodes are able to create union
    BoundingVolume objects from their children's bounding
    volumes.

    The RenderPass object (for visiting rendering passes)
    defines a children method which will use the bounding
    volumes to filter out those children which are not visible.

    The first attempt to do that filtering will recursively
    generate and cache the bounding volumes.

    Setting your contextDefinition's debugBBox flag to True
    will cause rendering of the bounding boxes when using
    the Flat renderer.
"""

from typing import Any, Optional, Sequence, Tuple

from OpenGLContext.arrays import *
from OpenGL.GL import *
from vrml import node, field, protofunctions, cache
from OpenGLContext import frustum
import logging

log = logging.getLogger(__name__)

try:
    from vrml.arrays import frustcullaccel
except ImportError:
    frustcullaccel = None


class UnboundedObject(ValueError):
    """Error raised when an object does not support bounding volumes"""


class BoundingVolume(node.Node):
    """Base class for all bounding volumes

    BoundingVolume is both a base class and a functional
    bounding volume which is always considered visible.
    Geometry which wishes to never be visible can return
    a BoundingVolume as their boundingVolume.
    """

    def visible(self, frustum: Any, matrix: Any = None, occlusion: int = 0,
                mode: Any = None) -> int:
        """Test whether volume is within given frustum"""
        return 0

    def getPoints(self) -> Any:
        """Get the points which comprise the volume"""
        return ()


class UnboundedVolume(BoundingVolume):
    """A bounding volume which is always visible

    Opposite of a BoundingVolume, geometry can return
    an UnboundedVolume if they always wish to be visible.
    """

    def visible(self, frustum: Any, matrix: Any = None, occlusion: int = 0,
                mode: Any = None) -> int:
        """Test whether volume is within given frustum

        We don't actually do anything here, just return true
        """
        return 1

    def getPoints(self) -> Any:
        """Signal to parents that we require unbounded operation"""
        raise UnboundedObject("""Attempt to get union of an unbounded volume""")


class BoundingBox(BoundingVolume):
    """Generic representation of a bounding box

    A bounding box is a bounding volume which is implemented
    as a set of points which can be tested against a frustum.
    Although at the moment we don't use the distinction between
    BoundingBox and AABoundingBox, the BoundingBox may
    eventually be used to provide specialized support for
    bitmap Text nodes (which should only need four points
    to determine their visibility, rather than eight).
    """

    points = field.newField("points", "MFVec4f", 0, [])
    if frustcullaccel:
        # We have the C extension module, use it
        def visible(self, frust: Any, matrix: Any = None, occlusion: int = 0,
                    mode: Any = None) -> int:
            """Determine whether this bounding-box is visible in frustum

            frustum -- Frustum object holding the clipping planes
                for the view
            matrix -- a matrix which transforms the local
                coordinates to the (world-space) coordinate
                system in which the frustum is defined.

            This version of the method uses the frustcullaccel
            C extension module to do the actual culling once
            the volume's points are multiplied by the matrix.
            """
            if matrix is None:
                matrix = frustum.viewingMatrix()
            points = self.getPoints()
            points = dot(points, matrix)
            culled, planeIndex = frustcullaccel.planeCull(frust.planes, points)
            return not culled
    else:

        def visible(self, frust: Any, matrix: Any = None, occlusion: int = 0,
                    mode: Any = None) -> int:
            """Determine whether this bounding-box is visible in frustum

            frustum -- Frustum object holding the clipping planes
                for the view
            matrix -- a matrix which transforms the local
                coordinates to the (world-space) coordinate
                system in which the frustum is defined.

            This version of the method uses a pure-python loop
            to do the actual culling once the points are
            multiplied by the matrix. (i.e. it does not use the
            frustcullaccel C extension module)
            """
            if matrix is None:
                matrix = frustum.viewingMatrix()
            points = self.getPoints()
            points = dot(points, matrix)
            points[:, -1] = 1.0
            if frust:
                # Vectorized plane test: distances[i, j] is point i's signed
                # distance to plane j (points @ planes.T). The object is culled
                # iff some plane has ALL points strictly behind it (< 0) -- the
                # same decision as the per-point loop, but one matmul instead of
                # 6*8 tiny numpy sum() calls, which dominated large-scene culling.
                distances = dot(points, array(frust.planes, 'f').T)
                if (distances < 0).all(axis=0).any():
                    return 0
            else:
                log.warning(
                    """BoundingBox visible called with Null frustum""",
                )
            return 1

    def getPoints(self) -> Any:
        """Return set of points to test against the frustum"""
        return self.points

    @staticmethod
    def union(boxes: Sequence[Any], matrix: Any = None) -> BoundingVolume:
        """Create BoundingBox union for the given bounding boxes

        This uses the getPoints method of the given
        bounding boxes to retrieve the extrema points
        which must be present in the union.  It then
        calculates an Axis-Aligned bounding box shape
        taking into account the matrix given.

        It would seem somewhat more efficient here to
        use the points array directly, but that would
        have the effect of geometrically increasing the
        number of checks for each succeeding parent,
        while creating the axis-aligned bounding box
        trades more work here to keep the constant-time
        operation for the "visible" check.

        Group nodes pass a None as the matrix, while
        Transform nodes should pass their individual
        transformation matrix (not the cumulative matrix).

        boxes -- list of AABoundingBox instances
        matrix -- if specified, the matrix to be applied
            to the box coordinates before calculating the
            resulting axis-aligned bounding box.
        """
        sets = []
        for box in boxes:
            if box:
                boxPoints = box.getPoints()
                if len(boxPoints) > 0:
                    sets.append(boxPoints)
        if not sets:
            return BoundingVolume()
        points = concatenate(tuple(sets))
        if matrix is not None:
            points = dot(points, matrix)
        return AABoundingBox.fromPoints(points)

    def debugRender(self) -> None:
        """Render this bounding box for debugging mode

        XXX Should really use points for rendering GL_POINTS
            geometry for the base class when it gets used.
        """


class AABoundingBox(BoundingBox):
    """Representation of an axis-aligned bounding box

    The axis-aligned bounding box defines the entire
    bounding box with two pieces of data, a center position
    and a size vector.  Other than this, it is just a
    point-based bounding box implementation.
    """

    center = field.newField("center", "SFVec3f", 0, (0, 0, 0))
    size = field.newField("size", "SFVec3f", 0, (0, 0, 0))

    def getPoints(self) -> Any:
        """Return set of points to test against the frustum

        If self.points field is not set, will calculate the
        points from the center and size fields.
        """
        if not len(self.points):
            cx, cy, cz = self.center
            sx, sy, sz = self.size
            sx /= 2.0
            sy /= 2.0
            sz /= 2.0
            self.points = array(
                [
                    (x, y, z, 1)
                    for x in (cx - sx, cx + sx)
                    for y in (cy - sy, cy + sy)
                    for z in (cz - sz, cz + sz)
                ],
                "f",
            )
        return self.points

    def debugRender(self) -> None:
        """Render this bounding box for debugging mode

        Draws the bounding box as a set of lines in the
        current OpenGL matrix (in OpenGLContext's visiting
        pattern, this is the matrix of the parent of the
        node which is determining whether to cull the node
        to which this bounding box is attached)
        """
        # This code is not OpenGL 3.1 compatible
        points = self.getPoints()
        glDisable(GL_LIGHTING)
        try:
            glColor3f(1, 0, 0)
            for set in [
                [points[0], points[1], points[3], points[2]],
                [points[4], points[5], points[7], points[6]],
            ]:
                glBegin(GL_LINE_LOOP)
                try:
                    for point in set:
                        glVertex3dv(point[:3])
                finally:
                    glEnd()
            glBegin(GL_LINES)
            try:
                for i in range(4):
                    glVertex3dv(points[i][:3])
                    glVertex3dv(points[i + 4][:3])
            finally:
                glEnd()
        finally:
            glEnable(GL_LIGHTING)

    @classmethod
    def fromPoints(cls, points: Any) -> "AABoundingBox":
        """Calculate from an array of points"""
        xes, yes, zes = points[:, 0], points[:, 1], points[:, 2]
        maxX, maxY, maxZ = xes[argmax(xes)], yes[argmax(yes)], zes[argmax(zes)]
        minX, minY, minZ = xes[argmin(xes)], yes[argmin(yes)], zes[argmin(zes)]
        size = maxX - minX, maxY - minY, maxZ - minZ
        return cls(
            center=(
                (size[0]) / 2 + minX,
                (size[1]) / 2 + minY,
                (size[2]) / 2 + minZ,
            ),
            size=size,
        )


class _Measure(object):
    """The least a node needs in order to be asked how big it is.

    Bounding volumes are computed against a *render mode* because some extents
    genuinely depend on one -- a ``Text`` node's is the size of the glyphs the
    context resolved a font for.  Measuring renders nothing, so all that is
    really wanted from the mode is somewhere to memoise the answer, and a node
    that needs more than that declines to measure rather than guessing.
    """

    def __init__(self) -> None:
        self.cache = cache.CACHE


def boundingSphere(
    nodes: Sequence[Any],
) -> Optional[Tuple[Tuple[float, ...], float]]:
    """``(centre, radius)`` around a run of nodes, or None if none can be measured.

    Nodes with no extent -- a ``Background``, a light, a sensor -- are skipped
    rather than making the whole answer unbounded, which is what asking a
    grouping node for its volume would do.

    What a caller wants when it needs to know **where a scene is and how big**:
    framing a camera on it, or choosing the point an examine drag pivots about.
    """
    mode = _Measure()
    volumes = []
    for child in nodes:
        measure = getattr(child, 'boundingVolume', None)
        if measure is None:
            continue
        try:
            volumes.append(measure(mode))
        except Exception:           # unbounded, or wants a real render mode
            continue
    try:
        volume = BoundingBox.union(volumes, None)
    except Exception:
        volume = None
    center = getattr(volume, 'center', None)
    size = getattr(volume, 'size', None)
    if center is None or size is None:
        return None
    # An explicit accumulator: ``from OpenGLContext.arrays import *`` above
    # shadows the builtin ``sum`` with numpy's, which refuses a generator.
    squared = 0.0
    for value in size:
        half = float(value) / 2.0
        squared += half * half
    return tuple(float(v) for v in center), squared ** 0.5


def volumeFromCoordinate(node: Any) -> BoundingVolume:
    """Calculate a bounding volume for a coordinate node

    This should work for all of:
        IndexedFaceSet
        IndexedLineSet
        PointSet
        IndexedPolygons

    This just takes advantage of the common features of the
    coordinate-based geometry types, ignoring the fact
    that individual pieces of geometry may not actually use
    all of the points within a volume.

    Note:
        this method is cache aware, it will return a cached
        bounding box if possible, or calculate and cache the
        bounding box before returning it.

    XXX There is a pathological case which may be encountered
        due to an optimization seen in certain VRML97
        generators. Namely, these generators will create
        an entire file with a single coordinate node with each
        individual piece of geometry indexing into that
        universal coordinate node. This would, in many designs
        provide an optimization because the coordinate node
        would never be swapped out, allowing the geometry to
        remain within the GL as the current vertex/color
        matrices.  In this case, OpenGLContext will have no
        bounding volume optimization at all, as it will take
        rebounding volume of each piece of geometry to be the
        bounding volume of the entire world.
    """
    current = getCachedVolume(node)
    if current:
        return current
    if (not node) or (not len(node.point)):
        volume = BoundingVolume()
    else:
        volume = AABoundingBox.fromPoints(node.point)
    if node:
        # note that even if not node.point, we
        # are dependent on that NULL node.point value
        dependencies = [(node, "point")]
    else:
        dependencies = []
    return cacheVolume(node, volume, dependencies)


### Abstraction/indirection for caching bounding volumes
##  Because the code to cache bounding volumes is generally
##  identical, we provide this set of two utility methods
##  to retrieve and cache the volumes with proper dependency
##  setup.
def cacheVolume(
    node: Any, volume: BoundingVolume, nodeFieldPairs: Sequence[Any] = ()
) -> BoundingVolume:
    """Cache bounding volume for the given node

    node -- the node associated with the volume
    volume -- the BoundingVolume object to be cached
    nodeFieldPairs -- set of (node,fieldName) tuples giving
        the dependencies for the volume.  Should normally
        include the node itself. If fieldName is None
        a dependency is created on the node itself.
    """
    holder = cache.CACHE.holder(node, key="boundingVolume", data=volume)
    for n, attr in nodeFieldPairs:
        if n:
            if attr is not None:
                holder.depend(n, protofunctions.getField(n, attr))
            else:
                holder.depend(n, None)
    return volume


def getCachedVolume(node: Any) -> Optional[BoundingVolume]:
    """Get currently-cached bounding volume for the node or None"""
    volume: Optional[BoundingVolume] = cache.CACHE.getData(
        node, key="boundingVolume")
    return volume
