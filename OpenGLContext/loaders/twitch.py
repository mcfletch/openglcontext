"""Quake3 BSP file loading module (lowest abstraction layer)

Written directly from the following:

    http://www.mralligator.com/q3/

Basically just uses numpy record declarations to parse the bsp files
into structured data-arrays...
"""
import numpy, sys, logging 
from OpenGL.arrays import vbo

log = logging.getLogger( __name__ )
filename = 'maps/focal_p132.bsp'
i4 = '<i4'
f4 = '<f4'
TEXTURE_RECORD = numpy.dtype( [
    ('filename','c',64),
    ('flags',i4),
    ('contents',i4),
])
PLANE_RECORD = numpy.dtype( [
    ('normal',f4,3),
    ('distance',f4,1),
] )
NODE_RECORD = numpy.dtype( [
    ('plane',i4,),
    ('children',i4,2),
    ('mins',i4,3),
    ('maxs',i4,3),
] )
LEAF_RECORD = numpy.dtype( [
    ('cluster',i4),
    ('area',i4),
    ('mins',i4,3),
    ('maxs',i4,3),
    ('leafface',i4),
    ('n_leaffaces',i4),
    ('leafbrush',i4),
    ('n_leafbrushes',i4),
] )
MODEL_RECORD = [
    ('mins',f4,3),
    ('maxs',f4,3),
    ('face',i4),
    ('n_faces',i4),
    ('brush',i4),
    ('n_brushes',i4),
]
BRUSH_RECORD = [
    ('brushside',i4),
    ('n_brushsides',i4),
    ('texture',i4),
]
BRUSHSIDE_RECORD = [
    ('plane',i4),
    ('texture',i4),
]
VERTEX_RECORD = [
    ('position',f4,3),
    ('texcoord_surface',f4,2),
    ('texcoord_lightmap',f4,2),
    ('normal',f4,3),
    ('color','B',4),
]
EFFECT_RECORD = [
    ('name','c',64),
    ('brush',i4),
    ('unknown',i4),
]
FACE_RECORD = [
    ('texture',i4),
    ('effect',i4),
    ('type',i4),
    ('vertex',i4),
    ('n_vertices',i4),
    ('meshvert',i4),
    ('n_meshverts',i4),
    ('lm_index',i4),
    ('lm_start',i4,2),
    ('lm_size',i4,2),
    ('lm_origin',f4,3),
    ('lm_vecs_s',f4,3),
    ('lm_vecs_t',f4,3),
    ('normal',f4,3),
    ('size',i4,2),
]
LIGHTMAP_RECORD = [
    ('texture','i1',(128,128,3)),
]
LIGHTVOL_RECORD = [
    ('ambient','i1',3),
    ('directional','i1',3),
    ('dir','i1',2),
]
VISDATA_RECORD_HEADER = [
    ('n_vecs',i4),
    ('sz_vecs',i4),
]

LUMP_ORDER = [
    ('entities','c'),
    ('textures',TEXTURE_RECORD),
    ('planes',PLANE_RECORD),
    ('nodes',NODE_RECORD),
    ('leafs',LEAF_RECORD),
    ('leaffaces',i4),
    ('leafbrushes',i4),
    ('models',MODEL_RECORD),
    ('brushes',BRUSH_RECORD),
    ('brushsides',BRUSHSIDE_RECORD),
    ('vertices',VERTEX_RECORD),
    ('meshverts',i4),
    ('effects',EFFECT_RECORD),
    ('faces',FACE_RECORD),
    ('lightmaps',LIGHTMAP_RECORD),
    ('lightvols',LIGHTVOL_RECORD),
    ('visdata','iio'),
]

def load_visdata( visdata ):
    header = numpy.dtype( VISDATA_RECORD_HEADER )
    result = []
    while len(visdata):
        this_header = visdata[:header.itemsize].view( header )[0]
        n_vecs,sz_vecs = this_header
        size = (n_vecs * sz_vecs)
        end = header.itemsize+size
        vecs = visdata[header.itemsize:end]
        assert len(vecs) == size
        result.append( (n_vecs,sz_vecs,vecs))
        visdata = visdata[end:]
    assert len(result) == 1
    return result[0]

def parse_bsp( array ):
    """Parse a BSP structure for the array 
    
    array -- numpy array with the data to parse...
    
    returns {
        <lump>: <lump_array>,
        for lump,dtype in LUMP_ORDER
    }
    """
    array = array.view( 'c' )
    iarray = array.view( i4 )
    magic = array[:4].tostring()
    assert magic == 'IBSP', magic 
    version = iarray[1]
    assert version == 0x2e, version
    direntries = iarray[2:2+17*2]
    direntries = numpy.reshape( direntries, (17,2))
    model = {}
    for (lump,dtype),(offset,length) in zip( LUMP_ORDER, direntries ):
        data = array[offset:offset+length]
        loader = globals().get( 'load_%s'%(lump,))
        if loader:
            model[lump] = data = loader( data )
        else:
            dtype = numpy.dtype( dtype )
            extra = len(data) % dtype.itemsize
            if extra:
                log.warn( 'Extra data in lump %s: %s bytes', lump, extra )
                data = data[:-extra]
            model[lump] = data = data.view( dtype )
            log.debug( 'Loaded %s %s', data.shape[0], lump )
    return model

class Twitch( object ):
    def __init__( self, model ):
        self.__dict__.update( model )
        self.vertex_vbo = vbo.VBO( self.vertices )
    
    simple_indices_vbo = None
    texture_set = None
    @property
    def simple_faces( self ):
        """Create an index VBO for the indices to render faces of type 1 and 3"""
        if self.simple_indices_vbo is None:
            faces = self.faces
            # for type 1 and 3 we can simply create indices...
            simple_types = numpy.logical_or( self.faces['type'] == 1, self.faces['type'] == 3)
            simple_faces = numpy.compress( simple_types, self.faces )
            # texture counts...
            sortorder = numpy.lexsort( (simple_faces['texture'],) )
            simple_faces = numpy.take( simple_faces, sortorder )
            
            self.texture_set = texture_set = []
            
            simple_index_count = numpy.sum( simple_faces['n_meshverts'] )
            indices = numpy.zeros( (simple_index_count,), 'I4' )
            # ick, should be a fast way to do this...
            starts = simple_faces['meshvert']
            textures = simple_faces['texture']
            stops = simple_faces['meshvert'] + simple_faces['n_meshverts']
            start_indices = simple_faces['vertex']
            current = 0
            texture = None
            for tex,start,stop,index in zip(textures,starts,stops,start_indices):
                if texture != tex:
                    if texture:
                        texture_set.append( (texture,stop))
                    texture = tex
                end = current + (stop-start)
                indices[current:end] = self.meshverts[start:stop] + index
                current = end
            self.simple_indices_vbo= vbo.VBO( indices, target = 'GL_ELEMENT_ARRAY_BUFFER' )
            # for type 2, we need to convert a control surface to a set of indices...
            log.debug( '%s textures used by simple geometry', len(self.texture_set, ))
        return self.simple_indices_vbo
    patch_indices_vbo = None
    @property
    def patch_faces( self ):
        """Create another pair of VBOs for our patch faces
        
        TODO: do the bezier position adjustment (currently just renders 
        the control points)
        
        a, -> [a,b,c],[d,e,f]
            a blend
                b = 1-a
                    x = u**2 * cp[0].x + 2*a*b * cp[1].x + b**2 * cp[2].x
                    y = ...
                    z = ...
            For the second blend, blend the control points...
        """
        if self.patch_indices_vbo is None:
            patch_faces = numpy.compress( self.faces['type'] == 2, self.faces )
            starts = patch_faces['vertex']
            sizes = patch_faces['size']
            patch_count = sum((patch_faces['size'][:,0]//3) * (patch_faces['size'][:,1]//3))
            
            current = 0
            index_pattern = numpy.array( [0,3,1,1,3,4,1,4,5,1,5,2,3,6,7,3,7,4,4,7,8,4,8,5], 'I' )
            indices = numpy.zeros( (patch_count,len(index_pattern)), 'I' )
            #indices[:] = index_pattern
            current = 0
            for (start,size) in zip( starts, sizes):
                patch_indices = numpy.arange( 0,size[0]*size[1], dtype='I' )
                patch_indices += start
                patch_indices = patch_indices.reshape( size )
                
                for i in range( 0, size[0]-1,2 ):
                    column = patch_indices[i:i+3]
                    for j in range( 0, size[1]-1,2):
                        block = column[:,j:j+3]
                        assert block.shape == (3,3), block
                        block = numpy.ravel( block )
                        assert len(block) == 9, block
                        block_expanded = numpy.take( block, index_pattern )
                        indices[current:current+len(block_expanded)] = block_expanded
                        current += len(block_expanded)
            self.patch_indices_vbo = vbo.VBO( patch_indices, target="GL_ELEMENT_ARRAY_BUFFER")
        return self.patch_indices_vbo

def load( filename ):
    array = numpy.memmap( filename, dtype='c', mode='c' )
    return Twitch( parse_bsp( array ) )
    
def main():
    logging.basicConfig( level=logging.DEBUG )
    return load( sys.argv[1] )

if __name__ == "__main__":
    main()
