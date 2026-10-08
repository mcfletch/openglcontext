"""X3D's MultiTexture: textures combined in order into a surface's colour

The shaders draw the stage chain :mod:`OpenGLContext.scenegraph.texturelayers`
reads from the node; the node itself holds no GL texture of its own, its
layers' textures being bound by the pass. In the compatibility profile the
first layer that is an ordinary 2D texture is drawn, combined with the
lit colour by its mode where the fixed-function texture environment has one
(``MODULATE``, ``REPLACE``, ``ADD``, ``ADD_SIGNED``, ``SUBTRACT`` and the
``SELECT`` modes), and modulating otherwise.
"""
from __future__ import annotations

from typing import Any, Optional

from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import texturelayers

__all__ = ['MultiTexture', 'fixed_function_mode']

#: Each mode the fixed-function texture environment has, as its GL name.
_FIXED_MODES = {
    texturelayers.MODES['MODULATE']: 'GL_MODULATE',
    texturelayers.MODES['REPLACE']: 'GL_REPLACE',
    texturelayers.MODES['SELECT_ARG1']: 'GL_REPLACE',
    texturelayers.MODES['ADD']: 'GL_ADD',
    texturelayers.MODES['ADD_SIGNED']: 'GL_ADD_SIGNED',
    texturelayers.MODES['SUBTRACT']: 'GL_SUBTRACT',
}


def fixed_function_mode(mode: int) -> str:
    """The fixed-function combine for a layer's colour mode, by its GL name

    ``GL_MODULATE`` for a mode the texture environment cannot express.
    """
    return _FIXED_MODES.get(mode, 'GL_MODULATE')


class MultiTexture(x3d.MultiTexture):
    """X3D's MultiTexture, drawn as a stage chain"""

    def layerTextures(self) -> list[Any]:
        """The texture nodes the chain combines, in order"""
        return [child for child in self.texture
                if child and not isinstance(child, x3d.MultiTexture)]

    def hasAlpha(self) -> bool:
        """Whether a layer's image has an alpha channel"""
        for child in self.layerTextures():
            found = getattr(child, 'hasAlpha', None)
            if callable(found) and found():
                return True
        return False

    def cached(self, mode: Any = None) -> None:
        """No texture of its own: the pass binds each layer's"""
        return None

    def _firstFlat(self) -> tuple[Optional[Any], int]:
        modes = list(self.mode)
        for index, child in enumerate(self.layerTextures()):
            if texturelayers.layer_kind(child) == texturelayers.KIND_2D:
                colour = (texturelayers.parse_mode(modes[index])[0] if index < len(modes)
                          else texturelayers.MODES['MODULATE'])
                return child, colour
        return None, 0

    def render(self, visible: int = 1, lit: int = 1, mode: Any = None) -> Optional[int]:
        """Draw the first 2D layer through the fixed-function texture unit

        Returns what that texture's ``render`` returns; None where there is
        no 2D layer.
        """
        child, colour = self._firstFlat()
        if child is None:
            return None
        found: Optional[int] = child.render(visible=visible, lit=lit, mode=mode)
        if not getattr(mode, 'shader_mode', False):
            from OpenGL import GL  # noqa: PLC0415 only the fixed-function pipeline asks
            GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_TEXTURE_ENV_MODE,
                         getattr(GL, fixed_function_mode(colour))
                         if fixed_function_mode(colour) in ('GL_MODULATE', 'GL_REPLACE',
                                                            'GL_ADD')
                         else GL.GL_COMBINE)
            if fixed_function_mode(colour) in ('GL_ADD_SIGNED', 'GL_SUBTRACT'):
                GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_COMBINE_RGB,
                             getattr(GL, fixed_function_mode(colour)))
        return found

    def renderPost(self, mode: Any = None) -> None:
        """Put the texture unit back as the first 2D layer's ``renderPost`` does"""
        child, _colour = self._firstFlat()
        if child is None:
            return
        if not getattr(mode, 'shader_mode', False):
            from OpenGL import GL  # noqa: PLC0415 only the fixed-function pipeline asks
            GL.glTexEnvi(GL.GL_TEXTURE_ENV, GL.GL_TEXTURE_ENV_MODE, GL.GL_MODULATE)
        child.renderPost(mode=mode)
