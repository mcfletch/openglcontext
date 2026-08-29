"""Figures that walk about on their own, so a crowd is a crowd of individuals.

A crowd where every figure plays the same clip from the same clock is one
figure drawn many times. What makes it a crowd is that each body is somewhere
else, facing somewhere else, and part way through something else -- walking,
picking up speed, coming to a halt, doing something while it is stopped,
turning, setting off again -- and that the renderer draws all of them in one
call anyway.

Three parts, each usable on its own:

:class:`Wander`
    Where every figure is, which way it faces, and what it is doing. A state
    machine over arrays with a figure axis on it, in the manner of
    :class:`~OpenGLContext.character.crowd.Crowd`'s posing: one pass of numpy
    for the whole field rather than one pass per figure. It holds no clips, no
    scenegraph and no GL, and its decisions come out of a named entropy stream,
    so a seeded session walks the same walk every time.

:class:`Gait`
    One figure's clips, dialled between standing still and running: its idles
    underneath, its walk and its run over them at the weight the body is
    travelling with. So a figure setting off, picking up speed or coming to a
    halt is a real blend of real clips, and every figure is at its own point in
    its own -- which is what the crowd has to be doing for one draw to be worth
    anything.

:class:`WanderingCrowd`
    The two of them tied to a :class:`~OpenGLContext.character.crowd.Crowd` and
    to the scenegraph, which is what an application usually wants::

        from functools import partial

        crowd = WanderingCrowd(
            (-9.0, 9.0, -14.0, 2.0), actions=2,
            gait=partial(Gait, walk='Walk', run='Run',
                         idle=['Survey', 'Sniff'],
                         walk_stride=0.82, run_stride=1.38))
        for _ in range(150):
            model = CharacterModel(load_gltf(document=document))
            scene.children.append(crowd.add(model))
        ...
        crowd.update(dt, mode=context)      # once a frame

**Heading is one number, and it is the number the scenegraph wants.** A figure
faces ``heading`` radians about +Y, which is exactly a ``Transform``'s
``rotation=(0, 1, 0, heading)``. That rotation turns +Z into
``(sin(heading), cos(heading))``, so heading is measured from +Z and a figure
walks along that vector; nothing has to hold a forward vector as well.

**Which way a model faces, and how far its walk carries it, are the model's
business and have to be measured.** The heading above assumes a figure whose
forward is +Z; one authored facing the other way is corrected once, with
:class:`WanderingCrowd`'s ``facing``, rather than by bending the arithmetic
around it. Both that and the strides come off one measurement: play the clip
and watch the vertices that are on the ground. They travel backwards under the
body at the speed the clip is carrying it forward, so their velocity is the
stride and its direction is the model's forward.

Neither is visible in a still frame -- a stride looks the same forwards and
backwards until something moves -- so guessing is what makes a crowd moonwalk,
sliding along while its legs stride the other way.
"""

from __future__ import annotations

from typing import Any, Callable, List, Optional, Sequence, Tuple, Union

import numpy as np

from OpenGLContext import entropy
from OpenGLContext.character.crowd import Crowd
from OpenGLContext.scenegraph.transform import Transform

__all__ = ['Gait', 'STAND', 'TURN', 'WALK', 'Wander', 'WanderingCrowd']

#: Standing still: the walk is fading out of the pose or already gone.
STAND = 0
#: Turning towards somewhere else, walking gently round rather than spinning.
TURN = 1
#: Walking, the whole of the clip in the pose.
WALK = 2


class Wander:
    """Where every figure of a field is, and what each of them is doing.

    A figure walks for a while, stands for a while, turns towards somewhere
    else and walks again; how long each of those lasts, how fast it walks and
    which way it turns are drawn per figure from a named entropy stream. It
    reaches the edge of the field, stops and turns back inwards, so a crowd
    stays a crowd instead of dispersing.

    Every attribute below is an array with one row per figure, read after each
    :meth:`step` and safe to read between them:

    ``position``
        ``(N, 2)`` of x and z, in metres.
    ``heading``
        ``(N,)`` radians about +Y -- a ``Transform`` rotation angle.
    ``moving``
        ``(N,)`` from 0 (standing) to 1 (walking), which is the weight a
        :class:`Gait` gives the walk. It eases between the two over ``fade``
        seconds, and it scales how fast the body travels, so a figure comes to
        a halt rather than stopping dead.
    ``speed``
        ``(N,)`` metres a second this figure walks at when it is walking.
    ``state``
        ``(N,)`` of :data:`STAND`, :data:`TURN` or :data:`WALK`.
    ``action``
        ``(N,)`` which of the model's idles a figure is doing. It steps on to
        the next one each time the figure comes to a halt, so a body that stops
        twice does two different things and a field of them is not a field
        doing one thing. Always 0 where the model has only one idle.
    ``walked``, ``turned``
        ``(N,)`` of whether the last :meth:`step` moved that figure, and
        whether it turned it. A figure walking straight ahead does not turn and
        a figure standing still does not move, so most of a field is neither
        each frame -- and writing a scenegraph node, a physics body or an audio
        emitter that has not moved is the sort of cost a crowd pays a hundred
        and fifty times over.
    """

    def __init__(self, bounds: Tuple[float, float, float, float] =
                 (-10.0, 10.0, -10.0, 10.0), *,
                 stream: str = 'wander',
                 speed: Tuple[float, float] = (0.75, 1.35),
                 walk: Tuple[float, float] = (2.5, 9.0),
                 stand: Tuple[float, float] = (0.8, 4.0),
                 turn_rate: float = 1.5,
                 turn_gait: float = 0.5,
                 fade: float = 0.35,
                 margin: float = 1.0,
                 actions: int = 1) -> None:
        #: ``(x0, x1, z0, z1)`` the figures keep inside.
        self.bounds = tuple(float(value) for value in bounds)
        #: Metres from the edge at which a walking figure turns back.
        self.margin = float(margin)
        self._speed = _pair(speed)
        self._walk = _pair(walk)
        self._stand = _pair(stand)
        self._turn_rate = float(turn_rate)
        #: How much of the walk plays while a figure is turning. Enough that
        #: the legs move it round rather than the body pivoting on the spot.
        self.turn_gait = float(turn_gait)
        #: Seconds a figure takes to go from standing to walking, or back.
        self.fade = float(fade)
        #: How many idles the model carries for a stopped figure to choose
        #: between; 1 is a model with one thing to do standing still.
        self.actions = max(1, int(actions))
        self._rng = entropy.generator(stream)
        self.position = np.zeros((0, 2), dtype='d')
        self.heading = np.zeros(0, dtype='d')
        self.goal = np.zeros(0, dtype='d')
        self.moving = np.zeros(0, dtype='d')
        self.speed = np.zeros(0, dtype='d')
        self.timer = np.zeros(0, dtype='d')
        self.state = np.zeros(0, dtype=np.int8)
        self.action = np.zeros(0, dtype=np.int32)
        self.walked = np.zeros(0, dtype=bool)
        self.turned = np.zeros(0, dtype=bool)
        self._pending: List[Tuple[float, float, float]] = []
        self._fresh = 0

    def __len__(self) -> int:
        return len(self.state) + len(self._pending)

    # -- membership --------------------------------------------------------
    def add(self, position: Optional[Sequence[float]] = None,
            heading: Optional[float] = None) -> int:
        """Take one more figure into the field, and answer with its row.

        Somewhere inside the bounds facing anywhere, unless told otherwise.
        The row is the index of every array above, and it does not move.
        """
        if position is None:
            x0, x1, z0, z1 = self.bounds
            position = (float(self._rng.uniform(x0, x1)),
                        float(self._rng.uniform(z0, z1)))
        if heading is None:
            heading = float(self._rng.uniform(-np.pi, np.pi))
        row = len(self)
        self._pending.append((float(position[0]), float(position[1]),
                              float(heading)))
        return row

    def _admit(self) -> None:
        """Fold everything :meth:`add` took in since the last step into the arrays."""
        if not self._pending:
            return
        taken = np.asarray(self._pending, dtype='d')
        self._pending = []
        count = len(taken)
        self.position = np.concatenate([self.position, taken[:, :2]])
        self.heading = np.concatenate([self.heading, taken[:, 2]])
        self.goal = np.concatenate([self.goal, taken[:, 2]])
        self.moving = np.concatenate([self.moving, np.zeros(count)])
        self.speed = np.concatenate([self.speed, self._draw(self._speed, count)])
        # Staggered, so a field built in one loop does not set off in one wave.
        self.timer = np.concatenate([self.timer, self._draw(self._walk, count)])
        self.state = np.concatenate(
            [self.state, np.full(count, WALK, dtype=np.int8)])
        # Spread over the idles, so the first figures to stop do not all stop
        # into the same one.
        self.action = np.concatenate(
            [self.action, self._rng.integers(0, self.actions, count,
                                             dtype=np.int32)])
        # Nothing has ever been told where these are, so the next step counts
        # them as having both moved and turned however still they are.
        self._fresh += count

    # -- the frame ---------------------------------------------------------
    def step(self, dt: float) -> None:
        """Move every figure on by ``dt`` seconds and settle what it is doing."""
        self._admit()
        step = max(0.0, float(dt))
        count = len(self.state)
        self.walked = np.zeros(count, dtype=bool)
        self.turned = np.zeros(count, dtype=bool)
        if self._fresh:
            self.walked[count - self._fresh:] = True
            self.turned[count - self._fresh:] = True
            self._fresh = 0
        if not count:
            return
        self.timer -= step
        self._halt()
        self._begin_turning()
        self._turn(step)
        self._ease(step)
        self._advance(step)

    def _halt(self) -> None:
        """Walking figures whose turn is up, and any that have reached the edge."""
        rows = np.flatnonzero((self.state == WALK)
                              & ((self.timer <= 0) | ~self._inside()))
        if not len(rows):
            return
        self.state[rows] = STAND
        self.timer[rows] = self._draw(self._stand, len(rows))
        # On to the next idle: a body that comes to a halt twice does two
        # different things, and over a field every idle gets shown.
        self.action[rows] = (self.action[rows] + 1) % self.actions

    def _begin_turning(self) -> None:
        """Figures that have stood long enough pick somewhere else to face."""
        rows = np.flatnonzero((self.state == STAND) & (self.timer <= 0))
        if not len(rows):
            return
        self.state[rows] = TURN
        self.goal[rows] = self._chosen_heading(rows)

    def _turn(self, dt: float) -> None:
        """Ease each turning figure round, and set the arrived ones walking."""
        rows = np.flatnonzero(self.state == TURN)
        if not len(rows):
            return
        delta = _wrap(self.goal[rows] - self.heading[rows])
        limit = self._turn_rate * dt
        self.heading[rows] = _wrap(self.heading[rows]
                                   + np.clip(delta, -limit, limit))
        self.turned[rows[delta != 0.0]] = True
        arrived = rows[np.abs(delta) <= limit]
        if len(arrived):
            self.state[arrived] = WALK
            self.timer[arrived] = self._draw(self._walk, len(arrived))

    def _ease(self, dt: float) -> None:
        """Move each figure's walk weight towards what its state asks for."""
        target = np.where(self.state == WALK, 1.0,
                          np.where(self.state == TURN, self.turn_gait, 0.0))
        limit = dt / self.fade if self.fade > 0 else np.inf
        self.moving += np.clip(target - self.moving, -limit, limit)

    def _advance(self, dt: float) -> None:
        """Carry every figure forward at the speed its walk is worth."""
        distance = self.speed * self.moving * dt
        self.walked |= distance > 0.0
        self.position[:, 0] += np.sin(self.heading) * distance
        self.position[:, 1] += np.cos(self.heading) * distance
        x0, x1, z0, z1 = self.bounds
        np.clip(self.position, (x0, z0), (x1, z1), out=self.position)

    # -- the decisions -----------------------------------------------------
    def _inside(self) -> np.ndarray:
        """Whether each figure is still clear of the edge by the margin."""
        x0, x1, z0, z1 = self.bounds
        low = np.asarray((x0 + self.margin, z0 + self.margin))
        high = np.asarray((x1 - self.margin, z1 - self.margin))
        return np.all((self.position >= low) & (self.position <= high), axis=1)

    def _chosen_heading(self, rows: np.ndarray) -> np.ndarray:
        """Where each of ``rows`` decides to face next.

        A real turn rather than a nudge, so that a figure setting off again is
        visibly going somewhere else; one that has walked out to the edge turns
        back towards the middle of the field instead of choosing freely, or it
        would spend the rest of the session against the boundary.
        """
        count = len(rows)
        turn = self._rng.uniform(0.7, np.pi, count) * self._rng.choice(
            np.asarray([-1.0, 1.0]), count)
        away = _wrap(self.heading[rows] + turn)
        x0, x1, z0, z1 = self.bounds
        centre = np.asarray(((x0 + x1) / 2.0, (z0 + z1) / 2.0))
        offset = centre - self.position[rows]
        inward = _wrap(np.arctan2(offset[:, 0], offset[:, 1])
                       + self._rng.uniform(-0.5, 0.5, count))
        return np.where(self._inside()[rows], away, inward)

    def _draw(self, span: Tuple[float, float], count: int) -> np.ndarray:
        return np.asarray(self._rng.uniform(span[0], span[1], count))


class Gait:
    """One figure's clips, dialled between standing still and running.

    Three layers over one another, made here on a model nothing has yet been
    played on, and held from then on:

    ``idle``
        What the figure does standing still, at full weight underneath
        everything. A model that carries several idles is given all of them and
        the figure cross-fades from one to the next as it stops, so a field of
        them is not a field doing one thing.
    ``walk``, ``run``
        The locomotion, at the weight the figure is moving with. Each is a lerp
        over what is beneath it, so a weight of 1 on ``walk`` and 0.4 on
        ``run`` is four tenths of the way from walking to running, and both at
        zero is the idle showing through untouched.

    ``walk_stride`` and ``run_stride`` are how far each clip carries a figure
    in a second when it is played at speed 1, in the units the figure is drawn
    at. They settle two things at once and neither can be guessed: how fast to
    run each clip's clock for the speed the body is travelling at, so the feet
    stay on the ground, and where the crossover from walking to running falls.
    Measure both -- see the note at the top of this module.
    """

    #: The layer the idle clips play on, always at full weight; the locomotion
    #: over it is what decides how much of it is seen.
    IDLE = 'idle'
    #: The layers the walk and the run play on, in that order over the idle.
    WALK = 'walk'
    RUN = 'run'

    def __init__(self, model: Any, walk: str, *,
                 run: Optional[str] = None,
                 idle: Union[str, Sequence[str], None] = None,
                 walk_stride: float = 1.0,
                 run_stride: Optional[float] = None,
                 fade: float = 0.35) -> None:
        mixer = getattr(model, 'mixer', model)
        #: The idle clips this figure has to choose between, in order.
        self.idles: List[str] = ([] if idle is None else
                                 [idle] if isinstance(idle, str) else list(idle))
        self.walk_stride = float(walk_stride)
        self.run_stride = float(run_stride if run_stride is not None
                                else walk_stride)
        #: Seconds an idle takes to cross-fade into the next.
        self.fade = float(fade)
        self.idle = mixer.layer(self.IDLE)
        self._showing = 0
        if self.idles:
            self.idle.play(self.idles[0])
        self.walk = mixer.layer(self.WALK, weight=0.0)
        self._walking = self.walk.play(walk)
        self.run = mixer.layer(self.RUN, weight=0.0)
        self._running = self.run.play(run) if run else None

    def apply(self, moving: float, speed: Optional[float] = None,
              action: int = 0) -> None:
        """Show ``moving`` of the locomotion over idle ``action``.

        ``moving`` is 0 for standing and 1 for travelling, and anything between
        is the blend of the two. ``speed`` is what the body is travelling at,
        which settles how fast the clips run and how much of the run is in the
        mix; left out, the clips keep whatever rate they are playing at and the
        walk is the whole of the locomotion. ``action`` picks which idle is
        showing, and a figure that stops somewhere else in the list cross-fades
        to it.
        """
        if self.idles:
            wanted = int(action) % len(self.idles)
            if wanted != self._showing:
                self._showing = wanted
                self.idle.play(self.idles[wanted], fade=self.fade)
        self.walk.weight = float(moving)
        if speed is None:
            return
        speed = float(speed)
        self._walking.speed = _rate(speed, self.walk_stride)
        if self._running is not None:
            self.run.weight = float(moving) * self._gallop(speed)
            self._running.speed = _rate(speed, self.run_stride)

    def _gallop(self, speed: float) -> float:
        """How much of the travel is a run rather than a walk, from 0 to 1.

        Nothing below what the walk was authored to carry, everything above
        what the run was; between them the two clips are mixed, which is what a
        body picking up speed looks like.
        """
        span = self.run_stride - self.walk_stride
        if span <= 0:
            return 1.0 if speed > self.walk_stride else 0.0
        return min(1.0, max(0.0, (speed - self.walk_stride) / span))


class WanderingCrowd:
    """A crowd of figures that walk about a field on their own.

    A :class:`~OpenGLContext.character.crowd.Crowd` posing every figure in one
    pass, a :class:`Wander` deciding where each of them goes, and a
    :class:`Gait` per figure turning that into the weights its clips blend at.
    Each figure gets a ``Transform`` of its own to stand in; mount that in the
    scenegraph and the rest follows from :meth:`update`.

    ``gait`` is what builds a figure's :class:`Gait`, for a model that needs
    telling where its standing frame is or how long its stride is::

        from functools import partial

        crowd = WanderingCrowd(bounds=(-9.0, 9.0, -14.0, 2.0),
                               gait=partial(Gait, still_at=0.5, stride=1.6))

    ``facing`` is radians added to the heading when a figure's node is turned,
    for a model whose forward is not +Z: ``math.pi`` for one authored facing
    -Z. Get it wrong and the crowd walks backwards through its own walk cycle,
    so measure it rather than guessing -- see the note at the top of this
    module.
    """

    def __init__(self, bounds: Tuple[float, float, float, float] =
                 (-10.0, 10.0, -10.0, 10.0), *,
                 crowd: Optional[Crowd] = None,
                 gait: Optional[Callable[[Any], Gait]] = None,
                 elevation: float = 0.0,
                 facing: float = 0.0,
                 scale: float = 1.0,
                 **named: Any) -> None:
        #: The crowd doing the posing; a caller reaches through it for the
        #: per-figure rates and the per-frame budget.
        self.crowd = crowd if crowd is not None else Crowd()
        #: Where the figures go.
        self.wander = Wander(bounds, **named)
        #: Height the figures stand at, since the field they walk is flat.
        self.elevation = float(elevation)
        #: Radians between the model's own forward and +Z.
        self.facing = float(facing)
        #: What each figure's node is scaled by, for a model authored at some
        #: size other than the metres the field is measured in. The strides a
        #: :class:`Gait` is given must be in the same units as the field, so
        #: scale a stride measured off the model by this too.
        self.scale = float(scale)
        self._gait = gait if gait is not None else _one_clip_gait
        self.gaits: List[Gait] = []
        self.transforms: List[Transform] = []

    def __len__(self) -> int:
        return len(self.transforms)

    @property
    def members(self) -> List[Any]:
        """The crowd's members, in the order figures were taken in."""
        return self.crowd.members

    def add(self, model: Any, position: Optional[Sequence[float]] = None,
            heading: Optional[float] = None) -> Transform:
        """Take a figure into the crowd; answer with the node to mount it by."""
        self.wander.add(position, heading)
        self.gaits.append(self._gait(model))
        self.crowd.add(model)
        transform = Transform(children=[model.group],
                              scale=(self.scale,) * 3)
        self.transforms.append(transform)
        return transform

    def update(self, dt: float, **named: Any) -> int:
        """Walk everyone on by ``dt`` seconds, then pose them.

        ``named`` goes to :meth:`~OpenGLContext.character.crowd.Crowd.update`,
        so the budget and the render mode are passed here; the count of figures
        posed comes back from it.
        """
        self.wander.step(dt)
        self._place()
        return self.crowd.update(dt, **named)

    def schedule(self, eye: Sequence[float],
                 bands: Sequence[Tuple[float, float]]) -> None:
        """Ask for fewer poses a second the further a figure is from ``eye``.

        ``bands`` is ``((metres, poses a second), ...)`` at increasing
        distances: a figure nearer than the first distance asks for the first
        rate, one past the last distance asks for the last rate, and a rate of
        0 means every frame. ``eye`` is a world position; its height is not
        read, since the figures are on the ground and the distance that matters
        is the one across it.

        Not posing a body nobody can see the detail of is the largest single
        lever a crowd has, and a field that walks about is a field where which
        figures those are changes every frame.
        """
        self.wander._admit()
        limits = np.asarray([float(band[0]) for band in bands])
        rates = np.asarray([float(band[1]) for band in bands])
        offset = self.wander.position - np.asarray((eye[0], eye[2]), dtype='d')
        distance = np.hypot(offset[:, 0], offset[:, 1])
        chosen = rates[np.minimum(np.searchsorted(limits, distance),
                                  len(rates) - 1)]
        for member, rate in zip(self.crowd.members, chosen.tolist(), strict=True):
            member.rate = rate

    def _place(self) -> None:
        """Put every figure where it has walked to, facing where it walks.

        The whole field is converted out of numpy in a few calls rather than a
        few per figure, and only the figures that actually moved are written:
        setting a scenegraph field validates the value and tells everything
        watching, which is far and away the largest thing here, and a field
        where most bodies are walking straight ahead turns hardly any of them.
        """
        wander = self.wander
        positions = wander.position.tolist()
        headings = wander.heading.tolist()
        moving = wander.moving.tolist()
        speeds = wander.speed.tolist()
        walked = wander.walked.tolist()
        turned = wander.turned.tolist()
        actions = wander.action.tolist()
        height, facing = self.elevation, self.facing
        for index, transform in enumerate(self.transforms):
            if walked[index]:
                x, z = positions[index]
                transform.translation = (x, height, z)
            if turned[index]:
                transform.rotation = (0.0, 1.0, 0.0, headings[index] + facing)
            self.gaits[index].apply(moving[index], speeds[index],
                                    actions[index])


def _pair(span: Any) -> Tuple[float, float]:
    """A ``(low, high)`` range, from one of those or from a single value."""
    try:
        low, high = span
    except TypeError:
        low = high = span
    return float(low), float(high)


def _one_clip_gait(model: Any) -> Gait:
    """The gait of a model nobody has described: its first clip, and nothing else.

    A figure then walks whatever that clip is and stands in the rest pose,
    which is what a one-clip model can do. A model carrying a walk, a run and
    an idle should be told which is which -- :class:`WanderingCrowd` takes a
    ``gait`` for exactly that -- since no naming convention says.
    """
    mixer = getattr(model, 'mixer', model)
    return Gait(model, walk=sorted(mixer.clips)[0])


def _rate(speed: float, stride: float) -> float:
    """How fast to run a clip's clock for a body travelling at ``speed``.

    1 where the clip carries nothing (an in-place cycle), since there is then
    no ground speed to keep up with and the authored rate is the only one that
    means anything.
    """
    return speed / stride if stride > 0 else 1.0


def _wrap(angle: Any) -> np.ndarray:
    """Angles brought back into ``(-pi, pi]``, so a turn takes the short way."""
    return np.asarray((np.asarray(angle) + np.pi) % (2.0 * np.pi) - np.pi)
