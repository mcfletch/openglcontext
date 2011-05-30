"""Quadratic geometry types (cone, sphere, cylinder, etc)

This implementation does not use the gluQuadric objects, it 
does direct creation via numpy operations.
"""
from OpenGL.GL import *
from vrml import field, protofunctions, node
from vrml.vrml97 import basenodes, nodetypes
from vrml import cache
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.arrays import *
from OpenGLContext import vectorutilities
from OpenGL.arrays import vbo


def mesh_indices( zstep,ystep, xstep=1 ):
    # now the indices, same as all quadratics
    indices = zeros( (zstep-1,ystep-1,6),dtype='H' )
    # all indices now render the first rectangle...
    indices[:] = (0,0+ystep,0+ystep+xstep, 0,0+ystep+xstep,0+xstep)
    xoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1))
    indices += xoffsets
    yoffsets = arange(0,zstep-1,1,dtype='H').reshape( (-1,1,1))
    indices += (yoffsets * ystep)
    return indices

class Quadric( nodetypes.Geometry, node.Node ):
    """Base-class for the various quadratic-type geometry classes"""
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0,
            mode = None, # the renderpass object for which we compile
        ):
        """Render the geometry"""
        vbos = mode.cache.getData(self)
        if not vbos:
            vbos = self.compile( mode = mode )
        if vbos is None:
            return 1
        coords,indices,count = vbos
        glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            coords.bind()
            glEnableClientState(GL_VERTEX_ARRAY)
            glVertexPointer( 3, GL_FLOAT,32,coords)
            if visible:
                if textured:
                    glEnableClientState(GL_TEXTURE_COORD_ARRAY)
                    glTexCoordPointer( 3, GL_FLOAT,32,coords+12)
                if lit:
                    glEnableClientState(GL_NORMAL_ARRAY)
                    glNormalPointer( GL_FLOAT,32,coords+20 )
            # TODO: sort for transparent geometry...
            indices.bind()
            # Can loop loading matrix and calling just this function 
            # for each sphere you want to render...
            # include both scale and position in the matrix...
            glDrawElements( 
                GL_TRIANGLES, count, GL_UNSIGNED_SHORT, indices
            )
        finally:
            glPopAttrib()
            glPopClientAttrib()
            coords.unbind()
            indices.unbind()
    def compile( self, mode=None ):
        """Compile this sphere for use on mode"""
        raise NotImplementedError( """Haven't implemented %s compilation yet"""%(self.__class__.__name__,))

class Sphere( basenodes.Sphere, Quadric ):
    """Sphere geometry rendered with GLU quadratic calls"""
    _unitSphere = None
    phi = field.newField( 'phi', 'SFFloat', 1, pi/6.0)
    def compile( self, mode=None ):
        """Compile this sphere for use on mode
        
        returns coordvbo,indexvbo,count
        """
        coords, indices = self.compileArrays( )
        vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
        if hasattr(mode,'cache'):
            holder = mode.cache.holder( self, vbos )
            holder.depend( self, 'radius' )
        return vbos
    
    def compileArrays( self ):
        """Compile to arrays...
        
        returns coordarray, indexarray
        """
        if self._unitSphere is None:
            # create a unitsphere instance for all instances
            Sphere._unitSphere = self.sphere( self.phi )
        coords,indices = self._unitSphere
        coords = copy( coords )
        coords[:,0:3] *= self.radius
        return coords, indices
    
    @classmethod
    def sphere( cls, phi=pi/8.0, latAngle=pi, longAngle=(pi*2) ):
        """Create arrays for rendering a unit-sphere
        
        phi -- angle between points on the sphere (stacks/slices)
        
        Note: creates 'H' type indices...
        
        returns coordarray, indexarray
        """
        latsteps = arange( 0,latAngle+0.000003, phi )
        longsteps = arange( 0,longAngle+0.000003, phi )
        return cls._partialSphere( latsteps,longsteps )

    @classmethod
    def _partialSphere( cls, latsteps, longsteps ):
        """Create a partial-sphere data-set for latsteps and longsteps
        
        returns (coordarray, indexarray)
        """
        ystep = len(longsteps)
        zstep = len(latsteps)
        xstep = 1
        coords = zeros((zstep,ystep,8), 'f')
        coords[:,:,0] = sin(longsteps)
        coords[:,:,1] = cos(latsteps).reshape( (-1,1))
        coords[:,:,2] = cos(longsteps)
        coords[:,:,3] = longsteps/(2*pi)
        coords[:,:,4] = latsteps.reshape( (-1,1))/ pi
        
        # now scale by sin of y's 
        scale = sin(latsteps).reshape( (-1,1))
        coords[:,:,0] *= scale
        coords[:,:,2] *= scale
        coords[:,:,5:8] = coords[:,:,0:3] # normals
        
        indices = mesh_indices( zstep, ystep )
        
        # now optimize/simplify the data-set...
        new_indices = []
        
        for (i,iSet) in enumerate(indices ):
            angle = latsteps[i]
            nextAngle = latsteps[i+1]
            if allclose(angle%(pi*2),0):
                iSet = iSet.reshape( (-1,3))[::2]
            elif allclose(nextAngle%(pi),0):
                iSet = iSet.reshape( (-1,3))[1::2]
            else:
                iSet = iSet.reshape( (-1,3))
            new_indices.append( iSet )
        indices = concatenate( new_indices )
        return coords.reshape((-1,8)), indices.reshape((-1,))
    
    def boundingVolume( self, mode=None ):
        """Create a bounding-volume object for this node

        In this case we use the AABoundingBox, despite
        the presence of the bounding sphere implementation.
        This is just a preference issue, I'm using
        AABoundingBox everywhere else, and want the sphere
        to interoperate properly.
        """
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size = (self.radius*2,self.radius*2,self.radius*2),
            ),
            ( (self, 'radius'), ),
        )
        
class Cone( basenodes.Cone, Quadric ):
    """Cone geometry rendered with GLU quadratic calls"""
    def compile( self, mode=None ):
        """Compile this sphere for use on mode"""
        coords,indices = self.cone( self.height, self.bottomRadius, self.bottom, self.side )
        vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
        holder = mode.cache.holder( self, vbos )
        holder.depend( self, 'bottomRadius' )
        holder.depend( self, 'height' )
        return vbos
    
    @classmethod
    def cone( 
        cls, height=2.0, radius=1.0, bottom=True, side=True,
        phi = pi/16, longAngle=(pi*2), top=False, cylinder=False
    ):
        """Generate a VBO data-set to render a cone"""
        tip = (0,height/2.0,0)
        longsteps = arange( 0,longAngle+0.000003, phi )
        ystep = len(longsteps)
        zstep = 0
        if top and cylinder:
            zstep += 2
        if side:
            zstep += 2
        if bottom:
            zstep += 2
        # need top-ring coords and 2 sets for 
        coords = zeros( (zstep,ystep,8), 'f')
        coords[:,:,0] = sin(longsteps) * radius
        coords[:,:,2] = cos(longsteps) * radius
        coords[:,:,3] = longsteps/(2*pi)
        def fill_disk( area, ycoord, normal=(0,-1,0), degenerate=1 ):
            """fill in disk elements for given area"""
            other = not degenerate
            # disk texture coordinates
            area[:,:,1] = ycoord
            # x and z are 0 at center
            area[degenerate,:,0] = 0.0 
            area[degenerate,:,2] = 0.0
            area[other,:,3] = sin( longsteps ) / 2.0 + .5
            area[other,:,4] = cos( longsteps ) / 2.0 + .5
            area[degenerate,:,3:5] = .5
            # normal for the disk is all the same...
            area[:,:,5:8] = normal
        def fill_sides( area ):
            """Fill in side-of-cylinder/cone components"""
            if not cylinder:
                area[0,:,0:3] = (0,height/2.0,0)
            else:
                area[0,:,1] = height/2.0
            area[1,:,1] = -height/2.0
            area[0,:,4] = 0
            area[1,:,4] = 1.0
            # normals for the sides...
            area[0:2,:-1,5:8] = vectorutilities.normalise(
                vectorutilities.crossProduct( 
                    area[0,:-1,0:3] - area[1,:-1,0:3],
                    area[1,:-1,0:3] - area[1,1:,0:3]
                )
            )
            area[0:2,-1,5:8] = area[0:2,0,5:8]
        
        offset = 0
        tocompress = {}
        if top and cylinder:
            fill_disk( coords[offset:offset+2],height/2.0,(0,1,0), degenerate=0 )
            tocompress[offset] = 0
            offset += 2
        if side:
            fill_sides( coords[offset:offset+2] )
            offset += 2
        if bottom:
            # disk texture coordinates
            fill_disk( coords[offset:offset+2], -height/2.0, (0,-1,0), degenerate=1 )
            tocompress[offset] = 1
            offset += 2
        
        # now the indices, same as all quadratics
        indices = mesh_indices( zstep, ystep )
        new_indices = []
        for (i,iSet) in enumerate( indices ):
            iSet = iSet.reshape( (-1,3) )
            if i in tocompress:
                if not tocompress[i]:
                    iSet = iSet[::2]
                else:
                    iSet = iSet[1::2]
            new_indices.append( iSet ) 
        # compress out degenerate indices if present...
        indices = concatenate( new_indices )
        return coords.reshape( (-1,8)), indices.reshape( (-1,))
    
    def boundingVolume( self, mode=None ):
        """Create a bounding-volume object for this node

        In this case we use the AABoundingBox, despite
        the presence of the bounding sphere implementation.
        This is just a preference issue, I'm using
        AABoundingBox everywhere else, and want the sphere
        to interoperate properly.
        """
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        radius = self.bottomRadius
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size = (radius*2,self.height,radius*2),
            ),
            ( (self, 'bottomRadius'), (self,'height') ),
        )



class Cylinder( basenodes.Cylinder, Quadric ):
    """Cylinder geometry rendered with GLU quadratic calls"""
    def compile( self, mode=None ):
        """Compile this sphere for use on mode"""
        coords,indices = Cone.cone( 
            self.height, self.radius, self.bottom, self.side,
            top=self.top, cylinder=True,
        )
        vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
        holder = mode.cache.holder( self, vbos )
        holder.depend( self, 'radius' )
        holder.depend( self, 'height' )
        return vbos
    def boundingVolume( self, mode=None ):
        """Create a bounding-volume object for this node

        In this case we use the AABoundingBox, despite
        the presence of the bounding sphere implementation.
        This is just a preference issue, I'm using
        AABoundingBox everywhere else, and want the sphere
        to interoperate properly.
        """
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        radius = self.radius
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                size = (radius*2,self.height,radius*2),
            ),
            ( (self, 'radius'), (self,'height') ),
        )

if __name__ == "__main__":
    c = Cone.cone()
    
