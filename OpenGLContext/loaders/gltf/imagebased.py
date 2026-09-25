"""Reading ``EXT_lights_image_based``: environment lighting shipped in the file.

The document-level block holds ``lights``, each a prefiltered specular cube
mip chain (``specularImages``: for each mip, six image indices in the order
+X, -X, +Y, -Y, +Z, -Z), nine spherical-harmonic ``irradianceCoefficients``,
``specularImageSize``, an ``intensity`` and a ``rotation``. A scene selects
one with ``{"light": n}``, and so does a zone's ``extensions`` block
(:mod:`~OpenGLContext.loaders.gltf.zoning`).

Each light is read into an
:class:`~OpenGLContext.scenegraph.imagebasedlight.ImageBasedLight` when a scene
or a zone first names it, with its faces decoded to linear float: a
four-channel PNG as RGBD HDR, anything else as the LDR values it holds. Each
mip's six faces are square and alike, and each mip is half as wide as the one
before. A light whose images cannot all be read, whose faces break those
rules, or whose coefficients are not nine rows of three finite numbers, is left
out with one warning, and whatever named it lights as though it had not; so
is a scene naming a light the document does not declare. An
``intensity`` or ``rotation`` that is no finite number of the right kind is
reported and left at its default; a ``specularImageSize`` other than the
faces' own width is reported, and the faces are read as they are.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any, Optional

import numpy as np

from OpenGLContext.loaders.documentvalues import DocumentValues, bounded
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight, decode_rgbd

log = logging.getLogger(__name__)

__all__ = ['EXTENSION', 'ImageLights', 'scene_light']

EXTENSION = 'EXT_lights_image_based'


class ImageLights:
    """The document's lights by index, each read the first time it is asked for.

    ``len()`` is how many the document declares. :meth:`light` decodes a
    light's faces when a scene or a zone first names it and keeps the result,
    None included, so a light nothing names is never decoded and one named
    twice is decoded once. An image named by several faces or lights is
    decoded once.
    """

    def __init__(self, g: Any, resolver: Any) -> None:
        extensions = getattr(g, 'extensions', None) or {}
        block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
        entries = block.get('lights') if isinstance(block, dict) else None
        self._g = g
        self._resolver = resolver
        self._entries: list[Any] = entries if isinstance(entries, list) else []
        self._lights: dict[int, Optional[ImageBasedLight]] = {}
        self._images: dict[int, Optional[np.ndarray]] = {}
        self._values = DocumentValues(logger=log)

    def __len__(self) -> int:
        return len(self._entries)

    def light(self, index: int) -> Optional[ImageBasedLight]:
        """The light at ``index``, or None where there is none or it cannot be read."""
        if not 0 <= index < len(self._entries):
            return None
        if index not in self._lights:
            self._lights[index] = self._read(index)
        return self._lights[index]

    def _read(self, index: int) -> Optional[ImageBasedLight]:
        try:
            return self._light(self._entries[index])
        except _Refused as reason:
            log.warning('%s light %d is left out: %s', EXTENSION, index, reason)
        except Exception as error:
            # Pillow refuses an oversized image with DecompressionBombError,
            # and a malformed entry can raise from anywhere in the decode.
            log.warning('%s light %d could not be read: %s', EXTENSION, index, error)
        return None

    def _face(self, index: Any) -> np.ndarray:
        if isinstance(index, bool) or not isinstance(index, int) \
                or not 0 <= index < len(self._g.images or []):
            raise _Refused('image %r is not one of the document\'s images' % (index,))
        if index not in self._images:
            self._images[index] = _decoded(self._g, index, self._resolver)
        face = self._images[index]
        if face is None:
            raise _Refused('image %d cannot be read' % (index,))
        return face

    def _light(self, entry: Any) -> ImageBasedLight:
        if not isinstance(entry, dict):
            raise _Refused('it is not an object')
        coefficients = _coefficients(entry.get('irradianceCoefficients'))
        if coefficients is None:
            raise _Refused('irradianceCoefficients is not nine rows of three numbers')
        mips = entry.get('specularImages')
        if not (isinstance(mips, list) and mips):
            raise _Refused('specularImages is not a list of mips')
        specular: list[list[np.ndarray]] = []
        for level, faces in enumerate(mips):
            if not isinstance(faces, list) or len(faces) != 6:
                raise _Refused('mip %d is not six image indices' % (level,))
            specular.append([self._face(index) for index in faces])
        top = _face_size(specular[0], 0)
        for level, faces in enumerate(specular[1:], 1):
            wanted = max(top >> level, 1)
            if _face_size(faces, level) != wanted:
                raise _Refused('mip %d is not %d pixels across' % (level, wanted))
        stated = self._values.integer(
            entry.get('specularImageSize'), top,
            '%s specularImageSize' % (EXTENSION,), minimum=1)
        if stated != top:
            self._values.warn(
                '%s specularImageSize %d is not the %d pixels its faces are; '
                'the faces are read as they are' % (EXTENSION, stated, top))
        return ImageBasedLight(
            specular=specular,
            intensity=self._values.number(entry.get('intensity'), 1.0,
                                          '%s intensity' % (EXTENSION,), minimum=0.0),
            rotation=self._values.vector(entry.get('rotation'), (0.0, 0.0, 0.0, 1.0),
                                         '%s rotation' % (EXTENSION,), length=4),
            irradianceCoefficients=coefficients,
            specularImageSize=top,
            DEF=str(entry.get('name') or '') or None)


class _Refused(ValueError):
    """Why a light is left out."""


def _decoded(g: Any, index: int, resolver: Any) -> Optional[np.ndarray]:
    """Image ``index`` as linear float: RGBD where it has alpha, else as it is."""
    from PIL import Image

    from OpenGLContext.loaders.gltf.textures import _image_bytes
    raw = _image_bytes(g, index, resolver)
    if raw is None:
        return None
    opened = Image.open(io.BytesIO(raw))
    image = opened.convert('RGBA' if opened.mode in ('RGBA', 'LA', 'PA') else 'RGB')
    return decode_rgbd(np.asarray(image)).astype('f4')


def _face_size(faces: list[np.ndarray], level: int) -> int:
    """How many pixels across one mip's six faces are, all alike and square."""
    sizes = {face.shape[:2] for face in faces}
    if len(sizes) != 1:
        raise _Refused('the faces of mip %d differ in size' % (level,))
    (height, width), = sizes
    if height != width:
        raise _Refused('the faces of mip %d are %dx%d, not square'
                       % (level, width, height))
    return int(width)


def _coefficients(raw: Any) -> Optional[list[tuple[float, ...]]]:
    """Nine rows of three finite numbers, or None."""
    if not isinstance(raw, list) or len(raw) != 9:
        return None
    rows = []
    for row in raw:
        if not isinstance(row, list) or len(row) != 3:
            return None
        numbers = tuple(bounded(value, math.nan) for value in row)
        if not all(math.isfinite(number) for number in numbers):
            return None
        rows.append(numbers)
    return rows


def scene_light(holder_extensions: Any, lights: ImageLights
                ) -> Optional[ImageBasedLight]:
    """The light a scene's (or a zone's) ``{"light": n}`` block names, or None.

    A block naming no light the document declares is reported, and the
    holder is lit as though it had no block.
    """
    block = holder_extensions.get(EXTENSION) if isinstance(holder_extensions, dict) else None
    if block is None:
        return None
    index = block.get('light') if isinstance(block, dict) else None
    if isinstance(index, bool) or not isinstance(index, int) \
            or not 0 <= index < len(lights):
        log.warning('%s names light %r, which the document does not have',
                    EXTENSION, index)
        return None
    return lights.light(index)
