from OpenGLContext.arrays import *
from OpenGLContext import triangleutilities

__all__ = ('mag','mag2','norm','cross','vector')

def _itemAccess( index, name ):
    def get_x( client ):
        return getattr( client, name)[index]
    def set_x( client, value ):
        base = getattr( client, name)
        base[index] = value
        setattr( client, name, base )
    return property( get_x,set_x, doc="""Get/Set item %i of %r for the client"""%(index,name))

def mag( sequence ):
    """Get magnitude for vector sequence"""
    return sqrt( mag2(sequence) )
def mag2( sequence ):
    """Get magnitude squared for vector sequence"""
    sequence *= sequence
    return sum( sequence )
def norm( sequence ):
    """Get normalised vector for vector sequence"""
    return vector( sequence / mag(sequence))
def cross( first, second ):
    """Get cross-product of two vectors"""
    return vector( triangleutilities.crossProduct( first, second ))


class vector(object):
    def __init__( self, x=0.0,y=None,z=None ):
        """Initialise the vector with a set of items"""
        if y is None or z is None:
            if isinstance( x, vector ):
                x = x._base
            if isinstance( x, (list,tuple,ArrayType)):
                value = asarray(ravel( x ),'d')[:3]
            elif isinstance( x, (int,long,float)):
                value = array((x,y or 0.0,z or 0.0),'d')
            else:
                raise TypeError( """Don't know how to convert %r to a vector type"""%(x,))
        else:
            value = asarray( (x,y,z), 'd' )
        self._base = value
    def __nonzero__( self ):
        """Is the vector non-null"""
        return len(self._base) > 0

    x = _itemAccess( 0, '_base' )
    y = _itemAccess( 1, '_base' )
    z = _itemAccess( 2, '_base' )
    w = _itemAccess( 3, '_base' )

    def __iter__( self ):
        return iter( self._base )
    def __getitem__( self, index ):
        return self._base[index]
    def __setitem__( self, index, value ):
        self._base[index] = value

    def _onBase( func ):
        def x( self, *args ):
            """Perform given function on our base and other"""
            return func( self._base, *args )
        return x
    def _onBaseR( func ):
        def x( self, other, *args ):
            """Perform given function on our base and other"""
            return func( other, self._base, *args )
        return x
    mag = _onBase( mag )
    mag2 = _onBase( mag2 )
    norm = _onBase( norm )
    cross = _onBase( cross )
    
    __abs__ = _onBase( fabs )
    __add__ = _onBase( add )
    __cmp__ = _onBase( allclose )
    __div__ = _onBase( divide_safe )
    __floordiv__ = _onBase( floor_divide )
    __mod__ = _onBase( remainder )
    __mul__ = _onBase( multiply )
    __neg__ = _onBase( negative )
    __pow__ = _onBase( power )
    __repr__ = _onBase( repr )
    __str__ = _onBase( str )
    __sub__ = _onBase( subtract )
    __truediv__ = _onBase( true_divide )
    __len__ = _onBase( len )
    __list__ = _onBase( list )

    # reverse functions...
    __radd__ = _onBaseR( add )
    __rdiv__ = _onBaseR( divide_safe )
    __rfloordiv__ = _onBaseR( floor_divide )
    __rmod__ = _onBaseR( remainder )
    __rmul__ = _onBaseR( multiply )
    __rpow__ = _onBaseR( power )
    __rsub__ = _onBaseR( subtract )
    __rtruediv__ = _onBaseR( true_divide )

    del _onBase
    del _onBaseR