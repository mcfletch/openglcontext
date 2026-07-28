"""Flat rendering mechanism using structural scenegraph observation"""
from . import _flat
from OpenGLContext.scenegraph import nodepath,switch,boundingvolume
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot, allclose
from OpenGLContext.debug.logs import getTraceback
from vrml.vrml97 import nodetypes
from vrml import olist
from OpenGLContext.scenegraph import shaders
import sys
from pydispatch.dispatcher import connect
import logging 
log = logging.getLogger( __name__ )

class FlatPass( _flat.FlatPass ):
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


        passCount -- not used, always set to 0 for code that expects
            a passCount to be available.
        transform -- ignored, legacy code only
    """
    # this are now obsolete...
    selectNames = False
    selectForced = False

    cache = None

    #: Bloom composites the scene with a shader; this pass has no shader path
    #: to composite with, so it draws straight to the framebuffer.
    supports_bloom = False

    
    def Render( self, context, mode ):
        """Render the geometry attached to this flat-renderer's scenegraph"""
        # clear the projection matrix set up by legacy sg
        matrix = self.getModelView()
        self.matrix = matrix

        toRender = self.renderSet( matrix )
        maxDepth = self.maxDepth = self.greatestDepth( toRender )
        vp = context.getViewPlatform()
        if maxDepth:
            self.projection = vp.viewMatrix(maxDepth)
        
        # Load our projection matrix for all legacy rendering operations...
        glMatrixMode( GL_PROJECTION )
        glLoadMatrixf( self.getProjection() )
        
        # do we need to do a selection-render pass?
        events = context.getPickEvents()
        debugSelection = (mode.context.contextDefinition.debugSelection
                          and mode.context.contextDefinition.pickEnabled)
        
        if events or debugSelection:
            self.selectRender( mode, toRender, events )
            events.clear()
            glMatrixMode( GL_PROJECTION )
            glLoadMatrixf( self.getProjection() )
        
        # Load the root 
        glMatrixMode( GL_MODELVIEW )
        matrix = self.getModelView()
        if not debugSelection:
            glLoadIdentity()
            self.matrix = matrix
            self.visible = True
            self.transparent = False
            self.lighting = True
            self.textured = True
            # Runtime-transparent shapes deferred from the opaque pass (3b).
            self._deferredTransparent = []

            self.legacyBackgroundRender( vp,matrix )
            # Set up generic "geometric" rendering parameters
            glFrontFace( GL_CCW )
            glEnable(GL_DEPTH_TEST)
            glDepthFunc( GL_LESS )
            glEnable(GL_LIGHTING)
            glDepthFunc(GL_LESS)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            self.legacyLightRender( matrix )

            self.renderOpaque( toRender )
            self.renderTransparent( toRender )
        context.SwapBuffers()
        self.matrix = matrix

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
        # okay, now visible presentations
        for remaining in range(0,self.MAX_LIGHTS-1):
            glDisable( GL_LIGHT0 + remaining )
        id = 0
        for path in self.paths.get( nodetypes.Light, ()):
            tmatrix = path.transformMatrix()

            localMatrix = dot(tmatrix,matrix)
            self.matrix = localMatrix
            self.renderPath = path
            glLoadMatrixf( localMatrix )

            path[-1].Light( GL_LIGHT0+id, mode=self )
            id += 1
            if id >= (self.MAX_LIGHTS-1):
                break
        if not id:
            # default VRML lighting...
            from OpenGLContext.scenegraph import light
            l = light.DirectionalLight( direction = (0,0,-1.0))
            glLoadMatrixf( matrix )
            l.Light( GL_LIGHT0, mode = self )
        self.matrix = matrix
    
    def renderOpaque( self, toRender ):
        """Render the opaque geometry from toRender (in reverse order)"""
        self.transparent = False
        debugFrustum = self.context.contextDefinition.debugBBox
        for key,mvmatrix,tmatrix,bvolume,path in toRender:
            if not key[0]:
                self.matrix = mvmatrix
                self.renderPath = path
                glMatrixMode(GL_MODELVIEW)
                glLoadMatrixf( mvmatrix )
                try:
                    path[-1].Render( mode = self )
                    if debugFrustum:
                        bvolume.debugRender( )
                except Exception:
                    log.exception(
                        """Failure in opaque render""",
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
        # Draw shapes deferred from the opaque pass.
        self._renderDeferredTransparent()

    def selectRender( self, mode, toRender, events ):
        """Legacy colour-buffer pick for the compatibility profile.

        Packs the id unshifted into RGB and toggles the fixed-function lighting
        state. Shared body in :func:`_flat._color_select_render`.
        """
        _flat._color_select_render(
            self, mode, toRender, events,
            id_shift=0, read_format=GL_RGB,
            setup_fixed_function=True, require_pick_enabled=True)

    MAX_LIGHTS = -1

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
