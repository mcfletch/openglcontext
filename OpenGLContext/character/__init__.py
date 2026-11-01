"""Rigged characters: the skeleton, the animation blend, and what is held.

Three pieces a game needs on top of a loaded glTF, none of which the format
answers by itself:

* :mod:`OpenGLContext.character.humanoid` -- which node is which bone, read
  from ``VRMC_vrm`` or from the joint names, in VRM 1.0's bone vocabulary.
* :mod:`OpenGLContext.character.mixer` -- more than one clip playing at once:
  cross-fades, layers masked to part of the body, and additive layers.
* :mod:`OpenGLContext.character.attachment` -- hanging a weapon, a tool or a
  hat on a joint, through the attachment points a model declares.
* :mod:`OpenGLContext.character.levels` -- a coarser mesh to draw a figure as
  when it is far away, posed by the same skeleton as the near one.
* :mod:`OpenGLContext.character.crowd` -- every figure of a build posed in one
  pass rather than one at a time.
* :mod:`OpenGLContext.character.locomotion` -- a character's speed and state
  turned into clips, rates and footsteps, through a clip map.
* :mod:`OpenGLContext.character.gaitmeasure` -- how fast a clip carries a
  body, measured from the clip.
* :mod:`OpenGLContext.character.facing` -- heading, ground tilt and lean for a
  character's node, and the fit of a model to its capsule.

:class:`OpenGLContext.character.model.CharacterModel` is the three together
over one loaded document, which is what a game usually wants.
"""

from OpenGLContext.character.attachment import (
    SOCKET_PREFIX, attach, detach, sockets,
)
from OpenGLContext.character.humanoid import (
    BONE_PARENT, HUMAN_BONES, REQUIRED_BONES, Humanoid, bone_for_name,
)
from OpenGLContext.character.levels import add_level, levels_match
from OpenGLContext.character.mixer import AnimationMixer, Layer, Track
from OpenGLContext.character.model import CharacterModel

__all__ = [
    'BONE_PARENT', 'HUMAN_BONES', 'REQUIRED_BONES', 'Humanoid', 'bone_for_name',
    'AnimationMixer', 'Layer', 'Track',
    'SOCKET_PREFIX', 'attach', 'detach', 'sockets',
    'add_level', 'levels_match',
    'CharacterModel',
]
