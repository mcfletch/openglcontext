"""VRML97 Background node, with image cube and gradient sphere"""
from OpenGLContext.scenegraph import cubebackground, spherebackground, imagetexture
from vrml import field
from vrml.vrml97 import basenodes

##print 'mros:'
##print basenodes.Background.__mro__
##print cubebackground.CubeBackground.__mro__
##print spherebackground.SphereBackground.__mro__

class Background(
    cubebackground._CubeBackground,
    spherebackground._SphereBackground,
    basenodes.Background,
):
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
    def Render( self, mode, clear = 1 ):
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
        """
        if mode.passCount == 0:
            if self.bound:
                spherebackground._SphereBackground.Render( self, mode, clear=1)
                if (
                    self.right.components or
                    self.left.components or
                    self.front.components or
                    self.back.components or
                    self.top.components or
                    self.bottom.components
                ):
                    cubebackground._CubeBackground.Render( self, mode, clear=0)

    