"""Flat rendering passes (base implementation)

This module provides both legacy fixed-function and shader-based rendering.
Set use_shaders=True on FlatPass instances to enable core-profile compatible
shader-based rendering using the VRML97 lighting model.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from OpenGLContext.scenegraph import nodepath,switch,boundingvolume
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot, allclose, concatenate, ones
from OpenGLContext import frustum
from OpenGLContext.debug.logs import getTraceback
from vrml.vrml97 import nodetypes
from vrml import olist
from OpenGLContext.scenegraph import shaders
import sys
from pydispatch.dispatcher import connect
import logging
log = logging.getLogger( __name__ )

if TYPE_CHECKING:
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

__all__ = (
    'SGObserver',
    'FlatPass',
    'get_inv_modelproj',
    'get_inv_modelview',
    'get_modelproj',
    'get_modelview',
    'get_projection',
)


class SelectionFBO:
    """Framebuffer Object for optimized selection rendering.

    Renders selection pass to a small FBO covering only the pick region,
    dramatically reducing pixel fill cost for selection operations.
    """

    def __init__(self, max_width: int = 512, max_height: int = 512):
        """Initialize the selection FBO.

        Args:
            max_width: Maximum width of the FBO texture
            max_height: Maximum height of the FBO texture
        """
        self.max_width = max_width
        self.max_height = max_height
        self.fbo = None
        self.color_texture = None
        self.depth_renderbuffer = None
        self.current_width = 0
        self.current_height = 0
        self._initialized = False

    def _ensure_initialized(self, width: int, height: int) -> bool:
        """Ensure FBO is created and sized appropriately.

        Returns True if FBO is ready, False if FBO creation failed.
        """
        # Clamp to max size
        width = min(width, self.max_width)
        height = min(height, self.max_height)

        if width <= 0 or height <= 0:
            return False

        # Check if we need to create or resize
        if self._initialized and width <= self.current_width and height <= self.current_height:
            return True

        # Clean up existing resources
        self._cleanup()

        try:
            # Create FBO
            self.fbo = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)

            # Create color texture
            self.color_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.color_texture)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                width, height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                GL_TEXTURE_2D, self.color_texture, 0
            )

            # Create depth renderbuffer
            self.depth_renderbuffer = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth_renderbuffer)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                GL_RENDERBUFFER, self.depth_renderbuffer
            )

            # Check framebuffer completeness
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("Selection FBO incomplete: status=%s", status)
                self._cleanup()
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                return False

            self.current_width = width
            self.current_height = height
            self._initialized = True

            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            return True

        except Exception as e:
            log.warning("Failed to create selection FBO: %s", e)
            self._cleanup()
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            return False

    def _cleanup(self):
        """Clean up OpenGL resources."""
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None

        if self.color_texture is not None:
            try:
                glDeleteTextures([self.color_texture])
            except Exception:
                pass
            self.color_texture = None

        if self.depth_renderbuffer is not None:
            try:
                glDeleteRenderbuffers(1, [self.depth_renderbuffer])
            except Exception:
                pass
            self.depth_renderbuffer = None

        self._initialized = False
        self.current_width = 0
        self.current_height = 0

    def bind(self, region_x: int, region_y: int, region_width: int, region_height: int) -> bool:
        """Bind the FBO and set up viewport for the pick region.

        Args:
            region_x: Left edge of pick region in viewport coords
            region_y: Bottom edge of pick region in viewport coords
            region_width: Width of pick region
            region_height: Height of pick region

        Returns:
            True if FBO is bound and ready, False otherwise
        """
        if not self._ensure_initialized(region_width, region_height):
            return False

        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        glViewport(0, 0, region_width, region_height)
        return True

    def unbind(self):
        """Unbind the FBO and restore default framebuffer."""
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def read_pixel(self, local_x: int, local_y: int) -> int:
        """Read a pixel from the FBO.

        Args:
            local_x: X coordinate within the FBO (not viewport coords)
            local_y: Y coordinate within the FBO (not viewport coords)

        Returns:
            32-bit RGBA value as integer
        """
        pixel = array([0, 0, 0, 0], 'B')
        glReadPixels(local_x, local_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
        return int(pixel.view('<I')[0])

    def read_depth(self, local_x: int, local_y: int) -> float:
        """Read depth value from the FBO.

        Args:
            local_x: X coordinate within the FBO
            local_y: Y coordinate within the FBO

        Returns:
            Depth value (0.0 to 1.0)
        """
        depth_pixel = array([[0.0]], 'f')
        glReadPixels(local_x, local_y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, depth_pixel)
        return float(depth_pixel[0][0])


class SelectionBufferFBO:
    """Full-resolution selection buffer using Multiple Render Targets (MRT).

    Renders object IDs alongside normal scene color during the forward pass,
    enabling zero-cost pick event processing via CPU-side buffer lookup.

    The buffer contains:
    - Color attachment 0: Normal scene color (blitted to screen)
    - Color attachment 1: Object ID encoded as RGBA8

    After each frame, the ID buffer is read back to CPU memory, and pick
    events are resolved by simple array lookup with no GPU interaction.
    """

    def __init__(self):
        """Initialize the selection buffer (lazy GPU resource creation)."""
        self.fbo = None
        self.color_texture = None       # Normal scene color (attachment 0)
        self.id_texture = None          # Object ID buffer (attachment 1)
        self.depth_renderbuffer = None
        self.width = 0
        self.height = 0
        self._initialized = False

        # CPU-side ID buffer (numpy array of uint8, RGBA format)
        self.id_buffer = None
        self.id_buffer_width = 0
        self.id_buffer_height = 0

        # CPU-side depth buffer (numpy array of float32)
        self.depth_buffer = None

        # Object ID to path mapping (rebuilt each frame)
        self.id_map = {}

    def ensure_size(self, width: int, height: int) -> bool:
        """Ensure FBO is created and sized to match viewport.

        Args:
            width: Viewport width
            height: Viewport height

        Returns:
            True if FBO is ready, False on failure
        """
        width = int(width)
        height = int(height)

        if width <= 0 or height <= 0:
            return False

        # Check if already correct size
        if self._initialized and width == self.width and height == self.height:
            return True

        # Need to recreate at new size
        self._cleanup()

        try:
            # Create FBO
            self.fbo = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)

            # Create color texture (attachment 0) - normal scene color
            self.color_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.color_texture)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                width, height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                GL_TEXTURE_2D, self.color_texture, 0
            )

            # Create ID texture (attachment 1) - object IDs as RGBA8
            self.id_texture = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, self.id_texture)
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_RGBA8,
                width, height, 0,
                GL_RGBA, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT1,
                GL_TEXTURE_2D, self.id_texture, 0
            )

            # Create depth renderbuffer
            self.depth_renderbuffer = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.depth_renderbuffer)
            glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, width, height)
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                GL_RENDERBUFFER, self.depth_renderbuffer
            )

            # Set draw buffers for MRT
            glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])

            # Check framebuffer completeness
            status = glCheckFramebufferStatus(GL_FRAMEBUFFER)
            if status != GL_FRAMEBUFFER_COMPLETE:
                log.warning("Selection buffer FBO incomplete: status=%s", status)
                self._cleanup()
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
                return False

            self.width = width
            self.height = height
            self._initialized = True

            # Pre-allocate CPU buffers
            self.id_buffer = array([0] * (width * height * 4), 'B')
            self.depth_buffer = array([0.0] * (width * height), 'f')
            self.id_buffer_width = width
            self.id_buffer_height = height

            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            log.debug("Selection buffer FBO created: %dx%d", width, height)
            return True

        except Exception as e:
            log.warning("Failed to create selection buffer FBO: %s", e)
            self._cleanup()
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            return False

    def _cleanup(self):
        """Clean up OpenGL resources."""
        if self.fbo is not None:
            try:
                glDeleteFramebuffers(1, [self.fbo])
            except Exception:
                pass
            self.fbo = None

        if self.color_texture is not None:
            try:
                glDeleteTextures([self.color_texture])
            except Exception:
                pass
            self.color_texture = None

        if self.id_texture is not None:
            try:
                glDeleteTextures([self.id_texture])
            except Exception:
                pass
            self.id_texture = None

        if self.depth_renderbuffer is not None:
            try:
                glDeleteRenderbuffers(1, [self.depth_renderbuffer])
            except Exception:
                pass
            self.depth_renderbuffer = None

        self._initialized = False
        self.width = 0
        self.height = 0

    def bind(self) -> bool:
        """Bind the FBO for rendering.

        Returns:
            True if bound successfully
        """
        if not self._initialized:
            return False
        glBindFramebuffer(GL_FRAMEBUFFER, self.fbo)
        # Ensure both attachments are written to
        glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])
        return True

    def unbind(self):
        """Unbind the FBO."""
        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def clear(self):
        """Clear both color attachments and depth buffer.

        Clears color attachment 0 to scene background (handled by caller)
        and color attachment 1 to zero (no object ID).
        """
        # Clear ID buffer to 0 (no object) - need to clear attachment 1 specifically
        # First clear depth
        glClear(GL_DEPTH_BUFFER_BIT)

        # Clear ID attachment to 0 by drawing to only that buffer
        glDrawBuffers(1, [GL_COLOR_ATTACHMENT1])
        glClearColor(0, 0, 0, 0)
        glClear(GL_COLOR_BUFFER_BIT)

        # Restore both draw buffers
        glDrawBuffers(2, [GL_COLOR_ATTACHMENT0, GL_COLOR_ATTACHMENT1])

    def read_id_buffer(self):
        """Read the ID buffer and depth buffer from GPU to CPU memory.

        Should be called after rendering is complete but before unbinding.
        Also reads depth buffer to enable 3D coordinate retrieval.
        """
        if not self._initialized or self.id_buffer is None:
            return

        # Read from attachment 1 (ID buffer)
        glReadBuffer(GL_COLOR_ATTACHMENT1)
        glReadPixels(
            0, 0, self.width, self.height,
            GL_RGBA, GL_UNSIGNED_BYTE, self.id_buffer
        )

        # Also read depth buffer for 3D coordinate unprojection
        if self.depth_buffer is not None:
            glReadPixels(
                0, 0, self.width, self.height,
                GL_DEPTH_COMPONENT, GL_FLOAT, self.depth_buffer
            )

    def blit_to_screen(self, target_width: int, target_height: int):
        """Blit the color buffer to the default framebuffer.

        Args:
            target_width: Screen width
            target_height: Screen height
        """
        if not self._initialized:
            return

        # Blit from our FBO to default framebuffer
        glBindFramebuffer(GL_READ_FRAMEBUFFER, self.fbo)
        glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0)
        glReadBuffer(GL_COLOR_ATTACHMENT0)

        glBlitFramebuffer(
            0, 0, self.width, self.height,
            0, 0, target_width, target_height,
            GL_COLOR_BUFFER_BIT,
            GL_NEAREST
        )

        glBindFramebuffer(GL_FRAMEBUFFER, 0)

    def lookup_object_id(self, x: int, y: int) -> int:
        """Look up object ID at pixel coordinates.

        Args:
            x: X coordinate (viewport space)
            y: Y coordinate (viewport space)

        Returns:
            Object ID at that pixel, or 0 if no object
        """
        if self.id_buffer is None:
            return 0

        x, y = int(x), int(y)
        if x < 0 or x >= self.id_buffer_width or y < 0 or y >= self.id_buffer_height:
            return 0

        # Calculate offset into RGBA buffer
        offset = (y * self.id_buffer_width + x) * 4
        r = self.id_buffer[offset]
        g = self.id_buffer[offset + 1]
        b = self.id_buffer[offset + 2]
        a = self.id_buffer[offset + 3]

        # Reconstruct 32-bit ID from RGBA
        return int(r) | (int(g) << 8) | (int(b) << 16) | (int(a) << 24)

    def lookup_depth(self, x: int, y: int) -> float:
        """Look up depth value at pixel coordinates.

        Args:
            x: X coordinate (viewport space)
            y: Y coordinate (viewport space)

        Returns:
            Depth value (0.0 to 1.0), or 1.0 if no depth data
        """
        if self.depth_buffer is None:
            return 1.0

        x, y = int(x), int(y)
        if x < 0 or x >= self.id_buffer_width or y < 0 or y >= self.id_buffer_height:
            return 1.0

        offset = y * self.id_buffer_width + x
        return float(self.depth_buffer[offset])

    def set_id_map(self, id_map: dict):
        """Set the object ID to path mapping for this frame."""
        self.id_map = id_map

    def get_path_at(self, x: int, y: int):
        """Get the object path at pixel coordinates.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Object path or empty list if no object
        """
        obj_id = self.lookup_object_id(x, y)
        return self.id_map.get(obj_id, [])


class SGObserver( object ):
    """Observer of a scenegraph that creates a flat set of paths

    Uses dispatcher watches to observe any changes to the (rendering)
    structure of a scenegraph and uses it to update an internal set
    of paths for all renderable objects in the scenegraph.
    """
    INTERESTING_TYPES = []
    def __init__( self, scene, contexts ):
        """Initialize the FlatPass for this scene and set of contexts

        scene -- the scenegraph to manage as a flattened hierarchy
        contexts -- set of (weakrefs to) contexts to be serviced,
            normally is a reference to Context.allContexts
        """
        self.scene = scene
        self.contexts = contexts
        self.paths = {
        }
        self.nodePaths = {}
        if scene:
            self.integrate( scene )
        connect(
            self.onChildAdd,
            signal = olist.OList.NEW_CHILD_EVT,
        )
        connect(
            self.onChildRemove,
            signal = olist.OList.DEL_CHILD_EVT,
        )
        connect(
            self.onSwitchChange,
            signal = switch.SWITCH_CHANGE_SIGNAL,
        )
    def integrate( self, node, parentPath=None ):
        """Integrate any children of node which are of interest"""
        if parentPath is None:
            parentPath = nodepath.NodePath( [] )
        todo = [ (node,parentPath) ]
        while todo:
            next,parents = todo.pop(0)
            path = parents + next
            np = self.npFor( next )
            np.append( path )
            if hasattr( next, 'bind' ):
                for context in self.contexts:
                    context = context()
                    if context is not None:
                        next.bind( context )
            _ = self.npFor(next)
            for typ in self.INTERESTING_TYPES:
                if isinstance( next, typ ):
                    self.paths.setdefault( typ, []).append( path )
            if hasattr(next, 'renderedChildren'):
                # watch for next's changes...
                for child in next.renderedChildren( ):
                    todo.append( (child,path) )
    def npFor( self, node ):
        """For some reason setdefault isn't working for the weakkeydict"""
        current = self.nodePaths.get( id(node) )
        if current is None:
            self.nodePaths[id(node)] = current = []
        return current
    def onSwitchChange( self, sender, value ):
        for path in self.npFor( sender ):
            for childPath in path.iterchildren():
                if childPath[-1] is not value:
                    childPath.invalidate()
            self.integrate( value, path )
        self.purge()
    def onChildAdd( self, sender, value ):
        """Sender has a new child named value"""
        if hasattr( sender, 'renderedChildren' ):
            children = sender.renderedChildren()
            if value in children:
                for path in self.npFor( sender ):
                    self.integrate( value, path )
    def onChildRemove( self, sender, value ):
        """Invalidate all paths where sender has value as its child IFF child no longer in renderedChildren"""
        if hasattr( sender, 'renderedChildren' ):
            children = sender.renderedChildren()
            if value not in children:
                for path in self.npFor( sender ):
                    for childPath in path.iterchildren():
                        if childPath[-1] is value:
                            childPath.invalidate()
                self.purge()
    def purge( self ):
        """Purge all references to path"""
        for key,values in self.paths.items():
            filtered = []
            for v in values:
                if not v.broken:
                    filtered.append( v )
                else:
                    np = self.npFor( v )
                    while v in np:
                        np.remove( v )
                    if not np:
                        try:
                            del self.nodePaths[id(v)]
                        except KeyError as err:
                            pass
            self.paths[key][:] = filtered

def get_modelview( shader, mode ):
    return mode.matrix 
def get_projection( shader, mode ):
    return mode.projection 
def get_modelproj( shader, mode ):
    return dot( mode.matrix, mode.projection )

def get_inv_modelview( shader, mode ):
    return dot( mode.viewPlatform.modelMatrix(inverse=True), mode.renderPath.transformMatrix( inverse=True ) )
def get_inv_projection( shader, mode ):
    return mode.viewPlatform.viewMatrix( mode.maxDepth, inverse=True )
def get_inv_modelproj( shader, mode ):
    mv = get_inv_modelview( shader, mode )
    proj = get_inv_projection( shader, mode )
    return dot( proj, mv )

class FlatPass( SGObserver ):
    """Flat rendering pass with a single function to render scenegraph

    Uses structural scenegraph observations to allow the actual
    rendering pass be a simple iteration over the paths known
    to be active in the scenegraph.

    Rendering Attributes:

        visible -- whether we are currently rendering a visible pass
        transparent -- whether we are currently doing a transparent pass
        lighting -- whether we currently are rendering a lit pass
        context -- context for which we are rendering
        cache -- cache of the context for which we are rendering
        projection -- projection matrix of current view platform
        modelView -- model-view matrix of current view platform
        viewport -- 4-component viewport definition for current context
        frustum -- viewing-frustum definition for current view platform
        MAX_LIGHTS -- queried maximum number of lights

        use_shaders -- whether to use shader-based rendering (core-profile compatible)
        shader_mode -- indicates shader mode is active (for geometry nodes to check)
        shader_program -- the VRML97ShaderProgram instance when use_shaders is True


        passCount -- not used, always set to 0 for code that expects
            a passCount to be available.
        transform -- ignored, legacy code only
    """
    passCount = 0
    visible = True
    transparent = False
    transform = True
    lighting = True
    lightingAmbient = True
    lightingDiffuse = True

    # this are now obsolete...
    selectNames = False
    selectForced = False

    cache = None

    # Shader-based rendering support
    use_shaders: bool = False
    shader_mode: bool = False  # Set True during shader render passes
    shader_program: Optional['VRML97ShaderProgram'] = None
    _shader_program_instance: Optional['VRML97ShaderProgram'] = None

    # Selection FBO for optimized picking (lazily initialized per instance)
    _selection_fbo: Optional[SelectionFBO] = None
    # MRT selection buffer for zero-cost picking (lazily initialized)
    _selection_buffer: Optional[SelectionBufferFBO] = None
    # Enable MRT-based selection (vs legacy per-pick rendering)
    use_mrt_selection: bool = True
    
    _UNIFORM_NAMES = '''mat_modelview inv_modelview tps_modelview itp_modelview 
        mat_projection inv_projection tps_projection itp_projection
        mat_modelproj inv_modelproj tps_modelproj itp_modelproj'''.split()

    _uniforms = None
    @property 
    def uniforms( self ):
        if self._uniforms is None:
            self._uniforms = []
            for name in self._UNIFORM_NAMES:
                attr = 'uniform_%s'%(name,)
                uniform = shaders.FloatUniformm4( name=name )
                self._uniforms.append( uniform )
                setattr( self, attr, uniform )
                if name.startswith( 'tps_' ) or name.startswith( 'itp_' ):
                    uniform.NEED_TRANSPOSE = True 
                else:
                    uniform.NEED_TRANSPOSE = False
                if name.startswith( 'inv_' ) or name.startswith( 'itp_' ):
                    uniform.NEED_INVERSE = True 
                else:
                    uniform.NEED_INVERSE = False 
            # now set up the lazy calculation operations 
            self.uniform_mat_modelview.currentValue = get_modelview
            self.uniform_mat_projection.currentValue = get_projection
            self.uniform_mat_modelproj.currentValue = get_modelproj
            self.uniform_tps_modelview.currentValue = get_modelview
            self.uniform_tps_projection.currentValue = get_projection
            self.uniform_tps_modelproj.currentValue = get_modelproj
            
            self.uniform_inv_modelview.currentValue = get_inv_modelview
            self.uniform_inv_projection.currentValue = get_inv_projection
            self.uniform_inv_modelproj.currentValue = get_inv_modelproj
            self.uniform_itp_modelview.currentValue = get_inv_modelview
            self.uniform_itp_projection.currentValue = get_inv_projection
            self.uniform_itp_modelproj.currentValue = get_inv_modelproj
            
        return self._uniforms
    
    def applyUniforms( self, shader ):
        """Apply our uniforms to the shader as appropriate"""
        for uniform in self.uniforms:
            uniform.render( shader, self )

    def getShaderProgram(self) -> 'VRML97ShaderProgram':
        """Get or create the shader program for this render pass.

        Returns:
            VRML97ShaderProgram instance
        """
        if self._shader_program_instance is None:
            from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
            self._shader_program_instance = VRML97ShaderProgram()
        return self._shader_program_instance

    def setupShaderLights(self, matrix: Any) -> None:
        """Set up lights for shader-based rendering.

        Args:
            matrix: Base modelview matrix (camera view matrix)
        """
        from OpenGLContext.passes.shaderpass import configure_light_from_node

        shader = self.shader_program
        shader.use(lit=True)  # Ensure shader is bound before setting uniforms
        light_count = 0
        light_paths = self.paths.get(nodetypes.Light, ())

        for path in light_paths:
            if light_count >= shader.MAX_LIGHTS:
                break
            tmatrix = path.transformMatrix()
            light_node = path[-1]
            if hasattr(light_node, 'on') and light_node.on:
                # Transform light to eye space (combine light's transform with view matrix)
                # This matches how fixed-function glLightfv works - it transforms
                # the light position/direction by the current modelview matrix
                light_matrix = dot(tmatrix, matrix)
                configure_light_from_node(shader, light_count, light_node, light_matrix)
                light_count += 1

        if light_count == 0:
            # Set default VRML97 headlight (direction already in eye space)
            shader.set_default_light()
            log.debug("Using default headlight")
        else:
            shader.set_num_lights(light_count)
            log.debug("Set up %d lights", light_count)

    def shaderBackgroundRender(self, vp: Any, matrix: Any) -> None:
        """Render background for shader mode.

        Uses the shader-based RenderShader method on background nodes
        when available, falling back to legacy rendering for backgrounds
        that don't support shader rendering (e.g. CubeBackground already
        has its own shader implementation).

        Args:
            vp: View platform
            matrix: Base matrix
        """
        bPath = self.currentBackground()
        if bPath is not None:
            # Set up matrix for background rendering
            self.matrix = dot(
                vp.quaternion.matrix(dtype='f'),
                bPath.transformMatrix(translate=0, scale=0, rotate=1)
            )
            background = bPath[-1]
            # Check if background has shader rendering capability
            if hasattr(background, 'RenderShader'):
                background.RenderShader(mode=self, clear=True)
            else:
                # For CubeBackground or other backgrounds with their own shader
                background.Render(mode=self, clear=True)
        else:
            # Default VRML background is black
            glClearColor(0.0, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    def shaderRenderOpaque(self, toRender: List, id_map: Optional[Dict] = None) -> None:
        """Render opaque geometry using shaders.

        Args:
            toRender: List of (sortKey, mvmatrix, tmatrix, bvolume, path) tuples
            id_map: Optional dict to populate with {object_id: path} for MRT selection.
                   If provided, object IDs will be set for each rendered object.
        """
        self.transparent = False
        debugFrustum = self.context.contextDefinition.debugBBox

        shader = self.shader_program
        shader.use(lit=True)

        for obj_index, (key, mvmatrix, tmatrix, bvolume, path) in enumerate(toRender):
            if not key[0]:  # Not transparent
                self.matrix = mvmatrix
                self.renderPath = path

                # Set matrices for this object
                shader.set_matrices(mvmatrix, self.projection)

                # Set object ID for MRT selection buffer
                if id_map is not None:
                    # Use index+1 so 0 means "no object" (background)
                    object_id = obj_index + 1
                    shader.set_object_id(object_id)
                    id_map[object_id] = path

                try:
                    path[-1].Render(mode=self)
                    if debugFrustum and bvolume:
                        bvolume.debugRender()
                except Exception as err:
                    log.error(
                        "Failure in shader opaque render: %s",
                        getTraceback(err),
                    )

        shader.unuse()

    def shaderRenderTransparent(self, toRender: List, id_map: Optional[Dict] = None) -> None:
        """Render transparent geometry using shaders.

        Args:
            toRender: List of (sortKey, mvmatrix, tmatrix, bvolume, path) tuples
            id_map: Optional dict to populate with {object_id: path} for MRT selection.
                   If provided, object IDs will be set for each rendered object.
        """
        self.transparent = True
        setup = False
        debugFrustum = self.context.contextDefinition.debugBBox

        shader = self.shader_program

        try:
            for obj_index, (key, mvmatrix, tmatrix, bvolume, path) in enumerate(toRender):
                if key[0]:  # Transparent
                    if not setup:
                        setup = True
                        shader.use(lit=True)
                        glEnable(GL_BLEND)
                        glBlendFunc(GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA)
                        glDepthMask(0)
                        glDepthFunc(GL_LEQUAL)

                    self.matrix = mvmatrix
                    self.renderPath = path

                    # Set matrices for this object
                    shader.set_matrices(mvmatrix, self.projection)

                    # Set object ID for MRT selection buffer
                    if id_map is not None:
                        # Use index+1 so 0 means "no object" (background)
                        object_id = obj_index + 1
                        shader.set_object_id(object_id)
                        id_map[object_id] = path

                    try:
                        path[-1].RenderTransparent(mode=self)
                        if debugFrustum and bvolume:
                            bvolume.debugRender()
                    except Exception as err:
                        log.error(
                            "Failure in shader transparent render: %s",
                            getTraceback(err),
                        )
        finally:
            self.transparent = False
            if setup:
                shader.unuse()
                glDisable(GL_BLEND)
                glDepthMask(1)
                glDepthFunc(GL_LEQUAL)
                glEnable(GL_DEPTH_TEST)

    def shaderRenderFrameCounter(self, context) -> None:
        """Render the frame counter using shader-based text rendering.

        Uses the DejaVu Sans Mono texture atlas for core-profile compatible
        text rendering. Displays green text on a dark semi-transparent background
        for visibility on any scene.
        """
        if not context.frameCounter:
            return

        try:
            from OpenGLContext.scenegraph.text.shadertext import get_text_renderer

            # Get viewport dimensions
            tx, ty = context.getViewPort()
            if not tx or not ty:
                return

            # Get frame counter data
            count, avg, last = context.frameCounter.summary()
            last *= 1000  # Convert to milliseconds

            # Format the text
            text = f'fps avg:{avg:.1f}\ncurr ms: {last:.0f}'

            # Get a text renderer (use 14px font for frame counter)
            text_renderer = get_text_renderer(14)

            # Render at bottom-left corner with margin
            margin = 10
            y_pos = margin + text_renderer.char_height * 2  # Room for 2 lines

            # Use green text on dark opaque background for visibility
            text_renderer.render_text(
                text,
                x=margin,
                y=y_pos,
                shader_program=self.shader_program,
                viewport_width=tx,
                viewport_height=ty,
                color=(0.0, 1.0, 0.0, 1.0),  # Bright green text
                background_color=(0.1, 0.1, 0.1, 1.0),  # Dark opaque background
                scale=1.0
            )
        except Exception as e:
            log.debug("Failed to render frame counter: %s", e)

    def shaderSelectRender(self, mode: Any, toRender: List, events: Dict) -> None:
        """Render for selection using unlit shader.

        Args:
            mode: Render mode
            toRender: Render set
            events: Pick events
        """
        glClearColor(0, 0, 0, 0)
        glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)

        self.visible = False
        self.transparent = False
        self.lighting = False
        self.textured = False

        matrix = self.matrix
        id_map = {}

        pickPoints = {}
        min_x, min_y = self.getViewport()[2:]
        max_x, max_y = 0, 0
        pickSize = 2
        offset = pickSize // 2

        for event in events.values():
            x, y = key = tuple(event.getPickPoint())
            pickPoints.setdefault(key, []).append(event)
            min_x = min((x - offset, min_x))
            max_x = max((x + offset, max_x))
            min_y = min((y - offset, min_y))
            max_y = max((y + offset, max_y))

        min_x = int(max((0, min_x)))
        min_y = int(max((0, min_y)))
        if max_x < min_x or max_y < min_y:
            return

        debugSelection = mode.context.contextDefinition.debugSelection

        if not debugSelection:
            glScissor(min_x, min_y, int(max_x) - min_x, int(max_y) - min_y)
            glEnable(GL_SCISSOR_TEST)

        shader = self.shader_program
        shader.use(lit=False)  # Use unlit shader

        try:
            for obj_id, (key, mvmatrix, tmatrix, bvolume, path) in enumerate(toRender):
                obj_id = (obj_id + 1) << 12

                # Convert ID to color (RGBA bytes)
                r = (obj_id >> 0) & 0xFF
                g = (obj_id >> 8) & 0xFF
                b = (obj_id >> 16) & 0xFF
                a = 255

                # Ensure unlit shader is active (geometry may have switched shaders)
                shader.use(lit=False)
                shader.set_solid_color((r / 255.0, g / 255.0, b / 255.0, a / 255.0))
                shader.set_matrices(mvmatrix, self.projection, program=shader.unlit_program)

                self.matrix = mvmatrix
                self.renderPath = path
                path[-1].Render(mode=self)
                id_map[obj_id] = path

            shader.unuse()

            pixel = array([0, 0, 0, 0], 'B')
            depth_pixel = array([[0]], 'f')

            for point, eventSet in pickPoints.items():
                # Convert coordinates to integers for glReadPixels
                px, py = int(point[0]), int(point[1])
                glReadPixels(px, py, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
                lpixel = int(pixel.view('<I')[0])
                paths = id_map.get(lpixel, [])
                event.setObjectPaths([paths])
                glReadPixels(
                    px, py, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, depth_pixel
                )
                event.viewCoordinate = px, py, depth_pixel[0][0]
                event.modelViewMatrix = matrix
                event.projectionMatrix = self.projection
                event.viewport = self.viewport
                if hasattr(mode.context, 'ProcessEvent'):
                    mode.context.ProcessEvent(event)
        finally:
            glDisable(GL_SCISSOR_TEST)

    def _createPickFrustum(self, pick_x: float, pick_y: float, pick_size: int = 4) -> 'frustum.Frustum':
        """Create a narrow frustum for pick region culling.

        Args:
            pick_x: Pick point X coordinate (viewport coordinates)
            pick_y: Pick point Y coordinate (viewport coordinates)
            pick_size: Size of the pick region in pixels

        Returns:
            Frustum object for the pick region
        """
        from OpenGLContext.arrays import identity, zeros, sqrt, reshape, compress, ravel

        # Get viewport dimensions
        vp = self.getViewport()
        vp_x, vp_y, vp_w, vp_h = vp

        # Calculate normalized device coordinates for pick region
        # NDC ranges from -1 to 1
        half_size = pick_size / 2.0

        # Convert pick region to NDC
        left = 2.0 * (pick_x - half_size - vp_x) / vp_w - 1.0
        right = 2.0 * (pick_x + half_size - vp_x) / vp_w - 1.0
        bottom = 2.0 * (pick_y - half_size - vp_y) / vp_h - 1.0
        top = 2.0 * (pick_y + half_size - vp_y) / vp_h - 1.0

        # Clamp to valid range
        left = max(-1.0, min(1.0, left))
        right = max(-1.0, min(1.0, right))
        bottom = max(-1.0, min(1.0, bottom))
        top = max(-1.0, min(1.0, top))

        # Create pick projection matrix by scaling the current projection
        # to focus on just the pick region
        proj = self.projection.copy()

        # Scale and translate to zoom into the pick region
        scale_x = 2.0 / (right - left) if right != left else 1.0
        scale_y = 2.0 / (top - bottom) if top != bottom else 1.0
        offset_x = -(right + left) / (right - left) if right != left else 0.0
        offset_y = -(top + bottom) / (top - bottom) if top != bottom else 0.0

        # Apply the pick matrix transformation
        pick_matrix = identity(4, 'f')
        pick_matrix[0, 0] = scale_x
        pick_matrix[1, 1] = scale_y
        pick_matrix[3, 0] = offset_x * scale_x
        pick_matrix[3, 1] = offset_y * scale_y

        # Combine pick matrix with projection
        pick_proj = dot(proj, pick_matrix)

        # Combine with modelview to get the full pick frustum matrix
        pick_modelproj = dot(self.modelView, pick_proj)

        # Create frustum from this matrix
        return frustum.Frustum.fromViewingMatrix(pick_modelproj, normalize=1)

    def _filterObjectsForPick(self, toRender: List, pick_points: List[Tuple[float, float]],
                               pick_size: int = 8) -> List:
        """Filter render set to only objects potentially under pick points.

        Uses bounding volume vs pick frustum intersection tests to quickly
        reject objects that cannot be under any pick point.

        Args:
            toRender: Full render set
            pick_points: List of (x, y) pick coordinates
            pick_size: Size of pick region to test against

        Returns:
            Filtered list of objects that may be under pick points
        """
        if not toRender or not pick_points:
            return toRender

        # Calculate bounding box of all pick points
        min_x = min(p[0] for p in pick_points)
        max_x = max(p[0] for p in pick_points)
        min_y = min(p[1] for p in pick_points)
        max_y = max(p[1] for p in pick_points)

        # Expand by pick size
        half_size = pick_size / 2.0
        min_x -= half_size
        max_x += half_size
        min_y -= half_size
        max_y += half_size

        # Create a single frustum for the entire pick region
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        region_size = max(max_x - min_x, max_y - min_y)

        pick_frustum = self._createPickFrustum(center_x, center_y, int(region_size) + 1)

        # Filter objects using bounding volume visibility test
        filtered = []
        for record in toRender:
            key, mvmatrix, tmatrix, bvolume, path = record
            if bvolume is not None:
                # Test if bounding volume is visible in pick frustum
                try:
                    visible = bvolume.visible(
                        pick_frustum, tmatrix.astype('f'),
                        occlusion=False,
                        mode=self
                    )
                    if visible:
                        filtered.append(record)
                except Exception:
                    # If visibility test fails, include the object to be safe
                    filtered.append(record)
            else:
                # No bounding volume, must include
                filtered.append(record)

        log.debug("Pick culling: %d/%d objects passed filter", len(filtered), len(toRender))
        return filtered

    def _getSelectionFBO(self) -> SelectionFBO:
        """Get or create the selection FBO for this pass instance."""
        if self._selection_fbo is None:
            self._selection_fbo = SelectionFBO(max_width=512, max_height=512)
        return self._selection_fbo

    def _getSelectionBuffer(self) -> SelectionBufferFBO:
        """Get or create the MRT selection buffer for this pass instance."""
        if self._selection_buffer is None:
            self._selection_buffer = SelectionBufferFBO()
        return self._selection_buffer

    # Cache for hasMouseMoveHandlers check (cleared each frame)
    _has_mousemove_handlers: Optional[bool] = None

    def _optimizePickEvents(self, context: Any, events: Dict) -> Dict:
        """Optimize pick events by filtering and de-duplicating.

        Optimizations:
        1. Skip mouse-move events if no mousemove/mousein/mouseout handlers registered
        2. De-duplicate events to only keep one per unique pixel coordinate

        Args:
            context: The rendering context
            events: Dictionary of pick events

        Returns:
            Optimized dictionary of pick events (may be empty)
        """
        if not events:
            return events

        original_count = len(events)

        # Check if we have mouse-move handlers (cache per frame for performance)
        if self._has_mousemove_handlers is None:
            self._has_mousemove_handlers = context.hasMouseMoveHandlers()

        has_move_handlers = self._has_mousemove_handlers

        # Filter and de-duplicate events
        # Key: (type, pixel_x, pixel_y) -> event (keeps latest)
        optimized = {}
        filtered_move_count = 0

        for key, event in events.items():
            event_type = getattr(event, 'type', 'unknown')

            # Skip mouse-move events if no handlers are registered
            if event_type == 'mousemove' and not has_move_handlers:
                filtered_move_count += 1
                continue

            # De-duplicate: use pixel coordinates as part of the key
            # This keeps only the latest event per unique (type, x, y)
            pick_point = event.getPickPoint()
            pixel_x, pixel_y = int(pick_point[0]), int(pick_point[1])
            dedup_key = (event_type, pixel_x, pixel_y)

            # Always keep the latest event for each unique position
            optimized[dedup_key] = event

        # Log optimization results if significant
        final_count = len(optimized)
        if original_count > 1 and (filtered_move_count > 0 or final_count < original_count):
            log.debug(
                "Pick event optimization: %d -> %d events "
                "(filtered %d moves, deduped %d)",
                original_count, final_count,
                filtered_move_count,
                original_count - filtered_move_count - final_count
            )

        return optimized

    def processPickEventsFromBuffer(self, mode: Any, events: Dict) -> None:
        """Process pick events using the cached MRT selection buffer.

        This is the fast path - no GPU rendering, just CPU array lookups.
        Also retrieves depth values for 3D coordinate unprojection.

        Args:
            mode: Render mode
            events: Pick events dict
        """
        if not events:
            return

        selection_buffer = self._getSelectionBuffer()
        if not selection_buffer._initialized or selection_buffer.id_buffer is None:
            # Buffer not ready, fall back to legacy method
            return

        matrix = self.matrix

        for event in events.values():
            x, y = event.getPickPoint()
            x, y = int(x), int(y)

            # Look up object ID and depth from cached buffer
            path = selection_buffer.get_path_at(x, y)
            depth = selection_buffer.lookup_depth(x, y)

            # Set event properties
            event.setObjectPaths([path] if path else [[]])
            event.viewCoordinate = x, y, depth
            event.modelViewMatrix = matrix
            event.projectionMatrix = self.projection
            event.viewport = self.viewport

            if hasattr(mode.context, 'ProcessEvent'):
                mode.context.ProcessEvent(event)

    def _createPickProjection(self, pick_region: Tuple[int, int, int, int],
                              viewport: Tuple[int, int, int, int]) -> 'array':
        """Create a pick projection matrix that zooms into the pick region.

        Args:
            pick_region: (x, y, width, height) of pick region in viewport coords
            viewport: (x, y, width, height) of the full viewport

        Returns:
            Modified projection matrix focused on pick region
        """
        from OpenGLContext.arrays import identity

        px, py, pw, ph = pick_region
        vx, vy, vw, vh = viewport

        # Calculate the scale factors to zoom into the pick region
        scale_x = vw / pw if pw > 0 else 1.0
        scale_y = vh / ph if ph > 0 else 1.0

        # Calculate the translation to center on the pick region
        # The center of the pick region in viewport coords
        pick_center_x = px + pw / 2.0
        pick_center_y = py + ph / 2.0

        # The center of the viewport
        view_center_x = vx + vw / 2.0
        view_center_y = vy + vh / 2.0

        # Translation in NDC space
        trans_x = (view_center_x - pick_center_x) / (vw / 2.0) * scale_x
        trans_y = (view_center_y - pick_center_y) / (vh / 2.0) * scale_y

        # Create pick matrix
        pick_matrix = identity(4, 'f')
        pick_matrix[0, 0] = scale_x
        pick_matrix[1, 1] = scale_y
        pick_matrix[3, 0] = trans_x
        pick_matrix[3, 1] = trans_y

        # Combine with original projection
        return dot(self.projection, pick_matrix)

    def shaderSelectRenderOptimized(self, mode: Any, toRender: List, events: Dict) -> None:
        """Optimized selection render processing each pick point individually.

        For each pick point:
        1. Pre-compute screen-space bounding boxes for all objects (done once)
        2. For each pick point, find objects whose screen bbox contains the point
        3. Render only those few objects (typically 1-10) with unique IDs
        4. Read back the single pixel

        This dramatically reduces rendering load compared to batch processing.

        Args:
            mode: Render mode
            toRender: Render set
            events: Pick events
        """
        if not events:
            return

        self.visible = False
        self.transparent = False
        self.lighting = False
        self.textured = False

        matrix = self.matrix
        vp = self.getViewport()
        vp_w, vp_h = float(vp[2]), float(vp[3])
        debugSelection = mode.context.contextDefinition.debugSelection

        # Collect pick points grouped by location
        pickPoints = {}
        for event in events.values():
            x, y = key = tuple(event.getPickPoint())
            pickPoints.setdefault(key, []).append(event)

        if not pickPoints:
            return

        # Pre-compute screen-space bounding boxes for all objects (done once)
        # This is the key optimization - project all bounding volumes to screen space
        screen_bboxes = self._computeScreenSpaceBBoxes(toRender, vp_w, vp_h)

        # Set up shader
        shader = self.shader_program
        shader.use(lit=False)

        # Use a tiny FBO (3x3) for each pick point
        selection_fbo = self._getSelectionFBO()
        pick_size = 3
        half_pick = pick_size // 2

        pixel = array([0, 0, 0, 0], 'B')
        depth_pixel = array([[0]], 'f')

        try:
            # Process each unique pick point
            for point, eventSet in pickPoints.items():
                px, py = point

                # Skip if outside viewport
                if px < 0 or py < 0 or px >= vp_w or py >= vp_h:
                    for event in eventSet:
                        event.setObjectPaths([[]])
                    continue

                # Find objects whose screen bounding box contains this pick point
                # This is a simple 2D point-in-rect test
                hit_indices = []
                for idx, bbox in enumerate(screen_bboxes):
                    if bbox is None:
                        # No bounding volume - must include
                        hit_indices.append(idx)
                    else:
                        min_x, min_y, max_x, max_y = bbox
                        if min_x <= px <= max_x and min_y <= py <= max_y:
                            hit_indices.append(idx)

                if not hit_indices:
                    # No objects under this point
                    for event in eventSet:
                        event.setObjectPaths([[]])
                    continue

                # Set up tiny FBO for this pick point
                region_x = int(max(0, px - half_pick))
                region_y = int(max(0, py - half_pick))
                region_w = min(pick_size, int(vp_w) - region_x)
                region_h = min(pick_size, int(vp_h) - region_y)

                use_fbo = not debugSelection and selection_fbo.bind(
                    region_x, region_y, region_w, region_h
                )

                if use_fbo:
                    pick_region = (region_x, region_y, region_w, region_h)
                    pick_projection = self._createPickProjection(pick_region, vp)
                    glClearColor(0, 0, 0, 0)
                    glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
                else:
                    pick_projection = self.projection
                    if not debugSelection:
                        glScissor(region_x, region_y, region_w, region_h)
                        glEnable(GL_SCISSOR_TEST)
                    glClearColor(0, 0, 0, 0)
                    glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)

                # Render only the objects that may be under this pick point
                id_map = {}
                for obj_id, idx in enumerate(hit_indices):
                    key, mvmatrix, tmatrix, bvolume, path = toRender[idx]
                    color_id = (obj_id + 1) << 12

                    r = (color_id >> 0) & 0xFF
                    g = (color_id >> 8) & 0xFF
                    b = (color_id >> 16) & 0xFF

                    shader.use(lit=False)
                    shader.set_solid_color((r / 255.0, g / 255.0, b / 255.0, 1.0))
                    shader.set_matrices(mvmatrix, pick_projection, program=shader.unlit_program)

                    self.matrix = mvmatrix
                    self.renderPath = path
                    path[-1].Render(mode=self)
                    id_map[color_id] = path

                # Read back the center pixel
                if use_fbo:
                    read_x = int(px) - region_x
                    read_y = int(py) - region_y
                    read_x = max(0, min(region_w - 1, read_x))
                    read_y = max(0, min(region_h - 1, read_y))
                else:
                    read_x, read_y = int(px), int(py)

                glReadPixels(read_x, read_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
                lpixel = int(pixel.view('<I')[0])
                paths = id_map.get(lpixel, [])

                glReadPixels(read_x, read_y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, depth_pixel)

                for event in eventSet:
                    event.setObjectPaths([paths])
                    event.viewCoordinate = int(px), int(py), depth_pixel[0][0]
                    event.modelViewMatrix = matrix
                    event.projectionMatrix = self.projection
                    event.viewport = self.viewport
                    if hasattr(mode.context, 'ProcessEvent'):
                        mode.context.ProcessEvent(event)

                # Clean up for this pick point
                if use_fbo:
                    selection_fbo.unbind()
                else:
                    glDisable(GL_SCISSOR_TEST)

        finally:
            shader.unuse()
            # Restore viewport
            glViewport(*[int(v) for v in vp])

    def _computeScreenSpaceBBoxes(self, toRender: List, vp_w: float, vp_h: float) -> List:
        """Pre-compute screen-space bounding boxes for all objects.

        Projects each object's bounding volume corners to screen space and
        computes the 2D bounding box.

        Args:
            toRender: Render set
            vp_w: Viewport width
            vp_h: Viewport height

        Returns:
            List of (min_x, min_y, max_x, max_y) tuples or None for objects without bounds
        """
        result = []
        modelViewProjection = dot(self.modelView, self.projection)

        for record in toRender:
            key, mvmatrix, tmatrix, bvolume, path = record

            if bvolume is None:
                result.append(None)
                continue

            try:
                points = bvolume.getPoints()
                if len(points) == 0:
                    result.append(None)
                    continue

                # Transform to clip space: point * modelview * projection
                mvp = dot(mvmatrix, self.projection)

                if points.shape[1] == 3:
                    points_4d = concatenate([points, ones((len(points), 1), dtype='f')], axis=1)
                else:
                    points_4d = points

                clip_points = dot(points_4d, mvp)

                # Perspective divide to NDC
                # Filter out points behind camera (w <= 0)
                valid_mask = clip_points[:, 3] > 0.001
                if not valid_mask.any():
                    # All points behind camera - skip
                    result.append(None)
                    continue

                valid_points = clip_points[valid_mask]
                ndc = valid_points[:, :3] / valid_points[:, 3:4]

                # Convert NDC to screen coordinates
                screen_x = (ndc[:, 0] + 1.0) * 0.5 * vp_w
                screen_y = (ndc[:, 1] + 1.0) * 0.5 * vp_h

                min_x = float(screen_x.min())
                max_x = float(screen_x.max())
                min_y = float(screen_y.min())
                max_y = float(screen_y.max())

                result.append((min_x, min_y, max_x, max_y))

            except Exception:
                result.append(None)

        return result

    INTERESTING_TYPES = [
        nodetypes.Rendering,
        nodetypes.Bindable,
        nodetypes.Light,
        nodetypes.Traversable,
        nodetypes.Background,
        nodetypes.TimeDependent,
        nodetypes.Fog,
        nodetypes.Viewpoint,
        nodetypes.NavigationInfo,
    ]
    def currentBackground( self ):
        """Find our current background node"""
        paths = self.paths.get( nodetypes.Background, () )
        for background in paths:
            if background[-1].bound:
                return background
        if paths:
            current = paths[0]
            current[-1].bound = 1
            return current
        return None

    def renderSet( self, matrix ):
        """Calculate ordered rendering set to display"""
        # ordered set of things to work with...
        toRender = []
        for path in self.paths.get( nodetypes.Rendering, ()):
            tmatrix = path.transformMatrix()
            mvmatrix = dot(tmatrix,matrix)
            sortKey = path[-1].sortKey( self, tmatrix )
            if hasattr( path[-1], 'boundingVolume' ):
                bvolume = path[-1].boundingVolume( self )
            else:
                bvolume = None
            toRender.append( (sortKey, mvmatrix,tmatrix,bvolume, path ) )
        toRender = self.frustumVisibilityFilter( toRender )
        toRender.sort( key = lambda x: x[0])
        return toRender

    def greatestDepth( self, toRender ):
        # experimental: adjust our frustum to smaller depth based on
        # the projected z-depth of bbox points...
        maxDepth = 0
        for (key,mv,tm,bv,path) in toRender:
            try:
                points = bv.getPoints()
            except (AttributeError,boundingvolume.UnboundedObject) as err:
                return 0
            else:
                translated = dot( points, mv )
                maxDepth = min((maxDepth, min( translated[:,2] )))
        # 101 is to allow the 100 unit background to show... sigh
        maxDepth = max((maxDepth,101))
        return -(maxDepth*1.01)

    def frustumVisibilityFilter( self, records ):
        """Filter records for visibility using frustum planes

        This does per-object culling based on frustum lookups
        rather than object query values.  It should be fast
        *if* the frustcullaccel module is available, if not
        it will be dog-slow.
        """
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
    
    _render_mode_logged = False

    def Render( self, context, mode ):
        """Render the geometry attached to this flat-renderer's scenegraph"""
        # Log render mode once on first frame
        if not self._render_mode_logged:
            self._render_mode_logged = True
            profile = getattr(context.contextDefinition, 'profile', 'unknown')
            render_mode = 'SHADER' if self.use_shaders else 'LEGACY'
            mrt_mode = 'MRT' if (self.use_shaders and self.use_mrt_selection) else 'LEGACY'
            log.info(f"Render mode: {render_mode}, Profile: {profile}, Selection: {mrt_mode}")

        # Reset per-frame caches
        self._has_mousemove_handlers = None

        # clear the projection matrix set up by legacy sg
        matrix = self.getModelView()
        self.matrix = matrix

        toRender = self.renderSet( matrix )
        maxDepth = self.maxDepth = self.greatestDepth( toRender )
        vp = context.getViewPlatform()
        if maxDepth:
            self.projection = vp.viewMatrix(maxDepth)

        # Set up shader mode if enabled
        if self.use_shaders:
            self.shader_program = self.getShaderProgram()
            self.shader_program.compile()
            self.shader_mode = True
        else:
            self.shader_mode = False
            self.shader_program = None

        # Get pick events
        events = context.getPickEvents()
        debugSelection = mode.context.contextDefinition.debugSelection

        # Optimize events: filter mouse-move if no handlers, de-duplicate by pixel
        if events:
            events = self._optimizePickEvents(context, events)

        # Log pick event count for debugging
        if events:
            log.debug("Render: processing %d pick events", len(events))

        # MRT selection path: process pick events from PREVIOUS frame's buffer
        # This gives one-frame latency but zero per-pick GPU cost
        use_mrt = self.use_shaders and self.use_mrt_selection and not debugSelection
        if use_mrt and events:
            self.processPickEventsFromBuffer(mode, events)
            context.pickEvents.clear()
        elif events or debugSelection:
            # Legacy selection path
            if self.use_shaders:
                self.shaderSelectRenderOptimized(mode, toRender, events)
            else:
                self.selectRender( mode, toRender, events )
            context.pickEvents.clear()

        # Load the root
        if not debugSelection:
            self.matrix = matrix
            self.visible = True
            self.transparent = False
            self.lighting = True
            self.textured = True

            # Set up generic "geometric" rendering parameters
            glFrontFace( GL_CCW )
            glEnable(GL_DEPTH_TEST)
            glDepthFunc( GL_LESS )
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            if self.use_shaders:
                # Set up MRT selection buffer if enabled
                selection_buffer = None
                id_map = None
                vp_size = context.getViewPort()

                if use_mrt:
                    selection_buffer = self._getSelectionBuffer()
                    if selection_buffer.ensure_size(int(vp_size[0]), int(vp_size[1])):
                        id_map = {}
                        selection_buffer.bind()
                        selection_buffer.clear()

                # Shader-based rendering path (core-profile compatible)
                self.shaderBackgroundRender(vp, matrix)
                self.setupShaderLights(matrix)
                self.shader_program.set_default_material()
                self.shader_program.set_scene_ambient((0.2, 0.2, 0.2))
                self.shaderRenderOpaque(toRender, id_map)
                self.shaderRenderTransparent(toRender, id_map)

                # Finalize MRT selection buffer
                if selection_buffer is not None and id_map is not None:
                    # Read back ID buffer for next frame's pick processing
                    selection_buffer.read_id_buffer()
                    selection_buffer.set_id_map(id_map)
                    # Blit color buffer to screen
                    selection_buffer.blit_to_screen(int(vp_size[0]), int(vp_size[1]))

                # Render frame counter to screen (not to MRT buffer)
                if context.frameCounter and context.frameCounter.display:
                    self.shaderRenderFrameCounter(context)
            else:
                # Legacy fixed-function rendering path
                self.legacyBackgroundRender( vp,matrix )
                self.legacyLightRender( matrix )
                self.renderOpaque( toRender )
                self.renderTransparent( toRender )

                # Render frame counter if enabled
                if context.frameCounter and context.frameCounter.display:
                    context.frameCounter.Render(context)

        context.SwapBuffers()
        self.matrix = matrix
        self.shader_mode = False  # Reset after render

    def legacyBackgroundRender( self, vp, matrix ):
        """Do legacy background rendering"""
        bPath = self.currentBackground( )
        if bPath is not None:
            # legacy...
            self.matrix = dot(
                vp.quaternion.matrix( dtype='f'),
                bPath.transformMatrix(translate=0,scale=0, rotate=1 )
            )
            bPath[-1].Render( mode=self, clear=True )
        else:
            ### default VRML background is black
            glClearColor(0.0,0.0,0.0,1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )

    def legacyLightRender( self, matrix ):
        """Do legacy light-rendering operation"""
        id = 0
        for path in self.paths.get( nodetypes.Light, ()):
            tmatrix = path.transformMatrix()

            localMatrix = dot(tmatrix,matrix)
            self.matrix = localMatrix
            self.renderPath = path
            #glLoadMatrixf( localMatrix )

            #path[-1].Light( GL_LIGHT0+id, mode=self )
            id += 1
            if id >= (self.MAX_LIGHTS-1):
                break
        if not id:
            # default VRML lighting...
            from OpenGLContext.scenegraph import light
            l = light.DirectionalLight( direction = (0,0,-1.0))
#            glLoadMatrixf( matrix )
#            l.Light( GL_LIGHT0, mode = self )
        self.matrix = matrix
    
    def renderGeometry( self, mvmatrix ):
        """Render geometry present in the given mvmatrix
        
        Intended for use in e.g. setting up a light texture, this 
        operation *just* does a query to find the visible objects 
        and then passes them (all) to renderOpaque
        """
        toRender = self.renderSet( mvmatrix )
        self.renderOpaque( toRender )
        self.renderTransparent( toRender )

    def renderOpaque( self, toRender ):
        """Render the opaque geometry from toRender (in reverse order)"""
        self.transparent = False
        debugFrustum = self.context.contextDefinition.debugBBox
        for key,mvmatrix,tmatrix,bvolume,path in toRender:
            if not key[0]:
                self.matrix = mvmatrix
                self.renderPath = path
#                glMatrixMode(GL_MODELVIEW)
#                glLoadMatrixf( mvmatrix )
                try:
                    path[-1].Render( mode = self )
                    if debugFrustum:
                        bvolume.debugRender( )
                except Exception as err:
                    log.error(
                        """Failure in opaque render: %s""",
                        getTraceback( err ),
                    )
                    import os 
                    os._exit(1)
    def renderTransparent( self, toRender ):
        """Render the transparent geometry from toRender (in forward order)"""
        self.transparent = True
        setup = False
        debugFrustum = self.context.contextDefinition.debugBBox
        try:
            for key,mvmatrix,tmatrix,bvolume,path in toRender:
                if key[0]:
                    if not setup:
                        setup = True
                        glEnable(GL_BLEND)
                        glBlendFunc(GL_ONE_MINUS_SRC_ALPHA,GL_SRC_ALPHA, )
                        glDepthMask( 0 )
                        glDepthFunc( GL_LEQUAL )

                    self.matrix = mvmatrix
                    self.renderPath = path
                    glLoadMatrixf( mvmatrix )
                    try:
                        path[-1].RenderTransparent( mode = self )
                        if debugFrustum:
                            bvolume.debugRender( )
                    except Exception as err:
                        log.error(
                            """Failure in %s: %s""",
                            path[-1].Render,
                            getTraceback( err ),
                        )
        finally:
            self.transparent = False
            if setup:
                glDisable( GL_BLEND )
                glDepthMask( 1 )
                glDepthFunc( GL_LEQUAL )
                glEnable( GL_DEPTH_TEST )
    def addTransparent( self, other ):
        pass

    def selectRender( self, mode, toRender, events ):
        """Render each path to color buffer

        We render all geometry as non-transparent geometry with
        unique colour values for each object.  We should be able
        to handle up to 2**24 objects before that starts failing.
        """
        # TODO: allow context to signal that it is "captured" by a
        # movement manager that doesn't need select rendering...
        # e.g. for an examine manager there's no reason to do select
        # render passes...
        # TODO: do line-box intersection tests for bounding boxes to
        # only render the geometry which is under the cursor
        # TODO: render to an FBO instead of the back buffer
        # (when available)
        # TODO: render at 1/2 size compared to context to create a
        # 2x2 selection square and reduce overhead.
        glClearColor( 0,0,0, 0 )
        glClear( GL_DEPTH_BUFFER_BIT|GL_COLOR_BUFFER_BIT )

        self.visible = False
        self.transparent = False
        self.lighting = False
        self.textured = False

        matrix = self.matrix
        map = {}

        pickPoints = {}
        # TODO: this could be faster, and we could do further filtering
        # using a frustum a-la select render mode approach...
        min_x,min_y = self.getViewport()[2:]
        max_x,max_y = 0,0
        pickSize = 2
        offset = pickSize//2
        for event in events.values():
            x,y = key = tuple(event.getPickPoint())
            pickPoints.setdefault( key, []).append( event )
            min_x = min((x-offset,min_x))
            max_x = max((x+offset,max_x))
            min_y = min((y-offset,min_y))
            max_y = max((y+offset,max_y))
        min_x = int(max((0,min_x)))
        min_y = int(max((0,min_y)))
        if max_x < min_x or max_y < min_y:
            # no pick points were found 
            return
        debugSelection = mode.context.contextDefinition.debugSelection
            
        if not debugSelection:
            glScissor( min_x,min_y,int(max_x)-min_x,int(max_y)-min_y)
            glEnable( GL_SCISSOR_TEST )

        glMatrixMode( GL_MODELVIEW )
        try:
            idHolder = array( [0,0,0,0], 'B' )
            idSetter = idHolder.view( '<I' )
            for id,(key,mvmatrix,tmatrix,bvolume,path) in enumerate(toRender):
                id = (id+1) << 12
                idSetter[0] = id
                glColor4ubv( idHolder )
                self.matrix = mvmatrix
                self.renderPath = path
                glLoadMatrixf( mvmatrix )
                path[-1].Render( mode=self )
                map[id] = path
            pixel = array([0,0,0,0],'B')
            depth_pixel = array([[0]],'f')
            for point,eventSet in pickPoints.items():
                # get the pixel colour (id) under the cursor.
                glReadPixels( point[0],point[1],1,1,GL_RGBA,GL_UNSIGNED_BYTE, pixel )
                lpixel = long( pixel.view( '<I' )[0] )
                paths = map.get( lpixel, [] )
                event.setObjectPaths( [paths] )
                # get the depth value under the cursor...
                glReadPixels(
                    point[0],point[1],1,1,GL_DEPTH_COMPONENT,GL_FLOAT,depth_pixel
                )
                event.viewCoordinate = point[0],point[1],depth_pixel[0][0]
                event.modelViewMatrix = matrix
                event.projectionMatrix = self.projection
                event.viewport = self.viewport
                if hasattr( mode.context, 'ProcessEvent'):
                    mode.context.ProcessEvent( event )
        finally:
            glColor4f( 1.0,1.0,1.0, 1.0)
            glDisable( GL_COLOR_MATERIAL )
            glEnable( GL_LIGHTING )
            glDisable( GL_SCISSOR_TEST )

    MAX_LIGHTS = -1
    def __call__( self, context ):
        """Overall rendering pass interface for the context client"""
        vp = context.getViewPlatform()
        self.setViewPlatform( vp )
        # These values are temporarily stored locally, we are
        # in the context lock, so we're not causing conflicts
        if self.MAX_LIGHTS == -1:
            self.MAX_LIGHTS = 8 #glGetIntegerv( GL_MAX_LIGHTS )
        self.context = context
        self.cache = context.cache
        self.viewport = (0,0) + context.getViewPort()
        
        self.calculateFrustum()

        self.Render( context, self )
        return True # flip yes, for now we always flip...

    def calculateFrustum( self ):
        """Construct our Frustum instance (currently by extracting from mv matrix)"""
        # TODO: calculate from view platform instead
        self.frustum = frustum.Frustum.fromViewingMatrix(
            self.modelproj,
            normalize = 1
        )
        return self.frustum
    
    def getProjection (self):
        """Retrieve the projection matrix for the rendering pass"""
        return self.projection
    def getViewport (self):
        """Retrieve the viewport parameters for the rendering pass"""
        return self.viewport
    def getModelView( self ):
        """Retrieve the base model-view matrix for the rendering pass"""
        return self.modelView
    
    def setViewPlatform( self, vp ):
        """Set our view platform"""
        self.viewPlatform = vp 
        self.projection = vp.viewMatrix().astype('f')
        self.modelView = vp.modelMatrix().astype('f')
        self.modelproj = dot( self.modelView, self.projection )
        self.matrix = None 
