"""``MSFT_lod``: a node's coarser alternatives, and when each is worth drawing.

A baked level-of-detail chain ships as one glTF. The node carrying the extension
is the finest level, its ``ids`` name the coarser ones in decreasing detail, and
``MSFT_screencoverage`` in the node's ``extras`` says how much of the window each
is worth drawing at. A reader that has never heard of the extension draws the
node it was given, which is the finest -- so the file is correct either way, and
this is what a reader that *has* heard of it does instead.

What the loader builds from that is a
:class:`~OpenGLContext.scenegraph.lod.ScreenCoverageLOD` holding one level per
alternative. The size it judges coverage by comes from the finest level's
``POSITION`` accessor, whose ``min``/``max`` glTF requires: the whole point of a
chain that streams is that a level can be sized, placed and culled without its
geometry being read.

Reference:
    https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Vendor/MSFT_lod
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple

import numpy as np

if TYPE_CHECKING:
    import pygltflib

#: The property the levels are named by, on a node's ``extensions``.
EXTENSION = 'MSFT_lod'
#: The one they are scheduled by, on a node's ``extras``.
COVERAGE = 'MSFT_screencoverage'

#: Where a guessed series starts, and what each further level takes over at.
#: Halving is the shape of a chain whose levels halve, which is what
#: :func:`OpenGLContext.meshlod.build_chain` produces.
FIRST_COVERAGE = 0.5


def alternative_ids(g: "pygltflib.GLTF2") -> set:
    """Every node index some node names as a coarser level of itself.

    A level belongs to the node that lists it. A file may mention one in its
    scene as well -- nothing forbids it -- and drawing it there too would put
    every level of the model on screen at once.
    """
    found: set = set()
    for node in (g.nodes or []):
        extensions = getattr(node, 'extensions', None) or {}
        if isinstance(extensions, dict):
            ids = (extensions.get(EXTENSION) or {}).get('ids') or []
            found.update(int(index) for index in ids)
    return found


def level_ids(extension: Any) -> list:
    """The coarser levels an ``MSFT_lod`` object names, in decreasing detail."""
    if not isinstance(extension, dict):
        return []
    return [int(index) for index in (extension.get('ids') or [])]


def screen_coverage(node: Any, levels: int) -> list:
    """The coverage each of ``levels`` levels takes over at, decreasing.

    The file's own figures where it gave them. The extension calls them a hint
    and a file may leave them out, so a chain that named none is scheduled by
    halving -- ending at zero, because a level a *reader* guessed a threshold
    for must not be the reason something disappears.
    """
    extras = getattr(node, 'extras', None) or {}
    stated = extras.get(COVERAGE) if isinstance(extras, dict) else None
    if stated:
        return [float(value) for value in stated]
    return [FIRST_COVERAGE / (2 ** index) for index in range(levels - 1)] + [0.0]


def mesh_bounds(g: "pygltflib.GLTF2",
                mesh_index: int) -> Optional[Tuple[Sequence[float], float]]:
    """``(centre, radius)`` of a mesh, from what its accessors declare.

    Read from the ``POSITION`` accessors' ``min``/``max`` rather than from the
    vertices, so a level whose bytes have not been fetched can still be placed
    and sized. None where the file declares neither.
    """
    lows: list = []
    highs: list = []
    for primitive in g.meshes[mesh_index].primitives:
        index = getattr(primitive.attributes, 'POSITION', None)
        if index is None:
            continue
        accessor = g.accessors[index]
        if not accessor.min or not accessor.max:
            continue
        lows.append([float(value) for value in accessor.min[:3]])
        highs.append([float(value) for value in accessor.max[:3]])
    if not lows:
        return None
    low = np.asarray(lows, dtype='d').min(axis=0)
    high = np.asarray(highs, dtype='d').max(axis=0)
    centre = (low + high) / 2.0
    return tuple(float(value) for value in centre), float(np.linalg.norm(high - low) / 2.0)
