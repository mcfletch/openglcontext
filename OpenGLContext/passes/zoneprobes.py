"""Environment probes captured inside zones.

A zone whose environment asks for a capture (``ZoneEnvironment.capture``) is
lit and reflected by what can be seen from inside it rather than by the
scene's sky: a room by its own walls and doorway, a tunnel by its bore and
lamps, a forest by its trees. The pass draws the scene into the six faces of a
cube from the zone's capture centre, and the probe convolves that cube into a
layer of its irradiance and prefiltered arrays
(:meth:`~OpenGLContext.passes.ibl.IBLProbe.convolve`), which ``pbr.frag``
reads for fragments inside the zone.

When a zone is captured, and how often, is :class:`CaptureSchedule`'s
business and has no GL in it:

* A zone is captured the first time something it lights is drawn, and then
  captured again, :data:`BOUNCES` times in all. The first capture draws the
  zone's own surfaces with no environment light, only the direct light
  reaching them and the sky seen through its openings; each later one draws
  them lit by the capture before, which adds the light bouncing once more
  off the walls.
* It is captured once more the first time the camera is inside it, since a
  world that streams its content in may not have loaded what surrounds a zone
  until the camera is near it, and the directional shadows are fitted to the
  camera's surroundings.
* At most one zone is captured in a frame, the nearest to the camera first,
  and :data:`FACES_PER_FRAME` limits how many of its faces are drawn in one
  frame, so a scene arriving with many zones spreads the work over frames.

:class:`CaptureTarget` is the GL side: the cube the faces are drawn into and
the depth buffer they share.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Hashable, Iterable, List, Optional, Tuple

from OpenGL.GL import (
    GL_CLAMP_TO_EDGE, GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT,
    GL_DEPTH_ATTACHMENT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_COMPONENT24,
    GL_FRAMEBUFFER, GL_FRAMEBUFFER_BINDING, GL_FRAMEBUFFER_COMPLETE,
    GL_LINEAR, GL_LINEAR_MIPMAP_LINEAR, GL_RENDERBUFFER, GL_RGBA16F,
    GL_TEXTURE_CUBE_MAP, GL_TEXTURE_CUBE_MAP_POSITIVE_X,
    GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_R,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_VIEWPORT,
    glBindFramebuffer, glBindRenderbuffer, glBindTexture,
    glCheckFramebufferStatus, glClear, glClearColor, glDeleteFramebuffers,
    glDeleteRenderbuffers, glDeleteTextures, glFramebufferRenderbuffer,
    glFramebufferTexture2D, glGenFramebuffers, glGenRenderbuffers,
    glGenTextures, glGenerateMipmap, glGetIntegerv, glRenderbufferStorage,
    glTexParameteri, glTexStorage2D, glViewport,
)

log = logging.getLogger(__name__)

__all__ = ['BOUNCES', 'FACES_PER_FRAME', 'CaptureSchedule', 'CaptureTarget']

#: How many times a zone is captured when it is first needed. Each capture
#: after the first sees the zone lit by the one before, one bounce more.
BOUNCES = 2

#: How many cube faces are drawn in one frame, of the one zone being
#: captured. Six captures a zone in a frame; fewer spreads a capture over
#: frames. The context's ``zoneCaptureFaces`` or
#: ``OPENGLCONTEXT_ZONE_CAPTURE_FACES`` overrides it.
FACES_PER_FRAME = 6


@dataclass
class _Capture:
    """What the schedule knows about one zone's probe."""

    layer: int
    done: int = 0
    wanted: int = 0
    inside: bool = False
    face: int = 0


class CaptureSchedule:
    """Which zone's probe to capture next, and which layer each probe is in.

    Zones are identified by any hashable key the caller chooses. Layer 0 is
    the scene's own environment, so zones are given layers from 1.
    """

    def __init__(self, bounces: int = BOUNCES) -> None:
        self.bounces = max(1, int(bounces))
        self._captures: Dict[Hashable, _Capture] = {}
        self._free: List[int] = []
        self._next_layer = 1

    def __len__(self) -> int:
        return len(self._captures)

    @property
    def layers(self) -> int:
        """How many array layers the probes need, the scene's included."""
        return self._next_layer

    def layer(self, key: Hashable) -> Optional[int]:
        """The layer ``key``'s probe is in, or None before its first capture."""
        capture = self._captures.get(key)
        if capture is None or not capture.done:
            return None
        return capture.layer

    def captured(self, key: Hashable) -> int:
        """How many captures of ``key`` have been finished."""
        capture = self._captures.get(key)
        return 0 if capture is None else capture.done

    def request(self, key: Hashable) -> bool:
        """Something lit by ``key``'s probe is about to be drawn.

        Returns whether this is the first request, so the caller knows a
        capture is now waiting.
        """
        if key in self._captures:
            return False
        layer = self._free.pop(0) if self._free else self._claim()
        self._captures[key] = _Capture(layer, wanted=self.bounces)
        return True

    def reserve(self, key: Hashable) -> bool:
        """Give ``key`` a layer that is filled some other way than a capture.

        An image-based light a document ships is uploaded rather than drawn,
        so it takes a layer with nothing to capture. Returns whether this is
        the first time, so the caller knows an upload is waiting.
        """
        if key in self._captures:
            return False
        layer = self._free.pop(0) if self._free else self._claim()
        self._captures[key] = _Capture(layer, wanted=0)
        return True

    def layer_of(self, key: Hashable) -> Optional[int]:
        """The layer ``key`` holds, filled or not, or None where it has none."""
        capture = self._captures.get(key)
        return None if capture is None else capture.layer

    def settled(self, key: Hashable) -> bool:
        """Whether ``key``'s probe has been captured and none of its captures
        is still to be drawn."""
        capture = self._captures.get(key)
        return capture is not None and capture.done > 0 and capture.wanted == 0

    @property
    def waiting(self) -> bool:
        """Whether any capture is still to be drawn."""
        return any(capture.wanted > 0 for capture in self._captures.values())

    def _claim(self) -> int:
        layer = self._next_layer
        self._next_layer += 1
        return layer

    def camera_inside(self, key: Hashable) -> None:
        """The camera is inside ``key``'s zone: capture it again, once."""
        capture = self._captures.get(key)
        if capture is None or capture.inside:
            return
        capture.inside = True
        capture.wanted = max(capture.wanted, 1)

    def keep(self, keys: Iterable[Hashable]) -> None:
        """Forget every zone but ``keys``, freeing their layers for reuse."""
        alive = set(keys)
        for key in [key for key in self._captures if key not in alive]:
            self._free.append(self._captures.pop(key).layer)
        self._free.sort()

    def lost(self) -> None:
        """Every probe past the scene's was lost: capture each again."""
        for capture in self._captures.values():
            capture.done = 0
            capture.face = 0
            capture.wanted = self.bounces

    def next(self, nearness: Callable[[Hashable], float]) -> Optional[Hashable]:
        """The zone to capture now, the nearest by ``nearness`` first, or None.

        A zone part way through a capture is finished before another starts.
        """
        waiting = [key for key, capture in self._captures.items() if capture.wanted > 0]
        if not waiting:
            return None
        started = [key for key in waiting if self._captures[key].face > 0]
        if started:
            return started[0]
        return min(waiting, key=nearness)

    def faces(self, key: Hashable, budget: int) -> List[int]:
        """The faces of ``key``'s cube to draw now, at most ``budget`` of them."""
        capture = self._captures[key]
        return list(range(capture.face, min(6, capture.face + max(1, int(budget)))))

    def drawn(self, key: Hashable, faces: int) -> bool:
        """``faces`` more faces of ``key`` were drawn; return whether its cube is whole."""
        capture = self._captures[key]
        capture.face += int(faces)
        if capture.face < 6:
            return False
        capture.face = 0
        return True

    def finished(self, key: Hashable) -> None:
        """``key``'s cube has been convolved into its layer."""
        capture = self._captures[key]
        capture.done += 1
        capture.wanted = max(0, capture.wanted - 1)


class CaptureTarget:
    """The cube a zone's capture is drawn into, with the depth buffer it needs.

    ``size`` is the width of a face in pixels, which is the probe's
    environment size so the prefilter samples it as it samples the scene's.
    """

    def __init__(self, size: int) -> None:
        self.size = int(size)
        self.cube: Optional[int] = None
        self._fbo: Optional[int] = None
        self._depth: Optional[int] = None
        self._previous = 0
        self._viewport: Tuple[int, int, int, int] = (0, 0, 0, 0)

    def _ensure(self) -> None:
        if self.cube is not None:
            return
        size = self.size
        levels = max(1, size.bit_length())
        cube = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_CUBE_MAP, cube)
        glTexStorage2D(GL_TEXTURE_CUBE_MAP, levels, GL_RGBA16F, size, size)
        for name in (GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_TEXTURE_WRAP_R):
            glTexParameteri(GL_TEXTURE_CUBE_MAP, name, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glBindTexture(GL_TEXTURE_CUBE_MAP, 0)
        depth = int(glGenRenderbuffers(1))
        glBindRenderbuffer(GL_RENDERBUFFER, depth)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, size, size)
        glBindRenderbuffer(GL_RENDERBUFFER, 0)
        self.cube, self._depth = cube, depth
        self._fbo = int(glGenFramebuffers(1))

    def begin(self) -> None:
        """Draw into the capture from here on; :meth:`end` restores the caller's target."""
        self._previous = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
        x, y, width, height = (int(v) for v in glGetIntegerv(GL_VIEWPORT))
        self._viewport = (x, y, width, height)
        self._ensure()
        assert self._fbo is not None and self._depth is not None
        glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT,
                                  GL_RENDERBUFFER, self._depth)

    def face(self, face: int) -> None:
        """Point the drawing at ``face`` of the cube, cleared."""
        assert self.cube is not None, 'face() is called between begin() and end()'
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                               GL_TEXTURE_CUBE_MAP_POSITIVE_X + face, self.cube, 0)
        status = int(glCheckFramebufferStatus(GL_FRAMEBUFFER))
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError('zone capture target incomplete: 0x%x' % (status,))
        glViewport(0, 0, self.size, self.size)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    def end(self, whole: bool) -> None:
        """Give the caller's target back; with ``whole``, build the cube's mips."""
        glBindFramebuffer(GL_FRAMEBUFFER, self._previous)
        glViewport(*self._viewport)
        if whole and self.cube is not None:
            glBindTexture(GL_TEXTURE_CUBE_MAP, self.cube)
            glGenerateMipmap(GL_TEXTURE_CUBE_MAP)
            glBindTexture(GL_TEXTURE_CUBE_MAP, 0)

    def release(self) -> None:
        """Let go of the GL objects; the next capture makes them again."""
        try:
            if self._fbo is not None:
                glDeleteFramebuffers(1, [self._fbo])
            if self._depth is not None:
                glDeleteRenderbuffers(1, [self._depth])
            if self.cube is not None:
                glDeleteTextures([self.cube])
        except Exception as err:     # pragma: no cover - teardown after the context
            log.debug('zone capture target teardown: %s', err)
        self.cube = self._fbo = self._depth = None
