"""UnlitMaterial: X3D's material for a surface drawn in its own colour, unlit

The PBR pass draws it with the lighting switched off: the colour is
`emissiveColor`, multiplied by `emissiveTexture` where there is one, at the
opacity `1 - transparency`. glTF's `KHR_materials_unlit` loads as one, with the
glTF base colour as the emissive colour.
"""
from typing import Any

import numpy as np

from vrml import field
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph.physicalmaterial import ChannelMaterial


class UnlitMaterial(ChannelMaterial, x3d.UnlitMaterial):
    """X3D's UnlitMaterial; its emissive texture is drawn as the base colour map"""

    PROTO = 'UnlitMaterial'
    CHANNELS = {'baseColor': 'emissiveTexture'}

    #: An octahedral impostor whose atlas holds the model with its light
    #: baked in: as :attr:`PhysicalMaterial.octahedralViews`.
    octahedralViews = field.newField('octahedralViews', 'SFInt32', 1, 0)
    #: Whether that atlas holds the upper hemisphere only.
    octahedralHemi = field.newField('octahedralHemi', 'SFBool', 1, True)

    def render(self, mode: Any = None) -> float:
        """Set the fixed-function material to emit the colour; the alpha it draws with

        The compatibility profile's pass calls this through `Appearance`, as
        it calls `Material.render`.
        """
        from OpenGL import GL  # noqa: PLC0415 GL only when the fixed-function pass draws
        alpha = 1.0 - float(self.transparency)
        if alpha <= 0.0:
            return 0.0
        dark = np.array((0.0, 0.0, 0.0, alpha), 'f')
        emission = np.append(np.asarray(self.emissiveColor, 'f')[:3], alpha).astype('f')
        face = GL.GL_FRONT_AND_BACK
        GL.glMaterialfv(face, GL.GL_DIFFUSE, dark)
        GL.glMaterialfv(face, GL.GL_AMBIENT, dark)
        GL.glMaterialfv(face, GL.GL_SPECULAR, dark)
        GL.glMaterialfv(face, GL.GL_EMISSION, emission)
        GL.glMaterialf(face, GL.GL_SHININESS, 0.0)
        return alpha
