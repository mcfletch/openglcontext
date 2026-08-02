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
        """Release the display-list, if there is still a context holding it.

        A display list outlives its context whenever the window closes before the
        garbage collector runs -- at interpreter shutdown, or in a test that
        renders into a context it then destroys. ``glDeleteLists`` against a dead
        or absent context raises ``GL_INVALID_OPERATION``, and an exception from
        ``__del__`` cannot propagate: Python prints it to stderr and continues.
        There is nothing to release in that case (the context took its lists with
        it), so the error is genuinely nothing to report -- but it must be caught
        here rather than left to surface as unraisable noise.

        See:
            glDeleteLists
        """
        try:
            if self.list is not None:
                glDeleteLists( self.list, 1 )
            self.list = None
        except AttributeError:
            # Interpreter shutdown has already torn the module's globals down.
            pass
        except Exception:
            # No current context, or one that no longer knows this list.
            self.list = None
