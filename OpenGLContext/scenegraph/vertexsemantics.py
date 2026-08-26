"""Where a geometry's arrays and a shader's inputs meet: the location table.

A geometry node writes its arrays into vertex buffers and a shader program reads
them back, and the two meet only at an attribute location number. This module is
where that number is decided, once, for the whole engine: the semantics the
engine speaks, the location each is read from, how many components it carries and
what the engine's own shaders call it.

Locations rather than names, because a Vertex Array Object records locations. A
VAO built by looking each name up in one program is valid only for that program,
so a mesh drawn by the lit program, the unlit program and the shadow depth pass
would need three of them. With the locations fixed, one VAO per geometry serves
every program that follows the table.

The keys are glTF's vertex semantics, the vocabulary the loaders already speak
(:mod:`OpenGLContext.loaders.gltf`, :mod:`OpenGLContext.scenegraph.frommesh`):

===============  ========  ==========  =============
Semantic         Location  Components  Shader name
===============  ========  ==========  =============
``TEXCOORD_0``   0         2           ``aTexCoord``
``NORMAL``       1         3           ``aNormal``
``POSITION``     2         3           ``aPosition``
``TANGENT``      3         4           ``aTangent``
``COLOR_0``      4         4           ``aColor``
``TEXCOORD_1``   11        2           ``aTexCoord1``
``JOINTS_0``     12        4           ``aJoints``
``WEIGHTS_0``    13        4           ``aWeights``
===============  ========  ==========  =============

Locations 5 to 10 and 14 carry the per-instance inputs the instanced draw path
supplies (:mod:`OpenGLContext.passes.instancing`): a ``mat4`` model-view occupies
four consecutive locations from 5, then the object id, the material index and a
skinned instance's joint base. A per-vertex input of your own therefore starts at
:data:`FIRST_FREE_LOCATION`.

A program that owns both its geometry and its shader -- the overlay UI batcher,
the particle system, the vegetation and terrain layers -- is outside this
agreement: nothing else feeds it, so it numbers its inputs as it likes. What it
must not do is spell one of the names above and mean something else by it;
``tests/unit/test_vertex_semantics.py`` holds every shader in the package to
that.
"""
from __future__ import annotations

from typing import Dict, NamedTuple, Tuple

__all__ = [
    'VertexSemantic', 'SEMANTICS', 'BY_SEMANTIC', 'BY_ATTRIBUTE', 'location',
    'LOC_TEXCOORD', 'LOC_NORMAL', 'LOC_POSITION', 'LOC_TANGENT', 'LOC_COLOR',
    'LOC_TEXCOORD1', 'LOC_JOINTS', 'LOC_WEIGHTS',
    'INSTANCE_MODELVIEW', 'INSTANCE_MODELVIEW_COLUMNS', 'INSTANCE_OBJECT_ID',
    'INSTANCE_MATERIAL', 'INSTANCE_JOINT_BASE', 'FIRST_FREE_LOCATION',
]


class VertexSemantic(NamedTuple):
    """One row of the table: what an array means and where it is read from."""

    semantic: str
    """glTF's name for the meaning of the array, e.g. ``'POSITION'``."""
    location: int
    """The attribute location every conforming shader reads it at."""
    components: int
    """Floats per vertex."""
    attribute: str
    """What the engine's own shaders call it."""


LOC_TEXCOORD = 0
LOC_NORMAL = 1
LOC_POSITION = 2
LOC_TANGENT = 3
LOC_COLOR = 4
LOC_TEXCOORD1 = 11
LOC_JOINTS = 12
LOC_WEIGHTS = 13

#: First of the four consecutive locations a per-instance ``mat4`` model-view
#: occupies; a matrix input takes one location per column.
INSTANCE_MODELVIEW = 5
INSTANCE_MODELVIEW_COLUMNS = 4
INSTANCE_OBJECT_ID = 9
INSTANCE_MATERIAL = 10
INSTANCE_JOINT_BASE = 14

#: Where a shader of your own may put an input the engine has no name for.
FIRST_FREE_LOCATION = 15

SEMANTICS: Tuple[VertexSemantic, ...] = (
    VertexSemantic('TEXCOORD_0', LOC_TEXCOORD, 2, 'aTexCoord'),
    VertexSemantic('NORMAL', LOC_NORMAL, 3, 'aNormal'),
    VertexSemantic('POSITION', LOC_POSITION, 3, 'aPosition'),
    VertexSemantic('TANGENT', LOC_TANGENT, 4, 'aTangent'),
    VertexSemantic('COLOR_0', LOC_COLOR, 4, 'aColor'),
    VertexSemantic('TEXCOORD_1', LOC_TEXCOORD1, 2, 'aTexCoord1'),
    VertexSemantic('JOINTS_0', LOC_JOINTS, 4, 'aJoints'),
    VertexSemantic('WEIGHTS_0', LOC_WEIGHTS, 4, 'aWeights'),
)

BY_SEMANTIC: Dict[str, VertexSemantic] = {
    entry.semantic: entry for entry in SEMANTICS
}
BY_ATTRIBUTE: Dict[str, VertexSemantic] = {
    entry.attribute: entry for entry in SEMANTICS
}


def location(semantic: str) -> int:
    """The attribute location a conforming shader reads ``semantic`` at.

    Raises ``KeyError`` naming the semantic when it is not one the engine
    speaks, since a wrong location draws every vertex at the origin and the
    geometry vanishes with no GL error to say why.
    """
    return BY_SEMANTIC[semantic].location
