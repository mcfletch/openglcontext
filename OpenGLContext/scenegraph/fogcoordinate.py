"""X3D's FogCoordinate: a fog depth given per vertex in place of the distance

A geometry's `fogCoord` holds one `depth`, 0 to 1, per coordinate; a list
shorter than the coordinates gives its last depth to the rest (ISO/IEC
19775-1, FogCoordinate). Drawn, a vertex's depth is the share of the fog colour it
takes, in place of the share its distance and the fog's `visibilityRange`
give: X_ITE's reading of the depth replacing the generated one.

:func:`vertex_depths` gives the depth of each vertex a mesh is drawn with,
from the coordinate each vertex was read from. :func:`bind_depths`
puts them in a buffer texture the PBR vertex shader reads by
`gl_VertexID`, so the depths take no vertex attribute location.
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_R32F, GL_STATIC_DRAW, GL_TEXTURE0, GL_TEXTURE_BUFFER, glActiveTexture, glBindBuffer,
    glBindTexture, glBufferData, glDeleteBuffers, glDeleteTextures, glGenBuffers,
    glGenTextures, glTexBuffer,
)

from vrml.x3d import nodes as x3d

from OpenGLContext import contextresources

#: The texture unit the PBR vertex shader reads the depths from: past the
#: units the fragment stage's samplers take (pbrpass).
FOG_DEPTH_UNIT = 36


class FogCoordinate(x3d.FogCoordinate):
    """X3D's FogCoordinate: the fog depth of each coordinate of its geometry"""


def vertex_depths(depth: Any, sources: Optional[np.ndarray],
                  count: int) -> Optional[np.ndarray]:
    """Each of a mesh's `count` vertices' fog depth, float32; None for no depths

    sources -- the coordinate each vertex was read from, or None where
        vertex i is coordinate i
    """
    values = np.clip(np.asarray(depth, dtype=np.float32).reshape(-1), 0.0, 1.0)
    if not len(values):
        return None
    points = np.arange(count) if sources is None else np.asarray(sources, np.int64)
    return np.ascontiguousarray(values[np.minimum(points, len(values) - 1)])


def _delete_texture(name: int) -> None:
    glDeleteTextures(1, np.array([name], np.uint32))


def _delete_buffer(name: int) -> None:
    glDeleteBuffers(1, np.array([name], np.uint32))


#: Each mesh's depth texture and its buffer in each context, deleted with the
#: mesh or the context.
_TEXTURES = contextresources.ContextNames('_fogDepthTextures', _delete_texture)
_BUFFERS = contextresources.ContextNames('_fogDepthBuffers', _delete_buffer)


def bind_depths(owner: Any, depths: np.ndarray) -> bool:
    """Put `owner`'s fog `depths` on :data:`FOG_DEPTH_UNIT`; whether they are there

    Uploaded into a buffer texture of the current context the first time,
    and kept with `owner` (a mesh, whose depths do not change) until it or
    the context is gone.
    """
    textures = _TEXTURES.entries(owner)
    buffers = _BUFFERS.entries(owner)
    if textures is None or buffers is None:
        return False
    texture = textures.get('depths')
    if texture is None:
        buffer = buffers['depths'] = int(glGenBuffers(1))
        glBindBuffer(GL_TEXTURE_BUFFER, buffer)
        glBufferData(GL_TEXTURE_BUFFER, np.ascontiguousarray(depths, np.float32),
                     GL_STATIC_DRAW)
        glBindBuffer(GL_TEXTURE_BUFFER, 0)
        texture = textures['depths'] = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_BUFFER, texture)
        glTexBuffer(GL_TEXTURE_BUFFER, GL_R32F, buffer)
    glActiveTexture(GL_TEXTURE0 + FOG_DEPTH_UNIT)
    glBindTexture(GL_TEXTURE_BUFFER, texture)
    glActiveTexture(GL_TEXTURE0)
    return True
