from vrml import csscolors

class _ColorSystem( object ):
    def __init__( self ):
        """Pull csscolors in as attributes"""
        for name,rgb in csscolors.cssColors.items():
            setattr( self, name, rgb )

color = _ColorSystem()