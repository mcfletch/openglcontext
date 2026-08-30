"""Shadow-map rendering mixin for shader-based FlatPass subclasses.

Captures each shadow-casting light's view of the scene into a depth map (a 2D map
for spot lights, a cascaded 2D-array for directional lights, a cube map for point
lights) and binds those maps + matrices so the lit shader can sample them. Mixes
into ``flatcore.FlatPass`` (or the PBR pass); a no-op unless ``use_shadows`` is on
and the scene has a supported shadow-casting light.

The depth pass reuses the existing lit pipeline driven by ``mode.matrix`` /
``mode.projection`` into a depth-only FBO, so it works across all geometry node
types (including ones that bind their own program). Shapes skip appearance setup
during the pass via the ``mode.shadow_pass`` flag.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np

from OpenGL.GL import (
    glEnable, glDisable, glIsEnabled, glPolygonOffset, glCullFace,
    glGetIntegerv, glBindFramebuffer, glViewport,
    GL_POLYGON_OFFSET_FILL, GL_CULL_FACE, GL_CULL_FACE_MODE,
    GL_DEPTH_CLAMP, GL_FRAMEBUFFER, GL_FRAMEBUFFER_BINDING, GL_VIEWPORT,
)
from OpenGLContext.arrays import dot  # type: ignore[attr-defined]  # numpy re-export via vrml.arrays star import
from OpenGLContext import frustum as frustum_module
from OpenGLContext.scenegraph import light as light_module
from OpenGLContext.passes import shadowmath
from OpenGLContext.passes.shadowmath import SHADOW_DEPTH_BIAS
from OpenGLContext.passes.shadowcaps import ShadowCapabilities
from OpenGLContext.passes.shadowpool import _CascadeControllerMixin, _ShadowMapPoolMixin
from vrml.vrml97 import nodetypes

log = logging.getLogger(__name__)

# Shadow depth-pass acne controls, named rather than scattered as literals
#. Polygon offset is the single *primary* control; the receiver
# shader adds a small constant depth bias plus a normal offset as secondary.
# Front-face culling was previously stacked on top of these as a fourth control
# pushing the same way, which over-biased into peter-panning AND silently
# dropped shadows from open / single-sided casters -- it has been
# removed in favour of the per-geometry ``solid`` handling the nodes already do.
SHADOW_POLYGON_OFFSET_FACTOR = 2.0
SHADOW_POLYGON_OFFSET_UNITS = 4.0
SHADOW_NORMAL_OFFSET = 0.02    # receiver normal offset, world units (shader)
# Bounds for a per-light requested shadow-map resolution.
SHADOW_MIN_RESOLUTION = 256
SHADOW_MAX_RESOLUTION = 8192


def per_light_shadow_resolution(lights: List[Any], default_resolution: int) -> int:
    """Resolution for the shadow maps, from the casting lights.

    They share one physical depth array, so one resolution serves every slot:
    the largest any light asks for, which keeps detail for the pickiest of them,
    clamped to a range a driver will allocate. A light leaving the field unset
    asks for nothing.

    Bias is not settled here. It is a count of shadow texels, converted into each
    map's own depth units where that map is built (``shadowmath.depth_bias_terms``),
    so every light's ``shadowBias`` reaches its own shadow rather than the largest
    of them reaching all.
    """
    resolutions = [int(r) for r in (getattr(light, 'shadowMapResolution', None)
                                    for light in lights) if r]
    resolution = max(resolutions) if resolutions else default_resolution
    return int(max(SHADOW_MIN_RESOLUTION, min(resolution, SHADOW_MAX_RESOLUTION)))


def light_depth_bias(light: Any) -> float:
    """The depth bias ``light`` asks its receivers to use, in shadow texels."""
    bias = getattr(light, 'shadowBias', None)
    return SHADOW_DEPTH_BIAS if bias is None else float(bias)


class ShadowMapMixin(_CascadeControllerMixin, _ShadowMapPoolMixin):
    """Adds shadow-map depth pre-pass + uniform binding to a FlatPass."""

    def instanceMinimum(self) -> int:
        """Smallest caster group worth one instanced depth draw.

        The host FlatPass overrides this with the environment-settled figure;
        the fallback here is what lets the depth-grouping logic be exercised
        without standing up a whole pass and a GL context.
        """
        return 8

    if TYPE_CHECKING:
        # Attributes/methods the host FlatPass supplies; declared for the type
        # checker so the mixin can reference them on ``self``.
        paths: Any
        matrix: np.ndarray
        projection: np.ndarray
        _caster_points: Optional[np.ndarray]

        def getModelView(self) -> np.ndarray: ...
        def _instanceKey(self, record: Any) -> Any: ...
        def _instanceable(self, record: Any) -> bool: ...

    use_shadows: bool = False
    shadow_pass: bool = False
    shadow_resolution: int = 2048
    shadow_cube_resolution: int = 1024
    # Directional-shadow cascade budget. Each extra cascade re-renders + clears a
    # full-resolution depth layer every frame, so cascades are treated as a
    # *premium* feature: the effective count is scaled down from this ceiling by
    # available VRAM and measured frame rate (see _effectiveCascades). Set
    # shadow_cascades_adaptive=False to pin the count at shadow_cascades.
    shadow_cascades: int = 4
    shadow_cascades_adaptive: bool = True
    shadow_soft: bool = False

    # Cascade-count control (fps-adaptive) lives in _CascadeControllerMixin; the
    # depth-array / cube-array / cube-map pools + _shadow_caps in _ShadowMapPoolMixin.
    # _ShadowMapPoolMixin.disposeShadowMaps assigns None to this attribute with no
    # class-level annotation, so mypy infers its base type as None; the precise
    # type is declared here (hence the assignment-override ignore).
    _shadow_bindings: Optional[List[dict]] = None  # type: ignore[assignment]

    # Camera-independent caster geometry, cached across frames (R1). The world
    # points and per-caster AABB corners depend only on the casters' transforms
    # and bounding volumes, so they are recomputed only when a caster moves
    # (detected via _casterSignature), not on every camera move.
    _caster_sig: Optional[tuple] = None
    _caster_points_raw: Optional[np.ndarray] = None
    _caster_aabb: Optional[np.ndarray] = None
    #: What each individual caster's geometry came out as, so that one thing
    #: moving does not re-derive the rest. Two frames' worth, turned over by
    #: :meth:`_turnOverCasterGeometry`. See :meth:`_casterWorldGeometry`.
    _caster_geometry_cache: Optional[Dict[tuple, tuple]] = None
    _caster_geometry_previous: Optional[Dict[tuple, tuple]] = None

    # Per-light depth-map reuse (R2). Maps id(light_node) -> the key describing
    # what the light's cached depth map was last rendered from. A spot/point map
    # is camera-independent, so an unchanged key means last frame's depth is still
    # valid and the depth pass can be skipped. Directional maps re-fit to the
    # camera every frame and are never entered here.
    _depth_map_cache: Optional[dict] = None  # type: ignore[assignment]  # base infers None (assigned in disposeShadowMaps); precise type here

    # Depth-pass instance grouping, cached across frames + lights (R5). The
    # group/single partition depends only on the caster set (geometry keys), so a
    # static scene reuses it every frame, and two directional lights that cull to
    # the same occluder set share one build. Keyed on the caster signature (a moved
    # caster invalidates) and the occluder set's path identities (a change in which
    # casters a light sees invalidates). Bounded to a handful of entries.
    _depth_grouping_cache: Optional[dict] = None  # type: ignore[assignment]  # base infers None (assigned in disposeShadowMaps); precise type here

    # -- public hooks ------------------------------------------------------
    def renderShadowMaps(self, toRender: List) -> None:
        """Render depth maps for all shadow-casting lights this frame."""
        self._shadow_bindings = []
        if not self.use_shadows or not toRender:
            return
        # Let geometry opt out of casting shadows (``node.castsShadow = False``) — dense
        # alpha foliage (grass) is expensive to render into every cascade for little
        # visual gain. This keeps the opted-out geometry out of the cascade fit /
        # camera-visible occluder set; the depth-pass caster pool excludes it in
        # _shadowCasterRecords, so it is skipped there too.
        toRender = [r for r in toRender
                    if getattr(r[4][-1], "castsShadow", True)]
        if not toRender:
            return
        shader = self.shader_program
        if shader is None or shader.program is None:
            return

        caps = self._ensureShadowCaps()
        self._applyPerLightShadowSettings(caps)
        shader.use(lit=True)
        # Assign the shadow samplers to distinct units up front: even unused they
        # are active samplers, and leaving the 2D-array/cube samplers aliasing
        # unit 0 (a 2D target) is an illegal draw in the depth pass.
        shader.init_shadow_samplers()
        shader.set_shadow_count(0)  # don't sample stale maps during the depth pass

        camera_view = np.asarray(self.getModelView(), dtype='d')
        camera_proj = np.asarray(self.projection, dtype='d')
        # Fit the cascades to the camera-visible geometry (resolution follows what
        # you can see)...
        occluder_points = self._occluderPoints(toRender)
        if occluder_points is None:
            return
        # ...but the caster POOL must not be limited to the camera frustum: an
        # object behind the camera can still cast a shadow onto visible geometry
        # (walk forward past a column and its shadow must not pop out). Refresh the
        # full renderable set + its camera-independent world geometry (reusing last
        # frame's when nothing moved); per-light _cullOccluders then keeps only the
        # casters in each light's frustum.
        self._refreshCasterData()
        # Spot/point near-far must bound the whole caster pool, not the
        # camera-visible subset: fitting them to occluder_points let a caster
        # outside the camera frustum fall past the near/far planes, so its shadow
        # popped as the camera moved. Fall back to the camera-visible points only
        # if the scene has no bounding volumes at all.
        if self._caster_points is None:
            self._caster_points = occluder_points

        max_slots = min(caps.max_shadow_lights(), shader.MAX_SHADOW_LIGHTS)
        light_index = -1
        slot = 0
        # Save the render target once for the whole batch. The per-map bind()
        # calls no longer save/restore per pass (a glGetIntegerv stall that
        # serialised every cascade/cube-face); we restore once at the end so all
        # the depth passes can pipeline on the GPU.
        saved_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
        saved_viewport = tuple(int(v) for v in glGetIntegerv(GL_VIEWPORT))
        try:
            for path in self.paths.get(nodetypes.Light, ()):
                light_node = path[-1]
                if not getattr(light_node, 'on', True):
                    continue
                light_index += 1
                if light_index >= shader.MAX_LIGHTS:
                    break
                if slot >= max_slots or not self._castsShadow(light_node, caps):
                    continue
                binding = self._renderLight(
                    path, light_node, slot, light_index,
                    camera_view, camera_proj, occluder_points, caps,
                )
                if binding is not None:
                    self._shadow_bindings.append(binding)
                    slot += 1
        finally:
            glBindFramebuffer(GL_FRAMEBUFFER, saved_fbo)
            glViewport(*saved_viewport)

    def bindShadowUniforms(self) -> None:
        """Bind rendered shadow maps onto every shadow-receiving program.

        Call after the lights are set. The lit program *and* the vertex-colour
        program both sample shadows now, so their uniforms are set
        in turn; the depth textures are shared GL state and bind only once.
        """
        shader = self.shader_program
        if shader is None or shader.program is None:
            return
        bindings = self._shadow_bindings or []
        caps = self._shadow_caps
        eye_to_world = np.linalg.inv(np.asarray(self.getModelView(), dtype='d')).astype('f')
        # Shared depth array (spot + CSM) and, when packed, the point cube-array
        # are GL texture state -> bind once for the whole frame.
        if self._shared_array is not None:
            shader.bind_shadow_array(self._shared_array.texture)
        if shader.shadow_cube_array and self._shared_cube_array is not None:
            shader.bind_cube_array(self._shared_cube_array.texture)
        for prog in shader.shadow_receiver_programs():
            shader._shadow_program = prog
            shader._bind_program(prog)
            shader.init_shadow_samplers()
            if not bindings:
                shader.set_shadow_count(0)
                continue
            shader.set_shadow_params(
                resolution=self.shadow_resolution,
                normal_offset=self._normalOffset(),
                soft=self.shadow_soft,
                gather=bool(caps and caps.has_texture_gather),
                light_size=self._lightSize(),
                eye_to_world=eye_to_world,
            )
            for b in bindings:
                if b['kind'] == 'spot':
                    shader.bind_spot_slot(b['slot'], b['light_index'], b['matrix'],
                                          b['bias'])
                elif b['kind'] == 'directional':
                    shader.bind_csm_slot(b['slot'], b['light_index'],
                                         b['matrices'], b['splits'], b['biases'])
                elif b['kind'] == 'point':
                    shader.bind_cube_slot(b['slot'], b['light_index'], b['texture'],
                                          b['light_pos'], b['near'], b['far'],
                                          b['bias'])
            shader.set_shadow_count(len(bindings))
        shader._shadow_program = None
        shader._bind_program(shader.program)

    # -- light dispatch ----------------------------------------------------
    def _renderLight(self, path: Any, light_node: Any, slot: int, light_index: int,
                     camera_view: np.ndarray, camera_proj: np.ndarray,
                     occluder_points: np.ndarray,
                     caps: ShadowCapabilities) -> Optional[dict]:
        # Spot/point fit their near-far to the full caster pool (self._caster_points);
        # only the directional cascades still follow the camera-visible
        # occluder_points.
        if isinstance(light_node, light_module.SpotLight):
            return self._renderSpot(path, light_node, slot, light_index,
                                    camera_view)
        if isinstance(light_node, light_module.DirectionalLight):
            return self._renderDirectional(path, light_node, slot, light_index,
                                           camera_view, camera_proj, occluder_points)
        if isinstance(light_node, light_module.PointLight):
            return self._renderPoint(path, light_node, slot, light_index,
                                     camera_view, caps)
        return None

    def _renderSpot(self, path: Any, light_node: Any, slot: int, light_index: int,
                    camera_view: np.ndarray) -> Optional[dict]:
        raw_transform = path.transformMatrix()
        tmatrix = np.asarray(raw_transform, dtype='d')
        pos = self._world_point(light_node.location, tmatrix)
        if not self._lightInView(pos, light_node):
            return None
        direction = self._world_dir(light_node.direction, tmatrix)
        if direction is None:
            return None
        cutoff = float(getattr(light_node, 'cutOffAngle', 0.785))
        # Fit near/far to the full caster pool, not the camera-visible
        # occluders, so the depth range -- and thus the shadow -- is camera-stable.
        caster_points = self._caster_points
        if caster_points is None:
            return None
        view, proj = self._spotViewProjection(pos, direction, cutoff, caster_points)
        smap = self._shared_map()
        layer = slot * self.shader_program.MAX_CASCADES
        # R2: the spot depth map is camera-independent, so skip the depth pass when
        # the light + casters are unchanged and the texture layer is intact. The
        # binding matrix below still folds in the moving camera every frame.
        if not self._depthMapFresh(light_node, raw_transform, (smap.texture, layer)):
            if not smap.bind_layer(layer, self.shadow_resolution, self._array_layers()):
                return None
            occluders = self._cullOccluders(self._toRender_cache, view, proj)
            try:
                self._renderDepth(occluders, view.astype('f'), proj.astype('f'))
            finally:
                smap.unbind()
            self._markDepthRendered(light_node, raw_transform, (smap.texture, layer))
        matrix = shadowmath.shadow_matrix_eye(camera_view, view, proj)
        return {'kind': 'spot', 'slot': slot, 'light_index': light_index,
                'matrix': matrix,
                'bias': shadowmath.depth_bias_terms(
                    proj, light_depth_bias(light_node), self.shadow_resolution)}

    def _renderDirectional(self, path: Any, light_node: Any, slot: int,
                           light_index: int, camera_view: np.ndarray,
                           camera_proj: np.ndarray,
                           occluder_points: np.ndarray) -> Optional[dict]:
        tmatrix = np.asarray(path.transformMatrix(), dtype='d')
        direction = self._world_dir(light_node.direction, tmatrix)
        if direction is None:
            return None
        # Fit cascades over the visible depth range bounded by the occluders.
        near, far = self._scene_depth_range(camera_view, occluder_points)
        count = max(1, min(self._effectiveCascades(), self.shader_program.MAX_CASCADES))
        splits = shadowmath.cascade_splits(near, far, count)
        smap = self._shared_map()
        base_layer = slot * self.shader_program.MAX_CASCADES
        # Per-caster AABBs of the whole caster pool (not just the camera-visible
        # occluders): each cascade's ortho is fitted to the receiver frustum, so an
        # up-sun caster would be clipped by the near plane and its shadow vanish.
        # Cached across frames + shared by both directional lights (R1); recomputed
        # only when a caster moves.
        caster_bounds = self._caster_aabb
        # Build every cascade's (view, proj) up front, collecting the receiver
        # corners of all cascades.
        cascades = []
        all_corners = []
        prev = near
        for c in range(count):
            far_d = splits[c]
            near_frac = self._depth01(camera_proj, prev)
            far_frac = self._depth01(camera_proj, far_d)
            corners = shadowmath.frustum_corners_world(
                camera_view, camera_proj, near_frac, far_frac)
            view, proj = shadowmath.directional_cascade(
                direction, corners, texel_snap=self.shadow_resolution,
                caster_bounds=caster_bounds)
            cascades.append((view, proj, far_d))
            all_corners.append(corners)
            prev = far_d
        # R3: cull the caster pool ONCE per light instead of once per cascade. An
        # ortho fitted to the union of every cascade's receiver corners bounds all
        # of them (each cascade's volume is a subset), so any caster that shadows
        # any cascade survives this single cull; the survivors are then drawn into
        # each cascade layer (a caster outside a given cascade is clipped by that
        # cascade's own projection, exactly as before -- just without re-scanning
        # all N casters per cascade).
        cull_view, cull_proj = shadowmath.directional_cascade(
            direction, np.concatenate(all_corners, axis=0),
            texel_snap=0, caster_bounds=caster_bounds)
        occluders = self._cullOccluders(self._toRender_cache, cull_view, cull_proj)
        # R4: partition the shared occluder set into instanced groups + singles
        # once, and reuse it for every cascade (each cascade still packs its own
        # light-space modelviews, but the group membership is identical).
        grouping = self._depthGrouping(occluders)
        matrices = []
        cascade_splits = []
        biases = []
        texel_bias = light_depth_bias(light_node)
        for c, (view, proj, far_d) in enumerate(cascades):
            if not smap.bind_layer(base_layer + c, self.shadow_resolution, self._array_layers()):
                return None
            try:
                self._renderDepth(occluders, view, proj, grouping=grouping)
            finally:
                smap.unbind()
            matrices.append(shadowmath.shadow_matrix_eye(camera_view, view, proj))
            cascade_splits.append(far_d)
            # Each cascade fits its own box, so a world bias is a different share
            # of each one's depth range.
            biases.append(shadowmath.depth_bias_terms(
                proj, texel_bias, self.shadow_resolution))
        return {'kind': 'directional', 'slot': slot, 'light_index': light_index,
                'matrices': matrices, 'splits': cascade_splits, 'biases': biases}

    def _renderPoint(self, path: Any, light_node: Any, slot: int, light_index: int,
                     camera_view: np.ndarray,
                     caps: ShadowCapabilities) -> Optional[dict]:
        if not (caps and caps.has_cube_shadow):
            return None
        raw_transform = path.transformMatrix()
        tmatrix = np.asarray(raw_transform, dtype='d')
        pos = self._world_point(light_node.location, tmatrix)
        if not self._lightInView(pos, light_node):
            return None
        # Distances to the full caster pool, not the camera-visible
        # occluders: a caster off-camera still casts into view, and fitting near/far
        # to only the visible subset made its shadow pop as the camera moved.
        d = np.linalg.norm(self._caster_points - pos, axis=1)
        near = max(0.05, float(d.min()) * 0.5)
        far = max(near + 0.1, float(d.max()) * 1.1)
        cube_array = bool(self.shader_program.shadow_cube_array)
        smap = self._cube_array_map() if cube_array else self._map_cube(slot)
        proj = shadowmath.cube_projection(near, far)
        # R2: the whole cube is camera-independent -- reuse every face when the
        # light + casters are unchanged. A cache hit means no caster left any
        # face's frustum, so the "clear every face" invariant still holds from the
        # frame that rendered it.
        if not self._depthMapFresh(light_node, raw_transform, (smap.texture, slot)):
            if self._renderCubeFaces(smap, pos, proj, slot, cube_array) is None:
                return None
            self._markDepthRendered(light_node, raw_transform, (smap.texture, slot))
        # Cube-array slots share one texture (bound once in bindShadowUniforms);
        # the fallback binds this slot's own cube map.
        return {'kind': 'point', 'slot': slot, 'light_index': light_index,
                'texture': None if cube_array else smap.texture,
                'light_pos': tuple(float(x) for x in pos),
                'near': near, 'far': far,
                'bias': shadowmath.depth_bias_terms(
                    proj, light_depth_bias(light_node), self.shadow_cube_resolution)}

    def _renderCubeFaces(self, smap: Any, pos: np.ndarray, proj: np.ndarray,
                         slot: int, cube_array: bool) -> Optional[bool]:
        """Render (and clear) all six faces of a point light's cube depth map.

        Returns True on success, None if a face bind failed (the caller then skips
        the light this frame).
        """
        for face in range(6):
            view = shadowmath.cube_face_view(pos, face)
            # Always bind + clear every face to depth 1.0, even when no caster
            # lies in this face's 90-degree frustum this frame. A receiver samples
            # the cube by the light->fragment direction, which can land on ANY
            # face, so a face left holding undefined depth (first frame, from
            # glTexStorage with no write) or last frame's depth (a caster that has
            # since left this face's frustum) produces phantom shadows that never
            # clear. bind_face() issues the glClear, so binding all six resets
            # them; only the *draw* is skipped when the face has no caster
            #.
            if cube_array:
                ok = smap.bind_face(slot, face, self.shadow_cube_resolution)
            else:
                ok = smap.bind_face(face, self.shadow_cube_resolution)
            if not ok:
                return None
            occluders = self._cullOccluders(self._toRender_cache, view, proj)
            if not occluders:
                continue   # face cleared above; nothing to render into it
            try:
                self._renderDepth(occluders, view, proj)
            finally:
                smap.unbind()
        return True

    # -- teardown ----------------------------------------------------------
    # -- internals ---------------------------------------------------------

    def _lightInView(self, world_pos: np.ndarray, light_node: Any) -> bool:
        """Is the light's sphere of influence inside the camera frustum?

        Directional lights (unbounded range) and lights whose range can't be
        computed are always considered relevant. A light whose influence sphere
        is entirely outside the view frustum contributes nothing visible and is
        skipped, freeing a shadow slot for a light that matters.
        """
        rng = None
        if hasattr(light_node, 'effectiveRange'):
            try:
                rng = light_node.effectiveRange()
            except Exception:
                rng = None
        if rng is None:
            return True
        frust = getattr(self, 'frustum', None)
        planes = getattr(frust, 'planes', None)
        if planes is None:
            return True
        center = np.array([world_pos[0], world_pos[1], world_pos[2], 1.0])
        for plane in planes:
            if float(np.dot(np.asarray(plane, dtype='d'), center)) < -rng:
                return False  # sphere entirely behind this frustum plane
        return True

    def _cullOccluders(self, toRender: List, light_view: np.ndarray,
                       light_proj: np.ndarray) -> List:
        """Keep only occluders whose bounds intersect the light's frustum.

        Shrinks the depth pass: an occluder outside the light frustum cannot cast
        into this shadow map. Falls back to the full list if anything is unsure.
        """
        try:
            mp = dot(np.asarray(light_view, dtype='d'), np.asarray(light_proj, dtype='d'))
            frust = frustum_module.Frustum.fromViewingMatrix(mp.astype('f'), normalize=1)
        except Exception:
            return toRender
        out = []
        for record in toRender:
            bvolume = record[3]
            tmatrix = record[2]
            if bvolume is None:
                out.append(record)
                continue
            try:
                if bvolume.visible(frust, tmatrix.astype('f')):
                    out.append(record)
            except Exception:
                out.append(record)
        return out if out else toRender

    def _castsShadow(self, light_node: Any, caps: ShadowCapabilities) -> bool:
        if not getattr(light_node, 'castShadows', True):
            return False
        if isinstance(light_node, light_module.SpotLight):
            return True
        if isinstance(light_node, light_module.DirectionalLight):
            return True
        if isinstance(light_node, light_module.PointLight):
            return bool(caps.has_cube_shadow)
        return False

    @staticmethod
    def _spotViewProjection(pos: np.ndarray, direction: np.ndarray, cutoff: float,
                            occluder_points: np.ndarray
                            ) -> Tuple[np.ndarray, np.ndarray]:
        """Spot light shadow (view, projection), fitting near/far to occluders.

        Delegates the frustum construction to
        :func:`shadowmath.spot_light_view_projection` so the cone-angle / clamp
        math lives in one place instead of being duplicated here.
        """
        view = shadowmath.look_at_matrix(pos, direction)
        near, far = shadowmath.near_far_from_points(view, occluder_points)
        return shadowmath.spot_light_view_projection(pos, direction, cutoff, near, far)

    def _applyPerLightShadowSettings(self, caps: ShadowCapabilities) -> None:
        """Read the shadow-map resolution the casting lights ask for.

        Applied only before the maps are first allocated, so honouring the field
        never triggers a mid-frame texture realloc; a later resolution change is
        ignored until the pools are disposed. Each light's ``shadowBias`` is read
        where its own map is built instead, since it converts against that map's
        projection.
        """
        casters = [p[-1] for p in self.paths.get(nodetypes.Light, ())
                   if getattr(p[-1], 'on', True) and self._castsShadow(p[-1], caps)]
        resolution = per_light_shadow_resolution(casters, self.shadow_resolution)
        maps_unallocated = (self._shared_array is None
                            and self._shared_cube_array is None
                            and not self._maps_cube)
        if casters and maps_unallocated:
            self.shadow_resolution = resolution
            self.shadow_cube_resolution = max(SHADOW_MIN_RESOLUTION, resolution // 2)

    def _normalOffset(self) -> float:
        # A few shadow-map texels in world units; scales with scene size loosely.
        return SHADOW_NORMAL_OFFSET

    def _lightSize(self) -> float:
        # PCSS penumbra scale (relative light size); larger -> softer shadows.
        return 0.02

    @staticmethod
    def _world_point(local: Any, tmatrix: np.ndarray) -> np.ndarray:
        p = np.array([local[0], local[1], local[2], 1.0])
        world: np.ndarray = p @ tmatrix
        return world[:3]

    @staticmethod
    def _world_dir(local: Any, tmatrix: np.ndarray) -> Optional[np.ndarray]:
        d: np.ndarray = np.array([local[0], local[1], local[2]]) @ tmatrix[:3, :3]
        if float(np.dot(d, d)) < 1e-12:
            return None
        return d

    @staticmethod
    def _depth01(camera_proj: np.ndarray, distance: float) -> float:
        """Window depth (0..1) of an eye-space point ``distance`` in front."""
        clip = np.array([0.0, 0.0, -float(distance), 1.0]) @ np.asarray(camera_proj, dtype='d')
        if abs(clip[3]) < 1e-9:
            return 0.0
        return float(np.clip(0.5 * (clip[2] / clip[3]) + 0.5, 0.0, 1.0))

    def _scene_depth_range(self, camera_view: np.ndarray,
                           occluder_points: np.ndarray) -> Tuple[float, float]:
        """Eye-space near/far distances spanning the occluders (for CSM)."""
        h = np.concatenate([occluder_points, np.ones((occluder_points.shape[0], 1))], axis=1)
        eye = h @ camera_view
        depths = -eye[:, 2]
        near = max(0.1, float(depths.min()))
        far = max(near + 1.0, float(depths.max()))
        return near, far

    def _shadowCasterRecords(self) -> List:
        """Renderable shadow-caster nodes, WITHOUT camera-frustum culling.

        A shadow caster behind the camera still casts into the visible scene, so
        the caster pool must be the whole scene, not the camera-visible render set.
        Geometry that opts out with ``node.castsShadow = False`` (e.g. dense alpha
        foliage) is excluded here, so it is drawn into no depth map -- this is the
        pool the per-light depth pass actually culls from. Each record mirrors the
        render-set tuple shape ``(sortKey, mvmatrix, tmatrix, bvolume, path)``; the
        depth pass and :meth:`_cullOccluders` use only ``tmatrix`` (world transform),
        ``bvolume`` and ``path``, so the first two slots are unused placeholders.
        """
        records = []
        for path in self.paths.get(nodetypes.Rendering, ()):
            node = path[-1]
            if not getattr(node, 'castsShadow', True):
                continue
            try:
                tmatrix = path.transformMatrix()
            except Exception:
                continue
            bvolume = node.boundingVolume(self) if hasattr(node, 'boundingVolume') else None
            records.append((None, None, tmatrix, bvolume, path))
        return records

    @staticmethod
    def _casterSignature(records: List) -> tuple:
        """A cheap change-detector for the caster set.

        ``transformMatrix()`` and ``boundingVolume()`` are dependency-cached, so
        an unmoved caster hands back the *same* matrix and volume objects frame
        after frame. Keying on their identities (plus the caster count) detects a
        moved / added / removed caster without touching the point data, so a
        static scene under a moving camera reuses last frame's world geometry.

        Load-bearing contract: this ``id()`` keying is correct ONLY because
        ``path.transformMatrix()`` and ``node.boundingVolume(mode)`` return the
        SAME object while a node is unmoved and a FRESH object once its transform
        or bound changes (the dependency cache in ``vrml/vrml97/nodepath.py``).
        Every shadow cache keyed on this signature -- the camera-independent caster
        geometry (R1), the per-light depth-map reuse (R2), and the depth-pass
        grouping (R5) -- rides on that identity. Two silent failure modes if those
        methods are ever optimized to break it: reuse a matrix/volume buffer IN
        PLACE on change and the signature never moves, so the shadow maps freeze on
        stale geometry; hand back a fresh wrapper on EVERY call and the signature
        never repeats, so the caches never hit and the depth pass re-runs each
        frame. Neither surfaces as an error, only as a wrong or slow shadow -- keep
        the stable-while-unmoved / fresh-on-change identity intact.
        """
        return tuple((id(r[2]), id(r[3])) for r in records)

    def _refreshCasterData(self) -> List:
        """Rebuild the caster records and (re)derive their camera-independent
        world geometry, reusing the previous frame's world points / AABB corners
        when no caster has moved (R1).

        Sets ``_toRender_cache`` (the caster pool for per-light culling),
        ``_caster_points_raw`` (world points, or None) and ``_caster_aabb``
        (per-caster world AABB corners) for the rest of the shadow pass.
        """
        records = self._shadowCasterRecords()
        self._turnOverCasterGeometry()
        # Reuse hinges on _casterSignature's identity contract: an unmoved caster
        # yields the same signature (skip the rebuild), a moved one a fresh
        # signature (rebuild). See _casterSignature for what breaks it. The
        # signature still gates the *depth maps*, which are per caster set; the
        # world geometry is kept per caster, so one thing moving costs one
        # thing's work rather than the scene's.
        sig = self._casterSignature(records)
        if sig != self._caster_sig:
            self._caster_sig = sig
            self._caster_points_raw, self._caster_aabb = \
                self._casterWorldGeometry(records)
        self._toRender_cache = records
        # Spot/point near-far fitting reads _caster_points; expose the cached
        # value each frame (renderShadowMaps applies the camera-visible fallback
        # if the scene has no bounding volumes at all).
        self._caster_points = self._caster_points_raw
        return records

    def _depthMapFresh(self, light_node: Any, transform: Any,
                       array_key: Any) -> bool:
        """Whether the depth map already stored at ``array_key`` is this light's (R2).

        A spot / point shadow map depends only on the light's world transform and
        the caster set -- both camera-independent -- so an unchanged light over an
        unchanged caster set can reuse the map it last rendered. The cache is keyed
        by the PHYSICAL depth slot (``array_key`` = its texture + layer/slot), not by
        the light: slots are handed out positionally each frame, so a light that
        leaves and re-enters the view can reclaim a layer another light rendered into
        meanwhile. Keying on the slot and recording its owner (this light, its
        transform identity, and the caster signature) means such a reclaim misses and
        re-renders instead of sampling the other light's depth.

        Query only -- it never mutates. The owner is recorded by
        :meth:`_markDepthRendered` *after* a successful render, so a bind/render
        failure leaves the slot unmarked and the next frame re-renders it rather than
        trusting a map that was never drawn.
        """
        if self._depth_map_cache is None:
            self._depth_map_cache = {}
        owner = self._depth_map_cache.get(array_key)
        return owner == (id(light_node), id(transform), self._caster_sig)

    def _markDepthRendered(self, light_node: Any, transform: Any,
                           array_key: Any) -> None:
        """Record that ``array_key``'s depth slot now holds ``light_node``'s map.

        Call only after the depth pass for the slot completed, so a failed render is
        never mistaken for a fresh map (see :meth:`_depthMapFresh`)."""
        if self._depth_map_cache is None:
            self._depth_map_cache = {}
        self._depth_map_cache[array_key] = (id(light_node), id(transform),
                                            self._caster_sig)

    def _occluderPoints(self, toRender: List) -> Optional[np.ndarray]:
        """World points of the camera-visible set, for fitting the cascades.

        Shares the frame's per-caster memo with :meth:`_casterWorldGeometry`:
        this set is a subset of the caster pool, so deriving it separately would
        derive most of the scene twice a frame.
        """
        self._toRender_cache = toRender
        return self._casterWorldGeometry(toRender)[0]

    @staticmethod
    def _casterGeometry(tmatrix: Any, bvolume: Any
                        ) -> Optional[Tuple[np.ndarray, np.ndarray]]:
        """One caster's world points and the eight corners of their AABB.

        Returns ``None`` for a caster that has no bounding volume, or whose
        volume yields no points -- it contributes nothing to a shadow fit.
        """
        if bvolume is None:
            return None
        try:
            pts = bvolume.getPoints()
        except Exception:
            return None
        if pts is None or len(pts) == 0:
            return None
        pts = np.asarray(pts, dtype='d')
        if pts.shape[1] == 3:
            pts = np.concatenate([pts, np.ones((pts.shape[0], 1))], axis=1)
        world = (pts @ np.asarray(tmatrix, dtype='d'))[:, :3]
        lo = world.min(axis=0)
        hi = world.max(axis=0)
        corners = np.asarray([[x, y, z] for x in (lo[0], hi[0])
                              for y in (lo[1], hi[1])
                              for z in (lo[2], hi[2])], dtype='d')
        return world, corners

    @classmethod
    def _worldPointsFromRecords(cls, records: List) -> Optional[np.ndarray]:
        """World-space bounding points of a set of render/caster records.

        Each record is a ``(sortKey, mvmatrix, tmatrix, bvolume, path)`` tuple;
        only ``tmatrix`` and ``bvolume`` are read here.
        """
        chunks = [found[0] for found in
                  (cls._casterGeometry(r[2], r[3]) for r in records)
                  if found is not None]
        if not chunks:
            return None
        return np.concatenate(chunks, axis=0)

    @classmethod
    def _casterWorldAABBCorners(cls, records: List) -> Optional[np.ndarray]:
        """Per-caster world-space AABB corners as a (K,8,3) array.

        One axis-aligned box per caster (not a merged point cloud) so
        :func:`shadowmath._extend_near_for_casters` can test each caster's box
        against a cascade footprint independently.
        """
        boxes = [found[1] for found in
                 (cls._casterGeometry(r[2], r[3]) for r in records)
                 if found is not None]
        if not boxes:
            return None
        return np.asarray(boxes, dtype='d')

    def _casterWorldGeometry(self, records: List
                             ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """``(world points, per-caster AABB corners)``, computed once per caster.

        A caster's world geometry depends on its bounding volume and its world
        transform and on nothing else, and the scenegraph hands both back as the
        *same objects* while that caster is unmoved (the identity contract
        :meth:`_casterSignature` describes). So the answer is kept per caster
        rather than per caster *set*: a game has one car moving through several
        hundred still trees, and re-deriving the trees because the car moved is
        the whole cost of the pass.

        What is kept is this frame's casters and the frame before's -- each entry
        holds the transform and volume it was derived from, so nothing is reused
        for an object that has since been collected and had its address handed to
        another, and a world paging tiles in and out does not accumulate every
        tile it has ever held. :meth:`_refreshCasterData` turns the frame over.
        """
        current = self._caster_geometry_cache
        if current is None:
            current = self._caster_geometry_cache = {}
        previous = self._caster_geometry_previous or {}
        points: List[np.ndarray] = []
        boxes: List[np.ndarray] = []
        for record in records:
            tmatrix, bvolume = record[2], record[3]
            key = (id(tmatrix), id(bvolume))
            entry = current.get(key) or previous.get(key)
            if entry is None:
                found = self._casterGeometry(tmatrix, bvolume)
                if found is None:
                    continue
                entry = (tmatrix, bvolume, found[0], found[1])
            current[key] = entry
            points.append(entry[2])
            boxes.append(entry[3])
        return (np.concatenate(points, axis=0) if points else None,
                np.asarray(boxes, dtype='d') if boxes else None)

    def _turnOverCasterGeometry(self) -> None:
        """Start a fresh frame's memo, keeping the last one as the fallback.

        Two frames' worth is what makes the memo a cache rather than a leak: a
        caster that is still here is copied forward as it is asked for, and one
        that has gone is dropped a frame later.
        """
        self._caster_geometry_previous = self._caster_geometry_cache
        self._caster_geometry_cache = {}

    @staticmethod
    def _lightSpaceModelviews(members: List, light_view: np.ndarray) -> np.ndarray:
        """Per-instance light-space modelviews (tmatrix * light_view), (N,4,4) f32.

        One batched matmul instead of a Python loop of per-member dots, which
        dominated the instanced depth pass on large groups. A member standing for
        a whole placement set contributes one matrix per placement.
        """
        from OpenGLContext.passes.instancing import instance_matrices
        return instance_matrices(members, index=2, after=light_view)

    def _renderDepthGroup(self, group: Any, shader: Any, depth_prog: Any,
                          light_view: np.ndarray) -> None:
        """Write a whole InstanceGroup into the shadow map in one instanced draw.

        The per-instance modelview is in LIGHT space (tmatrix * light_view), so the
        depth shader's instanced branch places each caster correctly. Ids/materials
        are irrelevant to a depth pass, so they pack 0.

        A skinned batch also carries the place each figure's joints start in the
        palette, and the depth program skins from it exactly as the colour one
        does: the shadow is of the pose the body is in, not of the pose it was
        built in.
        """
        from OpenGLContext.passes.instancing import (
            draw_instanced_mesh, instance_counts, instance_joint_bases,
            member_joint_bases,
        )
        modelviews = self._lightSpaceModelviews(group.members, light_view)
        if not len(modelviews):
            return
        bases = instance_joint_bases(self, group)
        # projectionMatrix (light proj) is consumed; modelViewMatrix is ignored
        # under instancing but set for completeness.
        shader.set_matrices(modelviews[0], self.projection, program=depth_prog)
        shader.set_instancing(True, program=depth_prog)
        skinning = getattr(shader, 'set_skinning', None)
        if skinning is not None:
            skinning(0 if bases is not None else None, program=depth_prog,
                     instanced=True)
        try:
            draw_instanced_mesh(
                group.geometry.instanceGPU(self), modelviews,
                [0] * len(modelviews),
                joint_bases=(member_joint_bases(
                    bases, group.members, instance_counts(group.members))
                    if bases is not None else None))
        finally:
            shader.set_instancing(False, program=depth_prog)
            if skinning is not None:
                # The uniform outlives the draw that set it, and the caster
                # after this one -- a batch of crates, a single ground quad --
                # reads a per-instance joint base nothing has bound.
                skinning(None, program=depth_prog)

    def _depthGrouping(self, toRender: List) -> Tuple[List, List]:
        """Partition depth casters into instanced groups + singles (R4).

        Returns ``(groups, singles)``; with instancing disabled every caster is a
        single. The partition depends only on the caster set (geometry keys), not
        the light or cascade, so a directional light's cascades -- which all draw
        the same occluder set -- build it once and share it rather than rebuilding
        it inside each cascade's depth pass.
        """
        if not getattr(self, 'instancing_enabled', False):
            return [], toRender
        # Reuse a previous frame's / other light's partition when the caster set
        # and this light's visible subset are both unchanged (R5). Building the
        # key is O(N) id reads, cheaper than build_instance_groups' per-record
        # geometry/material key + winding computation.
        key = (self._caster_sig, tuple(id(rec[4]) for rec in toRender))
        cache = self._depth_grouping_cache
        if cache is None:
            cache = self._depth_grouping_cache = {}
        hit: Optional[Tuple[List, List]] = cache.get(key)
        if hit is not None:
            return hit
        from OpenGLContext.passes.instancing import build_instance_groups
        result = build_instance_groups(
            list(toRender), min_instances=self.instanceMinimum(),
            key=self._instanceKey, instanceable=self._instanceable)
        # Only a few distinct caster sets exist per frame (one per shadow-casting
        # light); clear rather than grow unbounded if the scene churns.
        if len(cache) >= 8:
            cache.clear()
        cache[key] = result
        return result

    def _renderDepth(self, toRender: List, light_view: np.ndarray,
                     light_proj: np.ndarray,
                     grouping: Optional[Tuple[List, List]] = None) -> None:
        shader = self.shader_program
        # Position-only program: a shadow pass is just a vertex transform + depth
        # write, not the full PBR fragment shader (which ran ~22x per frame here).
        depth_prog = shader.use_depth()
        saved = (self.matrix, self.projection, self.shadow_pass)
        self.shadow_pass = True
        self.projection = np.asarray(light_proj, dtype='f')
        light_view = np.asarray(light_view, dtype='f')

        caps = self._shadow_caps
        depth_clamp = bool(caps and caps.has_depth_clamp)
        if depth_clamp:
            glEnable(GL_DEPTH_CLAMP)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(SHADOW_POLYGON_OFFSET_FACTOR, SHADOW_POLYGON_OFFSET_UNITS)
        # Don't force front-face culling here: it dropped
        # shadows from open / single-sided casters (a ground quad, a leaf card)
        # and over-stacked with the polygon + normal offsets into peter-panning.
        # Disable culling so every caster writes depth; the geometry nodes still
        # honour their own ``solid`` flag. Save and restore the caller's exact
        # cull state instead of hardcoding GL_BACK.
        saved_cull_enabled = bool(glIsEnabled(GL_CULL_FACE))
        saved_cull_mode = int(glGetIntegerv(GL_CULL_FACE_MODE))
        glDisable(GL_CULL_FACE)
        try:
            # Instance the depth pass too: without this an instanced scene draws
            # its color pass in one call but re-draws every caster per-shape into
            # each shadow map (N casters * cascades), which dominates the frame.
            # The group/single partition is caster-set-only, so callers that render
            # the same set into several layers (directional cascades) pass a
            # precomputed grouping; otherwise build it here.
            if grouping is None:
                grouping = self._depthGrouping(toRender)
            groups, casters = grouping
            for group in groups:
                try:
                    shader.use_depth()
                    self._renderDepthGroup(group, shader, depth_prog, light_view)
                except Exception as err:
                    log.debug("instanced shadow depth failure: %s", err)
            for record in casters:
                tmatrix = record[2]
                path = record[4]
                self.matrix = dot(tmatrix, light_view).astype('f')
                # A caster binds whatever program it draws through -- a line set
                # draws through the unlit one and leaves it bound -- so the depth
                # program is bound here rather than assumed to have survived the
                # caster before. A uniform location resolved against one program
                # and uploaded into another writes into whatever sits at that
                # location, and raises where nothing does.
                shader.use_depth()
                shader.set_matrices(self.matrix, self.projection, program=depth_prog)
                try:
                    path[-1].Render(mode=self)
                except Exception as err:
                    log.debug("shadow depth render failure: %s", err)
        finally:
            glCullFace(saved_cull_mode)
            if saved_cull_enabled:
                glEnable(GL_CULL_FACE)
            else:
                glDisable(GL_CULL_FACE)
            glDisable(GL_POLYGON_OFFSET_FILL)
            if depth_clamp:
                glDisable(GL_DEPTH_CLAMP)
            self.matrix, self.projection, self.shadow_pass = saved
