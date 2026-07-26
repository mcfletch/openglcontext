"""Environment and effects phases for the FlatPass shader render loop.

Four cohesive rendering concerns that ``FlatPass.Render()`` sequences:
image-based lighting, KHR transmission (glass), the HDR bloom wrap, and
frustum/cluster visibility culling. Holding them in ``_FlatEffectsMixin`` keeps
``Render`` a thin phase list and each concern in one place. The mixin is composed
into ``FlatPass``, so ``self`` is the pass and every ``self.matrix`` /
``self.shader_program`` / ``self._writeShapeId`` reference resolves through the
combined class.
"""
from __future__ import annotations

import os
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np
from OpenGL.GL import (
    glEnable, glDisable, glBlendFunc, glDepthMask,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
)

from OpenGLContext import renderoptions
from OpenGLContext.debug.logs import getTraceback

if TYPE_CHECKING:
    from OpenGLContext.passes.bloom import BloomPass
    from OpenGLContext.passes.ibl import IBLController, IBLProbe
    from OpenGLContext.passes.transmission import TransmissionBuffer

log = logging.getLogger(__name__)


class _FlatEffectsMixin:
    """IBL + transmission + bloom + visibility culling phases for FlatPass."""

    if TYPE_CHECKING:
        shader_program: Any
        _gl_renderer: str
        context: Any
        matrix: Any
        projection: Any
        viewport: Any
        frustum: Any
        renderPath: Any
        transparent: bool

        def _writeShapeId(self, shader: Any, path: Any, prog: Any,
                          id_map: Optional[Dict]) -> Any: ...

        def _restoreShapeId(self, masked: Any) -> None: ...

    # Transmission (KHR_materials_transmission). Filled on the first frame from the
    # GL renderer string; 'full' captures an opaque backdrop, 'blend' fakes it.
    _transmission_mode: Optional[str] = None
    _transmission_buffer: Optional["TransmissionBuffer"] = None

    # Image-based lighting (environment reflection for metals). Resolved once from
    # the GL renderer; the probe is built lazily on the first 'full' frame.
    _ibl_controller: Optional["IBLController"] = None
    _ibl_probe: Optional["IBLProbe"] = None

    # Cluster-cull the per-object frustum test when there are at least this many
    # records and OPENGLCONTEXT_INSTANCE_CLUSTER_CULL is set. The per-object test
    # below is pure Python (no frustcullaccel here), so its O(N) cost dominates
    # huge static fields; cluster culling replaces most per-instance tests with a
    # handful of per-cluster ones (see passes/instancing.cluster_cull).
    CLUSTER_CULL_MIN = 256
    CLUSTER_CULL_SIZE = 64

    _bloom_pass: Optional["BloomPass"] = None
    _bloom_active = False

    # -- image-based lighting ----------------------------------------------
    def iblSetup(self, matrix: Any) -> str:
        """Bind the environment-lighting path onto the PBR program for this frame.

        Resolves the effective IBL mode (with fps-adaptive degradation), builds the
        probe lazily when 'full', binds probe textures + the world-space transform,
        and sets ``iblMode``. No-op unless the bound program is the PBR program.
        Returns the effective mode string.
        """
        shader = self.shader_program
        if shader is None or not hasattr(shader, 'set_ibl_mode'):
            return 'off'
        from OpenGLContext.passes import ibl
        if self._ibl_controller is None:
            requested = renderoptions.choice(self, 'ibl', 'auto')
            base = ibl.resolve_ibl_mode(self._gl_renderer, requested=requested)
            self._ibl_controller = ibl.IBLController(
                base, adaptive=ibl.ibl_is_adaptive(requested))
        fc = getattr(getattr(self, 'context', None), 'frameCounter', None)
        fps = fc.recentFps() if fc is not None else 0.0
        mode = self._ibl_controller.effective_mode(fps)

        probe = None
        if mode == 'full':
            if self._ibl_probe is None:
                self._ibl_probe = ibl.IBLProbe()
            if self._ibl_probe.ensure_built():   # builds with its own programs bound
                probe = self._ibl_probe
            else:
                mode = 'analytic'                # build failed -> degrade this frame

        # eyeToWorld is uploaded with glUniformMatrix4fv, which targets the bound
        # program; the probe build leaves no program bound, so bind the lit PBR
        # program before setting matrix/probe uniforms.
        shader.use(lit=True)
        if probe is not None:
            probe.bind(shader)
        # The env probe is world-oriented; the shader samples it via eyeToWorld,
        # which is otherwise only set when shadows are on. Set it here too.
        if mode != 'off':
            eye_to_world = np.linalg.inv(np.asarray(matrix, dtype='d')).astype('f')
            shader.set_eye_to_world(eye_to_world)
        # ContextDefinition.iblIntensity scales the (un-shadowed) ambient /
        # environment term. Below 1.0 a shadow-casting key light reads clearly
        # instead of being lifted by full-strength ambient. 1.0 = unchanged.
        ibl_scale = float(renderoptions.number(
            self, 'iblIntensity',
            renderoptions.env_number('OPENGLCONTEXT_IBL_INTENSITY', 1.0)))
        shader.set_ibl_mode(ibl.MODE_CODE[mode], ibl_scale)
        # Camera exposure (1.0 unless a glTF scene with absolute-unit punctual lights
        # set a light-meter value on the context). Default keeps every other scene
        # -- VRML, IBL-lit demos, the blessed baselines -- pixel-identical.
        if hasattr(shader, 'set_exposure'):
            shader.set_exposure(
                float(getattr(getattr(self, 'context', None), 'gltf_exposure', 1.0)))
        # Aerial-perspective fog. A context sets gltf_fog = (density, (r,g,b)); the
        # default (0.0) leaves every other scene pixel-identical.
        if hasattr(shader, 'set_fog'):
            fog = getattr(getattr(self, 'context', None), 'gltf_fog', None)
            if fog:
                shader.set_fog(fog[0], fog[1])
            else:
                shader.set_fog(0.0)
        # Bloom: the scene renders into a linear HDR target, so the PBR shader emits
        # linear HDR (tone-mapping moves to the bloom composite). Off by default.
        if hasattr(shader, 'set_hdr_output'):
            shader.set_hdr_output(bool(getattr(self, '_bloom_active', False)))
        return mode

    # -- transmission (KHR_materials_transmission) --------------------------
    def transmissionMode(self) -> str:
        """Resolve the transmission path once, from the GL renderer string.

        Only the PBR program implements transmission; other shader programs stay
        'off'. See :func:`OpenGLContext.passes.transmission.resolve_mode`.
        """
        if self._transmission_mode is None:
            requested = renderoptions.choice(self, 'transmission', 'auto')
            shader = None if requested == 'off' else self.shader_program
            if requested == 'off':
                self._transmission_mode = 'off'
            elif shader is not None and hasattr(shader, 'set_transmission'):
                from OpenGLContext.passes.transmission import resolve_mode
                self._transmission_mode = resolve_mode(self._gl_renderer,
                                                       requested=requested)
            else:
                self._transmission_mode = 'off'
        return self._transmission_mode

    def transmissiveRecords(self, toRender: List) -> set:
        """Indices of opaque records whose material has transmission > 0."""
        out = set()
        for i, rec in enumerate(toRender):
            if rec[0][0]:
                continue  # already routed to the blended pass
            shape = rec[4][-1]
            appearance = getattr(shape, 'appearance', None)
            material = getattr(appearance, 'material', None)
            if material is not None and getattr(material, 'transmission', 0.0) > 0.0:
                out.add(i)
        return out

    def shaderRenderTransmissive(self, toRender: List, indices: set,
                                 id_map: Optional[Dict] = None) -> None:
        """Draw transmissive (glass) shapes after the opaque backdrop is ready.

        'full': capture the opaque colour buffer to a mipmapped texture, then draw
        each shape sampling it at the refracted screen position (back-to-front so
        overlapping glass composits sensibly). 'blend': the shapes are drawn as
        alpha-blended surfaces by shaderRenderTransparent-style state; here we just
        run the same draw with blending on and no backdrop.
        """
        mode = self.transmissionMode()
        if not indices or mode == 'off':
            return

        records = [(i, toRender[i]) for i in indices]
        # back-to-front: eye looks down -z, so ascending eye-space origin z.
        records.sort(key=lambda ir: ir[1][1][3][2])

        shader = self.shader_program
        shader._pick_active = id_map is not None
        shader.transmission_mode = mode
        shader.use(lit=True)
        # Transmissive shapes reconfigure under the new transmission mode.
        reset = getattr(shader, 'reset_appearance_cache', None)
        if reset is not None:
            reset()
        prog = shader.program

        buffer = None
        if mode == 'full':
            from OpenGLContext.passes.transmission import TransmissionBuffer
            vp = self.context.getViewPort()
            if self._transmission_buffer is None:
                self._transmission_buffer = TransmissionBuffer()
            buffer = self._transmission_buffer
            buffer.ensure_size(int(vp[0]), int(vp[1]))
            buffer.capture()                 # copies the just-drawn opaque scene
            shader.bind_transmission_backdrop(buffer)
        else:  # blend fallback
            glEnable(GL_BLEND)
            if id_map is not None:
                from OpenGLContext.passes._flat import disable_object_id_blend
                disable_object_id_blend()   # don't blend the picking id (4.6)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(0)

        self.transparent = (mode == 'blend')
        debugFrustum = self.context.contextDefinition.debugBBox
        try:
            for _obj_index, (_key, mvmatrix, _tmatrix, bvolume, path) in records:
                self.matrix = mvmatrix
                self.renderPath = path
                shader.set_matrices(mvmatrix, self.projection, program=prog)
                masked = self._writeShapeId(shader, path, prog, id_map)
                try:
                    if mode == 'blend':
                        path[-1].RenderTransparent(mode=self)
                    else:
                        path[-1].Render(mode=self)
                    if debugFrustum and bvolume:
                        bvolume.debugRender()
                except Exception as err:
                    log.error("Failure in shader transmissive render: %s",
                              getTraceback(err))
                finally:
                    self._restoreShapeId(masked)
        finally:
            self.transparent = False
            shader.transmission_mode = 'off'
            if mode == 'full':
                shader.clear_transmission_backdrop()
            else:
                glDisable(GL_BLEND)
                glDepthMask(1)
            shader.unuse()

    # -- visibility culling ------------------------------------------------
    def _cluster_cull_enabled(self) -> bool:
        return os.environ.get('OPENGLCONTEXT_INSTANCE_CLUSTER_CULL', '').strip().lower() \
            in ('1', 'true', 'yes', 'on')

    def frustumVisibilityFilter(self, records: List) -> List:
        """Filter records for visibility using frustum planes

        This does per-object culling based on frustum lookups
        rather than object query values.  It should be fast
        *if* the frustcullaccel module is available, if not
        it will be dog-slow.
        """
        if self._cluster_cull_enabled() and len(records) >= self.CLUSTER_CULL_MIN:
            try:
                return self._clusterFrustumFilter(records)
            except Exception as err:
                log.error("Cluster cull failed, falling back to per-object: %s",
                          getTraceback(err))
        result = []
        for record in records:
            (key,mv,tm,bv,path) = record
            if bv is not None:
                visible = bv.visible(
                    self.frustum, tm.astype('f'),
                    occlusion=False,
                    mode=self
                )
                if visible:
                    result.append( record )
            else:
                result.append( record )
        return result

    def _clusterFrustumFilter(self, records: List) -> List:
        """Cluster-accelerated equivalent of frustumVisibilityFilter.

        Spatially clusters the records by world translation and tests each
        cluster's (padded) AABB against the frustum once; only records in a
        possibly-visible cluster pay the exact per-instance test, so a cluster
        wholly outside the frustum is skipped with no per-instance work. The
        cluster AABB is padded by the largest member world bounding radius, so it
        can never reject a cluster that has a visible member -- the result is
        identical to the per-object filter, just cheaper.
        """
        from OpenGLContext.passes.instancing import cluster_cull
        from OpenGLContext.scenegraph import boundingvolume

        cullable = [r for r in records if r[3] is not None]
        forced = [r for r in records if r[3] is None]
        if not cullable:
            return records

        positions = np.empty((len(cullable), 3), 'f')
        max_radius = 0.0
        for i, (_key, _mv, tm, bv, _path) in enumerate(cullable):
            tm = np.asarray(tm, 'f')
            positions[i] = tm[3][:3]
            scale = max(float(np.linalg.norm(tm[j][:3])) for j in range(3))
            size = np.asarray(getattr(bv, 'size', (1.0, 1.0, 1.0)), 'f')
            max_radius = max(max_radius, 0.5 * float(np.linalg.norm(size)) * scale)

        ident = np.eye(4, dtype='f')
        R = max_radius

        def cluster_visible(mn: np.ndarray, mx: np.ndarray) -> bool:
            center = ((mn + mx) * 0.5).tolist()
            size = (mx - mn + 2.0 * R).tolist()
            aabb = boundingvolume.AABoundingBox(center=center, size=size)
            return bool(aabb.visible(self.frustum, ident, occlusion=False, mode=self))

        def instance_visible(rec: Any) -> bool:
            return bool(rec[3].visible(self.frustum, np.asarray(rec[2], 'f'),
                                       occlusion=False, mode=self))

        kept = cluster_cull(cullable, positions, cluster_visible, instance_visible,
                            cluster_size=self.CLUSTER_CULL_SIZE)
        return forced + kept

    # -- HDR bloom wrap ----------------------------------------------------
    def _begin_bloom(self) -> bool:
        """Start rendering into the HDR bloom target, if bloom is enabled. The scene
        renders to a linear HDR FBO; _end_bloom composites the glow back to screen."""
        from OpenGLContext.passes import bloom
        if not bloom.bloom_enabled(self):
            self._bloom_active = False
            return False
        w, h = int(self.viewport[2]), int(self.viewport[3])
        if not w or not h:
            self._bloom_active = False
            return False
        try:
            if self._bloom_pass is None:
                self._bloom_pass = bloom.BloomPass()
            self._bloom_pass.begin(w, h)
            self._bloom_active = True
            return True
        except Exception:
            self._bloom_active = False
            return False

    def _end_bloom(self) -> None:
        try:
            assert self._bloom_pass is not None
            self._bloom_pass.composite()
        except Exception:
            pass
        self._bloom_active = False
