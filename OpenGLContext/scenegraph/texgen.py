"""X3D's TextureCoordinateGenerator as the vertex shader's texture-coordinate mode -- no GL

A composed geometry whose first texture coordinate set is a
``TextureCoordinateGenerator`` carries a :class:`TexGen`; the PBR program
gives its mode and parameters to the vertex shader, which makes the first
coordinate set from each vertex (ISO/IEC 19775-1, 18.4.8):

- ``COORD``: the vertex's own x and y; ``COORD_EYE``, its x and y in the
  camera's space.
- ``SPHERE``: a sphere map of the camera's view reflected about the normal;
  ``SPHERE_LOCAL``, the same in the geometry's own space.
- ``CAMERA_SPACE_NORMAL``, ``CAMERA_SPACE_POSITION`` and
  ``CAMERA_SPACE_REFLECTION_VECTOR``: the x and y of the normal, the
  position and the reflected view in the camera's space.
- ``NOISE`` and ``NOISE_EYE``: value noise of the vertex's own or
  camera-space position, scaled by the first three parameters and moved by
  the next three.
- ``SPHERE_REFLECT`` and ``SPHERE_REFLECT_LOCAL``: a sphere map of the view
  refracted with the first parameter as the index of refraction (1.0 where
  none is given) and reflected with the second as the blend.

The fixed-function path does not generate coordinates.
"""
from __future__ import annotations

from typing import Any, NamedTuple, Optional

from vrml.x3d import nodes as x3d

__all__ = ['MODES', 'TexGen', 'texgen_of']

#: The vertex shader's number for each of X3D's modes; 0 is no generator.
MODES: dict[str, int] = {
    'SPHERE': 1,
    'CAMERA_SPACE_NORMAL': 2,
    'CAMERA_SPACE_POSITION': 3,
    'CAMERA_SPACE_REFLECTION_VECTOR': 4,
    'SPHERE_LOCAL': 5,
    'COORD': 6,
    'COORD_EYE': 7,
    'NOISE': 8,
    'NOISE_EYE': 9,
    'SPHERE_REFLECT': 10,
    'SPHERE_REFLECT_LOCAL': 11,
}

#: How many parameters the shader takes.
PARAMETERS = 8


class TexGen(NamedTuple):
    """A generator's mode number and its parameters, padded with zeros"""

    mode: int
    parameters: tuple[float, ...]


def texgen_of(node: Any) -> Optional[TexGen]:
    """The TexGen of a TextureCoordinateGenerator; None for any other node"""
    if not isinstance(node, x3d.TextureCoordinateGenerator):
        return None
    values = [float(value) for value in node.parameter][:PARAMETERS]
    values += [0.0] * (PARAMETERS - len(values))
    return TexGen(MODES.get(str(node.mode), MODES['SPHERE']), tuple(values))
