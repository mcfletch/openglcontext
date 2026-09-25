"""What makes ground *ground*, and the meshes drawn with it.

A landscape's surface is a blend of detail materials -- grass, forest floor,
rock, dirt -- placed over it by a control map and lit by a sun and a canopy
worked out once when the world was built. None of that is a property of the mesh
it is drawn on. :class:`GroundShading` holds it, once for a world; a
:class:`GroundPatch` is one mesh drawn with it.

Two meshes are drawn that way. A world that carries its landscape as a *field*
draws one of them, over the whole square, built from the height field
(:class:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain`). A world that
carries its ground in its *tiles* draws one per tile, meshed and detailed when
the world was baked and refined by the streamer as the camera comes in -- so the
close-up ground is geometry somebody made rather than a coarse surface dressed
up at draw time. The shading is the same in both, which is what makes the two
grounds one ground.

The blend is read from world XZ, so a patch is told where the world put it: a
tile is placed by the tileset's own transform, where a field sits at the origin.
"""
import ctypes
from typing import Any, Callable, Optional

import numpy as np
from OpenGL.GL import (
    GL_ARRAY_BUFFER, GL_BACK, GL_CLAMP_TO_EDGE, GL_DEPTH_TEST,
    GL_ELEMENT_ARRAY_BUFFER, GL_FALSE, GL_FLOAT, GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR, GL_R8, GL_RED, GL_REPEAT, GL_RGBA, GL_RGBA8,
    GL_STATIC_DRAW, GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_2D_ARRAY,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_TRIANGLES, GL_UNSIGNED_BYTE, GL_UNSIGNED_INT,
    glActiveTexture, glBindBuffer, glBindTexture, glBindVertexArray,
    glBufferData, glCullFace, glDrawElements, glEnable,
    glEnableVertexAttribArray, glGenBuffers, glGenTextures, glGenVertexArrays,
    glGenerateMipmap, glTexImage2D, glTexImage3D, glTexParameteri,
    glTexSubImage3D, glUniform1f, glUniform1i, glUniform2f, glUniform3f,
    glUniformMatrix3fv, glUniformMatrix4fv, glUseProgram,
    glVertexAttribPointer,
)
from PIL import Image
from vrml.vrml97 import basenodes as vnodes

from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.instancedgl import (
    ViewPrograms,
    delete_gl,
    ensure_gl,
    load_program,
    texture_rgba,
)
from OpenGLContext.scenegraph.vertexsemantics import LOC_NORMAL, LOC_POSITION

__all__ = ['GroundShading', 'GroundPatch', 'mount_ground', 'GROUND_MATERIAL']

#: What a baked ground primitive's material is called. A bake that means *this
#: surface is ground* says it here, because a material name is what survives
#: being written to glTF and read back -- and because it is a fact about the
#: surface rather than about the file it arrived in.
GROUND_MATERIAL = 'ground'

#: Which way the sunlight travels, from the sun down to the ground: a direction
#: with a negative y. The same figure the landscape's own shadows were baked
#: from.
DEFAULT_SUN = (-0.5, -0.72, -0.48)

# Detail-material tiling: DETAIL_SCALE repeats per world unit (crisp close-up),
# MACRO_SCALE a second, larger tiling mixed in to break the visible repeat.
DETAIL_SCALE = 0.35
MACRO_SCALE = 0.043
NORMAL_STRENGTH = 1.1

# Atmosphere. Kept in step with the vegetation nodes' lighting so the ground and
# the plants on it read under one sun: a warm key light, a hemispheric sky/ground
# ambient split, and exponential height fog.
SUN_COLOR = (1.3, 1.22, 1.05)
SKY_COLOR = (0.42, 0.52, 0.66)
GROUND_AMBIENT = (0.18, 0.17, 0.15)
FOG_DENSITY = 0.00016
FOG_COLOR = (0.46, 0.58, 0.76)

#: Every uniform the ground's program takes. Looked up once, by name, so a
#: shader that gains one needs nothing here but the name.
UNIFORMS = (
    'layerColor', 'layerNormal', 'layerRough', 'controlMap', 'sunShadow',
    'numLayers', 'worldMin', 'worldSize', 'detailScale', 'macroScale',
    'normalStrength', 'uModel', 'uModelView', 'uProjection', 'uNormalMatrix',
    'sunDirEye', 'sunColor', 'skyColor', 'groundAmbient', 'fogDensity',
    'fogColor',
)


class GroundShading:
    """The materials a world's ground is made of, and the light baked into it.

    :param extent: how wide the world's square is, in metres. The control map
        and the baked light cover it, and both are read from world XZ.
    :param layers: up to four detail material names, blended by the control
        map's RGBA channels.
    :param control: the control map -- a path, an open image, or the bytes of
        one.
    :param shading: how much of the sun reaches each cell of the ground, as a
        grid over the same square. What a landscape's own relief and its canopy
        did to the light, worked out once (see
        :attr:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain.shading`).
    :param sun: which way the sunlight travels, for the direct term -- three
        numbers, in any form :func:`numpy.asarray` reads, pointing down from the
        sun (see :data:`DEFAULT_SUN`).
    :param material_fn: ``material_fn(name, res)`` resolving a layer's texture
        paths; defaults to the cc0/ambientCG fetcher.

    One of these serves a whole world: the program, the layer textures, the
    control map and the baked light are built once and every patch drawn with it
    shares them. The uniforms that are the same for every patch are set when
    each form of the program is made; a patch sends only its placement and the
    view. Build it on the GL thread, or leave it to the first draw.
    """

    def __init__(self, extent: float, layers: "list[str]", control: Any,
                 shading: Any,
                 sun: Any = DEFAULT_SUN,
                 material_fn: "Optional[Callable[..., dict[str, Any]]]" = None
                 ) -> None:
        self.extent = float(extent)
        self.layers = list(layers)
        self.control = control
        self.shading = shading
        if material_fn is None:
            from OpenGLContext.loaders import cc0
            material_fn = cc0.material
        self.material_fn = material_fn
        direction = np.asarray(sun, 'd')
        self.sun = direction / np.linalg.norm(direction)
        self._gl: Any = None
        self._disabled = False

    @property
    def world_min(self) -> "tuple[float, float]":
        """The corner of the square the control map covers, in world XZ."""
        return (-self.extent / 2.0, -self.extent / 2.0)

    @property
    def world_size(self) -> "tuple[float, float]":
        """How far that square reaches, in world XZ."""
        return (self.extent, self.extent)

    def _init_gl(self) -> None:
        """Compile the program and upload the textures. GL thread."""
        prog = load_program('terrain_splat.vert', 'terrain_splat.frag')
        tex = dict(col=_array_texture('color', self.layers, self.material_fn),
                   nrm=_array_texture('normal', self.layers, self.material_fn),
                   rgh=_array_texture('roughness', self.layers, self.material_fn),
                   ctl=texture_rgba(self.control, clamp=True, mipmap=False),
                   sun=_shadow_texture(self.shading))
        views = ViewPrograms('terrain_splat.vert', 'terrain_splat.frag',
                             UNIFORMS, prog, setup=self._constants)
        self._gl = dict(prog=prog, tex=tex, views=views)
        views.resend()

    def _constants(self, U: "dict[str, int]") -> None:
        """Set the uniforms every patch shares, on the bound program."""
        for unit, name in enumerate(('layerColor', 'layerNormal', 'layerRough',
                                     'controlMap', 'sunShadow')):
            glUniform1i(U[name], unit)
        glUniform1i(U['numLayers'], len(self.layers))
        glUniform2f(U['worldMin'], *self.world_min)
        glUniform2f(U['worldSize'], *self.world_size)
        glUniform1f(U['detailScale'], DETAIL_SCALE)
        glUniform1f(U['macroScale'], MACRO_SCALE)
        glUniform1f(U['normalStrength'], NORMAL_STRENGTH)
        glUniform3f(U['sunColor'], *SUN_COLOR)
        glUniform3f(U['skyColor'], *SKY_COLOR)
        glUniform3f(U['groundAmbient'], *GROUND_AMBIENT)
        glUniform1f(U['fogDensity'], FOG_DENSITY)
        glUniform3f(U['fogColor'], *FOG_COLOR)

    def ready(self) -> bool:
        """Whether the ground can be drawn, building its GL objects if need be."""
        found: bool = ensure_gl(self)
        return found

    def begin(self, mode: Any, model: Any) -> "Optional[int]":
        """Bind the program, the textures and everything but the geometry.

        ``model`` is where the world put the mesh about to be drawn, as a 4x4
        in the scenegraph's row-vector form (``mode.matrix``'s, translation in
        the last row): the blend is read from world XZ, and a tile is placed by
        the tileset's transform. Answers the program that was bound, for :meth:`end`, or
        None where the program for a shared draw of several views would not
        compile and nothing should be drawn.
        """
        g = self._gl
        form = g['views'].for_mode(mode)
        if form is None:
            return None
        program, U = form
        previous = mode.current_program() if hasattr(mode, 'current_program') else 0
        glUseProgram(program)
        ViewPrograms.apply_views(mode, U)
        glUniformMatrix4fv(U['uModel'], 1, GL_FALSE,
                           np.ascontiguousarray(model, np.float32))
        glUniformMatrix4fv(U['uModelView'], 1, GL_FALSE,
                           np.ascontiguousarray(mode.matrix, np.float32))
        glUniformMatrix4fv(U['uProjection'], 1, GL_FALSE,
                           np.ascontiguousarray(mode.projection, np.float32))
        # The normal matrix is the plain modelview upper-3x3, correct while that
        # block is orthonormal (rotation only). Ground carries no scale, so no
        # inverse-transpose is needed; a scaled transform would skew normals.
        glUniformMatrix3fv(U['uNormalMatrix'], 1, GL_FALSE,
                           np.ascontiguousarray(np.asarray(mode.matrix)[:3, :3],
                                                np.float32))
        # The light's direction of travel in eye space; the shader lights by
        # its reverse, the direction to the sun.
        light = np.asarray(mode.matrix)[:3, :3].T @ self.sun
        light /= np.linalg.norm(light)
        glUniform3f(U['sunDirEye'], *light.astype(np.float32))
        tex = g['tex']
        for unit, (target, name) in enumerate((
                (GL_TEXTURE_2D_ARRAY, 'col'), (GL_TEXTURE_2D_ARRAY, 'nrm'),
                (GL_TEXTURE_2D_ARRAY, 'rgh'), (GL_TEXTURE_2D, 'ctl'),
                (GL_TEXTURE_2D, 'sun'))):
            glActiveTexture(GL_TEXTURE0 + unit)
            glBindTexture(target, tex[name])
        glActiveTexture(GL_TEXTURE0)
        glEnable(GL_DEPTH_TEST)
        # Back-face cull the ground; through the pass's cull memo so the next
        # mesh re-issues its own winding, with no glGet of live state. Seen in a
        # mirror the winding turns over, as it does for every other mesh.
        from OpenGLContext.passes.instancing import set_cull_state
        from OpenGLContext.scenegraph.winding import front_face
        set_cull_state(mode, True, front_face(True, getattr(mode, 'matrix', None),
                                              bool(getattr(mode, 'mirroredDraw', False))))
        glCullFace(GL_BACK)
        return int(previous)

    def end(self, previous: int) -> None:
        """Put back the program the pass had bound."""
        glUseProgram(previous)

    def dispose(self) -> None:
        """Free the program and the textures. GL thread."""
        g = self._gl
        if not g:
            return
        delete_gl(textures=list(g['tex'].values()), programs=list(g['views'].programs()))
        self._gl = None


def _array_texture(kind: str, layers: "list[str]",
                   material_fn: "Callable[..., dict[str, Any]]",
                   size: int = 1024) -> int:
    """A GL_TEXTURE_2D_ARRAY of ``kind`` (color/normal/roughness) for each layer.

    ``material_fn(name, res)`` returns a dict with at least a ``color`` path and
    optionally ``normal``/``roughness`` paths (the ambientCG/cc0 material API)."""
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D_ARRAY, tid)
    glTexImage3D(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA8, size, size, len(layers),
                 0, GL_RGBA, GL_UNSIGNED_BYTE, None)
    for i, name in enumerate(layers):
        m = material_fn(name, "1K")
        p = m.get(kind) or m["color"]
        im = Image.open(p).convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
        glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, i, size, size, 1,
                        GL_RGBA, GL_UNSIGNED_BYTE, np.asarray(im))
    glGenerateMipmap(GL_TEXTURE_2D_ARRAY)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_REPEAT)
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_REPEAT)
    return int(tid)


def _shadow_texture(shading: Any) -> int:
    """The baked light as a single-channel texture over the world's square."""
    lit = np.ascontiguousarray(np.asarray(shading, np.float32))
    found = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, found)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, lit.shape[1], lit.shape[0], 0,
                 GL_RED, GL_FLOAT, lit)
    for name, value in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR),
                        (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                        (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                        (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
        glTexParameteri(GL_TEXTURE_2D, name, value)
    return int(found)


class GroundPatch(vnodes.PointSet):
    """One mesh drawn as ground.

    :param shading: the world's :class:`GroundShading`, shared with every other
        patch of the same ground.
    :param vertices: ``(V, 6)`` float32 rows of position and normal, which is
        what :meth:`~OpenGLContext.scenegraph.terrain.heightfield.HeightField.mesh`
        produces and what a baked tile's ground primitive is read into.
    :param indices: the triangles, as a flat array of uint32.
    :param model: where the world puts this mesh, as a 4x4 in the scenegraph's
        row-vector form: a point ``p`` is at ``[*p, 1] @ model``, translation in
        the last row, as ``MatrixTransform.localMatrix`` holds it. A tile is
        placed by the tileset's transform; a field sits at the origin.

    Subclasses ``PointSet`` only to inherit the scenegraph render hook: it draws
    an indexed triangle mesh through the ground's program, not points. One draw
    serves every view of a shared draw that sees it.
    """

    #: One draw serves every view that sees the patch.
    multiviewShared = True

    def __init__(self, shading: GroundShading, vertices: Any, indices: Any,
                 model: Any = None) -> None:
        super(GroundPatch, self).__init__()
        self.shading = shading
        self.vertices = np.ascontiguousarray(
            np.asarray(vertices, np.float32).reshape(-1, 6))
        self.indices = np.ascontiguousarray(
            np.asarray(indices, np.uint32).ravel())
        self.model = np.eye(4, dtype='d') if model is None \
            else np.asarray(model, dtype='d')
        self._gl: Any = None
        self._disabled = False

    def _init_gl(self) -> None:
        """Upload this patch's own vertex array. GL thread."""
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)
        vb = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vb)
        glBufferData(GL_ARRAY_BUFFER, self.vertices.nbytes, self.vertices,
                     GL_STATIC_DRAW)
        ib = glGenBuffers(1)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, ib)
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, self.indices.nbytes,
                     self.indices, GL_STATIC_DRAW)
        # The ground's program and the shadow pass's depth-only program read
        # the position and the normal from the same locations, so one vertex
        # array serves both -- and the ground is the largest mesh in a world.
        glVertexAttribPointer(LOC_POSITION, 3, GL_FLOAT, GL_FALSE, 24,
                              ctypes.c_void_p(0))
        glEnableVertexAttribArray(LOC_POSITION)
        glVertexAttribPointer(LOC_NORMAL, 3, GL_FLOAT, GL_FALSE, 24,
                              ctypes.c_void_p(12))
        glEnableVertexAttribArray(LOC_NORMAL)
        glBindVertexArray(0)
        self._gl = dict(vao=vao, vb=vb, ib=ib, count=len(self.indices))

    def render(self, mode: Any = None, **named: Any) -> int:
        """Draw the patch, or hand its geometry to the shadow pass."""
        if not len(self.indices):
            return 1
        if getattr(mode, 'shadow_pass', False):
            return self.render_depth(mode)
        if not getattr(mode, 'visible', True):
            return 1
        if not ensure_gl(self) or not self.shading.ready():
            return 1
        from OpenGLContext.multiview.strategy import draw_elements
        previous = self.shading.begin(mode, self.model)
        if previous is None:
            return 1
        glBindVertexArray(self._gl['vao'])
        draw_elements(mode, GL_TRIANGLES, self._gl['count'], GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        self.shading.end(previous)
        return 1

    def render_depth(self, mode: Any) -> int:
        """Write the ground's depth for a shadow map.

        **The ground casts.** A hill shades the valley behind it, a cutting
        shades its own floor, and the rock over a bore is what keeps the sun out
        of it -- none of which happens for ground that only receives. The baked
        light this ground carries shades *itself*; it says nothing to anything
        standing on it or running through it.

        The shadow pass has bound its own depth program and set its matrices, so
        all this does is hand over the geometry.

        The ground's own program and textures are built here too, though this
        draw uses neither: what a world pays for its ground is then paid once,
        in the first pass that asks for any of it, rather than split across two.
        """
        if not ensure_gl(self) or not self.shading.ready():
            return 1
        glBindVertexArray(self._gl['vao'])
        glDrawElements(GL_TRIANGLES, self._gl['count'], GL_UNSIGNED_INT, None)
        glBindVertexArray(0)
        return 1

    def dispose(self) -> None:
        """Free this patch's GL objects. The shading is shared and is not one."""
        g = self._gl
        if not g:
            return
        delete_gl(vaos=[g['vao']], buffers=[g['vb'], g['ib']])
        self._gl = None

    def boundingVolume(self, mode: Any) -> "boundingvolume.AABoundingBox":
        if not len(self.vertices):
            return boundingvolume.AABoundingBox(size=(0, 0, 0), center=(0, 0, 0))
        low = self.vertices[:, :3].min(axis=0)
        high = self.vertices[:, :3].max(axis=0)
        return boundingvolume.AABoundingBox(
            size=tuple(float(v) for v in (high - low)),
            center=tuple(float(v) for v in (low + high) / 2.0))


def mount_ground(root: Any, shading: GroundShading, material: Any,
                 model: Any = None) -> int:
    """Draw every primitive of ``material`` under ``root`` as ground.

    What a bake puts in a tile is an ordinary glTF primitive whose material is
    named :data:`GROUND_MATERIAL`; what draws it is the world's own
    :class:`GroundShading`, shared with every other tile and with the field the
    world is collided against. So the mesh is what the bake made -- meshed at the
    level's own spacing, detailed and cut when the world was built -- and the
    renderer adds nothing to it at draw time.

    ``material`` is that material as the loaded document indexes it,
    ``scene.materials.get(GROUND_MATERIAL)``: glTF keeps material names in a
    namespace of their own, so the name a bake meant is looked up there rather
    than read off a DEF, which yields to the names a scene's nodes have taken.
    None -- a tile that carries no ground -- mounts nothing.

    ``model`` is where the world puts this subtree, which is the tile's own
    transform, in the row-vector form :class:`GroundPatch` takes: the blend is
    read from world XZ.

    A primitive with no normals is left as it was. Ground is shaded from its own
    normals, and one that arrives without them is not ground this can draw.

    :returns: how many primitives were mounted.
    """
    if material is None:
        return 0
    swapped = 0
    for shape in _shapes(root):
        mesh = shape.geometry
        if getattr(mesh, 'material', None) is not material:
            continue
        positions = getattr(mesh, 'positions', None)
        normals = getattr(mesh, 'normals', None)
        if positions is None or normals is None or not len(normals):
            continue
        vertices = np.concatenate(
            [np.asarray(positions, np.float32).reshape(-1, 3),
             np.asarray(normals, np.float32).reshape(-1, 3)], axis=1)
        indices = getattr(mesh, 'indices', None)
        if indices is None or not len(indices):
            indices = np.arange(len(vertices), dtype=np.uint32)
        shape.geometry = GroundPatch(shading, vertices, indices, model=model)
        swapped += 1
    return swapped


def _shapes(root: Any) -> "list[Any]":
    """Every node with geometry under this one, depth first and cycle safe."""
    found = []
    stack = [root]
    seen: "set[int]" = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if getattr(node, 'geometry', None) is not None:
            found.append(node)
        stack.extend(getattr(node, 'children', None) or ())
    return found
