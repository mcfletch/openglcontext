"""Movement modes as scenegraph nodes.

A mode is one named way of moving — walking, flying, swimming, first-person
mouse-look — declared as a ``PROTO`` like any other node, so it can be written
into a parsed file, carried in an ``SFNode`` field, and watched for change.

Each concrete mode declares **its own typed fields** for whatever it is
tunable by: one game's swim speed is 3 and another's is 10, and both are an
``SFFloat`` on :class:`SwimMode` rather than entries in a free-form mapping.
That buys validation, defaults and serialisation from the field system instead
of a parallel settings layer.

Two kinds of mode share the base class:

* **user-selected** — walk, fly, first-person.  The player chooses them.
* **world-imposed** — swim.  :meth:`MovementMode.enter_when` is how a mode says
  "I apply right now"; the mode itself decides, because only it knows what its
  trigger is.

A mode does not handle events.  It *samples* an
:class:`~OpenGLContext.events.inputstate.InputState` once per frame, so
several inputs act together — the reason walking and jumping at the same
moment needs no special case.
"""

from gettext import gettext as _
from typing import Any, Optional, Sequence, Tuple

from vrml import field, node


class KeyBinding(node.Node):
    """One command, what it is called, and the keys that trigger it.

    A node rather than a dict entry so a settings window can enumerate, label
    and rewrite bindings with no knowledge of any particular mode.
    """

    PROTO = 'KeyBinding'
    #: The command this triggers, as the mode names it.
    command = field.newField('command', 'SFString', 1, '')
    #: What a settings window shows the user.
    label = field.newField('label', 'SFString', 1, '')
    #: Key names, as the event system spells them; any one triggers it.
    keys = field.newField('keys', 'MFString', 1, list)
    #: A modifier that must be held with the key: ``shift``, ``ctrl``, ``alt``
    #: or empty for none.  It is what tells `ctrl` + arrow (tilt the view)
    #: apart from the same arrow alone (walk).
    modifier = field.newField('modifier', 'SFString', 1, '')

    #: How a generated settings page presents this; see
    #: :mod:`OpenGLContext.ui.generate`.
    UI_HINTS = {
        'keys': {'label': 'Keys', 'editor': 'keys'},
        'command': {'skip': True},
        'label': {'skip': True},
        'modifier': {'label': 'Held with',
                     'options': ('', 'shift', 'ctrl', 'alt'),
                     'optionLabels': ('none', 'Shift', 'Ctrl', 'Alt')},
    }


#: How long a turn must be held to reach ``turnAcceleration`` x ``turnRate``.
TURN_RAMP_SECONDS = 0.67

#: Which entry of the event system's modifier triple each name reads.
MODIFIER_INDEX = {'shift': 0, 'ctrl': 1, 'alt': 2}


class MovementMode(node.Node):
    """Base prototype: a named way of moving, with its own tunables."""

    PROTO = 'MovementMode'
    #: Whether the mode steers with the pointer and so wants it grabbed.
    capturePointer = field.newField('capturePointer', 'SFBool', 1, False)
    #: Radians of turn per second while a turn command is held.
    turnRate = field.newField('turnRate', 'SFFloat', 1, 2.0)
    #: Multiple of ``turnRate`` a held turn ramps up to, reached after
    #: :data:`TURN_RAMP_SECONDS`.  1.0 turns at a steady rate.  A viewer wants
    #: both a precise nudge and a quick spin in close quarters, and one rate
    #: gives only one of them.
    turnAcceleration = field.newField('turnAcceleration', 'SFFloat', 1, 1.0)
    #: How the mode is referred to when selecting one.
    name = field.newField('name', 'SFString', 1, '')
    #: A disabled mode is never selected and never claims the avatar.
    enabled = field.newField('enabled', 'SFBool', 1, True)
    #: Command-to-key bindings; replace wholesale to rebind.
    bindings = field.newField('bindings', 'MFNode', 1, list)

    #: Commands this mode acts on.  A settings window needs no more than this
    #: plus the bindings to present the mode.
    commands: Sequence[str] = ()

    #: How a generated settings page presents this mode's tunables.
    UI_HINTS = {
        # The name is how a game and a saved file refer to this mode, not
        # something a player chooses; renaming it from a settings screen would
        # break the binding file that stores keys under it.
        'name': {'skip': True},
        'enabled': {'label': 'Available'},
        'capturePointer': {'label': 'Steer with the mouse'},
    }

    def defaultBindings(self) -> Sequence[KeyBinding]:
        """The bindings a fresh instance starts with."""
        return []

    def __init__(self, **named: Any) -> None:
        super(MovementMode, self).__init__(**named)
        if not self.bindings:
            self.bindings = list(self.defaultBindings())

    def keys_for(self, command: str) -> Tuple[str, ...]:
        """The keys currently bound to ``command``."""
        for binding in self.bindings:
            if binding.command == command:
                return tuple(binding.keys)
        return ()

    def active(self, inputs: Any, command: str) -> bool:
        """Whether ``command`` is being asked for right now.

        A binding with a ``modifier`` needs that modifier held; a binding
        without one loses its key while another of this mode's bindings claims
        the same key with a modifier that *is* held, which is what stops
        `ctrl` + arrow walking forward as well as tilting the view.  A modifier
        no binding claims -- shift, which walking binds to run -- leaves the
        plain binding alone.
        """
        for binding in self.bindings:
            if binding.command != command:
                continue
            for key in binding.keys:
                if not inputs.held(key):
                    continue
                if binding.modifier:
                    index = MODIFIER_INDEX.get(binding.modifier)
                    if index is not None and inputs.modifiers(key)[index]:
                        return True
                elif not self._claimed(inputs, key):
                    return True
        return False

    def _claimed(self, inputs: Any, key: str) -> bool:
        """Whether a modified binding of this mode has taken ``key``."""
        for binding in self.bindings:
            index = MODIFIER_INDEX.get(binding.modifier)
            if (index is not None and binding.modifier
                    and key in binding.keys
                    and inputs.modifiers(key)[index]):
                return True
        return False

    def enter_when(self, platform: Any) -> bool:
        """Whether the world imposes this mode right now.

        False for a mode the player chooses.  A mode that the world can force —
        swimming, being carried, low gravity — overrides this, because the
        condition belongs to the mode and nothing else can know it.
        """
        return False

    def applyTo(self, platform: Any) -> None:
        """Put the body into the state this mode's movement assumes.

        Called when a mode takes over, and separate from :meth:`update`
        because it is a change of *state* rather than of velocity: whether the
        avatar falls, floats or swims is a property of the body, so a mode that
        only set a velocity would fly into the floor or swim through a wall.

        Every platform is asked and none is required to answer.  Most are a
        plain camera with no body under them at all, and a mode must work
        against one of those unchanged.
        """
        self._set(platform, 'set_fly', False)
        self._set(platform, 'set_swim', False)

    @staticmethod
    def _set(platform: Any, name: str, *args: Any, **named: Any) -> None:
        """Call one of the platform's body methods if it has one."""
        method = getattr(platform, name, None)
        if method is not None:
            method(*args, **named)

    #: Radians of turn per pixel of pointer motion, for the modes that steer
    #: with it.  Declared on the base because two modes want it and a player
    #: setting their sensitivity means it everywhere, not per mode.
    sensitivity = field.newField('sensitivity', 'SFFloat', 1, 0.003)
    #: Whether pushing the pointer forward looks down (flight-sim style).
    invertLook = field.newField('invertLook', 'SFBool', 1, False)

    def _mouseLook(self, inputs: Any, platform: Any) -> None:
        """Steer the gaze from this frame's pointer motion.

        Shared by every mode that takes the pointer, so a player's
        sensitivity and their inverted-look setting mean the same thing
        walking and swimming.  Duplicating it is how the two drift apart.
        """
        dx, dy = inputs.mouse_delta()
        if dx:
            # Positive turn swings right, and a rightward mouse gives a
            # positive dx, so this one passes straight through.
            platform.turn(dx * self.sensitivity)
        if dy:
            # The delta arrives in the pick point's origin -- y counting
            # *upward* -- so pushing the mouse forward gives a positive dy,
            # and positive look() tips the gaze *down*.  An un-inverted mouse
            # therefore subtracts: forward looks up.
            platform.look(-dy * self.sensitivity
                          * (-1.0 if self.invertLook else 1.0))

    def update(self, dt: float, inputs: Any, platform: Any) -> None:
        """Advance one frame from sampled input.  Overridden by each mode."""

    # -- helpers shared by the concrete modes ----------------------------
    #: How long the current turn has been held, and which way, for the ramp of
    #: :attr:`turnAcceleration`.  Not fields: this is the state of one gesture
    #: in progress, not something to save or edit.
    _turn_held: float = 0.0
    _turning: float = 0.0

    def _axis(self, inputs: Any, positive: str, negative: str) -> float:
        """A -1..1 axis from two commands of this mode."""
        return ((1.0 if self.active(inputs, positive) else 0.0)
                - (1.0 if self.active(inputs, negative) else 0.0))

    def _turn(self, dt: float, inputs: Any, platform: Any,
              rate: Optional[float] = None) -> None:
        """Apply the turn command every mode shares.

        ``platform.turn`` takes a **positive angle to swing right**, so the
        right-hand command passes its axis through unchanged.  That sense is
        the opposite of what deriving it from the yaw usually suggests: see
        :meth:`OpenGLContext.move.physicsplatform.PhysicsViewPlatform.turn`.

        The ramp resets when the turn stops or reverses, so the next tap starts
        slow again rather than overshooting at full speed.
        """
        if rate is None:
            rate = float(self.turnRate)
        turn = self._axis(inputs, 'turnright', 'turnleft')
        if turn and turn == self._turning:
            self._turn_held += dt
        else:
            self._turn_held = 0.0
        self._turning = turn
        if not turn:
            return
        peak = max(float(self.turnAcceleration), 1.0)
        ramp = min(1.0 + (peak - 1.0) * (self._turn_held / TURN_RAMP_SECONDS),
                   peak)
        platform.turn(turn * rate * ramp * dt)

class _GroundMode(MovementMode):
    """Shared behaviour of the modes that walk a surface."""

    #: Radians of pitch per second while a look command is held.
    lookRate = field.newField('lookRate', 'SFFloat', 1, 1.0)

    UI_HINTS = {
        'turnRate': {'label': 'Turn rate', 'minimum': 0.25, 'maximum': 8.0,
                     'step': 0.25, 'suffix': ' rad/s'},
        'lookRate': {'label': 'Look rate', 'minimum': 0.25, 'maximum': 8.0,
                     'step': 0.25, 'suffix': ' rad/s'},
        'turnAcceleration': {'label': 'Turn acceleration', 'minimum': 1.0,
                             'maximum': 6.0, 'step': 0.25, 'suffix': 'x'},
    }

    commands: Sequence[str] = (
        'forward', 'back', 'left', 'right', 'turnleft', 'turnright',
        'lookup', 'lookdown')

    def defaultBindings(self) -> Sequence[KeyBinding]:
        return [
            KeyBinding(command='forward', label=_('Forward'), keys=['w', '<up>']),
            KeyBinding(command='back', label=_('Back'), keys=['s', '<down>']),
            KeyBinding(command='left', label=_('Strafe left'), keys=['a']),
            KeyBinding(command='right', label=_('Strafe right'), keys=['d']),
            KeyBinding(command='turnleft', label=_('Turn left'), keys=['q', '<left>']),
            KeyBinding(command='turnright', label=_('Turn right'), keys=['e', '<right>']),
            KeyBinding(command='lookup', label=_('Look up'), keys=['<up>'],
                       modifier='ctrl'),
            KeyBinding(command='lookdown', label=_('Look down'), keys=['<down>'],
                       modifier='ctrl'),
        ]

    def _movement(self, inputs: Any) -> Tuple[float, float]:
        return (self._axis(inputs, 'forward', 'back'),
                self._axis(inputs, 'right', 'left'))

    def _look(self, dt: float, inputs: Any, platform: Any) -> None:
        """Tilt the view from the look commands.

        ``platform.look`` takes a **positive angle to look down**, so the
        look-*up* command subtracts.  Measured rather than derived; see
        :meth:`OpenGLContext.move.physicsplatform.PhysicsViewPlatform.look`.
        """
        pitch = self._axis(inputs, 'lookup', 'lookdown')
        if pitch:
            platform.look(-pitch * self.lookRate * dt)


class WalkMode(_GroundMode):
    """Walk, run and jump against gravity."""

    PROTO = 'WalkMode'
    walkSpeed = field.newField('walkSpeed', 'SFFloat', 1, 3.0)
    runSpeed = field.newField('runSpeed', 'SFFloat', 1, 6.0)

    UI_HINTS = {
        'walkSpeed': {'label': 'Walking speed', 'minimum': 0.5, 'maximum': 20.0,
                      'step': 0.5, 'suffix': ' m/s'},
        'runSpeed': {'label': 'Running speed', 'minimum': 0.5, 'maximum': 40.0,
                     'step': 0.5, 'suffix': ' m/s'},
    }

    commands: Sequence[str] = tuple(_GroundMode.commands) + ('run', 'jump')

    def defaultBindings(self) -> Sequence[KeyBinding]:
        return list(super(WalkMode, self).defaultBindings()) + [
            KeyBinding(command='run', label=_('Run'), keys=['<shift>']),
            KeyBinding(command='jump', label=_('Jump'), keys=[' ']),
        ]

    def update(self, dt: float, inputs: Any, platform: Any) -> None:
        forward, strafe = self._movement(inputs)
        self._turn(dt, inputs, platform, self.turnRate)
        self._look(dt, inputs, platform)
        running = inputs.held(*self.keys_for('run'))
        platform.set_move(forward=forward, strafe=strafe,
                          mode='run' if running else 'walk')
        # `pressed` rather than `held`: a jump is one launch per press, however
        # long the key stays down.
        if inputs.pressed(*self.keys_for('jump')):
            platform.jump()


class FlyMode(_GroundMode):
    """Free movement in three axes, ignoring gravity and geometry."""

    PROTO = 'FlyMode'
    flySpeed = field.newField('flySpeed', 'SFFloat', 1, 8.0)

    UI_HINTS = {
        'flySpeed': {'label': 'Flying speed', 'minimum': 0.5, 'maximum': 60.0,
                     'step': 0.5, 'suffix': ' m/s'},
    }

    commands: Sequence[str] = tuple(_GroundMode.commands) + ('up', 'down')

    def defaultBindings(self) -> Sequence[KeyBinding]:
        return list(super(FlyMode, self).defaultBindings()) + [
            KeyBinding(command='up', label=_('Rise'), keys=[' ']),
            KeyBinding(command='down', label=_('Sink'), keys=['c']),
        ]

    def applyTo(self, platform: Any) -> None:
        self._set(platform, 'set_fly', True)
        self._set(platform, 'set_swim', False)

    def update(self, dt: float, inputs: Any, platform: Any) -> None:
        forward, strafe = self._movement(inputs)
        self._turn(dt, inputs, platform, self.turnRate)
        self._look(dt, inputs, platform)
        platform.set_fly_move(forward=forward, strafe=strafe,
                              up=self._axis(inputs, 'up', 'down'))


class SwimMode(_GroundMode):
    """Movement while submerged — imposed by the world, not chosen.

    ``buoyancy`` is the fraction of gravity that pushes back up: 1.0 floats,
    0.0 sinks like a stone.
    """

    PROTO = 'SwimMode'
    swimSpeed = field.newField('swimSpeed', 'SFFloat', 1, 2.0)
    #: Steered with the pointer, like the mode a player was in a moment ago.
    capturePointer = field.newField('capturePointer', 'SFBool', 1, True)
    buoyancy = field.newField('buoyancy', 'SFFloat', 1, 0.9)

    UI_HINTS = {
        'swimSpeed': {'label': 'Swimming speed', 'minimum': 0.25,
                      'maximum': 20.0, 'step': 0.25, 'suffix': ' m/s'},
        'buoyancy': {'label': 'Buoyancy', 'minimum': 0.0, 'maximum': 1.0,
                     'step': 0.05},
    }
    commands: Sequence[str] = tuple(_GroundMode.commands) + ('up', 'down')

    def defaultBindings(self) -> Sequence[KeyBinding]:
        return list(super(SwimMode, self).defaultBindings()) + [
            KeyBinding(command='up', label=_('Swim up'), keys=[' ']),
            KeyBinding(command='down', label=_('Dive'), keys=['c']),
        ]

    def enter_when(self, platform: Any) -> bool:
        """Submerged, so the world has put the avatar in this mode."""
        return bool(self.enabled and getattr(platform, 'submerged', False))

    def applyTo(self, platform: Any) -> None:
        """Into the water, and **not** into the air.

        Flying is noclip and free of gravity; swimming collides with the pool
        it is in and is pulled by whatever fraction of gravity
        :attr:`buoyancy` leaves.  A swim implemented as a fly is a player who
        can leave a pool through its wall.
        """
        self._set(platform, 'set_fly', False)
        self._set(platform, 'set_swim', True, buoyancy=self.buoyancy)

    def update(self, dt: float, inputs: Any, platform: Any) -> None:
        """Swim, steering with the pointer and moving along the gaze.

        **Two things make this different from walking with the gravity off.**
        The pointer still steers, because a control scheme that changed the
        moment your feet left the floor would leave a player unable to aim in
        the one place they most need to; and *forward* means where you are
        looking, up and down included, because that is what swimming is. The
        dedicated up and down keys stay, for holding depth while looking
        somewhere else.
        """
        forward, strafe = self._movement(inputs)
        self._turn(dt, inputs, platform, self.turnRate)
        self._look(dt, inputs, platform)
        self._mouseLook(inputs, platform)
        up = self._axis(inputs, 'up', 'down')
        swim = getattr(platform, 'set_swim_move', None)
        if swim is None:
            # A plain camera has no swim move; it still has to go somewhere.
            platform.set_fly_move(forward=forward, strafe=strafe, up=up)
            return
        swim(forward=forward, strafe=strafe, up=up)


class FPSMode(WalkMode):
    """Walking with the mouse steering the view.

    ``sensitivity`` is radians of turn per pixel of mouse motion.
    """

    PROTO = 'FPSMode'
    capturePointer = field.newField('capturePointer', 'SFBool', 1, True)

    UI_HINTS = {
        'sensitivity': {'label': 'Mouse sensitivity', 'minimum': 0.0005,
                        'maximum': 0.02, 'step': 0.0005},
        'invertLook': {'label': 'Invert look'},
    }

    def update(self, dt: float, inputs: Any, platform: Any) -> None:
        super(FPSMode, self).update(dt, inputs, platform)
        self._mouseLook(inputs, platform)
