"""glTF image and texture decoding into ImageDataTexture nodes

Turns a glTF ``texture`` (its ``source`` image, resolved via bufferView, ``data:``
URI or external URI, plus its ``sampler`` wrap/filter enums) into an
:class:`~OpenGLContext.scenegraph.imagedata.ImageDataTexture`, with the sampler
as a ``TextureProperties``, memoising by texture index. Images are normalised to RGBA on decode so grayscale
and luminance-alpha sources sample correctly. ``EXT_texture_avif`` and
``EXT_texture_webp`` images are preferred to the core ``source`` where the
installed Pillow decodes the format (:func:`decodes`); ``KHR_texture_basisu``
(KTX2/Basis) is not read, as it needs a GPU-block transcoder Pillow lacks, and a
texture carrying it is drawn from its core ``source``.

``_TexInfo`` / ``_info`` wrap the raw textureInfo dicts that appear inside material
extensions, giving them the ``.index`` / ``.texCoord`` / ``.extensions`` attribute
shape the rest of the loader expects. Pillow is an optional dependency, imported
lazily where a texture is actually decoded.

**One image, loaded twice, is one texture.** A streamed world is hundreds of
files and the tree in one tile is the same tree as the tree in the next: the
same bark, byte for byte, embedded in every tile that has a tree in it. A
texture each would be a hundred copies of one image in video memory -- and,
worse, a hundred *different* textures, which is a hundred draws where there
should be one, since a single draw can bind only one. So textures are keyed on
what is in them, across documents, and held weakly: one nothing is drawing is
one the world has finished with.
"""
from __future__ import annotations

import hashlib
import io
import logging
import weakref
from typing import TYPE_CHECKING, Any, Optional

from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.sampler import sampler_of, texture_properties
from OpenGLContext.loaders.gltf.accessors import view_bytes
from OpenGLContext.loaders.resolver import Resolver, decode_data_uri, resolver_max

if TYPE_CHECKING:
    import pygltflib
    from PIL import Image

log = logging.getLogger(__name__)

#: Textures already loaded, by what is in them and how it is read. Weak, so a
#: world that streams tiles for an hour does not accumulate every image it has
#: ever seen; see :func:`_shared_texture`.
_SHARED: "weakref.WeakValueDictionary[tuple, ImageDataTexture]" = \
    weakref.WeakValueDictionary()


def forget_shared_textures() -> None:
    """Drop the shared-texture table. For a test that wants a clean start."""
    _SHARED.clear()


def shared_texture_count() -> int:
    """How many distinct images are being held."""
    return len(_SHARED)


def _image_bytes(g: "pygltflib.GLTF2", image_index: int,
                 resolver: Resolver) -> Optional[bytes]:
    """The encoded bytes of an image, however the file supplies them."""
    img = g.images[image_index]
    if getattr(img, 'bufferView', None) is not None:
        return bytes(view_bytes(g, img.bufferView, resolver))
    uri = getattr(img, 'uri', None)
    if uri and uri.startswith('data:'):
        return decode_data_uri(uri, resolver_max(resolver))
    if uri:
        fetched = resolver.fetch(uri)
        return None if fetched is None else bytes(fetched)
    return None


def _image_pil(g: "pygltflib.GLTF2", image_index: int,
               resolver: Resolver) -> "Optional[Image.Image]":
    raw = _image_bytes(g, image_index, resolver)
    if raw is None:
        return None
    return _decode(raw)


def _decode(raw: bytes) -> "Optional[Image.Image]":
    from PIL import Image
    pim: "Image.Image" = Image.open(io.BytesIO(raw))
    # Normalise to RGBA so grayscale (L) and luminance-alpha (LA) images expand
    # to (L,L,L,A) -- otherwise an LA texture samples as (lum, alpha, 0) and a
    # white pixel reads back yellow.
    if pim.mode != 'RGBA':
        pim = pim.convert('RGBA')
    return pim


#: The texture extensions whose image a texture prefers to its core ``source``,
#: most preferred first, with the format each names.
IMAGE_EXTENSIONS = (('EXT_texture_avif', 'image/avif'), ('EXT_texture_webp', 'image/webp'))

#: Pillow's name for each format an extension may name.
_PILLOW_FEATURES = {'image/avif': 'avif', 'image/webp': 'webp'}


def decodes(mime_type: str) -> bool:
    """Whether the installed Pillow decodes images of ``mime_type``.

    PNG and JPEG always; AVIF and WebP where Pillow was built with them.
    """
    if mime_type in ('image/png', 'image/jpeg'):
        return True
    feature = _PILLOW_FEATURES.get(mime_type)
    if feature is None:
        return False
    from PIL import features  # noqa: PLC0415 Pillow is imported where an image is read
    return bool(features.check(feature))


def _texture_source(tex: "pygltflib.Texture") -> Optional[int]:
    """The image index a texture's pixels come from, or None.

    The image an ``EXT_texture_avif`` or ``EXT_texture_webp`` extension names,
    where Pillow decodes that format: the extension's image is what the
    author meant, and the core ``source`` is the fallback for a reader without
    it. Otherwise ``texture.source``, which a document requiring one of those
    extensions may leave out. ``KHR_texture_basisu`` is never chosen.
    """
    extensions = getattr(tex, 'extensions', None) or {}
    for name, mime_type in IMAGE_EXTENSIONS:
        block = extensions.get(name)
        source = block.get('source') if isinstance(block, dict) else None
        if isinstance(source, int) and not isinstance(source, bool) and decodes(mime_type):
            return source
    if tex.source is not None:
        return int(tex.source)
    return None


def _pil_for_texinfo(g: "pygltflib.GLTF2", info: "Optional[_TexInfo]",
                     resolver: Resolver) -> "Optional[Image.Image]":
    """Decode the PIL image behind a texture-info dict (or None)."""
    if info is None or getattr(info, 'index', None) is None:
        return None
    src = _texture_source(g.textures[info.index])
    if src is None:
        return None
    try:
        return _image_pil(g, src, resolver)
    except Exception as err:
        log.warning("glTF: failed to decode spec/gloss image %s: %s", src, err)
        return None


def texture_image(g: "pygltflib.GLTF2", texture_index: Optional[int],
                  resolver: Resolver) -> "Optional[Image.Image]":
    """The decoded PIL image behind a ``textures`` index, or None.

    For a consumer that wants the pixels rather than a texture node -- the
    ``OMI_environment_sky`` panorama, which becomes a skybox and an IBL
    environment rather than a material channel.  Returns None for anything that
    will not decode, since a missing sky is not a reason to lose the scene.
    """
    if texture_index is None or not (0 <= texture_index < len(g.textures or [])):
        return None
    src = _texture_source(g.textures[texture_index])
    if src is None:
        return None
    try:
        return _image_pil(g, src, resolver)
    except Exception as err:
        log.warning("glTF: failed to decode image %s: %s", src, err)
        return None


def _texture_holder(g: "pygltflib.GLTF2", texture_index: Optional[int], resolver: Resolver,
                    cache: "dict[int, Optional[ImageDataTexture]]"
                    ) -> Optional[ImageDataTexture]:
    """The texture node at an index, remembered per document by index

    The shader decodes each channel's colour space itself, so one image used
    as a base colour and as a roughness map is one texture.
    """
    if texture_index is None:
        return None
    if texture_index in cache:
        return cache[texture_index]
    tex = g.textures[texture_index]
    src = _texture_source(tex)
    if src is None:
        return None
    # glTF sampler wrap/filter enums are GL enums; pass them straight through.
    sampler = None
    if getattr(tex, 'sampler', None) is not None and g.samplers:
        sampler = g.samplers[tex.sampler]
    settings = (getattr(sampler, 'wrapS', None), getattr(sampler, 'wrapT', None),
                getattr(sampler, 'minFilter', None),
                getattr(sampler, 'magFilter', None))
    try:
        holder = _shared_texture(_image_bytes(g, src, resolver), settings)
    except Exception as err:
        log.warning("glTF: failed to decode image %s: %s", src, err)
        return None
    cache[texture_index] = holder
    return holder


def _shared_texture(raw: Optional[bytes], settings: tuple) -> Optional[ImageDataTexture]:
    """The texture for these bytes with this sampler, decoding it only if new

    Two documents holding the same image get the same texture, which is what
    lets everything drawn with it collapse into one instanced draw. The key is
    the image and its sampler: one wrapped and one clamped are two textures.
    """
    if raw is None:
        return None
    key = (hashlib.sha256(raw).digest(),) + settings
    found = _SHARED.get(key)
    if found is not None:
        return found
    image = _decode(raw)
    if image is None:
        return None
    holder = ImageDataTexture(image=image)
    if any(value is not None for value in settings):
        holder.textureProperties = sampler_properties(*settings)
    _SHARED[key] = holder
    return holder


#: glTF sampler wrap modes (GL enums) as X3D boundary modes.
WRAP_MODES = {33071: 'CLAMP_TO_EDGE', 33648: 'MIRRORED_REPEAT', 10497: 'REPEAT'}
#: glTF sampler filters (GL enums) as X3D texture filters.
FILTERS = {
    9728: 'NEAREST_PIXEL', 9729: 'AVG_PIXEL',
    9984: 'NEAREST_PIXEL_NEAREST_MIPMAP', 9985: 'AVG_PIXEL_NEAREST_MIPMAP',
    9986: 'NEAREST_PIXEL_AVG_MIPMAP', 9987: 'AVG_PIXEL_AVG_MIPMAP',
}


def gl_sampler(texture: Any) -> "dict[str, int]":
    """A texture's sampler as a glTF sampler: GL enums, leaving out glTF's defaults"""
    sampler = sampler_of(texture)
    wraps = {mode: enum for enum, mode in WRAP_MODES.items()}
    wraps['CLAMP'] = 33071
    filters = {name: enum for enum, name in FILTERS.items()}
    entry = {}
    for key, value, table in (('wrapS', sampler['wrap_s'], wraps),
                              ('wrapT', sampler['wrap_t'], wraps),
                              ('minFilter', sampler['minification'], filters),
                              ('magFilter', sampler['magnification'], filters)):
        enum = table.get(value)
        if enum is not None and not (key.startswith('wrap') and enum == 10497):
            entry[key] = enum
    return entry


def sampler_properties(wrap_s: Optional[int], wrap_t: Optional[int],
                       min_filter: Optional[int], mag_filter: Optional[int]) -> Any:
    """A glTF sampler as a TextureProperties node; an absent value is glTF's default"""
    return texture_properties(
        wrap_s=WRAP_MODES.get(wrap_s or 10497, 'REPEAT'),
        wrap_t=WRAP_MODES.get(wrap_t or 10497, 'REPEAT'),
        minification=FILTERS.get(min_filter or 0, 'DEFAULT'),
        magnification=FILTERS.get(mag_filter or 0, 'DEFAULT'),
    )


class _TexInfo(object):
    """Wraps a raw glTF textureInfo dict (as found inside extensions)."""
    def __init__(self, d: Optional[dict]) -> None:
        self.index = d.get('index') if d else None
        self.texCoord = d.get('texCoord', 0) if d else 0
        self.extensions = d.get('extensions') if d else None


def _info(d: Optional[dict]) -> Optional["_TexInfo"]:
    return _TexInfo(d) if d else None
