"""Create PIL images from depth or stencil buffers

This module allows you to capture the current depth
or stencil buffer to a PIL image.  This allows you
to, for instance, save the image to disk and examine
it with an image editor to confirm that the buffer
includes the expected results.
"""
from OpenGL.GL import *
from OpenGLContext.arrays import *
try:
    from PIL import Image
except ImportError, err:
    # old style?
    import Image

def depth(
    x=0,y=0,width=-1,height=-1,
    normalise = 1, flip = 1,
):
    """Get the depth-buffer as a PIL image

        x,y -- start position for the captured rectangle
        width,height -- size of the captured rectangle

    if normalise is true, the image will be
    scaled to make the most-positive (deepest)
    values white and the most-negative (closest)
    values black.

    if flip, then the image will be flipped
    vertically so that it matches the PIL
    conventions instead of the OpenGL conventions.
    """
    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    data = glReadPixelsf(x, y, width, height, GL_DEPTH_COMPONENT)
    data = ravel(data)
    if normalise and data:
        diff = max(data) - min(data)
        data = (data - min(data)) * (255.0/(diff or 1.0))
    data = data.astype( 'b' )
    image = Image.fromstring( "L", (width, height), data )
    if flip:
        image = image.transpose( Image.FLIP_TOP_BOTTOM)
    return image

def stencil(
    x=0,y=0,width=-1,height=-1,
    normalise = 1, flip = 1,
):
    """Get the stencil-buffer as a PIL image

        x,y -- start position for the captured rectangle
        width,height -- size of the captured rectangle

    if normalise is true, the image will be
    scaled to make the most-positive (deepest)
    values white and the most-negative (closest)
    values black.

    if flip, then the image will be flipped
    vertically so that it matches the PIL
    conventions instead of the OpenGL conventions.
    """
    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    data = glReadPixels(0, 0, width, height, GL_STENCIL_INDEX, GL_UNSIGNED_BYTE)
    if flip:
        data = list(data)
        data.reverse()
    data = ravel(data)
    if normalise and data:
        data = data.astype('f')
        diff = float(max(data)) - float(min(data))
        data = (data - min(data)) * (255.0/(diff or 1.0))
    data = data.astype( 'b' )
    image = Image.fromstring( "L", (width, height), data )
    if flip:
        image = image.transpose( Image.FLIP_TOP_BOTTOM)
    return image
    