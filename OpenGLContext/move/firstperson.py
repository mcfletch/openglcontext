"""A character seen through its own eyes: the movement keys walk it, the camera is at its eyes.

``context.follow(character, view='eyes')`` makes an :class:`EyesController`. It
is the first-person counterpart of
:class:`~OpenGLContext.move.thirdperson.FollowController`: the same frame hooks,
the camera a :class:`~OpenGLContext.move.physicsplatform.PhysicsViewPlatform`
over the character, and the declared walk and fly modes in place of the follow
mode::

    hero = self.physics.add_character(position=(0, 0, 5))
    walker = self.follow(hero, view='eyes')
    walker.navigation.select('fly')
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from OpenGLContext.move.modes import walk_fly_modes
from OpenGLContext.move.physicsplatform import PhysicsViewPlatform
from OpenGLContext.move.thirdperson import FollowController

if TYPE_CHECKING:
    from OpenGLContext.physics.character import Character

__all__ = ['EyesController']


class EyesController(FollowController):
    """Has a character obey the keys of walk and fly modes, with the camera at its eyes.

    ``modes`` are the movement modes, the first in force; the default is the
    engine's walk and fly modes (:func:`~OpenGLContext.move.modes.walk_fly_modes`).
    ``yaw`` is the heading the camera starts at, in radians about +Y, 0
    looking along -Z. Selecting a mode puts the character in that mode's state:
    ``navigation.select('fly')`` lifts it off the ground.
    """

    def __init__(self, context: Any, character: Character,
                 modes: Sequence[Any] | None = None, yaw: float = 0.0) -> None:
        self.drive(context, character, PhysicsViewPlatform.over(character, yaw=yaw),
                   list(modes) if modes else list(walk_fly_modes()))
