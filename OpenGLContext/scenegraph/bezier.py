"""Produce Quake3-style Cubic Bezier Splines"""
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

def expand( points, divisions= 10, normals=False, texCoords=False, globalTexCoord=True ):
    """Expand bezier control points into the final data-set
    
    points -- array of 2N+1 x 2M+1 x 3 control points
    divisions -- number of divisions for each 3x3 control-point area
    normals -- if True, auto-generate normals for the array...
    
    return the array 
    """
    def final_count( M ):
        return ((M - 1)//2 * divisions-1) + 1
    M,N,D = points.shape
    
    if D < 3:
        raise RuntimeError( "Need at least x,y,z coordinates for points" )
    d = D
#    if normals:
#        normals = d
#        d += 3
#    if texCoords:
#        texCoords = d
#        d += 2
        
    expanded = zeros( (final_count(M),final_count(N),d), dtype=points.dtype )
    #expanded[::divisions-1,::divisions-1] = points[::2,::2] 
    
    # expand control curves in one direction...
    # creates a new points array to be used for other direction...
    ws = weight_array( divisions )
    assert len(ws) == divisions, ws
    
    for m in range( 0, M-1, 2 ):
        m_final = (m//2) * divisions 
        for n in range( 0, N-1, 2 ):
            n_final = (n//2) * divisions
            curves = dot( ws, points[m:m+3,n:n+3] )
            # now get final points...
            verts = dot( ws, curves )
            expanded[ m_final:m_final+divisions, n_final:n_final+divisions,:3] = verts
    
#    if normals:
#        normal_array = expanded[:,:,normals:normals+3]
#        # Now, we want the normal, take the cross-product of x-1 -> x+1, y-1 -> y+1
#        m_vecs = expanded[1:,:,:3] - expanded[:-1,:,:3]
#        y_vecs = expanded[:,1:,:3] - expanded[:,:-1,:3]
#        cross( m_vecs, y_vecs )
#        N[x,y] = normalized( cross( V[x-1,y] -> V[x+1,y], V[x,y-1],V[x,y+1] ) )
        
    
    return expanded

def fill_normals( expanded, start=3 ):
    for x in range( expanded.shape[0] ):
        for y in range( expanded.shape[1] ):
            expanded[x,y,start:start+3] = normal( expanded, x, y )

def normal( expanded, x,y ):
    x_start = x-1
    if x_start < 0:
        x_start = x
    x_end = x+1
    if x_end >= expanded.shape[0]:
        x_end = x

    y_start = y-1
    if y_start < 0:
        y_start = y
    y_end = y+1
    if y_end >= expanded.shape[1]:
        y_end = y
    
    raw = cross( 
        expanded[x_end,y,:3] - expanded[x_start,y,:3], 
        expanded[x,y_end,:3] - expanded[x,y_start,:3],
    )
    # TODO guard against 0's
    raw /= magnitude( raw )
    return raw

def grid_indices( expanded ):
    """Create indices array to render expanded vertex array
    
    expanded -- MxNx? array of points for which to generate indices
    
    Generates indices to render 2 CCW triangles for each 4-point square in the 
    grid.  Indices use standard numpy ordering, so last dimension (N) varies 
    fastest.
    
    return numpy dtype='i' array
    """
    M,N = expanded.shape[:2]
    quads = (M-1) * (N-1)
    indices = arange( 0, M*N ).reshape( (M,N ))
    indices = indices[:-1,:-1] # last row and column should not be start of quads...
    quadbases = ravel( indices ).repeat( 6 )
    
    offsets = tile( array( [0,1,N,N,1,1+N], 'i' ), quads )
    return offsets + quadbases

def _clampz(a):
    if a < 0:
        return 0
    return a
    
def _clampl( a, length ):
    if a >= length:
        a = length-1 
    return a

def _mag( v ):
    return sqrt( sum(v**2) )
def _norm( v ):
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
