"""What every flat pass does, whichever profile it draws through

The flat pass observes the scenegraph's structure and draws it once per frame
in a fixed sequence -- background, opaque, transmissive, transparent, selection
and overlay -- rather than traversing it once per rendering mode.  This module
holds the part that is the same either way: the traversal, the sorting, the
frustum culling, the pick queue and the matrix stack.

It is a base class and not something to instantiate.  The two concrete passes
are :mod:`OpenGLContext.passes.flatcore` (GLSL, core profile) and
:mod:`OpenGLContext.passes.flatcompat` (fixed function, compatibility
profile), and :mod:`OpenGLContext.passes.renderpass` chooses between them for
a context and caches the choice across frames.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from OpenGLContext.scenegraph import nodepath,switch,boundingvolume,lod
from OpenGL.GL import *
from OpenGL.GL import (
    glEnable, glDisable, glDisablei, glBlendFunc, glDepthMask, glDepthFunc,
    glClear, glClearColor,
    GL_BLEND, GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_LEQUAL, GL_DEPTH_TEST,
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
)
# numpy names re-exported dynamically through OpenGLContext.arrays; mypy cannot
# see them, so the attr-defined here is a false positive.
from OpenGLContext.arrays import (  # type: ignore[attr-defined]
    arange, array, asarray, dot, flatnonzero, zeros,
)
from OpenGLContext import frustum
from OpenGLContext.debug.logs import getTraceback
from OpenGLContext.passes.renderfailures import describe
from vrml.vrml97 import nodetypes
from vrml import olist
from OpenGLContext.scenegraph import shaders
from pydispatch.dispatcher import connect
import logging
log = logging.getLogger( __name__ )

if TYPE_CHECKING:
    from OpenGLContext.passes.renderfailures import RenderFailureLog
    from OpenGLContext.passes.renderstats import RenderStats
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

__all__ = (
    'SGObserver',
    'FlatPass',
    'get_inv_modelproj',
    'get_inv_modelview',
    'get_modelproj',
    'get_modelview',
    'get_projection',
)


from OpenGLContext.passes.selection import (
    SelectionMixin,
)
from OpenGLContext.passes.flateffects import _FlatEffectsMixin

# MRT draw-buffer index carrying the packed object id (attachment 1).
OBJECT_ID_ATTACHMENT = 1


def disable_object_id_blend() -> None:
    """Keep the object-id MRT attachment out of alpha blending.

    The transparent / transmissive passes enable blending for the colour
    attachment; the same enable would blend the packed object id in attachment 1,
    so a pick behind transparent geometry reads a corrupted (averaged) id. Indexed
    blend enables (core GL 3.3) switch blending off for just that attachment. A
    later ``glEnable(GL_BLEND)`` re-enables all attachments, so this must be issued
    after each pass turns blending on. Best-effort: drivers without indexed enables
    simply keep the prior (harmless in the single-attachment case) behaviour.
    """
    try:
        glDisablei(GL_BLEND, OBJECT_ID_ATTACHMENT)
    except Exception as err:
        log.debug("indexed blend disable unavailable: %s", err)
class SGObserver( object ):
    """Observer of a scenegraph that creates a flat set of paths

    Uses dispatcher watches to observe any changes to the (rendering)
    structure of a scenegraph and uses it to update an internal set
    of paths for all renderable objects in the scenegraph.
    """
    INTERESTING_TYPES = []

    #: Counts changes to the *set* of paths rendered from, so per-path data
    #: gathered against it is rebuilt rather than read against a set it no
    #: longer describes. Declared on the class rather than set up in
    #: ``__init__`` because a pass may be built by a subclass or a test harness
    #: that never reaches this one, and a gather must work on any of them.
    _pathGeneration = 0
    #: The ``(N,8,4)`` array :meth:`_boundingArrays` stacks corners into, kept
    #: so a frame allocates nothing for a scene whose size has not changed.
    _pointsBuffer = None
    #: The ``(N,4,4)`` array :meth:`_worldMatrices` fills each frame, kept so a
    #: frame allocates nothing for a scene whose size has not changed.
    _matrixBuffer = None
    #: Which copies of each declared set this gather's frustum kept, by ``id``
    #: of the record's path. Belongs to the gather rather than to the shapes: a
    #: depth pass culling against a light must not read the camera's answer.
    visiblePlacements = None

    def _pathSetChanged( self ):
        """Say that the set of paths to render is not the one last gathered."""
        self._pathGeneration += 1

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
            _ = self.npFor(next)
            for typ in self.INTERESTING_TYPES:
                if isinstance( next, typ ):
                    self.paths.setdefault( typ, []).append( path )
                    self._pathSetChanged()
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
        """A Switch has chosen a different child, or none at all.

        `value` is None for a Switch drawing nothing -- `whichChoice` of -1,
        which is how VRML97 hides a subtree. Then there is only the old path to
        break, and nothing to walk in its place.

        A Switch may name the child it already has -- level-of-detail assigns
        its choice from the viewer's distance every frame -- so a live path to
        `value` is kept rather than walked again. Exactly one survives: walking
        it afresh each time would leave a second path to the same node, and a
        third, each holding the transforms cached against it.
        """
        for path in self.npFor( sender ):
            keeping = None
            for childPath in path.iterchildren():
                if ( value is not None and childPath[-1] is value
                     and not childPath.broken and keeping is None ):
                    keeping = childPath
                else:
                    childPath.invalidate()
            if value is not None and keeping is None:
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
        """Drop every path whose subtree has left the scenegraph

        Both records have to let go. ``paths`` is the draw set a render walks;
        ``nodePaths`` is keyed by node and holds a path for every integrated
        node, including nodes this pass draws nothing for, so it cannot be
        maintained from ``paths`` alone.

        A path left in either record keeps alive every transform matrix cached
        against it, and each of those caches stays registered for the fields it
        depends on. Content streaming in and out of a world then grows the set
        of receivers every sender must notify, so the cost of a frame rises
        with how long the session has run rather than with what is on screen.
        """
        dropped = []
        for key, values in self.paths.items():
            live = []
            for v in values:
                if v.broken:
                    dropped.append( v )
                else:
                    live.append( v )
            if len(live) != len(values):
                self._pathSetChanged()
            values[:] = live
        for node_id in list( self.nodePaths.keys() ):
            paths = self.nodePaths[node_id]
            # By identity, not equality: two distinct paths running the same
            # route compare equal, and only this one is known to be broken.
            live = [ p for p in paths if not p.broken ]
            if len(live) == len(paths):
                continue
            dropped.extend([ p for p in paths if p.broken ])
            if live:
                paths[:] = live
            else:
                del self.nodePaths[node_id]
        # Drop the removed paths' persistent picking ids so a later pick can't
        # resolve a stale object.
        sel_map = getattr( self, '_sel_id_map', None )
        if sel_map is not None:
            for v in dropped:
                oid = getattr( v, '_sel_id', 0 )
                if oid:
                    sel_map.pop( oid, None )

def get_modelview( shader, mode ):
    return mode.matrix 
def get_projection( shader, mode ):
    return mode.projection 
def get_modelproj( shader, mode ):
    return dot( mode.matrix, mode.projection )

def get_inv_modelview( shader, mode ):
    return dot( mode.viewPlatform.modelMatrix(inverse=True), mode.renderPath.transformMatrix( inverse=True ) )
def get_inv_projection( shader, mode ):
    return mode.viewPlatform.viewMatrix( mode.maxDepth, inverse=True )
def get_inv_modelproj( shader, mode ):
    mv = get_inv_modelview( shader, mode )
    proj = get_inv_projection( shader, mode )
    return dot( proj, mv )

def _color_select_render(pass_obj, mode, toRender, events, *,
                         id_shift, read_format, setup_fixed_function,
                         require_pick_enabled):
    """Shared legacy colour-buffer pick.

    Draws every renderable path in a unique colour-encoded id, reads back the id
    under each pick point and resolves it to a path. The compatibility and
    core-fallback passes differ only in how the id is packed and read and whether
    the fixed-function lighting state is toggled -- passed in here so the ~90-line
    body lives in one place instead of two copies that had already diverged. This
    is the legacy fallback; the modern path is ``SelectionMixin`` (MRT).
    """
    self = pass_obj
    glClearColor(0, 0, 0, 0)
    glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
    if setup_fixed_function:
        glDisable(GL_LIGHTING)
        glEnable(GL_COLOR_MATERIAL)

    self.visible = False
    self.transparent = False
    self.lighting = False
    self.textured = False

    matrix = self.matrix
    id_map = {}

    pick_points = {}
    min_x, min_y = self.getViewport()[2:]
    max_x, max_y = 0, 0
    offset = 1   # half of the 2px pick square
    for event in events.values():
        x, y = key = tuple(event.getPickPoint())
        pick_points.setdefault(key, []).append(event)
        min_x = min((x - offset, min_x))
        max_x = max((x + offset, max_x))
        min_y = min((y - offset, min_y))
        max_y = max((y + offset, max_y))
    min_x = int(max((0, min_x)))
    min_y = int(max((0, min_y)))
    if max_x < min_x or max_y < min_y:
        return   # no pick points

    cd = mode.context.contextDefinition
    debug_selection = cd.debugSelection and (cd.pickEnabled or not require_pick_enabled)
    if not debug_selection:
        glScissor(min_x, min_y, int(max_x) - min_x, int(max_y) - min_y)
        glEnable(GL_SCISSOR_TEST)

    glMatrixMode(GL_MODELVIEW)
    try:
        id_holder = array([0, 0, 0, 0], 'B')
        id_setter = id_holder.view('<I')
        for index, (key, mvmatrix, tmatrix, bvolume, path) in enumerate(toRender):
            color_id = (index + 1) << id_shift
            id_setter[0] = color_id
            glColor4ubv(id_holder)
            self.matrix = mvmatrix
            self.renderPath = path
            glLoadMatrixf(mvmatrix)
            path[-1].Render(mode=self)
            id_map[color_id] = path
        pixel = array([0, 0, 0, 0], 'B')
        depth_pixel = array([[0]], 'f')
        for point, event_set in pick_points.items():
            px, py = int(point[0]), int(point[1])
            glReadPixels(px, py, 1, 1, read_format, GL_UNSIGNED_BYTE, pixel)
            lpixel = int(pixel.view('<I')[0])
            paths = id_map.get(lpixel, [])
            glReadPixels(px, py, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, depth_pixel)
            for event in event_set:
                event.setObjectPaths([paths])
                event.viewCoordinate = point[0], point[1], depth_pixel[0][0]
                event.modelViewMatrix = matrix
                event.projectionMatrix = self.projection
                event.viewport = self.viewport
                if hasattr(mode.context, 'ProcessEvent'):
                    mode.context.ProcessEvent(event)
    finally:
        glColor4f(1.0, 1.0, 1.0, 1.0)
        glDisable(GL_COLOR_MATERIAL)
        glEnable(GL_LIGHTING)
        glDisable(GL_SCISSOR_TEST)


def presentFrame( context ):
    """Hand the finished frame to ``context`` to put on the screen.

    Not ``SwapBuffers``: presenting the frame is the context's own step, and it
    is the last moment the frame can be read -- the screenshot key and the
    capture machinery both read it there.  See
    :meth:`OpenGLContext.context.Context.presentFrame`.  A context that predates
    that method, or that is not one of ours, is simply swapped.
    """
    present = getattr( context, 'presentFrame', None )
    if present is not None:
        return present()
    return context.SwapBuffers()


class FlatPass( _FlatEffectsMixin, SelectionMixin, SGObserver ):
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

        use_shaders -- whether to use shader-based rendering (core-profile compatible)
        shader_mode -- indicates shader mode is active (for geometry nodes to check)
        shader_program -- the VRML97ShaderProgram instance when use_shaders is True


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

    #: What the frame being drawn cost, in shapes and draw calls.  Read
    #: through the developer overlay; see OpenGLContext.passes.renderstats.
    _stats: Optional['RenderStats'] = None

    #: What could not draw, for the life of this pass rather than of a frame.
    #: See OpenGLContext.passes.renderfailures.
    _failures: Optional['RenderFailureLog'] = None

    @property
    def stats(self) -> 'RenderStats':
        """This pass's frame counts, made on first use and then reused.

        One object for the life of the pass rather than one per frame, so a
        context that took a reference to it keeps reading live numbers.
        """
        if self._stats is None:
            from OpenGLContext.passes.renderstats import RenderStats
            self._stats = RenderStats()
        return self._stats

    @property
    def failures(self) -> 'RenderFailureLog':
        """The causes of failure this pass has seen, made on first use."""
        if self._failures is None:
            from OpenGLContext.passes.renderfailures import RenderFailureLog
            self._failures = RenderFailureLog()
        return self._failures

    def renderFailed(self, where: str, node: Any, err: BaseException) -> None:
        """Note that ``node`` did not draw as it should have, and say so once.

        Catching what a node raises is what keeps one bad node from taking the
        frame with it; counting it is what keeps the resulting black window from
        being silent. The explanation goes out for the first occurrence of each
        cause and the rest are tallied for the summary at teardown.
        """
        if self.failures.record(where, node, err):
            log.error('Failure in %s render: %s', where, describe(err))

    def reportFailures(self) -> None:
        """Say what this pass could not draw, if anything failed at all.

        Through ``_failures`` rather than :attr:`failures` so a pass that had
        nothing go wrong does not make a log to report an empty one.
        """
        if self._failures is not None:
            self._failures.report()

    # Shader-based rendering support
    use_shaders: bool = False
    shader_mode: bool = False  # Set True during shader render passes
    shader_program: Optional['VRML97ShaderProgram'] = None
    _shader_program_instance: Optional['VRML97ShaderProgram'] = None

    # Shadow-mapping support (provided by ShadowMapMixin; no-ops on the base pass)
    use_shadows: bool = False
    shadow_pass: bool = False

    # IBL / transmission / bloom / cull phases live in _FlatEffectsMixin; the
    # first-frame block sets _gl_renderer, which those phases read.
    _gl_renderer: str = ''

    def renderShadowMaps(self, toRender):
        """Render shadow depth maps before the lit passes (mixin override)."""
        return None   # base pass has no shadows; ShadowMapMixin overrides this

    def bindShadowUniforms(self):
        """Bind shadow maps onto the lit program after lights (mixin override)."""
        return None   # base pass has no shadows; ShadowMapMixin overrides this

    # The selection framebuffers, picking methods and use_mrt_selection flag live
    # in SelectionMixin.
    # Frames for which to keep reading back the MRT id/depth buffers. Reading the
    # whole id+depth buffer every frame is a CPU cost and a GPU pipeline stall;
    # since the readback only feeds pick lookups, we do it only while picking is
    # active (events seen) and for a couple of frames after, then stop.
    _pick_warm_frames: int = 0
    _PICK_WARM_RESET: int = 3

    _UNIFORM_NAMES = '''mat_modelview inv_modelview tps_modelview itp_modelview 
        mat_projection inv_projection tps_projection itp_projection
        mat_modelproj inv_modelproj tps_modelproj itp_modelproj'''.split()

    _uniforms = None
    @property 
    def uniforms( self ):
        if self._uniforms is None:
            self._uniforms = []
            for name in self._UNIFORM_NAMES:
                attr = 'uniform_%s'%(name,)
                uniform = shaders.FloatUniformm4( name=name )
                self._uniforms.append( uniform )
                setattr( self, attr, uniform )
                if name.startswith( 'tps_' ) or name.startswith( 'itp_' ):
                    uniform.NEED_TRANSPOSE = True 
                else:
                    uniform.NEED_TRANSPOSE = False
                if name.startswith( 'inv_' ) or name.startswith( 'itp_' ):
                    uniform.NEED_INVERSE = True 
                else:
                    uniform.NEED_INVERSE = False 
            # now set up the lazy calculation operations 
            self.uniform_mat_modelview.currentValue = get_modelview
            self.uniform_mat_projection.currentValue = get_projection
            self.uniform_mat_modelproj.currentValue = get_modelproj
            self.uniform_tps_modelview.currentValue = get_modelview
            self.uniform_tps_projection.currentValue = get_projection
            self.uniform_tps_modelproj.currentValue = get_modelproj
            
            self.uniform_inv_modelview.currentValue = get_inv_modelview
            self.uniform_inv_projection.currentValue = get_inv_projection
            self.uniform_inv_modelproj.currentValue = get_inv_modelproj
            self.uniform_itp_modelview.currentValue = get_inv_modelview
            self.uniform_itp_projection.currentValue = get_inv_projection
            self.uniform_itp_modelproj.currentValue = get_inv_modelproj
            
        return self._uniforms
    
    def applyUniforms( self, shader ):
        """Apply our uniforms to the shader as appropriate"""
        for uniform in self.uniforms:
            uniform.render( shader, self )

    def getShaderProgram(self) -> 'VRML97ShaderProgram':
        """Get or create the shader program for this render pass.

        Returns:
            VRML97ShaderProgram instance
        """
        if self._shader_program_instance is None:
            from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
            self._shader_program_instance = VRML97ShaderProgram()
        return self._shader_program_instance

    def current_program(self) -> int:
        """The GL program this pass currently expects bound during its geometry loop.

        A raw-GL geometry node (vegetation, terrain, particles) that binds its own
        program to draw restores to this afterwards, so the pass's meshes keep the
        program the pass bound for them -- without a ``glGetIntegerv(GL_CURRENT_PROGRAM)``
        round-trip per node. Both the VRML97 and PBR passes track the live program on
        their ``shader_program`` (the PBR pass's is a ``PBRShaderProgram`` subclass),
        so one implementation serves both."""
        sp = self._shader_program_instance
        if sp is None:
            return 0
        return int(getattr(sp, '_active_program', 0) or getattr(sp, 'program', 0) or 0)

    def setupShaderLights(self, matrix: Any) -> None:
        """Set up lights for shader-based rendering.

        Args:
            matrix: Base modelview matrix (camera view matrix)
        """
        from OpenGLContext.passes.shaderpass import configure_light_from_node

        shader = self.shader_program
        shader.use(lit=True)  # Ensure shader is bound before setting uniforms
        light_count = 0
        light_paths = self.paths.get(nodetypes.Light, ())
        ceiling = self.maxLights(shader.MAX_LIGHTS)

        for path in light_paths:
            if light_count >= ceiling:
                break
            tmatrix = path.transformMatrix()
            light_node = path[-1]
            if hasattr(light_node, 'on') and light_node.on:
                # Transform light to eye space (combine light's transform with view matrix)
                # This matches how fixed-function glLightfv works - it transforms
                # the light position/direction by the current modelview matrix
                light_matrix = dot(tmatrix, matrix)
                configure_light_from_node(shader, light_count, light_node, light_matrix)
                light_count += 1

        if light_count == 0:
            # Set default VRML97 headlight (direction already in eye space)
            shader.set_default_light()
            log.debug("Using default headlight")
        else:
            shader.set_num_lights(light_count)
            log.debug("Set up %d lights", light_count)

    def maxLights(self, ceiling: int) -> int:
        """Lights to bind this frame.  The base pass uses all the shader has."""
        return int(ceiling)

    def shaderBackgroundRender(self, vp: Any, matrix: Any) -> None:
        """Render background for shader mode.

        Uses the shader-based RenderShader method on background nodes
        when available, falling back to legacy rendering for backgrounds
        that don't support shader rendering (e.g. CubeBackground already
        has its own shader implementation).

        Args:
            vp: View platform
            matrix: Base matrix
        """
        bPath = self.currentBackground()
        if bPath is not None:
            # Set up matrix for background rendering
            self.matrix = dot(
                vp.quaternion.matrix(dtype='f'),
                bPath.transformMatrix(translate=0, scale=0, rotate=1)
            )
            background = bPath[-1]
            # Check if background has shader rendering capability
            if hasattr(background, 'RenderShader'):
                background.RenderShader(mode=self, clear=True)
            else:
                # For CubeBackground or other backgrounds with their own shader
                background.Render(mode=self, clear=True)
        else:
            # Default VRML background is black
            glClearColor(0.0, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    @staticmethod
    def _materialSortKey(rec) -> int:
        """Group key so shapes sharing one material batch together in the draw.

        Identity of the material object; glTF/CAD loaders share one material
        instance across the parts that use it, so this collapses hundreds of
        parts to a handful of appearance uploads. Alive-this-frame, so ids are
        stable within the sort.
        """
        shape = rec[4][-1]
        appearance = getattr(shape, 'appearance', None)
        return id(getattr(appearance, 'material', None))

    def shaderRenderOpaque(self, toRender: List, id_map: Optional[Dict] = None,
                           skip: Optional[set] = None) -> None:
        """Render opaque geometry using shaders.

        Args:
            toRender: List of (sortKey, mvmatrix, tmatrix, bvolume, path) tuples
            id_map: Optional dict to populate with {object_id: path} for MRT selection.
                   If provided, object IDs will be set for each rendered object.
            skip: Optional set of toRender indices to omit (transmissive shapes,
                   which draw in shaderRenderTransmissive after the backdrop capture).
        """
        self.transparent = False
        debugFrustum = self.context.contextDefinition.debugBBox

        shader = self.shader_program
        assert shader is not None  # shader passes only run with a program bound
        shader._pick_active = id_map is not None
        shader.use(lit=True)
        # New frame: forget the last material so per-frame edits are re-uploaded.
        reset = getattr(shader, 'reset_appearance_cache', None)
        if reset is not None:
            reset()

        # Draw opaque geometry front-to-back so the GPU's early depth test can
        # reject occluded fragments before the (expensive) PBR fragment shader
        # runs -- this cuts overdraw cost, which dominates at high resolution.
        # The original toRender index is kept as the stable picking object id.
        opaque: List[Tuple[Optional[int], Any]] = [(i, rec) for i, rec in enumerate(toRender)
                  if not rec[0][0] and not (skip and i in skip)]
        # Opaque draw order is depth-buffer-correct in any order, so group by
        # material first (a CAD assembly is hundreds of parts sharing a handful of
        # materials); consecutive same-material shapes then skip the per-shape
        # appearance re-upload. Front-to-back is kept as the secondary key so early
        # depth rejection still helps within each material group.
        opaque.sort(key=lambda ir: (self._materialSortKey(ir[1]), -ir[1][1][3][2]))

        prog = shader.program

        # Instanced fast path: collapse groups of shapes that share one geometry
        # (and a compatible appearance) into single instanced draws, cutting the
        # O(N) per-object draw cost that dominates large duplicated-geometry
        # scenes. Off in the base pass; PBRPass enables it when the driver and
        # program support the per-instance attributes. Everything not grouped
        # (unique geometry, sub-threshold batches) falls through to the loop.
        singles: List[Tuple[Optional[int], Any]] = opaque
        if getattr(self, 'instancing_enabled', False):
            from OpenGLContext.passes.instancing import build_instance_groups
            groups, single_recs = build_instance_groups(
                [rec for (_i, rec) in opaque],
                min_instances=self.instanceMinimum(),
                key=self._instanceKey,
                instanceable=self._instanceable,
            )
            for group in groups:
                try:
                    self._drawInstanceGroup(group, shader, prog, id_map)
                except Exception as err:
                    self.renderFailed('instanced', group, err)
                else:
                    self.stats.instanceGroups += 1
                    self.stats.instances += len(group)
                    self.stats.draws += 1
            singles = [(None, rec) for rec in single_recs]

        self.stats.opaque += len(singles)
        self.stats.draws += len(singles)
        for obj_index, (key, mvmatrix, tmatrix, bvolume, path) in singles:
            self.matrix = mvmatrix
            self.renderPath = path

            # Set matrices for this object (pass the program to avoid a per-draw
            # glGetIntegerv(GL_CURRENT_PROGRAM) round-trip).
            shader.set_matrices(mvmatrix, self.projection, program=prog)

            # Set object ID for MRT selection buffer (stable per-path id; the
            # persistent map is maintained by _objectIdFor, not rebuilt here).
            # A non-pickable shape masks the id attachment instead, reading
            # through to whatever is behind it.
            masked = self._writeShapeId(shader, path, prog, id_map)

            try:
                path[-1].Render(mode=self)
                if debugFrustum and bvolume:
                    bvolume.debugRender()
            except Exception as err:
                self.renderFailed('opaque', path[-1], err)
            finally:
                self._restoreShapeId(masked)

        shader.unuse()

    def shaderRenderTransparent(self, toRender: List, id_map: Optional[Dict] = None) -> None:
        """Render transparent geometry using shaders.

        Args:
            toRender: List of (sortKey, mvmatrix, tmatrix, bvolume, path) tuples
            id_map: Optional dict to populate with {object_id: path} for MRT selection.
                   If provided, object IDs will be set for each rendered object.
        """
        # Blended surfaces (glTF alphaMode=BLEND, or VRML97 transparency>0) draw
        # after all opaque geometry, back-to-front, with depth writes disabled so
        # overlapping translucent layers accumulate in the correct order. The
        # original toRender index is preserved as the picking object id.
        transparent = [(i, rec) for i, rec in enumerate(toRender) if rec[0][0]]
        if not transparent:
            return
        self.stats.transparent += len(transparent)
        self.stats.draws += len(transparent)
        # Eye looks down -z, so farthest-first is ascending eye-space origin z.
        transparent.sort(key=lambda ir: ir[1][1][3][2])

        self.transparent = True
        debugFrustum = self.context.contextDefinition.debugBBox

        shader = self.shader_program
        assert shader is not None  # shader passes only run with a program bound
        shader._pick_active = id_map is not None
        shader.use(lit=True)
        glEnable(GL_BLEND)
        if id_map is not None:
            disable_object_id_blend()   # don't blend the picking id (4.6)
        # Straight (non-premultiplied) alpha src-over: src*srcA + dst*(1-srcA).
        # This is coupled to the shader's alpha output: both the
        # VRML97 (vrml97_lighting.frag: `alpha = 1.0 - transparency`) and PBR
        # fragment shaders emit alpha as *opacity*, so these are the correct
        # factors. The legacy fixed-function path (renderTransparent below) emits
        # alpha as *transparency* and therefore uses the reversed factors -- do not
        # unify the two blindly; changing one side without the other inverts every
        # transparent surface. Locked by tests/test_transparent_blend.py.
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glDepthMask(0)
        glDepthFunc(GL_LEQUAL)
        prog = shader.program

        try:
            for obj_index, (key, mvmatrix, tmatrix, bvolume, path) in transparent:
                self.matrix = mvmatrix
                self.renderPath = path

                # Set matrices for this object (pass program to avoid a
                # per-draw glGetIntegerv round-trip).
                shader.set_matrices(mvmatrix, self.projection, program=prog)

                # Set object ID for MRT selection buffer (stable per-path id),
                # or mask it for a non-pickable shape.
                masked = self._writeShapeId(shader, path, prog, id_map)

                try:
                    path[-1].RenderTransparent(mode=self)
                    if debugFrustum and bvolume:
                        bvolume.debugRender()
                except Exception as err:
                    self.renderFailed('transparent', path[-1], err)
                finally:
                    self._restoreShapeId(masked)
        finally:
            self.transparent = False
            shader.unuse()
            glDisable(GL_BLEND)
            glDepthMask(1)
            glDepthFunc(GL_LEQUAL)
            glEnable(GL_DEPTH_TEST)

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
        nodetypes.Auditory,
        # Not a nodetype but a node class: an LOD has to be found again each
        # frame so it can be told where the viewer is, and the same path
        # bookkeeping that finds the lights will find it.
        lod.LOD,
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

    def currentFog( self ):
        """The bound Fog node's path, or None.

        Bindable like the background: the first node that says it is bound
        wins, and with none bound the first found is bound and used, so a scene
        that simply contains a fog gets it without anyone sending `set_bind`.
        """
        from OpenGLContext.scenegraph.fog import bound_fog
        return bound_fog( self.paths.get( nodetypes.Fog, () ) )

    # Persistent object-id <-> path map for MRT picking. Stable per-path ids
    # (stashed on the NodePath) mean the {id: path} map is only mutated when the
    # scene structure changes, not rebuilt every warm frame -- the O(N) build
    # dominated pick cost on 10^5-part scenes. See purge() for invalidation.
    _sel_id_map = None
    _sel_next = 1

    # Instanced-geometry hooks. The base pass never instances; PBRPass overrides
    # instancing_enabled + the two methods below.
    instancing_enabled = False

    def instanceMinimum( self ) -> int:
        """Smallest group worth collapsing into one instanced draw.

        Instancing has a fixed per-batch setup cost, so a pair of shapes is
        cheaper drawn as a pair. The shader passes override this to read
        OPENGLCONTEXT_INSTANCE_MIN.
        """
        return 8

    def _instanceable( self, path ) -> bool:
        """Whether this path's geometry can be drawn instanced (base: never)."""
        return False

    def _instanceKey( self, path ):
        """Batch key for a path. Base: geometry + material + texture identity, so a
        group is a set of visually identical shapes. PBRPass widens this to
        geometry + texture set (materials vary per instance via a material array)."""
        from OpenGLContext.passes.instancing import geometry_instance_key
        return geometry_instance_key( path )

    def _drawInstanceGroup( self, group, shader, prog, id_map ):
        """Draw one InstanceGroup in a single instanced call (subclass override)."""
        raise NotImplementedError(
            "instancing_enabled is True but _drawInstanceGroup is not implemented"
        )

    def _shapePickable( self, path ):
        """Whether this path's rendered node accepts picks (the default).

        The ``pickable`` flag is opt-out: only a Shape explicitly marked
        ``pickable=False`` is skipped; any node without the field (non-Shape
        renderables) stays pickable.
        """
        return bool( getattr( path[-1], 'pickable', True ) )

    def _writeShapeId( self, shader, path, prog, id_map ):
        """Set this shape's object id, or mask the id attachment if non-pickable.

        Returns True when the id attachment (MRT draw buffer OBJECT_ID_ATTACHMENT)
        was masked off; the caller must restore it with ``_restoreShapeId`` once
        the shape has drawn. A masked shape is never allocated an id, so it can
        neither be resolved from the id map nor overwrite the id of geometry
        behind it -- the pick reads straight through.
        """
        if id_map is None:
            return False
        if self._shapePickable( path ):
            shader.set_object_id( self._objectIdFor( path ), program=prog )
            return False
        glColorMaski( OBJECT_ID_ATTACHMENT, GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE )
        return True

    def _restoreShapeId( self, masked ):
        """Re-enable writes to the id attachment after a masked (non-pickable) draw."""
        if masked:
            glColorMaski( OBJECT_ID_ATTACHMENT, GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE )

    def _objectIdFor( self, path ):
        """Return this path's stable object-id, allocating on first sight.

        The id is independent of draw/sort order (transparent shapes reorder with
        the camera), so the persistent map stays valid across frames.
        """
        if self._sel_id_map is None:
            self._sel_id_map = {}
        oid = getattr( path, '_sel_id', 0 )
        if not oid:
            oid = self._sel_next
            self._sel_next += 1
            path._sel_id = oid
            self._sel_id_map[oid] = path
        return oid

    def _selectionIdMap( self ):
        """The persistent {object_id: path} map (created lazily)."""
        if self._sel_id_map is None:
            self._sel_id_map = {}
        return self._sel_id_map

    def renderAudio( self, context ):
        """Keep the scene's sounds in step with the camera, for this frame.

        Delegates to :func:`OpenGLContext.audio.scene.update`; everything the
        engine needs -- the listener pose, the emitters' world positions, which
        voices start and stop -- is worked out there.  Returns how many nodes
        were driven, which is what the developer overlay reports.

        **A scene with nothing audible in it costs nothing**: no device is
        opened and no audio thread starts until a frame is drawn containing an
        ``Auditory`` node.  And a failure here is a warning, never a lost
        frame: a sound card that disappears mid-session must not take the
        window with it.
        """
        paths = self.paths.get( nodetypes.Auditory, () )
        if not paths:
            return 0
        try:
            from OpenGLContext.audio import scene as audioscene
            return audioscene.update( context, paths )
        except Exception as err:
            log.warning(
                "Failure updating scene audio: %s", getTraceback( err ),
            )
            return 0

    def selectLevels( self, matrix ):
        """Let every LOD node choose its level for where the viewer now is.

        Before the render set is gathered, not during it: a level that changes
        replaces a subtree, and the flattened scenegraph the pass renders from
        has to be told about the new one before it walks it.

        Only from the camera. A shadow pass draws the same scene from a light,
        and choosing detail by how far a *lamp* is from a figure would swap
        levels as the sun moved.
        """
        paths = self.paths.get( lod.LOD, () )
        if not paths:
            return
        for path in list( paths ):
            node = path[-1]
            try:
                distance = lod.distance_to_viewer(
                    node, dot( path.transformMatrix(), matrix ) )
            except Exception as err:      # pragma: no cover - malformed content
                log.warning( 'could not place an LOD node: %s', err )
                continue
            node.select( distance )

    def renderSet( self, matrix ):
        """The scene's shapes, culled to the frustum and ordered for drawing.

        Every path is asked for its world matrix, because a matrix is what the
        scenegraph may have changed since the last frame and the path is what
        knows.  Everything after that is done to the whole scene at once: the
        camera transform is one matrix product over a stacked array rather than
        one per shape, and the frustum test is one product against the clipping
        planes rather than eight points and six planes per shape.

        Culling *before* the sort key rather than after is what makes the rest
        of the frame proportional to what is on screen: a key is only worked out
        for a shape that survives, and in a level most shapes do not.  The keys
        of shapes nobody can see were never read.
        """
        paths = self.paths.get( nodetypes.Rendering, ())
        if not paths:
            return []
        volumes, points, bounded, drawing = self._boundingArrays( paths )
        matrices = self._worldMatrices( paths )
        keep = self._frustumSurvivors( matrices, points, bounded, drawing )
        if not len(keep):
            return []
        kept = matrices[keep]
        # One product for the whole surviving set. `matrix` is the camera's, so
        # this is the only place the frame's viewpoint enters the gather.
        modelviews = kept @ asarray( matrix, 'f' )
        toRender = []
        seen = self.visiblePlacements = {}
        for at, index in enumerate( keep ):
            path = paths[index]
            tmatrix = matrices[index]
            node = path[-1]
            # A declared set is one object to the test above, so its whole box
            # survived if any of it did. Ask it which of its copies this frustum
            # actually keeps, and drop the record if the answer is none.
            within = getattr( node, 'visiblePlacements', None )
            if within is not None:
                found = within( self.frustum, tmatrix, mode=self )
                if found is not None:
                    if not len(found):
                        continue
                    seen[id(path)] = found
            toRender.append( (
                node.sortKey( self, tmatrix ),
                modelviews[at], tmatrix, volumes[index], path,
            ) )
        toRender.sort( key = lambda x: x[0])
        return toRender

    def _boundingArrays( self, paths ):
        """Each path's bounding volume and its corner points, stacked.

        Asked of every node every frame rather than remembered: a volume is not
        a property of the shape alone. An
        :class:`~OpenGLContext.scenegraph.instancedshape.InstancedShape` bounds
        all of its placements, so its extent changes whenever they do, and a set
        of corners kept from an earlier frame would cull this frame's copies
        against where the last frame's were. The node's own volume cache is
        where that question is already answered correctly; this only stacks the
        answers so the test can be done to the whole scene at once.

        ``bounded`` marks the paths whose volume offers the eight corners the
        test needs. A volume that offers none is *unbounded* -- of unknown
        extent -- and is never culled: not knowing where a thing is has to mean
        drawing it.

        ``drawing`` is the separate question of whether the node has anything to
        put on screen at all, which it answers itself through
        :meth:`~OpenGLContext.scenegraph.shape.Shape.drawsNothing`. A node that
        says no is left out: it is not culled for being outside the frustum, it
        simply is not there this frame.
        """
        count = len(paths)
        points = self._pointsBuffer
        if points is None or len(points) != count:
            points = self._pointsBuffer = zeros( (count, 8, 4), 'f' )
        volumes, bounded, drawing = [], [], []
        for index, path in enumerate( paths ):
            node = path[-1]
            nothing = getattr( node, 'drawsNothing', None )
            if nothing is not None and nothing():
                volumes.append( None )
                bounded.append( False )
                drawing.append( False )
                continue
            drawing.append( True )
            volume = node.boundingVolume( self ) if hasattr(
                node, 'boundingVolume' ) else None
            volumes.append( volume )
            corners = None
            if volume is not None:
                try:
                    corners = asarray( volume.getPoints(), 'f' )
                except (AttributeError, boundingvolume.UnboundedObject):
                    corners = None
            if corners is not None and corners.shape == (8, 4):
                points[index] = corners
                bounded.append( True )
            else:
                bounded.append( False )
        return (volumes, points, array( bounded, dtype=bool ),
                array( drawing, dtype=bool ))

    def _worldMatrices( self, paths ):
        """Every path's world matrix, stacked into one array.

        The per-path call stands because the transform cache behind it is what
        knows whether anything moved; what is saved is everything downstream of
        it being done one shape at a time.
        """
        matrices = self._matrixBuffer
        if matrices is None or len(matrices) != len(paths):
            matrices = self._matrixBuffer = zeros( (len(paths), 4, 4), 'f' )
        for index, path in enumerate( paths ):
            matrices[index] = path.transformMatrix()
        return matrices

    def _frustumSurvivors( self, matrices, points, bounded, drawing ):
        """Indices of the paths the frustum does not reject.

        A shape is rejected when some clipping plane has all eight of its
        corners behind it, which is the same decision
        :meth:`OpenGLContext.scenegraph.boundingvolume.BoundingBox.visible`
        makes one shape at a time.
        """
        planes = asarray( self.frustum.planes, 'f' )
        if not len(planes):
            return flatnonzero( drawing )
        # Corners into world space: (N,8,4) against each path's own (4,4).
        world = points @ matrices
        world[:, :, 3] = 1.0
        distances = world @ planes.T
        outside = (distances < 0).all( axis=1 ).any( axis=1 ) & bounded
        return flatnonzero( drawing & ~outside )

    def greatestDepth( self, toRender ):
        # experimental: adjust our frustum to smaller depth based on
        # the projected z-depth of bbox points...
        # **The depths are not read, and have not been.** A depth measured this
        # way is an eye-space z in front of the camera, so it is never positive;
        # it starts at zero and only ever decreases. The floor below -- which is
        # there so the hundred-unit background still shows -- is therefore always
        # the larger of the two, and the answer is the same constant whatever
        # the scene contains. Projecting every corner of every shape to reach it
        # cost a measurable slice of each frame.
        #
        # What the scan still decides is whether every record *has* an extent:
        # one of unknown extent could reach any distance, and a zero is how this
        # tells the caller not to narrow the projection at all. So that is what
        # is asked, and nothing else.
        #
        # Restoring the depths means fixing the floor -- `max` against a
        # positive number can only ever choose the positive number -- and that
        # changes the projection every scene is drawn with, so it is a
        # deliberate change rather than a tidy-up.
        for (key,mv,tm,bv,path) in toRender:
            try:
                bv.getPoints()
            except (AttributeError,boundingvolume.UnboundedObject) as err:
                return 0
        # 101 is to allow the 100 unit background to show... sigh
        return -(101*1.01)

    _render_mode_logged = False

    def Render( self, context, mode ):
        """Render the geometry attached to this flat-renderer's scenegraph"""
        # Log render mode once on first frame
        if not self._render_mode_logged:
            self._render_mode_logged = True
            profile = getattr(context.contextDefinition, 'profile', 'unknown')
            render_mode = 'SHADER' if self.use_shaders else 'LEGACY'
            mrt_mode = 'MRT' if (self.use_shaders and self.use_mrt_selection) else 'LEGACY'
            log.info(f"Render mode: {render_mode}, Profile: {profile}, Selection: {mrt_mode}")
            # Report the actual GL driver. A `llvmpipe`/`softpipe`/`swrast`
            # renderer here means GL fell back to CPU software rendering (e.g. a
            # misconfigured container) -- warn loudly, since it silently caps
            # performance ~100x below the real GPU.
            try:
                from OpenGL.GL import (
                    glGetString, GL_VENDOR, GL_RENDERER, GL_VERSION,
                )
                vendor = (glGetString(GL_VENDOR) or b'?').decode('latin-1')
                renderer = (glGetString(GL_RENDERER) or b'?').decode('latin-1')
                version = (glGetString(GL_VERSION) or b'?').decode('latin-1')
                self._gl_renderer = renderer
                log.info("GL vendor=%s renderer=%s version=%s", vendor, renderer, version)
                if any(s in renderer.lower() for s in ('llvmpipe', 'softpipe', 'swrast', 'software')):
                    log.warning(
                        "GL is running on a SOFTWARE rasteriser (%s) -- the GPU "
                        "is not being used; rendering will be very slow.", renderer)
            except Exception as err:
                log.debug("Could not query GL driver strings: %s", err)

            # Colour is written already sRGB-encoded: the PBR/VRML97 shaders end
            # with an explicit linearToSRGB() and the legacy path outputs
            # display-referred colour directly, so the framebuffer must NOT
            # re-encode. GL_FRAMEBUFFER_SRGB defaults off, but a backend that
            # requests an sRGB-capable default framebuffer can hand it to us
            # enabled -- which would double-encode and wash the frame out. We
            # never enable it ourselves (grep confirms), so disabling it once
            # here, on the first frame with the context current, is enough; any
            # future pass that turns it on owns restoring it.
            try:
                glDisable(GL_FRAMEBUFFER_SRGB)
            except Exception as err:
                log.debug("GL_FRAMEBUFFER_SRGB not available to disable: %s", err)

        # Reset per-frame caches
        self.stats.reset()
        context.renderStats = self.stats
        self._has_mousemove_handlers = None
        # Deferred runtime-transparent shapes are collected fresh each frame
        #; drained by renderTransparent.
        self._deferredTransparent = []

        # clear the projection matrix set up by legacy sg
        matrix = self.getModelView()
        self.matrix = matrix

        # Before the scene is walked, not after: sorting a shape asks its
        # appearance for a texture, which compiles one, and how a texture is
        # compiled depends on which pipeline will sample it.
        if self.use_shaders:
            self.shader_program = self.getShaderProgram()
            self.shader_program.compile()
            # Reset the per-frame program-bind cache so a skip can
            # never be based on a program another pass/frame left bound.
            self.shader_program.begin_frame()
            self.shader_mode = True
        else:
            self.shader_mode = False
            self.shader_program = None

        self.selectLevels( matrix )
        toRender = self.renderSet( matrix )
        self.stats.shapes = len(toRender)
        maxDepth = self.maxDepth = self.greatestDepth( toRender )
        vp = context.getViewPlatform()
        if maxDepth:
            self.projection = vp.viewMatrix(maxDepth)

        # Get pick events
        events = context.getPickEvents()
        # pickEnabled=False suppresses the whole selection subsystem; events are
        # already empty (gated in addPickEvent), so only debugSelection remains.
        debugSelection = (mode.context.contextDefinition.debugSelection
                          and mode.context.contextDefinition.pickEnabled)

        # Optimize events: filter mouse-move if no handlers, de-duplicate by pixel
        if events:
            events = self._optimizePickEvents(context, events)

        # Keep the id/depth readback warm only while picking is active.
        if events:
            self._pick_warm_frames = self._PICK_WARM_RESET

        # Log pick event count for debugging
        if events:
            log.debug("Render: processing %d pick events", len(events))

        # MRT selection path: resolve picks from the object-id buffer.
        use_mrt = self.use_shaders and self.use_mrt_selection and not debugSelection
        self.use_async_pick = (use_mrt and
                               getattr(context.contextDefinition, 'pickAsync', True))
        # Deferred events submitted on earlier frames are dispatched here as soon
        # as their fence signals; this frame's events are submitted after the
        # selection buffer is rendered (see below), so they resolve next frame.
        if self.use_async_pick:
            self.drainAsyncPicks(mode)
        elif use_mrt and events:
            # Synchronous readback of the PREVIOUS frame's buffer (one-frame
            # latency, but a GPU stall per pick).
            self.processPickEventsFromBuffer(mode, events)
            context.pickEvents.clear()
        elif events or debugSelection:
            # Legacy selection path
            if self.use_shaders:
                self.shaderSelectRenderOptimized(mode, toRender, events)
            else:
                self.selectRender( mode, toRender, events )
            context.pickEvents.clear()

        # Load the root
        if not debugSelection:
            self.matrix = matrix
            self.visible = True
            self.transparent = False
            self.lighting = True
            self.textured = True

            # Set up generic "geometric" rendering parameters
            glFrontFace( GL_CCW )
            glEnable(GL_DEPTH_TEST)
            glDepthFunc( GL_LESS )
            glEnable(GL_CULL_FACE)
            glCullFace(GL_BACK)

            if self.use_shaders:
                # Render shadow maps before binding the MRT selection FBO; the
                # shadow pass binds/unbinds its own depth FBOs and restores state.
                if self.use_shadows:
                    self.shader_program.use(lit=True)
                    self.renderShadowMaps(toRender)

                # Render into the MRT selection FBO only while picking is active.
                # Otherwise render straight to the screen: no second render
                # target, no full-buffer readback (a GPU stall), and no blit --
                # all of which are wasted when nothing is querying object IDs.
                selection_buffer = None
                id_map = None
                vp_size = context.getViewPort()

                if use_mrt and self._pick_warm_frames > 0:
                    selection_buffer = self._getSelectionBuffer()
                    if selection_buffer.ensure_size(int(vp_size[0]), int(vp_size[1])):
                        id_map = self._selectionIdMap()
                        selection_buffer.bind()
                        selection_buffer.clear()
                    else:
                        selection_buffer = None

                # Shader-based rendering path (core-profile compatible)
                self.shaderBackgroundRender(vp, matrix)
                self.setupShaderLights(matrix)
                if self.use_shadows:
                    self.bindShadowUniforms()
                self.iblSetup(matrix)
                self.shader_program.set_default_material()
                # glTF lighting is IBL + punctual only -- a flat white fill is
                # non-physical and washes out self-lit scenes (DirectionalLight,
                # PointLightIntensityTest read pale grey instead of dark + crisp
                # lights). A glTF viewer sets context.gltf_scene_ambient low/zero;
                # legacy VRML scenes keep the 0.2 fill that stands in for no lights.
                amb = getattr(getattr(self, 'context', None),
                              'gltf_scene_ambient', None)
                if amb is None:
                    amb = (0.2, 0.2, 0.2)
                elif not isinstance(amb, (tuple, list)):
                    amb = (float(amb),) * 3
                self.shader_program.set_scene_ambient(tuple(amb))
                # Transmissive (glass) shapes are opaque-alpha but must draw after
                # the opaque scene so they can sample it as a backdrop; split them
                # out of the opaque pass unless transmission is disabled.
                transmissive = (self.transmissiveRecords(toRender)
                                if self.transmissionMode() != 'off' else set())
                self.shaderRenderOpaque(toRender, id_map, skip=transmissive)
                self.shaderRenderTransmissive(toRender, transmissive, id_map)
                self.shaderRenderTransparent(toRender, id_map)

                # Restore winding/cull GL defaults once, after the geometry loop,
                # so a PBR mesh's CW winding or disabled culling never leaks past
                # this frame. No-op for pure VRML97 scenes. Guarded
                # lazy import keeps the generic pass free of a hard PBR dependency.
                try:
                    from OpenGLContext.scenegraph.pbrmesh import PBRMesh
                    PBRMesh.reset_draw_state(self)
                    # Delete VAOs whose meshes were GC'd since last frame, now
                    # that this context is current.
                    PBRMesh.flush_pending_deletes(self)
                except Exception:
                    pass

                # Finalize MRT selection buffer: keep the id->path map for next
                # frame's per-pixel pick lookups (read on demand from the FBO --
                # no full-framebuffer readback), then present.
                if selection_buffer is not None and id_map is not None:
                    self._pick_warm_frames -= 1
                    selection_buffer.set_id_map(id_map)
                    selection_buffer.blit_to_screen(int(vp_size[0]), int(vp_size[1]))

                # Async pick: submit this frame's samples now that the id buffer
                # holds this frame's render; they resolve on a later frame with no
                # GPU stall. Always clear the queue so events aren't resubmitted.
                if self.use_async_pick and events:
                    if selection_buffer is not None and id_map is not None:
                        self.submitAsyncPicks(mode, events, id_map)
                    context.pickEvents.clear()

            else:
                # Legacy fixed-function rendering path
                self.legacyBackgroundRender( vp,matrix )
                self.legacyLightRender( matrix )
                self.renderOpaque( toRender )
                self.renderTransparent( toRender )

            # The HUD, the developer overlay and any screen that is open, drawn
            # over the finished frame rather than into the MRT buffer.  Outside
            # the branch above because it belongs to the *frame* and not to
            # either way of filling one: the overlay renderer builds its own
            # program and does not care which path drew the world, and a
            # compatibility-profile context whose menu could not be seen would
            # be a program nobody can use.  See OpenGLContext.ui.screen.
            overlay = getattr(context, 'renderShaderOverlay', None)
            if overlay is not None:
                overlay(self)

        presentFrame( context )
        self.matrix = matrix
        self.shader_mode = False  # Reset after render

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
    
    def renderGeometry( self, mvmatrix ):
        """Draw everything visible from ``mvmatrix``, and nothing else

        A whole frame is more than its geometry -- a background, lights, the
        selection buffer, the overlay.  A caller that wants only the geometry,
        drawn from a matrix of its own choosing, asks for it here: rendering the
        scene from a light's point of view to fill a depth map is what this is
        for.  See docs/tutorials/shadow_1.html.
        """
        toRender = self.renderSet( mvmatrix )
        self.renderOpaque( toRender )
        self.renderTransparent( toRender )

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
                except Exception as err:
                    self.renderFailed( 'opaque', path[-1], err )
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
                        self.renderFailed( 'transparent', path[-1], err )
        finally:
            self.transparent = False
            if setup:
                glDisable( GL_BLEND )
                glDepthMask( 1 )
                glDepthFunc( GL_LEQUAL )
                glEnable( GL_DEPTH_TEST )
        # Draw shapes deferred from the opaque pass.
        self._renderDeferredTransparent()
    def addTransparent( self, other ):
        """Defer a shape found transparent during the opaque pass.

        `Shape.Render` calls this and returns without drawing when a shape
        statically classed opaque turns out transparent at render time. Record it
        (with the current modelview matrix and path) so `renderTransparent` can
        replay it, instead of silently dropping it for the frame.
        """
        if getattr( self, '_deferredTransparent', None ) is None:
            self._deferredTransparent = []
        self._deferredTransparent.append(
            ( self.matrix, self.renderPath, other ) )

    def _renderDeferredTransparent( self ):
        """Draw shapes deferred via addTransparent, then clear the queue.

        Self-contained blend setup/teardown so it renders correctly whether or
        not the main transparent loop already ran.
        """
        deferred = getattr( self, '_deferredTransparent', None )
        if not deferred:
            return
        self.transparent = True
        glEnable( GL_BLEND )
        glBlendFunc( GL_ONE_MINUS_SRC_ALPHA, GL_SRC_ALPHA )
        glDepthMask( 0 )
        glDepthFunc( GL_LEQUAL )
        try:
            for matrix, path, shape in deferred:
                self.matrix = matrix
                self.renderPath = path
                glLoadMatrixf( matrix )
                try:
                    shape.RenderTransparent( mode = self )
                except Exception as err:
                    self.renderFailed( 'deferred transparent', shape, err )
        finally:
            self._deferredTransparent = []
            glDisable( GL_BLEND )
            glDepthMask( 1 )
            glDepthFunc( GL_LEQUAL )
            glEnable( GL_DEPTH_TEST )
            self.transparent = False

    def selectRender( self, mode, toRender, events ):
        """Legacy colour-buffer pick fallback for the core/shader FlatPass.

        Packs the id shifted 12 bits into RGBA (no fixed-function lighting).
        Shared body in :func:`_color_select_render`.
        """
        _color_select_render(
            self, mode, toRender, events,
            id_shift=12, read_format=GL_RGBA,
            setup_fixed_function=False, require_pick_enabled=False)

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

        # Anything the application pins to the camera -- a first-person weapon,
        # a held tool -- is placed here, in the one window where the view
        # platform is settled and no geometry has been gathered yet. Written
        # any earlier (an idle callback, an event handler) it is posed from the
        # *previous* frame's camera, and the pinned object visibly lags and
        # then catches up as the player moves.
        attach = getattr( context, 'placeViewAttachments', None )
        if attach is not None:
            attach( self )

        # Here rather than in Render(): every concrete pass overrides Render()
        # and one of them would eventually forget, leaving a default install
        # silent while a sound played directly through the engine still worked.
        self.renderAudio( context )

        if self._begin_bloom():
            try:
                self.Render( context, self )
            finally:
                self._end_bloom()
        else:
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
