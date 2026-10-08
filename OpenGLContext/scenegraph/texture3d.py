"""X3D's Texturing3D textures: a volume of texels sampled in three dimensions

Each node holds one ``(depth, height, width, channels)`` uint8 volume
(:meth:`_Texture3D.volumeData`), slice r=0 first and row t=0 first in each
slice, and uploads it as a ``GL_TEXTURE_3D``
(:class:`~OpenGLContext.texture.VolumeTexture`) the first time a frame draws
it, kept in the context's cache until the volume or the sampler changes:

- ``PixelTexture3D``: its ``image`` field, the number of components, the
  width, the height and the depth, then the pixels s first, then t, then r,
  each an integer holding its components as bytes, as ``PixelTexture``'s.
- ``ComposedTexture3D``: its ``texture`` field's 2D textures, one slice each;
  a slice of another size than the first is resampled to it, and the slices
  have the first one's channels.
- ``ImageTexture3D``: the first of its ``url`` entries that reads: a DDS or
  KTX volume, an NRRD volume (with its detached data file beside the
  header), or a single picture, which is a volume one slice deep
  (:mod:`OpenGLContext.loaders.textureimages`). Its ``width``, ``height``,
  ``depth`` and ``colorDepth`` outputs are sent when it has read.

A 3D texture is drawn through an appearance's ``texture`` field or a
``MultiTexture`` layer, sampled at the geometry's ``TextureCoordinate3D`` or
``TextureCoordinate4D``, or where there is none at the position across the
geometry's bounding box (:mod:`OpenGLContext.scenegraph.texturelayers`).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import numpy as np
from vrml import cache, field, node
from vrml.x3d import loadsensor
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.imagetexture import ImageURLField, load_first, sfimage_pixels

__all__ = ['VOLUME_KEY', 'ComposedTexture3D', 'ImageTexture3D', 'PixelTexture3D',
           'VolumeField', 'image_array', 'with_channels']

log = logging.getLogger(__name__)

#: The key a node's volume is kept under in vrml's cache.
VOLUME_KEY = 'texture3d-volume'


class VolumeField(field.Field):
    """A field holding a decoded volume: a numpy array, or None"""

    fieldType = 'Volume'

    @classmethod
    def defaultDefault(cls) -> Any:
        return None


def image_array(texture: Any) -> Optional[np.ndarray]:
    """A 2D texture node's pixels as an ``(h, w, c)`` uint8 array, bottom row first

    A PIL image (an ``ImageTexture``, an ``ImageDataTexture``) or an
    ``SFImage`` (a ``PixelTexture``); None for a texture with no pixels yet.
    """
    image = getattr(texture, 'image', None)
    if image is None:
        return None
    if hasattr(image, 'getbands'):
        if image.mode not in ('L', 'LA', 'RGB', 'RGBA'):
            image = image.convert('RGBA' if 'A' in image.getbands() else 'RGB')
        pixels = np.asarray(image)
        pixels = pixels[..., None] if pixels.ndim == 2 else pixels
        # A PIL image is top row first; texture coordinate t=0 is its bottom.
        top_first = bool(getattr(texture, 'TOP_FIRST', False))
        return np.ascontiguousarray(pixels if top_first else pixels[::-1])
    decoded = sfimage_pixels(image, texture)
    if decoded is None:
        return None
    components, width, height, data = decoded
    return np.frombuffer(data, np.uint8).reshape(height, width, components)


class _Texture3D(node.Node):
    """What the three Texturing3D nodes share: a volume, uploaded when drawn"""

    #: The node's fields its volume is made from, watched by the cache.
    VOLUME_FIELDS: tuple[str, ...] = ()

    def buildVolume(self) -> Optional[np.ndarray]:
        """The volume, worked out from the node's fields as they stand"""
        raise NotImplementedError

    def volumeData(self) -> Optional[np.ndarray]:
        """The ``(depth, height, width, channels)`` uint8 volume, or None

        Kept in vrml's cache until a field in :attr:`VOLUME_FIELDS` is set.
        """
        held = cache.CACHE.getData(self, VOLUME_KEY)
        if held is None:
            held = (self.buildVolume(),)
            holder = cache.CACHE.holder(self, held, VOLUME_KEY)
            self.dependVolume(holder)
        found: Optional[np.ndarray] = held[0]
        return found

    def dependVolume(self, holder: Any) -> None:
        """Make ``holder`` clear when anything the volume is made from changes"""
        for name in self.VOLUME_FIELDS:
            holder.depend(self, name)

    def hasAlpha(self) -> bool:
        """Whether the volume has an alpha channel (two or four of them)"""
        volume = self.volumeData()
        return volume is not None and volume.shape[-1] in (2, 4)

    def cached(self, mode: Any = None) -> Any:
        """The volume as a GL 3D texture in ``mode``'s context, or None before it has one

        Uploaded the first time it is asked for, and again after the volume
        or the sampler changes.
        """
        tex = mode.cache.getData(self)
        if tex is not None:
            return tex
        volume = self.volumeData()
        if volume is None:
            return None
        from OpenGLContext.scenegraph.sampler import apply_sampler, sampler_of  # noqa: PLC0415 GL
        from OpenGLContext.texture import VolumeTexture  # noqa: PLC0415 GL only when drawn
        tex = VolumeTexture(volume)
        depth, height, width = volume.shape[:3]
        apply_sampler(tex, sampler_of(self, (width, height, depth)))
        holder = mode.cache.holder(self, tex)
        self.dependVolume(holder)
        for name in ('repeatS', 'repeatT', 'repeatR', 'textureProperties'):
            holder.depend(self, name)
        return tex


class PixelTexture3D(_Texture3D, x3d.PixelTexture3D):
    """X3D's PixelTexture3D: a volume given in the document"""

    VOLUME_FIELDS = ('image',)

    def buildVolume(self) -> Optional[np.ndarray]:
        values = [int(value) for value in self.image]
        if len(values) < 4:
            return None
        components, width, height, depth = values[:4]
        pixels = values[4:]
        if not 1 <= components <= 4 or min(width, height, depth) <= 0:
            return None
        if len(pixels) != width * height * depth:
            log.warning('PixelTexture3D %s holds %d pixels of %dx%dx%d', self,
                        len(pixels), width, height, depth)
            return None
        packed = np.asarray(pixels, dtype=np.int64) & 0xFFFFFFFF
        shifts = np.arange(components - 1, -1, -1, dtype=np.int64) * 8
        channels = ((packed[:, None] >> shifts) & 0xFF).astype(np.uint8)
        return channels.reshape(depth, height, width, components)


class ComposedTexture3D(_Texture3D, x3d.ComposedTexture3D):
    """X3D's ComposedTexture3D: 2D textures stacked into a volume"""

    VOLUME_FIELDS = ('texture',)

    def dependVolume(self, holder: Any) -> None:
        super().dependVolume(holder)
        for child in self.texture:
            if child and isinstance(getattr(type(child), 'image', None), field.Field):
                holder.depend(child, 'image')

    def buildVolume(self) -> Optional[np.ndarray]:
        slices = [image_array(child) for child in self.texture if child]
        slices = [found for found in slices if found is not None]
        if not slices:
            return None
        height, width, channels = slices[0].shape
        from PIL import Image  # noqa: PLC0415 only a slice of another size needs it
        stacked = []
        for pixels in slices:
            pixels = with_channels(pixels, channels)
            if pixels.shape[:2] != (height, width):
                pixels = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(
                    pixels[..., channel])).resize((width, height), Image.Resampling.BILINEAR))
                    for channel in range(channels)], -1)
            stacked.append(pixels)
        return np.ascontiguousarray(np.stack(stacked))


def with_channels(pixels: np.ndarray, channels: int) -> np.ndarray:
    """``pixels`` with ``channels`` channels (1 to 4): grey widened to colour, colour
    averaged to grey, an alpha of 255 added or the alpha dropped"""
    have = pixels.shape[-1]
    if have == channels:
        return pixels
    grey = pixels[..., :1] if have <= 2 else np.round(
        pixels[..., :3].astype(np.float32).mean(-1, keepdims=True)).astype(np.uint8)
    alpha = pixels[..., -1:] if have in (2, 4) else np.full(grey.shape, 255, np.uint8)
    colour = np.repeat(grey, 3, -1) if have <= 2 else pixels[..., :3]
    return {1: grey, 2: np.concatenate([grey, alpha], -1), 3: colour,
            4: np.concatenate([colour, alpha], -1)}[channels]


class ImageTexture3D(_Texture3D, x3d.ImageTexture3D):
    """X3D's ImageTexture3D: a volume read from a file"""

    VOLUME_FIELDS = ('volume',)
    volume = VolumeField(' volume', 1, None)
    url = ImageURLField('url', 1, list)

    def buildVolume(self) -> Optional[np.ndarray]:
        found: Optional[np.ndarray] = self.volume
        return found

    def loadBackground(self, url: Any, contexts: Any = ()) -> Optional[np.ndarray]:
        """Read the first of ``url`` that holds a volume; the volume, or None

        Asks each of ``contexts`` (weak references) for a redraw once it has.
        """
        from OpenGLContext.loaders import textureimages  # noqa: PLC0415 only a load reads files

        def decode(file: Any, base: str) -> np.ndarray:
            return textureimages.read_volume(file.read(), lambda name: _fetch(base, name))
        found = load_first(self, url, decode)
        if found is None:
            loadsensor.set_load_state(self, loadsensor.FAILED)
            log.warning('Unable to load a volume from the url %s for %s', url, self)
            return None
        volume = found[0]
        self.volume = volume
        depth, height, width, channels = volume.shape
        self.width, self.height, self.depth, self.colorDepth = width, height, depth, channels
        loadsensor.set_load_state(self, loadsensor.LOADED)
        for reference in contexts:
            context = reference()
            if context:
                context.triggerRedraw(1)
        return volume

    def _deleteVolume(self) -> None:
        self.volume = None

    #: What deleting ``url`` deletes (:class:`ImageURLField`): the volume.
    image = property(lambda self: self.volume, doc='The volume read from the url',
                     fdel=_deleteVolume)


def _fetch(base: str, name: str) -> bytes:
    """The bytes of ``name`` read relative to ``base``, as a document's url is"""
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 only a load reads files
    found = Loader(name, baseURL=base)
    if not found:
        raise IOError('nothing at %s' % (name,))
    stream = found[2]
    try:
        data: bytes = stream.read()
    finally:
        stream.close()
    return data

