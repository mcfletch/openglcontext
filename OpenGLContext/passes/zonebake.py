"""Baking the environment each zone captures, so a run draws none.

A zone whose environment asks for a capture (``ZoneEnvironment.capture``) is
drawn six times over, for every bounce, the first time it is needed
(:mod:`~OpenGLContext.passes.zoneprobes`). A world that ships its zones can
instead be baked once: :func:`bake_zone_lights` stands the camera at each
capturing zone's capture point, draws frames until the pass has finished that
zone's captures, and reads the probe layer back. What it returns is what an
``EXT_lights_image_based`` light holds -- an irradiance cube and the
prefiltered mips -- for the caller to write into its document, a game's cache,
or wherever it keeps them.

:class:`ZoneBakePlan` is the scheduling, with no GL: which zone the camera is
in, and when it moves on.

    class Baker(EGLContext):
        renderer = 'pbr'                      # the pass that captures zones
        def OnInit(self):
            self.sg = sceneGraph(children=[sky, sun, world])

    with Baker(size=(256, 256), ibl='full') as context:
        for baked in bake_zone_lights(context):
            store(baked.zone, baked.irradiance, baked.mips)

The context needs the PBR pass (:attr:`Context.renderer
<OpenGLContext.context.Context.renderer>` or ``OPENGLCONTEXT_RENDERER``) and
the ``full`` probe (the definition's ``ibl``), since a capture is a layer of
that probe; with anything else no zone is captured and nothing is returned.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from collections.abc import Callable, Hashable, Sequence
from typing import Any, Optional

__all__ = ['FRAMES_PER_ZONE', 'BakedZoneLight', 'ZoneBakePlan', 'bake_zone_lights']

log = logging.getLogger(__name__)

#: How many frames one zone is given to finish its captures -- and, for a
#: world that streams, for its surroundings to arrive -- before it is baked
#: with what it has.
FRAMES_PER_ZONE = 40

Eye = tuple[float, float, float]


@dataclass
class BakedZoneLight:
    """One zone's captured environment.

    ``zone`` is the ``Zone`` node; ``irradiance`` six float32 faces of the
    irradiance cube; ``mips`` the prefiltered levels, finest first, each six
    faces, in linear light.
    """

    zone: Any
    irradiance: Sequence[Any]
    mips: Sequence[Sequence[Any]]


class ZoneBakePlan:
    """Which zone a bake stands the camera in, and when it moves on. No GL.

    ``zones`` are ``(key, eye)`` pairs in the order to visit them. After each
    frame drawn with the camera at the current zone's ``eye``, :meth:`step`
    is told whether that zone's captures have settled; the zone is finished
    when they have, or after ``frames_per_zone`` frames, whichever is first.
    """

    def __init__(self, zones: Sequence[tuple[Hashable, Eye]],
                 frames_per_zone: int = FRAMES_PER_ZONE) -> None:
        if int(frames_per_zone) < 1:
            raise ValueError('a zone needs at least one frame, not %r'
                             % (frames_per_zone,))
        self.zones = list(zones)
        self.frames_per_zone = int(frames_per_zone)
        self._index = 0
        self._frames = 0
        #: The keys finished without their captures settling.
        self.missed: list[Hashable] = []

    @property
    def current(self) -> Optional[tuple[Hashable, Eye]]:
        """The ``(key, eye)`` of the zone being baked, or None when done."""
        return self.zones[self._index] if self._index < len(self.zones) else None

    @property
    def finished(self) -> bool:
        return self._index >= len(self.zones)

    @property
    def progress(self) -> tuple[int, int]:
        """``(zones finished, zones in all)``."""
        return self._index, len(self.zones)

    def step(self, settled: bool) -> Optional[bool]:
        """One frame was drawn for the current zone.

        Returns None while the zone goes on, True when its captures settled
        and False when its frames ran out; either way the plan has moved to
        the next zone.
        """
        if self.finished:
            raise RuntimeError('every zone has been baked')
        self._frames += 1
        if not settled and self._frames < self.frames_per_zone:
            return None
        if not settled:
            self.missed.append(self.zones[self._index][0])
        self._index += 1
        self._frames = 0
        return bool(settled)


def _capturing(flat: Any) -> list[tuple[Any, Eye]]:
    """``(Zone node, capture point in the world)`` for every zone the pass
    has placed whose environment asks for a capture."""
    from OpenGLContext.scenegraph.zone import ENVIRONMENT
    found = []
    for placed in flat.zones:
        setting = placed.setting(ENVIRONMENT)
        if setting is None or not bool(getattr(setting, 'capture', False)):
            continue
        eye = placed.to_world(setting.captureCentre)
        x, y, z = (float(v) for v in eye)
        found.append((placed.zone, (x, y, z)))
    return found


def bake_zone_lights(context: Any, frames_per_zone: int = FRAMES_PER_ZONE,
                     before_frame: Optional[Callable[[Eye], None]] = None,
                     progress: Optional[Callable[[int, int], None]] = None,
                     ) -> list[BakedZoneLight]:
    """Every capturing zone of ``context``'s scene, captured and read back.

    ``context`` is an open context (an offscreen one, usually) whose scene
    holds the zones. ``before_frame(eye)`` is called before each frame with
    the camera's position, for a world that streams its content in around the
    camera; ``progress(done, total)`` after each zone. A zone whose captures
    do not settle within ``frames_per_zone`` frames is baked with what it has,
    and one never captured at all is left out and logged. Raises
    ``RuntimeError`` where the context drew no render pass.
    """
    from OpenGLContext.passes import renderpass

    context.OnDraw(force=1)
    flat = renderpass.current_pass()
    if flat is None:
        raise RuntimeError('the context drew no render pass')
    plan = ZoneBakePlan(_capturing(flat), frames_per_zone)
    baked: list[BakedZoneLight] = []
    while plan.current is not None:
        zone, eye = plan.current
        context.platform.setPosition(eye)
        if before_frame is not None:
            before_frame(eye)
        context.OnDraw(force=1)
        if plan.step(flat.zoneCaptureSettled(zone)) is None:
            continue
        light = flat.zoneLightImage(zone)
        if light is None:
            log.warning('zone %r was not captured', getattr(zone, 'DEF', None) or zone)
        else:
            baked.append(BakedZoneLight(zone, light[0], light[1]))
        if progress is not None:
            progress(*plan.progress)
    return baked
