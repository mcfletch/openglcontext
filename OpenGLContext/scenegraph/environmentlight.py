"""X3D's EnvironmentLight as the scene's image-based light

``diffuseCoefficients`` are glTF's ``irradianceCoefficients`` (X3D 4.1,
17.4): nine RGB spherical-harmonic coefficients of the irradiance, up to l=2,
here multiplied by the light's ``color``. :meth:`EnvironmentLight.imageLight`
is the :class:`~OpenGLContext.scenegraph.imagebasedlight.ImageBasedLight` the
render pass lights the scene with, with the light's ``intensity`` and
``rotation``; its one specular level is the irradiance the same
coefficients give, so smooth surfaces reflect a blurred environment. The
cube-map ``diffuseTexture`` and ``specularTexture`` are not read, nor are
``origin`` and ``global``.
"""
from __future__ import annotations

import math
from typing import Any, Optional

import numpy as np
from vrml import cache, protofunctions
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight

__all__ = ['EnvironmentLight', 'IMAGE_LIGHT_KEY']

#: Where an EnvironmentLight keeps its ImageBasedLight, in vrml's cache.
IMAGE_LIGHT_KEY = 'environment-image-light'

#: The width of the specular level made from the coefficients.
SPECULAR_SIZE = 16


class EnvironmentLight(x3d.EnvironmentLight):
    """X3D's EnvironmentLight, lighting the scene from its coefficients"""

    def imageLight(self) -> Optional[ImageBasedLight]:
        """The image-based light this is drawn as; None where it is off or has no coefficients

        Kept in vrml's cache until a field of this light is set.
        """
        held = cache.CACHE.getData(self, IMAGE_LIGHT_KEY)
        if held is None:
            held = (self._build(),)
            holder = cache.CACHE.holder(self, held, IMAGE_LIGHT_KEY)
            for declared in protofunctions.getFields(self):
                if not declared.name.startswith(' '):
                    holder.depend(self, declared)
        found: Optional[ImageBasedLight] = held[0]
        return found

    def _build(self) -> Optional[ImageBasedLight]:
        values = np.asarray(self.diffuseCoefficients, dtype=np.float64).ravel()
        if not self.on or len(values) < 27:
            return None
        coefficients = values[:27].reshape(9, 3) * np.asarray(self.color, np.float64)[:3]
        x, y, z, angle = (float(value) for value in self.rotation)
        length = math.sqrt(x * x + y * y + z * z) or 1.0
        half = math.sin(angle / 2.0) / length
        light = ImageBasedLight(intensity=float(self.intensity),
                                rotation=(x * half, y * half, z * half, math.cos(angle / 2.0)),
                                irradianceCoefficients=[tuple(row) for row in coefficients],
                                specularImageSize=SPECULAR_SIZE)
        # The specular level is the irradiance unturned and at unit intensity:
        # specular_faces turns and scales it as irradiance_faces does.
        unturned = ImageBasedLight(irradianceCoefficients=light.irradianceCoefficients)
        light.specular = [unturned.irradiance_faces(SPECULAR_SIZE)]
        return light
