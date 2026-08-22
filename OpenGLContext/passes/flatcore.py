"""The core-profile flat pass: the VRML97 lighting model in GLSL

Draws through :class:`~OpenGLContext.passes.shaderpass.VRML97ShaderProgram`
rather than the fixed-function pipeline, so it runs on an OpenGL 3.3+ core
context.  ``use_shaders`` is already true here; the compatibility-profile pass
is :mod:`OpenGLContext.passes.flatcompat`, and
:mod:`OpenGLContext.passes.renderpass` picks between them from the context's
profile and renderer.  Shadow mapping comes from
:class:`~OpenGLContext.passes.shadowmixin.ShadowMapMixin`.
"""
import os
from typing import Optional

from OpenGLContext import renderoptions
from . import _flat
from .shadowmixin import ShadowMapMixin
import logging
log = logging.getLogger(__name__)


class FlatPass(ShadowMapMixin, _flat.FlatPass):
    """Core-profile compatible flat rendering pass.

    This class inherits all functionality from _flat.FlatPass.
    When use_shaders=True, rendering uses GLSL shaders instead of
    the deprecated fixed-function pipeline.

    The shader-based path:
    - Uses VRML97 lighting model implemented in GLSL
    - Is compatible with OpenGL 3.3+ core profile
    - Works on platforms without fixed-function support (e.g., macOS)

    Rendering Attributes:
        use_shaders -- Set True to enable shader-based rendering
        shader_mode -- True during shader render passes
        shader_program -- VRML97ShaderProgram instance when using shaders

        visible -- whether we are currently rendering a visible pass
        transparent -- whether we are currently doing a transparent pass
        lighting -- whether we currently are rendering a lit pass
        context -- context for which we are rendering
        cache -- cache of the context for which we are rendering
        projection -- projection matrix of current view platform
        modelView -- model-view matrix of current view platform
        viewport -- 4-component viewport definition for current context
        frustum -- viewing-frustum definition for current view platform
        MAX_LIGHTS -- maximum number of lights (8)
    """
    # Enable shader-based rendering by default for core profile compatibility
    # Set to False to use legacy fixed-function rendering (not recommended for core profile)
    use_shaders: bool = True

    # Per-instance overrides. None means "ask the context definition", which is
    # what lets a settings screen turn shadows off mid-session; an assignment
    # (pass.use_shadows = False) pins this pass and outranks the field.
    _use_shadows: Optional[bool] = None
    _shadow_soft: Optional[bool] = None

    @property
    def use_shadows(self) -> bool:
        """Whether this pass renders shadow maps (ContextDefinition.shadows)."""
        if self._use_shadows is not None:
            return self._use_shadows
        return renderoptions.flag(self, 'shadows', renderoptions.env_flag_once(
            'OPENGLCONTEXT_SHADOWS', True))

    @use_shadows.setter
    def use_shadows(self, value: bool) -> None:
        self._use_shadows = bool(value)

    @property
    def shadow_soft(self) -> bool:
        """PCSS contact-hardening shadows (ContextDefinition.shadowsSoft)."""
        if self._shadow_soft is not None:
            return self._shadow_soft
        return renderoptions.flag(
            self, 'shadowsSoft',
            renderoptions.env_flag_once('OPENGLCONTEXT_SHADOWS_SOFT', False))

    @shadow_soft.setter
    def shadow_soft(self, value: bool) -> None:
        self._shadow_soft = bool(value)

    def maxLights(self, ceiling: int) -> int:
        """Lights to bind this frame: the shader's ceiling, or fewer if asked.

        A scene can carry more lights than a weak GPU should shade, and the
        cheapest way to buy back a frame is to light with fewer of them.
        """
        return max(0, min(int(ceiling),
                          int(renderoptions.number(self, 'maximumLights', ceiling))))

    def instanceMinimum(self) -> int:
        """Smallest group worth collapsing into one instanced draw.

        A method rather than a class attribute assigned at import: read at
        import the variable is settled before a test -- or an application --
        has had a chance to set it, and nothing can reach it afterwards.
        """
        return int(renderoptions.env_number_once(
            'OPENGLCONTEXT_INSTANCE_MIN', 4, integer=True))

    # The base _flat.FlatPass declares instancing_enabled as a writeable class
    # attribute; this read-only property refines it (env-gated), so mypy's
    # attribute/property override check does not apply.
    @property
    def instancing_enabled(self) -> bool:  # type: ignore[override]
        """Instance shapes sharing one geometry through the VRML97 lit shader.

        Off with ContextDefinition.instancing. Only geometry exposing a cached
        VAO (_instanceable) batches; ordinary VRML97 geometry falls through
        unchanged. The PBR pass overrides this with its own richer
        (material-array) path.
        """
        return renderoptions.flag(
            self, 'instancing',
            renderoptions.env_flag_once('OPENGLCONTEXT_INSTANCING', True))

    def _instanceable(self, path) -> bool:
        """Geometry drawable through the shared instanced path -- anything exposing
        an ``instanceGPU(mode)`` (PBRMesh, Box, Sphere, ...)."""
        return hasattr(getattr(path[-1], 'geometry', None), 'instanceGPU')

    def _instanceKey(self, path):
        """Group by (geometry-content, material): distinct same-shape geometry
        nodes sharing a Material batch (a sphere field of many Sphere nodes). With
        collapse off, fall back to node-identity grouping (USE/DEF only)."""
        from OpenGLContext.passes.instancing import (
            geometry_instance_key, geometry_content_instance_key,
        )
        collapse = os.environ.get('OPENGLCONTEXT_INSTANCE_COLLAPSE', '1').strip().lower() \
            not in ('0', 'off', 'false', 'no')
        if collapse:
            return geometry_content_instance_key(path)
        return geometry_instance_key(path)

    def _drawInstanceGroup(self, group, shader, prog, id_map) -> None:
        """Draw an InstanceGroup through the VRML97 lit program in one call.

        Binds the group's single representative material (per-instance material
        factors are the PBR pass's richer path), then hands per-instance modelviews
        and object ids to the instanced draw. Each instance keeps a distinct pick
        id; a non-pickable instance packs 0.
        """
        from OpenGLContext.passes.instancing import (
            draw_instanced_mesh, instance_counts, instance_matrices, per_instance,
        )
        from OpenGLContext.passes.shaderpass import configure_material_from_node
        from OpenGL.GL import GL_LINES
        members = group.members
        geom = group.geometry
        self.renderPath = members[0][4]
        self.matrix = members[0][1]
        # A member standing for a whole placement set expands to one instance per
        # placement, all sharing that node's pick id.
        modelviews = instance_matrices(members, visible=self.visiblePlacements)
        counts = instance_counts(members, visible=self.visiblePlacements)
        if id_map is not None:
            oids = [self._objectIdFor(rec[4]) if self._shapePickable(rec[4]) else 0
                    for rec in members]
        else:
            oids = [0] * len(members)
        oids = per_instance(oids, counts)
        gpu = geom.instanceGPU(self)

        # Line geometry (debug proxy wireframes) draws through the unlit line
        # program -- per-vertex colour, no material/lighting -- then restores the
        # lit program so later mesh groups and singles are unaffected.
        if int(getattr(gpu, 'draw_mode', 0)) == int(GL_LINES):
            line_prog = getattr(shader, 'line_program', None)
            if not line_prog:
                return
            shader.use_line()
            shader.set_matrices(self.matrix, self.projection, program=line_prog)
            shader.set_instancing(True, program=line_prog)
            try:
                draw_instanced_mesh(gpu, modelviews, oids)
            finally:
                shader.set_instancing(False, program=line_prog)
                shader.use(lit=True)
            return

        appearance = group.appearance
        material = getattr(appearance, 'material', None) if appearance is not None else None
        if material is not None:
            configure_material_from_node(shader, material)
        else:
            shader.set_default_material()
        shader.set_matrices(self.matrix, self.projection, program=prog)
        if hasattr(shader, 'set_vertex_color'):
            shader.set_vertex_color(getattr(geom, 'colors', None) is not None)
        if hasattr(geom, '_apply_draw_state'):
            geom._apply_draw_state(self)
        shader.set_instancing(True, program=prog)
        try:
            draw_instanced_mesh(gpu, modelviews, oids)
        finally:
            shader.set_instancing(False, program=prog)
