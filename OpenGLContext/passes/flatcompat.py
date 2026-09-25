"""The compatibility-profile flat pass: the fixed-function pipeline

Lighting and materials go through ``glLight*`` and ``glMaterial*``, and
geometry is drawn from display lists and client-side vertex arrays.  The
core-profile pass is :mod:`OpenGLContext.passes.flatcore`; which of the two
renders a given context is decided in
:mod:`OpenGLContext.passes.renderpass`, not chosen by the caller.
"""
from typing import Any, Dict, List, Sequence

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

    #: The fixed function writes display-referred colour, which the bloom
    #: chain would tone-map a second time, so this pass draws straight to the
    #: framebuffer whatever ``ContextDefinition.bloom`` says.
    supports_bloom = False

    
    def Render( self, context: Any, mode: Any ) -> None:
        """Render the geometry attached to this flat-renderer's scenegraph"""
        frames = self.prepareViews()
        self.clearUncovered( context, frames )
        active = self.activeFrame if self.activeFrame is not None else frames[0]
        matrix = active.modelView
        self.matrix = matrix

        # do we need to do a selection-render pass?
        events = context.getPickEvents()
        debugSelection = (mode.context.contextDefinition.debugSelection
                          and mode.context.contextDefinition.pickEnabled)

        if events or debugSelection:
            self.selectRenderViews( mode, events, debugSelection )
            events.clear()

        if not debugSelection:
            self.matrix = matrix
            self.visible = True
            self.transparent = False
            self.lighting = True
            self.textured = True
            try:
                for frame in frames:
                    self.renderViewLegacy( frame )
            finally:
                self.finishViews()
        self.applyViewFrame( active, gl=False )

        # The HUD, the developer overlay and any screen that is open, drawn over
        # the finished frame.  The overlay renderer builds its own program and
        # does not care that the world below it was drawn fixed-function, and a
        # context whose menu could not be seen would be a program nobody can
        # use.  See OpenGLContext.ui.screen.ScreenMixin.
        overlay = getattr(context, 'renderShaderOverlay', None)
        if overlay is not None:
            overlay(self)

        _flat.presentFrame( context )
        self.matrix = matrix

    def applyViewFrame( self, frame: Any, gl: bool = True ) -> None:
        """Look through ``frame``'s view, with its projection on the matrix stack.

        Every fixed-function draw is projected by the stack rather than by a
        uniform, so the view's projection is loaded as it is chosen, and the
        modelview left at the identity the background and lights load onto.
        """
        super( FlatPass, self ).applyViewFrame( frame, gl )
        if gl:
            glMatrixMode( GL_PROJECTION )
            glLoadMatrixf( self.getProjection() )
            glMatrixMode( GL_MODELVIEW )
            glLoadIdentity()

    def renderViewLegacy( self, frame: Any ) -> None:
        """Draw one view of the frame through the fixed-function pipeline."""
        self._beginView( frame )
        try:
            # Set up generic "geometric" rendering parameters
            glFrontFace( GL_CCW )
            glEnable(GL_DEPTH_TEST)
            glDepthFunc( GL_LESS )
            glEnable(GL_LIGHTING)
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)
            self.legacyNormalRescale()

            self.legacyLightRender( frame.modelView )

            self.renderOpaque( frame.toRender )
            self.renderTransparent( frame.toRender )
            self.resetMeshDrawState()
        finally:
            self._endView( frame )

    def legacyBackgroundRender( self, vp: Any, matrix: Any ) -> None:
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

    def legacyNormalRescale( self ) -> None:
        """Have the GL return transformed normals to unit length

        The fixed function transforms a normal by the inverse transpose of the
        modelview, which for a scale of ``s`` divides the normal's length by
        ``s``.  A Transform with a ``scale`` field would otherwise light what is
        under it as though ``N.L`` were ``1/s`` times what it is -- a half-size
        shape lit twice as brightly, a doubled one half as much -- and the
        core-profile shaders, which normalize the transformed normal, would
        disagree with this pass about the same scene.

        GL_NORMALIZE rather than GL_RESCALE_NORMAL: VRML97 allows a
        non-uniform scale, which rescaling alone does not answer.
        """
        glEnable(GL_NORMALIZE)

    def renderGeometry( self, mvmatrix: Any ) -> None:
        """Draw the geometry, with the state a fixed-function draw depends on

        Render sets that state up for a whole frame, but a caller wanting the
        geometry alone -- a shadow tutorial filling a depth map from a light,
        say -- comes straight here and never passes through it.
        """
        self.legacyNormalRescale()
        return super( FlatPass, self ).renderGeometry( mvmatrix )

    def legacyLightRender( self, matrix: Any ) -> None:
        """Do legacy light-rendering operation"""
        # okay, now visible presentations
        for remaining in range(0,self.MAX_LIGHTS-1):
            glDisable( GL_LIGHT0 + remaining )
        bound = 0
        for path in self.paths.get( nodetypes.Light, ()):
            tmatrix = path.transformMatrix()

            localMatrix = dot(tmatrix,matrix)
            self.matrix = localMatrix
            self.renderPath = path
            glLoadMatrixf( localMatrix )

            path[-1].Light( GL_LIGHT0+bound, mode=self )
            bound += 1
            if bound >= (self.MAX_LIGHTS-1):
                break
        if not bound:
            # default VRML lighting...
            from OpenGLContext.scenegraph import light
            l = light.DirectionalLight( direction = (0,0,-1.0))
            glLoadMatrixf( matrix )
            l.Light( GL_LIGHT0, mode = self )
        self.matrix = matrix
    
    def renderOpaque( self, toRender: Sequence[Any] ) -> None:
        """Render the opaque geometry from toRender (in reverse order)"""
        self.transparent = False
        debugFrustum = self.context.contextDefinition.debugBBox
        for key,mvmatrix,_tmatrix,bvolume,path,node in toRender:
            if not key[0]:
                self.matrix = mvmatrix
                self.renderPath = path
                glMatrixMode(GL_MODELVIEW)
                glLoadMatrixf( mvmatrix )
                try:
                    node.Render( mode = self )
                    if debugFrustum:
                        bvolume.debugRender( )
                except Exception as err:
                    self.renderFailed( 'opaque', node, err )
    def renderTransparent( self, toRender: Sequence[Any] ) -> None:
        """Render the transparent geometry from toRender (in forward order)"""
        self.transparent = True
        setup = False
        debugFrustum = self.context.contextDefinition.debugBBox
        try:
            for key,mvmatrix,_tmatrix,bvolume,path,node in toRender:
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
                        node.RenderTransparent( mode = self )
                        if debugFrustum:
                            bvolume.debugRender( )
                    except Exception as err:
                        self.renderFailed( 'transparent', node, err )
        finally:
            self.transparent = False
            if setup:
                glDisable( GL_BLEND )
                glDepthMask( 1 )
                glDepthFunc( GL_LEQUAL )
                glEnable( GL_DEPTH_TEST )
        # Draw shapes deferred from the opaque pass.
        self._renderDeferredTransparent()

    def selectRender( self, mode: Any, toRender: Sequence[Any],
                      events: Dict[Any, Any] ) -> None:
        """Legacy colour-buffer pick for the compatibility profile.

        Packs the id unshifted into RGB and toggles the fixed-function lighting
        state. Shared body in :func:`_flat._color_select_render`.
        """
        _flat._color_select_render(
            self, mode, toRender, events,
            id_shift=0, read_format=GL_RGB,
            setup_fixed_function=True, require_pick_enabled=True)

    MAX_LIGHTS = -1

    def getProjection( self ) -> Any:
        """Retrieve the projection matrix for the rendering pass"""
        return self.projection
    def getViewport( self ) -> Any:
        """Retrieve the viewport parameters for the rendering pass"""
        return self.viewport
    def getModelView( self ) -> Any:
        """Retrieve the base model-view matrix for the rendering pass"""
        return self.modelView
    
    def setViewPlatform( self, vp: Any ) -> None:
        """Set our view platform"""
        self.viewPlatform = vp 
        self.projection = vp.viewMatrix().astype('f')
        self.modelView = vp.modelMatrix().astype('f')
        self.modelproj = dot( self.modelView, self.projection )
        self.matrix = None 
