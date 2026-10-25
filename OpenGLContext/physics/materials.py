"""The physics materials of a context: presets, the ones the application defines, and pair rules.

A material says how a surface grips, bounces and sounds. The presets of
:data:`omi_physics.model.MATERIAL_PRESETS` (``wood``, ``metal``, ``rubber``,
``ice``) are there from the start; :meth:`Materials.define` adds others, and
:meth:`Materials.pair` overrides the friction between two of them. A body takes
a material by name::

    physics.materials.define('mud', friction=0.9, restitution=0.0, sound='squelch.ogg')
    physics.add_static(floor, material='mud')

A material with a ``sound`` plays it where a body of that material is struck.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from omi_physics import model

if TYPE_CHECKING:
    from OpenGLContext.audio.manager import SoundSource
    from OpenGLContext.physics.service import Physics

__all__ = ['Materials', 'PhysicsMaterial']


@dataclass(frozen=True)
class PhysicsMaterial:
    """A named material: how it grips and bounces, and the sound a strike on it makes."""
    name: str
    material: model.Material
    sound: SoundSource | None = None
    #: A clip played where a character's foot lands on a body of this material.
    footstep: SoundSource | None = None


class Materials:
    """The materials of one physics service."""

    def __init__(self, physics: Physics) -> None:
        self._physics = physics
        self._known: dict[str, PhysicsMaterial] = {
            name: PhysicsMaterial(name, material)
            for name, material in model.MATERIAL_PRESETS.items()}

    @property
    def names(self) -> list[str]:
        """The names a body may take, presets first."""
        return list(self._known)

    def get(self, name: str) -> PhysicsMaterial:
        """The material called ``name``; ValueError naming the known ones if there is none."""
        found = self._known.get(name)
        if found is None:
            raise ValueError('no material is called %r; the materials are %s'
                             % (name, ', '.join(self._known)))
        return found

    def define(self, name: str, friction: float | None = None, restitution: float | None = None,
               sound: SoundSource | None = None, static_friction: float | None = None,
               dynamic_friction: float | None = None,
               footstep: SoundSource | None = None) -> PhysicsMaterial:
        """Make a material called ``name``; defining it again replaces it.

        ``friction`` sets both coefficients, ``static_friction`` and
        ``dynamic_friction`` one each. ``restitution`` is the fraction of the
        closing speed a bounce keeps. ``sound`` is a clip played where a body
        of this material is struck, and ``footstep`` one played where a
        character's foot lands on it. Each is a path, URL, name given to
        ``audio.load`` or a decoded :class:`~omi_audio.clip.Clip`.
        """
        base = model.Material()
        material = model.Material(
            staticFriction=_pick(base.staticFriction, static_friction, friction),
            dynamicFriction=_pick(base.dynamicFriction, dynamic_friction, friction),
            restitution=_pick(base.restitution, restitution))
        made = PhysicsMaterial(name, material, sound, footstep)
        self._known[name] = made
        self._physics._send_world('material', name, material)
        return made

    def pair(self, first: str, second: str, friction: float | None = None,
             static_friction: float | None = None,
             dynamic_friction: float | None = None) -> None:
        """Set the friction between bodies of two materials, in place of what the two combine to."""
        one, other = self.get(first), self.get(second)
        static = static_friction if static_friction is not None else friction
        dynamic = dynamic_friction if dynamic_friction is not None else friction
        if static is None or dynamic is None:
            raise ValueError('pair needs friction, or both static_friction and dynamic_friction')
        self._physics._send_world('pair_friction', one.name, other.name, float(static), float(dynamic))

    def sound_of(self, name: str | None) -> SoundSource | None:
        """The sound of the material called ``name``, or None."""
        found = self._known.get(name) if name else None
        return None if found is None else found.sound

    def footstep_of(self, name: str | None) -> SoundSource | None:
        """The footstep clip of the material called ``name``, or None."""
        found = self._known.get(name) if name else None
        return None if found is None else found.footstep

    @property
    def has_footsteps(self) -> bool:
        """Whether any material has a footstep clip."""
        return any(known.footstep is not None for known in self._known.values())

    @property
    def has_sounds(self) -> bool:
        """Whether any material has a sound."""
        return any(known.sound is not None for known in self._known.values())


def _pick(default: float, *values: float | None) -> float:
    """The first of ``values`` that is given, else ``default``, as a float."""
    for value in values:
        if value is not None:
            return float(value)
    return float(default)
