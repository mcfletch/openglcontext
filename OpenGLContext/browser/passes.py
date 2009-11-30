from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.passes import renderpass

class PassMixIn(object):
    """Rendering-pass mix-in which is visual-aware"""
    def SceneGraphLights( self, node ):
        """Render lights for a scenegraph

        The default implementation limits you to eight active
        lights, despite the fact that many OpenGL renderers
        support more than this.  There have been problems with
        support for calculating light IDs beyond eight, so I
        have limited the set for now.

        This method relies on the pre-scanning pass implemented
        by the renderpass.OverallPass object.  That is not
        a particularly desirable dependency, but eliminating it
        will likely be quite messy.
        """
        if hasattr( node, 'lights' ):
            if hasattr( node, 'ambient'):
                a = node.ambient # egads, no color at all!
                glLightModelfv(GL_LIGHT_MODEL_AMBIENT, [a,a,a, 1.0] )
            IDs = [
                GL_LIGHT0, GL_LIGHT1, GL_LIGHT2, GL_LIGHT3,
                GL_LIGHT4, GL_LIGHT5, GL_LIGHT6, GL_LIGHT7,
            ]
            from OpenGLContext.scenegraph import light
            for direction,lightID in zip(node.lights, IDs):
                # egads, no color at all!
                l = light.PointLight( location=direction )
                l.Light( lightID, self )
        else:
            return super( PassMixIn, self).SceneGraphLights( node )
    def SceneGraphBackground( self, node ):
        """Render background for a scenegraph

        The background paths found by the OverallPass are used to
        transform the individual background objects to their appropriate
        positions in the scene. In general, only the rotation
        of the path will affect a background node, as they are
        rendered around the viewpoint, rather than around a
        particular object-space position.

        This method relies on the pre-scanning pass implemented
        by the renderpass.OverallPass object.  That is not
        a particularly desirable dependency, but eliminating it
        will likely be quite messy.
        """
        if hasattr( node, 'background'):
            r,g,b = node.background
            glClearColor( r,g,b, 0 )
            glClear( GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT )
##		else:
##			return super( PassMixIn, self).SceneGraphBackground( node )

class OpaqueRenderPass( PassMixIn, renderpass.OpaqueRenderPass ):
    """Opaque Pass for rendering visual-style scenegraph"""

defaultRenderPasses = renderpass.PassSet(
    renderpass.OverallPass,
    [
        OpaqueRenderPass,
        renderpass.TransparentRenderPass,
        renderpass.SelectRenderPass,
    ],
)