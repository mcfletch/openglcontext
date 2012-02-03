"""Default rendering-algorithm implementation

This module provides the default rendering algorithm
implementation, including the opaque, transparent and
selection rendering-passes.  The classes here are also
used as the base classes for the shadow/passes.py
module which implements the shadow-casting rendering
algorithm.
"""
from __future__ import generators
import time, weakref, traceback, sys
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import *

from OpenGLContext import visitor, displaylist, frustum, utilities
from OpenGLContext.passes import rendervisitor
from OpenGLContext.scenegraph import nodepath
from vrml.vrml97 import nodetypes
from vrml import node
import logging 
log = logging.getLogger( __name__ )

class RenderPass(object):
    """A particular pass of a particular rendering mode

    Most RenderPass instances are actually VisitingRenderPass
    instances, with the notable exception of TransparentRenderPass
    objects.
    
    Attributes (normally class-static):
        transform -- whether to do transforms, most do

        visible -- whether there is any visible change to
            the buffer (use textures, colours, etceteras)
        transparent -- whether is a transparent-rendering pass

        selectNames -- whether should push/pop selection "names"
        selectForced -- whether we are currently in forced-
            selection mode
        stencil -- whether we are rendering into the stencil buffer

        lighting -- lighting is being used (most opaque/
            transparent, but not selection)
        lightingAmbient -- whether ambient lighting should be used
        lightingDiffuse -- whether diffuse lighting should be used
            (non-ambient)

    Note:
        The RenderPass will look up any missing attributes
        in the OverallPass object, so effectively the RenderPass
        has all of the attributes of the OverallPass which
        is passed to the initializer.

    Note:
        This class is a consolidation of the RenderPass and
        RenderMode classes in OpenGLContext version 1.0
    """
    ### Per-pass-type constants...
    ## Arguably these should be part of the RenderVisitor class,
    ## as that class uses the constants defined here
    ## but they are needed for non-visiting classes as well
    visible = 1
    transform = 1
    transparent = 0
    selectNames = 0
    selectForced = 0
    stencil = 0

    lighting = 1 
    lightingAmbient = 1 
    lightingDiffuse = 1

    cache = None

    def __init__( self, overall, passCount = 0 ):
        """Initialise the per-mode render-pass object

        overall -- the OverallPass instance which is driving
            this RenderPass instance.  Attributes of the
            OverallPass are made available via the __getattr__
            hook.
        passCount -- the index of this pass within the
            OverallPass, an integer representing the
            number of passes which have come before us.

        The initializer calls OnInit when it is finished
        to allow for easy sub-class customization.
        """
        self.overall = weakref.proxy( overall )
        self.passCount = passCount
        self.cache = self.overall.context.cache
        
        super( RenderPass, self).__init__()
        self.OnInit()
    def OnInit( self ):
        """Initialization customization point"""

    def __getattr__( self, key ):
        """Defer to the overall pass on attribute lookup failure"""
        if key != 'overall':
            return getattr( self.overall, key)
        raise AttributeError( """%s object does not have the attribute %s"""%(self.__class__.__name__, key))

    def __call__( self ):
        """Do the rendering pass

        return whether or not there has been a visible change
        """
        return self.visible
        

    def shouldDraw( self ):
        """Test whether this pass should be performed,
        This implementation just returns 1, subclasses
        should return an intelligent value"""
        return 1


class VisitingRenderPass( RenderPass, rendervisitor.RenderVisitor ):
    """A render-pass using the (normal) scenegraph-visitor pattern

    Basically, the RenderVisitor implements the rendering
    algorithm and the code for common object types.  The
    VisitingRenderPass(es) define exceptions to the
    basic algorithm.
    """
    frustum = None # storage of the frustum
    # whether to cull using the frustum
    #   -1 -- automatic choice preferring query cull, bb cull, no cull
    #   2 -- query-based culling 
    #   1 -- bounding-box culling 
    #   0 -- no culling (slow!)
    frustumCulling = -1 
    def __call__( self ):
        """Do the rendering pass

        Visits the context and all of its children if the
        shouldDraw method returns a true value.

        Returns self.visible if the visiting sequence
        occurred, otherwise returns 0
        """
        if self.shouldDraw( ):
            self.visit( self.context )
            return self.visible
        return 0
    def children( self, node ):
        """Get children to visit for a node

        Adds (experimental, slow, and currently incorrect)
        frustum-culling check to filter out children who
        are not within the frustum.  Will only be enabled
        if the context defines a true attribute:
            USE_FRUSTUM_CULLING
        """
        base = super( VisitingRenderPass, self).children( node )
        if self.frustumCulling == -1:
            context = self.overall.context
            if getattr( context, 'USE_FRUSTUM_CULLING',None):
                if getattr( context, 'USE_OCCLUSION_CULLING',None):
                    if context.extensions.initExtension( 'ARB_occlusion_query' ):
                        self.__class__.frustumCulling = 2
                    elif context.extensions.initExtension( "GL_HP_occlusion_test"):
                        self.__class__.frustumCulling = 2
                    else:
                        self.__class__.frustumCulling = 1
                else:
                    self.__class__.frustumCulling = 1
            else:
                self.__class__.frustumCulling = 0
        if self.frustumCulling and self.frustum:
            matrix = self.currentStack.transformMatrix()
            for child in base:
                if hasattr( child, 'visible'):
                    if child.visible(
                        self.frustum, matrix,
                        occlusion=(self.frustumCulling==2),
                        mode=self
                    ):
                        yield child
                else:
                    yield child
        else:
            for child in base:
                yield child
    

class OpaqueRenderPass(VisitingRenderPass):
    """Opaque geometry rendering through scenegraph visitation

    The opaque rendering passes is the most "normal"
    of the rendering passes.  It basically just uses
    the RenderVisitor implementation to render the
    scenegraph or Context.

    The OpaqueRenderPass uses the context's shouldRedraw
    and suppressRedraw methods to determine whether or not to
    render itself, (and to let the context know that it has
    rendered).  This is not ideologically pure, as potentially
    there could be another rendering pass responsible for
    "visible" rendering.  It is, however, practical for now.

    Note:
        The OpaqueRenderPass registers objects for the
        TransparentRenderPass, so the TransparentRenderPass
        cannot operate without a preceding OpaqueRenderPass.
    """
    visible = 1 # whether there is any visible change to the buffer
    transform = 1 # whether to do transforms, most do
    lighting = 1 # lighting is being used (most opaque/transparent, but not selection)
    transparent = 0 # whether is a transparent-rendering pass
    selectNames = 0 # whether should push/pop selection "names"
    def shouldDraw( self ):
        """Checks the client's shouldRedraw() value, then calls suppressRedraw"""
        value = self.context.shouldRedraw()
        self.context.suppressRedraw()
        return value

class TransparentRenderPass(RenderPass):
    """Blend-based transparent/translucent geometry rendering

    This is an implementation of transparent geometry rendering
    which, although not rigorously generalized, should provide
    basic functionality.

    XXX What is wrong with the implementation?

        Properly done, a transparent-rendering algorithm should
        sort all polygons of all transparent objects together
        with each vertex of each polygon projected, and any
        intersecting polygons tesselated to form polygons which
        are unambiguously in front of or behind every other
        polygon.

        I haven't implemented that algorithm, mostly because it
        is a great deal of work for a fairly minimal payback
        given relatively infrequent occurrence of intersecting
        transparent geometry.

        There is a further problem when doing stencil-shadow
        rendering, in that the multi-pass rendering does not
        have proper depth information.  I haven't come across
        a decent explanation of how to implement support for
        this, so I haven't done so.
    """
    visible = 1 # whether there is any visible change to the buffer
    transform = 0 # whether to do transforms, most do
    lighting = 1 # lighting is being used (most opaque/transparent, but not selection)
    transparent = 1 # whether is a transparent-rendering pass
    selectNames = 0 # whether should push/pop selection "names"

    def shouldDraw( self  ):
        """Checks to see if there are registered transparent objects

        If there are none, then the entire pass will be skipped.
        """
        return self.getTransparent()
    def __call__( self ):
        """Render all registered transparent objects

        Objects are projected into screen coordinates,
        sorted according to their local origin depth,
        then rendered with the model view matrix active
        at transparent-object registration (during the
        OpaqueRenderPass).

        See:
            OverallPass.addTransparent
            OverallPass.getTransparent
        """
        if self.shouldDraw():
            self.ContextRenderSetup( self.context )
            self.ContextSetupDisplay( self.context )
            try:
                projection, viewport = self.getProjection (), self.getViewport ()
                items = []
                for object, matrix in self.getTransparent ():
                    try:
                        distance = gluProject( 0,0,0, matrix, projection, viewport )[2]
                    except TypeError:
                        continue
                    else:
                        items.append(
                            (
                                float(distance),
                                object,
                                matrix,
                            )
                        )
                
                items.sort( lambda x,y: cmp(x[0],y[0]))
                # we want to render front-to-back
                items.reverse()
                for distance, object, matrix in items:
                    glMatrixMode(GL_MODELVIEW)
                    glLoadMatrixd( matrix )
                    self.Render( object )
                return self.visible
            finally:
                self.ContextShutdown()
        return 0
    def ContextRenderSetup( self, node ):
        """Set up the context for rendering prior to scene rendering

        Note:
            Although this is the same name as a customization point
            for the RenderVisitor API, this object is not a
            RenderVisitor.  This method is called directly by the
            __call__ method.
        """
        # most everything's already set up by the opaque mode...
        glRenderMode( GL_RENDER )

    def ContextSetupDisplay( self, node):
        """Establishes rendering parameters for the rendering pass

        This particular transparent-geometry-rendering algorithm
        uses glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA),
        which requires back-to-front sorting of geometry to
        produce proper results.  It is one of the most
        reliable methods for producing transparent geometry
        effects.

        Note:
            Although this is the same name as a customization point
            for the RenderVisitor API, this object is not a
            RenderVisitor.  This method is called directly by the
            __call__ method.
        """
        # most everything's already set up by the opaque mode...
        glEnable(GL_BLEND);
        glEnable(GL_DEPTH_TEST);
        glBlendFunc(GL_ONE_MINUS_SRC_ALPHA,GL_SRC_ALPHA, )
        glDepthMask( 0 ) # prevent updates to the depth buffer...

    def restoreBlending( self ):
        """Restore our blending mode after a node has changed it"""
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE_MINUS_SRC_ALPHA,GL_SRC_ALPHA, )

    def ContextShutdown( self ):
        """Clears the transparency-specific rendering parameters

        Called after the entire rendering pass has completed,
        this method is responsible for "cleaning up" after the
        transparent-rendering pass.  It also clears the list
        of transparent objects build up by the OpaqueRenderPass.

        Note:
            Although this is the same name as a customization point
            for the RenderVisitor API, this object is not a
            RenderVisitor.  This method is called directly by the
            __call__ method.
        """
        glDisable(GL_BLEND);
        glEnable(GL_DEPTH_TEST);
        glDepthMask( 1 ) # allow updates to the depth buffer
        del self.getTransparent ()[:]

    def Render( self, node ):
        """Render a shape node as transparent geometry

        This method knows how to render a Shape node as transparent
        geometry.  Basically that consists of calling the geometry's
        render method with transparent = 1

        Note:
            Although this is the same name as a customization point
            for the RenderVisitor API, this object is not a
            RenderVisitor.  This method is called directly by the
            __call__ method.
        """
        textureToken = None
        if node.appearance:
            lit, textured, alpha, textureToken = node.appearance.render ( mode=self )
        else:
            lit = 0
            textured = 0
            glColor3f( 1,1,1)
        if lit and self.lighting:
            glEnable(GL_LIGHTING)
        else:
            glDisable(GL_LIGHTING)
        ## do the actual work of rendering it transparently...
        if node.geometry:
            node.geometry.render (lit = lit, textured = textured, transparent=1, mode=self)
        if node.appearance:
            node.appearance.renderPost( textureToken, mode=self )
        if textured:
            self.restoreBlending()
        glDisable(GL_LIGHTING)



class SelectRenderPass( VisitingRenderPass ):
    """glSelectBuffer-based selection rendering mode

    This is an implementation of glSelectBuffer-based
    selection modes.  It allows for projecting multiple
    "pick" events into the scenegraph.  The
    implementation tries to be as general as possible.

    The RenderVisitor.Grouping method takes care of
    calling the Grouping nodes' pushName method to
    generate the name stack which is reported by the
    SelectRenderPass.

    See:
        OpenGLContext.events.mouseevents
        OpenGLContext.context.getPickEvents
        OpenGLContext.context.addPickEvent

    Note:
        Each pick event causes a complete render-traversal,
        which, if there are a lot of pick-events, can
        dramatically slowdown your frame rate!  There
        should be some logic to try to minimize these
        events, but I haven't come up with a generalized
        solution to the problem.

    Note:
        Pick events are registered and accessed from the
        Context object. The SelectRenderPass can deal
        (and it does deal only in the current implementation)
        with events which were generated/registered either
        by a previous render-pass, or between rendering
        passes.
    
    Attributes:
        bufferSize -- the size of the Name buffer used
            to store the name-stack which will be reported.
            The default value, 512, is somewhat wasteful
            but does allow for fairly deep scenegraph's.
        matrixSize -- the pixel-size dimensions of the
            pick matrix (default is 2,2) used
        pickPoint -- stores the current pick-point for the
            selection rendering pass.
        selectable -- mapping from "name" (OpenGL integer name)
            to selectable Node (an opaque object reference) used
            to provide easy access to the list of selected nodes.
            See:
                addSelectable()
    """
    visible = 0 # whether there is any visible change to the buffer
    transform = 1 # whether to do transforms, most do
    lighting = 0 # lighting is being used (most opaque/transparent, but not selection)
    transparent = 0 # whether is a transparent-rendering pass
    selectNames = 1 # whether should push/pop selection "names"
    bufferSize = 512
    matrixSize = (2,2)
    pickPoint = (-1,-1)
    frustumCulling = 1 # whether to cull using the frustum (experimental), -1 triggers query, 0 no, 1 yes
    
    def shouldDraw( self ):
        """Only draw if there are picking events pending"""
        if self.context.getPickEvents():
            return 1
        return 0

    def __call__( self ):
        """Render geometry once for each pick-event to be serviced

        This is the actual implementation of the glSelectBuffer-
        based selection code. It is fairly standard OpenGL
        selection code.

        We take all of the events which have the same picking-point
        and render them together (since they have the same picking
        characteristics).

        For each picking-point, we set up the constrained picking
        matrix and results array in our ContextSetupDisplay/
        PickProjection methods, which are visited by the standard
        RenderVisitor algorithm.

        The visiting code, particularly RenderVisitor.Grouping,
        pushes the appropriate names onto the name stack during
        rendering, filling the results array as appropriate.

        After visiting the entire scenegraph, we retrieve the results
        from the name-stack and dispatch the events to their
        appropriate handlers.

        XXX
            Really the event handling should not be going on here,
            instead the events should be added to a queue to be
            processed after the RenderPass has completely finished,
            and the ContextLock has been released (but the scenegraph
            lock has been re-acquired).
        """
        if self.shouldDraw( ):
            client = self.context
            events = client.getPickEvents().values()
            client.getPickEvents().clear()
            pickPoints = {}
            for event in events:
                key = tuple(event.getPickPoint())
                pickPoints.setdefault( key, []).append( event )

            for point, set in pickPoints.items():
                self.pickPoint = point
                self.selectable = {}
                self.visit( client )
                ## following two lines get the results of the render...
                nameStack = list(glRenderMode(GL_RENDER))
                ## and now update the event...
                for event in set:
                    ##print '%s items rendered'%( len(self.selectable), )
                    event.setNameStack( nameStack )
                    event.setObjectPaths([
                        nodepath.NodePath(filter(None,[
                            self.selectable.get(long(name))
                            for name in names
                        ]))
                        for (near,far,names) in nameStack
                    ])
                    event.modelViewMatrix = self.modelView
                    event.projectionMatrix = self.projection
                    event.viewport = self.viewport
                    if hasattr( client, 'ProcessEvent'):
                        client.ProcessEvent( event )
            return self.visible
        return 0
    def ContextSetupDisplay( self, node):
        """Customization point calls PickProjection after standard setup"""
        super( SelectRenderPass, self).ContextSetupDisplay( node )
        self.PickProjection()
    def PickProjection( self ):
        """Setup the constrained picking matrix and result buffer

        We set up the view frustum to be a
        box centered around the picking point of size
        self.matrixSize, projecting back into the screen
        from our current viewpoint.

        We then set up the selection buffer into which
        our results will be saved, and then switch to
        selection-mode rendering.
        """
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glInitNames()
        x,y = self.pickPoint
        gluPickMatrix(
            x,y,
            self.matrixSize [0], self.matrixSize [1],
            self.getViewport()
        )
        glSelectBuffer(self.bufferSize)
        glRenderMode(GL_SELECT)
    def addSelectable( self, name, obj ):
        """Register a selectable node with the given name"""
        self.selectable[name] = obj
    def vmethods( self, obj ):
        """Get all relevant "virtual methods" as unbound methods

        This adds "self.PushName" as the first virtual method for all nodes
        """
        base = super( SelectRenderPass, self).vmethods( obj )
        if isinstance( obj, node.Node ):
            if not base or base[0] != type(self).PushName:
                base.insert(0, type(self).PushName )
        return base

    def PushName( self, node ):
        """Push node name onto the stack, return pop-token

        XXX should be guarding against name-stack overflows here!
        """
        # using id node fails on 64-bit machines where memory is getting
        # allocated in values > 32-bit unsigned integers can hold
        name = id(node)
        if name > 0xffffffff:
            name = name & 0xffffffff
        while name in self.selectable:
            name = (name + 1) & 0xffffffff
        glPushName( name )
        self.addSelectable( name, node )
        return self.PopName
    def PopName( self, otherSelf ):
        """Pop our name from the stack"""
        glPopName( )

    

class OverallPass (object):
    """Representation of an overall rendering pass

    The OverallPass object represents a collection of sub-passes
    which, together, are considered a full rendering cycle.  The
    OverallPass stores information about the entire rendering
    cycle, with the attributes of the OverallPass available to
    each sub-pass (and thereby to rendering code).

    Attributes:
        context -- reference to the client Context object
            into which this pass is being rendered

        lightPaths, viewPaths, backgroundPaths, fogPaths --
            nodepath objects for each active object of the given
            node-types found during the initial "findBindables"
            "rendering" pass which is run before any of the
            regular render-passes.
            See:
                findBindables
                RenderVisitor.SceneGraphLights
                RenderVisitor.SceneGraphBackground

        transparentObjects -- sequence of transparent object
            records registered (normally by OpaqueRenderPass) for
            processing (normally by TransparentRenderPass).
            See:
                addTransparent()
                getTransparent()


        ## Note: the following are not considered particularly useful
        # and may disappear at some point in time
        startTime -- the startTime value passed to the initializer,
            or the value of time.time() during initialization if
            there was no value
        viewport -- glGetIntegerv( GL_VIEWPORT )
            -> (x,y, width, height)
        projection -- glGetDoublev( GL_PROJECTION_MATRIX )
            -> 4x4 float matrix
        modelView -- glGetDoublev( GL_MODELVIEW_MATRIX )
            -> 4x4 float matrix
    """
    viewport = None
    projection = None
    modelView = None
    lightPaths = None
    viewPaths = None
    backgroundPaths = None
    fogPaths = None
    
    def __init__ (
        self, 
        context=None,
        subPasses = (),
        startTime = None,
    ):
        """Initialize the OverallPass object

        context -- the client Context node
        subPasses -- sequence of sub-pass RenderPass objects
        startTime -- optional starting time value
        """
        self.startTime = startTime or time.time()
        self.context = context
        self.setSubPasses( subPasses )
        self.OnInit()

    def OnInit(self):
        """Initialize pass-specific functionality"""
        # cache context values...
        self.getViewport()
        self.getProjection()
        self.getModelView()
        # setup transparent and selection attributes
        # should be done by those sub-passes instead
        self.transparentObjects = []
        self.selectable = {}
        # overall pointers to paths set up by findBindables
        self.findBindables()

    def __call__( self ):
        """Render the pass and all sub-passes

        Reports whether or not there was a visible change
        """
        changed = 0
        for passObject in self.subPasses:
            try:
                changed += passObject()
                self.visibleChange = changed
            except Exception, error:
                traceback.print_exc( limit=6 )
                sys.stderr.write( """Exception in rendering object %s"""%(passObject))
        if self.visibleChange:
            self.context.SwapBuffers()
        return changed

    def setSubPasses( self, passes ):
        """Set the sub-passes for the meta-pass, passes is a sequence of classes"""
        self.subPasses = []
        count = 0
        for passClass in passes:
            self.subPasses.append(
                passClass(
                    overall = self,
                    passCount = count,
                )
            )
            count += 1
        return count

    def getProjection (self):
        """Retrieve the projection matrix for the rendering pass"""
        # XXX is this actually reliable???
        try:
            if not self.projection:
                self.projection = glGetDoublev( GL_PROJECTION_MATRIX )
        except ValueError, err:
            # numpy arrays don't allow truth testing...
            # since we have it, we have a non-None value
            pass
        return self.projection
    def getViewport (self):
        """Retrieve the viewport parameters for the rendering pass"""
        try:
            if not self.viewport:
                self.viewport = glGetIntegerv( GL_VIEWPORT )
        except ValueError, err:
            # numpy arrays don't allow truth testing...
            # since we have it, we have a non-None value
            pass
        return self.viewport
    def getModelView( self ):
        """Retrieve the base model-view matrix for the rendering pass"""
        try:
            if not self.modelView:
                self.modelView = glGetDoublev( GL_MODELVIEW_MATRIX )
        except ValueError, err:
            # numpy arrays don't allow truth testing...
            # since we have it, we have a non-None value
            pass
        return self.modelView

    ### transparency-specific values
    def addTransparent(self, token, matrix=None):
        """Register object for transparent rendering pass

        token -- opaque pointer to an object to be rendered
            during the transparent rendering pass

        The current model-view matrix will be stored with
        the token for use during the transparent rendering pass
        """
        if matrix is None:
            matrix = glGetDoublev( GL_MODELVIEW_MATRIX )
        token = (token,matrix)
        # Because matrices are not able to do comparisons
        # without *very* expensive allclose calls, we just
        # add any token to the list.  This may cause multiple
        # records to get added in some more exotic rendering
        # contexts, but avoids skipping already-existing nodes
        # which have been included with USEs
        # The following line is what should have worked :(
        # if token not in self.transparentObjects:
        self.transparentObjects.append (token)
    def getTransparent (self):
        """Retrieve current list of registered transparent objects

        The list is a series of two-tuples, with each
        entry composed of the opaque pointer registered with
        addTransparent and the model-view matrix active
        at the time of registration.
        """
        return self.transparentObjects

    ### selection-specific methods
##	def getNameStack( self ):
##		"""Return the name stack from selection rendermode"""
##		return self.selectionNameStack
##	def setNameStack( self, stack ):
##		"""Set the selection results (name stack)"""
##		self.selectionNameStack = stack
    ### setup scan for Bindables and Lights
    def findBindables( self ):
        """Calculate and store nodepath(s) for active bindable and light nodes

        See:
            RenderVisitor.SceneGraphLights
            RenderVisitor.SceneGraphBackground
        """
        bindables = None
        for (attribute,nodeType,match) in [
            ('lightPaths',nodetypes.Light,lambda x: x.on),
            ('backgroundPaths',nodetypes.Background, None),
            ('viewpointPaths',nodetypes.Viewpoint, None),
            ('fogPaths',nodetypes.Fog, None),
            ('otherBinds',None,lambda x: hasattr(x,'bind')),
        ]:
            cached = self.context.cache.getData( self.context, attribute )
            # TODO: need to be able to watch all hierarchy-defining fields 
            # for the entire path to be able to watch for path changes!
            if cached is None:
                holder = self.context.cache.holder( self.context, None, attribute )
                if not bindables:
                    bindables = visitor.find(
                        self.context,
                        (
                            nodetypes.Bindable,
                            nodetypes.Light,
                            nodetypes.TimeDependent,
                        ),
                    )
                set = []
                for path in bindables:
                    if (not nodeType) or isinstance( path[-1], nodeType ):
                        if (match and match( path[-1] )) or not match:
                            set.append( path )
#							for node in path:
#								holder.depend( node.hier_fields )
                    elif hasattr( path[-1], 'bind' ):
                        path[-1].bind( self.context )
                holder.data = set 
                setattr( self, attribute, set )
            else:
                setattr( self, attribute, cached )


class PassSet( list ):
    """Callable list of sub-passes with associated OverallPass

    The PassSet is called once per render-cycle,
    and is responsible for creating the OverallPass
    which does the actual rendering.  It simply
    creates the OverallPass with the given sub-passes
    and calls the OverallPass, returning the result.
    """
    def __init__( self, overallClass, items=() ):
        """Initialize the PassSet

        overallClass -- the OverallPass class which will
            be used to do the actual rendering.
        items -- list of sub-passes to be passed to the
            OverallPass object
        """
        self.overallClass = overallClass
        super( PassSet, self).__init__( items )
    def __call__( self, context):
        """Initialize and run a render pass for context with our sub-passes"""
        overall = self.overallClass(
            context = context,
            subPasses = list(self)
        )
        return overall()

visitingDefaultRenderPasses = PassSet(
    OverallPass,
    [
        OpaqueRenderPass,
        TransparentRenderPass,
        SelectRenderPass,
    ],
)
USE_FLAT = True
FLAT = None
class _defaultRenderPasses( object ):
    def __call__( self,context ):
        global FLAT
        if FLAT is None:
            if USE_FLAT:
                from OpenGLContext.passes.flat import FlatPass
                sg = context.getSceneGraph()
                if sg is not None:
                    FLAT = FlatPass( context.getSceneGraph(), context.allContexts )
                else:
                    return visitingDefaultRenderPasses( context )
            else:
                return visitingDefaultRenderPasses( context )
            log.warn( 'Using Flat/Legacy-reduced renderer' )
        return FLAT( context )
defaultRenderPasses = _defaultRenderPasses()
