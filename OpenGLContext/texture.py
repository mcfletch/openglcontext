"""Resource-manager for textures (with PIL conversions)"""

import numpy as np
from collections.abc import Callable, Iterable, Sequence
from typing import Any, ClassVar, Optional

from OpenGL.GL import *
from OpenGL.GL.ARB import texture_non_power_of_two
from OpenGL.extensions import available
from OpenGLContext import contextresources
from OpenGLContext.arrays import ArrayType
from OpenGLContext.loaders import basisu
from PIL import Image
import weakref
import logging

log = logging.getLogger(__name__)


def _textureDeleter(textureID: int) -> Callable[[Any], None]:
    """Create function to clean up the texture on deletion"""

    def cleanup(ref: Any) -> None:
        if available(glDeleteTextures):
            glDeleteTextures(1, np.array([textureID], dtype=np.uint32))

    return cleanup


class NumpyAdapter(object):
    @classmethod
    def shapeToMode(cls, size: int) -> str:
        return {
            3: "RGB",
            4: "RGBA",
            2: "LA",
            1: "L",
        }[size]

    def __init__(self, array: Any) -> None:
        self.size = array.shape[:-1]
        self.mode = self.shapeToMode(array.shape[-1])
        self.info: dict[str, Any] = {}
        self.array = array

    def tostring(self, *args: Any, **named: Any) -> Any:
        return self.array

    tobytes = tostring

    def resize(self, *args: Any, **named: Any) -> Any:
        raise RuntimeError("""Don't support numpy image resizing""")

    def transpose(self, mode: Any = None) -> 'NumpyAdapter':
        """Null-operation for transpose to allow processing with PIL expecting code"""
        return self


class Texture(object):
    """Holder for an OpenGL compiled texture

    This object holds onto a texture until it
    is deleted.  Provides methods for storing
    raw data or PIL images (store and fromPIL
    respectively)

    Attributes:
        components -- number of components in the image,
            if 0, then there is no currently stored image
        texture -- OpenGL textureID as returned by a call
            to glGenTextures(1), will be freed when the
            Texture object is deleted
        format -- GL_RGB/GL_RGBA/GL_LUMINANCE/GL_LUMINANCE_ALPHA, the format
            the image was read as.  The luminance names describe what a sample
            means -- one channel standing for all three -- rather than what is
            uploaded: a core profile takes neither as a format, so the texture
            holds GL_R8/GL_RG8 and carries the swizzle that makes a sample of
            it (L, L, L, 1) or (L, L, L, A).  See :meth:`store`.
        topFirst -- whether a PIL image's top row is stored first, at t=0.
            VRML97 and X3D put texture coordinate (0, 0) at an image's lower
            left, so their textures store the bottom row first; glTF puts it
            at the upper left.
        target -- the GL texture target the texture is bound to.
    """

    target: int = GL_TEXTURE_2D

    def __init__(self, image: Any = None, format: Optional[int] = None,
                 topFirst: bool = False) -> None:
        """Initialise the texture, if image is not None, store it

        image -- optional PIL image to store
        """
        self.components = 0
        self.format = format
        self.topFirst = topFirst
        self.texture = glGenTextures(1)
        self.cleanup = _textureDeleter(self.texture)
        if image is not None:
            self.fromPIL(image)

    def store(
        self,
        components: int,
        format: int,
        x: int,
        y: int,
        image: Any,
    ) -> None:
        """define the texture's parameters...
            components -- number of components (3 or 4 for
                RGB and RGBA respectively)
            format -- GL_RGB, GL_RGBA, GL_LUMINANCE
            x,y -- dimensions of the image
            image -- string, data in raw (unencoded) format

        See:
            glBindTexture, glPixelStorei, glTexImage2D
        """
        self.components = components
        self.format = format
        # make our ID current
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        # copy the texture into the current texture ID
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        # Use sized internal format for Core Profile compatibility
        # Map format to sized internal format (Core Profile requires explicit sizes)
        internal_format = {
            GL_RGB: GL_RGB8,
            GL_RGBA: GL_RGBA8,
            GL_LUMINANCE: GL_R8,
            GL_LUMINANCE_ALPHA: GL_RG8,
        }.get(format, GL_RGBA8)
        # Map legacy source formats to core-compatible equivalents
        # GL_LUMINANCE and GL_LUMINANCE_ALPHA are not valid source formats in core profile
        source_format = {
            GL_LUMINANCE: GL_RED,
            GL_LUMINANCE_ALPHA: GL_RG,
        }.get(format, format)
        glTexImage2D(
            GL_TEXTURE_2D, 0, internal_format, x, y, 0, source_format, GL_UNSIGNED_BYTE, image
        )
        # A luminance texture means one channel standing for all three, which is
        # what GL_LUMINANCE did and what GL_R8 does not: it samples as
        # (R, 0, 0, 1), so a greyscale light map modulating a surface annihilates
        # its green and blue and leaves it red. The swizzle restores the meaning
        # -- (R, R, R, 1), and (R, R, R, G) where alpha came with it -- for the
        # sized formats a core profile will accept.
        swizzle = {
            GL_LUMINANCE: (GL_RED, GL_RED, GL_RED, GL_ONE),
            GL_LUMINANCE_ALPHA: (GL_RED, GL_RED, GL_RED, GL_GREEN),
        }.get(format)
        if swizzle is not None:
            for parameter, source in zip(
                (GL_TEXTURE_SWIZZLE_R, GL_TEXTURE_SWIZZLE_G,
                 GL_TEXTURE_SWIZZLE_B, GL_TEXTURE_SWIZZLE_A), swizzle):
                glTexParameteri(GL_TEXTURE_2D, parameter, source)
        # Set texture parameters for Core Profile compatibility
        # Without these, the default GL_TEXTURE_MIN_FILTER (GL_NEAREST_MIPMAP_LINEAR)
        # requires mipmaps, which causes the texture to appear black if not generated
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)

    def bind(self) -> 'Texture':
        """Make this the texture bound to ``GL_TEXTURE_2D``, and return it.

        All a shader needs, and all that uploading into the texture needs.
        ``GL_TEXTURE_2D`` as an *enable* switches on a fixed-function texture
        unit, which a core profile does not have; see :meth:`__call__`.
        """
        glBindTexture(GL_TEXTURE_2D, self.texture)
        return self

    def __call__(self) -> 'Texture':
        """Bind the texture and switch the fixed-function texture unit on.

        The compatibility-profile entry point: ``glEnable(GL_TEXTURE_2D)`` is
        what makes the fixed-function pipeline sample from the bound texture,
        and is ``GLError(1280, 'invalid enumerant')`` in a core context.  Code
        that samples through a shader calls :meth:`bind` instead.

        See:
            glBindTexture, glEnable(GL_TEXTURE_2D)
        """
        self.bind()
        glEnable(GL_TEXTURE_2D)
        return self

    __enter__ = __call__

    def __exit__(self, typ: Any, val: Any, tb: Any) -> None:
        """Disable for context-manager behaviour"""
        glDisable(GL_TEXTURE_2D)

    def update(self, lower_left: Sequence[int], size: Sequence[int],
               data: Any) -> Any:
        """Update the texture with new data

        The texture has to have been stored already: the format the update is
        read as is the one the stored image set.
        """
        if self.format is None:
            raise RuntimeError(
                """Cannot update a texture that has had no image stored"""
            )
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        # copy the texture into the current texture ID
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        return glTexSubImage2D(
            GL_TEXTURE_2D,
            0,
            lower_left[0],
            lower_left[1],
            size[0],
            size[1],
            self.format,
            GL_UNSIGNED_BYTE,
            data,
        )

    def fromPIL(self, image: Any) -> int:
        """Automated storage of image data from a PIL Image instance

        Uses the ensureRGB method to convert the image to RGB,
        then ensurePow2 to make the image a valid size for OpenGL,
        then calls self.store(...) with the appropriate arguments.

        Returns the number of components in the image. A Basis Universal
        image (:class:`~OpenGLContext.loaders.basisu.BasisImage`) is stored as
        its level 0 pixels; :class:`BasisTexture` uploads it compressed.
        """
        if isinstance(image, basisu.BasisImage):
            image = image.pil()
        if isinstance(image, ArrayType):
            image = NumpyAdapter(image)
        else:
            image = self.ensureRGB(image)
            image = self.ensurePow2(image)
        components, format = getLengthFormat(image)
        x, y, image = image.size[0], image.size[1], self.pilAsString(image, self.topFirst)
        self.store(
            components,
            format,
            x,
            y,
            image,
        )
        return components

    @staticmethod
    def pilAsString(image: Any, topFirst: bool = False) -> Any:
        """The image's pixels, its bottom row first, or its top row with `topFirst`

        An array is taken as it is.
        """
        return image.tobytes("raw", image.mode, 0, 1 if topFirst else -1)

    def ensureRGB(self, image: Any) -> Any:
        """The PIL image in a mode the texture stores: a palette image as RGB,
        and an image with a transparent colour (a PNG's tRNS chunk) with an
        alpha channel, LA for greyscale and RGBA otherwise

        Any other image is answered as it is.
        """
        if 'transparency' in image.info and image.mode in ("L", "RGB", "P"):
            return image.convert("LA" if image.mode == "L" else "RGBA")
        if image.mode == "P":
            log.info("Paletted image found, converting: %s", image.info)
            image = image.convert("RGB")
        return image

    NPOT_SUPPORT: Optional[bool] = None

    def ensurePow2(self, image: Any) -> Any:
        """Ensure that the PIL image is pow2 x pow2 dimensions

        Note:
            This method will create a _new_ PIL image if
            the image is not a valid size (It will use BICUBIC
            filtering (from PIL) to do the resizing). Otherwise
            just returns the same image object.
        """

        if self.NPOT_SUPPORT is None:
            self.__class__.NPOT_SUPPORT = (
                texture_non_power_of_two.glInitTextureNonPowerOfTwoARB()
            )
            if not self.NPOT_SUPPORT:
                log.warning(
                    "Implementation requires Power-of-Two textures (very old device?)"
                )
        if not self.NPOT_SUPPORT:
            ### Now resize non-power-of-two images...
            # should check whether it needs it first!
            newSize = bestSize(image.size[0]), bestSize(image.size[1])
            if newSize != image.size:
                log.warning(
                    "Non-power-of-2 image %s found resizing: %s",
                    image.size,
                    image.info,
                )
                image = image.resize(newSize, Image.Resampling.BICUBIC)
        return image


#: What each GL context offers for Basis Universal textures, keyed by the
#: context (:func:`~OpenGLContext.contextresources.context_key`) and dropped as
#: it dies.
_CAPABILITIES: dict[contextresources.ContextKey, basisu.Capabilities] = {}


@contextresources.on_context_lost
def _forget_capabilities() -> None:
    """Drop the answer for the context being torn down."""
    _CAPABILITIES.pop(contextresources.context_key(), None)  # type: ignore[arg-type]  # None is never a key and pops nothing


def compressed_capabilities() -> basisu.Capabilities:
    """The current context's extensions, version and kind, asked once per context

    With no context current the answer is a context offering no compressed
    format, and it is not remembered.
    """
    key = contextresources.context_key()
    if key is None:
        return basisu.Capabilities()
    found = _CAPABILITIES.get(key)
    if found is None:
        found = _CAPABILITIES[key] = _query_capabilities()
    return found


def _query_capabilities() -> basisu.Capabilities:
    from OpenGL import extensions as glextensions  # noqa: PLC0415 kept with the one query that needs it
    version = glextensions.GLQuerier.getVersion()
    names = glextensions.GLQuerier.getExtensions() or ()
    text = glGetString(GL_VERSION) or b''
    return basisu.Capabilities(
        frozenset(name.decode('latin-1') if isinstance(name, bytes) else str(name)
                  for name in names),
        (int(version[0]), int(version[1])) if version else (0, 0),
        es=bytes(text).startswith(b'OpenGL ES'),
    )


class BasisTexture(Texture):
    """A 2D texture holding a Basis Universal image in a format the context samples

    The image (:class:`~OpenGLContext.loaders.basisu.BasisImage`) is
    transcoded to the best block format the context's extensions and version
    offer (:func:`compressed_capabilities`), or to RGBA8 where it offers none,
    and every mip level the file holds is uploaded: compressed ones with
    ``glCompressedTexImage2D``. ``mip_levels`` is how many, which tells
    :func:`~OpenGLContext.scenegraph.sampler.apply_sampler` not to generate
    them; ``target_format`` is the format's name (``'bc7'``, ``'rgba8'``).

    ``topFirst`` false, a VRML97 or X3D texture, puts the image's bottom row at
    t=0; a block format's rows cannot be turned over, so that texture is RGBA8.
    The texture is written whole by :meth:`store_basis`; :meth:`update` does
    not apply to it.
    """

    def __init__(self, image: basisu.BasisImage, topFirst: bool = False) -> None:
        super().__init__(topFirst=topFirst)
        self.mip_levels = 0
        self.target_format = ''
        self.store_basis(image)

    def store_basis(self, image: basisu.BasisImage) -> None:
        """Transcode and upload ``image``, replacing whatever the texture held"""
        target, levels = basisu.plan(image, compressed_capabilities(), top_first=self.topFirst)
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        for level in levels:
            if level.compressed:
                # PyOpenGL's wrapper passes the array's byte count as
                # imageSize; its stub lists imageSize as an argument.
                glCompressedTexImage2D(
                    GL_TEXTURE_2D, level.level, level.internal_format, level.width,
                    level.height, 0, level.data)  # type: ignore[call-arg]  # the wrapper computes imageSize
            else:
                glTexImage2D(GL_TEXTURE_2D, level.level, level.internal_format, level.width,
                             level.height, 0, level.gl_format, level.gl_type, level.data)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_BASE_LEVEL, 0)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAX_LEVEL, len(levels) - 1)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER,
                        GL_LINEAR_MIPMAP_LINEAR if len(levels) > 1 else GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        self.mip_levels = len(levels)
        self.target_format = target
        self.components = 4 if image.has_alpha else 3
        # No format to update with: a block format takes no glTexSubImage2D of pixels.
        self.format = None


class CubeTexture(Texture):
    """Texture class for use with Cube samplers"""

    target = GL_TEXTURE_CUBE_MAP

    CUBE_NAME_MAP: ClassVar[dict[str, int]] = {
        "-x": GL_TEXTURE_CUBE_MAP_NEGATIVE_X,
        "+x": GL_TEXTURE_CUBE_MAP_POSITIVE_X,
        "-y": GL_TEXTURE_CUBE_MAP_NEGATIVE_Y,
        "+y": GL_TEXTURE_CUBE_MAP_POSITIVE_Y,
        "-z": GL_TEXTURE_CUBE_MAP_NEGATIVE_Z,
        "+z": GL_TEXTURE_CUBE_MAP_POSITIVE_Z,
    }

    def __init__(self, images: Any = None, format: Optional[int] = None) -> None:
        """Initialise the texture, if image is not None, store it

        images -- optional name:image mapping with keys from
            -x,+y,-y,+y,-z,+z
        """
        super(CubeTexture, self).__init__(format=format)
        if images:
            self.fromPIL(images)

    def fromPIL(self, images: Any) -> int:
        """Construct the texture from PIL/Numpy arrays

        GL takes only square faces of one size, so each PIL image is resampled
        to a square as wide as the largest side among the six. Faces given as
        arrays are taken as they are, and must already be square and one size
        (ValueError otherwise).
        """
        if isinstance(images, dict):
            images = images.items()
        our_images = [
            (k, v) for k, v in images if (k in self.CUBE_NAME_MAP and v is not None)
        ]
        if not len(our_images) == 6:
            raise ValueError("Need six non-null images")
        prepared = []
        for key, image in our_images:
            if isinstance(image, basisu.BasisImage):
                image = image.pil()
            if isinstance(image, ArrayType):
                prepared.append((key, NumpyAdapter(image)))
            else:
                prepared.append((key, self.ensurePow2(self.ensureRGB(image))))
        side = max(max(image.size[0], image.size[1]) for _key, image in prepared)
        components = format = x = y = 0
        final_images = []
        for key, image in prepared:
            if (image.size[0], image.size[1]) != (side, side):
                if isinstance(image, NumpyAdapter):
                    raise ValueError(
                        "Cube map faces given as arrays must be square and one size; "
                        "face %s is %sx%s where another is %sx%s"
                        % (key, image.size[0], image.size[1], side, side))
                image = image.resize((side, side), Image.Resampling.BICUBIC)
            components, format = getLengthFormat(image)
            (
                x,
                y,
            ) = image.size[0], image.size[1]
            # GL lays out a cube map face from its top row
            final_images.append((key, self.pilAsString(image, topFirst=True)))
        self.store(components, format, x, y, final_images)
        return components

    def store(
        self,
        components: int,
        format: int,
        x: int,
        y: int,
        images: Any,
    ) -> None:
        """Store our images in the appropriate format"""
        self.components = components
        self.format = format

        glBindTexture(GL_TEXTURE_CUBE_MAP, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_WRAP_R, GL_CLAMP_TO_EDGE)
        # Use sized internal format for Core Profile compatibility
        internal_format = {
            GL_RGB: GL_RGB8,
            GL_RGBA: GL_RGBA8,
            3: GL_RGB8,
            4: GL_RGBA8,
        }.get(format, GL_RGBA8)
        if isinstance(images, dict):
            images = images.items()
        for key, image in images:
            glTexImage2D(
                self.CUBE_NAME_MAP[key],
                0,
                internal_format,
                x,
                y,
                0,
                format,
                GL_UNSIGNED_BYTE,
                image,
            )

    def bind(self) -> 'CubeTexture':
        """Make this the texture bound to ``GL_TEXTURE_CUBE_MAP``, and return it."""
        glBindTexture(GL_TEXTURE_CUBE_MAP, self.texture)
        return self

    def __call__(self) -> 'CubeTexture':
        """Bind the cube map.

        A cube map is sampled through a shader's sampler, so there is no
        fixed-function unit to enable: binding is the whole operation.

        See:
            glBindTexture
        """
        return self.bind()

    __enter__ = __call__

    def __exit__(self, typ: Any, val: Any, tb: Any) -> None:
        """Disable for context-manager behaviour"""
        # Unbind the texture
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0)


#: Sized internal format, source format and swizzle for 1 to 4 channels of
#: unsigned bytes, under a core profile: one channel is luminance and two are
#: luminance with alpha, as :meth:`Texture.store` reads them.
_CHANNEL_FORMATS: dict[int, tuple[int, int, Optional[tuple[int, int, int, int]]]] = {
    1: (GL_R8, GL_RED, (GL_RED, GL_RED, GL_RED, GL_ONE)),
    2: (GL_RG8, GL_RG, (GL_RED, GL_RED, GL_RED, GL_GREEN)),
    3: (GL_RGB8, GL_RGB, None),
    4: (GL_RGBA8, GL_RGBA, None),
}


class VolumeTexture(Texture):
    """A 3D texture holding a ``(depth, height, width, channels)`` uint8 volume

    The first slice is r=0 and the first row of a slice t=0. One channel is
    luminance and two luminance with alpha, as for a 2D texture. Sampled
    through a shader's ``sampler3D``, or the fixed-function ``GL_TEXTURE_3D``
    unit.
    """

    target = GL_TEXTURE_3D

    def __init__(self, volume: Any = None) -> None:
        super().__init__()
        self.size: tuple[int, int, int] = (0, 0, 0)
        if volume is not None:
            self.store_volume(volume)

    def store_volume(self, volume: Any) -> None:
        """Upload ``volume``, replacing whatever the texture held"""
        volume = np.ascontiguousarray(volume, dtype=np.uint8)
        if volume.ndim == 3:
            volume = volume[..., None]
        depth, height, width, channels = volume.shape
        internal, source, swizzle = _CHANNEL_FORMATS[channels]
        self.components = channels
        self.format = source
        self.size = (width, height, depth)
        glBindTexture(GL_TEXTURE_3D, self.texture)
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1)
        glTexImage3D(GL_TEXTURE_3D, 0, internal, width, height, depth, 0, source,
                     GL_UNSIGNED_BYTE, volume)
        if swizzle is not None:
            for parameter, value in zip(
                    (GL_TEXTURE_SWIZZLE_R, GL_TEXTURE_SWIZZLE_G,
                     GL_TEXTURE_SWIZZLE_B, GL_TEXTURE_SWIZZLE_A), swizzle):
                glTexParameteri(GL_TEXTURE_3D, parameter, value)
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        for wrap in (GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TEXTURE_WRAP_R):
            glTexParameteri(GL_TEXTURE_3D, wrap, GL_CLAMP_TO_EDGE)

    def bind(self) -> 'VolumeTexture':
        """Make this the texture bound to ``GL_TEXTURE_3D``, and return it."""
        glBindTexture(GL_TEXTURE_3D, self.texture)
        return self

    def __call__(self) -> 'VolumeTexture':
        """Bind the volume and switch the fixed-function 3D texture unit on."""
        self.bind()
        glEnable(GL_TEXTURE_3D)
        return self

    __enter__ = __call__

    def __exit__(self, typ: Any, val: Any, tb: Any) -> None:
        glDisable(GL_TEXTURE_3D)


class MMTexture(Texture):
    """Mip-mapped texture object

    Note: You'll want your images to use
    minFilter = GL_LINEAR_MIPMAP_NEAREST
    to actually see any effect from using a
    MMTexture.
    """

    def store(
        self,
        components: int,
        format: int,
        x: int,
        y: int,
        image: Any,
    ) -> None:
        """Store the image as :meth:`Texture.store` does, and its mipmap chain

        See:
            glGenerateMipmap
        """
        super().store(components, format, x, y, image)
        glGenerateMipmap(GL_TEXTURE_2D)

    def ensurePow2(self, image: Any) -> Any:
        """Return the image unchanged: a texture of any size has mipmaps."""
        return image


def getLengthFormat(image: Any) -> tuple[int, int]:
    """Return PIL image component-length and format

    This returns the number of components, and the OpenGL
    mode constant describing the PIL image's format.  It
    currently only supports GL_RGBA, GL_RGB and GL_LUMINANCE
    formats (PIL: RGBA, RGBX, RGB, and L), the Texture
    object's ensureRGB converts Paletted images to RGB
    before they reach this function.
    """
    if image.mode == "RGB":
        length = 3
        format = GL_RGB
    elif image.mode in ("RGBA", "RGBX"):
        length = 4
        format = GL_RGBA
    elif image.mode == "L":
        length = 1
        format = GL_LUMINANCE
    elif image.mode == "LA":
        length = 2
        format = GL_LUMINANCE_ALPHA
    else:
        raise TypeError(
            "Currently only support Luminance, RGB and RGBA images. Image is type %s"
            % image.mode
        )
    return length, format


def bestSize(dim: int) -> int:
    """Try to figure out the best power-of-2 size for the given dimension

    At the moment, this is the next-largest power-of-two
    which is also <= glGetIntegerv( GL_MAX_TEXTURE_SIZE ).
    """
    boundary = min((int(glGetIntegerv(GL_MAX_TEXTURE_SIZE)), dim))
    test = 1
    while test < boundary:
        test = test * 2
    return test
