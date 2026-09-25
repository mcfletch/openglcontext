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
as the LDR values it holds. A light whose images cannot all be read is left
out with one warning, and whatever named it lights as though it had not.
"""
from __future__ import annotations

import io
import logging
from typing import Any, List, Optional

import numpy as np

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


def _light(g: Any, entry: Any, resolver: Any) -> Optional[ImageBasedLight]:
    if not isinstance(entry, dict):
        return None
    coefficients = entry.get('irradianceCoefficients')
    mips = entry.get('specularImages')
    if not (isinstance(coefficients, list) and len(coefficients) == 9
            and isinstance(mips, list) and mips):
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
        intensity=float(entry.get('intensity', 1.0)),
        rotation=tuple(float(v) for v in entry.get('rotation', (0.0, 0.0, 0.0, 1.0))),
        irradianceCoefficients=[tuple(float(v) for v in row) for row in coefficients],
        specularImageSize=int(entry.get('specularImageSize', len(specular[0][0]))),
        DEF=str(entry.get('name') or '') or None)


def read_lights(g: Any, resolver: Any) -> List[Optional[ImageBasedLight]]:
    """Every light the document declares, by index; None where one cannot be read."""
    extensions = getattr(g, 'extensions', None) or {}
    block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    entries = block.get('lights') if isinstance(block, dict) else None
    if not isinstance(entries, list):
        return []
    found = []
    for index, entry in enumerate(entries):
        try:
            light = _light(g, entry, resolver)
        except (OSError, ValueError) as error:
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
