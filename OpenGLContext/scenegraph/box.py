"""Box node for use in geometry attribute of Shapes"""
from vrml import cache
from OpenGLContext.arrays import array
from OpenGL.arrays import vbo
from OpenGL.GL import *
from vrml.vrml97 import basenodes
from vrml import protofunctions

class Box( basenodes.Box ):
    """Simple Box object of given size centered about local origin

    The Box geometry node can be used in the geometry
    field of a Shape node to be displayed. Use Transform
    nodes to position the box within the world.

    The Box includes texture coordinates and normals.

    Attributes of note within the Box object:

        size -- x,y,z tuple giving the size of the box
        listID -- used internally to store the display list
            used to display the box during rendering

    Reference:
        http://www.web3d.org/technicalinfo/specifications/vrml97/part1/nodesRef.html#Box
    """
    def compile( self, mode=None ):
        """Compile the box as a display-list"""
        if vbo.get_implementation():
            vb = vbo.VBO( array( list(yieldVertices( self.size )), 'f'))
            def draw( textured=True,lit=True ):
                vb.bind()
                try:
                    glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
                    try:
                        glEnableClientState( GL_VERTEX_ARRAY )
                        if lit:
                            glEnableClientState( GL_NORMAL_ARRAY )
                            glNormalPointer( GL_FLOAT, 32, vb+8 )
                        if textured:
                            glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                            glTexCoordPointer( 2, GL_FLOAT, 32, vb )
                        glVertexPointer( 3, GL_FLOAT, 32, vb+20 )
                        glDrawArrays( GL_TRIANGLES, 0, 36 )
                    finally:
                        glPopClientAttrib()
                finally:
                    vb.unbind()
        else:
            vb = array( list(yieldVertices( self.size )), 'f')
            def draw(textured=True,lit=True):
                glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
                try:
                    glInterleavedArrays( GL_T2F_N3F_V3F, 0, vb )
                    glDrawArrays( GL_TRIANGLES, 0, 36 )
                finally:
                    glPopClientAttrib()
        holder = mode.cache.holder(self, draw)
        holder.depend( self, protofunctions.getField(self, 'size') )
        return draw

    def _get_shader_vbo(self, mode):
        """Get or create VBO for shader rendering."""
        vb = mode.cache.getData(self, 'shader_vbo')
        if vb is None:
            vb = vbo.VBO(array(list(yieldVertices(self.size)), 'f'))
            holder = mode.cache.holder(self, vb, 'shader_vbo')
            holder.depend(self, protofunctions.getField(self, 'size'))
        return vb

    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # XXX should sort triangle geometry...
            mode = None, # the renderpass object for which we compile
        ):
        """Render the Box (build and) call the display list"""
        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode)

        # Legacy rendering path
        vb = mode.cache.getData(self)
        if not vb:
            vb = self.compile( mode=mode )
        if vb:
            vb(textured=textured,lit=lit)
        return 1

    def _render_shader(self, mode):
        """Render the box using the shader pipeline."""
        from OpenGLContext.scenegraph.shadergeometry import VertexFormat
        from OpenGLContext.scenegraph.geometryarrays import (
            GeometryArrays, render_geometry,
        )
        vb = self._get_shader_vbo(mode)
        return render_geometry(mode, GeometryArrays.interleaved(
            vb, VertexFormat.T2F_N3F_V3F, count=36,
        ), owner=self, where='Box')

    def instanceContentKey(self):
        """Boxes of the same size share geometry, so they batch as instances."""
        return ('Box', tuple(round(float(v), 6) for v in self.size))

    def instanceGPU(self, mode):
        """Cached separate-VBO mesh-GPU (position/normal/texcoord) for instancing."""
        from OpenGLContext.passes.instancing import build_mesh_gpu
        verts = list(yieldVertices(self.size))   # (u,v, nx,ny,nz, x,y,z) * 36
        texcoords = [v[0:2] for v in verts]
        normals = [v[2:5] for v in verts]
        positions = [v[5:8] for v in verts]
        return build_mesh_gpu(
            mode, self, positions, normals, texcoords, indices=None,
            cache_key='instance_gpu',
            depend_fields=(protofunctions.getField(self, 'size'),))
    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size = self.size,
            ),
            ( (self, 'size'), ),
        )

def yieldVertices(size):
    x,y,z = size 
    x,y,z = x/2.0,y/2.0,z/2.0
    normal = ( 0.0, 0.0, 1.0)
    yield (0.0, 0.0)+ normal + (-x,-y,z);
    yield (1.0, 0.0)+ normal + (x,-y,z);
    yield (1.0, 1.0)+ normal + (x,y,z);
    yield (0.0, 0.0)+ normal + (-x,-y,z);
    yield (1.0, 1.0)+ normal + (x,y,z);
    yield (0.0, 1.0)+ normal + (-x,y,z);

    normal = ( 0.0, 0.0,-1.0);
    yield (1.0, 0.0)+ normal + (-x,-y,-z);
    yield (1.0, 1.0)+ normal + (-x,y,-z);
    yield (0.0, 1.0)+ normal + (x,y,-z);
    yield (1.0, 0.0)+ normal + (-x,-y,-z);
    yield (0.0, 1.0)+ normal + (x,y,-z);
    yield (0.0, 0.0)+ normal + (x,-y,-z);

    normal = ( 0.0, 1.0, 0.0)
    yield (0.0, 1.0)+ normal + (-x,y,-z);
    yield (0.0, 0.0)+ normal + (-x,y,z);
    yield (1.0, 0.0)+ normal + (x,y,z);
    yield (0.0, 1.0)+ normal + (-x,y,-z);
    yield (1.0, 0.0)+ normal + (x,y,z);
    yield (1.0, 1.0)+ normal + (x,y,-z);

    normal = ( 0.0,-1.0, 0.0)
    yield (1.0, 1.0)+ normal + (-x,-y,-z);
    yield (0.0, 1.0)+ normal + (x,-y,-z);
    yield (0.0, 0.0)+ normal + (x,-y,z);
    yield (1.0, 1.0)+ normal + (-x,-y,-z);
    yield (0.0, 0.0)+ normal + (x,-y,z);
    yield (1.0, 0.0)+ normal + (-x,-y,z);

    normal = ( 1.0, 0.0, 0.0)
    yield (1.0, 0.0)+ normal + (x,-y,-z);
    yield (1.0, 1.0)+ normal + (x,y,-z);
    yield (0.0, 1.0)+ normal + (x,y,z);
    yield (1.0, 0.0)+ normal + (x,-y,-z);
    yield (0.0, 1.0)+ normal + (x,y,z);
    yield (0.0, 0.0)+ normal + (x,-y,z);

    normal = (-1.0, 0.0, 0.0)
    yield (0.0, 0.0)+ normal + (-x,-y,-z);
    yield (1.0, 0.0)+ normal + (-x,-y,z);
    yield (1.0, 1.0)+ normal + (-x,y,z);
    yield (0.0, 0.0)+ normal + (-x,-y,-z);
    yield (1.0, 1.0)+ normal + (-x,y,z);
    yield (0.0, 1.0)+ normal + (-x,y,-z);
