"""Flat rendering mechanism using structural scenegraph observation

Rewritten version that should be core-profile compatible...
"""
from . import _flat
from OpenGLContext.scenegraph import nodepath,switch,boundingvolume
from OpenGL.GL import *
from OpenGLContext.arrays import array, dot, allclose
from OpenGLContext import frustum
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
        
        # do we need to do a selection-render pass?
        events = context.getPickEvents()
        debugSelection = mode.context.contextDefinition.debugSelection
        
        if events or debugSelection:
            self.selectRender( mode, toRender, events )
            events.clear()
        
        # Load the root 
        if not debugSelection:
            self.matrix = matrix
            self.visible = True
            self.transparent = False
            self.lighting = True
            self.textured = True

            self.legacyBackgroundRender( vp,matrix )
            # Set up generic "geometric" rendering parameters
            glFrontFace( GL_CCW )
            glEnable(GL_DEPTH_TEST)
            glDepthFunc( GL_LESS )
            glDepthFunc(GL_LESS)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            self.legacyLightRender( matrix )

            self.renderOpaque( toRender )
            self.renderTransparent( toRender )

            if context.frameCounter and context.frameCounter.display:
                context.frameCounter.Render( context )
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
                except Exception, err:
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
                    except Exception, err:
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
