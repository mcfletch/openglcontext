"""Low level testing function (draw a cube)

This module provides a simple function for drawing
a cube.  It is used by various modules for low level
testing purposes (i.e. in module-level rather than
system level tests).

This version was taken from the NeHe tutorials,
to replace the original which did not include
texture coordinate information.
"""
from typing import Callable, Optional

from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array
from OpenGLContext.scenegraph import box

#: The drawing function, built on the first call to suit what the driver offers.
VBO: Optional[Callable[[], None]] = None

def drawCube() -> None:
    """Draw a cube 2,2,2 units centered around the origin"""
    # draw six faces of a cube
    global VBO 
    if VBO is None:
        if vbo.get_implementation():
            # vbo.VBO starts as None and is replaced by whichever
            # implementation the module settles on, so a checker sees the None.
            data = vbo.VBO( array( list(box.yieldVertices( (2,2,2) )), 'f') )  # type: ignore[misc]
            def draw() -> None:
                data.bind()
                try:
                    glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
                    try:
                        # glEnableClientState, not glEnable: the array enables
                        # are client state, and glEnable takes only the
                        # capability enums.  Asked the other way it raises
                        # GL_INVALID_ENUM and the arrays stay switched off, so
                        # the draw that follows reads whatever was enabled
                        # before it.
                        glEnableClientState( GL_VERTEX_ARRAY )
                        glEnableClientState( GL_NORMAL_ARRAY )
                        glEnableClientState( GL_TEXTURE_COORD_ARRAY )
                        glVertexPointer( 3, GL_FLOAT, 32, data+20 )
                        glNormalPointer( GL_FLOAT, 32, data+8 )
                        glTexCoordPointer( 2, GL_FLOAT, 32, data )
                        glDrawArrays( GL_TRIANGLES, 0, 36 )
                    finally:
                        glPopClientAttrib()
                finally:
                    data.unbind()
            VBO = draw 
        else:
            data = array( list(box.yieldVertices( (2,2,2) )), 'f')
            def draw() -> None:
                # No unbind to pair with: this path holds a plain array rather
                # than a buffer object, and nothing was bound to release.
                glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
                try:
                    # interleaved arrays is not 3.1 compatible,
                    # but this is the old-code path...
                    glInterleavedArrays( GL_T2F_N3F_V3F, 0, data )
                    glDrawArrays( GL_TRIANGLES, 0, 36 )
                finally:
                    glPopClientAttrib()
            VBO = draw
    VBO()