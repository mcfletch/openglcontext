"""X3D's RenderedTexture: the scene drawn into a picture the surface wears

The render pass draws it (:mod:`OpenGLContext.passes.generatedtextures`),
``width`` by ``height`` pixels, from its ``viewpoint`` or, without one, from
the camera's place; its ``scene`` in place of the world where it has one,
with its ``background`` and ``fog`` in place of the bound ones where it has
them. ``depthMap`` true gives the depth drawn rather than the colour, as a
grey picture, near black and far white. ``update`` is ``NONE`` (drawn once,
the first time it is needed), ``NEXT_FRAME_ONLY`` or ``ALWAYS``, as for a
``GeneratedCubeMapTexture``.

X3D 4.1 declares RenderedTexture's capture fields (``url``,
``singleFrame``, ``maxNumberFrames``, ...) and not these; ``update``,
``viewpoint``, ``scene``, ``background`` and ``fog`` are the engine's, and a
document carries them in an ``OpenGLContext`` metadata set
(``vrml.x3d.extension``). The capture fields are kept and not acted on.
"""
from __future__ import annotations

from typing import Any, Optional

from vrml import field, node
from vrml.x3d import nodes as x3d

__all__ = ['RenderedTexture']


class RenderedTexture(x3d.RenderedTexture):
    """X3D's RenderedTexture, drawn by the render pass"""

    x3dExtension = 'OpenGLContext'
    update = field.newField('update', 'SFString', 1, 'NONE')
    viewpoint = field.newField('viewpoint', 'SFNode', 1, node.NULL)
    scene = field.newField('scene', 'SFNode', 1, node.NULL)
    background = field.newField('background', 'SFNode', 1, node.NULL)
    fog = field.newField('fog', 'SFNode', 1, node.NULL)

    def cached(self, mode: Any = None) -> Any:
        """The picture the pass last drew, or None before its first drawing

        Asking is what tells the pass the texture is wanted.
        """
        generated = getattr(mode, 'generatedTexture', None)
        return generated(self) if generated is not None else None

    def hasAlpha(self) -> bool:
        """Whether the picture has transparent parts: it is drawn opaque"""
        return False

    def render(self, visible: int = 1, lit: int = 1, mode: Any = None) -> Optional[int]:
        """Nothing: the compatibility profile does not draw generated textures"""
        return None

    def renderPost(self, mode: Any = None) -> None:
        """Nothing to undo"""
