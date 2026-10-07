"""VRML97 Background node, with image cube and gradient sphere"""
from typing import Any

from OpenGLContext.scenegraph import cubebackground, spherebackground, imagetexture
from vrml import field
from vrml.vrml97 import basenodes
from vrml.x3d import binding

class SkyAndCube(
    cubebackground._CubeBackground,
    spherebackground._SphereBackground,
):
    """The drawing a Background and a TextureBackground share

    The sky and ground colours on a sphere, then over them each of the six
    sides (``right``, ``left``, ``front``, ``back``, ``top``, ``bottom``) that
    has an image. Only the background bound on its scene's stack draws, and
    only in a pass's first view.
    """
    def Render( self, mode: Any, clear: int = 1 ) -> int:
        """Draw the background with the fixed-function sky; 1 where something was drawn"""
        if mode.passCount != 0 or binding.bound(self) is not self:
            return 0
        drawn = spherebackground._SphereBackground.Render( self, mode, clear=1)
        if self.hasImages():
            drawn = cubebackground._CubeBackground.Render( self, mode, clear=0) or drawn
        return drawn

    def RenderShader( self, mode: Any, clear: int = 1 ) -> int:
        """Draw the background with the shader sky; 1 where something was drawn"""
        if mode.passCount != 0 or binding.bound(self) is not self:
            return 0
        drawn = spherebackground._SphereBackground.RenderShader(self, mode, clear=True)
        if self.hasImages():
            drawn = cubebackground._CubeBackground.Render( self, mode, clear=0) or drawn
        return drawn


class Background(SkyAndCube, basenodes.Background):
    """VRML97-style background node

    The Background node is a rather involved node,
    there are to major sub-categories of functionality:
        CubeBackground -- panoramic image-cube background
        SphereBackground -- gradient sphere background

    OpenGLContext separates at these two types of
    functionality into super-classes of the Background
    node which may be used individually.

    OpenGLContext also allows for transparent images
    in the CubeBackground attributes, which allows the
    gradient sphere behind the images.

    Note:
        To be closer to VRML97, the Background node
        actually uses different fields for the right,
        top, bottom, etceteras fields than those used
        by the cubebackground Node. Each storage name
        is prefixed with a ' '.  This should have
        the effect of not linearising these values
        to VRML97.
    """
    right = field.newField(' right', 'SFNode', default=imagetexture.ImageTexture)
    top = field.newField(' top', 'SFNode', default=imagetexture.ImageTexture)
    back = field.newField(' back', 'SFNode', default=imagetexture.ImageTexture)
    left = field.newField(' left', 'SFNode', default=imagetexture.ImageTexture)
    front = field.newField(' front', 'SFNode', default=imagetexture.ImageTexture)
    bottom = field.newField(' bottom', 'SFNode', default=imagetexture.ImageTexture)
