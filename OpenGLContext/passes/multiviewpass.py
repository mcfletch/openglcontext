"""A frame of several views, as the render pass draws it.

:class:`MultiviewPassMixin` is the pass's side of :mod:`OpenGLContext.multiview`:
it lays the context's :class:`~OpenGLContext.multiview.views.ViewLayout` out
in the window and works out each view's camera (:meth:`~MultiviewPassMixin.layoutViews`),
culls the frame's one walk of the scene for each view
(:meth:`~MultiviewPassMixin.prepareViews`), looks through a view
(:meth:`~MultiviewPassMixin.applyViewFrame`), draws the shapes one submission can
serve for every view (:meth:`~MultiviewPassMixin.renderShared`) through the
strategy the driver supports, and routes pick events to the view they were
made in. It is composed into :class:`~OpenGLContext.passes._flat.FlatPass`,
so ``self`` is the pass; what it needs of the pass is declared at the top of
the class. See docs/multiview.rst.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Tuple

import numpy
from OpenGL.GL import (
    GL_CCW, GL_COLOR_BUFFER_BIT, GL_CW, GL_DEPTH_BUFFER_BIT, GL_SCISSOR_TEST,
    glClear, glClearColor, glDeleteBuffers, glDisable, glEnable, glFrontFace,
    glScissor, glViewport,
)

from OpenGLContext.arrays import array, asarray, dot
from OpenGLContext.passes import reflection
from OpenGLContext.passes.disposal import PassResources
import logging

if TYPE_CHECKING:
    from OpenGLContext.multiview.strategy import ViewFrame
    from OpenGLContext.passes._flat import GatheredPaths
    from OpenGLContext.passes.flateffects import Lighting
    from OpenGLContext.scenegraph import lod

log = logging.getLogger( __name__ )

__all__ = ( 'MultiviewPassMixin', )


class MultiviewPassMixin( PassResources ):
    """The views of a frame: their cameras, culls, shared draw and events."""

    if TYPE_CHECKING:
        context: Any
        shader_program: Any
        use_shaders: bool
        use_shadows: bool
        modelView: Any
        projection: Any
        modelproj: Any
        frustum: Any
        viewport: Any
        viewPlatform: Any
        maxDepth: Any
        matrix: Any
        visible: bool
        transparent: bool
        lighting: bool
        textured: bool
        mirroredDraw: bool
        visiblePlacements: Optional[Dict[int, Any]]
        _zoneHidden: Any

        def setViewPlatform( self, vp: Any ) -> None: ...
        def calculateFrustum( self ) -> Any: ...
        def chooseLevels( self, viewers: Sequence['lod.Viewer'] ) -> None: ...
        def gatherPaths( self ) -> 'GatheredPaths': ...
        def renderSet( self, matrix: Any,
                       gathered: Optional['GatheredPaths'] = None ) -> List[Any]: ...
        def greatestDepth( self, toRender: Sequence[Any] ) -> float: ...
        def zoneHiddenAt( self, camera: Any ) -> Any: ...
        def setupViewLighting( self, matrix: Any, lighting: Optional['Lighting'],
                               fitted: bool = False ) -> None: ...
        def shaderRenderOpaque( self, toRender: List, id_map: Optional[Dict] = None,
                                skip: Optional[set] = None ) -> None: ...
        def resetMeshDrawState( self ) -> None: ...
        def shaderSelectRenderOptimized( self, mode: Any, toRender: List,
                                         events: Dict ) -> None: ...
        def selectRender( self, mode: Any, toRender: Sequence[Any],
                          events: Dict[Any, Any] ) -> None: ...

    #: The cameras the shape being drawn is seen from, as points in the eye
    #: space it is drawn in, while one draw serves several views; None for a
    #: draw that serves one. What a shape choosing its detail by distance
    #: measures to; see :func:`OpenGLContext.scenegraph.tessellationlod.lod_level`.
    viewerEyes: Optional[List[Any]] = None
    #: How many views each draw of a shared ``vertex``-strategy draw reaches,
    #: so every draw is instanced that many times over; 0 otherwise. See
    #: :func:`OpenGLContext.multiview.strategy.draw_arrays`.
    viewCopies: int = 0

    def sharesDraw( self, record: Sequence[Any] ) -> bool:
        """Whether one draw of ``record`` can serve every view that sees it.

        True for an opaque shape whose geometry says it draws with the pass's
        lit programs alone (``multiviewShared``) and whose appearance brings no
        program of its own. A transparent or glass shape is sorted and drawn
        per view, an instanced set that culls its own placements culls them
        per view, and a mirror reads a different reflection in each view.
        """
        key, node = record[0], record[5]
        if key[0] or getattr( node, 'visiblePlacements', None ) is not None:
            return False
        if reflection.is_reflector( record ):
            return False
        if not getattr( getattr( node, 'geometry', None ), 'multiviewShared', False ):
            return False
        appearance = getattr( node, 'appearance', None )
        if getattr( appearance, 'bringsProgram', False ):
            return False
        material = getattr( appearance, 'material', None )
        return not ( getattr( material, 'transmission', 0.0 )
                     or getattr( material, 'octahedralViews', 0 ) )

    def sharedRecords( self, frames: Sequence['ViewFrame'],
                       reference: 'ViewFrame' ) -> Dict[int, List[Any]]:
        """The records one draw serves several views for, by view mask.

        Each is put in ``reference``'s eye space, which is where a shared draw
        is made; the mask says which views it is sent to. Grouped by mask so
        the draws of a group are made with one uniform setting. A wireframe
        view takes no part: ``glPolygonMode`` holds for every viewport at once,
        so it draws its shapes itself.
        """
        found: Dict[int, List[Any]] = {}
        for index, frame in enumerate( frames ):
            if frame.view.style.wireframe:
                continue
            for record in frame.toRender:
                if not self.sharesDraw( record ):
                    continue
                entry = found.get( id( record[4] ) )
                if entry is None:
                    found[id( record[4] )] = entry = [ record, 0 ]
                entry[1] |= 1 << index
        if not found:
            return {}
        entries = list( found.values() )
        worlds = asarray( [ record[2] for record, _mask in entries ], 'f' )
        modelviews = worlds @ asarray( reference.modelView, 'f' )
        groups: Dict[int, List[Any]] = {}
        for (record, mask), modelview in zip( entries, modelviews ):
            key, _mv, tmatrix, bvolume, path, node = record
            groups.setdefault( mask, [] ).append(
                ( key, modelview, tmatrix, bvolume, path, node ) )
        return groups

    #: The uniform buffer the ``ViewBlock`` table is uploaded to.
    _viewTable: Optional[int] = None

    def disposeResources( self ) -> None:
        """Release the view table."""
        table, self._viewTable = self._viewTable, None
        if table is not None:
            try:
                glDeleteBuffers( 1, [table] )
            except Exception:
                log.debug( 'deleting the view table failed', exc_info=True )
        super().disposeResources()

    def uploadViewTable( self, frames: Sequence['ViewFrame'],
                         reference: 'ViewFrame', capacity: int = 0 ) -> List[Any]:
        """Fill and bind the ``ViewBlock`` for drawing ``frames`` in ``reference``'s space.

        ``capacity`` is the views the bound programs were compiled for, which
        the block is filled out to. Returns the records, whose eyes the shapes
        measure their detail to.
        """
        from OpenGL import GL
        from OpenGLContext.multiview.strategy import (
            VIEW_BLOCK_BINDING, pack_view_table, view_records,
        )
        if self._viewTable is None:
            self._viewTable = int( GL.glGenBuffers( 1 ) )
        data = pack_view_table( frames, reference, capacity )
        GL.glBindBuffer( GL.GL_UNIFORM_BUFFER, self._viewTable )
        GL.glBufferData( GL.GL_UNIFORM_BUFFER, len( data ), data, GL.GL_DYNAMIC_DRAW )
        GL.glBindBuffer( GL.GL_UNIFORM_BUFFER, 0 )
        GL.glBindBufferBase( GL.GL_UNIFORM_BUFFER, VIEW_BLOCK_BINDING, self._viewTable )
        return view_records( frames, reference )

    def renderShared( self, frames: Sequence['ViewFrame'],
                      id_map: Optional[Dict[int, Any]],
                      lighting: Optional['Lighting'] = None, mirrored: bool = False,
                      capacity: int = 0, into_atlas: bool = False ) -> Optional[set]:
        """Draw every shape that can serve several views once, for all of them.

        The draw is made in the active view's eye space, exactly as that view
        alone would draw it -- its modelviews, lights and shadow matrices -- and
        programs compiled for this many views send each triangle to the views
        in the shape's mask, through the ``ViewBlock``: a geometry stage does it
        for the ``geometry`` strategy, and for ``vertex`` each draw is instanced
        once per view and the vertex stage routes each copy. Returns the ``id`` of every path drawn, for each view to
        leave out, or None where the programs for this many views did not
        compile and every view draws everything itself.

        ``into_atlas`` draws mirror views into the reflection atlas, in linear
        HDR. ``mirrored`` says every view's camera has been reflected an odd
        number of times, which turns the winding over and which the reference
        camera's modelviews do not say.

        ``capacity`` asks for programs compiled for at least that many views,
        for a caller whose count of views changes from frame to frame and
        would otherwise meet a compile at each new count.
        """
        from OpenGL import GL
        shader = self.shader_program
        assert shader is not None, 'a shared draw is made with the pass program'
        reference = self.activeFrame if self.activeFrame is not None else frames[0]
        groups = self.sharedRecords( frames, reference )
        if not groups:
            return set()
        strategy = self.multiviewStrategy or 'geometry'
        if not shader.select_program_set( max( len( frames ), capacity ), strategy ):
            self.multiviewFailed( strategy )
            return None
        drawn: set = set()
        try:
            self.applyViewFrame( reference, gl=False )
            rects = array( [ frame.rect for frame in frames ], 'f' )
            GL.glViewportArrayv( 0, len( frames ), rects )
            GL.glScissorArrayv( 0, len( frames ), rects.astype( 'i' ) )
            glEnable( GL_SCISSOR_TEST )
            records = self.uploadViewTable( frames, reference, shader.program_set )
            matrix = reference.modelView
            self.matrix = matrix
            self.visible = True
            self.transparent = False
            self.lighting = True
            self.textured = True
            self.setupViewLighting( matrix, lighting, fitted=reference.fitted )
            if into_atlas:
                hdr = getattr( shader, 'set_hdr_output', None )
                if hdr is not None:
                    hdr( True )
            if mirrored:
                from OpenGLContext.scenegraph.pbrmesh import PBRMesh
                self.mirroredDraw = True
                PBRMesh.reset_draw_state( self )
                glFrontFace( GL_CW )
            for mask, group in groups.items():
                shader.set_view_mask( mask )
                self.viewerEyes = [ record.eye for index, record in enumerate( records )
                                    if mask >> index & 1 ]
                if strategy == 'vertex':
                    self.viewCopies = len( self.viewerEyes )
                self.shaderRenderOpaque( group, id_map )
                drawn.update( id( record[4] ) for record in group )
            self.resetMeshDrawState()
        finally:
            self.viewerEyes = None
            self.viewCopies = 0
            if mirrored:
                self.mirroredDraw = False
                glFrontFace( GL_CCW )
            shader.select_program_set( 0 )
        return drawn

    def selectRenderViews( self, mode: Any, events: Dict[Any, Any],
                           debugSelection: bool ) -> None:
        """Resolve ``events`` by drawing the selection render, a view at a time.

        Each view draws its own shapes through its own camera into its own
        rectangle and resolves the events made in it. ``debugSelection`` puts
        the selection render on screen in place of the frame, so every view
        draws it whether or not it has an event to resolve.
        """
        grouped = { id( frame ): subset for frame, subset in self.eventsByView( events ) }
        try:
            for frame in self.viewFrames:
                subset = grouped.get( id( frame ) )
                if subset is None and not debugSelection:
                    continue
                self.applyViewFrame( frame )
                if self.use_shaders:
                    self.shaderSelectRenderOptimized( mode, frame.toRender, subset or {} )
                else:
                    self.selectRender( mode, frame.toRender, subset or {} )
        finally:
            self.finishViews()
        if self.activeFrame is not None:
            self.applyViewFrame( self.activeFrame, gl=False )

    #: This frame's views, each with its camera's matrices, frustum and draw
    #: list; the first frame's active view is :attr:`activeFrame`. Built by
    #: :meth:`layoutViews` and :meth:`prepareViews`.
    viewFrames: Sequence['ViewFrame'] = ()
    activeFrame: Optional['ViewFrame'] = None
    #: The view being drawn, for a node that draws differently per view.
    view: Any = None
    #: Whether the views are confined to their rectangles by the scissor
    #: test, which a frame of more than one view needs and one view does not.
    _scissorViews = False
    #: How this pass draws a frame of several views, settled the first time it
    #: draws one and again when the definition asks for another; see
    #: :mod:`OpenGLContext.multiview.strategy`.
    multiviewStrategy: Optional[str] = None
    #: What the definition asked for when :attr:`multiviewStrategy` was chosen.
    _multiviewRequested: Optional[str] = None
    #: The strategies whose programs would not compile on this pass's context.
    _multiviewFailed: Tuple[str, ...] = ()

    def chooseMultiview( self ) -> str:
        """The strategy the definition asks for, or the best this driver can build."""
        from OpenGLContext.multiview.strategy import (
            MultiviewCapabilities, requested_strategy,
        )
        self._multiviewRequested = requested_strategy( self )
        return MultiviewCapabilities.detect().choose(
            self._multiviewRequested, failed=self._multiviewFailed )

    def settleMultiview( self ) -> str:
        """The strategy this frame draws several views with.

        Chosen the first time it is asked for, and chosen again when the
        definition's ``multiview`` field no longer names what it was chosen
        for, so the settings screen's choice takes effect on the next frame.
        """
        from OpenGLContext.multiview.strategy import requested_strategy
        if ( self.multiviewStrategy is None
                or requested_strategy( self ) != self._multiviewRequested ):
            self.multiviewStrategy = self.chooseMultiview()
        return self.multiviewStrategy

    def sharesViews( self, frames: Sequence['ViewFrame'] ) -> bool:
        """Whether ``frames`` are drawn by one submission rather than in turn.

        That takes several views, a strategy that shares, and no more views
        than the driver has viewports.
        """
        if self.multiviewStrategy not in ( 'geometry', 'vertex' ) or len( frames ) < 2:
            return False
        from OpenGLContext.multiview.strategy import MultiviewCapabilities
        return len( frames ) <= MultiviewCapabilities.detect().max_views

    def multiviewFailed( self, strategy: str ) -> None:
        """Pass over ``strategy`` from now on, its programs having failed to compile.

        The frame that found out draws each view in turn; the next one uses
        the next strategy the driver offers.
        """
        self._multiviewFailed = self._multiviewFailed + ( strategy, )
        self.multiviewStrategy = self.chooseMultiview()

    _defaultLayout: Any = None

    def viewLayout( self, context: Any ) -> Any:
        """The :class:`~OpenGLContext.multiview.views.ViewLayout` this frame draws.

        The context's own, where it has one; otherwise a single view through
        the context's view platform, kept by the pass.
        """
        found = getattr( context, 'getViewLayout', None )
        if found is not None:
            return found()
        if self._defaultLayout is None:
            from OpenGLContext.multiview.views import ViewLayout
            self._defaultLayout = ViewLayout.single()
        return self._defaultLayout

    def layoutViews( self, context: Any ) -> List['ViewFrame']:
        """Place this frame's views and work out each one's camera.

        Leaves the pass looking through the layout's active view. Attachments
        pinned to the camera, the audio listener and the shadow cascades are
        placed from it.
        """
        from OpenGLContext.multiview.strategy import ViewFrame
        from OpenGLContext.multiview.views import tile_of
        layout = self.viewLayout( context )
        width, height = context.getViewPort()
        shown = layout.arrange( width, height ) or layout.views[:1]
        frames = []
        for view in shown:
            camera = view.camera if view.camera is not None else context.getViewPlatform()
            with tile_of( view, camera, ( width, height ) ):
                self.setViewPlatform( camera )
            frames.append( ViewFrame(
                view, camera, view.rect if view.visible else (0, 0, width, height),
                self.modelView, self.projection, self.modelproj,
                self.calculateFrustum(), fitted=view is layout.active,
            ) )
        active = next( ( frame for frame in frames if frame.fitted ), frames[0] )
        active.fitted = True
        self.viewFrames = frames
        self.activeFrame = active
        # A view clears and draws inside its own rectangle. One view filling
        # the window needs no scissor; anything else does, including a single
        # view an arrangement has placed in part of the window, whose
        # background would otherwise clear the whole of it.
        from OpenGLContext.multiview.views import covers
        self._scissorViews = ( len( frames ) > 1
                               or not covers( [ frames[0].rect ], width, height ) )
        # Settled for a frame of several views, and kept current once settled:
        # the reflections read it on a frame of one.
        if self._scissorViews or self.multiviewStrategy is not None:
            self.settleMultiview()
        self.applyViewFrame( active, gl=False )
        return frames

    def clearUncovered( self, context: Any, frames: List['ViewFrame'] ) -> None:
        """Clear the window where no view will draw in it.

        A view clears its own rectangle and nothing else, and a layout need not
        tile the window: an arrangement of an application's own can leave a
        band for a toolbar. What no view covers would otherwise hold the frame
        before it.
        """
        from OpenGLContext.multiview.views import covers
        width, height = context.getViewPort()
        if covers( [ frame.rect for frame in frames ], width, height ):
            return
        glDisable( GL_SCISSOR_TEST )
        glViewport( 0, 0, int( width ), int( height ) )
        glClearColor( 0.0, 0.0, 0.0, 1.0 )
        glClear( GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )

    def applyViewFrame( self, frame: 'ViewFrame', gl: bool = True ) -> None:
        """Look through ``frame``'s view: its camera, its rectangle, its draw list.

        Everything the draw stages read about the camera is on the pass --
        ``modelView``, ``projection``, ``frustum``, ``viewport``,
        ``visiblePlacements`` -- so drawing a view is setting these and running
        the same stages. ``gl`` also sets the viewport and, with several views,
        the scissor rectangle, so a clear and a wide line stay inside the tile.
        """
        self.view = frame.view
        self.viewPlatform = frame.camera
        self.modelView = frame.modelView
        self.projection = frame.projection
        self.modelproj = frame.modelproj
        self.frustum = frame.frustum
        self.viewport = frame.rect
        self.maxDepth = frame.maxDepth
        self.visiblePlacements = frame.visiblePlacements
        self.matrix = frame.modelView
        if gl:
            glViewport( *frame.rect )
            if self._scissorViews:
                glScissor( *frame.rect )
                glEnable( GL_SCISSOR_TEST )

    def prepareViews( self ) -> List['ViewFrame']:
        """Cull and sort the scene once per view, from one walk of it.

        Levels of detail are chosen first, for every view at once, since a
        level that changes replaces a subtree the walk has to see. Each view
        then culls the one table against its own frustum and trims its
        projection to the depth of what it kept.
        """
        from OpenGLContext.multiview.views import tile_of
        from OpenGLContext.scenegraph.lod import viewer_for
        frames = list( self.viewFrames )
        window = self.context.getViewPort()
        self.chooseLevels( [
            viewer_for( frame.camera, frame.modelView, frame.projection )
            for frame in frames ] )
        # Kept for the frame: the shadow casters, each mirror view and each
        # zone capture read the same walk.
        gathered = self.gatherPaths()
        for frame in frames:
            self.applyViewFrame( frame, gl=False )
            # Nodes the zones hide from this view's camera are left out of its
            # cull; the active view's set stands for the frame's other draws.
            self._zoneHidden = self.zoneHiddenAt( self.cameraPosition( frame ) )
            frame.toRender = self.renderSet( frame.modelView, gathered )
            frame.visiblePlacements = self.visiblePlacements or {}
            frame.maxDepth = self.greatestDepth( frame.toRender )
            if frame.maxDepth:
                with tile_of( frame.view, frame.camera, window ):
                    frame.projection = frame.camera.viewMatrix( frame.maxDepth )
                # The frustum stays the one the view was culled with.
                frame.modelproj = dot( asarray( frame.modelView, 'f' ),
                                       asarray( frame.projection, 'f' ) )
        active = self.activeFrame if self.activeFrame is not None else frames[0]
        self.applyViewFrame( active, gl=False )
        self._zoneHidden = self.zoneHiddenAt( self.cameraPosition( active ) )
        return frames

    @staticmethod
    def cameraPosition( frame: 'ViewFrame' ) -> Any:
        """Where ``frame``'s camera is in the world, or None."""
        try:
            return numpy.linalg.inv( asarray( frame.modelView, 'd' ) )[3, :3]
        except numpy.linalg.LinAlgError:
            return None

    def frameForEvent( self, event: Any ) -> Optional['ViewFrame']:
        """The view a pick event is resolved through.

        The one the context routed it to, where that view was drawn this frame;
        otherwise the one under its pick point; otherwise the active view.
        """
        frames = self.viewFrames
        routed = getattr( event, 'view', None )
        for frame in frames:
            if frame.view is routed:
                return frame
        point = event.getPickPoint() if hasattr( event, 'getPickPoint' ) else None
        if point:
            for frame in frames:
                if frame.view.contains( point[0], point[1] ):
                    return frame
        return self.activeFrame

    def eventsByView( self, events: Dict[Any, Any] ) -> List[Tuple['ViewFrame', Dict[Any, Any]]]:
        """``events`` divided among the views they are resolved through, in draw order."""
        grouped: Dict[int, Dict[Any, Any]] = {}
        for key, event in events.items():
            frame = self.frameForEvent( event )
            if frame is not None:
                grouped.setdefault( id( frame ), {} )[key] = event
        return [ ( frame, grouped[id( frame )] ) for frame in self.viewFrames
                 if id( frame ) in grouped ]

    def finishViews( self ) -> None:
        """Give the whole window back once every view is drawn, or once one has failed.

        The scissor test goes off whatever this frame's layout was, so a frame
        that stopped part-way through its views leaves nothing confined to a
        tile for the frame after it.
        """
        glDisable( GL_SCISSOR_TEST )
        width, height = self.context.getViewPort()
        glViewport( 0, 0, int(width), int(height) )
