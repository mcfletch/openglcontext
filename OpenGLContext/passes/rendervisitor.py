"""Basic Rendering code implemented as a Visitor class

The RenderVisitor class provides a basic implementation
of rendering a Context/scenegraph via a Visitor pattern.
It provides support for setting up lights, backgrounds,
viewpoints, transforms, and selection-names.  (Those last
two are only applicable to scenegraph-based applications).

A few helper classes provide post-node-traversal
resetting mechanisms.
"""
import sys, traceback, types, math
from OpenGL.GL import *
from vrml import node
from vrml.vrml97 import nodetypes
from OpenGLContext.scenegraph import nodepath
from OpenGLContext import visitor, frustum, doinchildmatrix
from OpenGLContext.arrays import array
import logging 
log = logging.getLogger( __name__ )

RADTODEG = 180/math.pi
class RenderVisitor( visitor.Visitor ):
    """OpenGL Rendering visitor/traversal object for scenegraphs

    This class does the "normal" setup and rendering for
    "normal" scenegraph nodes, Context(s) and SceneGraph(s)
    themselves.  It is the base class of most RenderPass
    objects (with the notable exception of Transparent
    rendering passes (which do no traversal at the moment)).
    """
    # to prevent a mutual-import problem, we
    # only import context when we actually need to...
    contextBaseClass = None
    frustum = None
    def __init__( self ):
        """Initialise the visitor object"""
        if not self.contextBaseClass:
            from OpenGLContext import context
            self.__class__.contextBaseClass = context.Context
        super(RenderVisitor, self).__init__()

    def buildVMethods( self ):
        """Add scenegraph-package-specific class:method mappings
        """
        vmethods = super( RenderVisitor, self).buildVMethods()
        from OpenGLContext.scenegraph import scenegraph, basenodes
        vmethods.update( dict([
            (self.contextBaseClass, 'Context'),
            (scenegraph.SceneGraph, 'SceneGraph'),
            (nodetypes.Transforming, 'Transform'),
##			(nodetypes.Grouping, 'Grouping'),
            (nodetypes.Rendering, 'Rendering'),
        ]))
        return vmethods

    def SceneGraph( self, node ):
        """Render a scenegraph object (SetupBindables)

        This method is only called if the Context returns
        a non-null value from getSceneGraph(), as it only
        is called when a Scenegraph instance is encountered.
        
        If a Scenegraph is active, we do not use the code in
        ContextSetupBindables, so the Scenegraph is responsible
        for setting up all of the bindable nodes it wishes
        to have rendered.

        calls:
            SceneGraphCamera(node)
            SceneGraphLights(node)
            SceneGraphBackground(node)
        """
        self.SceneGraphCamera( node )
        self.SceneGraphLights( node )
        self.SceneGraphBackground( node )
    def SceneGraphCamera( self, node ):
        """Setup the camera/viewpoint from the scenegraph

        XXX
            At the moment, there is no Viewpoint support in
            OpenGLContext, so this method merely calls the
            Context's Viewpoint method.
        """
        if self.viewpointPaths:
            node.viewpointPaths = self.viewpointPaths[:]
            found = 0
            for path in self.viewpointPaths:
                if getattr(path[-1], 'isBound',None):
                    found = 1
                    view = path[-1]
            if not found:
                view = None
                if node.boundViewpoint:
                    # currently bound has been un-bound, goto next
                    for index,path in enumerate(self.viewpointPaths):
                        if path[-1] is node.boundViewpoint:
                            view = self.viewpointPaths[
                                (index+1)%len(self.viewpointPaths)
                            ][-1]
                            break
                if view is None:
                    view = self.viewpointPaths[0][-1]
                    log.info( "Binding to first viewpoint: %s", view )
                view.isBound = True
            if node.boundViewpoint is not view:
                view.moveTo( path, self.context )
                node.boundViewpoint = view
        self.context.Viewpoint( self )
        if not self.frustum:
            self.frustum = frustum.Frustum.fromViewingMatrix(normalize = 1)
        else:
            log.warn(
                """Calculated frustum twice for the same rendering pass %s""",
                self
            )
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
        if self.lighting:
            # Enable lighting calculations
            enabledLights = []
            IDs = [
                GL_LIGHT0, GL_LIGHT1, GL_LIGHT2, GL_LIGHT3,
                GL_LIGHT4, GL_LIGHT5, GL_LIGHT6, GL_LIGHT7,
            ]
            glEnable(GL_LIGHTING);
            lightPaths = self.lightPaths[:]
            def tryLight( lightPath, IDs, visitor):
                """Try to enable a light, returns either
                None or the ID used during enabling."""
                lightPath.transform()
                return lightPath[-1].Light( ID, visitor )
            if lightPaths:
                while IDs and lightPaths:
                    lightPath = lightPaths[0]
                    del lightPaths[0]
                    ID = IDs[0]
                    used = doinchildmatrix.doInChildMatrix( tryLight, lightPath, ID, self )
                    if used:
                        enabledLights.append( IDs.pop(0) )
                if lightPaths and not IDs:
                    log.warn( """Unable to render all lights in scene, more than 8 active lights, %s skipped"""%(len(lightPaths)))
            else:
                # create a default light
                self.SceneGraphDefaultlight( IDs[0] )
                del IDs[0]

            # disable the remaining lights
            for ID in IDs:
                glDisable(ID);
            return 	enabledLights
        elif self.lighting:
            glEnable(GL_LIGHTING);
            self.SceneGraphDefaultlight( GL_LIGHT0 )
        return None
    def SceneGraphDefaultlight( self, lightID ):
        """Create the default headlight

        VRML browsers generally have a default lighting scheme
        where, if there are no lights in the scene, a headlight
        is created pointing from the viewpoint forward into the scene.

        The light paths found by the OverallPass are used to
        transform the individual light objects to their appropriate
        positions in the scene.

        XXX
            This code is not quite right, instead of creating
            a headlight, it is just creating a simple light pointing
            forward from 0,0,10.  What we want is a light that always
            points forward from the current viewpoint in the current
            view direction.
        """
        if self.lightingDiffuse:
            glEnable(lightID)
            glLight(lightID, GL_DIFFUSE, array((1.0,1.0,1.0,1.0),'f'))
            glLight(lightID, GL_POSITION, array((0.0,0.0,10.0,1.0),'f'))

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
        if self.passCount == 0:
            current = None
            for background in self.backgroundPaths:
                if background[-1].bound:
                    current = background
                    break
            if not current:
                if self.backgroundPaths:
                    current = self.backgroundPaths[0]
                    current[-1].bound = 1
            def doBackground( path, visitor ):
                """Render the background"""
                glLoadIdentity()
                ### XXX ick! this is horribly fragile!
                x,y,z,r = visitor.context.platform.quaternion.XYZR()
                glRotate( r*RADTODEG, x,y,z )
                
                path.transform(visitor, translate=0,scale=0, rotate=1 )
                return path[-1].Render( visitor )

            if current:
                return doinchildmatrix.doInChildMatrix( doBackground, current, self )
            else:
                ### default VRML background is black
                glClearColor(0.0,0.0,0.0,1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )

    def Rendering( self, node ):
        """Render a rendering node (Shape)

        At the moment, this just calls node.Render( self )
        """
        assert hasattr( node, "Render"), """Rendering node %s does not have a Render method"""%( self.__class__ )
        return node.Render( self )

    def Transform( self, node ):
        """Render a transform object, return a finalisation token

        This method attempts to catch model-view matrix overflows
        and gracefully handle them.  It returns "tokens" which reset
        the model-view matrix to the previous condition.  This is
        part of the Visitor API.

        Note:
            Most Transforming nodes are also Grouping nodes,
            so both the Transform method and the Grouping method
            will be run for those nodes.
        """
        assert hasattr( node, "transform"), """Transforming node %s does not have a transform method"""%( node.__class__ )
        if self.transform:
            glMatrixMode(GL_MODELVIEW)
            try:
                glPushMatrix() # should do checks here to make sure we're not going over limit
            except GLerror, error:
                matrix = glGetDouble( GL_MODELVIEW_MATRIX )
                node.transform()
                return TransformOverflowToken( matrix)
            else:
                node.transform ()
                return TransformPopToken
        return None


##	def Grouping( self, node ):
##		"""Render a grouping node, return a finalisation token
##
##		Grouping notes are primarily of interest during selection
##		rendering passes, where they push and pop names on the
##		OpenGL name stack.  There are a number of selection-specific
##		attributes on the RenderPass object which determine whether
##		or not an individual Grouping node's name is pushed onto
##		the stack.
##
##		Grouping nodes also keep track of their individual
##		"sensitivity" (by monitoring whether or not they have a
##		mouse-sensor child).  Sensitive Grouping nodes alter the
##		RenderPass's selection-specific attributes to manipulate
##		their children's selection-mode rendering.
##		"""
##		mustPop = 0
##		if self.selectNames:
##			if node.sensitive or self.selectForced:
##				# need to push name
##				pselectForced = self.selectForced
##				if node.sensitive == 1:
##					# we are ourselves sensitive, so we need to render all
##					# of our children as being sensitive, regardless of
##					# whether they themselves are sensitive (ie. forced mode)
##					self.selectForced = 1
##				mustPop = node.pushName(self)
##				if mustPop:
##					return GroupPopToken(pselectForced)
    ### Context-rendering methods...
    def Context( self, node ):
        """Render the Context object

        calls:
            ContextRenderSetup(node)
            ContextSetupDisplay(node)
            ContextSetupBindables(node)
        """
        self.ContextRenderSetup( node )
        self.ContextSetupDisplay( node )
        self.ContextSetupBindables( node )
    def ContextRenderSetup( self, node ):
        """Set up the context for rendering prior to scene rendering

        This method runs even when there is a scenegraph

        It sets the rendering mode to GL_RENDER, and loads
        identity matrices for the projection and model
        view matrices.
        """
        glRenderMode( GL_RENDER )
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()
    def ContextSetupDisplay( self, node):
        """Establishes rendering parameters for context's rendering pass

        This method runs even when there is a scenegraph
        
        (Re-)establishes common rendering parameters which
        may have been left in unexpected states.  If the Context
        object has a SetupDisplay method, we call that.  Otherwise
        we enable depth testing, set the depth test to GL_LESS,
        enable face-culling, and set face-culling to cull back-faces.
        """
        if hasattr( node, "SetupDisplay"):
            return node.SetupDisplay( self )
        else:
            ### A fairly generic set of rendering options
            glEnable(GL_DEPTH_TEST);
            glDepthFunc(GL_LESS)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)
    def ContextSetupBindables( self, node):
        """Set up the bindable objects (viewpoints, backgrounds, lights)

        If the Context object has a non-null scenegraph, as
        returned by getSceneGraph(), then this method will
        do nothing, as the scenegraph will be responsible for
        setting up the bindable nodes.

        If the Context does not have the scenegraph, then we
        look for a Context.SetupBindables method, and call
        that with context.SetupBindables(self)

        If the Context does not have a SetupBindables method
        or a scenegraph, we call:
            context.Viewpoint ( self )
            context.Background( self )
            context.Lights ( self )
        """
        if not node.getSceneGraph():
            if hasattr( node, "SetupBindables"):
                node.SetupBindables( self )
            else:
                node.Viewpoint ( self )
                node.Background( self )
                node.Lights ( self )
            if not self.frustum:
                self.frustum = frustum.Frustum.fromViewingMatrix(normalize = 1)
            else:
                log.warn( """ContextSetupBindables called twice for the same rendering pass %s""", self)

### Finalisation tokens
class GroupPopToken( object ):
    """Pop name off name-stack and restore selection-mode-state

    This is part of the visitor API used by the Grouping method
    it restores the name stack after a Grouping node's children
    are finished being visited.
    """
    def __init__( self, selectForced=0):
        self.selectForced = selectForced
    def __call__( self, mode=None ):
        glPopName( )
        mode.selectForced = self.selectForced

class _TransformPopToken(object):
    """Pop matrix off model-view-stack

    This is part of the visitor API used by the Transform method
    it restores the model-view matrix stack after a Transforming
    node's children are finished being visited.

    This version is used when the model-view matrix stack
    has not overflowed, which allows us to use the more efficient
    glPopMatrix call.
    """
    def __call__( self, mode=None ):
        glMatrixMode(GL_MODELVIEW)
        glPopMatrix()
TransformPopToken = _TransformPopToken()

class TransformOverflowToken( object ):
    """Restore previous matrix in model-view-stack overflow situations

    This is part of the visitor API used by the Transform method
    it restores the model-view matrix stack after a Transforming
    node's children are finished being visited.

    This version is used when the model-view matrix stack
    has overflowed, using the more expensive glLoadMatrixd
    call to do the restoration.
    """
    def __init__( self, matrix):
        self.matrix = matrix
    def __call__( self, mode=None ):
        glMatrixMode(GL_MODELVIEW)
        glLoadMatrixd( self.matrix )
    
