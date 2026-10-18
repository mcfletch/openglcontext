"""glTF image and texture decoding into ImageDataTexture nodes

Turns a glTF ``texture`` (its ``source`` image, resolved via bufferView, ``data:``
URI or external URI, plus its ``sampler`` wrap/filter enums) into an
:class:`~OpenGLContext.scenegraph.imagedata.ImageDataTexture`, with the sampler
as a ``TextureProperties``, memoising by texture index. Images are normalised to RGBA on decode so grayscale
and luminance-alpha sources sample correctly. A ``KHR_texture_basisu``,
``EXT_texture_avif`` or ``EXT_texture_webp`` image is preferred to the core
``source``, in that order, where it is decoded here (:func:`decodes`): Basis
Universal KTX 2 needs the optional opengl_basisu
(:mod:`OpenGLContext.loaders.basisu`), and becomes a texture uploaded in a
block format the context samples; AVIF and WebP need a Pillow built with them.
An image that does not decode gives way to the next, the core ``source`` last.

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
from OpenGLContext.loaders import basisu
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
    """A PIL image in RGBA of encoded bytes; a Basis Universal file's level 0"""
    from PIL import Image
    if basisu.is_basis(raw):
        return basisu.open_image(raw).pil().convert('RGBA')
    pim: "Image.Image" = Image.open(io.BytesIO(raw))
    # Normalise to RGBA so grayscale (L) and luminance-alpha (LA) images expand
    # to (L,L,L,A) -- otherwise an LA texture samples as (lum, alpha, 0) and a
    # white pixel reads back yellow.
    if pim.mode != 'RGBA':
        pim = pim.convert('RGBA')
    return pim


BASISU_EXTENSION = 'KHR_texture_basisu'

#: The texture extensions whose image a texture prefers to its core ``source``,
#: most preferred first, with the format each names.
IMAGE_EXTENSIONS = ((BASISU_EXTENSION, 'image/ktx2'), ('EXT_texture_avif', 'image/avif'),
                    ('EXT_texture_webp', 'image/webp'))

#: Pillow's name for each format an extension may name.
_PILLOW_FEATURES = {'image/avif': 'avif', 'image/webp': 'webp'}


def decodes(mime_type: str) -> bool:
    """Whether images of ``mime_type`` are decoded here.

    PNG and JPEG always; KTX 2 where opengl_basisu is installed; AVIF and WebP
    where Pillow was built with them.
    """
    if mime_type in ('image/png', 'image/jpeg'):
        return True
    if mime_type == 'image/ktx2':
        return basisu.available()
    feature = _PILLOW_FEATURES.get(mime_type)
    if feature is None:
        return False
    from PIL import features  # noqa: PLC0415 Pillow is imported where an image is read
    return bool(features.check(feature))


def _texture_sources(tex: "pygltflib.Texture") -> list[int]:
    """The image indices a texture's pixels may come from, most preferred first.

    The images the extensions in :data:`IMAGE_EXTENSIONS` name, where that
    format is decoded here: the extension's image is what the author meant,
    and the core ``source`` is the fallback for a reader without it. Then
    ``texture.source``, which a document requiring one of those extensions may
    leave out.
    """
    extensions = getattr(tex, 'extensions', None) or {}
    found = []
    for name, mime_type in IMAGE_EXTENSIONS:
        block = extensions.get(name)
        source = block.get('source') if isinstance(block, dict) else None
        if isinstance(source, int) and not isinstance(source, bool) and decodes(mime_type):
            found.append(source)
    if tex.source is not None and int(tex.source) not in found:
        found.append(int(tex.source))
    return found


def _texture_source(tex: "pygltflib.Texture") -> Optional[int]:
    """The image index a texture's pixels come from first, or None (:func:`_texture_sources`)."""
    sources = _texture_sources(tex)
    return sources[0] if sources else None


def basisu_notice(g: "pygltflib.GLTF2") -> Optional[str]:
    """What a document loses to opengl_basisu not being installed, or None.

    None where the document has no ``KHR_texture_basisu`` texture or the
    transcoder is installed.
    """
    if basisu.available():
        return None
    basis = [tex for tex in (g.textures or [])
             if isinstance((getattr(tex, 'extensions', None) or {}).get(BASISU_EXTENSION), dict)]
    if not basis:
        return None
    fallback = sum(1 for tex in basis if tex.source is not None)
    return ('glTF %s: %s. Of its %d Basis textures, %d are drawn from their fallback '
            'image and %d are not drawn.' % (BASISU_EXTENSION, basisu.missing_reason(),
                                             len(basis), fallback, len(basis) - fallback))


def _decoded_texture(g: "pygltflib.GLTF2", tex: "pygltflib.Texture", resolver: Resolver,
                     what: str = 'image') -> "Optional[Image.Image]":
    """The PIL image of a texture's first source that decodes, or None

    ``what`` names the image in the warning a source that does not decode logs.
    """
    for src in _texture_sources(tex):
        try:
            image = _image_pil(g, src, resolver)
        except Exception as err:
            log.warning("glTF: failed to decode %s %s: %s", what, src, err)
            continue
        if image is not None:
            return image
    return None


def _pil_for_texinfo(g: "pygltflib.GLTF2", info: "Optional[_TexInfo]",
                     resolver: Resolver) -> "Optional[Image.Image]":
    """Decode the PIL image behind a texture-info dict (or None)."""
    if info is None or getattr(info, 'index', None) is None:
        return None
    return _decoded_texture(g, g.textures[info.index], resolver, 'spec/gloss image')


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
    return _decoded_texture(g, g.textures[texture_index], resolver)


VIDEO_EXTENSION = 'EXT_texture_video'

#: A video's file suffix by its MIME type, for one written out of a buffer view.
_VIDEO_SUFFIX = {'video/mp4': '.mp4', 'video/quicktime': '.mov', 'video/webm': '.webm'}


def video_texture(g: "pygltflib.GLTF2", tex: Any, resolver: Resolver) -> Any:
    """The MovieTexture an ``EXT_texture_video`` texture names, or None.

    The extension (Draft; github.com/takahirox/EXT_texture_video) lists the
    document's videos under its root ``extensions`` by ``uri`` or
    ``bufferView`` and ``mimeType``, and a texture names one by ``source``. A
    ``uri`` is resolved under the document's policy; a ``bufferView``'s bytes
    are written once, by their digest, to the asset cache, since the decoder
    reads a movie from a file. The movie loops from the start of the clock.
    None where the texture names no video, or the video is not there, and the
    texture is then drawn from its core ``source``.
    """
    block = (getattr(tex, 'extensions', None) or {}).get(VIDEO_EXTENSION)
    source = block.get('source') if isinstance(block, dict) else None
    root = (getattr(g, 'extensions', None) or {}).get(VIDEO_EXTENSION)
    videos = root.get('videos') if isinstance(root, dict) else None
    if not isinstance(source, int) or isinstance(source, bool) \
            or not isinstance(videos, list) or not 0 <= source < len(videos) \
            or not isinstance(videos[source], dict):
        return None
    video = videos[source]
    try:
        if isinstance(video.get('uri'), str) and not video['uri'].startswith('data:'):
            location = str(resolver.resolve(video['uri']))
        elif isinstance(video.get('bufferView'), int):
            location = _cached_video(bytes(view_bytes(g, video['bufferView'], resolver)),
                                     str(video.get('mimeType') or 'video/mp4'))
        else:
            return None
    except (IOError, ValueError) as err:
        log.warning("glTF %s video %d is not read: %s", VIDEO_EXTENSION, source, err)
        return None
    from OpenGLContext.scenegraph.movietexture import MovieTexture  # noqa: PLC0415 the node imports the video player
    return MovieTexture(url=[location], loop=True)


def _cached_video(data: bytes, mime_type: str) -> str:
    """A path holding ``data``, written to the asset cache once by its digest."""
    import os  # noqa: PLC0415 only a buffered video is written
    from OpenGLContext import atomicfiles  # noqa: PLC0415 as above
    from OpenGLContext.loaders.resolver import default_cache_dir  # noqa: PLC0415 as above
    path = os.path.join(default_cache_dir(), 'gltf-video',
                        hashlib.sha256(data).hexdigest() + _VIDEO_SUFFIX.get(mime_type, '.mp4'))
    if not os.path.isfile(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        atomicfiles.write_bytes(path, data)
    return path


def _texture_holder(g: "pygltflib.GLTF2", texture_index: Optional[int], resolver: Resolver,
                    cache: "dict[int, Optional[ImageDataTexture]]"
                    ) -> Optional[ImageDataTexture]:
    """The texture node at an index, remembered per document by index

    The shader decodes each channel's colour space itself, so one image used
    as a base colour and as a roughness map is one texture. A texture naming
    an ``EXT_texture_video`` video is a MovieTexture (:func:`video_texture`).
    """
    if texture_index is None:
        return None
    if texture_index in cache:
        return cache[texture_index]
    tex = g.textures[texture_index]
    movie = video_texture(g, tex, resolver)
    if movie is not None:
        cache[texture_index] = movie
        return movie  # type: ignore[no-any-return]  # a MovieTexture is drawn as an image texture is
    # glTF sampler wrap/filter enums are GL enums; pass them straight through.
    sampler = None
    if getattr(tex, 'sampler', None) is not None and g.samplers:
        sampler = g.samplers[tex.sampler]
    settings = (getattr(sampler, 'wrapS', None), getattr(sampler, 'wrapT', None),
                getattr(sampler, 'minFilter', None),
                getattr(sampler, 'magFilter', None))
    for src in _texture_sources(tex):
        try:
            holder = _shared_texture(_image_bytes(g, src, resolver), settings)
        except Exception as err:
            log.warning("glTF: failed to decode image %s: %s", src, err)
            continue
        if holder is not None:
            cache[texture_index] = holder
            return holder
    return None


def _shared_texture(raw: Optional[bytes], settings: tuple) -> Optional[ImageDataTexture]:
    """The texture for these bytes with this sampler, decoding it only if new

    Two documents holding the same image get the same texture, which is what
    lets everything drawn with it collapse into one instanced draw. The key is
    the image and its sampler: one wrapped and one clamped are two textures.
    A Basis Universal file's texture holds it as a
    :class:`~OpenGLContext.loaders.basisu.BasisImage`, uploaded compressed.
    """
    if raw is None:
        return None
    key = (hashlib.sha256(raw).digest(),) + settings
    found = _SHARED.get(key)
    if found is not None:
        return found
    image: Any = basisu.open_image(raw) if basisu.is_basis(raw) else _decode(raw)
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
