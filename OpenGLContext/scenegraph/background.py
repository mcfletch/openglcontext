"""VRML97 Background node, with image cube and gradient sphere"""
from typing import Any

from OpenGLContext.scenegraph import cubebackground, spherebackground, imagetexture
from vrml import field
from vrml.vrml97 import basenodes
from vrml.x3d import binding

##print 'mros:'
##print basenodes.Background.__mro__
##print cubebackground.CubeBackground.__mro__
##print spherebackground.SphereBackground.__mro__

class SkyAndCube(
    cubebackground._CubeBackground,
    spherebackground._SphereBackground,
):
    """The drawing a Background and a TextureBackground share

    The sky and ground colours on a sphere, then the six sides (``right``,
    ``left``, ``front``, ``back``, ``top``, ``bottom``) as a cube over it once
    every side has an image. Only the background bound on its scene's stack
    draws.
    """
    def Render( self, mode: Any, clear: int = 1 ) -> int:
        """Render the Background

        mode -- the RenderingPass object representing
            the current rendering pass
        clear -- whether or not to do a background
            clear before rendering

        This implementation calls the CubeBackground
        Render method iff one of the image attributes
        has a non-0 component count (has been loaded).

        Note:
            the Background node only renders if the
            mode's passCount == 0


        XXX
            Should optimize whether to render the sphere
            background depending on whether we have all
            of the image's loaded and all are non-Alpha
            (i.e. you can't see the sphere)

        Answers 1 where something was drawn and 0 where nothing was -- what a
        background answers, whichever one it is.
        """
        if mode.passCount == 0:
            if binding.bound(self) is self:
                drawn = spherebackground._SphereBackground.Render( self, mode, clear=1)
                if (
                    self.right.components and
                    self.left.components and
                    self.front.components and
                    self.back.components and
                    self.top.components and
                    self.bottom.components
                ):
                    drawn = cubebackground._CubeBackground.Render( self, mode, clear=0)
                return drawn
        return 0

    def RenderShader( self, mode: Any, clear: int = 1 ) -> int:
        """Render the Background using shader pipeline

        mode -- the RenderingPass object representing
            the current rendering pass
        clear -- whether or not to do a background
            clear before rendering

        This implementation renders the sphere gradient first using
        shaders, then the cube background (which already uses its
        own shader) on top if images are loaded.

        Answers 1 where something was drawn and 0 where nothing was.
        """
        if mode.passCount == 0:
            if binding.bound(self) is self:
                drawn = spherebackground._SphereBackground.RenderShader(
                    self, mode, clear=True)
                if (
                    self.right.components and
                    self.left.components and
                    self.front.components and
                    self.back.components and
                    self.top.components and
                    self.bottom.components
                ):
                    # CubeBackground already uses its own shader implementation
                    drawn = cubebackground._CubeBackground.Render( self, mode, clear=0)
                return drawn
        return 0

    


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
