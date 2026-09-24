"""Environment and effects phases for the FlatPass shader render loop.

Five cohesive rendering concerns that ``FlatPass.Render()`` sequences:
image-based lighting, KHR transmission (glass), planar reflections of the
scene, the HDR bloom wrap, and frustum/cluster visibility culling. Holding them in ``_FlatEffectsMixin`` keeps
``Render`` a thin phase list and each concern in one place. The mixin is composed
into ``FlatPass``, so ``self`` is the pass and every ``self.matrix`` /
``self.shader_program`` / ``self._writeShapeId`` reference resolves through the
combined class.
"""
from __future__ import annotations

import contextlib
import os
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np
from OpenGL.GL import (
    glEnable, glDisable, glBlendFunc, glDepthMask,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA,
)

from OpenGLContext import renderoptions
from OpenGLContext.debug.logs import getTraceback
from OpenGLContext.scenegraph import fog as fognode

if TYPE_CHECKING:
    from OpenGLContext.passes.bloom import BloomPass
    from OpenGLContext.passes.ibl import IBLController, IBLProbe
    from OpenGLContext.passes.gputimer import GpuTimer
    from OpenGLContext.passes.reflectionatlas import ReflectionAtlas
    from OpenGLContext.passes.reflectionplanner import Lookup, ReflectionPlanner
    from OpenGLContext.passes.reflectiontiles import Budget
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

        def _writeShapeId(self, shader: Any, path: Any, node: Any, prog: Any,
                          id_map: Optional[Dict]) -> Any: ...

        def _restoreShapeId(self, masked: Any) -> None: ...

        def applyLightGrid(self, shader: Any, node: Any, tmatrix: Any,
                           bvolume: Any, program: Any = None) -> None: ...

        def currentFog(self) -> Any: ...

        visiblePlacements: Optional[Dict[int, Any]]

        def applyViewFrame(self, frame: Any, gl: bool = True) -> None: ...

        def renderSet(self, matrix: Any, gathered: Any = None) -> List[Any]: ...

        def setupViewLighting(self, matrix: Any, lighting: Any,
                              fitted: bool = False) -> None: ...

        def shaderRenderOpaque(self, toRender: List, id_map: Optional[Dict] = None,
                               skip: Optional[set] = None) -> None: ...

        def sharesViews(self, frames: Any) -> bool: ...

        def sharesDraw(self, record: Any) -> bool: ...

        def chooseMultiview(self) -> str: ...

        def renderShared(self, frames: Any, id_map: Optional[Dict],
                         lighting: Any = None, mirrored: bool = False) -> Optional[set]: ...

        multiviewStrategy: Optional[str]
        activeFrame: Any
        view: Any
        stats: Any
        _scissorViews: bool

    # Transmission (KHR_materials_transmission). Filled on the first frame from the
    # GL renderer string; 'full' captures an opaque backdrop, 'blend' fakes it.
    _transmission_mode: Optional[str] = None
    _transmission_buffer: Optional["TransmissionBuffer"] = None

    # Planar reflections: whether the program can read them, settled once,
    # and what draws and holds them.
    _planar_reflections: Optional[bool] = None
    _reflection_atlas: Optional["ReflectionAtlas"] = None
    _reflection_planner: Optional["ReflectionPlanner"] = None
    _reflection_timer: Optional["GpuTimer"] = None
    #: What each mirror in each view reads this frame, by
    #: :func:`~OpenGLContext.passes.reflectionplanner.key_for`.
    _reflection_lookups: Dict[Any, "Lookup"] = {}
    #: What each mirror read the frame before: what a mirror seen in a mirror
    #: view reads, from the copy of the atlas that frame left.
    _previous_lookups: Dict[Any, "Lookup"] = {}
    #: The mirror views this frame drew with a mirror left out of them.
    _incompleteMirrors: set = set()
    #: The lookup the program was last given, so a run of shapes that are
    #: not mirrors sets nothing.
    _reflection_applied: Any = None
    #: True while a draw is made in an unmirrored camera's eye space for
    #: views that are mirrored, which turns every triangle's winding over
    #: without the modelview's determinant saying so.
    mirroredDraw = False

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
    #: Whether this pass's colour can be composited through the HDR bloom
    #: chain: its shaders write linear HDR while bloom is on. A pass whose
    #: output is already display-referred says False and draws straight to
    #: the framebuffer.
    supports_bloom = True

    # -- image-based lighting ----------------------------------------------
    def iblPrepare(self) -> Tuple[str, Optional["IBLProbe"]]:
        """This frame's environment-lighting mode, and the probe when it is 'full'.

        Resolves the effective IBL mode (with fps-adaptive degradation) and
        builds the probe the first time 'full' is asked for. The build renders
        offscreen, so a frame of several views asks here once, before any view
        confines drawing to its rectangle, and hands the answer to each view's
        :meth:`iblSetup`.
        """
        shader = self.shader_program
        if shader is None or not hasattr(shader, 'set_ibl_mode'):
            return 'off', None
        from OpenGLContext.passes import ibl
        if self._ibl_controller is None:
            requested = renderoptions.choice(self, 'ibl', 'auto')
            base = ibl.resolve_ibl_mode(self._gl_renderer, requested=requested)
            self._ibl_controller = ibl.IBLController(
                base, adaptive=ibl.ibl_is_adaptive(
                    requested,
                    capturing=bool(getattr(getattr(self, 'context', None),
                                           'renderingForCapture', False))))
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
        return mode, probe

    def iblSetup(self, matrix: Any,
                 prepared: Optional[Tuple[str, Optional["IBLProbe"]]] = None) -> str:
        """Bind the environment-lighting path onto the PBR program for one view.

        ``prepared`` is this frame's :meth:`iblPrepare`, asked for here where
        it is not given. Binds the probe textures and the camera's eye-to-world
        transform, and sets ``iblMode``. No-op unless the bound program is the
        PBR program. Returns the effective mode string.
        """
        shader = self.shader_program
        if shader is None or not hasattr(shader, 'set_ibl_mode'):
            return 'off'
        from OpenGLContext.passes import ibl
        mode, probe = prepared if prepared is not None else self.iblPrepare()

        # eyeToWorld is uploaded with glUniformMatrix4fv, which targets the bound
        # program; the probe build leaves no program bound, so bind the lit PBR
        # program before setting matrix/probe uniforms.
        shader.use(lit=True)
        if probe is not None:
            probe.bind(shader)
        # Where the camera is in the world, which is what turns an eye-space
        # normal into a world-space one. Uploaded every frame rather than only
        # for the paths that were the first to want it: the env probe is
        # world-oriented, so are the shadow cascades, and so is the baked
        # irradiance grid, and a uniform that is right only when some other
        # feature happens to be switched on is a trap for the next one.
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
        # Fog, from the bound Fog node the pass has already collected. A scene
        # with none is left pixel-identical, which is nearly every scene.
        if hasattr(shader, 'set_fog'):
            self.applyFog(shader)
        # Bloom: the scene renders into a linear HDR target, so the PBR shader emits
        # linear HDR (tone-mapping moves to the bloom composite). Off by default.
        if hasattr(shader, 'set_hdr_output'):
            shader.set_hdr_output(bool(getattr(self, '_bloom_active', False)))
        return mode

    def applyFog(self, shader: Any) -> None:
        """Hand the shader the fog the camera is standing in, or none.

        The node's own accumulated matrix decides the scale of its
        ``visibilityRange``, so a fog authored for a model carries its range
        with it when the model is placed at a different size.
        """
        path = self.currentFog()
        if path is None:
            shader.set_fog(0.0, mode=fognode.FOG_NONE)
            return
        mode, density, color = path[-1].fogParameters(path.transformMatrix())
        shader.set_fog(density, color, mode=mode)

    # -- planar reflections --------------------------------------------------
    def planarReflectionsEnabled(self) -> bool:
        """Whether mirrors and water reflect the scene this frame.

        ``ContextDefinition.planarReflections`` asks for it, read every frame
        so a settings screen switching it takes effect on the next one; and
        the PBR program has to have compiled it in, which is settled once: a
        driver without the texture unit it reads leaves every reflector
        reflecting the environment probe.
        """
        if self._planar_reflections is None:
            self._planar_reflections = bool(getattr(
                self.shader_program, 'planar_reflection_supported', False))
        return self._planar_reflections and renderoptions.flag(
            self, 'planarReflections',
            renderoptions.env_flag_once('OPENGLCONTEXT_PLANAR_REFLECTIONS', True))

    def reflectionBudget(self) -> "Budget":
        """The most this frame's reflections may cost, from the definition.

        ``reflectionViews`` of 0 takes the strategy's own: sixteen mirror
        views where one submission reaches them all, two where each is a draw
        of the scene. Settles the multi-view strategy where nothing has yet.
        """
        from OpenGLContext.multiview.strategy import MultiviewCapabilities
        from OpenGLContext.passes.reflectiontiles import Budget
        if self.multiviewStrategy is None:
            self.multiviewStrategy = self.chooseMultiview()
        strategy = self.multiviewStrategy
        views = int(renderoptions.number(self, 'reflectionViews', renderoptions.env_number_once(
            'OPENGLCONTEXT_REFLECTION_VIEWS', 0, integer=True)))
        if views <= 0:
            views = (MultiviewCapabilities.detect().max_views
                     if strategy in ('vertex', 'geometry') else 2)
        from OpenGLContext.passes.reflectionatlas import FILL
        width, height = self.reflectionAtlasSize()
        return Budget(views=views,
                      separate_views=int(renderoptions.number(
                          self, 'reflectionSeparateViews', renderoptions.env_number_once(
                              'OPENGLCONTEXT_REFLECTION_SEPARATE_VIEWS', 4, integer=True))),
                      texels=int(width * height * FILL))

    def reflectionAtlasSize(self) -> Tuple[int, int]:
        """The reflection atlas's size in texels, for this window."""
        from OpenGLContext.passes.reflectionatlas import atlas_size
        width, height = self.context.getViewPort()
        return atlas_size(int(width), int(height), self.reflectionShare())

    def reflectionShare(self) -> float:
        """The atlas's share of the window's pixels."""
        return max(0.05, float(renderoptions.number(
            self, 'reflectionAtlas',
            renderoptions.env_number_once('OPENGLCONTEXT_REFLECTION_ATLAS', 0.5))))

    def renderReflections(self, frames: List[Any], lighting: Any = None) -> None:
        """Draw this frame's reflections into the atlas, for the mirrors to read.

        :class:`~OpenGLContext.passes.reflectionplanner.ReflectionPlanner`
        says which mirror views to draw and where; each is culled from the
        frame's walk through its own camera, and they are drawn together:
        what can serve several views in one shared submission, the rest a
        view at a time. The views' own camera is looked through again
        afterwards.
        """
        previous = self._reflection_lookups
        self._previous_lookups = {}
        self._reflection_lookups = {}
        self._reflection_applied = None
        if not self.planarReflectionsEnabled():
            return
        gathered = getattr(self, '_frameGather', None)
        if gathered is None:
            return
        from OpenGLContext.passes.reflectionatlas import ReflectionAtlas
        from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
        if self._reflection_planner is None:
            self._reflection_planner = ReflectionPlanner()
        planner = self._reflection_planner
        target = float(renderoptions.number(
            self, 'reflectionMilliseconds',
            renderoptions.env_number_once('OPENGLCONTEXT_REFLECTION_MS', 0.0)))
        timer = self._reflection_timer
        if target > 0.0 and timer is not None and timer.milliseconds is not None:
            planner.schedule.measured(timer.milliseconds, target)
        size = self.reflectionAtlasSize()
        plan = planner.plan(frames, size, self.reflectionBudget,
                            separate=self._separateShapes)
        self._reflection_lookups = plan.lookups
        self._incompleteMirrors = set()
        if plan.unfinished:
            # A context that draws only when something changes would otherwise
            # leave a still scene showing reflections drawn while the pass was
            # settling, or none, until something else asked for a frame.
            trigger = getattr(self.context, 'triggerRedraw', None)
            if trigger is not None:
                trigger(0)
        if not plan.lookups:
            return
        atlas = self._reflection_atlas
        if atlas is None:
            atlas = self._reflection_atlas = ReflectionAtlas()
        if atlas.ensure_size(*size):
            # A new atlas holds nothing any tile says it does.
            previous = {}
            if not plan.draws:
                planner.reset()
                self._reflection_lookups = {}
                return
        # Only what was drawn once the pass settled is passed on to another
        # mirror: a picture from those first frames is not one to keep.
        self._previous_lookups = {key: lookup for key, lookup in previous.items()
                                  if not lookup.provisional}
        if plan.draws:
            from OpenGLContext.passes.gputimer import GpuTimer
            if timer is None:
                timer = self._reflection_timer = GpuTimer()
            trace = getattr(self.context, 'loopTrace', None)
            with (trace.phase('reflections') if trace is not None
                  else contextlib.nullcontext()):
                timer.begin()
                try:
                    self._drawMirrorViews(plan, lighting, gathered, atlas)
                finally:
                    timer.end()
        if self._incompleteMirrors:
            # Each is drawn again next frame, when the mirror it left out has
            # a reflection of its own to show.
            planner.redo(self._incompleteMirrors)
            trigger = getattr(self.context, 'triggerRedraw', None)
            if trigger is not None:
                trigger(0)
        self.stats.mirrorViews = len(plan.draws)
        self.stats.mirrorTexels = plan.texels
        self.stats.mirrorMilliseconds = None if timer is None else timer.milliseconds
        atlas.bind()
        from OpenGLContext.passes.reflectionatlas import LEVELS
        shader = self.shader_program
        shader.use(lit=True)
        shader.set_planar_levels(LEVELS - 1 if atlas.mipmapped else 0)

    def _separateShapes(self, frame: Any) -> bool:
        """Whether a view's mirrors would draw shapes a shared draw refuses."""
        from OpenGLContext.passes.reflection import is_reflector
        return any(not record[0][0] and not is_reflector(record)
                   and not self.sharesDraw(record) for record in frame.toRender)

    def mirrorFrames(self, plan: Any, gathered: Any) -> List[Any]:
        """A :class:`~OpenGLContext.multiview.strategy.ViewFrame` per mirror view.

        Each is the mirror's camera, drawing into its tile, with what that
        camera's frustum keeps of the frame's walk: opaque, and large enough
        to cover two texels of the tile. A mirror in it shows the reflection
        it had the frame before. One in view that had none yet is left out,
        and the view noted in :attr:`_incompleteMirrors` to be drawn again once
        it has; one no view shows has no reflection of its own and reflects
        the environment probe.
        """
        from OpenGLContext import frustum
        from OpenGLContext.multiview.strategy import ViewFrame
        from OpenGLContext.passes.reflection import fov, is_reflector, too_small
        mirrors = []
        self._incompleteMirrors = set()
        earlier = self._previous_lookups
        coming = {candidate.key for candidate in plan.candidates}
        for draw in plan.draws:
            mirror = draw.mirror
            modelproj = mirror.modelproj
            frame = ViewFrame(
                draw.frame.view, draw.frame.camera, draw.tile.rect,
                mirror.modelView, mirror.projection, modelproj,
                frustum.Frustum.fromViewingMatrix(modelproj, normalize=1),
                fitted=False)
            self.applyViewFrame(frame, gl=False)
            texels = draw.tile.height / max(
                (mirror.crop[3] - mirror.crop[1]) / 2.0 * fov(draw.frame.projection),
                1e-6)
            eye = np.linalg.inv(np.asarray(mirror.modelView, 'd'))[3, :3]
            kept = []
            for record in self.renderSet(mirror.modelView, gathered):
                if record[0][0] or too_small(record, eye, texels):
                    continue
                if is_reflector(record):
                    if record[4] is draw.record[4]:
                        continue
                    key = (id(frame.view), id(record[4]))
                    if key not in earlier and key in coming:
                        self._incompleteMirrors.add(draw.key)
                        continue
                kept.append(record)
            frame.toRender = kept
            frame.visiblePlacements = self.visiblePlacements or {}
            mirrors.append(frame)
        return mirrors

    def _drawMirrorViews(self, plan: Any, lighting: Any, gathered: Any,
                         atlas: "ReflectionAtlas") -> None:
        """Draw every mirror view of ``plan`` into its tile of ``atlas``."""
        from OpenGL.GL import (
            glDisable, glFrontFace, glScissor, glViewport,
            GL_CCW, GL_CW, GL_SCISSOR_TEST,
        )
        from OpenGLContext.multiview.strategy import MultiviewCapabilities
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        from OpenGLContext.passes.reflection import is_reflector
        shader = self.shader_program
        active = self.activeFrame
        mirrors = self.mirrorFrames(plan, gathered)
        # A mirror seen in a mirror view reads the reflection it had the frame
        # before, from a copy: the atlas itself is being drawn into.
        bounce = any(is_reflector(record) for frame in mirrors
                     for record in frame.toRender)
        if bounce:
            atlas.keep()
            atlas.bind_kept()
            self._reflection_lookups = self._previous_lookups
            shader.use(lit=True)
            shader.set_planar_levels(0)
        previous = atlas.begin()
        drawn_before = self.stats.draws
        try:
            for frame in mirrors:
                atlas.clear(frame.rect)
            shared: set = set()
            if self.sharesViews(mirrors):
                limit = max(1, MultiviewCapabilities.detect().max_views)
                # One set of programs for every count of mirror views the
                # budget allows, compiled the first frame there are mirrors.
                capacity = min(limit, max(1, self.reflectionBudget().views))
                for start in range(0, len(mirrors), limit):
                    chunk = mirrors[start:start + limit]
                    found = self.renderShared(chunk, None, lighting, mirrored=True,
                                              capacity=capacity)
                    if found is None:
                        break
                    shared |= found
            for frame in mirrors:
                records = [record for record in frame.toRender
                           if id(record[4]) not in shared]
                if not records:
                    continue
                self.applyViewFrame(frame, gl=False)
                glViewport(*frame.rect)
                glScissor(*frame.rect)
                self.setupViewLighting(frame.modelView, lighting, fitted=False)
                # Uniforms go to the bound program, and lighting setup can
                # leave another one bound.
                shader.use(lit=True)
                shader.set_hdr_output(True)
                # A mirrored camera turns every triangle's winding over. A
                # mesh follows its modelview's determinant; everything else
                # follows this.
                glFrontFace(GL_CW)
                PBRMesh.reset_draw_state(self)
                self.shaderRenderOpaque(records, None)
                glFrontFace(GL_CCW)
                PBRMesh.reset_draw_state(self)
        finally:
            self.stats.mirrorDraws = self.stats.draws - drawn_before
            glFrontFace(GL_CCW)
            PBRMesh.reset_draw_state(self)
            atlas.end(previous, mipmap=plan.rough)
            if not self._scissorViews:
                glDisable(GL_SCISSOR_TEST)
            shader.use(lit=True)
            shader.set_hdr_output(bool(getattr(self, '_bloom_active', False)))
            if bounce:
                self.clearPlanarReflection()
                self._reflection_lookups = plan.lookups
            if active is not None:
                self.applyViewFrame(active)

    def applyPlanarReflection(self, shader: Any, record: Any, program: Any = None) -> None:
        """Have the shape about to be drawn read its reflection, or none.

        A mirror's lookup is the one for the view being drawn; every other
        shape reads none, and a run of them sets nothing.
        """
        lookups = self._reflection_lookups
        lookup = lookups.get((id(self.view), id(record[4]))) if lookups else None
        if lookup is self._reflection_applied:
            return
        apply = getattr(shader, 'set_planar_reflection', None)
        if apply is None:
            return
        apply(lookup, program=program)
        self._reflection_applied = lookup

    def clearPlanarReflection(self) -> None:
        """Nothing reads a reflection until the next view says what it reads."""
        shader = self.shader_program
        if self._reflection_applied is not None and hasattr(shader, 'set_planar_reflection'):
            shader.use(lit=True)
            shader.set_planar_reflection(None)
        self._reflection_applied = None

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
            shape = rec[5]
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
                disable_object_id_blend()   # don't blend the picking id
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glDepthMask(0)

        self.transparent = (mode == 'blend')
        debugFrustum = self.context.contextDefinition.debugBBox
        try:
            for _obj_index, record in records:
                _key, mvmatrix, tmatrix, bvolume, path, node = record
                self.matrix = mvmatrix
                self.renderPath = path
                shader.set_matrices(mvmatrix, self.projection, program=prog)
                masked = self._writeShapeId(shader, path, node, prog, id_map)
                self.applyLightGrid(shader, node, tmatrix, bvolume, prog)
                self.applyPlanarReflection(shader, record, prog)
                try:
                    if mode == 'blend':
                        node.RenderTransparent(mode=self)
                    else:
                        node.Render(mode=self)
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
            (key,mv,tm,bv,path,node) = record
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
        if not self.supports_bloom or not bloom.bloom_enabled(self):
            self._bloom_active = False
            return False
        # The window, not the pass's viewport: with several views the viewport
        # is one view's tile, and the target holds all of them.
        w, h = (int(value) for value in self.context.getViewPort())
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
        """Composite the glow onto the frame, each view within its own rectangle.

        Called once the views are drawn and before anything is drawn over them,
        so the overlay is not bloomed and the frame presented is the finished
        one.
        """
        frames = getattr(self, 'viewFrames', None) or ()
        rects = [frame.rect for frame in frames] if len(frames) > 1 else None
        try:
            assert self._bloom_pass is not None
            self._bloom_pass.composite(rects)
        except Exception:
            pass
        self._bloom_active = False
