"""Equirectangular high-dynamic-range panoramas, whichever format they are in.

An environment panorama lights a scene and is drawn as its sky
(:mod:`OpenGLContext.passes.ibl`, :mod:`OpenGLContext.scenegraph.hdrbackground`).
Two formats carry them:

* Radiance RGBE (``.hdr``, ``.pic``), decoded by :mod:`OpenGLContext.loaders.hdr`
  with numpy alone;
* OpenEXR (``.exr``), read through the OpenEXR project's own bindings, which
  the ``OpenGLContext[exr]`` extra installs.  Every EXR codec is read, PIZ and
  DWA included, in half or full float.

:func:`is_panorama` is the one rule for which sources are panoramas, and
:func:`load_panorama` returns any of them as an ``(H, W, 3)`` ``float32``
array of linear radiance, top row first.
"""
from __future__ import annotations

import os
from typing import Any

import numpy as np

from OpenGLContext.loaders import hdr, resolver

__all__ = ['PANORAMA_SUFFIXES', 'PanoramaError', 'is_panorama', 'load_panorama']

#: The file suffixes read as panoramas, in lower case.
PANORAMA_SUFFIXES = ('.hdr', '.pic', '.exr')


class PanoramaError(ValueError):
    """A file that cannot be read as a colour panorama."""


def _path_of(source: str) -> str:
    """``source`` without a URL's query string or fragment."""
    return source.split('?', 1)[0].split('#', 1)[0]


def is_panorama(source: str | None) -> bool:
    """Whether ``source``, a path or URL, names a panorama by its suffix.

    A URL's query string and fragment are ignored, so a CDN link with
    parameters still matches.
    """
    return bool(source) and _path_of(source or '').lower().endswith(PANORAMA_SUFFIXES)


def load_panorama(path: str, name: str | None = None) -> np.ndarray:
    """A local panorama as an ``(H, W, 3)`` float32 array of linear radiance.

    The suffix of ``name`` picks the decoder, or of ``path`` where no name is
    given: a URL fetched into the cache passes the URL, whose suffix the
    cached file may not keep.  An ``.exr`` needs the OpenEXR bindings, and
    raises :class:`ImportError` naming the extra that installs them where they
    are missing.
    """
    if _path_of(name or path).lower().endswith('.exr'):
        return _load_exr(resolver.contained_source(path))
    return hdr.load_hdr(path)


def _openexr() -> Any:
    try:
        import OpenEXR
    except ImportError as err:
        raise ImportError(
            'reading an OpenEXR panorama needs the OpenEXR bindings: '
            'pip install "OpenGLContext[exr]"') from err
    return OpenEXR


def _load_exr(path: str) -> np.ndarray:
    """The colour of an EXR's first part: R, G and B, or Y as grey."""
    OpenEXR = _openexr()
    if not os.path.isfile(path):
        raise PanoramaError('no such file: %s' % path)
    try:
        with OpenEXR.File(path, separate_channels=True) as image:
            channels = {name: channel.pixels
                        for name, channel in image.channels().items()}
    except (RuntimeError, OSError, ValueError) as err:
        raise PanoramaError('%s is not a readable OpenEXR image: %s'
                            % (path, err)) from err
    if all(name in channels for name in 'RGB'):
        planes = [channels[name] for name in 'RGB']
    elif 'Y' in channels:
        planes = [channels['Y']] * 3
    else:
        raise PanoramaError('%s has no colour channels (R, G, B or Y), only %s'
                            % (path, ', '.join(sorted(channels))))
    return np.ascontiguousarray(np.stack(planes, axis=-1), dtype=np.float32)
