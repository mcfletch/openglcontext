"""Flat rendering mechanism using structural scenegraph observation"""
from OpenGLContext.scenegraph import nodepath,switch,boundingvolume
from OpenGL.GL import *
from OpenGL.GLU import gluUnProject
from OpenGLContext.arrays import array, dot
from OpenGLContext import frustum
from OpenGLContext.debug.logs import getTraceback
from vrml.vrml97 import nodetypes
from vrml import olist
from vrml.vrml97.transformmatrix import RADTODEG
import weakref,random, sys, ctypes, logging
from pydispatch.dispatcher import connect
import logging 
log = logging.getLogger( __name__ )

if sys.maxint > 2L<<32:
    BIGINTS = True
else:
    BIGINTS = False

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
            after = self.npFor(next)
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
                        except KeyError, err:
                            pass
            self.paths[key][:] = filtered

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
            except (AttributeError,boundingvolume.UnboundedObject), err:
                return 0
            else:
                translated = dot( points, mv )
                maxDepth = min((maxDepth, min( translated[:,2] )))
        return -(maxDepth*1.01)

    def frustumVisibilityFilter( self, records ):
        """Filter records for visibility using frustum planes

        This does per-object culling based on frustum lookups
        rather than object query values.  It should be fast
        *if* the frustcullaccel module is available, if not
        it will be dog-slow.
        """
        result = []
        frustum = self.frustum
        for record in records:
            (key,mv,tm,bv,path) = record
            if bv is not None:
                visible = bv.visible(
                    frustum, tm.astype('f'),
                    occlusion=False,
                    mode=self
                )
                if visible:
                    result.append( record )
            else:
                result.append( record )
        return result

    def Render( self, context, mode ):
        """Render the geometry attached to this flat-renderer's scenegraph"""
        vp = context.getViewPlatform()
        # clear the projection matrix set up by legacy sg
        glMatrixMode( GL_MODELVIEW )
        matrix = self.getModelView()
        self.matrix = matrix
        glLoadIdentity()

        toRender = self.renderSet( matrix )
        maxDepth = self.greatestDepth( toRender )
        if maxDepth:
            previous = self.projection
            self.projection = vp.viewMatrix(maxDepth)

        glMatrixMode( GL_PROJECTION )
        glLoadMatrixf( self.getProjection() )

        events = context.getPickEvents()
        debugSelection = mode.context.contextDefinition.debugSelection
        if events or debugSelection:
            self.selectRender( mode, toRender, events )
            events.clear()
        glMatrixMode( GL_PROJECTION )
        glLoadMatrixf( self.getProjection() )
        glMatrixMode( GL_MODELVIEW )
        matrix = self.getModelView()
        if not debugSelection:
            glLoadIdentity()
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
            glEnable(GL_LIGHTING)
            glDepthFunc(GL_LESS)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            self.legacyLightRender( matrix )

            self.renderOpaque( toRender )
            self.renderTransparent( toRender )

            if context.frameCounter.display:
                context.frameCounter.Render( context )
        context.SwapBuffers()
        self.matrix = matrix

    def legacyBackgroundRender( self, vp,matrix ):
        """Do legacy background rendering"""
        bPath = self.currentBackground( )
        if bPath is not None:
            glMultMatrixf( vp.quaternion.matrix( dtype='f') )
            bPath.transform(self, translate=0,scale=0, rotate=1 )
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
                glLoadMatrixf( mvmatrix )
                try:
                    path[-1].Render( mode = self )
                    if debugFrustum:
                        bvolume.debugRender( )
                except Exception, err:
                    log.error(
                        """Failure in %s: %s""",
                        path[-1].Render,
                        getTraceback( err ),
                    )
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
        glDisable( GL_LIGHTING )
        glEnable( GL_COLOR_MATERIAL )

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
        if not self.context.contextDefinition.debugSelection:
            glScissor( min_x,min_y,int(max_x)-min_x,int(max_y)-min_y)
            glEnable( GL_SCISSOR_TEST )
        glMatrixMode( GL_MODELVIEW )
        try:
            idHolder = array( [0,0,0,0], 'B' )
            idSetter = idHolder.view( '<I' )
            for id,(key,mvmatrix,tmatrix,bvolume,path) in enumerate(toRender):
                id = (id+1) << 12
                idSetter[0] = id
                glColor4bv( idHolder )
                self.matrix = mvmatrix
                glLoadMatrixf( mvmatrix )
                path[-1].Render( mode=self )
                map[id] = path
            for point,eventSet in pickPoints.items():
                # get the pixel colour (id) under the cursor.
                pixel = glReadPixels( point[0],point[1],1,1,GL_RGBA,GL_BYTE )
                pixel = long( pixel.view( '<I' )[0][0][0] )
                paths = map.get( pixel, [] )
                event.setObjectPaths( [paths] )
                # get the depth value under the cursor...
                pixel = glReadPixels(
                    point[0],point[1],1,1,GL_DEPTH_COMPONENT,GL_FLOAT
                )
                event.viewCoordinate = point[0],point[1],pixel[0][0]
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
        mode = self
        vp = context.getViewPlatform()
        self.viewPlatform = vp
        # These values are temporarily stored locally, we are
        # in the context lock, so we're not causing conflicts
        if self.MAX_LIGHTS == -1:
            self.MAX_LIGHTS = 8 #glGetIntegerv( GL_MAX_LIGHTS )
        self.context = context
        self.cache = context.cache
        self.projection = vp.viewMatrix().astype('f')
        self.viewport = (0,0) + context.getViewPort()
        self.modelView = vp.modelMatrix().astype('f')
        # TODO: calculate from view platform instead
        self.frustum = frustum.Frustum.fromViewingMatrix(
            dot(self.modelView,self.projection),
            normalize = 1
        )

        # We're here setting up legacy OpenGL settings
        # eventually these will be uniform setups...
        self.Render( context, self )
        return True # flip yes, for now we always flip...

    def getProjection (self):
        """Retrieve the projection matrix for the rendering pass"""
        return self.projection
    def getViewport (self):
        """Retrieve the viewport parameters for the rendering pass"""
        return self.viewport
    def getModelView( self ):
        """Retrieve the base model-view matrix for the rendering pass"""
        return self.modelView
