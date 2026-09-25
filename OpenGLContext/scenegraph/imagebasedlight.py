"""An image-based light: a prefiltered environment and its diffuse irradiance.

``EXT_lights_image_based`` ships the environment lighting a document was
authored under, already convolved: a cube of specular images for each
roughness level (a mip chain, faces ordered +X, -X, +Y, -Y, +Z, -Z) and nine
spherical-harmonic coefficients for the diffuse irradiance, up to l=2. A
scene selects one with ``{"light": n}``, and so does a zone
(:class:`~OpenGLContext.scenegraph.zone.ZoneEnvironment`'s ``light``).

:class:`ImageBasedLight` holds one, decoded: :attr:`specular` is the mip
chain as linear float ``(size, size, 3)`` faces, and :meth:`irradiance_faces`
evaluates the coefficients into the six faces of an irradiance cube, in the
units the PBR shader's irradiance map holds (irradiance over pi, so it
multiplies albedo directly). ``rotation`` turns the environment; it is applied
as the faces are read, so the renderer samples a world-aligned cube.

The renderer uploads a light into a layer of its probe arrays
(:meth:`~OpenGLContext.passes.ibl.IBLProbe.upload_light`) once, when the light
is first needed, and draws nothing to do it.
"""
from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Optional

import numpy as np
from vrml import field, node
from vrml.vrml97 import nodetypes

__all__ = ['ImageBasedLight', 'face_directions', 'sh_irradiance', 'sh_fit',
           'encode_rgbd', 'decode_rgbd']

#: The real spherical-harmonic basis constants up to l=2.
_SH = (0.282095, 0.488603, 0.488603, 0.488603,
       1.092548, 1.092548, 0.315392, 1.092548, 0.546274)


def face_directions(face: int, size: int) -> np.ndarray:
    """World directions at the texel centres of one GL cube face, ``(size, size, 3)``.

    Faces in GL order: +X, -X, +Y, -Y, +Z, -Z, rows from the top of the face
    image, as ``load_cubemap_faces`` uploads them.
    """
    t = (np.arange(size) + 0.5) / size * 2.0 - 1.0
    u, v = np.meshgrid(t, t)            # u across, v down the image
    one = np.ones_like(u)
    if face == 0:
        d = np.stack([one, -v, -u], -1)
    elif face == 1:
        d = np.stack([-one, -v, u], -1)
    elif face == 2:
        d = np.stack([u, one, v], -1)
    elif face == 3:
        d = np.stack([u, -one, -v], -1)
    elif face == 4:
        d = np.stack([u, -v, one], -1)
    else:
        d = np.stack([-u, -v, -one], -1)
    return d / np.linalg.norm(d, axis=-1, keepdims=True)


def sh_irradiance(coefficients: Any, directions: np.ndarray) -> np.ndarray:
    """Irradiance from nine RGB spherical-harmonic coefficients, at each direction."""
    c = np.asarray(coefficients, dtype='d').reshape(9, 3)
    x, y, z = directions[..., 0], directions[..., 1], directions[..., 2]
    basis = [
        np.full_like(x, _SH[0]), _SH[1] * y, _SH[2] * z, _SH[3] * x,
        _SH[4] * x * y, _SH[5] * y * z, _SH[6] * (3.0 * z * z - 1.0),
        _SH[7] * x * z, _SH[8] * (x * x - y * y),
    ]
    out = np.zeros(directions.shape[:-1] + (3,), dtype='d')
    for weight, coefficient in zip(basis, c, strict=True):
        out += weight[..., None] * coefficient
    return np.maximum(out, 0.0)


def sh_fit(faces: Sequence[np.ndarray]) -> np.ndarray:
    """Nine RGB spherical-harmonic coefficients, l <= 2, fitted to a cube's six faces.

    ``faces`` are ``(n, n, 3)`` in GL order; each texel is weighted by the
    solid angle it covers, so the fit is the projection :func:`sh_irradiance`
    evaluates back.
    """
    size = faces[0].shape[0]
    t = (np.arange(size) + 0.5) / size * 2.0 - 1.0
    u, v = np.meshgrid(t, t)
    weight = (4.0 / (size * size)) / (1.0 + u * u + v * v) ** 1.5
    found = np.zeros((9, 3), dtype='d')
    for face in range(6):
        directions = face_directions(face, size)
        values = np.asarray(faces[face], dtype='d')[..., :3] * weight[..., None]
        x, y, z = directions[..., 0], directions[..., 1], directions[..., 2]
        bases = (np.full_like(x, _SH[0]), _SH[1] * y, _SH[2] * z, _SH[3] * x,
                 _SH[4] * x * y, _SH[5] * y * z, _SH[6] * (3.0 * z * z - 1.0),
                 _SH[7] * x * z, _SH[8] * (x * x - y * y))
        for index, basis_values in enumerate(bases):
            found[index] += (values * basis_values[..., None]).sum(axis=(0, 1))
    return found


def encode_rgbd(values: np.ndarray) -> np.ndarray:
    """8-bit RGBA from linear float RGB: the colour times D, with D in the alpha.

    D is one where the brightest channel is at most one and falls as the colour
    brightens, so values up to 255 survive; :func:`decode_rgbd` divides back.
    """
    rgb = np.maximum(np.asarray(values, dtype='d')[..., :3], 0.0)
    peak = np.maximum(rgb.max(axis=-1, keepdims=True), 1e-6)
    d = np.clip(1.0 / peak, 1.0 / 255.0, 1.0)
    d = np.maximum(np.floor(d * 255.0), 1.0) / 255.0
    out = np.empty(rgb.shape[:-1] + (4,), dtype='u1')
    out[..., :3] = np.clip(np.round(rgb * d * 255.0), 0, 255)
    out[..., 3:] = np.round(d * 255.0)
    return out


def decode_rgbd(pixels: np.ndarray) -> np.ndarray:
    """Linear float RGB from an 8-bit image, RGBD-decoded where it has alpha.

    A four-channel PNG in ``EXT_lights_image_based`` is RGBD: the colour
    divided by the alpha channel is the HDR value. Three channels are LDR
    values used as they are.
    """
    values = np.asarray(pixels, dtype='d') / 255.0
    if values.shape[-1] == 4:
        return values[..., :3] / np.maximum(values[..., 3:4], 1.0 / 255.0)
    return values[..., :3]


def _rotation_matrix(quaternion: Sequence[float]) -> np.ndarray:
    x, y, z, w = (float(v) for v in quaternion)
    length = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / length, y / length, z / length, w / length
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _sample(faces: Sequence[np.ndarray], directions: np.ndarray) -> np.ndarray:
    """A cube's six faces read in each direction, filtered bilinearly within a face.

    The four texels round the point are those of the face the direction
    lands on, clamped at its edges; a turned environment is smooth wherever
    the faces are.
    """
    size = faces[0].shape[0]
    d = directions
    ax, ay, az = np.abs(d[..., 0]), np.abs(d[..., 1]), np.abs(d[..., 2])
    out = np.zeros(d.shape[:-1] + (3,), dtype='d')
    major = np.argmax(np.stack([ax, ay, az], -1), -1)
    for face in range(6):
        axis, positive = face // 2, face % 2 == 0
        mask = (major == axis) & ((d[..., axis] > 0) == positive)
        if not np.any(mask):
            continue
        v = d[mask] / np.abs(d[mask][:, axis:axis + 1])
        u_, v_ = {0: (-v[:, 2], -v[:, 1]), 1: (v[:, 2], -v[:, 1]),
                  2: (v[:, 0], v[:, 2]), 3: (v[:, 0], -v[:, 2]),
                  4: (v[:, 0], -v[:, 1]), 5: (-v[:, 0], -v[:, 1])}[face]
        x = np.clip((u_ + 1.0) / 2.0 * size - 0.5, 0.0, size - 1.0)
        y = np.clip((v_ + 1.0) / 2.0 * size - 0.5, 0.0, size - 1.0)
        x0 = np.minimum(x.astype(int), size - 2) if size > 1 else x.astype(int)
        y0 = np.minimum(y.astype(int), size - 2) if size > 1 else y.astype(int)
        x1 = np.minimum(x0 + 1, size - 1)
        y1 = np.minimum(y0 + 1, size - 1)
        fx = (x - x0)[:, None]
        fy = (y - y0)[:, None]
        texels = np.asarray(faces[face], dtype='d')
        top = texels[y0, x0] * (1.0 - fx) + texels[y0, x1] * fx
        bottom = texels[y1, x0] * (1.0 - fx) + texels[y1, x1] * fx
        out[mask] = top * (1.0 - fy) + bottom * fy
    return out


class ImageBasedLight(nodetypes.Children, node.Node):
    """One ``EXT_lights_image_based`` light, decoded; see the module docstring."""

    PROTO = 'ImageBasedLight'
    #: Multiplies the light's diffuse and specular contribution.
    intensity = field.newField('intensity', 'SFFloat', 1, 1.0)
    #: The environment's turn, a quaternion ``(x, y, z, w)``.
    rotation = field.newField('rotation', 'SFVec4f', 1, (0.0, 0.0, 0.0, 1.0))
    #: Nine RGB spherical-harmonic coefficients of the irradiance, l <= 2.
    irradianceCoefficients = field.newField('irradianceCoefficients', 'MFVec3f', 1, list)
    #: The width of the largest specular mip.
    specularImageSize = field.newField('specularImageSize', 'SFInt32', 1, 0)

    def __init__(self, specular: Optional[list[list[np.ndarray]]] = None,
                 **named: Any) -> None:
        super().__init__(**named)
        #: The mip chain: for each level, six linear ``(n, n, 3)`` faces.
        self.specular: list[list[np.ndarray]] = list(specular or [])

    @property
    def rotated(self) -> bool:
        x, y, z, w = (float(v) for v in self.rotation)
        return not (abs(x) < 1e-9 and abs(y) < 1e-9 and abs(z) < 1e-9)

    def specular_faces(self, level: int) -> list[np.ndarray]:
        """The six faces of one mip, turned by :attr:`rotation`, scaled by intensity."""
        faces = self.specular[level]
        if self.rotated:
            turn = _rotation_matrix(self.rotation)
            size = faces[0].shape[0]
            faces = [_sample(faces, face_directions(face, size) @ turn)
                     for face in range(6)]
        return [np.asarray(face, dtype='f4') * float(self.intensity) for face in faces]

    def irradiance_faces(self, size: int) -> list[np.ndarray]:
        """The six faces of the irradiance cube, ``(size, size, 3)``, as the shader reads them."""
        turn = _rotation_matrix(self.rotation) if self.rotated else np.identity(3)
        return [(sh_irradiance(self.irradianceCoefficients,
                               face_directions(face, size) @ turn)
                 / math.pi * float(self.intensity)).astype('f4')
                for face in range(6)]
