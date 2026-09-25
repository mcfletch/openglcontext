"""Holder for a single display-list"""
from typing import Optional

from OpenGL.GL import *

from OpenGLContext import contextresources

#: Every display list's name, by the context that made it: a collected
#: holder's list is deleted the next time that context makes a list, and a
#: context that is torn down takes its lists with it.
_LISTS = contextresources.ContextNames(
    '_contextLists', lambda name: glDeleteLists(name, 1))


class DisplayList( object ):
    """Holder for an OpenGL compiled display list

    This object holds onto a display list until the object is collected.  It
    provides start and end methods for the list-definition phase and a default
    call method for execution.

    The list is a name in the context current when the holder is made, and is
    deleted there: once the holder is collected, the next time that context
    makes a list, or when the context is torn down.
    """
    __slots__ = ('list', '_contextLists', '__weakref__')

    #: The list's GL name, or None once it has been released.
    list: Optional[int]

    def __init__( self ) -> None:
        """Initialize the display list

        See:
            glGenLists
        """
        lists = _LISTS.entries(self)
        self.list = glGenLists (1)
        if self.list == 0:
            raise RuntimeError( """Unable to generate a new display-list, context may not support display lists""")
        if lists is not None:
            lists['list'] = self.list
    def start( self, mode: int = GL_COMPILE ) -> None:
        """Start defining the display-list

        mode can be either:
            GL_COMPILE or GL_COMPILE_AND_EXECUTE
        See:
            glNewList
        """
        if self.list is None:
            raise RuntimeError( """Display list has already been released""" )
        glNewList( self.list, mode )
    def end( self ) -> None:
        """Finish defining the display-list

        See:
            glEndList
        """
        glEndList()
    def __call__( self ) -> None:
        """Call (execute) the display-list

        See:
            glCallList
        """
        if self.list is None:
            raise RuntimeError( """Display list has already been released""" )
        glCallList( self.list )
