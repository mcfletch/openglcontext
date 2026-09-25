"""Planar reflections as a render pass draws them: the mirror views of a frame.

:class:`ReflectionsMixin` is the pass's side of
:mod:`OpenGLContext.passes.reflection`: once a frame, before any view is
drawn, it asks the :class:`~OpenGLContext.passes.reflectionplanner.ReflectionPlanner`
which mirror views to draw, culls each from the frame's walk of the scene
through its own camera, draws them into the
:class:`~OpenGLContext.passes.reflectionatlas.ReflectionAtlas`, and then tells
each mirror drawn in a view which tile it reads
(:meth:`ReflectionsMixin.applyPlanarReflection`). It is composed into the pass
through the effects mixin, so ``self`` is the pass; what it needs of the pass
is declared at the top of the class. See docs/reflections.rst.
"""
from __future__ import annotations

import contextlib
import logging
from types import MappingProxyType
from typing import (
    TYPE_CHECKING, AbstractSet, Any, Dict, List, Mapping, Optional, Set, Tuple,
)

import numpy as np

from OpenGLContext import renderoptions
from OpenGLContext.passes.disposal import PassResources, let_go
from OpenGLContext.passes.layerguard import LayerGuard

if TYPE_CHECKING:
    from OpenGLContext.multiview.strategy import ViewFrame
    from OpenGLContext.passes._flat import GatheredPaths
    from OpenGLContext.passes.flateffects import Lighting
    from OpenGLContext.passes.framestate import FrameState
    from OpenGLContext.passes.gputimer import GpuTimer
    from OpenGLContext.passes.reflectionatlas import ReflectionAtlas
    from OpenGLContext.passes.reflectionplanner import Lookup, ReflectionPlanner
    from OpenGLContext.passes.reflectiontiles import Budget
    from OpenGLContext.passes.renderstats import RenderStats

log = logging.getLogger(__name__)

__all__ = ('ReflectionsMixin',)

#: What a pass whose reflections have never been drawn reads: nothing, and
#: read-only, so no pass can fill it for every other.
_NO_LOOKUPS: Mapping[Any, Any] = MappingProxyType({})


class ReflectionsMixin(PassResources):
    """A frame's planar reflections, drawn before its views and read by its mirrors."""

    if TYPE_CHECKING:
        shader_program: Any
        context: Any
        frustum: Any
        visiblePlacements: Optional[Dict[int, Any]]
        multiviewStrategy: Optional[str]
        _pathGeneration: int
        activeFrame: Optional["ViewFrame"]
        view: Any
        _scissorViews: bool
        _bloom_active: bool

        @property
        def stats(self) -> "RenderStats": ...

        def frameGather(self) -> "GatheredPaths": ...
        def applyViewFrame(self, frame: Any, gl: bool = True) -> None: ...
        frameState: Optional["FrameState"]

        def renderSet(self, matrix: Any, gathered: Any = None,
                      among: Optional[np.ndarray] = None) -> List[Any]: ...
        def setupViewLighting(self, matrix: Any, lighting: Optional["Lighting"],
                              fitted: bool = False) -> None: ...
        def shaderRenderOpaque(self, toRender: List, id_map: Optional[Dict] = None,
                               skip: Optional[set] = None) -> None: ...
        def sharesViews(self, frames: Any) -> bool: ...
        def sharesDraw(self, record: Any) -> bool: ...
        def chooseMultiview(self) -> str: ...
        def renderShared(self, frames: Any, id_map: Optional[Dict],
                         lighting: Optional["Lighting"] = None, mirrored: bool = False,
                         capacity: int = 0, into_atlas: bool = False
                         ) -> Optional[Dict[int, Any]]: ...
        def _frustumSurvivors(self, matrices: Any, points: Any, bounded: Any,
                              drawing: Any) -> Any: ...
        def mirrorsZoned(self) -> bool: ...
        def mirrorAllowed(self, record: Any, eye: Any) -> bool: ...

    #: Whether the program can read reflections, settled once; and what
    #: draws and holds them.
    _planar_reflections: Optional[bool] = None
    _reflection_atlas: Optional["ReflectionAtlas"] = None
    _reflection_planner: Optional["ReflectionPlanner"] = None
    _reflection_timer: Optional["GpuTimer"] = None
    #: What switches reflections off for good if drawing them raises.
    _reflection_guard: Optional[LayerGuard] = None
    #: What each mirror in each view reads this frame, by
    #: :func:`~OpenGLContext.passes.reflectionplanner.key_for`.
    _reflection_lookups: Mapping[Any, "Lookup"] = _NO_LOOKUPS
    #: What each mirror read the frame before: what a mirror seen in a mirror
    #: view reads, from the copy of the atlas that frame left.
    _previous_lookups: Mapping[Any, "Lookup"] = _NO_LOOKUPS
    #: The mirror views this frame drew with a mirror left out of them.
    _incompleteMirrors: AbstractSet[Any] = frozenset()
    #: :meth:`sceneMirrors`' answer, and what it was worked out for.
    _sceneMirrors: Optional[Tuple[Any, Any]] = None
    #: The lookup the program was last given, so a run of shapes that are
    #: not mirrors sets nothing.
    _reflection_applied: Any = None
    #: True while a draw is made in an unmirrored camera's eye space for
    #: views that are mirrored, which turns every triangle's winding over
    #: without the modelview's determinant saying so.
    mirroredDraw = False

    def disposeResources(self) -> None:
        """Release the atlas and the timer; mirrors read nothing until the next plan."""
        let_go(self, '_reflection_timer')
        self._releaseReflections()
        self._reflectionsOff()
        super().disposeResources()

    def _releaseReflections(self) -> None:
        """Give back the atlas and forget every tile it held.

        While reflections are off, and as the pass lets its resources go; the
        next frame that draws a reflection makes an atlas again, and plans
        every mirror as one with no tile.
        """
        let_go(self, '_reflection_atlas')
        if self._reflection_planner is not None:
            self._reflection_planner.reset()

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
        if self._reflection_guard is not None and self._reflection_guard.failed:
            return False
        return self._planar_reflections and renderoptions.flag(
            self, 'planarReflections',
            renderoptions.env_flag_once('OPENGLCONTEXT_PLANAR_REFLECTIONS', True))

    def reflectsScene(self) -> bool:
        """Whether this frame may draw reflections: they are on and a shape is a mirror."""
        return self.planarReflectionsEnabled() and bool(len(self.sceneMirrors()))

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

    def renderReflections(self, frames: List[Any],
                          lighting: Optional[Lighting] = None) -> None:
        """Draw this frame's reflections into the atlas, for the mirrors to read.

        :class:`~OpenGLContext.passes.reflectionplanner.ReflectionPlanner`
        says which mirror views to draw and where; each is culled from the
        frame's walk through its own camera, and they are drawn together:
        what can serve several views in one shared submission, the rest a
        view at a time. The views' own camera is looked through again
        afterwards.

        An exception from any of it is logged once and switches planar
        reflections off (:class:`~OpenGLContext.passes.layerguard.LayerGuard`):
        every mirror reflects the environment probe from then on, and the
        frame is drawn.
        """
        if self._reflection_guard is None:
            self._reflection_guard = LayerGuard(
                'planar reflection', off=self._reflectionsOff, logger=log)
        self._reflection_guard.run(self._renderReflections, frames, lighting)

    def _reflectionsOff(self) -> None:
        """Leave nothing a mirror would read: each reflects the probe."""
        self._reflection_lookups = {}
        self._previous_lookups = {}
        self._reflection_applied = None
        self._incompleteMirrors = frozenset()

    def _renderReflections(self, frames: List[Any], lighting: Optional[Lighting]) -> None:
        previous = self._reflection_lookups
        self._previous_lookups = {}
        self._reflection_lookups = {}
        self._reflection_applied = None
        self._incompleteMirrors = frozenset()
        if not self.planarReflectionsEnabled():
            self._releaseReflections()
            return
        if self._drawReflections(frames, lighting, previous) or self._incompleteMirrors:
            # A context that draws only when something changes would otherwise
            # leave a still scene showing reflections drawn while the pass was
            # settling, none, or ones drawn with a mirror left out, until
            # something else asked for a frame.
            trigger = getattr(self.context, 'triggerRedraw', None)
            if trigger is not None:
                trigger(0)

    def _drawReflections(self, frames: List[Any], lighting: Optional[Lighting],
                         previous: Mapping[Any, "Lookup"]) -> bool:
        """Plan and draw this frame's reflections; whether the plan is unfinished."""
        gathered = self.frameGather()
        from OpenGLContext.passes.reflectionatlas import LEVELS, ReflectionAtlas
        from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
        if self._reflection_planner is None:
            self._reflection_planner = ReflectionPlanner()
        planner = self._reflection_planner
        indices = self.sceneMirrors()
        if not len(indices):
            # Nothing in the scene is a mirror: no tile the planner holds is
            # read, and no view is looked through for one.
            planner.reset()
            return False
        mirror_paths = {id(gathered.paths[index]): gathered.paths[index] for index in indices}
        # Zones may say which mirrors draw a reflection from where a camera is.
        planner.allowed = self.mirrorAllowed if self.mirrorsZoned() else None
        target = float(renderoptions.number(
            self, 'reflectionMilliseconds',
            renderoptions.env_number_once('OPENGLCONTEXT_REFLECTION_MS', 0.0)))
        timer = self._reflection_timer
        if target > 0.0 and timer is not None and timer.milliseconds is not None:
            # Named with the timer, whose count starts again when it is remade.
            planner.schedule.measured(timer.milliseconds, target, scale=timer.tag,
                                      reading=(timer, timer.reading))
        size = self.reflectionAtlasSize()
        bounces = int(renderoptions.number(
            self, 'reflectionBounces', renderoptions.env_number_once(
                'OPENGLCONTEXT_REFLECTION_BOUNCES', 2, integer=True)))
        plan = planner.plan(frames, size, self.reflectionBudget,
                            separate=self._separateShapes, inside=self.mirrorsIn,
                            bounces=bounces,
                            shown=lambda frame: [record for record in frame.toRender
                                                 if mirror_paths.get(id(record[4])) is record[4]])
        if self.activeFrame is not None:
            # Looking for mirrors in the mirrors' views looked through them.
            self.applyViewFrame(self.activeFrame, gl=False)
        if not plan.lookups:
            return plan.unfinished
        atlas = self._reflection_atlas
        if atlas is None:
            atlas = self._reflection_atlas = ReflectionAtlas()
        if atlas.ensure_size(*size):
            # A new atlas holds only what this frame draws into it.
            previous = {}
            drawn = {draw.key for draw in plan.draws}
            planner.keep_only(drawn)
            plan.lookups = {key: lookup for key, lookup in plan.lookups.items()
                            if plan.canonical(key) in drawn}
        self._reflection_lookups = plan.lookups
        if not plan.lookups:
            return plan.unfinished
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
                timer.begin(tag=planner.schedule.time_scale)
                try:
                    self._drawMirrorViews(plan, lighting, gathered, atlas)
                finally:
                    timer.end()
        if self._incompleteMirrors:
            # Each is drawn again next frame, when the mirror it left out has
            # a reflection of its own to show.
            planner.redo(self._incompleteMirrors)
        self.stats.mirrorViews = len(plan.draws)
        self.stats.mirrorTexels = plan.texels
        self.stats.mirrorMilliseconds = None if timer is None else timer.milliseconds
        atlas.bind()
        shader = self.shader_program
        shader.use(lit=True)
        shader.set_planar_levels(LEVELS - 1 if atlas.mipmapped else 0)
        return plan.unfinished

    def _separateShapes(self, mirror: Any) -> bool:
        """Whether a mirror view drawn through ``mirror``'s camera draws a
        shape a shared draw refuses, and so costs a draw of its own.

        The shapes its frustum keeps are asked, each at most once a frame;
        what they answer is kept on the frame's state.
        """
        gathered = self.frameGather()
        keep = self._survivorsThrough(mirror.modelproj)
        if not len(keep):
            return False
        refuses = self._refusesShare(gathered)
        unknown = keep[refuses[keep] < 0]
        for index in unknown:
            refuses[index] = self._refusedAt(gathered, int(index))
        return bool((refuses[keep] == 1).any())

    def _refusesShare(self, gathered: "GatheredPaths") -> np.ndarray:
        """Per path of ``gathered``, whether a mirror view draws it apart
        from a shared draw: 1, 0, or -1 where not asked yet this frame."""
        state = self.frameState
        refuses = None if state is None else state.refusesShare
        if refuses is None or len(refuses) != len(gathered.paths):
            refuses = np.full(len(gathered.paths), -1, dtype=np.int8)
            if state is not None:
                state.refusesShare = refuses
        return refuses

    def _refusedAt(self, gathered: "GatheredPaths", index: int) -> bool:
        """Whether a mirror view draws path ``index`` apart from a shared draw.

        An opaque shape that is no mirror and that one draw cannot serve
        several views with; a transparent one is not drawn in a mirror view,
        and a mirror in one is drawn singly whatever its view.
        """
        from OpenGLContext.passes.reflection import is_reflector
        node, own = gathered.nodes[index], gathered.own[index]
        record = (node.sortKey(self, own), None, own, gathered.volumes[index],
                  gathered.paths[index], node)
        return (not record[0][0] and not is_reflector(record)
                and not self.sharesDraw(record))

    def _survivorsThrough(self, modelproj: Any, frame: Any = None,
                          among: Optional[np.ndarray] = None) -> np.ndarray:
        """Indices into this frame's walk of what a camera's frustum keeps.

        ``modelproj`` is the camera's world-to-clip matrix; ``frame``, where
        given, keeps the frustum made from it. ``among`` narrows the walk to
        those indices first.
        """
        from OpenGLContext import frustum
        gathered = self.frameGather()
        found = None if frame is None else frame.frustum
        if found is None:
            found = frustum.Frustum.fromViewingMatrix(modelproj, normalize=1)
            if frame is not None:
                frame.frustum = found
        subset = slice(None) if among is None else among
        current, self.frustum = self.frustum, found
        try:
            keep = self._frustumSurvivors(
                gathered.matrices[subset], gathered.points[subset],
                np.asarray(gathered.bounded)[subset],
                np.asarray(gathered.drawing)[subset])
        finally:
            self.frustum = current
        return np.asarray(keep if among is None else np.asarray(among)[keep], dtype=int)

    def sceneMirrors(self) -> Any:
        """Indices into this frame's gather of the shapes that are mirrors.

        Kept while the scene's paths and every field deciding which shapes are
        mirrors stay as they were
        (:func:`~OpenGLContext.passes.reflection.mirror_generation`).
        """
        from OpenGLContext.passes.reflection import mirror_generation, shape_reflector
        gathered = self.frameGather()
        key = (self._pathGeneration, mirror_generation(), len(gathered.nodes))
        known = self._sceneMirrors
        if known is None or known[0] != key:
            known = self._sceneMirrors = (key, np.array(
                [index for index, node in enumerate(gathered.nodes)
                 if shape_reflector(node) is not None], dtype=int))
        return known[1]

    def mirrorsIn(self, frame: Any) -> List[Any]:
        """The scene's mirrors inside a mirror view's frustum, as draw records.

        Only the mirrors are tested, against the frustum of ``frame``'s own
        camera, so a chain of mirrors costs a test of the few mirrors a scene
        has at each step rather than a cull of the whole scene.
        """
        indices = self.sceneMirrors()
        if not len(indices):
            return []
        gathered = self.frameGather()
        keep = self._survivorsThrough(frame.modelproj, frame, among=indices)
        modelview = np.asarray(frame.modelView, 'f')
        return [(gathered.nodes[index].sortKey(self, gathered.own[index]),
                 gathered.matrices[index] @ modelview, gathered.own[index],
                 gathered.volumes[index], gathered.paths[index], gathered.nodes[index])
                for index in keep]

    def mirrorContents(self, frame: Any, texels: float = 0.0) -> List[Any]:
        """What a mirror view's ``frame`` draws, of the frame's walk of the scene.

        What its camera's frustum keeps, opaque, and large enough to cover two
        texels of its tile. ``texels`` is the tile's texels per radian, worked
        out from the frame's rectangle and projection where not given. Sets
        the frame's frustum where it has none, and the placements it keeps of
        each instanced set. Which shapes are too small is measured for the
        whole walk at once, from where each is and how far it reaches, which
        is worked out once a frame.
        """
        from OpenGLContext import frustum
        from OpenGLContext.passes.reflection import fov, reach, too_small_mask
        if frame.frustum is None:
            frame.frustum = frustum.Frustum.fromViewingMatrix(frame.modelproj, normalize=1)
        if texels <= 0.0:
            texels = frame.rect[3] / max(fov(frame.projection), 1e-6)
        self.applyViewFrame(frame, gl=False)
        gathered = self.frameGather()
        state = self.frameState
        placed = None if state is None else state.reach
        if placed is None or len(placed[1]) != len(gathered.paths):
            placed = reach(gathered.matrices, gathered.points, gathered.bounded)
            if state is not None:
                state.reach = placed
        eye = np.linalg.inv(np.asarray(frame.modelView, 'd'))[3, :3]
        small = too_small_mask(placed[0], placed[1], gathered.bounded, eye, texels)
        records = [record for record in self.renderSet(frame.modelView, gathered, ~small)
                   if not record[0][0]]
        frame.visiblePlacements = self.visiblePlacements or {}
        return records

    def mirrorFrames(self, plan: Any) -> List[Any]:
        """A :class:`~OpenGLContext.multiview.strategy.ViewFrame` per mirror view.

        Each is the mirror's camera, drawing into its tile as the draw's
        :class:`~OpenGLContext.passes.reflectionplanner.ReflectedView`, with
        what :meth:`~OpenGLContext.passes.reflectionplanner.ReflectionPlanner.contents`
        keeps of :meth:`mirrorContents` to draw. A view that left out a mirror
        is noted in :attr:`_incompleteMirrors`, to be drawn again next frame.
        """
        from OpenGLContext.multiview.strategy import ViewFrame
        from OpenGLContext.passes.reflection import fov
        planner = self._reflection_planner
        assert planner is not None, 'a plan comes from the pass\'s planner'
        mirrors = []
        incomplete: Set[Any] = set()
        self._incompleteMirrors = incomplete
        earlier = self._previous_lookups
        for draw in plan.draws:
            mirror = draw.mirror
            frame = ViewFrame(
                draw.view, draw.frame.camera, draw.tile.rect,
                mirror.modelView, mirror.projection, mirror.modelproj, None,
                fitted=False)
            texels = draw.tile.height / max(
                (mirror.crop[3] - mirror.crop[1]) / 2.0 * fov(draw.frame.projection),
                1e-6)
            frame.toRender, left_out = planner.contents(
                plan, draw, self.mirrorContents(frame, texels), earlier)
            if left_out:
                incomplete.add(draw.key)
            mirrors.append(frame)
        return mirrors

    def _drawMirrorViews(self, plan: Any, lighting: Optional[Lighting], gathered: Any,
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
        mirrors = self.mirrorFrames(plan)
        # A mirror seen in a mirror view reads the reflection it had the frame
        # before, from a copy: the atlas itself is being drawn into.
        bounce = any(is_reflector(record) for frame in mirrors
                     for record in frame.toRender)
        if bounce:
            from OpenGLContext.passes.reflection import bounds_tile
            atlas.keep(bounds_tile(lookup.bounds, atlas.size)
                       for lookup in self._previous_lookups.values())
            atlas.bind_kept()
            self._reflection_lookups = self._previous_lookups
            shader.use(lit=True)
            shader.set_planar_levels(0)
        else:
            # Nothing drawn reads a reflection, and the unit is not left
            # naming the texture being drawn into.
            atlas.unbind()
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
                budget = plan.budget or self.reflectionBudget()
                capacity = min(limit, max(1, budget.views))
                # A camera reflected an even number of times has its winding
                # the right way round again, so those views draw apart.
                for odd in (True, False):
                    views = [frame for frame in mirrors if _turned(frame) == odd]
                    for start in range(0, len(views), limit):
                        found = self.renderShared(views[start:start + limit], None,
                                                  lighting, mirrored=odd,
                                                  capacity=capacity, into_atlas=True)
                        if found is None:
                            break
                        shared |= {(id(frame), path) for frame in views[start:start + limit]
                                   for path in found}
            for frame in mirrors:
                records = [record for record in frame.toRender
                           if (id(frame), id(record[4])) not in shared]
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
                glFrontFace(GL_CW if _turned(frame) else GL_CCW)
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

        A mirror's lookup is the one for the view being drawn. A mirror seen
        in a mirror view with none of its own yet reads the one for the view
        that mirror is seen from, and so on to the viewer's: a reflection from
        a little way off, where the probe would read as a flash. Every other
        shape reads none, and a run of them sets nothing.
        """
        from OpenGLContext.passes.reflectionplanner import ReflectedView, lookup_key
        lookups = self._reflection_lookups
        lookup = None
        if lookups:
            view, path = self.view, record[4]
            lookup = lookups.get(lookup_key(view, path))
            while lookup is None and isinstance(view, ReflectedView):
                view = view.source
                lookup = lookups.get(lookup_key(view, path))
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
def _turned(frame: Any) -> bool:
    """Whether a mirror view's camera has been reflected an odd number of times."""
    return int(getattr(frame.view, 'depth', 1)) % 2 == 1
