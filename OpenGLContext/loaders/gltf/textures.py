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
"""
from __future__ import annotations

import io
import logging
from typing import TYPE_CHECKING, Optional

from OpenGLContext.scenegraph.pbrmaterial import PBRTexture
from OpenGLContext.loaders.gltf.accessors import _buffer_bytes
from OpenGLContext.loaders.resolver import Resolver, _decode_data_uri, _resolver_max

if TYPE_CHECKING:
    import pygltflib
    from PIL import Image

log = logging.getLogger(__name__)


def _image_pil(g: "pygltflib.GLTF2", image_index: int,
               resolver: Resolver) -> "Optional[Image.Image]":
    from PIL import Image
    img = g.images[image_index]
    raw = None
    if getattr(img, 'bufferView', None) is not None:
        bv = g.bufferViews[img.bufferView]
        data = _buffer_bytes(g, bv.buffer, resolver)
        start = bv.byteOffset or 0
        raw = data[start:start + bv.byteLength]
    else:
        uri = getattr(img, 'uri', None)
        if uri and uri.startswith('data:'):
            raw = _decode_data_uri(uri, _resolver_max(resolver))
        elif uri:
            raw = resolver.fetch(uri)
    if raw is None:
        return None
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
        return tex.source
    webp = (getattr(tex, 'extensions', None) or {}).get('EXT_texture_webp')
    if webp is not None:
        return webp.get('source')
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


def _texture_holder(g: "pygltflib.GLTF2", texture_index: Optional[int], resolver: Resolver,
                    srgb: bool, cache: dict) -> Optional[PBRTexture]:
    if texture_index is None:
        return None
    if texture_index in cache:
        return cache[texture_index]
    tex = g.textures[texture_index]
    src = _texture_source(tex)
    if src is None:
        return None
    try:
        image = _image_pil(g, src, resolver)
    except Exception as err:
        log.warning("glTF: failed to decode image %s: %s", src, err)
        return None
    # glTF sampler wrap/filter enums are GL enums; pass them straight through.
    sampler = None
    if getattr(tex, 'sampler', None) is not None and g.samplers:
        sampler = g.samplers[tex.sampler]
    holder = PBRTexture(
        image, srgb=srgb,
        wrap_s=getattr(sampler, 'wrapS', None),
        wrap_t=getattr(sampler, 'wrapT', None),
        min_filter=getattr(sampler, 'minFilter', None),
        mag_filter=getattr(sampler, 'magFilter', None),
    ) if image is not None else None
    cache[texture_index] = holder
    return holder


class _TexInfo(object):
    """Wraps a raw glTF textureInfo dict (as found inside extensions)."""
    def __init__(self, d: Optional[dict]) -> None:
        self.index = d.get('index') if d else None
        self.texCoord = d.get('texCoord', 0) if d else 0
        self.extensions = d.get('extensions') if d else None


def _info(d: Optional[dict]) -> Optional["_TexInfo"]:
    return _TexInfo(d) if d else None
