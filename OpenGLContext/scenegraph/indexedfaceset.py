"""Indexed Face-set VRML97 node implemented using ArrayGeometry

XXX This node needs some serious optimization.  Possible approaches:

    display-list-generation, probably the most appropriate
        approach of them all, as it will almost certainly
        provide a serious speed boost.  This can be a
        fairly simplistic mechanism, as it won't need the
        tesselator, and it can simply process the values
        as a stream of instructions.
        OpenGL 3.x deprecates display-lists...
    GL_TRIANGLE_STRIP, GL_QUAD_STRIP -- can dramatically
        reduce memory bandwidth, requires some serious
        analysis of the topology to get a decent result
        while keeping VRML semantics
    IndexedPolygons -- a single index array or equal
        index arrays can be rendered without expansion
    Double vs. floating point -- be able to downsample
        arrays to 'f' type if the data can be precisely
        stored within a 'f' type array
    GL_ATI_vertex_array_object -- cache arrays on the
        "server" side of the GL engine then use them
        from there
    GL_EXT_vertex_array_set -- cache the arrays in the
        client-side GL engine with all arrays together
        and the associated enables etc. should make the
        call to render a single restore of state and then
        glDrawArrays() -- note that I (mcf) don't have
        this extension available, so can't implement this.

    GL_EXT_compiled_vertex_array -- should be used if
        available, alternate version of same functionality
        GL_EXT_static_vertex_array. This is only useful
        if we are making multiple calls to render, which
        we are currently not doing.

    cache index-sets:
        used to do a take of the data-arrays to get triangles-arrays
        depends on the index arrays and the tessellation-types

        if no tessellation required:
            possible to update the entire coordinate array
            and just re-take before rendering
        all-equal-index sets:
            basically if the indices arrays are all identical
            we could use an index-based array-drawing call,
            which avoids the take-calls entirely, see
            IndexedPolygons for an implementation.
        if tessellation required:
            store polys-to-tessellate as meta-indices
                depends on the index-sets
            re-tessellate whenever coordinates change
            store end-of-data-array indices
                depends on everything, used to decide
                where the new values start writing
                if the data array has changed, then is
                the length of the data-array
"""

import numpy as np
from OpenGLContext.scenegraph import coordinatebounded
from vrml.vrml97 import basenodes
from vrml import protofunctions

# The compile pipeline lives in ``ifscompiler``; re-exported here so importers
# that used ``from ...indexedfaceset import IndexedPolygonsCompiler`` etc. keep
# working, and so ``COMPILER_CLASSES`` is populated when this module loads.
from OpenGLContext.scenegraph.ifscompiler import (
    DummyRender,
    DUMMY_RENDER,
    COMPILER_CLASSES,
    IFSCompiler,
    ArrayGeometryCompiler,
    IndexedPolygonsCompiler,
    IndexedValueSource,
    getXNull,
    build_normalPerVertex,
)
import logging

log = logging.getLogger(__name__)


class IndexedFaceSet(coordinatebounded.CoordinateBounded, basenodes.IndexedFaceSet):
    """Indexed Face-set VRML97 node

    The IndexedFaceSet is the most common VRML97
    geometry-node type.  Most 3D modellers will export
    most geometry as IndexedFaceSets, as they are
    the most general of the polygonal geometry types.

    The OpenGLContext IndexedFaceSet node tries to
    follow the VRML97 IndexedFaceSet node's semantics
    as closely as possible whenever those semantics are
    defined.  If you detect non-conformant operation,
    please report it as a bug in OpenGLContext.

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#IndexedFaceSet

    There are a number of major sub-types of IFS:
        have coord + normal
            need to tesselate
                need to get simple triangle-points array
                need to get simple normals array
                # may need texCoordArray as well
                # may need color as well
        have coord but no normal
            need to tesselate
                need to get simple triangle-points array
                need to calculate normals for (face/vertex)
                # may need texCoordArray as well
                # may need color as well
        have only a single index-set, but 2 or 3 arrays
            could just use indexed drawing if all elements
            are triangles, in this case we don't have _any_
            real overhead for a delta on the points/normals/colors,
            what would VRML do?

        have everything
            once tesselated, we have a simple "take" to get values
    """

    USE_DISPLAY_LISTS = 0
    DEBUG_DRAW_NORMALS = 0

    def render(
        self,
        visible=1,
        lit=1,
        textured=1,
        transparent=0,
        mode=None,  # the renderpass object for which we compile
    ):
        """Render the IndexedFaceSet's geometry for a Shape

        visible -- can skip normals and textures if not
        lit - can skip normals if not
        textured -- can skip textureCoordinates if not
        transparent -- need to sort triangle geometry...
        """
        renderer = mode.cache.getData(self)
        if renderer is None:
            renderer = self.compile(visible, lit, textured, transparent, mode=mode)
        if not renderer:
            return 0
        return renderer.render(
            visible,
            lit,
            textured,
            transparent,
            mode=mode,
        )

    def compile(
        self,
        visible=1,
        lit=1,
        textured=1,
        transparent=0,
        mode=None,
    ):
        """Compile the rendering structures for the IndexedFaceSet"""
        set = []
        for cc in COMPILER_CLASSES:
            set.append((cc.weight(self), cc))
        set.sort()
        return set[-1][1](self)(
            visible=visible,
            lit=lit,
            textured=textured,
            transparent=transparent,
            mode=mode,
        )

    # -- instancing -------------------------------------------------------
    def _hasGeometry(self):
        return bool(len(self.coordIndex) and self.coord and len(self.coord.point))

    def _instanceArrays(self):
        """Expanded (positions, normals, texcoords) triangle soup for instancing.

        Reuses ``ArrayGeometryCompiler`` -- the same tessellation the
        non-instanced shader path draws -- so an instanced IndexedFaceSet looks
        identical to its per-shape rendering. Returns ``None`` when empty. Note
        per-vertex color is dropped by the shared instanced mesh (documented
        limitation of ``build_mesh_gpu``); a color-varying field still batches by
        shape, it just renders with the material colour.
        """
        if not self._hasGeometry():
            return None
        expanded = ArrayGeometryCompiler(self).expandedArrays()
        if expanded is None:
            return None
        vertexArray, colorArray, normalArray, textureCoordinateArray = expanded
        return vertexArray, normalArray, textureCoordinateArray

    def instanceContentKey(self):
        """Hashable signature so distinct-but-identical IFS nodes share one draw.

        Covers the scatter case: a bolt, tile or leaf authored as an IFS and used
        hundreds of times collapses into a single instanced call. Hashes exactly
        the arrays and flags that determine the tessellated output. ``None`` when
        empty (falls back to node identity in the grouper).
        """
        import hashlib
        if not self._hasGeometry():
            return None
        h = hashlib.blake2b(digest_size=16)

        def feed(name, arr):
            if arr is not None and len(arr):
                h.update(name.encode('ascii'))
                h.update(np.ascontiguousarray(arr).tobytes())

        feed('coordIndex', self.coordIndex)
        feed('point', self.coord.point if self.coord else None)
        feed('normalIndex', self.normalIndex)
        feed('normal', self.normal.vector if self.normal else None)
        feed('texCoordIndex', self.texCoordIndex)
        feed('texCoord', self.texCoord.point if self.texCoord else None)
        return ('IndexedFaceSet', h.hexdigest(),
                bool(self.normalPerVertex), round(float(self.creaseAngle), 6),
                bool(self.ccw), bool(self.solid), bool(getattr(self, 'convex', True)))

    def instanceGPU(self, mode):
        """Cached separate-VBO mesh-GPU (position/normal/texcoord) for instancing."""
        from OpenGLContext.passes.instancing import build_mesh_gpu
        arrays = self._instanceArrays()
        if arrays is None:
            return None
        positions, normals, texcoords = arrays
        return build_mesh_gpu(
            mode, self, positions, normals, texcoords, indices=None,
            cache_key='instance_gpu',
            depend_fields=(protofunctions.getField(self, 'coordIndex'),
                           protofunctions.getField(self, 'coord')))


