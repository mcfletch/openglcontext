"""Reading ``EXT_lights_image_based``: environment lighting shipped in the file.

The document-level block holds ``lights``, each a prefiltered specular cube
mip chain (``specularImages``: for each mip, six image indices in the order
+X, -X, +Y, -Y, +Z, -Z), nine spherical-harmonic ``irradianceCoefficients``,
``specularImageSize``, an ``intensity`` and a ``rotation``. A scene selects
one with ``{"light": n}``, and so does a zone's ``extensions`` block
(:mod:`~OpenGLContext.loaders.gltf.zoning`).

Each light is read into an
:class:`~OpenGLContext.scenegraph.imagebasedlight.ImageBasedLight` with its
faces decoded to linear float: a four-channel PNG as RGBD HDR, anything else
as the LDR values it holds. A light whose images cannot all be read, or whose
coefficients are not nine rows of three finite numbers, is left out with one
warning, and whatever named it lights as though it had not. An ``intensity``,
``rotation`` or ``specularImageSize`` that is no finite number of the right
kind is reported and left at its default.
"""
from __future__ import annotations

import io
import logging
import math
from typing import Any, List, Optional, Tuple

import numpy as np

from OpenGLContext.loaders.documentvalues import DocumentValues, bounded
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight, decode_rgbd

log = logging.getLogger(__name__)

__all__ = ['EXTENSION', 'read_lights', 'scene_light']

EXTENSION = 'EXT_lights_image_based'


def _face(g: Any, index: Any, resolver: Any) -> Optional[np.ndarray]:
    from PIL import Image

    from OpenGLContext.loaders.gltf.textures import _image_bytes
    if not isinstance(index, int) or not 0 <= index < len(g.images or []):
        return None
    raw = _image_bytes(g, index, resolver)
    if raw is None:
        return None
    opened = Image.open(io.BytesIO(raw))
    image = opened.convert('RGBA' if opened.mode in ('RGBA', 'LA', 'PA') else 'RGB')
    return decode_rgbd(np.asarray(image)).astype('f4')


def _light(g: Any, entry: Any, resolver: Any,
           values: DocumentValues) -> Optional[ImageBasedLight]:
    if not isinstance(entry, dict):
        return None
    coefficients = _coefficients(entry.get('irradianceCoefficients'))
    mips = entry.get('specularImages')
    if coefficients is None or not (isinstance(mips, list) and mips):
        return None
    specular: List[List[np.ndarray]] = []
    for level in mips:
        if not isinstance(level, list) or len(level) != 6:
            return None
        faces = [_face(g, index, resolver) for index in level]
        if any(face is None for face in faces):
            return None
        specular.append(faces)                            # type: ignore[arg-type]
    return ImageBasedLight(
        specular=specular,
        intensity=values.number(entry.get('intensity'), 1.0,
                                '%s intensity' % (EXTENSION,), minimum=0.0),
        rotation=values.vector(entry.get('rotation'), (0.0, 0.0, 0.0, 1.0),
                               '%s rotation' % (EXTENSION,), length=4),
        irradianceCoefficients=coefficients,
        specularImageSize=values.integer(
            entry.get('specularImageSize'), len(specular[0][0]),
            '%s specularImageSize' % (EXTENSION,), minimum=1),
        DEF=str(entry.get('name') or '') or None)


def _coefficients(raw: Any) -> Optional[List[Tuple[float, ...]]]:
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


def read_lights(g: Any, resolver: Any) -> List[Optional[ImageBasedLight]]:
    """Every light the document declares, by index; None where one cannot be read."""
    extensions = getattr(g, 'extensions', None) or {}
    block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    entries = block.get('lights') if isinstance(block, dict) else None
    if not isinstance(entries, list):
        return []
    found = []
    values = DocumentValues(logger=log)
    for index, entry in enumerate(entries):
        try:
            light = _light(g, entry, resolver, values)
        except Exception as error:
            # Pillow refuses an oversized image with DecompressionBombError,
            # which is neither an OSError nor a ValueError.
            log.warning('%s light %d could not be read: %s', EXTENSION, index, error)
            light = None
        else:
            if light is None:
                log.warning('%s light %d is incomplete; it is left out', EXTENSION, index)
        found.append(light)
    return found


def scene_light(holder_extensions: Any, lights: List[Optional[ImageBasedLight]]
                ) -> Optional[ImageBasedLight]:
    """The light a scene's (or a zone's) ``{"light": n}`` block names, or None."""
    block = holder_extensions.get(EXTENSION) if isinstance(holder_extensions, dict) else None
    if block is None:
        return None
    index = block.get('light') if isinstance(block, dict) else None
    if not isinstance(index, int) or not 0 <= index < len(lights):
        return None
    return lights[index]
