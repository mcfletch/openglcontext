"""Flat rendering mechanism using structural scenegraph observation

Core-profile compatible flat rendering pass. This module inherits from
_flat.FlatPass which now supports both legacy fixed-function and
shader-based rendering paths.

Set use_shaders=True on FlatPass instances to enable core-profile
compatible shader-based rendering using the VRML97 lighting model.

Example usage:
    from OpenGLContext.passes import flatcore

    # Create the render pass with shaders enabled
    render_pass = flatcore.FlatPass(scene, contexts)
    render_pass.use_shaders = True  # Enable shader-based rendering
"""
import os
from . import _flat
from .shadowmixin import ShadowMapMixin
import logging
log = logging.getLogger(__name__)


def _shadows_enabled_by_env() -> bool:
    # Shadows default ON; OPENGLCONTEXT_SHADOWS=0 (or false/no/off) disables them.
    return os.environ.get('OPENGLCONTEXT_SHADOWS', '').strip().lower() not in (
        '0', 'false', 'no', 'off',
    )


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

    # Shadow mapping is ON by default; disable per-instance (pass.use_shadows =
    # False) or globally via OPENGLCONTEXT_SHADOWS=0.
    use_shadows: bool = _shadows_enabled_by_env()

    # Soft (PCSS contact-hardening) shadows; OPENGLCONTEXT_SHADOWS_SOFT=1.
    shadow_soft: bool = os.environ.get(
        'OPENGLCONTEXT_SHADOWS_SOFT', '').strip().lower() in ('1', 'true', 'yes', 'on')

    # Minimum group size worth an instanced draw (env-overridable), shared by the
    # PBR subclass. The base _flat default (8) does not read the env.
    INSTANCE_MIN: int = int(os.environ.get('OPENGLCONTEXT_INSTANCE_MIN', '4') or 4)

    @property
    def instancing_enabled(self) -> bool:
        """Instance shapes sharing one geometry through the VRML97 lit shader.

        Off with OPENGLCONTEXT_INSTANCING=0. Only geometry exposing a cached VAO
        (_instanceable) batches; ordinary VRML97 geometry falls through unchanged.
        The PBR pass overrides this with its own richer (material-array) path.
        """
        return os.environ.get('OPENGLCONTEXT_INSTANCING', '1').strip().lower() \
            not in ('0', 'off', 'false', 'no')

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
        from OpenGLContext.passes.instancing import draw_instanced_mesh
        from OpenGLContext.passes.shaderpass import configure_material_from_node
        from OpenGL.GL import GL_LINES
        members = group.members
        geom = group.geometry
        self.renderPath = members[0][4]
        self.matrix = members[0][1]
        modelviews = [rec[1] for rec in members]
        if id_map is not None:
            oids = [self._objectIdFor(rec[4]) if self._shapePickable(rec[4]) else 0
                    for rec in members]
        else:
            oids = [0] * len(members)
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
