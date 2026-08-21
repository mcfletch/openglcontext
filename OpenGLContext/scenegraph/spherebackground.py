"""Gradient-sphere background node"""
import os
from math import *
from OpenGLContext.arrays import *
from OpenGL.GL import *
from OpenGL.GL import shaders as GL_shaders
from OpenGL.arrays import vbo

from vrml import cache
from vrml import field, protofunctions, node
from vrml.vrml97 import nodetypes
from OpenGLContext import displaylist
import bisect

# Shader directory path
SHADER_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'shaders')

MINANGLE = pi*1.0/4
MAXANGLE = pi*3.0/4
SEGMENTS = 32

class _SphereBackground( object ):
    groundAngle = field.newField( 'groundAngle', 'MFFloat', 1, [])
    groundColor = field.newField( 'groundColor', 'MFColor', 1, [])
    skyColor = field.newField( 'skyColor', 'MFColor', 1, [[0.0, 0.0, 0.0]])
    skyAngle = field.newField( 'skyAngle', 'MFFloat', 1, [])
    
    bound = field.newField( 'bound', 'SFBool', 1, 0)

    def compile(self, mode=None):
        """Build the cached display list for this background object

        Note: we store 2 display lists in the cache, but only return
        one from the compile method.  The second list is the final
        rendering list, while the first is just the low-level rendering
        code.
        """
        colorSet = self.colorSet()
        if len(colorSet):
            vertices, colors = self.buildSphere( colorSet )
            glMultMatrixf( mode.matrix )
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
                glDisable( GL_DEPTH_TEST ) # we don't want to do anything with the depth buffer...
                glDisable( GL_LIGHTING )
                glEnable( GL_COLOR_MATERIAL )
                glDisable( GL_CULL_FACE )
                
                for index in range( int(SEGMENTS) ):
                    first()
                    glRotated( 360.0/SEGMENTS, 0,1,0)
                glDisableClientState( GL_VERTEX_ARRAY )
                glDisableClientState( GL_COLOR_ARRAY )
                # now, completely wipe out the depth buffer, so this appears as a "background"... no idea how expensive this is
                glClear( GL_DEPTH_BUFFER_BIT )

                glEnable( GL_DEPTH_TEST )
                glEnable( GL_LIGHTING )
                glColor( 0.0,0.0,0.0)
                glDisable( GL_COLOR_MATERIAL )
                glEnable( GL_CULL_FACE )
                glFrontFace( GL_CCW )
                
                holder = mode.cache.holder(self, (first, second))
                for field in protofunctions.getFields( self ):
                    # change to any field requires a recompile
                    if field.name != 'bound':
                        holder.depend( self, field )
                return second
            finally:
                second.end()
        holder = mode.cache.holder(self, (None, ()))
        return None
        
    def buildSphere( self, colorSet ):
        """Build a coordinate-set for the color/angle mapping"""
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
        
    def Render( self, mode, clear = 1 ):
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
            if self.bound:
                dl = mode.cache.getData(self)
                if dl is None:
                    dl = self.compile( mode=mode )
                else:
                    # see note on compile's return value/store value
                    dl = dl[1]
                if clear:
                    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT);
                if dl:
                    if callable( dl ):
                        dl()
                    return 1
                return 0


    def colorSet( self ):
        """Compound the sky and ground angle:color arrays into a single angle:color array-set"""
        # okay, ground angles are pi-groundA
        if (
            not len(self.skyAngle) and 
            not len(self.groundAngle) and 
            not len(self.groundColor)
        ):
            # Nothing but sky colours. One of them, with no angle to grade it
            # against, is VRML97's way of saying the sky is that colour all
            # over, so it spans the sphere; with no colours at all there is
            # nothing to draw.
            if len(self.skyColor):
                # Three stops rather than two: buildSphere lays a vertex pair
                # per stop between the poles, so a set of only the two poles
                # describes no surface and nothing rasterises.
                uniform = zeros((3, 4), 'f')
                uniform[:, 1:] = self.skyColor[0]
                uniform[1, 0] = pi / 2.0
                uniform[2, 0] = pi
                return uniform
            return []
        # now need to trim skyA and skyC to lowest groundA
        # and (likely) generate a new A and C for the sky's last value...
        if len(self.skyAngle):
            maxSky = max( self.skyAngle)
        else:
            maxSky = 0
        if len(self.skyAngle):
            if maxSky < pi:
                skys = zeros( (len(self.skyColor)+1,4), 'f')
                skys[1:-1,0] = self.skyAngle
                skys[:-1,1:] = self.skyColor
                skys[-1] = skys[-2]
                skys[-1,0] = pi
            else:
                skys = zeros( (len(self.skyColor),4), 'f')
                skys[1:,0] = self.skyAngle
                skys[:,1:] = self.skyColor
                
                if maxSky > pi:
                    # need to compress back to pi
                    # and possibly do last-element interpolation
                    t = len(compress( less(skys[:,0],pi,0), skys ))-1
                    if skys[t,0] == pi:
                        skys = skys[:t]
                    else:
                        skys = skys[:t+1]
                        skys[t+1] = _linInterp( skys[t],skys[t+1], pi)
                    
            # just to be sure, we sort by angle...
            skys = setSort( skys)
        else:
            skys = zeros((0,4),'f')
        # now need to cap skys to ground's minimum value...
        if len(self.groundAngle):
            # no capping if no grounds, so require angles
            groundA = pi - self.groundAngle
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

            grounds = zeros( (len(self.groundColor),4), 'f')
            grounds[0,0] = pi
            grounds[1:,0] = groundA
            grounds[:,1:] = self.groundColor
            grounds = setSort(grounds)
            if capAngle < MAXANGLE:
                grounds = self.pushOut(grounds,MAXANGLE-(pi/4), MAXANGLE )
            skys = concatenate((skys,grounds))
        else:
            skys = self.pushOut(skys,MAXANGLE-(pi/4), MAXANGLE )
            skys = self.pushOut(skys,MINANGLE,MINANGLE+(pi/4) )
        return skys
    def pushOut( self, colorSet, start,stop ):
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
    _background_shader = None
    _background_shader_locations = None

    @classmethod
    def _compile_background_shader(cls):
        """Compile the background shader program (class-level singleton)."""
        if cls._background_shader is not None:
            return cls._background_shader, cls._background_shader_locations

        vert_path = os.path.join(SHADER_DIR, 'vrml97_background.vert')
        frag_path = os.path.join(SHADER_DIR, 'vrml97_background.frag')

        with open(vert_path, 'r') as f:
            vert_source = f.read()
        with open(frag_path, 'r') as f:
            frag_source = f.read()

        vertex_shader = GL_shaders.compileShader(vert_source, GL_VERTEX_SHADER)
        fragment_shader = GL_shaders.compileShader(frag_source, GL_FRAGMENT_SHADER)
        program = GL_shaders.compileProgram(vertex_shader, fragment_shader)

        locations = {
            'aPosition': glGetAttribLocation(program, 'aPosition'),
            'aColor': glGetAttribLocation(program, 'aColor'),
            'modelViewMatrix': glGetUniformLocation(program, 'modelViewMatrix'),
            'projectionMatrix': glGetUniformLocation(program, 'projectionMatrix'),
        }
        cls._background_shader = program
        cls._background_shader_locations = locations
        return program, locations

    def compileShader(self, mode=None):
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

        all_vertices = concatenate(all_vertices, axis=0)
        all_colors = concatenate(all_colors, axis=0)

        vertices_vbo = vbo.VBO(all_vertices.astype('f'))
        colors_vbo = vbo.VBO(all_colors.astype('f'))

        return (vertices_vbo, colors_vbo, len(all_vertices))

    def RenderShader(self, mode, clear=True):
        """Render the background using shaders.

        Args:
            mode: RenderingPass object with matrix and projection
            clear: Whether to clear buffers before rendering
        """
        if mode.passCount != 0 or not self.bound:
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

        if clear:
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_STENCIL_BUFFER_BIT)

        if shader_data is None:
            return 0

        vertices_vbo, colors_vbo, vertex_count = shader_data

        # Get shader program
        program, locations = self._compile_background_shader()

        # Save state we'll modify (core profile compatible)
        depth_test_enabled = glIsEnabled(GL_DEPTH_TEST)
        cull_face_enabled = glIsEnabled(GL_CULL_FACE)

        # Create VAO for core profile compatibility
        vao = glGenVertexArrays(1)
        glBindVertexArray(vao)

        try:
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_CULL_FACE)

            glUseProgram(program)

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
            glDeleteVertexArrays(1, [vao])
            if depth_test_enabled:
                glEnable(GL_DEPTH_TEST)
            if cull_face_enabled:
                glEnable(GL_CULL_FACE)

        return 1

class SphereBackground( _SphereBackground, nodetypes.Background, nodetypes.Children, node.Node ):
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
    
                           

def _linInterp( a,b, atAngle ):
    c,nc = a[1:], b[1:]
    a,na = a[0], b[0]
    if na == a:
        return b
    # get linear interpolation
    r = zeros((4,),'d')
    r[1:] = c+((atAngle-a)/(na-a) * (nc-c))
    r[0] = atAngle
    return r
    
def setSort( set ):
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
    ).compile())
    
