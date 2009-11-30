"""Holder for a single display-list"""
from OpenGL.GL import *

class DisplayList( object ):
    """Holder for an OpenGL compiled display list

    This object holds onto a display list until the
    object is deleted.  It provides start and end
    methods for the list-definition phase and a
    default call method for execution.
    """
    __slots__ = ('list','__weakref__')
    def __init__( self ):
        """Initialize the display list

        See:
            glGenLists
        """
        self.list = glGenLists (1)
        if self.list == 0:
            raise RuntimeError( """Unable to generate a new display-list, context may not support display lists""")
    def start( self, mode= GL_COMPILE ):
        """Start defining the display-list

        mode can be either:
            GL_COMPILE or GL_COMPILE_AND_EXECUTE
        See:
            glNewList
        """
        glNewList( self.list, mode )
    def end( self ):
        """Finish defining the display-list

        See:
            glEndList
        """
        glEndList()
    def __call__( self ):
        """Call (execute) the display-list

        See:
            glCallList
        """
        glCallList( self.list )
    def __del__( self, glDeleteLists = glDeleteLists ):
        """Clean up the OpenGL display-list resources

        See:
            glDeleteLists
        """
        try:
            if self.list is not None:
                glDeleteLists( self.list, 1 )
            self.list = None
        except AttributeError, err:
            pass

    
        