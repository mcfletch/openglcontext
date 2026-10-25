"""A character's state turned into the clips that show it.

A game that moves a character knows its speed, whether it is on the ground and
what it is doing. :class:`Locomotion` turns those into clips on a
:class:`~OpenGLContext.character.model.CharacterModel`: idle, walk, run and
sprint blended by speed, each looping clip played at the rate that keeps its
feet on the ground, the jump, fall, landing, slide, swim and knock-down clips
when the character is doing those, and a footstep when a foot lands.

    clips = ClipMap.ual()                           # a shipped vocabulary
    clips = ClipMap.guess(model)                    # roles found by name
    clips = ClipMap(idle='Idle', walk=('Walk', 1.4), run=('Run', 3.8),
                    jump_up='Jump', jump_down='Fall', land='Land')

    locomotion = Locomotion(clips, model)
    locomotion.on_footstep(lambda foot, phase: ...)
    ...
    settled = locomotion.update(LocomotionInput(speed=3.1, grounded=True), dt)
    model.update(dt)                                # once a frame, after

:class:`LocomotionInput` is the record a game fills each frame, from a physics
character or from its own simulation. :meth:`Locomotion.update` returns what it
settled on as a :class:`Settled`, which a test reads without a window.
Built with no model, a :class:`Locomotion` settles and raises footsteps and
plays nothing.

**A role is a job; a clip fills it.** :data:`ROLES` lists the jobs. A
:class:`ClipMap` says which clip does each, and for the looping ones the speed
in metres a second the clip was authored for (or measured at: see
:mod:`OpenGLContext.character.gaitmeasure`). A rate is the character's speed
over the authored speed, kept inside the map's ``rate_range``: below the range
the idle shows through instead of a walk in slow motion, and above it a clip
stays at its limit.

**The blend by speed is** :class:`~OpenGLContext.character.wander.Gait` **'s.**
The idle is underneath at full weight, the first locomotion clip lies over it
at the weight the body is moving with, and the next lies over that at the share
:func:`~OpenGLContext.character.wander.run_share` gives it. The map's walk, run
and sprint are those clips, in that order; a map without one of them uses the
next.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from OpenGLContext.character.gaitmeasure import measure_stride
from OpenGLContext.character.wander import Gait, run_share

log = logging.getLogger(__name__)

__all__ = [
    'ROLES', 'STATES', 'ClipSpec', 'ClipMap', 'LocomotionInput', 'Settled',
    'Locomotion',
]

#: What a clip can be for, in the order a map lists them.
ROLES = (
    'idle', 'walk', 'run', 'sprint', 'crouch_idle', 'crouch_walk',
    'jump_up', 'jump_down', 'land', 'slide', 'fall', 'swim', 'down',
    'get_up', 'death',
)
#: What a character can be doing, as :attr:`LocomotionInput.state` names it.
STATES = ('standing', 'crouching', 'sliding', 'airborne', 'down', 'swimming',
          'flying')

#: The speed in metres a second a looping role is played against when its
#: clip declares none and none can be measured.
DEFAULT_SPEEDS = {'walk': 1.4, 'run': 3.8, 'sprint': 6.0, 'crouch_walk': 0.9,
                  'swim': 1.5}
#: Below this many metres a second a character is standing still.
STAND_SPEED = 0.05
#: The speed of a landing, in metres a second, at which the landing clip shows
#: in full; slower landings show a share of it, no less than ``_MIN_LAND``.
HARD_LANDING = 6.0
_MIN_LAND = 0.25
#: Seconds a landing lasts when its clip's length is not known.
LAND_TIME = 0.35
#: A descent faster than this many metres a second plays the fall.
LONG_FALL = 6.0
#: Roles played as one action over the ground pose, and which of them loop.
_ACTIONS = ('jump_up', 'jump_down', 'fall', 'land', 'slide', 'swim', 'down',
            'get_up', 'death')
_LOOPING_ACTIONS = frozenset({'jump_down', 'fall', 'swim'})
_EPSILON = 1e-9


@dataclass(frozen=True)
class ClipSpec:
    """The clip that fills a role, and what is known about it."""

    clip: str
    #: Metres a second the clip was authored for, or None to measure it.
    speed: Optional[float] = None
    #: ``(foot, seconds into the clip)`` for each foot landing; None for the
    #: half cycle.
    contacts: Optional[tuple[tuple[str, float], ...]] = None
    #: Seconds one cycle (or a one-shot) lasts; None reads the model's clip.
    cycle: Optional[float] = None
    #: Seconds to fade into this role; None takes the map's.
    fade: Optional[float] = None


def _spec(value: Any) -> ClipSpec:
    if isinstance(value, ClipSpec):
        return value
    if isinstance(value, str):
        return ClipSpec(value)
    clip, speed = value
    return ClipSpec(str(clip), speed=float(speed))


class ClipMap:
    """Which clip fills each role.

    Roles are keyword arguments, each a clip name, a ``(clip name, authored
    speed)`` pair or a :class:`ClipSpec`; a role left out is not played. ``fade``
    is the seconds a role fades in over unless its spec says otherwise, and
    ``rate_range`` is the lowest and highest rate a looping clip plays at.

    :meth:`guess` also fills :attr:`unmatched` and :attr:`leftover`.
    """

    def __init__(self, *, fade: float = 0.15,
                 rate_range: tuple[float, float] = (0.55, 2.1),
                 **roles: Any) -> None:
        unknown = sorted(set(roles) - set(ROLES))
        if unknown:
            raise TypeError('unknown role %s; the roles are %s'
                            % (', '.join(unknown), ', '.join(ROLES)))
        self.fade = float(fade)
        self.rate_range = (float(rate_range[0]), float(rate_range[1]))
        self._specs = {role: _spec(roles[role]) for role in ROLES
                       if roles.get(role) is not None}
        #: Roles :meth:`guess` found no clip for.
        self.unmatched: tuple[str, ...] = ()
        #: Clips :meth:`guess` found no role for.
        self.leftover: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return 'ClipMap(%s)' % ', '.join(
            '%s=%r' % (role, spec.clip) for role, spec in self._specs.items())

    def spec(self, role: str) -> Optional[ClipSpec]:
        """The spec filling ``role``, or None."""
        return self._specs.get(role)

    def clips(self) -> tuple[str, ...]:
        """The clip names the map uses, once each, in role order."""
        return tuple(dict.fromkeys(spec.clip for spec in self._specs.values()))

    def missing(self, model: Any) -> tuple[str, ...]:
        """The roles whose clip ``model`` does not carry."""
        return tuple(role for role, spec in self._specs.items()
                     if spec.clip not in model.clips)

    def fade_for(self, role: str) -> float:
        """Seconds to fade into ``role``."""
        spec = self._specs.get(role)
        return self.fade if spec is None or spec.fade is None else spec.fade

    # -- vocabularies -----------------------------------------------------
    @classmethod
    def ual(cls) -> "ClipMap":
        """The Universal Animation Library's names.

        The speeds are the model's ground speeds in metres a second at rate 1,
        and the contacts the times its feet land, both from
        :func:`~OpenGLContext.character.gaitmeasure.measure` on the library's
        character. The roll plays for a knock-down and the library has no
        get-up clip.
        """
        return cls(
            idle='Idle_Loop',
            walk=ClipSpec('Walk_Loop', speed=1.0,
                          contacts=(('left', 0.0), ('right', 0.667))),
            run=ClipSpec('Jog_Fwd_Loop', speed=5.7,
                         contacts=(('right', 0.467), ('left', 0.904))),
            sprint=ClipSpec('Sprint_Loop', speed=8.3,
                            contacts=(('right', 0.313), ('left', 0.604))),
            crouch_idle='Crouch_Idle_Loop',
            crouch_walk=('Crouch_Fwd_Loop', 0.76),
            jump_up='Jump_Start', jump_down='Jump_Loop', fall='Jump_Loop',
            land='Jump_Land', slide='Slide', swim=('Swim_Fwd_Loop', 2.8),
            down='Roll', death='Death01')

    @classmethod
    def guess(cls, model: Any, **named: Any) -> "ClipMap":
        """Roles found by the words in ``model``'s clip names.

        A clip name is split into words at underscores, hyphens, digits and
        capitals, and a role takes the clip with the words it names and the
        fewest others, so ``Walk_Loop`` beats ``Walk_Formal_Loop``. A clip may
        fill more than one role. The roles nothing matched are in
        :attr:`unmatched` and the clips no role took in :attr:`leftover`, which
        is what to read before filling the gaps by hand. ``named`` is passed to
        the map: ``fade`` and ``rate_range``.
        """
        names = list(model.clips)
        words = {name: _words(name) for name in names}
        chosen: dict[str, str] = {}
        for role in ROLES:
            found = _best(role, names, words)
            if found is not None:
                chosen[role] = found
        roles: dict[str, Any] = {**named, **chosen}
        found_map = cls(**roles)
        found_map.unmatched = tuple(role for role in ROLES if role not in chosen)
        used = set(chosen.values())
        found_map.leftover = tuple(name for name in names if name not in used)
        return found_map


#: Per role, the word sets that name it in order of preference, and the words
#: that rule a clip out.
_NAMES: dict[str, tuple[tuple[frozenset[str], ...], frozenset[str]]] = {}


def _define(role: str, alternatives: Iterable[Iterable[str]],
            forbid: Iterable[str] = ()) -> None:
    _NAMES[role] = (tuple(frozenset(a) for a in alternatives), frozenset(forbid))


_OTHER_BODIES = ('crouch', 'swim', 'sit', 'sitting', 'talking', 'torch',
                 'pistol', 'rifle', 'sword', 'spell', 'combat', 'dance')
_define('idle', [('idle',)], _OTHER_BODIES)
_define('walk', [('walk',)], ('crouch', 'swim', 'back'))
_define('run', [('run',), ('jog',)], ('crouch', 'swim', 'sprint', 'back'))
_define('sprint', [('sprint',)], ('crouch',))
_define('crouch_idle', [('crouch', 'idle')])
_define('crouch_walk', [('crouch', 'walk'), ('crouch', 'fwd'),
                        ('crouch', 'move'), ('crouch', 'run')])
_define('jump_up', [('jump', 'start'), ('jump', 'up'), ('jump', 'takeoff'),
                    ('jump',)], ('land', 'loop', 'down', 'crouch'))
_define('jump_down', [('jump', 'down'), ('jump', 'loop'), ('jump', 'fall'),
                      ('fall',)], ('land', 'start'))
_define('land', [('land',)], ('start',))
_define('slide', [('slide',)])
_define('fall', [('fall',), ('jump', 'loop')], ('land', 'start'))
_define('swim', [('swim', 'fwd'), ('swim', 'loop'), ('swim',)], ('idle',))
_define('down', [('knocked',), ('knockdown',), ('down',), ('stumble',)],
        ('jump',))
_define('get_up', [('get', 'up'), ('getup',), ('stand', 'up'), ('rise',)])
_define('death', [('death',), ('die',), ('dying',), ('dead',)])

_WORD = re.compile(r'[A-Z]+(?![a-z])|[A-Z]?[a-z]+')


def _words(name: str) -> tuple[str, ...]:
    return tuple(word.lower() for word in _WORD.findall(name))


def _best(role: str, names: list[str],
          words: Mapping[str, tuple[str, ...]]) -> Optional[str]:
    """The clip of ``names`` that fills ``role`` best, or None."""
    alternatives, forbid = _NAMES[role]
    for required in alternatives:
        fits = [name for name in names
                if required <= set(words[name]) and not forbid & set(words[name])]
        if fits:
            return min(fits, key=lambda name: (
                len(words[name]) - len(required),
                min(words[name].index(w) for w in required), name))
    return None


@dataclass
class LocomotionInput:
    """What a game knows about a character this frame."""

    #: Ground speed in metres a second.
    speed: float = 0.0
    #: Up is positive.
    vertical_speed: float = 0.0
    grounded: bool = True
    #: One of :data:`STATES`.
    state: str = 'standing'
    #: How far through a slide the character is, from 0 to 1.
    slide_progress: float = 0.0
    #: The speed it hit the ground at in the frame it landed, else None.
    landing_speed: Optional[float] = None
    crouching: bool = False
    dead: bool = False


@dataclass(frozen=True)
class Settled:
    """What :meth:`Locomotion.update` settled on for a frame."""

    #: The role showing most.
    role: str
    #: Each clip's share of the pose, summing to 1 when anything plays.
    clips: Mapping[str, float]
    #: The playback rate of each looping clip showing.
    rates: Mapping[str, float]
    #: How far through the clip a held role (the slide) is, else None.
    progress: Optional[float] = None
    #: ``(foot, phase)`` of each foot that landed this frame, in order.
    footsteps: tuple[tuple[str, float], ...] = field(default_factory=tuple)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _stack(shares: list[float]) -> list[float]:
    """What each layer of a stack shows, from the weight it lies over the rest at.

    The last layer lies over all the others, so it shows ``shares[-1]`` and the
    one below it shows its own share of what is left.
    """
    shown = []
    left = 1.0
    for share in reversed(shares):
        shown.append(left * share)
        left *= 1.0 - share
    shown.reverse()
    return shown


@dataclass
class _Ground:
    """The pose of a character on the ground."""

    #: Each role's share of the pose.
    roles: dict[str, float]
    #: The same by clip, where roles share a clip.
    weights: dict[str, float]
    #: The playback rate of each cycle, by clip.
    rates: dict[str, float]
    #: The role showing most.
    role: str
    #: Whether that role is a cycle with feet to land.
    cycling: bool
    #: The weight each locomotion layer lies over the one below at.
    shares: list[float]
    #: What the crouch idle and the crouch walk show of the pose.
    crouch_idle: float
    crouch_walk: float


class Locomotion:
    """One character's clips, kept in step with what it is doing.

    ``model`` is the :class:`~OpenGLContext.character.model.CharacterModel` to
    play on, or None to settle without playing. The roles whose clip the model
    lacks are left out and named in :attr:`missing`. A looping role with no
    authored speed in the map is measured with
    :func:`~OpenGLContext.character.gaitmeasure.measure_stride` (a few
    milliseconds a clip) unless ``measure_missing`` is false; a clip that
    plants no foot, and a model with no skeleton, take
    :data:`DEFAULT_SPEEDS`. :attr:`speeds` has the speeds in use.
    """

    def __init__(self, clip_map: ClipMap, model: Any = None, *,
                 measure_missing: bool = True) -> None:
        self.clip_map = clip_map
        self.model = model
        #: The mapped roles the model has no clip for.
        self.missing: tuple[str, ...] = (
            () if model is None else clip_map.missing(model))
        self._specs = {role: spec for role in ROLES
                       if (spec := clip_map.spec(role)) is not None
                       and role not in self.missing}
        #: The speed each looping role is played against, in metres a second.
        self.speeds: dict[str, float] = {}
        for role in DEFAULT_SPEEDS:
            if role in self._specs:
                self.speeds[role] = self._speed_of(role, measure_missing)
        self._ladder: list[str] = [role for role in ('walk', 'run', 'sprint')
                                   if role in self._specs]
        self._footsteps: list[Callable[[str, float], None]] = []
        self._phase = 0.0
        self._crouch: Optional[float] = None
        self._action_role: Optional[str] = None
        self._land_left = 0.0
        self._land_share = 1.0
        self._get_up_left = 0.0
        self._was_down = False
        self._actions: dict[str, Any] = {}
        self._build_layers()

    # -- construction -----------------------------------------------------
    def _speed_of(self, role: str, measure_missing: bool) -> float:
        spec = self._specs[role]
        if spec.speed is not None:
            return spec.speed
        model = self.model
        if measure_missing and model is not None and model.humanoid is not None:
            try:
                found = measure_stride(model, spec.clip)
            except ValueError:
                found = 0.0
            if found > 0.0:
                log.info('%s: %s measured at %.2f m/s', role, spec.clip, found)
                return found
        return DEFAULT_SPEEDS[role]

    def _cycle_of(self, role: str) -> Optional[float]:
        """Seconds one cycle of ``role``'s clip lasts, or None if unknown."""
        spec = self._specs[role]
        if spec.cycle is not None:
            return spec.cycle
        if self.model is None:
            return None
        return float(self.model.clips[spec.clip].duration) or None

    def _build_layers(self) -> None:
        """The layers the roles play on, in the order they are laid over."""
        model = self.model
        self._gait: Optional[Gait] = None
        self._layers: dict[str, Any] = {}
        if model is None:
            return
        idle = self._specs.get('idle')
        ladder = self._ladder
        if ladder:
            self._gait = Gait(
                model, self._specs[ladder[0]].clip,
                run=self._specs[ladder[1]].clip if len(ladder) > 1 else None,
                idle=idle.clip if idle else None,
                walk_stride=self.speeds[ladder[0]],
                run_stride=self.speeds[ladder[1]] if len(ladder) > 1 else None,
                fade=self.clip_map.fade)
        elif idle is not None:
            model.layer('idle').play(idle.clip)
        if len(ladder) > 2:
            self._layers['sprint'] = self._looping_layer('sprint', ladder[2])
        for role in ('crouch_walk', 'crouch_idle'):
            if role in self._specs:
                self._layers[role] = self._looping_layer(role, role)
        self._layers['action'] = model.layer('action')

    def _looping_layer(self, name: str, role: str) -> Any:
        layer = self.model.layer(name, weight=0.0)
        layer.play(self._specs[role].clip)
        return layer

    # -- events -----------------------------------------------------------
    def on_footstep(self, function: Callable[[str, float], None]) -> None:
        """Call ``function(foot, phase)`` when a foot lands.

        ``foot`` is ``'left'`` or ``'right'`` and ``phase`` is the fraction of
        the cycle the contact falls at.
        """
        self._footsteps.append(function)

    def play_action(self, name: str, layer: str = 'upper', *,
                    fade: float = 0.1, loop: bool = False,
                    bones: Iterable[str] = ('spine',)) -> Any:
        """Play the clip ``name`` once on ``layer``, over the movement.

        The layer is made on first use and moves only the joints under
        ``bones`` (the upper body by default). It fades out when the clip ends.
        Returns the track, or None when there is no model or it has no such
        clip.
        """
        model = self.model
        if model is None or name not in model.clips:
            return None
        found = model.layer(layer, mask=model.mask(*bones))
        track = found.play(name, fade=fade, loop=loop, restart=True)
        self._actions[layer] = track
        return track

    # -- the frame --------------------------------------------------------
    def update(self, state: LocomotionInput, dt: float) -> Settled:
        """Settle ``state`` into clips for a frame of ``dt`` seconds.

        Plays them on the model, if there is one; the caller advances the model
        with :meth:`~OpenGLContext.character.model.CharacterModel.update`
        afterwards.
        """
        crouch = self._ease_crouch(state, dt)
        action, share, progress = self._action_for(state, dt)
        ground = self._ground(state.speed, crouch)
        clips = {name: weight * (1.0 - share)
                 for name, weight in ground.weights.items()}
        rates = dict(ground.rates)
        if action is not None:
            clip = self._specs[action].clip
            clips[clip] = clips.get(clip, 0.0) + share
            if action == 'swim':
                rates[clip] = self._rate('swim', state.speed)
        stepping = ground.cycling and action is None and state.grounded
        steps, phase = self._step(ground.role if stepping else None, rates, dt)
        self._play(ground, action, share, progress, phase)
        for foot, fraction in steps:
            for function in self._footsteps:
                function(foot, fraction)
        clips = {name: weight for name, weight in clips.items()
                 if weight > _EPSILON}
        role = action if action is not None and share >= 0.5 else ground.role
        return Settled(role=role, clips=clips,
                       rates={n: r for n, r in rates.items() if n in clips},
                       progress=progress, footsteps=steps)

    def _ease_crouch(self, state: LocomotionInput, dt: float) -> float:
        """How far into the crouch the pose is, from 0 to 1."""
        wanted = 1.0 if state.crouching or state.state == 'crouching' else 0.0
        if self._crouch is None:
            self._crouch = wanted
        else:
            fade = self.clip_map.fade_for('crouch_idle')
            step = 1.0 if fade <= 0 else dt / fade
            self._crouch += _clamp(wanted - self._crouch, -step, step)
        return self._crouch

    def _action_for(self, state: LocomotionInput, dt: float
                    ) -> tuple[Optional[str], float, Optional[float]]:
        """The action role showing, how much of the pose it takes, and progress."""
        specs = self._specs
        if state.landing_speed is not None and 'land' in specs:
            self._land_left = self._cycle_of('land') or LAND_TIME
            self._land_share = _clamp(state.landing_speed / HARD_LANDING,
                                      _MIN_LAND, 1.0)
        else:
            self._land_left -= dt
        down = state.state == 'down'
        if self._was_down and not down and 'get_up' in specs:
            self._get_up_left = self._cycle_of('get_up') or 0.0
        else:
            self._get_up_left -= dt
        self._was_down = down
        if state.dead and 'death' in specs:
            return 'death', 1.0, None
        if down and 'down' in specs:
            return 'down', 1.0, None
        if self._get_up_left > 0:
            return 'get_up', 1.0, None
        if state.state == 'swimming' and 'swim' in specs:
            return 'swim', 1.0, None
        if state.state == 'flying' and 'fall' in specs:
            return 'fall', 1.0, None
        if state.state == 'sliding' and 'slide' in specs:
            return 'slide', 1.0, _clamp(state.slide_progress, 0.0, 1.0)
        if state.state == 'airborne' or (
                not state.grounded and state.state not in ('swimming', 'flying')):
            role = self._airborne_role(state)
            if role is not None:
                return role, 1.0, None
        if self._land_left > 0 and 'land' in specs:
            return 'land', self._land_share, None
        return None, 0.0, None

    def _airborne_role(self, state: LocomotionInput) -> Optional[str]:
        specs = self._specs
        if state.vertical_speed > 0:
            return 'jump_up' if 'jump_up' in specs else None
        if state.vertical_speed < -LONG_FALL and 'fall' in specs:
            return 'fall'
        if 'jump_down' in specs:
            return 'jump_down'
        return 'fall' if 'fall' in specs else None

    def _rate(self, role: str, speed: float) -> float:
        """``speed`` over the role's authored speed, within the map's range."""
        low, high = self.clip_map.rate_range
        return _clamp(speed / self.speeds[role], low, high)

    def _moving(self, role: str, speed: float) -> float:
        """How much of the pose is the role's cycle rather than the idle."""
        if speed <= STAND_SPEED:
            return 0.0
        return min(1.0, speed / (self.speeds[role] * self.clip_map.rate_range[0]))

    def _ground(self, speed: float, crouch: float) -> _Ground:
        """The pose of a character on the ground at ``speed`` and ``crouch``."""
        specs, ladder = self._specs, self._ladder
        shares: list[float] = []
        idle_left = 1.0
        if ladder:
            shares.append(self._moving(ladder[0], speed))
            for low, high in zip(ladder, ladder[1:], strict=False):
                shares.append(shares[0] * run_share(
                    speed, self.speeds[low], self.speeds[high]))
            for share in shares:
                idle_left *= 1.0 - share
        crouch_idle, crouch_walk = self._crouched(crouch, speed)
        stand = 1.0 - crouch_idle - crouch_walk
        roles: dict[str, float] = {role: weight * stand for role, weight in
                                   zip(ladder, _stack(shares), strict=True)}
        if 'idle' in specs:
            roles['idle'] = idle_left * stand
        if 'crouch_idle' in specs:
            roles['crouch_idle'] = crouch_idle
        if 'crouch_walk' in specs:
            roles['crouch_walk'] = crouch_walk
        weights: dict[str, float] = {}
        for role, weight in roles.items():
            clip = specs[role].clip
            weights[clip] = weights.get(clip, 0.0) + weight
        cycles = [*ladder, *(('crouch_walk',) if 'crouch_walk' in specs else ())]
        rates = {specs[role].clip: self._rate(role, speed) for role in cycles}
        main = max(roles, key=lambda role: roles[role], default='idle')
        return _Ground(roles, weights, rates, main, main in cycles, shares,
                       crouch_idle, crouch_walk)

    def _crouched(self, crouch: float, speed: float) -> tuple[float, float]:
        """What the crouch idle and the crouch walk show of the pose.

        With both clips the crouch is ``crouch`` of the pose, split between
        them by how much the body moves. With one, that one carries it, the
        walk only while moving. With neither the standing pose is kept.
        """
        specs = self._specs
        idle, walk = 'crouch_idle' in specs, 'crouch_walk' in specs
        moving = self._moving('crouch_walk', speed) if walk else 0.0
        if idle and walk:
            return crouch * (1.0 - moving), crouch * moving
        if idle:
            return crouch, 0.0
        if walk:
            return 0.0, crouch * moving
        return 0.0, 0.0

    # -- the footsteps ----------------------------------------------------
    def _step(self, role: Optional[str], rates: Mapping[str, float], dt: float
              ) -> tuple[tuple[tuple[str, float], ...], float]:
        """Move the cycle on, and say which feet landed and where it was.

        ``role`` is the cycle being walked, or None when no foot is on the
        ground to step. Returns the landings in order and the phase the cycle
        was at when the frame began.
        """
        before = self._phase
        cycle = None if role is None else self._cycle_of(role)
        if role is None or cycle is None:
            return (), before
        self._phase = before + dt * rates[self._specs[role].clip] / cycle
        found = []
        for foot, fraction in self._contacts(role, cycle):
            lap = math.floor(before - fraction) + 1
            while lap + fraction <= self._phase:
                found.append((lap + fraction, foot, fraction % 1.0))
                lap += 1
        found.sort()
        return tuple((foot, fraction) for _at, foot, fraction in found), before

    def _contacts(self, role: str, cycle: float) -> list[tuple[str, float]]:
        """``(foot, fraction of the cycle in (0, 1])`` for each landing of ``role``."""
        given = self._specs[role].contacts
        raw = given if given is not None else (('left', 0.0), ('right', cycle / 2))
        return [(foot, (at / cycle) % 1.0 or 1.0) for foot, at in raw]

    # -- the mixer --------------------------------------------------------
    def _play(self, ground: _Ground, action: Optional[str], share: float,
              progress: Optional[float], phase: float) -> None:
        """Put the settled pose on the model's layers."""
        model = self.model
        if model is None:
            return
        self._play_ground(ground, phase)
        self._play_action(action, share, progress)
        for layer, track in list(self._actions.items()):
            if track.finished:
                model.layer(layer).stop(fade=0.1)
                del self._actions[layer]

    def _play_ground(self, ground: _Ground, phase: float) -> None:
        ladder, specs, shares = self._ladder, self._specs, ground.shares
        tracks: list[tuple[Any, str]] = []
        if self._gait is not None:
            self._gait.apply(shares[0], None)
            layers = [self._gait.walk, self._gait.run][:len(ladder)]
            for layer, share in zip(layers[1:], shares[1:], strict=False):
                layer.weight = share
            tracks.extend(zip(layers, ladder, strict=False))
        if 'sprint' in self._layers:
            self._layers['sprint'].weight = shares[2]
            tracks.append((self._layers['sprint'], ladder[2]))
        if 'crouch_walk' in self._layers:
            left = 1.0 - ground.crouch_idle
            self._layers['crouch_walk'].weight = (
                ground.crouch_walk / left if left > _EPSILON else 0.0)
            tracks.append((self._layers['crouch_walk'], 'crouch_walk'))
        if 'crouch_idle' in self._layers:
            self._layers['crouch_idle'].weight = ground.crouch_idle
        for layer, role in tracks:
            track = layer.current
            track.speed = ground.rates[specs[role].clip]
            track.time = (phase % 1.0) * track.duration

    def _play_action(self, action: Optional[str], share: float,
                     progress: Optional[float]) -> None:
        layer = self._layers['action']
        if action is None:
            if self._action_role is not None:
                layer.stop(fade=self.clip_map.fade_for(self._action_role))
                self._action_role = None
            return
        clip = self._specs[action].clip
        if action != self._action_role:
            previous = self._action_role
            same_clip = previous is not None and self._specs[previous].clip == clip
            layer.play(clip, fade=self.clip_map.fade_for(action),
                       loop=action in _LOOPING_ACTIONS, restart=not same_clip)
            self._action_role = action
        layer.weight = share
        track = layer.current
        if action == 'slide':
            track.speed = 0.0
            track.time = (progress or 0.0) * track.duration
