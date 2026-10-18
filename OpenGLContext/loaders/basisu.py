"""Basis Universal textures (KTX 2 and ``.basis``) through the optional opengl_basisu

A Basis Universal file holds its images in an intermediate codec (ETC1S or
UASTC) that transcodes to whichever block format a GPU samples: BC7 or BC1 to
BC5 on desktop, ETC or ASTC on mobile, RGBA8 where there is none. glTF's
``KHR_texture_basisu`` stores its textures this way, and X3D's texture nodes
read the same files by URL.

The transcoder is the separate ``opengl_basisu`` distribution, installed by
``pip install 'OpenGLContext[basisu]'``. Without it, :func:`available` is false
and every entry point raises :class:`BasisTextureError` naming that extra.

This module holds no GL. :func:`open_image` gives a :class:`BasisImage`;
:func:`plan` answers the target format and the mip levels to upload for a
context's :class:`Capabilities`, which :class:`OpenGLContext.texture.BasisTexture`
uploads. :func:`read` answers the pixels the cube-map and volume readers in
:mod:`OpenGLContext.loaders.textureimages` take.
"""
from __future__ import annotations

import functools
import struct
from dataclasses import dataclass, field
from types import ModuleType
from typing import TYPE_CHECKING, Any, Optional

import numpy as np

if TYPE_CHECKING:
    from PIL import Image

__all__ = [
    'EXTRA', 'INSTALL', 'BasisTextureError', 'BasisImage', 'Capabilities', 'Level',
    'available', 'missing_reason', 'is_basis', 'open_image', 'plan', 'read',
]

#: The OpenGLContext extra that installs the transcoder.
EXTRA = 'basisu'
#: The command that installs it.
INSTALL = "pip install 'OpenGLContext[basisu]'"

_KTX2_MAGIC = b'\xabKTX 20\xbb\r\n\x1a\n'
_BASIS_SIGNATURE = b'sB'
#: The size of a ``.basis`` file's header, which it records after its signature.
_BASIS_HEADER_SIZE = 77
#: The KTX 2 Data Format Descriptor colour models of the two Basis codecs.
_KHR_DF_MODEL_ETC1S = 163
_KHR_DF_MODEL_UASTC = 166
#: KTX 2 supercompression schemes: none, BasisLZ (ETC1S), Zstandard (UASTC).
_BASIS_SCHEMES = (0, 1, 2)


class BasisTextureError(ValueError):
    """A Basis Universal file that cannot be read here, with the reason."""


@functools.cache
def _import_transcoder() -> Optional[ModuleType]:
    try:
        import opengl_basisu  # noqa: PLC0415 an optional dependency, imported where it is first asked for
    except ImportError:
        return None
    return opengl_basisu


def _transcoder() -> Optional[ModuleType]:
    """The opengl_basisu module, or None where it is not installed."""
    return _import_transcoder()


def available() -> bool:
    """Whether opengl_basisu is installed, so Basis Universal files are read."""
    return _transcoder() is not None


def missing_reason() -> str:
    """What a Basis Universal file needs that is not installed."""
    return 'Basis Universal textures need opengl_basisu: %s' % (INSTALL,)


def _module() -> ModuleType:
    module = _transcoder()
    if module is None:
        raise BasisTextureError(missing_reason())
    return module


def is_basis(data: bytes) -> bool:
    """Whether ``data`` is a ``.basis`` file or a KTX 2 file with a Basis Universal payload.

    Read from the header and the Data Format Descriptor, so it answers without
    opengl_basisu: ETC1S is ``VK_FORMAT_UNDEFINED`` with BasisLZ
    supercompression, UASTC is ``VK_FORMAT_UNDEFINED`` with the UASTC colour
    model.
    """
    if data[:2] == _BASIS_SIGNATURE:
        # The signature, the version, then the header's own size.
        header_size = int.from_bytes(data[4:6], 'little')
        return _BASIS_HEADER_SIZE <= header_size <= len(data)
    if data[:12] != _KTX2_MAGIC or len(data) < 80:
        return False
    (vk_format,) = struct.unpack_from('<I', data, 12)
    (scheme,) = struct.unpack_from('<I', data, 44)
    if vk_format != 0 or scheme not in _BASIS_SCHEMES:
        return False
    if scheme == 1:
        return True
    dfd_offset, dfd_length = struct.unpack_from('<2I', data, 48)
    # The descriptor's total size, then the basic block's vendor/type word,
    # versions and size, then the colour model as its first byte.
    model_at = dfd_offset + 12
    if dfd_length < 16 or model_at >= len(data):
        return False
    return data[model_at] in (_KHR_DF_MODEL_ETC1S, _KHR_DF_MODEL_UASTC)


@dataclass(frozen=True)
class Capabilities:
    """The compressed formats a context offers: its extensions, version and kind.

    ``version`` is the context's ``(major, minor)``; ``es`` says it is OpenGL
    ES. The default is a context offering no compressed format, which takes
    RGBA8.
    """

    extensions: frozenset[str] = frozenset()
    version: tuple[int, int] = (0, 0)
    es: bool = False


@dataclass(frozen=True)
class Level:
    """One mip level to upload.

    ``compressed`` levels go to ``glCompressedTexImage2D`` with
    ``data.nbytes`` as the image size; the others to ``glTexImage2D`` with
    ``gl_format`` and ``gl_type``, which are 0 for a compressed level.
    """

    level: int
    width: int
    height: int
    internal_format: int
    compressed: bool
    data: np.ndarray
    gl_format: int = 0
    gl_type: int = 0


@dataclass(eq=False)
class BasisImage:
    """One Basis Universal file, opened, in the shape a texture node holds an image in

    ``size`` is level 0's ``(width, height)``, ``mode`` is ``'RGBA'`` where the
    file stores alpha and ``'RGB'`` otherwise, and ``info`` is the dictionary
    the texture cache reads a URL from, as a PIL image's is. ``data`` is the
    file's bytes. :meth:`pil` is level 0 as a PIL image, for what reads pixels
    (a glTF specular-glossiness conversion, a roughness mean, an X3D writer).
    """

    data: bytes
    texture: Any
    info: dict[str, Any] = field(default_factory=dict)
    _pil: Optional[Image.Image] = field(default=None, repr=False)

    @property
    def size(self) -> tuple[int, int]:
        return int(self.texture.width), int(self.texture.height)

    @property
    def levels(self) -> int:
        return int(self.texture.levels)

    @property
    def has_alpha(self) -> bool:
        return bool(self.texture.has_alpha)

    @property
    def srgb(self) -> bool:
        return bool(self.texture.srgb)

    @property
    def mode(self) -> str:
        return 'RGBA' if self.has_alpha else 'RGB'

    def getbands(self) -> tuple[str, ...]:
        """The image's channel names, as PIL's ``getbands`` gives them"""
        return tuple(self.mode)

    def pixels(self, level: int = 0, face: int = 0, layer: int = 0) -> np.ndarray:
        """One image as ``(height, width, 4)`` uint8 RGBA, top row first"""
        try:
            image = self.texture.transcode('rgba8', level=level, face=face, layer=layer)
        except (ValueError, IndexError) as err:
            raise BasisTextureError('a Basis Universal image that does not transcode: %s'
                                    % (err,)) from err
        return np.asarray(image.data)

    def pil(self) -> Image.Image:
        """Level 0 as a PIL image in :attr:`mode`, top row first"""
        if self._pil is None:
            from PIL import Image  # noqa: PLC0415 PIL only for what reads the pixels
            pixels = self.pixels()
            self._pil = Image.fromarray(pixels if self.has_alpha else pixels[..., :3], self.mode)
        return self._pil


def open_image(data: bytes, url: Optional[str] = None) -> BasisImage:
    """The :class:`BasisImage` in ``data``; ``url`` is kept in its ``info``."""
    module = _module()
    try:
        texture = module.open(bytes(data))
    except module.BasisuError as err:
        raise BasisTextureError('a Basis Universal file the transcoder refuses: %s'
                                % (err,)) from err
    if texture.codec.is_hdr:
        raise BasisTextureError('a Basis Universal %s texture is high dynamic range, '
                                'which is not read' % (texture.codec.name,))
    image = BasisImage(bytes(data), texture)
    if url is not None:
        image.info['url'] = url
    return image


def plan(image: BasisImage, capabilities: Capabilities, top_first: bool = True,
         face: int = 0, layer: int = 0) -> tuple[str, list[Level]]:
    """The target format's name and every mip level of one image, to upload

    The target is the best format ``capabilities`` offers for the file's codec
    and alpha (``opengl_basisu.choose_target``). Its enum is the linear one
    for an sRGB file as well: the shaders decode each map's colour space
    themselves. ``top_first`` false is a texture whose first row is t=0 at the
    bottom (VRML97 and X3D), which takes RGBA8 with its rows turned over, as a
    block format's rows cannot be.
    """
    module = _module()
    if top_first:
        target = module.choose_target(
            capabilities.extensions, codec=image.texture.codec, has_alpha=image.has_alpha,
            version=capabilities.version, es=capabilities.es)
    else:
        target = module.Target.RGBA8
    info = target.info
    levels = []
    try:
        transcoded = image.texture.transcode_levels(target, face=face, layer=layer)
    except (ValueError, IndexError) as err:
        raise BasisTextureError('a Basis Universal image that does not transcode: %s'
                                % (err,)) from err
    for found in transcoded:
        data = np.asarray(found.data)
        if not top_first:
            data = np.ascontiguousarray(data[::-1])
        levels.append(Level(found.level, found.width, found.height, info.internal_format(),
                            info.compressed, data, info.gl_format or 0, info.gl_type or 0))
    return str(target.value), levels


def read(data: bytes) -> tuple[str, list[np.ndarray]]:
    """The kind of image a Basis Universal file holds and its pixels, at level 0

    As :func:`OpenGLContext.loaders.textureimages.read_ktx2` answers: a cube
    map is ``'cube'`` and six faces as the file holds them; a 2D array is
    ``'volume'``, its layers the slices, each turned so its first row is t=0;
    anything else is ``'image'``, top row first. Pixels are RGB, or RGBA where
    the file stores alpha.
    """
    image = open_image(data)
    texture = image.texture
    channels = 4 if image.has_alpha else 3

    def pixels(face: int = 0, layer: int = 0) -> np.ndarray:
        return np.ascontiguousarray(image.pixels(face=face, layer=layer)[..., :channels])

    if texture.faces == 6:
        return 'cube', [pixels(face=face) for face in range(6)]
    if texture.is_array and texture.layers > 1:
        return 'volume', [np.ascontiguousarray(
            np.stack([pixels(layer=layer) for layer in range(texture.layers)])[:, ::-1])]
    return 'image', [pixels()]
