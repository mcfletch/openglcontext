"""Create PIL images from depth or stencil buffers

This module allows you to capture the current depth
or stencil buffer to a PIL image.  This allows you
to, for instance, save the image to disk and examine
it with an image editor to confirm that the buffer
includes the expected results.
"""
from typing import Any, Tuple

from OpenGL.GL import *
from OpenGLContext.arrays import *
from PIL import Image


def _rectangle(x: int, y: int, width: int, height: int) -> Tuple[int, int]:
    """Fill in a negative width or height from the current viewport"""
    if width >= 0 and height >= 0:
        return width, height
    viewport = glGetIntegerv(GL_VIEWPORT)
    if width < 0:
        width = int(viewport[2]) - x
    if height < 0:
        height = int(viewport[3]) - y
    return width, height


def _image(
    values: Any,
    width: int,
    height: int,
    normalise: bool,
    flip: bool,
    scale: float,
) -> Image.Image:
    """Turn a buffer of floats into an 8-bit greyscale image

    ``scale`` maps an un-normalised value onto the 0-255 the image holds; it is
    255 for a buffer whose values run 0-1 and 1 for one already in bytes.
    """
    values = ravel(asarray(values, 'f'))
    if normalise and len(values):
        low, high = float(values.min()), float(values.max())
        values = (values - low) * (255.0 / ((high - low) or 1.0))
    else:
        values = values * scale
    pixels = clip(values, 0, 255).astype('B')
    image = Image.frombytes("L", (width, height), pixels.tobytes())
    if flip:
        # GL numbers rows from the bottom of the buffer, PIL from the top.
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return image


def depth(
    x: int = 0,
    y: int = 0,
    width: int = -1,
    height: int = -1,
    normalise: bool = True,
    flip: bool = True,
) -> Image.Image:
    """Get the depth-buffer as a PIL image

        x,y -- start position for the captured rectangle
        width,height -- size of the captured rectangle; a negative one is the
            rest of the viewport from x,y

    if normalise is true, the image will be
    scaled to make the most-positive (deepest)
    values white and the most-negative (closest)
    values black.  Otherwise the depth buffer's own
    0-1 range is what spans black to white.

    if flip, then the image will be flipped
    vertically so that it matches the PIL
    conventions instead of the OpenGL conventions.
    """
    width, height = _rectangle(x, y, width, height)
    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    data = glReadPixels(x, y, width, height, GL_DEPTH_COMPONENT, GL_FLOAT)
    return _image(data, width, height, normalise, flip, 255.0)


def stencil(
    x: int = 0,
    y: int = 0,
    width: int = -1,
    height: int = -1,
    normalise: bool = False,
    flip: bool = True,
) -> Image.Image:
    """Get the stencil-buffer as a PIL image

        x,y -- start position for the captured rectangle
        width,height -- size of the captured rectangle; a negative one is the
            rest of the viewport from x,y

    A stencil index is already a byte, so by default it is the pixel value.
    if normalise is true, the image is instead scaled to make the largest
    index white and the smallest black, which is what makes a buffer using
    only the low indices visible.

    if flip, then the image will be flipped
    vertically so that it matches the PIL
    conventions instead of the OpenGL conventions.
    """
    width, height = _rectangle(x, y, width, height)
    glPixelStorei(GL_PACK_ALIGNMENT, 1)
    data = glReadPixels(x, y, width, height, GL_STENCIL_INDEX, GL_FLOAT)
    return _image(data, width, height, normalise, flip, 1.0)
