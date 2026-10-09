"""The compatibility-profile flat pass: the fixed-function pipeline

Lighting and materials go through ``glLight*`` and ``glMaterial*``, and
geometry is drawn from display lists and client-side vertex arrays. Each draw
is lit by the lights whose scope holds it and whose `radius` reaches its
bounds; the others are switched off for it (:mod:`~OpenGLContext.passes.lightscope`).
The
core-profile pass is :mod:`OpenGLContext.passes.flatcore`; which of the two
renders a given context is decided in
:mod:`OpenGLContext.passes.renderpass`, not chosen by the caller.
"""
from collections.abc import Sequence
from typing import Any, Optional

from . import _flat
from OpenGLContext.move import navigationinfo
from OpenGLContext.passes.fixedprojectors import FixedProjectorsMixin
from OpenGLContext.scenegraph.textureprojector import is_projector
from vrml.x3d import nodes as x3dnodes
from OpenGLContext.passes import glstate, lightscope
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

class FlatPass( FixedProjectorsMixin, _flat.FlatPass ):
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
            glstate.load_matrix( self.getProjection() )
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
            self.restoreLegacyLights()
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

    #: The bits of the lights :meth:`legacyLightRender` enabled, those of
    #: them with a radius as world spheres, and the bits switched off for the
    #: draw being made (:meth:`applyLegacyLights`).
    _legacyLit = 0
    _legacyReach: lightscope.Reaching = ()
    _legacyOff = 0

    def legacyLightRender( self, matrix: Any ) -> None:
        """Enable a GL light for each light of the scene, then the headlight

        Records the scoped lights and those with a radius, which
        :meth:`applyLegacyLights` switches off per draw. Texture projectors
        are given texture units of their own
        (:mod:`~OpenGLContext.passes.fixedprojectors`), and an
        ``EnvironmentLight`` lights nothing here.
        """
        for remaining in range(0,self.MAX_LIGHTS-1):
            glDisable( GL_LIGHT0 + remaining )
        bound = 0
        lit = 0
        placed = []
        paths = []
        projectors = []
        for path in self.layerPaths( nodetypes.Light ):
            if is_projector( path[-1] ):
                projectors.append( path )
                continue
            if isinstance( path[-1], x3dnodes.EnvironmentLight ):
                continue
            tmatrix = path.transformMatrix()

            localMatrix = dot(tmatrix,matrix)
            self.matrix = localMatrix
            self.renderPath = path
            glstate.load_matrix( localMatrix )

            if path[-1].Light( GL_LIGHT0+bound, mode=self ):
                lit |= 1 << bound
                placed.append( (bound, path[-1], tmatrix) )
            paths.append( path )
            bound += 1
            if bound >= (self.MAX_LIGHTS-1):
                break
        self._legacyLit = lit
        self._legacyOff = 0
        self._legacyReach = lightscope.reaching_lights( placed )
        self.lightScopes = self.lightScopes.following( lightscope.scoped_lights( paths ) )
        if self.hasHeadlight( bound ):
            from OpenGLContext.scenegraph import light
            l = light.DirectionalLight( direction = (0,0,-1.0))
            glstate.load_matrix( matrix )
            l.Light( GL_LIGHT0 + bound, mode = self )
        self.setupFixedProjectors( projectors, matrix )
        self.matrix = matrix
    
    def applyLegacyLights( self, path: Any, tmatrix: Any, bvolume: Any ) -> None:
        """Switch off the lights whose scope or radius leaves out the draw of
        `path`, and the texture projectors whose scope does"""
        self.applyFixedProjectors( path )
        lit = self._legacyLit
        if not lit:
            return
        mask = self.lightScopes.mask( path )
        if self._legacyReach:
            low, high = self.worldBox( tmatrix, bvolume )
            mask |= lightscope.reach_mask( self._legacyReach, low, high )
        self._switchLegacyLights( mask & lit )

    def restoreLegacyLights( self ) -> None:
        """Switch back on every light a draw switched off, and the projectors' units off"""
        self._switchLegacyLights( 0 )
        self.endFixedProjectors()

    def _switchLegacyLights( self, mask: int ) -> None:
        changed = mask ^ self._legacyOff
        slot = 0
        while changed:
            if changed & 1:
                if mask & (1 << slot):
                    glDisable( GL_LIGHT0 + slot )
                else:
                    glEnable( GL_LIGHT0 + slot )
            changed >>= 1
            slot += 1
        self._legacyOff = mask

    def renderOpaque( self, toRender: Sequence[Any] ) -> None:
        """Render the opaque geometry from toRender (in reverse order)"""
        self.transparent = False
        debugFrustum = self.context.contextDefinition.debugBBox
        for key,mvmatrix,_tmatrix,bvolume,path,node in toRender:
            if not key[0]:
                self.matrix = mvmatrix
                self.renderPath = path
                glMatrixMode(GL_MODELVIEW)
                glstate.load_matrix( mvmatrix )
                self.applyFixedClipPlanes( path, _tmatrix )
                self.applyLegacyLights( path, _tmatrix, bvolume )
                try:
                    node.Render( mode = self )
                    if debugFrustum:
                        bvolume.debugRender( )
                except Exception as err:
                    self.renderFailed( 'opaque', node, err )
        self.endFixedClipPlanes()
    def selectRender( self, mode: Any, toRender: Sequence[Any],
                      events: dict[Any, Any], missed: Optional[list[Any]] = None ) -> None:
        """Legacy colour-buffer pick for the compatibility profile.

        Packs the id unshifted into RGB and toggles the fixed-function lighting
        state. Shared body in :func:`_flat._color_select_render`.
        """
        _flat._color_select_render(
            self, mode, toRender, events,
            id_shift=0, read_format=GL_RGB,
            setup_fixed_function=True, require_pick_enabled=True, missed=missed)

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
        self.modelView = vp.modelMatrix().astype('d')
        self.modelproj = dot( self.modelView, self.projection )
        self.matrix = None 
