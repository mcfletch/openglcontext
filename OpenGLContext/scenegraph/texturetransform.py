"""VRML97-style TextureTransform node"""
from typing import Any, Optional

from OpenGL.GL import *
from OpenGL.error import GLError
from vrml.vrml97 import basenodes

from OpenGLContext.arrays import array, any, allclose
from math import pi
RADTODEG = 180/pi
NULLSCALE = array([1,1],'d')

class TextureTransform(basenodes.TextureTransform):
    """Texture-transformation node based on the VRML node

    A texture transform should be applied within a block
    that switches to texture-transform mode first, applies
    the change, then switches back.  You should then pop
    the texture-transform stack when you're done.

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#TextureTransform
    """
    def transform( self, mode: Any = None, translate: int = 1,
                   scale: int = 1, rotate: int = 1 ) -> None:
        ''' Perform the actual alteration of the current matrix '''
        if translate and any(self.translation):
            x,y = self.translation
            glTranslatef(x,y,0)
        if (rotate or scale) and any(self.center):
            cx,cy = self.center
            glTranslatef(cx,cy,0)
        if rotate and self.rotation:
            glRotatef( self.rotation * RADTODEG, 0,0,1)
        if scale and not allclose(self.scale, NULLSCALE):
            sx,sy = self.scale
            glScalef( sx,sy,1.0 )
        if (rotate or scale) and any(self.center):
            glTranslatef( -cx,-cy,0)
    def render(
        self,
        mode: Any = None, # the renderpass object
    ) -> Optional[Any]:
        """Render the texture transform

        returns None or the matrix to be restored
        after rendering
        """
        glMatrixMode( GL_TEXTURE )
        try:
            try:
                glPushMatrix()
            except GLError:
                matrix = glGetDoublev( GL_TEXTURE_MATRIX )
                self.transform()
                return matrix
            else:
                self.transform()
                return None
        finally:
            glMatrixMode( GL_MODELVIEW )
    def renderPost( self, token: Any, mode: Any = None ) -> None:
        """Restore the texture-transform matrix"""
        glMatrixMode( GL_TEXTURE )
        try:
            if token is None:
                glPopMatrix()
            else:
                glLoadMatrixd( token )
        finally:
            glMatrixMode( GL_MODELVIEW )