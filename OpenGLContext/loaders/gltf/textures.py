"""glTF image and texture decoding -> PBRTexture holders.

Turns a glTF ``texture`` (its ``source`` image, resolved via bufferView, ``data:``
URI or external URI, plus its ``sampler`` wrap/filter enums) into a
:class:`~OpenGLContext.scenegraph.pbrmaterial.PBRTexture` the PBR pass can upload,
memoising by texture index. Images are normalised to RGBA on decode so grayscale
and luminance-alpha sources sample correctly. ``EXT_texture_webp`` is honoured
(Pillow decodes WebP); ``KHR_texture_basisu`` (KTX2/Basis) is intentionally not,
as it needs a GPU-block transcoder Pillow lacks.

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
from typing import TYPE_CHECKING, Optional

from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
from OpenGLContext.loaders.gltf.accessors import _buffer_bytes
from OpenGLContext.loaders.resolver import Resolver, _decode_data_uri, _resolver_max

if TYPE_CHECKING:
    import pygltflib
    from PIL import Image

log = logging.getLogger(__name__)

#: Textures already loaded, by what is in them and how it is read. Weak, so a
#: world that streams tiles for an hour does not accumulate every image it has
#: ever seen; see :func:`_shared_texture`.
_SHARED: "weakref.WeakValueDictionary[tuple, PBRTexture]" = \
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
        bv = g.bufferViews[img.bufferView]
        data = _buffer_bytes(g, bv.buffer, resolver)
        start = bv.byteOffset or 0
        return bytes(data[start:start + bv.byteLength])
    uri = getattr(img, 'uri', None)
    if uri and uri.startswith('data:'):
        return _decode_data_uri(uri, _resolver_max(resolver))
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


def _texture_source(tex: "pygltflib.Texture") -> Optional[int]:
    """The image index a texture's pixels come from, or None.

    Normally ``texture.source``. When that is absent, fall back to
    ``EXT_texture_webp`` -- a WebP image is the sole source when the extension is
    *required* (the base ``source`` is then omitted), and Pillow decodes WebP, so
    it loads like any other raster. ``KHR_texture_basisu`` (KTX2/Basis Universal)
    is intentionally *not* consulted: it needs a GPU-block transcoder Pillow lacks.
    """
    if tex.source is not None:
        return int(tex.source)
    webp = (getattr(tex, 'extensions', None) or {}).get('EXT_texture_webp')
    if webp is not None:
        source = webp.get('source')
        return None if source is None else int(source)
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

    For a consumer that wants the pixels rather than a
    :class:`~OpenGLContext.scenegraph.pbrmaterial.PBRTexture` to upload -- the
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
                    srgb: bool, cache: "dict[tuple, Optional[PBRTexture]]"
                    ) -> Optional[PBRTexture]:
    """The texture at an index, read as sRGB or as linear.

    Remembered per document by index *and* colour space: one image serving as
    both a base colour and a roughness map is two textures, because a base
    colour is sRGB and a roughness map is not, and whichever was asked for
    first would otherwise answer for both.
    """
    if texture_index is None:
        return None
    remembered = (texture_index, bool(srgb))
    if remembered in cache:
        return cache[remembered]
    tex = g.textures[texture_index]
    src = _texture_source(tex)
    if src is None:
        return None
    # glTF sampler wrap/filter enums are GL enums; pass them straight through.
    sampler = None
    if getattr(tex, 'sampler', None) is not None and g.samplers:
        sampler = g.samplers[tex.sampler]
    settings = (srgb,
                getattr(sampler, 'wrapS', None), getattr(sampler, 'wrapT', None),
                getattr(sampler, 'minFilter', None),
                getattr(sampler, 'magFilter', None))
    try:
        holder = _shared_texture(_image_bytes(g, src, resolver), settings)
    except Exception as err:
        log.warning("glTF: failed to decode image %s: %s", src, err)
        return None
    cache[remembered] = holder
    return holder


def _shared_texture(raw: Optional[bytes], settings: tuple) -> Optional[PBRTexture]:
    """The texture for these bytes read this way, decoding it only if new.

    Two documents holding the same image get the same texture, which is what
    lets everything drawn with it collapse into one instanced draw. The key is
    the image and *how it is read* -- the same file as a base colour and as a
    roughness map is two textures, because one is sRGB and the other is not,
    and one wrapped and one clamped are two for the same sort of reason.
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
    srgb, wrap_s, wrap_t, min_filter, mag_filter = settings
    holder = PBRTexture(image, srgb=srgb, wrap_s=wrap_s, wrap_t=wrap_t,
                        min_filter=min_filter, mag_filter=mag_filter)
    _SHARED[key] = holder
    return holder


class _TexInfo(object):
    """Wraps a raw glTF textureInfo dict (as found inside extensions)."""
    def __init__(self, d: Optional[dict]) -> None:
        self.index = d.get('index') if d else None
        self.texCoord = d.get('texCoord', 0) if d else 0
        self.extensions = d.get('extensions') if d else None


def _info(d: Optional[dict]) -> Optional["_TexInfo"]:
    return _TexInfo(d) if d else None
