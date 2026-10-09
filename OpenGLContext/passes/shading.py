"""How surfaces are shaded: points, wireframe, flat, Gouraud or Phong -- no GL

``ContextDefinition.shading`` (``OPENGLCONTEXT_SHADING``) chooses, with the
values of X_ITE's ``Shading`` option and of X3D's browser option of the same
name (19775-1, Table 9.2):

- ``point`` - each polygon drawn as its corners;
- ``wireframe`` - each polygon drawn as its edges;
- ``flat`` - each face lit with its own normal, worked out from the
  fragment's position, and a document's Material textured as ``gouraud``;
- ``gouraud`` - a document's Material lit without its textures and the result
  multiplied by its main texture (19775-1, 17.2.2.7);
- ``phong`` - a document's Material lit with its texture multiplying the
  diffuse colour (17.2.2.5).

``auto`` is ``gouraud`` for a VRML97 or X3D document, X_ITE's default, and
``phong`` for any other scene, where no Material is drawn by X3D's equation
and the two are the same. ``point`` and ``wireframe`` set the polygon mode
for the scene's geometry and leave its lighting as ``auto`` has it.
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ['SHADINGS', 'CHOICES', 'LABELS', 'resolve', 'chosen', 'polygon_mode',
           'default_shading', 'frame_shading']

#: The shadings, in X_ITE's order.
SHADINGS: tuple[str, ...] = ('point', 'wireframe', 'flat', 'gouraud', 'phong')
#: What ``ContextDefinition.shading`` accepts.
CHOICES: tuple[str, ...] = ('auto',) + SHADINGS
#: What a settings screen shows for each of those.
LABELS: tuple[str, ...] = ('By the scene', 'Points', 'Wireframe', 'Flat', 'Gouraud', 'Phong')
#: Other spellings: X_ITE reads POINTSET as POINT.
SYNONYMS: dict[str, str] = {'pointset': 'point'}


def default_shading() -> str:
    """``OPENGLCONTEXT_SHADING``, one of :data:`CHOICES`, else ``auto``"""
    from OpenGLContext import renderoptions
    return renderoptions.env_choice_once('OPENGLCONTEXT_SHADING', CHOICES, SYNONYMS, 'auto')


def chosen(source: Any) -> str:
    """The shading ``source``'s definition chooses, as it is spelt there"""
    from OpenGLContext import renderoptions
    return renderoptions.choice(source, 'shading', default_shading())


def resolve(choice: str, document: bool) -> str:
    """The shading ``choice`` draws with: itself, or for ``auto`` the scene's"""
    choice = str(choice).lower()
    choice = SYNONYMS.get(choice, choice)
    if choice == 'auto':
        return 'gouraud' if document else 'phong'
    if choice not in SHADINGS:
        raise ValueError('shading is one of %s, not %r' % (CHOICES, choice))
    return choice


def frame_shading(source: Any, scene: Any = None) -> str:
    """The shading a frame of ``scene`` drawn through ``source`` uses"""
    from OpenGLContext import lighting
    if scene is None:
        scene = getattr(source, 'scene', None)
    return resolve(chosen(source), lighting.scene_x3d_lit(scene, 'auto'))


def polygon_mode(shading: str) -> Optional[int]:
    """``GL_POINT`` or ``GL_LINE`` for ``point`` and ``wireframe``, else None"""
    from OpenGL.GL import GL_LINE, GL_POINT  # noqa: PLC0415 the rest of the module needs no GL
    return {'point': GL_POINT, 'wireframe': GL_LINE}.get(shading)
