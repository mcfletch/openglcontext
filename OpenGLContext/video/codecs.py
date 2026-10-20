"""The codecs a recording can be written in, and the names they are asked for by.

A recording is H.264, HEVC, VP9 or AV1, all stored in an MP4 file. Which of them
a machine produces is up to its GPU's encoder; this module only names them, so a
command line can check a spelling before any window opens or any encoder
package is imported.
"""
from __future__ import annotations

__all__ = ['CODECS', 'canonical']

#: The codecs a recording takes, in the names the encoder package uses.
CODECS = ('h264', 'hevc', 'vp9', 'av1')

_ALIASES = {
    'avc': 'h264', 'h.264': 'h264', 'x264': 'h264',
    'h265': 'hevc', 'h.265': 'hevc', 'x265': 'hevc',
}


def canonical(name: str) -> str:
    """The name in :data:`CODECS` that `name` spells, whatever its case.

    ``'h265'`` is HEVC and ``'avc'`` is H.264. Raises :class:`ValueError`
    listing the codecs there are for any other name.
    """
    lowered = name.strip().lower()
    lowered = _ALIASES.get(lowered, lowered)
    if lowered not in CODECS:
        raise ValueError('%r is not a recording codec; the codecs are %s'
                         % (name, ', '.join(CODECS)))
    return lowered
