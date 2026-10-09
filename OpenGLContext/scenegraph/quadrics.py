"""The quadrics: Sphere, Cone and Cylinder, tessellated with NumPy

Each is drawn as the mesh of its arrays at the level of detail its distance
from the viewer chooses (:class:`~OpenGLContext.scenegraph.meshgeometry.LevelledMesh`).
"""
import numpy as np
from typing import Any
from vrml import field, node
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext.scenegraph import boundingvolume
from OpenGLContext.arrays import (
    zeros, arange, sin, cos, pi, concatenate, allclose, copy,
)
from OpenGLContext import vectorutilities
from OpenGLContext.scenegraph import tessellationlod
from OpenGLContext.scenegraph.meshgeometry import LevelledMesh

#: The longitude the sides start at, the back (-Z) for points (sin, cos) of
#: it: where VRML97 puts the texture's seam, u 0 and 1 (19775-1, 13.3).
SEAM = pi


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


def lod_phi( base_phi: float, level: int, period: float ) -> float:
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


def mesh_indices( zstep: int, ystep: int, xstep: int = 1 ) -> Any:
    # now the indices, same as all quadratics
    indices = zeros( (zstep-1,ystep-1,6),dtype='H' )
    # all indices now render the first rectangle...
    indices[:] = (0,0+ystep,0+ystep+xstep, 0,0+ystep+xstep,0+xstep)
    xoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1))
    indices += xoffsets
    yoffsets = arange(0,zstep-1,1,dtype='H').reshape( (-1,1,1))
    indices += (yoffsets * ystep)
    return indices

class Quadric( LevelledMesh, nodetypes.Geometry, node.Node ):
    """Base-class for the quadrics: Sphere, Cone and Cylinder

    Each is drawn as the mesh of its interleaved ``V3F_T2F_N3F`` arrays at the
    level of detail its distance from the viewer chooses
    (:mod:`~OpenGLContext.scenegraph.tessellationlod`); a subclass gives
    :meth:`compileArrays`.
    """
    #: Draws with the pass's lit programs alone, so one draw can serve every
    #: view of a frame that sees it; see :mod:`OpenGLContext.multiview.strategy`.
    multiviewShared = True

    def compileArrays( self, level: int = 0 ) -> tuple[Any, Any]:
        """(coords Nx8 interleaved V3F_T2F_N3F, indices) at `level`"""
        raise NotImplementedError( '%s must give its arrays' % (self.__class__.__name__,) )

    def compile( self, mode: Any = None, level: int = 0, key: str = '' ) -> tuple[Any, Any, int]:
        """(coordinate VBO, index VBO, index count) of :meth:`compileArrays` at `level`

        For a program drawing the quadric's arrays itself, as the shader
        tutorials do; kept in ``mode.cache`` under `key` where `mode` has one.
        The node draws its mesh (:meth:`mesh`).
        """
        from OpenGL.arrays import vbo  # noqa: PLC0415 only a caller drawing the arrays itself needs GL buffers
        coords, indices = self.compileArrays( level )
        vbos = (vbo.VBO( coords ), vbo.VBO( indices, target='GL_ELEMENT_ARRAY_BUFFER' ),
                len( indices ))
        if getattr( mode, 'cache', None ) is not None:
            holder = mode.cache.holder( self, vbos, key=key )
            for name in self._lodDependFields():
                holder.depend( self, name )
        return vbos

    def _lodDependFields( self ) -> tuple[str, ...]:
        """The fields :meth:`compileArrays` reads"""
        return ()

    def levelArrays( self, level: int ) -> Any:
        """The mesh arrays of :meth:`compileArrays` at `level`"""
        from OpenGLContext.scenegraph import meshdata  # noqa: PLC0415 meshdata reads the node path module
        coords, indices = self.compileArrays( level )
        c = np.asarray( coords, dtype='f' ).reshape( -1, 8 )
        return meshdata.arrays( c[:, 0:3], c[:, 5:8], c[:, 3:5], indices=np.asarray( indices ) )

    def drawLevel( self, mode: Any ) -> int:
        """The level for this quadric's distance from the viewer"""
        return int( tessellationlod.lod_level( mode, (0, 0, 0), self._lod_bounding_radius() ) )

    # -- distance level-of-detail -----------------------------------------
    def _lod_bounding_radius( self ) -> float:
        """Characteristic local radius for the distance metric (subclass hook)."""
        return 1.0

class Sphere( basenodes.Sphere, Quadric ):
    """Sphere geometry rendered with GLU quadratic calls"""
    # Unit spheres are context-independent and shared across instances, one per
    # LOD level (keyed by level -> (coords, indices)).
    #: Unit-radius meshes, keyed by the angular step they were tessellated at,
    #: so every sphere drawn at a given detail shares one tessellation.
    _unitSpheres: dict[float, tuple[Any, Any]] = {}
    #: Base angular step: pi/12 is a 24-sided silhouette, fine enough that the
    #: LOD schedule can step down from it without a visible pop.
    phi = field.newField( 'phi', 'SFFloat', 1, pi/12.0)

    def _lod_bounding_radius( self ) -> float:
        return float( self.radius )

    def compileArrays( self, level: int = 0 ) -> tuple[Any, Any]:
        """Compile to arrays at the given LOD level...

        returns coordarray, indexarray
        """
        # period=pi: phi must divide the pole-to-pole latitude evenly (which
        # also closes the 2*pi longitude) or the mesh has a cap/seam gap.
        step = lod_phi( self.phi, level, pi )
        # Keyed on the step rather than on the level, because the step is what
        # the mesh is: two spheres of different phi at the same level are two
        # different meshes, and two that resolve to the same step are one.
        if step not in Sphere._unitSpheres:
            Sphere._unitSpheres[step] = self.sphere( step )
        coords,indices = Sphere._unitSpheres[step]
        coords = copy( coords )
        coords[:,0:3] *= self.radius
        return coords, indices

    def _lodDependFields( self ) -> tuple[str, ...]:
        return ('radius', 'phi')

    def instanceContentKey( self ) -> tuple[Any, ...]:
        """Spheres of the same radius/tessellation share geometry -> one instanced
        draw (the molecular-model case: thousands of identical atoms)."""
        return ('Sphere', round(float(self.radius), 6), round(float(self.phi), 6),
                bool(self.solid))

    @classmethod
    def sphere( cls, phi: float = pi/8.0, latAngle: float = pi,
                longAngle: float = (pi*2) ) -> tuple[Any, Any]:
        """Create arrays for rendering a unit-sphere
        
        phi -- angle between points on the sphere (stacks/slices)

        The longitude starts at the back, -Z, where VRML97's texture seam is
        (:data:`SEAM`).

        returns coordarray, indexarray
        """
        latsteps = arange( 0,latAngle+0.000003, phi )
        longsteps = SEAM + arange( 0,longAngle+0.000003, phi )
        return cls._partialSphere( latsteps,longsteps )

    @classmethod
    def _partialSphere( cls, latsteps: Any, longsteps: Any ) -> tuple[Any, Any]:
        """Create a partial-sphere data-set for latsteps and longsteps
        
        returns (coordarray, indexarray)
        """
        ystep = len(longsteps)
        zstep = len(latsteps)
        coords = zeros((zstep,ystep,8), 'f')
        coords[:,:,0] = sin(longsteps)
        coords[:,:,1] = cos(latsteps).reshape( (-1,1))
        coords[:,:,2] = cos(longsteps)
        # VRML97: u from 0 at the seam, anticlockwise seen from above; v
        # from 0 at the bottom to 1 at the top
        coords[:,:,3] = (longsteps - SEAM)/(2*pi)
        coords[:,:,4] = 1.0 - latsteps.reshape( (-1,1))/ pi
        
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
    
    def boundingVolume( self, mode: Any = None ) -> Any:
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

    def _lod_bounding_radius( self ) -> float:
        return max( float(self.bottomRadius), float(self.height) / 2.0 )

    def compileArrays( self, level: int = 0 ) -> tuple[Any, Any]:
        """(coords Nx8 interleaved V3F_T2F_N3F, indices) at `level`"""
        return self.cone(
            self.height, self.bottomRadius, self.bottom, self.side,
            phi=lod_phi( self._BASE_PHI, level, 2*pi ),   # ring closes over 2*pi
        )

    def _lodDependFields( self ) -> tuple[str, ...]:
        return ('bottomRadius', 'height', 'bottom', 'side')

    def instanceContentKey( self ) -> tuple[Any, ...]:
        return ('Cone', round(float(self.height), 6), round(float(self.bottomRadius), 6),
                bool(self.bottom), bool(self.side), bool(self.solid))

    @classmethod
    def cone(
        cls, height: float = 2.0, radius: float = 1.0, bottom: bool = True,
        side: bool = True, phi: float = pi/16, longAngle: float = (pi*2),
        top: bool = False, cylinder: bool = False
    ) -> tuple[Any, Any]:
        """Generate a VBO data-set to render a cone

        Texture coordinates are VRML97's: the side wraps from the seam at the
        back (:data:`SEAM`) with v 0 at the bottom; the top cap's image is
        upright with its top toward -Z, the bottom cap's toward +Z.
        """
        longsteps = SEAM + arange( 0,longAngle+0.000003, phi )
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
        coords[:,:,3] = (longsteps - SEAM)/(2*pi)
        def fill_disk( area: Any, ycoord: float, normal: Any = (0,-1,0),
                       degenerate: int = 1, towards: float = 1.0 ) -> None:
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
            area[other,:,4] = towards * cos( longsteps ) / 2.0 + .5
            area[degenerate,:,3:5] = .5
            # normal for the disk is all the same...
            area[:,:,5:8] = normal
        def fill_sides( area: Any ) -> None:
            """Fill in side-of-cylinder/cone components"""
            if not cylinder:
                area[0,:,0:3] = (0,height/2.0,0)
            else:
                area[0,:,1] = height/2.0
            area[1,:,1] = -height/2.0
            area[0,:,4] = 1.0
            area[1,:,4] = 0.0
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
            fill_disk( coords[offset:offset+2],height/2.0,(0,1,0), degenerate=0,
                       towards=-1.0 )
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
    
    def boundingVolume( self, mode: Any = None ) -> Any:
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
    def _lod_bounding_radius( self ) -> float:
        return max( float(self.radius), float(self.height) / 2.0 )

    def compileArrays( self, level: int = 0 ) -> tuple[Any, Any]:
        """(coords Nx8 interleaved V3F_T2F_N3F, indices) at `level`"""
        return Cone.cone(
            self.height, self.radius, self.bottom, self.side,
            phi=lod_phi( Cone._BASE_PHI, level, 2*pi ),   # ring closes over 2*pi
            top=self.top, cylinder=True,
        )

    def _lodDependFields( self ) -> tuple[str, ...]:
        return ('radius', 'height', 'bottom', 'side', 'top')

    def instanceContentKey( self ) -> tuple[Any, ...]:
        return ('Cylinder', round(float(self.height), 6), round(float(self.radius), 6),
                bool(self.bottom), bool(self.side), bool(self.top), bool(self.solid))

    def boundingVolume( self, mode: Any = None ) -> Any:
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
    
