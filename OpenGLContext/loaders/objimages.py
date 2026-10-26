"""The picture arithmetic an OBJ material's maps need, in NumPy and PIL.

An MTL file gives each material property its own map; the engine's
``PhysicalMaterial`` reads roughness from the green channel and metalness from
the blue channel of one texture, opacity from the base colour's alpha, and a
surface's relief as a tangent-space normal map. These functions turn the
separate maps into those. No GL, no scenegraph.

Images are handled as they are stored in the file, first row at the top.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
from PIL import Image

from OpenGLContext.loaders.mtlfile import TextureMap

__all__ = ['alpha_mode', 'channel_values', 'combine_metallic_roughness',
           'looks_like_normal_map', 'normal_from_height', 'with_alpha']

#: The slope a bump map's height step per texel makes, before ``-bm``: a
#: height that changes by 1/4 between neighbouring texels tilts the normal 45
#: degrees.
BUMP_SLOPE = 4.0

#: A mask with at most this fraction of its texels between fully clear and
#: fully opaque is a cutout; antialiased edges are that fraction.
CUTOUT_EDGE_FRACTION = 0.05


def channel_values(image: Image.Image, texture: TextureMap) -> np.ndarray:
    """The values a scalar map holds, ``(height, width)`` float32 from 0 to 1

    The channel is ``texture.channel`` (``r``, ``g``, ``b``, ``m`` for the alpha
    matte), or the luminance where it names none. ``-mm`` is then applied:
    ``base + value * gain``, clipped to the range.
    """
    rgba = np.asarray(image.convert('RGBA'), dtype=np.float32) / 255.0
    index = {'r': 0, 'g': 1, 'b': 2, 'm': 3}.get(texture.channel)
    if index is not None:
        values = rgba[..., index]
    else:
        values = rgba[..., 0] * 0.2126 + rgba[..., 1] * 0.7152 + rgba[..., 2] * 0.0722
    if texture.base != 0.0 or texture.gain != 1.0:
        values = np.clip(texture.base + values * texture.gain, 0.0, 1.0)
    return np.ascontiguousarray(values, dtype=np.float32)


def _resized(values: np.ndarray, size: tuple[int, int]) -> np.ndarray:
    """``values`` resampled to ``size`` (width, height); the array itself where it is that size"""
    if (values.shape[1], values.shape[0]) == size:
        return values
    resampled = Image.fromarray(values, 'F').resize(size, Image.Resampling.BILINEAR)
    return np.asarray(resampled, dtype=np.float32)


def combine_metallic_roughness(roughness: Optional[np.ndarray],
                               metallic: Optional[np.ndarray]) -> Image.Image:
    """glTF's metallic-roughness texture: roughness in green, metalness in blue

    Either may be None, and its channel is then full, so the material's factor
    alone says the value. Maps of different sizes meet at the larger.
    """
    present = [values for values in (roughness, metallic) if values is not None]
    if not present:
        raise ValueError('a metallic-roughness texture needs a roughness or a metallic map')
    width = max(values.shape[1] for values in present)
    height = max(values.shape[0] for values in present)
    packed = np.full((height, width, 3), 255, dtype=np.uint8)
    for channel, values in ((1, roughness), (2, metallic)):
        if values is not None:
            packed[..., channel] = np.rint(_resized(values, (width, height)) * 255.0)
    return Image.fromarray(packed, 'RGB')


def normal_from_height(height: np.ndarray, strength: float) -> Image.Image:
    """A tangent-space normal map from a height map

    ``height`` is ``(rows, columns)`` from 0 to 1 and tiles: an edge's
    neighbour is the opposite edge. Slopes are central differences, scaled by
    ``strength`` times :data:`BUMP_SLOPE`. The result follows glTF's convention,
    green pointing toward +v, which is up the picture.
    """
    along = (np.roll(height, -1, axis=1) - np.roll(height, 1, axis=1)) * 0.5
    down = (np.roll(height, -1, axis=0) - np.roll(height, 1, axis=0)) * 0.5
    scale = strength * BUMP_SLOPE
    normal = np.stack([-along * scale, down * scale, np.ones_like(height)], axis=-1)
    normal /= np.linalg.norm(normal, axis=-1, keepdims=True)
    return Image.fromarray(np.rint((normal * 0.5 + 0.5) * 255.0).astype(np.uint8), 'RGB')


def looks_like_normal_map(image: Image.Image) -> bool:
    """Whether a picture is a tangent-space normal map rather than a height map

    A normal map averages to the violet of an unperturbed normal, (0.5, 0.5, 1),
    and a height map or photograph does not: a grey average has no blue to
    spare.
    """
    small = image.convert('RGB').resize((min(image.width, 64), min(image.height, 64)))
    red, green, blue = np.asarray(small, dtype=np.float32).reshape(-1, 3).mean(axis=0) / 255.0
    return bool(blue > 0.7 and abs(red - 0.5) < 0.12 and abs(green - 0.5) < 0.12)


def alpha_mode(alpha: np.ndarray) -> str:
    """The alpha mode an opacity mask is drawn with

    ``OPAQUE`` where nothing is clear, ``MASK`` for a cutout (leaves, fences:
    texels clear or opaque, with only an antialiased edge between), ``BLEND``
    otherwise. A cutout is drawn without sorting, which blending would need.
    """
    if float(alpha.min()) >= 0.99:
        return 'OPAQUE'
    between = np.count_nonzero((alpha > 0.05) & (alpha < 0.95))
    return 'MASK' if between <= CUTOUT_EDGE_FRACTION * alpha.size else 'BLEND'


def with_alpha(color: Optional[Image.Image], alpha: np.ndarray) -> Image.Image:
    """``color`` as RGBA with ``alpha`` as its alpha channel

    White where there is no colour picture. A mask of another size is resampled
    to the picture's.
    """
    if color is None:
        rgba = np.full((alpha.shape[0], alpha.shape[1], 4), 255, dtype=np.uint8)
    else:
        rgba = np.array(color.convert('RGBA'), dtype=np.uint8)
    mask = _resized(np.ascontiguousarray(alpha, dtype=np.float32), (rgba.shape[1], rgba.shape[0]))
    rgba[..., 3] = np.rint(np.clip(mask, 0.0, 1.0) * 255.0)
    return Image.fromarray(rgba, 'RGBA')
