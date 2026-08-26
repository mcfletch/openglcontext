"""Triangle-mesh geometry for PBR / glTF assets.

Holds raw vertex attribute arrays (position, normal, texcoord, optional tangent)
and an optional index buffer, and renders them through the bound shader program
at the attribute locations :mod:`OpenGLContext.scenegraph.vertexsemantics`
declares. Because those locations are the same in every conforming program, the
one VAO built here serves the lit pass, the unlit pass and the shadow depth pass
alike.

The pass binds the program and sets matrices before calling ``render``; this node
only sets up the VAO and issues the draw.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_TRIANGLES, GL_POINTS, GL_FLOAT, GL_FALSE, GL_UNSIGNED_INT,
    GL_ELEMENT_ARRAY_BUFFER, GL_CCW, GL_CW,
    glGenVertexArrays, glBindVertexArray, glDeleteVertexArrays,
    glEnableVertexAttribArray, glVertexAttribPointer,
    glDrawElements, glDrawArrays,
)
from OpenGL.arrays import vbo
from vrml import node, field
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.scenegraph.vertexsemantics import (
    LOC_TEXCOORD, LOC_NORMAL, LOC_POSITION, LOC_TANGENT, LOC_COLOR,
    LOC_TEXCOORD1, LOC_JOINTS, LOC_WEIGHTS,
)


class _MeshGPU(object):
    """Per-context GPU resources for a :class:`PBRMesh` (built once, reused).

    Builds the VBOs and a Vertex Array Object that records the attribute
    pointers and (for indexed meshes) the element-buffer binding, so drawing a
    frame is just ``glBindVertexArray`` + a draw call. Held by the scenegraph
    cache; the buffers are released by ``vbo.VBO`` finalisers when this object is
    collected, and the VAO id is freed in ``release``.
    """

    # Deform counter of the arrays last uploaded to the dynamic VBOs; the cache in
    # PBRMesh._gpu re-uploads when it lags the node's ``_deform_version``.
    _uploaded_morph_version: int = 0

    _ATTRS = (
        ('positions', LOC_POSITION, 3),
        ('normals', LOC_NORMAL, 3),
        ('texcoords', LOC_TEXCOORD, 2),
        ('tangents', LOC_TANGENT, 4),
        ('colors', LOC_COLOR, 4),
        ('texcoords1', LOC_TEXCOORD1, 2),
        ('skin_joint_floats', LOC_JOINTS, 4),
        ('skin_weights', LOC_WEIGHTS, 4),
    )

    def __init__(self, mesh: Any, pending_deletes: Optional[list[Any]] = None) -> None:
        # Shared per-context list the finalizer hands its VAO id to; deleted at a
        # safe point by PBRMesh.flush_pending_deletes. A list, not
        # the context, so this GPU object never keeps a context alive.
        self._pending_deletes = pending_deletes
        self.vao = None
        # Persistent instanced-draw resources, built lazily by the instancing
        # module's draw path and reused across frames (no per-frame VAO/VBO churn).
        # The instance VBO is a self-finalizing vbo.VBO; the VAO id is reclaimed
        # here, like ``self.vao``.
        self._instance_vao = None
        self._instance_vbo = None
        self.indexed = mesh.indices is not None
        self.count = len(mesh.indices) if self.indexed else len(mesh.positions)
        self.draw_mode = int(getattr(mesh, 'draw_mode', GL_TRIANGLES))
        self.idx_vbo = None
        if self.indexed:
            self.idx_vbo = vbo.VBO(mesh.indices, target=GL_ELEMENT_ARRAY_BUFFER)

        self.attr_layout: list[tuple[Any, int, int]] = []  # (vbo, location, size) recorded into the VAO
        # name -> VBO for the attributes a morph deform re-uploads in place. The
        # VAO records the attribute *binding* (buffer id + pointer), so updating
        # the buffer's contents keeps the VAO valid -- no re-specification needed.
        self.dyn: dict[str, Any] = {}
        for name, loc, size in self._ATTRS:
            # Optional attributes (e.g. a second UV set) may be absent on simpler
            # mesh types such as the quadric/IFS _ArrayMesh; treat missing as None.
            data = getattr(mesh, name, None)
            if data is None:
                continue
            buf = vbo.VBO(data)
            self.attr_layout.append((buf, loc, size))
            if name in ('positions', 'normals', 'tangents'):
                if getattr(mesh, 'deforms_vertices', False):
                    self.dyn[name] = buf
            elif name == 'texcoords' and getattr(mesh, 'deforms_texcoords', False):
                # Only where the mesh says its UVs move: a skinned character's
                # never do, and re-uploading them every frame is pure waste.
                self.dyn[name] = buf

        self.vao = glGenVertexArrays(1)
        glBindVertexArray(self.vao)
        self._bind_attributes()
        if self.idx_vbo is not None:
            self.idx_vbo.bind()  # recorded in the VAO's element-buffer binding
        glBindVertexArray(0)
        for buf, _loc, _size in self.attr_layout:
            buf.unbind()
        if self.idx_vbo is not None:
            self.idx_vbo.unbind()

    def _bind_attributes(self) -> None:
        for buf, loc, size in self.attr_layout:
            buf.bind()
            glEnableVertexAttribArray(loc)
            glVertexAttribPointer(loc, size, GL_FLOAT, GL_FALSE, 0, None)

    def _draw_elements(self) -> None:
        if self.indexed:
            glDrawElements(self.draw_mode, self.count, GL_UNSIGNED_INT, None)
        else:
            glDrawArrays(self.draw_mode, 0, self.count)

    def update_dynamic(self, mesh: Any) -> None:
        """Re-upload the deformed vertex buffers in place.

        Which buffers those are was decided when they were built: positions,
        normals and tangents always, texture coordinates only for a mesh whose
        UVs move.
        """
        for name, buf in self.dyn.items():
            data = getattr(mesh, name)
            if data is not None:
                buf.set_array(np.ascontiguousarray(data, dtype=np.float32))
                buf.bind()      # pushes the new data to the existing buffer id
                buf.unbind()

    def draw(self) -> None:
        glBindVertexArray(self.vao)
        if self.draw_mode == GL_POINTS:
            # let the vertex shader's gl_PointSize take effect (core profile)
            from OpenGL.GL import glEnable, glDisable, GL_PROGRAM_POINT_SIZE
            glEnable(GL_PROGRAM_POINT_SIZE)
            self._draw_elements()
            glDisable(GL_PROGRAM_POINT_SIZE)
        else:
            self._draw_elements()
        glBindVertexArray(0)

    def release(self) -> None:
        """Delete the VAOs now. Only safe when the owning context is current."""
        for attr in ('vao', '_instance_vao'):
            vao = getattr(self, attr, None)
            if vao is not None:
                try:
                    glDeleteVertexArrays(1, [vao])
                except Exception:
                    pass
                setattr(self, attr, None)

    def __del__(self) -> None:
        # Never call GL from a finalizer: GC can run this with no current context
        # (leaking the VAO) or with a *different* context current (deleting an
        # unrelated live VAO that happens to reuse this id). Hand the id to the
        # per-context queue instead; the pass deletes it next frame while the
        # right context is current.
        # getattr defaults: a _MeshGPU built via __new__ (tests) never ran __init__,
        # so the instance-VAO slot may be absent -- a finalizer must not raise.
        vao = getattr(self, 'vao', None)
        ivao = getattr(self, '_instance_vao', None)
        self.vao = None
        self._instance_vao = None
        pending = getattr(self, '_pending_deletes', None)
        if pending is not None:
            for v in (vao, ivao):
                if v is not None:
                    try:
                        pending.append(v)
                    except Exception:
                        pass


class PBRMesh(node.Node):
    """Indexed triangle mesh with PBR vertex attributes."""
    PROTO = 'PBRMesh'

    solid = field.newField('solid', 'SFBool', 1, True)

    #: The undeformed arrays, captured the first time anything wants to deform
    #: this mesh -- by morph targets, by skinning, or by a material's own
    #: surface deformer. None until then, which is also how a static mesh is
    #: told apart from a posed one.
    _base_positions: Any = None
    _base_normals: Any = None
    _base_tangents: Any = None
    _base_texcoords: Any = None

    #: Whether the vertex shader skins this mesh rather than the CPU. Settled
    #: on the first draw, from what the renderer is configured for and what the
    #: driver can do; until then it is what the engine would prefer, so a mesh
    #: posed before it is ever drawn keeps the rest pose in its buffers rather
    #: than deforming arrays the shader is about to skin again.
    skin_on_gpu: bool = True
    _skin_path_settled: bool = False
    _skin_version: int = 0
    _uploaded_skin_version: int = 0
    _joint_bound_cache: Any = None
    #: Whether a compute shader owns this mesh's palette range.
    _skin_from_gpu: bool = False
    #: A mesh whose joint palette this one shares -- a figure's coarse level
    #: reading the range its fine level holds, since both are posed alike.
    _palette_peer: Any = None
    _palette_base: Optional[int] = None

    def __init__(self, positions: Any = None, normals: Any = None, texcoords: Any = None,
                 tangents: Any = None, colors: Any = None, indices: Any = None,
                 solid: bool = True,
                 material: Any = None, morph_targets: Any = None,
                 skin_joints: Any = None, skin_weights: Any = None, texcoords1: Any = None,
                 draw_mode: int = GL_TRIANGLES, **named: Any) -> None:
        super(PBRMesh, self).__init__(solid=solid, **named)
        # GL primitive mode (glTF primitive.mode == the GL enum): GL_TRIANGLES for the
        # common case, or GL_POINTS/GL_LINES/GL_LINE_LOOP/GL_LINE_STRIP.
        self.draw_mode = int(draw_mode)
        # The owning material, when the mesh is placed without a Shape wrapper, so
        # sortKey can classify transparency directly. The normal
        # glTF/scenegraph path wraps the mesh in a Shape whose Appearance carries
        # the material; there Shape.sortKey/Appearance.sortKey drives sorting.
        self.material = material
        self.positions = self._farray(positions, 3)
        self.normals = self._farray(normals, 3)
        self.texcoords = self._farray(texcoords, 2)
        self.texcoords1 = self._farray(texcoords1, 2)
        self.tangents = self._farray(tangents, 4)
        self.colors = self._rgba(colors)
        self.indices = None if indices is None else np.asarray(indices, dtype=np.uint32).ravel()
        self._volume: Any = None
        self._init_deform(morph_targets, skin_joints, skin_weights)

    @staticmethod
    def _farray(a: Any, width: int) -> Optional[np.ndarray]:
        if a is None:
            return None
        a = np.asarray(a, dtype=np.float32)
        if a.ndim == 1:
            a = a.reshape(-1, width)
        return np.ascontiguousarray(a, dtype=np.float32)

    @classmethod
    def _rgba(cls, colors: Any) -> Optional[np.ndarray]:
        """Vertex colours as RGBA, widening RGB to it.

        glTF's COLOR_0 is VEC3 or VEC4, and a mesher with no transparency to
        express writes three. The attribute the shader reads is four wide
        either way, so a three-wide array is given an opaque alpha rather than
        handed over to be read past the end of.
        """
        widened = cls._farray(colors, 4)
        if widened is None or widened.shape[-1] == 4:
            return widened
        opaque = np.ones((len(widened), 4), dtype=np.float32)
        opaque[:, :widened.shape[-1]] = widened
        return opaque

    # -- deformation (morph targets + linear-blend skinning) ----------------
    def _init_deform(self, morph_targets: Any, skin_joints: Any, skin_weights: Any) -> None:
        """Store rest-pose base arrays and set up morph / skin state.

        A deformable mesh keeps immutable ``_base_*`` rest arrays; every frame the
        active weights (:meth:`set_morph_weights`) and joint matrices
        (:meth:`set_skin_matrices`) recompute ``positions``/``normals``/
        ``tangents`` as morph-then-skin (the glTF-defined order). ``_deform_version``
        is bumped on each change so each per-context GPU re-uploads when stale.
        """
        self.morph_targets: list[dict[str, Any]] = []
        self.morph_weights: Optional[np.ndarray] = None
        self.skin_joints: Any = None
        self.skin_joint_floats: Any = None
        self.skin_weights: Any = None
        self._skin_matrices: Any = None
        self._deform_version = 0
        self._skin_version = 0
        self._uploaded_skin_version = 0
        self._skin_path_settled = False
        self._skin_from_gpu = False
        self._joint_bound_cache = None
        #: A material's claim on this surface's shape -- see
        #: :meth:`set_surface_deformer`.  Distinct from morph and skin, which
        #: are the *mesh's* own animation; this is movement the thing painted
        #: on the mesh asks for, and it runs last.
        self._surface_deformer: Any = None
        skinned = skin_joints is not None and skin_weights is not None
        if not morph_targets and not skinned:
            return
        self._capture_rest_pose()
        for tgt in (morph_targets or []):
            entry: dict[str, Any] = {}
            for key, width in (('positions', 3), ('normals', 3), ('tangents', 3)):
                arr = tgt.get(key) if tgt else None
                if arr is not None:
                    entry[key] = self._farray(arr, width)
            self.morph_targets.append(entry)
        if self.morph_targets:
            self.morph_weights = np.zeros(len(self.morph_targets), dtype=np.float32)
        if skinned:
            j = np.asarray(skin_joints, dtype=np.uint32)
            w = np.asarray(skin_weights, dtype=np.float32)
            self.skin_joints = np.ascontiguousarray(j.reshape(-1, 4))
            # The same indices as floats, because that is what a GL 3.3 vertex
            # attribute carries without an integer-attribute pointer, and a
            # joint index is far inside what a float names exactly.
            self.skin_joint_floats = np.ascontiguousarray(
                self.skin_joints, dtype=np.float32)
            w = w.reshape(-1, 4)
            wsum = w.sum(axis=1, keepdims=True)
            wsum[wsum == 0] = 1.0
            self.skin_weights = np.ascontiguousarray(w / wsum, dtype=np.float32)

    def _capture_rest_pose(self) -> None:
        """Keep the undeformed arrays, so every frame deforms the *rest* pose.

        Deforming the last frame's result compounds: a one-unit wave walks the
        surface away over a few seconds.  Copies rather than references, so a
        deformer that writes in place cannot corrupt what it is handed next
        frame.
        """
        if self._base_positions is not None:
            return
        self._base_positions = None if self.positions is None else self.positions.copy()
        self._base_normals = None if self.normals is None else self.normals.copy()
        self._base_tangents = None if self.tangents is None else self.tangents.copy()
        self._base_texcoords = None if self.texcoords is None else self.texcoords.copy()

    def set_surface_deformer(self, deformer: Any) -> None:
        """Set what a *material* does to this surface's vertices, or None.

        ``deformer(positions, normals, texcoords)`` returns the three arrays
        moved, and is called afresh whenever :meth:`refresh_surface` is -- so a
        deformer that reads a clock is re-read rather than remembered.  It is
        always handed the rest pose (after any morph and skin), never its own
        last output.

        This is how a Quake `.shader`'s ``deformVertexes`` and ``tcMod turb``
        reach the geometry: the movement belongs to what is painted on the
        surface rather than to the mesh, so it is set by whoever built the
        material and runs after the mesh's own animation.

        Set it **before** the mesh is first drawn: whether the texture-coordinate
        buffer is uploaded as dynamic is decided when the GPU buffers are built
        (:attr:`deforms_texcoords`).
        """
        self._capture_rest_pose()
        self._surface_deformer = deformer
        self._apply_deform()

    def refresh_surface(self) -> None:
        """Re-run the deform chain, picking up whatever the deformer now says."""
        if self._surface_deformer is not None:
            self._apply_deform()

    @property
    def deforms_texcoords(self) -> bool:
        """Whether this mesh's UVs move and so want a dynamic vertex buffer.

        Morphing and skinning never move UVs, so a skinned character does not
        pay to re-upload them; a surface with a ``tcMod turb`` on it does.
        """
        return self._surface_deformer is not None and self.texcoords is not None

    @property
    def _morph_version(self) -> int:
        # back-compat alias: the GPU cache keys re-upload off this counter.
        return self._deform_version

    @property
    def is_deformable(self) -> bool:
        """True when the mesh has morph targets or skin joints (per-frame CPU
        deform + dynamic VBO re-upload); a plain static mesh returns False."""
        return (bool(self.morph_targets) or self.skin_joints is not None
                or self._surface_deformer is not None)

    @property
    def deforms_vertices(self) -> bool:
        """Whether this mesh's vertex arrays change and so want dynamic buffers.

        A skinned mesh drawn through the vertex shader's skinning does not: its
        buffers hold the rest pose for the life of the context, and the pose is
        a palette of matrices instead. Morph targets and a material's surface
        deformer both still move the vertices themselves.
        """
        if bool(self.morph_targets) or self._surface_deformer is not None:
            return True
        return self.skin_joints is not None and not self.skin_on_gpu

    def set_morph_weights(self, weights: Any) -> None:
        """Set morph-target weights and recompute the deformed mesh (CPU)."""
        if not self.morph_targets:
            return
        w = np.zeros(len(self.morph_targets), dtype=np.float32)
        src = np.asarray(weights, dtype=np.float32).ravel()
        w[:len(src)] = src[:len(w)]
        self.morph_weights = w
        self._apply_deform()

    def set_skin_matrices(self, matrices: Any) -> None:
        """Set the per-joint skin matrices (J,4,4 row-vector) for this frame.

        Where the vertex shader does the skinning, this is the whole of what a
        posed frame costs the mesh: the matrices are handed to the GPU as they
        are, and the vertex buffers -- which still hold the rest pose -- are
        left alone. Where it does not, the mesh is deformed here instead, and
        the deformed arrays are re-uploaded before the next draw.
        """
        if self.skin_joints is None:
            return
        self._skin_matrices = np.ascontiguousarray(matrices, dtype=np.float64)
        self._skin_version += 1
        if self.skin_on_gpu:
            self._volume = None
            return
        self._apply_deform()

    def _apply_deform(self) -> None:
        """Recompute positions/normals/tangents = skin(morph(base))."""
        pos, nrm, tan, uvs = self._deformed()
        self.positions = None if pos is None else np.ascontiguousarray(pos, dtype=np.float32)
        self.normals = None if nrm is None else np.ascontiguousarray(nrm, dtype=np.float32)
        self.tangents = tan
        if uvs is not None:
            self.texcoords = np.ascontiguousarray(uvs, dtype=np.float32)
        self._volume = None
        self._deform_version += 1

    def posed_positions(self) -> Any:
        """Where this mesh's vertices are in the pose it was last given.

        The vertex arrays of a mesh the shader skins hold the rest pose for the
        life of the context, which is the point of skinning there -- so a caller
        that wants the *posed* vertices rather than a picture of them, to
        measure a reach or to test a pose, asks for them here and is given a
        fresh array. Under the CPU deform this is what ``positions`` already
        holds.
        """
        if not self.is_deformable:
            return self.positions
        return self._deformed()[0]

    def _deformed(self) -> tuple:
        """(positions, normals, tangents, texcoords) = surface(skin(morph(base)))."""
        pos = None if self._base_positions is None else self._base_positions.astype(np.float64)
        nrm = None if self._base_normals is None else self._base_normals.astype(np.float64)
        tan = None if self._base_tangents is None else self._base_tangents.copy()
        # 1) morph: base + sum_i weight_i * target_i
        if self.morph_weights is not None:
            for wi, tgt in zip(self.morph_weights, self.morph_targets, strict=True):
                if wi == 0.0:
                    continue
                if pos is not None and 'positions' in tgt:
                    pos += wi * tgt['positions']
                if nrm is not None and 'normals' in tgt:
                    nrm += wi * tgt['normals']
                if tan is not None and 'tangents' in tgt:
                    tan[:, :3] += wi * tgt['tangents']
        # 2) skin: linear blend of the per-vertex weighted joint matrices
        if self._skin_matrices is not None and self.skin_joints is not None and pos is not None:
            mats = self._skin_matrices                      # (J,4,4) row-vector
            per_vertex = np.einsum(
                'nk,nkij->nij', self.skin_weights, mats[self.skin_joints])  # (N,4,4)
            ph = np.concatenate([pos, np.ones((len(pos), 1))], axis=1)      # (N,4)
            pos = np.einsum('ni,nij->nj', ph, per_vertex)[:, :3]
            if nrm is not None:
                nrm = np.einsum('ni,nij->nj', nrm, per_vertex[:, :3, :3])
            if tan is not None:
                tan[:, :3] = np.einsum('ni,nij->nj', tan[:, :3].astype(np.float64),
                                       per_vertex[:, :3, :3]).astype(np.float32)
        # 3) the material's own claim on the surface, last, on the posed mesh.
        uvs = None if self._base_texcoords is None else self._base_texcoords.copy()
        if self._surface_deformer is not None:
            moved = self._surface_deformer(
                None if pos is None else pos.copy(),
                None if nrm is None else nrm.copy(), uvs)
            if moved is not None:
                # A deformer that returns nothing usable costs its effect, not
                # the surface: content is not always well formed.
                pos, nrm, uvs = moved
        if nrm is not None:
            lens = np.linalg.norm(nrm, axis=1, keepdims=True)
            lens[lens == 0] = 1.0
            nrm = nrm / lens
        return pos, nrm, tan, uvs

    # -- bounding volume (frustum culling + shadow occluder points) ---------
    def boundingVolume(self, mode: Any = None) -> Any:
        if self._volume is None:
            if self.positions is None or not len(self.positions):
                self._volume = boundingvolume.BoundingVolume()
            elif self.skin_on_gpu and self._skin_matrices is not None:
                self._volume = boundingvolume.AABoundingBox.fromPoints(self.posed_positions())
            else:
                self._volume = boundingvolume.AABoundingBox.fromPoints(self.positions)
        return self._volume

    def _posed_volume(self) -> Any:
        """Bounds for a mesh whose vertices the shader poses, not the CPU.

        The vertex arrays hold the rest pose, so bounding *them* would put a
        figure's bounds where it was modelled rather than where it is -- which
        culls a body its animation has carried out of the box, and misleads
        everything else that reads a scene's extent, the image-based lighting
        included.

        Every vertex the pose moves is moved by a joint that reaches it, so the
        sphere around **that joint's own** rest-pose vertices, carried by the
        joint's matrix, contains it. The union over the joints is therefore a
        bound on the posed mesh, and a close one: a joint reaches a hand or a
        shin, not the whole body. It costs one small matrix product a frame
        rather than skinning the mesh a second time.
        """
        centres, radii, used = self._joint_bounds()
        matrices = self._skin_matrices
        count = min(len(matrices), len(centres))
        if not count or not used[:count].any():
            return boundingvolume.AABoundingBox.fromPoints(self.positions)
        live = np.flatnonzero(used[:count])
        homogeneous = np.concatenate(
            [centres[live], np.ones((len(live), 1))], axis=1)
        moved = np.einsum('ji,jik->jk', homogeneous, matrices[live])[:, :3]
        reach = radii[live][:, None]
        return boundingvolume.AABoundingBox.fromPoints(
            np.concatenate([moved - reach, moved + reach]))

    def _joint_bounds(self) -> tuple:
        """Per joint: the centre and radius of the rest vertices it reaches.

        Worked out once from the bind pose, which is all it depends on.
        """
        if self._joint_bound_cache is None:
            rest = (self._base_positions if self._base_positions is not None
                    else self.positions).astype('d')
            count = int(self.skin_joints.max()) + 1 if len(self.skin_joints) else 0
            low = np.full((count, 3), np.inf)
            high = np.full((count, 3), -np.inf)
            for column in range(self.skin_joints.shape[1]):
                reached = self.skin_weights[:, column] > 0
                if not reached.any():
                    continue
                index = self.skin_joints[reached, column]
                np.minimum.at(low, index, rest[reached])
                np.maximum.at(high, index, rest[reached])
            used = np.isfinite(low).all(axis=1)
            centres = np.where(used[:, None], (low + high) / 2.0, 0.0)
            radii = np.where(used, np.linalg.norm(
                np.where(used[:, None], high - low, 0.0), axis=1) / 2.0, 0.0)
            self._joint_bound_cache = (centres, radii, used)
        return self._joint_bound_cache

    # -- rendering ----------------------------------------------------------
    # Cache key under which the per-context VAO+VBOs hang off ``mode.cache``.
    _GPU_CACHE_KEY = 'pbrmesh_gpu'

    def instanceGPU(self, mode: Any) -> "_MeshGPU":
        """The cached mesh-GPU used by the instanced draw path (its own VAO)."""
        return self._gpu(mode)

    def _gpu(self, mode: Any) -> "_MeshGPU":
        """Return the cached ``_MeshGPU`` (VAO + VBOs) for this context.

        The VAO records the vertex-attribute and element-buffer bindings once,
        so per-frame rendering is a single ``glBindVertexArray`` + draw instead
        of re-uploading pointers (and churning a VAO) every frame for every
        primitive. Resources hang off the context ``mode.cache`` keyed on this
        node, so they are dropped when the node is collected.
        """
        gpu = mode.cache.getData(self, key=self._GPU_CACHE_KEY)
        if gpu is None:
            gpu = _MeshGPU(self, pending_deletes=self._pending_delete_queue(mode))
            mode.cache.holder(self, gpu, key=self._GPU_CACHE_KEY)
            if self.is_deformable:
                # Freshly built from the current (already-deformed) arrays.
                gpu._uploaded_morph_version = self._deform_version
        elif self.is_deformable and \
                getattr(gpu, '_uploaded_morph_version', 0) != self._deform_version:
            gpu.update_dynamic(self)
            gpu._uploaded_morph_version = self._deform_version
        built: _MeshGPU = gpu
        return built

    # Per-context queue of VAO ids whose owning mesh has been collected. The
    # finalizer can't touch GL, so it appends here and the pass
    # drains it via flush_pending_deletes with the context current.
    _PENDING_DELETE_ATTR = '_pbr_pending_vao_deletes'

    @classmethod
    def _pending_delete_queue(cls, mode: Any) -> list[Any]:
        target = getattr(mode, 'context', None) or mode
        q = getattr(target, cls._PENDING_DELETE_ATTR, None)
        if q is None:
            q = []
            try:
                setattr(target, cls._PENDING_DELETE_ATTR, q)
            except Exception:
                return []   # can't stash the queue; deletes fall to context teardown
        return q

    @classmethod
    def flush_pending_deletes(cls, mode: Any) -> None:
        """Delete VAOs orphaned by collected meshes.

        Called once per pass with the context current, so the ids -- which are
        only meaningful in their owning context -- are deleted safely. Idempotent
        and a no-op when nothing was collected.
        """
        target = getattr(mode, 'context', None) or mode
        q = getattr(target, cls._PENDING_DELETE_ATTR, None)
        if not q:
            return
        ids, q[:] = q[:], []
        for vao in ids:
            try:
                glDeleteVertexArrays(1, [vao])
            except Exception:
                pass

    def render(self, visible: int = 1, lit: int = 1, textured: int = 1,
               transparent: int = 0, mode: Any = None) -> int:
        if self.positions is None or not len(self.positions):
            return 1
        if not getattr(mode, 'shader_mode', False):
            return 1  # PBR meshes are shader-only

        sp = getattr(mode, 'shader_program', None)
        if self.skin_joints is not None:
            self._resolve_skin_path(mode, sp)
        gpu = self._gpu(mode)      # re-uploads morph-deformed buffers if stale
        self._apply_draw_state(mode)
        if sp is not None and hasattr(sp, 'set_skinning'):
            # Every mesh says whether it is skinned, not only the skinned ones:
            # the uniform outlives the draw that set it, and an unskinned shape
            # after a figure would otherwise be posed by the figure's joints.
            sp.set_skinning(self._skin_palette_base(mode))

        # Tell the shader whether this mesh carries per-vertex colors. Skipped in
        # the shadow depth pass: the depth program has no such uniform (and is the
        # bound program), so setting it would target the wrong program.
        if not getattr(mode, 'shadow_pass', False):
            if sp is not None and hasattr(sp, 'set_vertex_color'):
                sp.set_vertex_color(self.colors is not None)

        gpu.draw()
        return 1

    # -- skinning -----------------------------------------------------------
    def _resolve_skin_path(self, mode: Any, program: Any) -> None:
        """Settle, once, whether the vertex shader skins this mesh or the CPU does.

        Before the first draw the mesh assumes the shader will, so a pose set
        while the scene is still loading leaves the rest pose in the vertex
        buffers rather than deforming arrays the shader is about to skin again.
        Here is where that assumption meets the renderer that is actually
        running -- a driver with no texture unit to spare for the palette, a
        pass with no skinning in its program, or an application that has asked
        for the CPU deform -- and where it is put right if it was wrong.
        """
        if self._skin_path_settled:
            return
        self._skin_path_settled = True
        from OpenGLContext.scenegraph.skinning import (
            gpu_skinning_is_enabled, palette_for,
        )
        wanted = (gpu_skinning_is_enabled(getattr(mode, 'context', None) or mode)
                  and bool(getattr(program, 'skinning_supported', False))
                  and palette_for(mode) is not None)
        if wanted:
            return
        self.skin_on_gpu = False
        if self._skin_matrices is not None:
            self._apply_deform()

    def _skin_palette_base(self, mode: Any) -> Optional[int]:
        """This mesh's place in the joint palette, its matrices written there.

        ``None`` where the mesh is not skinned on the GPU or has not been posed
        yet, which draws the rest pose -- the same thing an unposed figure has
        always drawn.
        """
        claimed = self.skin_claim(mode)
        if claimed is None:
            return None
        base, matrices = claimed
        if matrices is not None:
            from OpenGLContext.scenegraph.skinning import palette_for
            palette = palette_for(mode)
            if palette is not None:
                palette.write(base, matrices)
        return base

    def skin_from_gpu(self, mode: Any, joints: int) -> Optional[int]:
        """Reserve this mesh's palette range for a compute shader to fill.

        The joint matrices then live only on the GPU: nothing is uploaded for
        this mesh and nothing is read back. Returns where its range starts, or
        None where there is no palette to reserve from.
        """
        if not self.skin_on_gpu:
            return None
        from OpenGLContext.scenegraph.skinning import palette_for
        palette = palette_for(mode)
        if palette is None:
            return None
        self._skin_from_gpu = True
        return palette.reserve(self, joints)

    def skin_claim(self, mode: Any) -> Optional[tuple]:
        """``(base, matrices)`` for this mesh, or None if it is not skinned here.

        ``matrices`` is None where what is in the palette is already this pose.
        Separate from writing them so a caller drawing a whole crowd can gather
        every figure's range and upload the lot in one go, which is one call
        rather than one a body.
        """
        if not self.skin_on_gpu:
            return None
        from OpenGLContext.scenegraph.skinning import palette_for
        palette = palette_for(mode)
        if palette is None:
            return None
        if self._skin_from_gpu:
            # A compute shader filled the range this frame; the matrices never
            # existed on this side to send.
            reserved = palette.reserved_base(self)
            return None if reserved is None else (reserved, None)
        if self._skin_matrices is None:
            return None
        base = palette.reserve(self, len(self._skin_matrices))
        if self._uploaded_skin_version == self._skin_version:
            return base, None
        self._uploaded_skin_version = self._skin_version
        return base, self._skin_matrices

    def _wants_cull(self, mode: Any) -> bool:
        """Whether back-face culling should be on for this mesh in this pass.

        Off during the shadow depth pass (all casters write depth),
        for a non-solid mesh, or for a double-sided material.
        """
        if getattr(mode, 'shadow_pass', False):
            return False
        if not self.solid:
            return False
        if getattr(mode, '_appearance_double_sided', False):
            return False
        return True

    def _apply_draw_state(self, mode: Any) -> None:
        """Set winding + cull state, skipping redundant GL calls.

        A negative-determinant modelview flips triangle winding, so the front-face
        must follow it for culling to stay correct. Both the winding and the cull
        enable are tracked on ``mode`` and only re-issued when they actually
        change -- an assembly draws hundreds of same-state shapes in a row. The
        pass restores the GL defaults once at the end via :meth:`reset_draw_state`,
        so no CW winding or disabled-cull state leaks past the geometry loop.
        """
        from OpenGLContext.passes.instancing import set_cull_state
        set_cull_state(mode, self._wants_cull(mode),
                       self._front_face(getattr(mode, 'matrix', None)))

    @staticmethod
    def reset_draw_state(mode: Any) -> None:
        """Restore GL winding/cull defaults after the geometry loop.

        Called once per pass, not per draw, so a mesh's CW winding or disabled
        culling never leaks into the next pass/frame. Idempotent and safe to call
        even if no PBR mesh drew.
        """
        from OpenGLContext.passes.instancing import reset_cull_state
        reset_cull_state(mode)

    def _front_face(self, mv: Any) -> int:
        if mv is None:
            return int(GL_CCW)
        try:
            a = mv.tolist() if hasattr(mv, 'tolist') else mv
            # Sign of the modelview upper-3x3 determinant (a direct 3x3 solve, not
            # a per-shape LAPACK det()); negative parity flips triangle winding.
            det = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
                   - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
                   + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
        except Exception:
            return int(GL_CCW)
        return int(GL_CW) if det < 0 else int(GL_CCW)

    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
        # Report transparency from the attached material so a mesh placed without a
        # Shape still sorts into the transparent pass. The common
        # path renders through a Shape, where Appearance.sortKey decides instead.
        from OpenGLContext.scenegraph.pbrmaterial import material_is_transparent
        return (material_is_transparent(self.material), [], None)
