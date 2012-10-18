"""Produce Quake3-style Quadratic Bezier Splines"""
from OpenGLContext.arrays import *

def weights( a ):
    """Calculate control-point weights for given step on the control curve
    
    This is currently hard-coded as:
    
        a**2, 2*a*(1.0-a), (1.0-a)**2
    
    It could be parameterized in the future to allow for other weightings 
    and/or higher-order splines.
    
    returns numpy 'f' array of weights
    """
    b = 1.0 - a
    return array([a**2, 2*a*b, b**2],dtype='f')
def weight_array( divisions ):
    """Create array of weights for the given number of divisions"""
    assert divisions > 1, """Need at least 1 division"""
    steps = arange( divisions )/float(divisions-1)
    return array([
        weights(1.0-a)
        for a in steps
    ], dtype='f' )

def _final_count( M,divisions=10 ):
    """Calculate final number of vertices where M control points are defined"""
    return ((M - 1)//2 * divisions-1) + 1

def grid_size( points, divisions=10 ):
    """Calculate grid dimensions for given set of points
    
    returns (M,N) size of the final grid
    """
    M,N = points.shape[:2]
    return _final_count( M, divisions ), _final_count( N, divisions )

def expand_color( points, division=10 ):
    """Expand color control-points array 
    
    Texture coordinates are blended from control[0] to control[2] for each 
    sub-patch in the points grid
    """

def four_way_blend( divisions = 10 ):
    """Create a matrix doing 4-way blend for a patch
    
    Assumes vertices are in CCW order around the patch...
    """
    divisions = _final_count( 3, divisions )
    
    ramp = arange( divisions )/float( divisions-1 )
    
    curves = zeros( (2,divisions,4), dtype='f' )
    curves[0,:,0] = ramp[::-1]
    curves[0,:,1] = ramp
    curves[-1,:,2] = ramp
    curves[-1,:,3] = ramp[::-1]
    # now, the matrix is just the ramps between curves...
    blend_ramp1 = zeros( (divisions,divisions,4), dtype='f')
    blend_ramp2 = zeros( (divisions,divisions,4), dtype='f')

    blend_ramp1[:] = curves[0]
    blend_ramp2[:] = curves[1]
    
    blend_ramp1 *= ramp.reshape((divisions,1))
    blend_ramp2 *= ramp[::-1].reshape((divisions,1))
    
    return blend_ramp1 + blend_ramp2
    
def expand_blend( points, divisions=10 ):
    """Blend control points for each sub-patch in points
    
    Texture coordinates are blended from control[0] to control[2] for each 
    sub-patch in the points grid
    """
    M,N,d = points.shape
    expanded = zeros( (_final_count(M,divisions),_final_count(N,divisions),d), dtype=points.dtype )
    
    blend_ramp = four_way_blend( divisions )
    
    # Index in the control points array
    for m in range( 0, M-1, 2 ):
        # index in the expanded array
        m_final = (m//2) * divisions 
        # Index in the control points array
        for n in range( 0, N-1, 2 ):
            # index in the expanded array
            n_final = (n//2) * divisions
            cps = array( [points[m,n],points[m+2,n],points[m+2,n+2],points[m,n+2]])
            blended = dot( blend_ramp, cps )
            expanded[ m_final:m_final+divisions, n_final:n_final+divisions] = blended
    
    return expanded

def expand( points, divisions= 10, final_size=None ):
    """Expand bezier control points into the final data-set
    
    points -- array of 2N+1 x 2M+1 x 3 control points
    divisions -- number of divisions for each 3x3 control-point area
    
    return the array 
    """
    M,N,D = points.shape
    
    if final_size is not None:
        d = final_size
    else:
        d = D
    if d < 3:
        raise RuntimeError( "Need at least x,y,z coordinates for points" )
    
    expanded = zeros( (_final_count(M,divisions),_final_count(N,divisions),d), dtype=points.dtype )
    
    # expand control curves in one direction...
    # creates a new points array to be used for other direction...
    # TODO: note: this means that the centre control point is "damped" by the 
    # equations twice, that is, the result of the control point being applied is 
    # the applied as a control point... it seems fine visually, but it may not 
    # be what the modeller intended...
    ws = weight_array( divisions )
    assert len(ws) == divisions, ws
    
    # Index in the control points array
    for m in range( 0, M-1, 2 ):
        # index in the expanded array
        m_final = (m//2) * divisions 
        # Index in the control points array
        for n in range( 0, N-1, 2 ):
            # index in the expanded array
            n_final = (n//2) * divisions
            
            # Now the actual calculations
            # Get the 3 control curves from the control points
            curves = dot( ws, points[m:m+3,n:n+3] )
            # now get final points from the 3 control curves
            verts = dot( ws, curves )
            # And push them into the result array...
            expanded[ m_final:m_final+divisions, n_final:n_final+divisions,:3] = verts

    return expanded

def grid_indices( expanded, offset=0 ):
    """Create indices array to render expanded vertex array
    
    expanded -- MxNx? array of points for which to generate indices
    
    Generates indices to render 2 CCW triangles for each 4-point square in the 
    grid.  Indices use standard numpy ordering, so last dimension (N) varies 
    fastest.
    
    return numpy dtype='i' array
    """
    M,N = expanded.shape[:2]
    quads = (M-1) * (N-1)
    indices = arange( offset, offset+(M*N) ).reshape( (M,N ))
    indices = indices[:-1,:-1] # last row and column should not be start of quads...
    quadbases = ravel( indices ).repeat( 6 )
    
    offsets = tile( array( [0,1,N,N,1,1+N], 'i' ), quads )
    return offsets + quadbases

def _clampz(a):
    """Prevent a from going < 0"""
    if a < 0:
        return 0
    return a
def _clampl( a, length ):
    """Prevent a from going >= length"""
    if a >= length:
        a = length-1 
    return a
def _mag( v ):
    """Calculate magnitude of the vector"""
    return sqrt( sum(v**2) )
def _norm( v ):
    """Normalize the vector"""
    mag = _mag( v )
    if mag != 0:
        return v/_mag(v)
    else:
        return array([0,1,0],'f')
    
def grid_normals( expanded ):
    """Calculate normals for each point in expanded (continuous smoothing)
    
    N[x,y] = cross([x-1,y] -> [x+1,y], [x,y-1]->[x,y+1]) with coords clamped to the array
    """
    M,N = expanded.shape[:2]
    normals = zeros((M,N,3), dtype='f')
    for x in range( M ):
        for y in range( N ):
            x_vec = expanded[_clampl(x+1,M),y] - expanded[ _clampz(x-1),y]
            y_vec = expanded[x,_clampl(y+1,N)] - expanded[ x,_clampz(y-1)]
            normals[x,y] = _norm(cross( x_vec, y_vec ))
    return normals

def grid_texcoords( expanded ):
    """Generate texture coordinates from 0-1.0
    
    expanded -- the MxN array for which to generate
    """
    M,N = expanded.shape[:2]
    tex_coords = zeros( (M,N,2), 'f')
    values = arange( N )/ float(N-1)
    tex_coords[:,:,0] = values 
    values = (arange( M )/ float(M-1)).reshape((-1,1))
    tex_coords[:,:,1] = values 
    return tex_coords
    
