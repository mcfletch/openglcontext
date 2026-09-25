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

Which end of the chain the file's own node is at is the thing to get wrong, so
in the specification's words: "The ``node`` object with the extension is the
highest LOD level", "each value in the array points to a LOD level that is lower
in quality than the previous level", and a client without the extension loads
"the highest LOD level" and ignores the rest. Where a level's *bytes* live is a
separate question -- a baked chain keeps the coarsest inside the glb and each
finer one in a sidecar -- and says nothing about which node carries the
extension.

Reference:
    https://github.com/KhronosGroup/glTF/tree/main/extensions/2.0/Vendor/MSFT_lod
"""
from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.loaders.documentvalues import DocumentValues
from OpenGLContext.loaders.gltf.accessors import declared_bounds

if TYPE_CHECKING:
    import pygltflib

log = logging.getLogger(__name__)

#: The property the levels are named by, on a node's ``extensions``.
EXTENSION = 'MSFT_lod'
#: The one they are scheduled by, on a node's ``extras``.
COVERAGE = 'MSFT_screencoverage'

#: Where a guessed series starts, and what each further level takes over at.
#: Halving is the shape of a chain whose levels halve, which is what
#: ``OpenGLContext_editor.meshlod.build_chain`` produces.
FIRST_COVERAGE = 0.5


def alternative_ids(g: "pygltflib.GLTF2",
                    values: Optional[DocumentValues] = None) -> set:
    """Every node index some node names as a coarser level of itself.

    A level belongs to the node that lists it. A file may mention one in its
    scene as well -- nothing forbids it -- and drawing it there too would put
    every level of the model on screen at once.
    """
    values = values if values is not None else DocumentValues(logger=log)
    found: set = set()
    for index, node in enumerate(g.nodes or []):
        extensions = getattr(node, 'extensions', None) or {}
        if isinstance(extensions, dict):
            found.update(level_ids(extensions.get(EXTENSION), values, own=index))
    return found


def level_ids(extension: Any, values: Optional[DocumentValues] = None,
              own: Optional[int] = None) -> list:
    """The coarser levels an ``MSFT_lod`` object names, in decreasing detail.

    An extension that is no object names none, and an id that is no node
    index is reported and passed over. So is ``own``, the index of the node
    carrying the extension: a node is not a coarser level of itself, and
    counting it as one would take it out of the scene.
    """
    if extension is None:
        return []
    values = values if values is not None else DocumentValues(logger=log)
    if not isinstance(extension, dict):
        values.warn('%s is %r, which is not an object; the node is drawn at its '
                    'finest level' % (EXTENSION, extension))
        return []
    ids = extension.get('ids') or []
    if not isinstance(ids, list):
        values.warn('%s ids is %r, which is not a list; the node is drawn at its '
                    'finest level' % (EXTENSION, ids))
        return []
    found = []
    for raw in ids:
        index = values.integer(raw, -1, '%s id' % (EXTENSION,))
        if index < 0:
            values.warn('%s id %r is not a node index; that level is left out'
                        % (EXTENSION, raw))
            continue
        if index == own:
            values.warn('%s on node %d names the node itself as a coarser '
                        'level; that id is left out' % (EXTENSION, own))
            continue
        found.append(index)
    return found


def screen_coverage(node: Any, levels: int,
                    values: Optional[DocumentValues] = None,
                    kept: Optional[Sequence[int]] = None) -> list:
    """The coverage each of the levels drawn takes over at, decreasing.

    ``levels`` is how many levels the file declares, the node's own and one
    for each id. The file's figures are one per declared level, and may add
    one more below which nothing is drawn. ``kept`` is which of the declared
    levels were built (all of them by default): a level left out takes its
    figure with it, so the others keep theirs.

    The file's own figures where it gave them. The extension calls them a hint
    and a file may leave them out, so a chain that named none is scheduled by
    halving -- ending at zero, because a level a *reader* guessed a threshold
    for must not be the reason something disappears. A figure that is no
    finite number, a value that is no list, or a list of any other length is
    reported and the chain is scheduled by halving; a negative figure is 0.
    """
    kept = list(range(levels)) if kept is None else list(kept)
    extras = getattr(node, 'extras', None) or {}
    stated = extras.get(COVERAGE) if isinstance(extras, dict) else None
    if stated:
        values = values if values is not None else DocumentValues(logger=log)
        # NaN stands for a figure DocumentValues reported as unusable.
        read = ([values.number(value, math.nan, COVERAGE, minimum=0.0)
                 for value in stated] if isinstance(stated, list) else [math.nan])
        if not all(math.isfinite(value) for value in read):
            values.warn('%s is %r, which is not a list of numbers; the levels '
                        'are scheduled by halving' % (COVERAGE, stated))
        elif len(read) not in (levels, levels + 1):
            values.warn('%s has %d figures for %d levels; the levels are '
                        'scheduled by halving' % (COVERAGE, len(read), levels))
        else:
            return [read[index] for index in kept] + read[levels:]
    return halving_coverage(len(kept))


def halving_coverage(levels: int) -> list:
    """The coverage each of ``levels`` levels takes over at when none was
    measured: :data:`FIRST_COVERAGE`, halved for each further level, and 0 for
    the coarsest, so the chain is never culled by a threshold nobody chose.

    What the loader reads a file that states no coverage as, and what
    :meth:`~OpenGLContext.loaders.gltf.writer.GLTFWriter.add_lod` writes when
    its caller measured none.
    """
    if levels <= 0:
        return []
    return [FIRST_COVERAGE / (2 ** index) for index in range(levels - 1)] + [0.0]


def mesh_bounds(g: "pygltflib.GLTF2",
                mesh_index: int) -> Optional[Tuple[Sequence[float], float]]:
    """``(centre, radius)`` of a mesh, from what its accessors declare.

    Read from the ``POSITION`` accessors' ``min``/``max`` rather than from the
    vertices, so a level whose bytes have not been fetched can still be placed
    and sized. None where the file declares neither, or declares no three
    finite numbers for either.
    """
    lows: list = []
    highs: list = []
    for primitive in g.meshes[mesh_index].primitives:
        index = getattr(primitive.attributes, 'POSITION', None)
        if index is None:
            continue
        declared = declared_bounds(g.accessors[index])
        if declared is None:
            continue
        lows.append(declared[0])
        highs.append(declared[1])
    if not lows:
        return None
    low = np.asarray(lows, dtype='d').min(axis=0)
    high = np.asarray(highs, dtype='d').max(axis=0)
    centre = (low + high) / 2.0
    return tuple(float(value) for value in centre), float(np.linalg.norm(high - low) / 2.0)
