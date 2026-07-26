"""Cascade-count controller and shadow-map GL-resource pool for ShadowMapMixin.

Two self-contained responsibilities that back ``ShadowMapMixin``'s per-light
render orchestration:

* :class:`_CascadeControllerMixin` -- the fps-adaptive directional-cascade count
  state machine (VRAM cap + ramp-up/shed on measured frame rate, or an env pin).
* :class:`_ShadowMapPoolMixin` -- lazy allocation and teardown of the shared depth
  array, the point-light cube-array, and per-slot cube fallbacks.

Both are mixed into ``ShadowMapMixin`` (which itself mixes into ``FlatPass``), so
``self`` is the pass and the orchestration methods read this state directly.
"""
from __future__ import annotations

import os
import logging
from typing import TYPE_CHECKING, Any, Optional

from OpenGLContext.passes.shadowmap import ShadowMapArray, ShadowMapCube, ShadowMapCubeArray
from OpenGLContext.passes.shadowcaps import ShadowCapabilities

log = logging.getLogger(__name__)


class _CascadeControllerMixin:
    """Fps-adaptive directional-cascade count (VRAM cap + frame-rate ramp)."""

    if TYPE_CHECKING:
        _shadow_caps: Optional[ShadowCapabilities]
        shadow_cascades: int
        shadow_cascades_adaptive: bool
        shader_program: Any

    # Adaptive-cascade controller state.
    _adaptive_cascades: int = 1     # current effective count (ramps up with headroom)
    _cascade_up_streak: int = 0
    _cascade_cooldown: int = 0      # frames to wait before probing upward again
    _CASCADE_FPS_UP: float = 90.0   # need to be comfortably above 60 to add a cascade
    _CASCADE_FPS_DOWN: float = 60.0 # drop a cascade the moment we fall to 60
    _CASCADE_UP_FRAMES: int = 45    # sustain the headroom ~<1s before ramping up
    _CASCADE_COOLDOWN: int = 600    # after shedding, don't re-probe for ~10s (no oscillation)

    def _vramCascadeCap(self) -> int:
        """Max cascades the GPU's VRAM budget allows (cascades are a premium)."""
        caps = self._shadow_caps
        vram = getattr(caps, 'total_vram_mb', 0) if caps else 0
        budget = max(1, min(self.shadow_cascades, self.shader_program.MAX_CASCADES))
        if not vram:
            return min(budget, 2)      # unknown VRAM: stay conservative
        if vram < 3000:
            return 1                   # <3 GB: single cascade only
        if vram < 6000:
            return min(budget, 2)
        return budget                  # >=6 GB ("lots of VRAM"): full budget

    def _effectiveCascades(self) -> int:
        """Adaptive cascade count: ramp up only with VRAM and fps headroom.

        Cascades are enabled *if and only if* we have the VRAM for them and are
        rendering well above 60 fps; if the frame rate sags to 60 we shed a
        cascade immediately. This keeps shadows from dragging a scene below
        60 fps while still using the extra quality when the GPU can afford it.

        ``ContextDefinition.shadowCascades`` (or ``OPENGLCONTEXT_SHADOW_CASCADES``)
        pins the count to a fixed value and bypasses the fps probe entirely. The shared depth array is already
        allocated at its full ``MAX_CASCADES`` size and never reallocated
       , so the only remaining source of frame-to-frame variation
        is *how many* of those layers get rendered; pinning it makes shadow
        output deterministic for reference-image regression / CI.
        """
        from OpenGLContext import renderoptions
        forced = int(renderoptions.number(
            self, 'shadowCascades',
            renderoptions.env_number('OPENGLCONTEXT_SHADOW_CASCADES', 0,
                                     integer=True)))
        if forced:
            return max(1, min(forced, self.shader_program.MAX_CASCADES))
        cap = self._vramCascadeCap()
        if not self.shadow_cascades_adaptive:
            return max(1, min(self.shadow_cascades, cap,
                              self.shader_program.MAX_CASCADES))
        fc = getattr(getattr(self, 'context', None), 'frameCounter', None)
        fps = fc.recentFps() if fc is not None else 0.0
        cur = max(1, min(self._adaptive_cascades, cap))
        if self._cascade_cooldown > 0:
            self._cascade_cooldown -= 1
        if fps and fps < self._CASCADE_FPS_DOWN and cur > 1:
            cur -= 1                                   # shed a cascade at once
            self._cascade_up_streak = 0
            self._cascade_cooldown = self._CASCADE_COOLDOWN   # don't immediately re-probe
        elif (fps > self._CASCADE_FPS_UP and cur < cap
              and self._cascade_cooldown == 0):
            self._cascade_up_streak += 1
            if self._cascade_up_streak >= self._CASCADE_UP_FRAMES:
                cur += 1                               # earn one after sustained headroom
                self._cascade_up_streak = 0
        else:
            self._cascade_up_streak = 0
        self._adaptive_cascades = cur
        return cur


class _ShadowMapPoolMixin:
    """Lazy alloc + teardown of the shared depth array / cube-array / cube maps."""

    if TYPE_CHECKING:
        shader_program: Any
        shadow_resolution: int
        shadow_cube_resolution: int

    _shadow_caps: Optional[ShadowCapabilities] = None
    # Spot maps and directional cascades share one depth array;
    # point lights share one cube-array when the driver supports it, else fall
    # back to one cube map per slot.
    _shared_array: Optional[ShadowMapArray] = None
    _shared_cube_array: Optional[ShadowMapCubeArray] = None
    _maps_cube: Optional[dict] = None

    def disposeShadowMaps(self) -> None:
        """Release every shadow FBO + depth texture this pass allocated.

        The map pools (the shared depth array, the point cube-array, and any
        per-slot cube fallbacks) are created lazily and live for the pass's
        lifetime; nothing else frees them, so a context resize, a scenegraph
        swap that replaces the cached pass, or a context close would otherwise
        leak the GL objects (the pool classes have no finalizer -- deliberately,
        so GC never touches GL). Call this from the pass/context teardown while
        the owning context is still current. Idempotent.
        """
        for pool in (self._shared_array, self._shared_cube_array):
            if pool is not None:
                try:
                    pool.cleanup()
                except Exception as err:
                    log.debug("shadow map cleanup failed: %s", err)
        for pool in (self._maps_cube or {}).values():
            try:
                pool.cleanup()
            except Exception as err:
                log.debug("cube shadow map cleanup failed: %s", err)
        self._shared_array = None
        self._shared_cube_array = None
        self._maps_cube = None
        self._shadow_bindings = None
        # Drop the per-light depth-map reuse cache (R2): its entries key on the
        # now-freed textures + light identities, so a fresh allocation must
        # re-render rather than trust a stale hit.
        self._depth_map_cache = None
        # Drop the depth grouping cache (R5): it holds render records for the
        # outgoing scene.
        self._depth_grouping_cache = None

    # -- map pools ---------------------------------------------------------
    def _array_layers(self) -> int:
        """Layer count of the shared spot+CSM depth array."""
        s = self.shader_program
        return s.MAX_SHADOW_LIGHTS * s.MAX_CASCADES

    def _shared_map(self) -> ShadowMapArray:
        """The single depth array holding every spot map and CSM cascade.

        Spot slot ``s`` uses layer ``s*MAX_CASCADES``; directional slot ``s``
        cascade ``c`` uses layer ``s*MAX_CASCADES + c``.
        """
        if self._shared_array is None:
            self._shared_array = ShadowMapArray(self.shadow_resolution, self._array_layers())
        return self._shared_array

    def _cube_array_map(self) -> ShadowMapCubeArray:
        if self._shared_cube_array is None:
            self._shared_cube_array = ShadowMapCubeArray(
                self.shadow_cube_resolution, self.shader_program.MAX_SHADOW_LIGHTS)
        return self._shared_cube_array

    def _map_cube(self, slot: int) -> ShadowMapCube:
        if self._maps_cube is None:
            self._maps_cube = {}
        if slot not in self._maps_cube:
            self._maps_cube[slot] = ShadowMapCube(self.shadow_cube_resolution)
        return self._maps_cube[slot]

    def _ensureShadowCaps(self) -> ShadowCapabilities:
        if self._shadow_caps is None:
            self._shadow_caps = ShadowCapabilities.detect(getattr(self, 'context', None))
        return self._shadow_caps
