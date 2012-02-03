"""Compound passes for rendering a shadowed scene...

The rendering passes here provide the bulk of the algorithm
for rendering shadowed scenes.  You can follow the algorithm
starting at the OverallShadowPass, which manages 3 sets of
sub-passes:

    ambient light passes (subPasses)
        opaque-ambient-light pass
        transparent-ambient-light pass
    light pass (perLightPasses)
        stencil setup pass
        opaque-1-light pass
        transparent-1-light pass
    regular selection pass (postPasses)


The ambient light passes perform two major functions.

    They set up the depth buffer with the scene's geometry

    They add all of the ambient and emissive contribution
    of the lights in the scene.

Each light then has two or three passes (depending on whether
there are transparent objects in the scene).  The first pass
renders the shadow volume objects into the stencil buffer,
which creates a stencil shadow which marks off those areas
of the scene which are not illuminated by the current light.

The second pass renders the opaque geometry blending in the
contribution of the current light, with the stencil buffer
masking of those areas which are shadowed from the light.

If there are transparent objects, eventually we will render
them in much the same way, but at the moment, the depth buffer
is not being updated during the opaque render pass, so the
transparent objects will have undergo almost arbitrary lighting.

XXX Obviously that should change.

After the lighting passes are finished, the standard selection
rendering passes can occur.
"""
from OpenGL.GL import *
from OpenGLContext import visitor, doinchildmatrix, frustum
from OpenGLContext.passes import renderpass, rendervisitor
from vrml import cache
from OpenGLContext.scenegraph import basenodes, indexedfaceset
from OpenGLContext.shadow import edgeset
from OpenGLContext.debug import state
from vrml import protofunctions
try:
    from OpenGLContext.debug import bufferimage
except ImportError:
    bufferimage = None

from OpenGLContext.arrays import *
from math import pi
import sys
import logging
log = logging.getLogger( __name__ )

class OverallShadowPass (renderpass.OverallPass):
    """Pass w/ ambient, light-specific, and selection sub-passes

    If we are doing no visible passes, then we are
    basically just a regular selection pass.

    Otherwise we need to do the ambient rendering
    pass (possibly two if we have transparent objects),
    with this pass finding and registering all
    lights and edge-sets.

    Then for each light:
        Do the stencil-buffer set up pass, which walks
        the list of edge sets (creating and) rendering
        the shadow volume for the current light.

        Do an opaque render with just the single light
        enabled, and the stencil buffer excluding
        shadowed geometry.

        If there are transparent objects, render them
        using the same set up as the opaque render.

    Finally:
        kill off the stencil buffer set up
    """
    passDebug = 1
    debugShadowSilouhette = 1
    debugShadowVolume = 1
    debugShadowNoStencil = 0
    debugShadowNoBackFaces = 0
    debugShadowNoFrontFaces = 0
    debugShadowNoCaps = 0
    debugShadowNoBoots = 0
    debugShadowNoEdges = 0
    
    def __init__ (
        self, 
        context=None,
        subPasses = (),
        startTime = None,
        perLightPasses = (),
        postPasses = (),
    ):
        """Initialise OverallShadowPass

        perLightPasses -- list of passes to be applied to each
            light in the active light set
        postPasses -- list of passes applied after all of the
            light-specific passes are applied
        """
        super( OverallShadowPass, self).__init__(context, subPasses, startTime)
        self.perLightPasses = perLightPasses
        self.postPasses = postPasses

    def __call__( self ):
        """Render the pass and all sub-passes"""
        if __debug__:
            if self.passDebug:
                sys.stderr.write( """START NEW PASS\n""" )
        changed = 0
        passCount = -1
        # XXX not the right place for this.
        glStencilFunc(GL_ALWAYS, 0, ~0);
        glStencilOp(GL_KEEP,GL_KEEP,GL_KEEP);
        glDepthFunc(GL_LESS);
        glColorMask(GL_TRUE,GL_TRUE,GL_TRUE,GL_TRUE);
        glColor( 1.0, 1.0, 1.0, 1.0 )
        
        glDisable(GL_BLEND);
        glDisable(GL_STENCIL_TEST);
        glDepthMask(1)
        
        glBlendFunc(GL_ONE,GL_ZERO);
        glStencilMask(~0)

        # run through the regular pass-types
        for passObject in self.subPasses:
            if __debug__:
                if self.passDebug:
                    sys.stderr.write( 'SUB-PASS %s\n'%( passObject))
            changed += passObject()
            passCount = passObject.passCount
            self.visibleChange = changed
        passCount += 1
        # now run through the per-light passes
        # creating a new pass for each light's
        # version of each pass
        try:
            for light in self.lightPaths:
                self.currentLight = light
                for passClass in self.perLightPasses:
                    passObject = passClass( self, passCount )
                    if __debug__:
                        if self.passDebug:
                            sys.stderr.write( 'SUB-PASS %s\n'%( passObject))
                    passCount += 1
                    changed += passObject()
                    self.visibleChange = changed
        finally:
            # do some cleanup to make sure next pass is visible
            glDisable(GL_BLEND);
            glDisable(GL_STENCIL_TEST);
            glDepthMask(1);
        for passClass in self.postPasses:
            passObject = passClass( self, passCount )
            if __debug__:
                if self.passDebug:
                    sys.stderr.write( 'SUB-PASS %s\n'%( passObject))
            passCount += 1
            changed += passObject()
            self.visibleChange = changed
        return changed


class AmbientOnly( object ):
    """Render with only ambient lights
    """
    lighting = 1
    lightingAmbient = 1 # whether ambient lighting should be used
    lightingDiffuse = 0 # whether diffuse lighting should be used (non-ambient)
class AmbientOpaque( AmbientOnly, renderpass.OpaqueRenderPass ):
    """Opaque rendering pass with only ambient lights

    This will be the only pass which actually writes
    to the depth buffer.  It will also be responsible
    for registering each light, and edge-set with the
    appropriate matrices.
    """
class AmbientTransparent( AmbientOnly, renderpass.TransparentRenderPass ):
    """Transparent rendering pass with only ambient lights"""


class SpecificLight( object ):
    """Mix-in to run lighting for a specific light

    The overall pass keeps track of currentLight for us
    """
    lightID = GL_LIGHT0
    frustumCulling = 0 # the shadows shouldn't be culled if the objects are off-screen
    def SceneGraph( self, node ):
        """Render lights for a scenegraph"""
        def tryLight( lightPath, ID, visitor):
            """Try to enable a light, returns either
            None or the ID used during enabling."""
            lightPath.transform()
            return lightPath[-1].Light( ID, visitor )
        if self.lighting:
            doinchildmatrix.doInChildMatrix( tryLight, self.currentLight, self.lightID, self )
    def shouldDraw( self ):
        """Whether we should draw"""
        return self.visibleChange or super( SpecificLight,self).shouldDraw()



class LightStencil (SpecificLight, renderpass.OpaqueRenderPass):
    """Sets up the stencil buffer for the current light"""
    lighting = 0
    lightingAmbient = 0 # whether ambient lighting should be used
    lightingDiffuse = 0 # whether diffuse lighting should be used (non-ambient)
    stencil = 1
    cacheKey = 'edgeSet'
    def Context( self, node):
        """Setup stencil buffer where we render shadow volumes"""
        # disable depth buffer writing
        glDepthMask(GL_FALSE);
        # force depth-testing on
        glEnable(GL_DEPTH_TEST);
        glDepthFunc( GL_LESS );

        # enable blending
        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE,GL_ONE);

        # clear the stencil buffer
        glClear(GL_STENCIL_BUFFER_BIT);

        # disable color-buffer writing
        glColorMask(0,0,0,0);
        
        # enable use of the stencil buffer for determining whether to write
        glEnable(GL_STENCIL_TEST);
        glStencilFunc(GL_ALWAYS,0,~0);
        glStencilMask(~0);

        glEnable( GL_CULL_FACE )

##		try:
##			self.DebugSaveDepthBuffer()
##		except:
##			print 'failed to save depth buffer'

    def Rendering( self, node ):
        """Regular rendering isn't desirable..."""
        ### should have a way to specify non-occluding geometry...
        node = node.geometry
        if not isinstance( node, basenodes.IndexedFaceSet ):
            return
        cc = indexedfaceset.ArrayGeometryCompiler( node )
        ag = cc.compile(
            visible=False,lit=False,textured=False,transparent=False,
            mode = self, 
        )
        if ag is indexedfaceset.DUMMY_RENDER:
            return None
        # okay, we have an array-geometry object
        edgeSet = self.cache.getData(node,self.cacheKey)
        if not edgeSet:
            if ag.vertices:
                edgeSet = edgeset.EdgeSet(
                    points = ag.vertices.data,
                    ccw = ag.ccw == GL_CCW,
                )
                holder = self.cache.holder(
                    client = node,
                    key = self.cacheKey,
                    data = edgeSet,
                )
                for (n, attr) in [
                    (node, 'coordIndex'),
                    (node, 'ccw'),
                    (node.coord, 'point'),
                ]:
                    if n:
                        holder.depend( n, protofunctions.getField(n,attr) )
            else:
                edgeSet = None
        if not edgeSet:
            return
        # okay, we have an edge-set object...
        volume = edgeSet.volume( self.currentLight, self.currentStack )
        if not volume:
            return
        # now we have a shadow-volume for this light and edge-set
        volume.render( self )

    def DebugSaveDepthBuffer( self, file = "depth_buffer.jpg" ):
        if not bufferimage:
            return
        width, height = self.context.getViewPort()
        image = bufferimage.depth(0,0, width, height )
        image.save( file, "JPEG" )
        
class LightOpaque(SpecificLight, renderpass.OpaqueRenderPass):
    """Opaque rendering pass for a specific light"""
    lighting = 1
    lightingAmbient = 0 # whether ambient lighting should be used
    lightingDiffuse = 1 # whether diffuse lighting should be used (non-ambient)
    def Context( self, node):
        glCullFace(GL_BACK);
        glStencilFunc(GL_EQUAL, 0, ~0);
        # this should be INCR according to the article...
        glStencilOp(GL_KEEP,GL_KEEP,GL_INCR);
        glDepthFunc(GL_EQUAL);
        glDepthMask(~1);
        glColorMask(1,1,1,1);
        glColor( 1.,1.,1.)
        # enable blending
        glEnable(GL_BLEND);
        glEnable(GL_LIGHTING);
        glBlendFunc(GL_ONE,GL_ONE);
    def SaveStencilDebug( self ):
        if not bufferimage:
            return
        width, height = self.context.getViewPort()
        image = bufferimage.stencil(0,0, width, height )
        image.save( "buffer.jpg", "JPEG" )
    def SceneGraph( self, node ):
        """Render lights for a scenegraph"""
        def tryLight( lightPath, ID, visitor):
            """Try to enable a light, returns either
            None or the ID used during enabling."""
            lightPath.transform()
            return lightPath[-1].Light( ID, visitor )
        if self.lighting:
            doinchildmatrix.doInChildMatrix( tryLight, self.currentLight, self.lightID, self )
        if not self.frustum:
            self.frustum = frustum.Frustum.fromViewingMatrix(normalize = 1)
        else:
            log.warn( """SceneGraphCamera called twice for the same rendering pass %s""", self)
        
class LightTransparent(SpecificLight, renderpass.TransparentRenderPass):
    lighting = 1
    lightingAmbient = 0 # whether ambient lighting should be used
    lightingDiffuse = 1 # whether diffuse lighting should be used (non-ambient)
    def ContextSetupDisplay( self, node):
        super( LightTransparent, self).ContextSetupDisplay( node )
        glStencilFunc(GL_EQUAL, 0, ~0);
        glStencilOp(GL_KEEP,GL_KEEP,GL_INCR);
        glDepthFunc(GL_EQUAL);
        glColorMask(1,1,1,1);

### Finalisation tokens
class ShadowPassSet( object ):
    """Callable list of sub-passes"""
    def __init__ (
        self,
        overallClass, 
        subPasses = (),
        perLightPasses = (),
        postPasses = (),
    ):
        self.overallClass = overallClass
        self.subPasses = subPasses
        self.perLightPasses = perLightPasses
        self.postPasses = postPasses
    def __call__( self, context):
        """initialise and run a render pass with our elements"""
        overall = self.overallClass(
            context = context,
            subPasses = self.subPasses,
            perLightPasses = self.perLightPasses,
            postPasses = self.postPasses,
        )
        return overall()

### following object only used for testing
ambientRenderPass = renderpass.PassSet(
    OverallShadowPass,
    [
        AmbientOpaque,
        AmbientTransparent,
        renderpass.SelectRenderPass,
    ],
)
### The normal pass-set
defaultRenderPasses = ShadowPassSet(
    OverallShadowPass,
    subPasses = [
        AmbientOpaque,
        AmbientTransparent,
    ],
    perLightPasses = [
        LightStencil ,
        LightOpaque,
        LightTransparent,
    ],
    postPasses = [
        renderpass.SelectRenderPass,
    ]

)
