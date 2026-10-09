"""X3D's EnvironmentLight as the scene's image-based light

``diffuseCoefficients`` are glTF's ``irradianceCoefficients`` (X3D 4.1,
17.4): nine RGB spherical-harmonic coefficients of the irradiance, up to l=2,
here multiplied by the light's ``color``. :meth:`EnvironmentLight.imageLight`
is the :class:`~OpenGLContext.scenegraph.imagebasedlight.ImageBasedLight` the
render pass lights the scene with, with the light's ``intensity`` and
``rotation``.

``specularTexture``, a ``ComposedCubeMapTexture`` or ``ImageCubeMapTexture``,
is the environment smooth surfaces reflect: its faces decoded from sRGB to
linear light, and each rougher level the faces averaged down by half, to a
texel a side. ``diffuseTexture`` is the irradiance (over pi, so a white face
lights a white surface fully), read as its spherical-harmonic fit. The
irradiance is the ``diffuseCoefficients`` where there are nine of them, else
the diffuse cube map's, else the specular cube map convolved. Without a
specular cube map the one specular level is the irradiance, so smooth
surfaces reflect a blurred environment. A ``GeneratedCubeMapTexture`` is not
read here, nor are ``origin`` and ``global``. All multiply by ``color``.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from vrml import cache, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight, sh_fit

__all__ = ['EnvironmentLight', 'IMAGE_LIGHT_KEY', 'IRRADIANCE_BANDS', 'mip_chain']

#: Where an EnvironmentLight keeps its ImageBasedLight, in vrml's cache.
IMAGE_LIGHT_KEY = 'environment-image-light'

#: The width of the specular level made from the coefficients.
SPECULAR_SIZE = 16


class EnvironmentLight(x3d.EnvironmentLight):
    """X3D's EnvironmentLight, lighting the scene from its coefficients"""

    def imageLight(self) -> Optional[ImageBasedLight]:
        """The image-based light this is drawn as; None where it is off or has
        neither coefficients nor a cube map with faces

        Kept in vrml's cache until a field of this light, or a face of one of
        its cube maps, is set.
        """
        held = cache.CACHE.getData(self, IMAGE_LIGHT_KEY)
        if held is None:
            held = (self._build(),)
            holder = cache.CACHE.holder(self, held, IMAGE_LIGHT_KEY)
            for declared in protofunctions.getFields(self):
                if not declared.name.startswith(' '):
                    holder.depend(self, declared)
            for texture in (self.diffuseTexture, self.specularTexture):
                depend = getattr(texture, 'dependFaces', None)
                if depend is not None:
                    depend(holder)
        found: Optional[ImageBasedLight] = held[0]
        return found

    def _build(self) -> Optional[ImageBasedLight]:
        if not self.on:
            return None
        colour = np.asarray(self.color, np.float64)[:3]
        values = np.asarray(self.diffuseCoefficients, dtype=np.float64).ravel()
        specular = _linear_faces(self.specularTexture)
        diffuse = _linear_faces(self.diffuseTexture)
        if len(values) >= 27:
            coefficients = values[:27].reshape(9, 3)
        elif diffuse is not None:
            coefficients = sh_fit(diffuse) * math.pi
        elif specular is not None:
            coefficients = sh_fit(specular) * IRRADIANCE_BANDS[:, None]
        else:
            return None
        coefficients = coefficients * colour
        x, y, z, angle = (float(value) for value in self.rotation)
        length = math.sqrt(x * x + y * y + z * z) or 1.0
        half = math.sin(angle / 2.0) / length
        light = ImageBasedLight(intensity=float(self.intensity),
                                rotation=(x * half, y * half, z * half, math.cos(angle / 2.0)),
                                irradianceCoefficients=[tuple(row) for row in coefficients],
                                specularImageSize=SPECULAR_SIZE)
        if specular is not None:
            light.specular = mip_chain([face * colour for face in specular])
            light.specularImageSize = int(specular[0].shape[0])
        else:
            # The specular level is the irradiance unturned and at unit
            # intensity: specular_faces turns and scales it as
            # irradiance_faces does.
            unturned = ImageBasedLight(irradianceCoefficients=light.irradianceCoefficients)
            light.specular = [unturned.irradiance_faces(SPECULAR_SIZE)]
        return light


#: What each band of a radiance's spherical-harmonic coefficients is
#: multiplied by to give the irradiance's: the cosine lobe's pi, 2 pi / 3
#: and pi / 4.
IRRADIANCE_BANDS = np.array([math.pi] + [2.0 * math.pi / 3.0] * 3 + [math.pi / 4.0] * 5)


def _linear_faces(texture: Any) -> Optional[list[np.ndarray]]:
    """A cube map node's six faces as linear float RGB, or None"""
    faces_of = getattr(texture, 'faceImages', None)
    faces = faces_of() if faces_of is not None else None
    if not faces:
        return None
    values = [np.asarray(face, np.float64)[..., :3] / 255.0 for face in faces]
    return [np.where(face <= 0.04045, face / 12.92, ((face + 0.055) / 1.055) ** 2.4)
            for face in values]


def mip_chain(faces: list[np.ndarray]) -> list[list[np.ndarray]]:
    """The faces, then each level the one before averaged down by half, to one texel"""
    chain = [faces]
    while chain[-1][0].shape[0] > 1:
        level = []
        for face in chain[-1]:
            size = face.shape[0] // 2 * 2
            trimmed = face[:size, :size]
            level.append(0.25 * (trimmed[0::2, 0::2] + trimmed[1::2, 0::2]
                                 + trimmed[0::2, 1::2] + trimmed[1::2, 1::2]))
        chain.append(level)
    return chain
