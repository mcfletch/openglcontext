"""A scene's X3D sound nodes as one engine's processing graph, kept in step once a frame

:class:`SoundGraph` is the engine side of :mod:`OpenGLContext.scenegraph.x3dsound`.
Each frame it is handed the scene's top-level sound nodes, each with its world
matrix, and the time. It walks from them through every node's inputs, makes
each X3D node's :mod:`omi_audio.graph` node the first time it meets it,
advances each node's time and writes its fields onto its graph node, rewires
the graph where the scene's wiring has changed, and places the Sound and
SpatialSound nodes for the listener.

What is heard (ISO/IEC 19775-1, 16.2):

- each enabled AudioDestination and StreamAudioDestination;
- each Sound and SpatialSound that no destination reads, as a VRML97 Sound is
  heard.

A source in no destination is made and timed but not heard.

The listener is the camera, or a ListenerPointSource whose
`trackCurrentView` is FALSE. Where more Sound and SpatialSound nodes are heard
than the ``budget`` of voices, those that rank lowest are silenced: higher
`priority` first; among those above 0.5, the more recently heard; then the
louder at the listener (16.4.2).

Given the frame's :class:`~OpenGLContext.audio.acoustics.Acoustics`, each
Sound and SpatialSound is heard at the share its straight path to the listener
passes through the scene's acoustic surfaces.

MicrophoneSource and StreamAudioSource open an input only with ``capture``
true, and only while they are heard and running; the input is closed when
either stops.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Iterable, Sequence
from typing import Any, Optional

from omi_audio.device import CaptureDevice, open_capture
from omi_audio.engine import AudioEngine
from omi_audio.spatial import Listener

from OpenGLContext.audio.acoustics import Acoustics
from OpenGLContext.scenegraph import x3dsound

log = logging.getLogger(__name__)

__all__ = ['SoundGraph', 'audible', 'open_capture']

#: Voices a graph hears at once where its caller gives no budget.
DEFAULT_BUDGET = 32


def audible(candidates: Sequence[tuple[Any, x3dsound.Placement, float, float]],
            budget: int) -> set[Any]:
    """The nodes heard among ``candidates`` of ``(node, placement, priority, since)``

    At most ``budget`` of them: higher priority first, then for priorities
    above 0.5 the one heard since later, then the louder.
    """
    if len(candidates) <= budget:
        return {candidate[0] for candidate in candidates}

    def rank(candidate: tuple[Any, x3dsound.Placement, float, float]) -> tuple[float, float, float]:
        _, placement, priority, since = candidate
        return (-priority, -since if priority > 0.5 else 0.0, -placement.level)

    ranked = sorted(candidates, key=rank)
    return {candidate[0] for candidate in ranked[:max(0, budget)]}


class _Walk:
    """Every sound node reached from a frame's roots, and what each reads

    `inputs` are each node's sources as ``(node, channel)``: its own inputs
    whole, and the channel each ChannelSplitter listing it among its
    `outputs` gives it. `matrices` is the world matrix of the root each node
    was first reached from. `destined` holds what a destination reads.
    """

    def __init__(self, roots: Sequence[tuple[Any, Any]]) -> None:
        self.order: list[Any] = []
        self.matrices: dict[Any, Any] = {}
        self.destined: set[Any] = set()
        own: dict[Any, list[Any]] = {}
        split: dict[Any, list[tuple[Any, int]]] = {}
        for root, matrix in roots:
            if not isinstance(root, x3dsound.SoundNode):
                continue
            stack = [root]
            while stack:
                current = stack.pop()
                if current in self.matrices:
                    continue
                self.matrices[current] = matrix
                self.order.append(current)
                own[current] = current.audioInputs()
                stack.extend(reversed(own[current]))
                for channel, output in enumerate(current.audioOutputs()):
                    split.setdefault(output, []).append((current, channel))
                    stack.append(output)
        self.inputs: dict[Any, list[tuple[Any, Optional[int]]]] = {
            current: [(source, None) for source in own[current]] + list(split.get(current, ()))
            for current in self.order}
        self.roots = [root for root, _ in roots if root in self.matrices]
        stack = [source for root in self.roots if isinstance(root, x3dsound.Destination)
                 for source, _ in self.inputs[root]]
        while stack:
            current = stack.pop()
            if current not in self.destined:
                self.destined.add(current)
                stack.extend(source for source, _ in self.inputs[current])


class SoundGraph:
    """One engine's graph of a scene's X3D sound nodes"""

    def __init__(self, engine: AudioEngine) -> None:
        self.engine = engine
        self._made: dict[Any, Any] = {}
        self._wiring: list[Any] = []
        self._planned: set[Any] = set()
        self._last: dict[tuple[Any, str], Any] = {}
        self._captures: dict[Any, CaptureDevice] = {}
        self._since: dict[Any, float] = {}
        self._reported: set[str] = set()
        self._heard: tuple[Any, ...] = ()
        self._nodes: tuple[Any, ...] = ()
        #: How long the latest :meth:`update` took, in seconds.
        self.seconds = 0.0

    def __repr__(self) -> str:
        return '<%s %d nodes, %d heard>' % (type(self).__name__, len(self._made),
                                            len(self._heard))

    @property
    def heard(self) -> tuple[Any, ...]:
        """The X3D nodes whose output is heard"""
        return self._heard

    @property
    def nodes(self) -> tuple[Any, ...]:
        """The X3D nodes the latest :meth:`update` drove, each before its inputs"""
        return self._nodes

    def audioNode(self, found: Any) -> Any:
        """The graph node ``found`` plays as, or None where it is not in this graph"""
        return self._made.get(found)

    def changed(self, owner: Any, key: str, value: Any) -> bool:
        """Whether ``value`` differs from the last given for ``owner`` and ``key``; records it

        A number or a string compares by value, anything else by identity.
        """
        name = (owner, key)
        if name in self._last:
            previous = self._last[name]
            if previous is value or (isinstance(value, (int, float, str))
                                     and type(previous) is type(value) and previous == value):
                return False
        self._last[name] = value
        return True

    # ------------------------------------------------------------------

    def update(self, roots: Sequence[tuple[Any, Any]], now: float,
               listener: Optional[Listener] = None, budget: int = DEFAULT_BUDGET,
               capture: bool = False, acoustics: Optional[Acoustics] = None) -> int:
        """Keep the graph in step with ``roots`` at time ``now``; how many nodes it drove

        ``roots`` are the frame's top-level sound nodes, each with its world
        matrix. ``listener`` is the camera's; the engine's where None.
        ``budget`` is how many Sound and SpatialSound nodes are heard at once,
        ``capture`` whether an input may be opened, and ``acoustics`` the
        frame's acoustic surfaces.
        """
        started = time.perf_counter()
        walk = _Walk(roots)
        fresh = set()
        for found in walk.order:
            if found not in self._made:
                self._made[found] = found.makeAudio(self)
                fresh.add(found)
        for found in walk.order:
            found.applyAudio(self._made[found], self)
            advance = getattr(found, 'advance', None)
            if advance is not None:
                advance(now)
        heard = self._choose(walk)
        wiring = self._describe(walk, heard)
        planned = self._planned
        if wiring != self._wiring:
            planned = self._rewire(walk, heard)
            self._wiring = wiring
            self._forget(walk)
        for found in walk.order:
            rejoined = found in fresh or (found in planned and found not in self._planned)
            found.runAudio(self._made[found], rejoined)
        self._planned = planned
        self._capture(walk, capture)
        self._place(walk, listener if listener is not None else self.engine.listener,
                    budget, now, acoustics)
        for found in walk.order:
            if found in fresh:
                self._made[found].settle()
            found.reportAudio(self._made[found], self)
        self._nodes = tuple(walk.order)
        self.seconds = time.perf_counter() - started
        return len(walk.order)

    def clear(self) -> None:
        """Hear nothing, close every input and let every node go"""
        self.update((), 0.0)

    def close(self) -> None:
        """:meth:`clear`; the graph may be used again"""
        self.clear()

    # ------------------------------------------------------------------

    def _choose(self, walk: _Walk) -> tuple[Any, ...]:
        """The nodes heard, each once: destinations, and placed sounds no destination reads"""
        chosen: dict[Any, None] = {}
        for root in walk.roots:
            if isinstance(root, x3dsound.Destination):
                active = bool(root.enabled)
                if self.changed(root, 'isActive', active):
                    root.isActive = active
                if active:
                    chosen[root] = None
            elif isinstance(root, x3dsound.Placed) and root not in walk.destined:
                chosen[root] = None
        self._heard = tuple(chosen)
        return self._heard

    @staticmethod
    def _describe(walk: _Walk, heard: Iterable[Any]) -> list[Any]:
        """The wiring as one flat list, compared frame to frame"""
        described: list[Any] = []
        for found in walk.order:
            described.append(found)
            for source, channel in walk.inputs[found]:
                described.extend((source, channel))
            described.append(None)
        described.extend(heard)
        return described

    def _rewire(self, walk: _Walk, heard: Sequence[Any]) -> set[Any]:
        """Connect every graph node to its inputs and compile; the X3D nodes now rendered"""
        made = self._made
        for found in walk.order:
            audio = made[found].disconnect()
            for source, channel in walk.inputs[found]:
                audio.connect(made[source], channel)
        try:
            self.engine.graph.set_outputs([made[found] for found in heard])
        except ValueError as error:
            self._report('wiring', 'the X3D sound graph is not heard: %s' % (error,))
            self.engine.graph.set_outputs([])
        rendered = set(self.engine.graph.nodes)
        return {found for found in walk.order if made[found] in rendered}

    def _forget(self, walk: _Walk) -> None:
        """Let go of the nodes this frame did not reach"""
        reached = set(walk.order)
        for gone in [found for found in self._made if found not in reached]:
            del self._made[gone]
            if self._last.get((gone, 'isActive')):
                gone.isActive = False
            self._since.pop(gone, None)
            device = self._captures.pop(gone, None)
            if device is not None:
                device.close()
        self._last = {name: value for name, value in self._last.items() if name[0] in reached}

    def _capture(self, walk: _Walk, allowed: bool) -> None:
        """Open each heard, running input where capture is allowed; close the rest"""
        for found in walk.order:
            if not isinstance(found, x3dsound.Captured):
                continue
            wanted = allowed and found in self._planned and bool(found.running())
            device = self._captures.get(found)
            if wanted and device is None:
                audio = self._made[found]
                device = open_capture(self.engine.sample_rate, found.captureDevice(),
                                      ring=audio.ring)
                device.start()
                self._captures[found] = device
            elif not wanted and device is not None:
                device.close()
                del self._captures[found]
            if not allowed and found in self._planned:
                self._report('capture', '%s is silent: audio capture is off '
                             '(AudioSettings.microphone)' % (type(found).__name__,))

    def _place(self, walk: _Walk, listener: Listener, budget: int, now: float,
               acoustics: Optional[Acoustics] = None) -> None:
        """Place every Sound and SpatialSound for the listener, within the budget,
        each at the share of it the acoustic surfaces pass"""
        for found in walk.order:
            if isinstance(found, x3dsound.ListenerPointSource):
                point = found.listener(walk.matrices[found])
                if point is not None:
                    listener = point
                    break
        hearing = x3dsound.Hearing(listener)
        placed = [found for found in walk.order if isinstance(found, x3dsound.Placed)]
        placements = [found.placement(walk.matrices[found], hearing) for found in placed]
        if acoustics:
            behind = [index for index, placement in enumerate(placements)
                      if placement.level > 0.0]
            shares = acoustics.occlusions(
                [placed[index].origin(walk.matrices[placed[index]]) for index in behind],
                hearing.position)
            for index, share in zip(behind, shares.tolist(), strict=True):
                placements[index] = x3dsound.scaled(placements[index], share)
        candidates = [(found, placement, float(found.priority), self._since.setdefault(found, now))
                      for found, placement in zip(placed, placements, strict=True)]
        chosen = audible(candidates, budget)
        for found, placement, _, _ in candidates:
            found.placeAudio(self._made[found], placement if found in chosen else x3dsound.SILENT)

    def _report(self, kind: str, message: str) -> None:
        """Log ``message`` once for this graph"""
        if kind not in self._reported:
            self._reported.add(kind)
            log.warning(message)
