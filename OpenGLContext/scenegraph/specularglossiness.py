"""SpecularGlossinessMaterial: X_ITE's specular/glossiness material, glTF's legacy workflow

A dielectric described by its diffuse colour, the colour of its reflection
at normal incidence (`specularColor`) and its smoothness (`glossiness`, 1
less the roughness), as glTF's KHR_materials_pbrSpecularGlossiness has it.
The PBR pass draws it through the metallic/roughness program with no metal:
the diffuse colour is the base colour, the specular colour the dielectric
reflectance, and the roughness 1 - `glossiness`. The
`specularGlossinessTexture`'s RGB (sRGB) multiplies the specular colour and
its alpha the glossiness. The glTF loader reads a material with the
extension and no `pbrMetallicRoughness` as one, and the glTF writer writes
one with the extension.
"""
from typing import Any

import numpy as np
from vrml.x3d import xite

from OpenGLContext.scenegraph.physicalmaterial import AMBIENT_SHARE, ChannelMaterial


class SpecularGlossinessMaterial(ChannelMaterial, xite.SpecularGlossinessMaterial):
    """X_ITE's SpecularGlossinessMaterial, drawn by the PBR pass"""

    PROTO = 'SpecularGlossinessMaterial'
    CHANNELS = {
        'baseColor': 'diffuseTexture', 'specularColor': 'specularGlossinessTexture',
        'emissive': 'emissiveTexture', 'occlusion': 'occlusionTexture',
        'normal': 'normalTexture',
    }

    def render(self, mode: Any = None) -> float:
        """Set the fixed-function material from the factors; the alpha it draws with

        The compatibility profile's pass calls this through `Appearance`. The
        diffuse colour is the diffuse and ambient colour, the specular colour
        the highlight's, and glossiness narrows the highlight.
        """
        from OpenGL import GL  # noqa: PLC0415 GL only when the fixed-function pass draws
        alpha = 1.0 - float(self.transparency)
        if alpha <= 0.0:
            return 0.0
        diffuse = np.asarray(self.diffuseColor, 'f')[:3]
        specular = np.asarray(self.specularColor, 'f')[:3]
        emission = np.asarray(self.emissiveColor, 'f')[:3]
        gloss = min(max(float(self.glossiness), 0.0), 1.0)
        face = GL.GL_FRONT_AND_BACK
        GL.glMaterialfv(face, GL.GL_DIFFUSE, np.append(diffuse, alpha).astype('f'))
        GL.glMaterialfv(face, GL.GL_AMBIENT,
                        np.append(diffuse * AMBIENT_SHARE, alpha).astype('f'))
        GL.glMaterialfv(face, GL.GL_SPECULAR, np.append(specular, alpha).astype('f'))
        GL.glMaterialfv(face, GL.GL_EMISSION, np.append(emission, alpha).astype('f'))
        GL.glMaterialf(face, GL.GL_SHININESS, float(128.0 * gloss * gloss))
        return alpha
