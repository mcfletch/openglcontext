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
from . import _flat
import logging
log = logging.getLogger(__name__)


class FlatPass(_flat.FlatPass):
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
    # Set to False to use legacy fixed-function rendering
    use_shaders: bool = False 
