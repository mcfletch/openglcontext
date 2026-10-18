"""Gradient-sphere background node

An X3D ``Background`` or ``TextureBackground`` with a ``transparency`` draws
its sky and ground over a clear of transparent black, at ``1 - transparency``
opacity, and not at all at 1; the image sides keep their own alpha
(:func:`sky_alpha`). The colour buffer's alpha is left at that opacity, so a
window composited with its alpha shows what is behind it.
"""
import contextlib
import numpy as np
from collections.abc import Iterator
from typing import Any, Optional

from OpenGLContext.arrays import *
from OpenGL.GL import *
# PyOpenGL generates the type-inferring entry points at import time, so
# they need naming to be seen.
from OpenGL.GL import glColor, glColorPointerf, glVertexPointerf
from OpenGL.GL import shaders as GL_shaders
from OpenGL.arrays import vbo

from vrml import cache
from vrml import field, protofunctions, node
from vrml.vrml97 import nodetypes
from vrml.x3d import binding
from OpenGLContext import contextresources, displaylist
from OpenGLContext.scenegraph import bindable
from OpenGLContext.passes import glstate, tonemapping
from OpenGLContext.passes.shadersource import preprocess_shader
import bisect


#: The gradient program, per GL context that compiled one.  A program is a name
#: its own context issues, so a second window handed the first one's program
#: draws through a name its driver never gave out.
_shaders: dict[Optional[contextresources.ContextKey], Any] = {}
#: The vertex array every gradient sphere is drawn through, per GL context;
#: each draw points it at that sphere's buffers.
_vertex_arrays: dict[Optional[contextresources.ContextKey], int] = {}


@contextresources.on_context_lost
def _drop_context_resources() -> None:
    """Forget the program and vertex array of the context now being destroyed.

    Keying alone leaves them reachable by the next context the driver gives the
    same address to; letting go as the context dies is what makes the key
    trustworthy.  The sphere's own vertex buffers live in the render pass's
    cache, which lets go of its own.
    """
    key = contextresources.context_key()
    _shaders.pop(key, None)
    _vertex_arrays.pop(key, None)


def _vertex_array() -> int:
    """The gradient spheres' vertex array, for the current context"""
    key = contextresources.context_key()
    found = _vertex_arrays.get(key)
    if found is None:
        found = _vertex_arrays[key] = int(glGenVertexArrays(1))
    return found

def sky_alpha(node: Any) -> float:
    """How opaque `node`'s sky and ground are: ``1 - transparency``, in [0, 1]"""
    transparency = float(getattr(node, 'transparency', 0.0) or 0.0)
    # numpy's clip: the star import above names numpy's min and max
    return 1.0 - float(np.clip(transparency, 0.0, 1.0))


def clear_for(alpha: float) -> None:
    """Clear colour, depth and stencil; to transparent black under a sky less than opaque"""
    bits = GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT
    if alpha >= 1.0:
        glClear(bits)
        return
    previous = [float(value) for value in glGetFloatv(GL_COLOR_CLEAR_VALUE)]
    glClearColor(0.0, 0.0, 0.0, 0.0)
    try:
        glClear(bits)
    finally:
        glClearColor(*previous)


@contextlib.contextmanager
def blended(alpha: float) -> Iterator[None]:
    """Draw the block at `alpha` over the colour buffer, as X_ITE composites a
    transparent background; nothing changes for an opaque one"""
    if alpha >= 1.0:
        yield
        return
    blending = bool(glIsEnabled(GL_BLEND))
    functions = [int(glGetIntegerv(name)) for name in (
        GL_BLEND_SRC_RGB, GL_BLEND_DST_RGB, GL_BLEND_SRC_ALPHA, GL_BLEND_DST_ALPHA)]
    colour = [float(value) for value in glGetFloatv(GL_BLEND_COLOR)]
    glEnable(GL_BLEND)
    glBlendColor(0.0, 0.0, 0.0, alpha)
    glBlendFuncSeparate(GL_CONSTANT_ALPHA, GL_ONE_MINUS_CONSTANT_ALPHA,
                        GL_CONSTANT_ALPHA, GL_ONE_MINUS_CONSTANT_ALPHA)
    try:
        yield
    finally:
        glBlendFuncSeparate(*functions)
        glBlendColor(*colour)
        if not blending:
            glDisable(GL_BLEND)


MINANGLE = pi*1.0/4
MAXANGLE = pi*3.0/4
SEGMENTS = 32

#: Where the fixed-function display lists are kept in the pass's cache.  A key
#: of this class's own, because `Background` mixes it with `_CubeBackground`
#: and both cache against the same node: sharing the default key would have
#: each of them reading what the other compiled.  The shader path keeps its
#: buffers under ``'shader_bg'`` for the same reason.
LEGACY_CACHE_KEY = 'sphere_bg_dl'

def drawn_stops(angles: Any, colors: Any) -> tuple[Any, Any]:
    """A Background's sky or ground angles and the colours drawn between them

    X3D gives one colour more than angles. Extra colours are left out, and
    with no more colours than angles that part of the background is not drawn
    at all, as X_ITE draws it; both come back empty then.
    """
    angles = asarray(angles, 'f').reshape(-1)
    colors = asarray(colors, 'f').reshape(-1, 3)
    if len(colors) <= len(angles):
        return angles[:0], colors[:0]
    return angles, colors[:len(angles) + 1]


class _SphereBackground( object ):
    groundAngle = field.newField( 'groundAngle', 'MFFloat', 1, [])
    groundColor = field.newField( 'groundColor', 'MFColor', 1, [])
    skyColor = field.newField( 'skyColor', 'MFColor', 1, [[0.0, 0.0, 0.0]])
    skyAngle = field.newField( 'skyAngle', 'MFFloat', 1, [])
    bound = bindable.bound_field()

    def compile(self, mode: Any) -> Any:
        """Build the cached display list for this background object

        `mode` is the rendering pass, and is required: the list is built
        against its matrix.  `Background` mixes this class with
        `_CubeBackground`, so the two have to agree on what `compile` takes.

        Note: we store 2 display lists in the cache, but only return
        one from the compile method.  The second list is the final
        rendering list, while the first is just the low-level rendering
        code.
        """
        colorSet = self.colorSet()
        if len(colorSet):
            vertices, colors = self.buildSphere( colorSet )
            glstate.multiply_matrix( mode.matrix )
            first = displaylist.DisplayList()
            first.start()
            try:
                glVertexPointerf(vertices)
                glColorPointerf ( colors )
                glEnableClientState( GL_VERTEX_ARRAY )
                glEnableClientState( GL_COLOR_ARRAY )
                glDrawArrays( GL_TRIANGLE_STRIP, 0, len(vertices))
            finally:
                first.end()
            second = displaylist.DisplayList()
            second.start()
            try:
                glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)
                # The sphere has a radius of one about the eye, and a camera's
                # near plane may be further off than that; clamping depth
                # rather than clipping at the planes draws it whatever they are.
                glEnable( GL_DEPTH_CLAMP )
                glDisable( GL_DEPTH_TEST ) # we don't want to do anything with the depth buffer...
                glDisable( GL_LIGHTING )
                glEnable( GL_COLOR_MATERIAL )
                glDisable( GL_CULL_FACE )
                
                for _index in range( int(SEGMENTS) ):
                    first()
                    glRotated( 360.0/SEGMENTS, 0,1,0)
                glDisableClientState( GL_VERTEX_ARRAY )
                glDisableClientState( GL_COLOR_ARRAY )
                # now, completely wipe out the depth buffer, so this appears as a "background"... no idea how expensive this is
                glClear( GL_DEPTH_BUFFER_BIT )

                glDisable( GL_DEPTH_CLAMP )
                glEnable( GL_DEPTH_TEST )
                glEnable( GL_LIGHTING )
                glColor( 0.0,0.0,0.0)
                glDisable( GL_COLOR_MATERIAL )
                glEnable( GL_CULL_FACE )
                glFrontFace( GL_CCW )
                
                holder = mode.cache.holder(self, (first, second), LEGACY_CACHE_KEY)
                for field in protofunctions.getFields( self ):
                    # change to any field but bound requires a recompile
                    if field.name != 'bound':
                        holder.depend( self, field )
                return second
            finally:
                second.end()
        holder = mode.cache.holder(self, (None, ()), LEGACY_CACHE_KEY)
        return None
        
    def buildSphere( self, colorSet: Any ) -> tuple[Any, Any]:
        """``(vertices, colours)`` for one segment of the angle:colour set

        A vertex pair per stop between the poles, so a set of only the two
        poles describes no surface and nothing rasterises.
        """
        n = len(colorSet)

        if len(colorSet) and colorSet[0][0] == 0:
            l = (n-2)*2 + 2
            doStart = 1
        else:
            l = (n-1)*2 + 1
            doStart = 0
        
        vertices = zeros(
            (
                l, # length...
                3, # components
            ),
            'f',
        )
        # calculate the coordinates...
        fraction = cos( pi/SEGMENTS)
        # z = sin(angle) * fraction
        vertices[doStart:-1,2] = repeat(sin(colorSet[doStart:-1,0])*fraction,2, 0)
        # y = cos(angle) * sky
        vertices[doStart:-1,1] = repeat(cos(colorSet[doStart:-1,0]),2, 0)
        # except at the poles...
        if doStart:
            vertices[0,1] = 1
        vertices[-1,1] = -1
        # x = sin(pi/(<segments))
        vertices[doStart+1:-1:2,0] = -sin(pi/(SEGMENTS*.9)) * vertices[doStart+1:-1:2,2]
        vertices[doStart:-1:2,0] = sin(pi/(SEGMENTS*.9)) * vertices[doStart:-1:2,2]
        
        
        colors = zeros( shape(vertices), 'f')
        # now put in the colors
        colors[doStart:-1] = repeat(colorSet[doStart:-1,1:],2, 0)
        if doStart:
            colors[0] = colorSet[0,1:]
        colors[-1] = colorSet[-1,1:]
        return vertices.astype('f'), colors.astype('f')
        
    def Render( self, mode: Any, clear: int = 1 ) -> int:
        """Render the Background

        mode -- the RenderingPass object representing
            the current rendering pass
        clear -- whether or not to do a background
            clear before rendering

        Note:
            the SphereBackground node only renders if the
            mode's passCount == 0
        """
        if mode.passCount == 0:
            if binding.bound(self) is self:
                dl = mode.cache.getData(self, LEGACY_CACHE_KEY)
                if dl is None:
                    # This class's own compile, not whichever the MRO offers:
                    # `Background` mixes it with `_CubeBackground`, whose
                    # compile builds the image cube and comes first there.
                    dl = _SphereBackground.compile( self, mode=mode )
                else:
                    # see note on compile's return value/store value
                    dl = dl[1]
                alpha = sky_alpha(self)
                if clear:
                    clear_for(alpha)
                if dl:
                    if callable( dl ) and alpha > 0.0:
                        with blended(alpha):
                            dl()
                    return 1
        return 0


    def colorSet( self ) -> Any:
        """Compound the sky and ground angle:color arrays into a single angle:color array-set"""
        skyAngle, skyColor = drawn_stops(self.skyAngle, self.skyColor)
        groundAngle, groundColor = drawn_stops(self.groundAngle, self.groundColor)
        if len(groundColor) and not len(groundAngle):
            # One ground colour and no angle is that colour from the nadir to
            # the horizon, as one sky colour is the sky all over
            groundAngle = array([pi / 2.0], 'f')
            groundColor = array([groundColor[0], groundColor[0]], 'f')
        # okay, ground angles are pi-groundA
        if (
            not len(skyAngle) and 
            not len(groundAngle) and 
            not len(groundColor)
        ):
            # Nothing but sky colours. One of them, with no angle to grade it
            # against, is VRML97's way of saying the sky is that colour all
            # over, so it spans the sphere; with no colours at all there is
            # nothing to draw.
            if len(skyColor):
                # Three stops rather than two: buildSphere lays a vertex pair
                # per stop between the poles, so a set of only the two poles
                # describes no surface and nothing rasterises.
                uniform = zeros((3, 4), 'f')
                uniform[:, 1:] = skyColor[0]
                uniform[1, 0] = pi / 2.0
                uniform[2, 0] = pi
                return uniform
            return []
        # now need to trim skyA and skyC to lowest groundA
        # and (likely) generate a new A and C for the sky's last value...
        if len(skyAngle):
            maxSky = max( skyAngle)
        else:
            maxSky = 0
        if len(skyAngle):
            if maxSky < pi:
                skys = zeros( (len(skyColor)+1,4), 'f')
                skys[1:-1,0] = skyAngle
                skys[:-1,1:] = skyColor
                skys[-1] = skys[-2]
                skys[-1,0] = pi
            else:
                skys = zeros( (len(skyColor),4), 'f')
                skys[1:,0] = skyAngle
                skys[:,1:] = skyColor
                
                if maxSky > pi:
                    # Stops past the south pole are past the far side of the
                    # sphere; cut at pi, with the colour there interpolated
                    # between the stops either side of it.
                    t = len(compress( less(skys[:,0],pi), skys, 0 ))-1
                    if t+1 < len(skys):
                        skys[t+1] = _linInterp( skys[t],skys[t+1], pi)
                    skys = skys[:t+2]

            # just to be sure, we sort by angle...
            skys = setSort( skys)
        elif len(skyColor):
            # VRML97 gives skyAngle one fewer value than skyColor, so a single
            # colour has no angle at all and is the sky all over -- down to
            # wherever the ground starts.  Two stops rather than one, because
            # both the ground capping below and pushOut work between a pair.
            skys = zeros( (2,4), 'f')
            skys[:,1:] = skyColor[0]
            skys[1,0] = pi
        else:
            skys = zeros((0,4),'f')
        # now need to cap skys to ground's minimum value...
        if len(groundAngle):
            # no capping if no grounds, so require angles
            groundA = pi - asarray(groundAngle, 'f')
            capAngle = min( groundA )
            if len(skys):
                t = len(compress( less(skys[:,0],capAngle), skys, 0 ))-1
                # t+1 is now to be the cut-off, and should be linear
                # interpolation of t and t+1 colour
                if t+1 < len(skys):
                    skys[t+1] = _linInterp( skys[t],skys[t+1], capAngle)
                skys = skys[:t+2]
                skys = self.pushOut(skys,MINANGLE,MINANGLE+(pi/4) )
                if capAngle > MAXANGLE:
                    skys = self.pushOut(skys, MAXANGLE-(pi/4), MAXANGLE )

            grounds = zeros( (len(groundColor),4), 'f')
            grounds[0,0] = pi
            grounds[1:,0] = groundA
            grounds[:,1:] = groundColor
            grounds = setSort(grounds)
            if capAngle < MAXANGLE:
                grounds = self.pushOut(grounds,MAXANGLE-(pi/4), MAXANGLE )
            skys = concatenate((skys,grounds))
        else:
            skys = self.pushOut(skys,MAXANGLE-(pi/4), MAXANGLE )
            skys = self.pushOut(skys,MINANGLE,MINANGLE+(pi/4) )
        return skys
    def pushOut( self, colorSet: Any, start: float, stop: float ) -> Any:
        """Push the colorSet values out to a distance they can be seen

        Basically, if there is no value between pi/4 and 3pi/4, insert
        values at those points with the proper linear interpolation
        for colour.
        """
        a = colorSet[:,0]
        startI, stopI = bisect.bisect( a,start),bisect.bisect( a,stop)
        if startI == stopI:
            # need to insert
            colorSet = resize(colorSet,(int(len(colorSet))+1,4))
            colorSet[-1] = _linInterp( colorSet[startI-1],colorSet[startI], ((stop-start)/2)+start )
            colorSet = setSort( colorSet)
        return colorSet

    # Shader-based rendering support
    @staticmethod
    def _compile_background_shader() -> tuple[Any, dict[str, int]]:
        """The gradient program and its locations, for the current context."""
        key = contextresources.context_key()
        compiled: tuple[Any, dict[str, int]] | None = _shaders.get(key)
        if compiled is not None:
            return compiled

        vert_source = preprocess_shader('vrml97_background.vert')
        frag_source = preprocess_shader('vrml97_background.frag')

        vertex_shader = GL_shaders.compileShader(vert_source, GL_VERTEX_SHADER)
        fragment_shader = GL_shaders.compileShader(frag_source, GL_FRAGMENT_SHADER)
        program = GL_shaders.compileProgram(vertex_shader, fragment_shader)

        compiled = (program, {
            'aPosition': glGetAttribLocation(program, 'aPosition'),
            'aColor': glGetAttribLocation(program, 'aColor'),
            'modelViewMatrix': glGetUniformLocation(program, 'modelViewMatrix'),
            'projectionMatrix': glGetUniformLocation(program, 'projectionMatrix'),
        })
        _shaders[key] = compiled
        return compiled

    def compileShader(self, mode: Any = None) -> tuple[Any, Any, int] | None:
        """Compile shader-based rendering data for this background.

        Returns (vertices_vbo, colors_vbo, vertex_count, rotation_matrices)
        or None if no colorSet.
        """
        colorSet = self.colorSet()
        if not len(colorSet):
            return None

        vertices, colors = self.buildSphere(colorSet)

        # Build the full rotated sphere geometry
        # Instead of rendering N segments with rotation, we pre-compute all vertices
        all_vertices = []
        all_colors = []
        rotation_angle = 2 * pi / SEGMENTS

        for i in range(int(SEGMENTS)):
            angle = i * rotation_angle
            cos_a = cos(angle)
            sin_a = sin(angle)
            # Rotate vertices around Y axis
            rotated = vertices.copy()
            rotated[:, 0] = vertices[:, 0] * cos_a - vertices[:, 2] * sin_a
            rotated[:, 2] = vertices[:, 0] * sin_a + vertices[:, 2] * cos_a
            all_vertices.append(rotated)
            all_colors.append(colors)

        every_vertex = concatenate(all_vertices, axis=0)
        every_colour = concatenate(all_colors, axis=0)

        vertices_vbo = vbo.VBO(every_vertex.astype('f'))
        colors_vbo = vbo.VBO(every_colour.astype('f'))

        return (vertices_vbo, colors_vbo, len(every_vertex))

    def RenderShader(self, mode: Any, clear: bool = True) -> int:
        """Render the background using shaders.

        Args:
            mode: RenderingPass object with matrix and projection
            clear: Whether to clear buffers before rendering
        """
        if mode.passCount != 0 or binding.bound(self) is not self:
            return 0

        # Get or compile shader data
        shader_data = mode.cache.getData(self, 'shader_bg')
        if shader_data is None:
            shader_data = self.compileShader(mode=mode)
            if shader_data is not None:
                holder = mode.cache.holder(self, shader_data, 'shader_bg')
                for fld in protofunctions.getFields(self):
                    if fld.name != 'bound':
                        holder.depend(self, fld)

        alpha = sky_alpha(self)
        if clear:
            clear_for(alpha)

        if shader_data is None:
            return 0
        if alpha <= 0.0:
            return 1

        vertices_vbo, colors_vbo, vertex_count = shader_data

        # Get shader program
        program, locations = self._compile_background_shader()

        # Save state we'll modify (core profile compatible)
        depth_test_enabled = glIsEnabled(GL_DEPTH_TEST)
        cull_face_enabled = glIsEnabled(GL_CULL_FACE)

        glBindVertexArray(_vertex_array())

        try:
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_CULL_FACE)

            glUseProgram(program)
            tonemapping.upload_display(program, tonemapping.frame_display(mode))

            # Set matrices. The background is infinitely far away, so it must
            # follow the camera's orientation but not its position -- otherwise
            # a camera far from the world origin sees the finite gradient sphere
            # off to one side (black elsewhere). Strip the translation (row 3 in
            # this row-vector convention) so the sphere stays centred on the eye.
            if locations['modelViewMatrix'] != -1:
                mv = mode.matrix.astype('f').copy()
                # Zero the translation regardless of row/column-vector convention.
                mv[3, 0] = mv[3, 1] = mv[3, 2] = 0.0
                mv[0, 3] = mv[1, 3] = mv[2, 3] = 0.0
                glUniformMatrix4fv(
                    locations['modelViewMatrix'], 1, GL_FALSE, mv
                )
            if locations['projectionMatrix'] != -1:
                glUniformMatrix4fv(
                    locations['projectionMatrix'], 1, GL_FALSE,
                    mode.projection.astype('f')
                )

            # Bind vertex data
            vertices_vbo.bind()
            if locations['aPosition'] != -1:
                glEnableVertexAttribArray(locations['aPosition'])
                glVertexAttribPointer(
                    locations['aPosition'], 3, GL_FLOAT, GL_FALSE, 0, None
                )
            vertices_vbo.unbind()

            colors_vbo.bind()
            if locations['aColor'] != -1:
                glEnableVertexAttribArray(locations['aColor'])
                glVertexAttribPointer(
                    locations['aColor'], 3, GL_FLOAT, GL_FALSE, 0, None
                )
            colors_vbo.unbind()

            # Render as triangle strips - each segment's worth
            segment_size = vertex_count // int(SEGMENTS)
            with blended(alpha):
                for i in range(int(SEGMENTS)):
                    glDrawArrays(GL_TRIANGLE_STRIP, i * segment_size, segment_size)

            # Cleanup
            if locations['aPosition'] != -1:
                glDisableVertexAttribArray(locations['aPosition'])
            if locations['aColor'] != -1:
                glDisableVertexAttribArray(locations['aColor'])

            glUseProgram(0)

            # Clear depth buffer so background appears behind everything
            glClear(GL_DEPTH_BUFFER_BIT)

        finally:
            # Restore state
            glBindVertexArray(0)
            if depth_test_enabled:
                glEnable(GL_DEPTH_TEST)
            if cull_face_enabled:
                glEnable(GL_CULL_FACE)

        return 1

class SphereBackground( _SphereBackground, binding.Bindable, nodetypes.Background, nodetypes.Children, node.Node ):
    """Gradient-sphere Background Node

    This Background object (gradient sphere) provides a
    smooth-shaded gradiant which can be useful for certain
    abstract or low-overhead worlds.  A sphere is created
    which fades between a given set of colors at given
    latitudes.

    The SphereBackground node tries to follow the VRML97
    Background node's semantics for the included fields
    as much as possible.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Background
    """
    
                           

def _linInterp( a: Any, b: Any, atAngle: float ) -> Any:
    """The stop between ``a`` and ``b`` at ``atAngle``, or ``b`` where they meet"""
    c,nc = a[1:], b[1:]
    a,na = a[0], b[0]
    if na == a:
        return b
    # get linear interpolation
    r = zeros((4,),'d')
    r[1:] = c+((atAngle-a)/(na-a) * (nc-c))
    r[0] = atAngle
    return r
    
def setSort( set: Any ) -> Any:
    """An angle:colour set in ascending order of angle"""
    return take(set, argsort( set[:,0] ), 0)
                
if __name__ == "__main__":
    print(SphereBackground(
        skyAngle = [],
        skyColor = [],
        groundAngle=[.23],
        groundColor =[
            [1,0,0],
            [.5,0,0],
        ]
    ).colorSet())
    
