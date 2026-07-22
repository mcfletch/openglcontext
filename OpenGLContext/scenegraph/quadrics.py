"""Quadratic geometry types (cone, sphere, cylinder, etc)

This implementation does not use the gluQuadric objects, it 
does direct creation via numpy operations.
"""
import numpy as np
from OpenGL.GL import *
from vrml import field, protofunctions, node
from vrml.vrml97 import basenodes, nodetypes
from vrml import cache
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.arrays import (
    zeros, arange, sin, cos, pi, concatenate, allclose, copy,
)
from OpenGLContext import vectorutilities
from OpenGLContext.scenegraph import tessellationlod
from OpenGL.arrays import vbo


# Distance-LOD tuning (Option B: dense base + gentle steps). A UV quadric's
# silhouette is its slice count, so *any* visible drop in slices reads as the
# outline turning polygonal (an octagon) -- the only way to keep transitions from
# popping is to start dense and step down GENTLY, never below a "still round"
# floor. Measured object-pop (fraction of the object's own pixels that change at
# a switch) for this schedule is ~2-14% per step, versus ~75% for an aggressive
# halving; see tests/test_lod_transitions.py.
#
# Each level keeps this fraction of the full-resolution slice count:
LOD_STEP_FACTOR = (1.0, 0.83, 0.67, 0.5)
# ...but never fewer than this many slices, so the coarsest level stays a
# recognizable round solid rather than a smoothed tetrahedron.
LOD_MIN_STEPS = 6


def lod_phi( base_phi, level, period ):
    """Angular step for an LOD level that divides ``period`` into whole steps.

    ``period`` is the angular span the steps must close over: ``pi`` for a
    sphere's pole-to-pole latitude (which also makes its 2*pi longitude close),
    ``2*pi`` for a cone/cylinder's ring. Returning ``period / steps`` for an
    integer ``steps`` is essential -- ``arange(0, period, phi)`` only reaches
    ``period`` (closing the mesh) when phi divides it evenly; an arbitrary scaled
    phi left the last step short, so coarse quadrics were missing a pole cap /
    seam wedge (off-by-one whose size grew with the level).
    """
    full_steps = max( LOD_MIN_STEPS, round( period / base_phi ) )
    factor = LOD_STEP_FACTOR[min(level, len(LOD_STEP_FACTOR) - 1)]
    steps = max( LOD_MIN_STEPS, round( full_steps * factor ) )
    return period / steps


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
        # Check for shader mode
        if getattr(mode, 'shader_mode', False):
            return self._render_shader(mode)

        # Legacy rendering path
        vbos = self._lod_vbos( mode )
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
                    glTexCoordPointer( 2, GL_FLOAT,32,coords+12)
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
            indices.unbind()
            coords.unbind()
        return 1

    def _render_shader(self, mode):
        """Render the quadric using the shader pipeline."""
        from OpenGLContext.scenegraph.shadergeometry import (
            render_shader_interleaved, VertexFormat
        )
        vbos = self._lod_vbos( mode )
        if vbos is None:
            return 1
        coords, indices, count = vbos
        return render_shader_interleaved(
            mode, coords, 0, VertexFormat.V3F_T2F_N3F,
            index_vbo=indices, index_count=count, owner=self
        )

    # -- distance level-of-detail -----------------------------------------
    def _lod_bounding_radius( self ):
        """Characteristic local radius for the distance metric (subclass hook)."""
        return 1.0

    def _lod_vbos( self, mode ):
        """Return the (coords, indices, count) VBOs for this frame's LOD level.

        Each level is tessellated and cached separately under ``mode.cache`` so a
        near quadric keeps full detail while a far one reuses a coarse mesh; the
        level 0 mesh matches the pre-LOD tessellation, so close-up appearance is
        unchanged.
        """
        level = tessellationlod.lod_level( mode, (0, 0, 0), self._lod_bounding_radius() )
        key = 'lod%d' % level
        vbos = None
        if hasattr( mode, 'cache' ):
            vbos = mode.cache.getData( self, key=key )
        if not vbos:
            vbos = self.compile( mode=mode, level=level, key=key )
        return vbos

    def compile( self, mode=None, level=0, key='' ):
        """Compile this sphere for use on mode"""
        raise NotImplementedError( """Haven't implemented %s compilation yet"""%(self.__class__.__name__,))

    # -- instancing -------------------------------------------------------
    # Quadrics share one interleaved V3F_T2F_N3F layout, so one instanced-draw
    # GPU builder serves them all; each subclass supplies its arrays + content key.
    def _instanceArrays( self ):
        """(coords Nx8 interleaved V3F_T2F_N3F, indices) at a fixed LOD level."""
        raise NotImplementedError

    def _instanceDependFields( self ):
        """Fields whose change should rebuild the cached instance GPU."""
        return ()

    def instanceGPU( self, mode ):
        """Cached separate-VBO mesh-GPU (position/normal/texcoord) for instancing.

        De-interleaves the quadric's V3F_T2F_N3F arrays (fixed LOD, so every
        instance shares one tessellation) into the shader attribute layout.
        """
        from OpenGLContext.passes.instancing import build_mesh_gpu
        coords, indices = self._instanceArrays()
        c = np.asarray( coords, dtype='f' ).reshape( -1, 8 )
        return build_mesh_gpu(
            mode, self, positions=c[:, 0:3], normals=c[:, 5:8],
            texcoords=c[:, 3:5], indices=np.asarray( indices ).ravel(),
            cache_key='instance_gpu', depend_fields=self._instanceDependFields() )

class Sphere( basenodes.Sphere, Quadric ):
    """Sphere geometry rendered with GLU quadratic calls"""
    # Unit spheres are context-independent and shared across instances, one per
    # LOD level (keyed by level -> (coords, indices)).
    _unitSpheres = None
    # Base angular step. Raised from the old pi/6 (a chunky 12-gon that made every
    # LOD step read as an octagon) to pi/12 (a smooth 24-gon), giving headroom for
    # the gentle LOD schedule to step down without a visible silhouette pop.
    phi = field.newField( 'phi', 'SFFloat', 1, pi/12.0)

    def _lod_bounding_radius( self ):
        return float( self.radius )

    def compile( self, mode=None, level=0, key='' ):
        """Compile this sphere for use on mode

        returns coordvbo,indexvbo,count
        """
        coords, indices = self.compileArrays( level )
        vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
        if hasattr(mode,'cache'):
            holder = mode.cache.holder( self, vbos, key=key )
            holder.depend( self, 'radius' )
        return vbos

    def compileArrays( self, level=0 ):
        """Compile to arrays at the given LOD level...

        returns coordarray, indexarray
        """
        if Sphere._unitSpheres is None:
            Sphere._unitSpheres = {}
        if level not in Sphere._unitSpheres:
            # one unit sphere per level, tessellated with a coarser phi as the
            # level rises; level 0 uses the node's base phi (unchanged look).
            # period=pi: phi must divide the pole-to-pole latitude evenly (which
            # also closes the 2*pi longitude) or the mesh has a cap/seam gap.
            Sphere._unitSpheres[level] = self.sphere( lod_phi( self.phi, level, pi ) )
        coords,indices = Sphere._unitSpheres[level]
        coords = copy( coords )
        coords[:,0:3] *= self.radius
        return coords, indices

    def instanceContentKey( self ):
        """Spheres of the same radius/tessellation share geometry -> one instanced
        draw (the molecular-model case: thousands of identical atoms)."""
        return ('Sphere', round(float(self.radius), 6), round(float(self.phi), 6))

    def _instanceArrays( self ):
        return self.compileArrays( 0 )

    def _instanceDependFields( self ):
        return ('radius',)
    
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
    _BASE_PHI = pi/16

    def _lod_bounding_radius( self ):
        return max( float(self.bottomRadius), float(self.height) / 2.0 )

    def compile( self, mode=None, level=0, key='' ):
        """Compile this sphere for use on mode"""
        coords,indices = self.cone(
            self.height, self.bottomRadius, self.bottom, self.side,
            phi=lod_phi( self._BASE_PHI, level, 2*pi ),   # ring closes over 2*pi
        )
        vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
        holder = mode.cache.holder( self, vbos, key=key )
        holder.depend( self, 'bottomRadius' )
        holder.depend( self, 'height' )
        return vbos

    def instanceContentKey( self ):
        return ('Cone', round(float(self.height), 6), round(float(self.bottomRadius), 6),
                bool(self.bottom), bool(self.side))

    def _instanceArrays( self ):
        return self.cone( self.height, self.bottomRadius, self.bottom, self.side,
                          phi=lod_phi( self._BASE_PHI, 0, 2*pi ) )

    def _instanceDependFields( self ):
        return ('bottomRadius', 'height', 'bottom', 'side')

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
            # Use integer index, not boolean (numpy boolean indexing differs!)
            other = 1 - degenerate
            # disk texture coordinates
            area[:,:,1] = ycoord
            # x and z are 0 at center
            area[degenerate,:,0] = 0.0
            area[degenerate,:,2] = 0.0
            # Set texture coords for the outer ring (non-degenerate row)
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
    def _lod_bounding_radius( self ):
        return max( float(self.radius), float(self.height) / 2.0 )

    def compile( self, mode=None, level=0, key='' ):
        """Compile this sphere for use on mode"""
        coords,indices = Cone.cone(
            self.height, self.radius, self.bottom, self.side,
            phi=lod_phi( Cone._BASE_PHI, level, 2*pi ),   # ring closes over 2*pi
            top=self.top, cylinder=True,
        )
        vbos = vbo.VBO(coords), vbo.VBO(indices,target = 'GL_ELEMENT_ARRAY_BUFFER' ), len(indices)
        holder = mode.cache.holder( self, vbos, key=key )
        holder.depend( self, 'radius' )
        holder.depend( self, 'height' )
        return vbos

    def instanceContentKey( self ):
        return ('Cylinder', round(float(self.height), 6), round(float(self.radius), 6),
                bool(self.bottom), bool(self.side), bool(self.top))

    def _instanceArrays( self ):
        return Cone.cone( self.height, self.radius, self.bottom, self.side,
                          phi=lod_phi( Cone._BASE_PHI, 0, 2*pi ),
                          top=self.top, cylinder=True )

    def _instanceDependFields( self ):
        return ('radius', 'height', 'bottom', 'side', 'top')

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
    
