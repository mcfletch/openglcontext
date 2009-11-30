"""Rendering pass subclasses for use with gl2ps"""
from OpenGLContext import renderpass
from OpenGL.gl2ps import *
from OpenGL.GL import *

class OpaqueRenderPass( renderpass.OpaqueRenderPass ):
    """Opaque rendering pass for gl2ps"""
    def SceneGraphBackground( self, node ):
        """Don't draw a background

        The background objects draw themselves about 1m from
        the viewer's eye, so they tend to entirely obscure the
        scene.
        """
    def shouldDraw( self  ):
        """Always want to draw when we invoke the exporter"""
        return 1
    def ContextRenderSetup( self, node ):
        """Set up the context for rendering prior to scene rendering

        Only diff from base class is _not_ setting mode to GL_RENDER
        """
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
class TransparentRenderPass( renderpass.TransparentRenderPass ):
    """Transparent rendering pass for gl2ps"""
    def ContextRenderSetup( self, node ):
        """Set up the context for rendering prior to scene rendering

        We don't want to do anything at all here...
        """

defaultRenderPasses = renderpass.PassSet(
    renderpass.OverallPass,
    [
        OpaqueRenderPass,
        TransparentRenderPass,
    ],
)
    