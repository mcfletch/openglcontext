"""The screen-space layers a context draws over its finished frame.

Two kinds of thing end up in front of the world, and they behave differently
enough that keeping them apart is the whole point of this module:

* **HUD layers** (:mod:`OpenGLContext.ui.hudwidgets`) are non-interactive.  A
  health bar, a reticule, the developer overlay.  They are drawn every frame,
  they never take an event, and they never stop the world hearing one.
* **Overlay panels** (:mod:`OpenGLContext.ui.overlay`) are screens.  Settings,
  key bindings, a question.  The top one takes the input and a modal one stops
  everything below it hearing anything at all.

Every context has the first kind, because the developer overlay is where the
frame rate is now drawn and every context has a frame rate; a context gains the
second by mixing in :class:`~OpenGLContext.ui.overlay.OverlayMixin`.  Both are
drawn by one renderer in one batch, HUD first and panels over it, so a dialog
opened over a game covers its HUD instead of fighting with it.

**HUD layers are laid out every frame; panels are not.**  A panel is a few
dozen widgets whose text has to be measured, and it changes only when something
happens to it.  A HUD is a handful of elements whose *values* change constantly
-- and a debug overlay's plate changes size as the numbers in it do -- so
measuring it per frame is both necessary and cheap.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from OpenGLContext.events import systemtime
from OpenGLContext.ui.metrics import FontMetrics, font_size_for, metrics_for

log = logging.getLogger(__name__)

__all__ = ['ScreenMixin']


class ScreenMixin(object):
    """Gives a context its HUD layers, its debug overlay and their drawing."""

    # Supplied by the context this is mixed into (annotations only, so the
    # real methods are still found at run time).
    getViewPort: Any
    getViewPlatform: Any
    triggerRedraw: Any

    _hudLayers: Optional[List[Any]] = None
    _debugOverlay: Optional[Any] = None

    # -- the layers -------------------------------------------------------
    @property
    def hudLayers(self) -> List[Any]:
        """The HUD trees drawn over this context's frames, back to front."""
        if self._hudLayers is None:
            self._hudLayers = []
        return self._hudLayers

    def addHUDLayer(self, layer: Any) -> Any:
        """Draw a HUD layer over this context, in front of the ones already there."""
        self.hudLayers.append(layer)
        self.triggerRedraw(1)
        return layer

    def removeHUDLayer(self, layer: Any) -> None:
        """Stop drawing a layer.  Removing one that is not there does nothing."""
        if layer in self.hudLayers:
            self.hudLayers.remove(layer)
            self.triggerRedraw(1)

    # -- the developer overlay --------------------------------------------
    @property
    def debugOverlay(self) -> Any:
        """This context's developer overlay, made and installed on first use.

        Lazily, because most of the cost of it is the providers it registers
        and a context that never shows one should never pay for them.  It goes
        in **behind** any HUD the application adds later, so a game's own
        screen furniture is drawn over it rather than under it.
        """
        if self._debugOverlay is None:
            from OpenGLContext.ui.debugoverlay import (
                DebugOverlay, install_default_providers,
            )
            overlay = DebugOverlay(visible=DebugOverlay.startsVisible())
            install_default_providers(overlay, self)
            self._debugOverlay = overlay
            self.hudLayers.insert(0, overlay)
        return self._debugOverlay

    def toggleDebugOverlay(self, event: Any = None) -> bool:
        """Show the developer overlay if it is hidden, hide it if it is up.

        Takes an optional event so it can be bound to a key directly.
        """
        shown = bool(self.debugOverlay.toggle())
        self.triggerRedraw(1)
        return shown

    # -- measurement ------------------------------------------------------
    def interfaceScale(self) -> float:
        """How much larger than usual the player wants the interface.

        The window's own height is *not* in here: that is answered by
        :func:`~OpenGLContext.ui.metrics.font_size_for` and applies whether or
        not anyone has a preference.  This is the preference on top of it --
        eyesight and viewing distance rather than resolution.
        """
        scale = getattr(getattr(self, 'contextDefinition', None), 'uiScale', 1.0)
        return float(scale) or 1.0

    def overlayFontSize(self) -> int:
        """The atlas size the overlay measures and draws with right now.

        A method rather than a setting, because the answer changes with the
        window: a screen that was comfortable in a 1080p window is half the
        size it should be when that window is dragged onto a 4K display.
        """
        return font_size_for(self.getViewPort()[1], self.interfaceScale())

    def overlayMetrics(self) -> Optional[FontMetrics]:
        """Measurements for the font the overlay draws with, or None.

        None until there is a GL context with a built font atlas: measuring
        against a zero-sized character would collapse every widget in the tree.
        """
        from OpenGLContext.scenegraph.text.shadertext import get_text_renderer
        renderer = get_text_renderer(self.overlayFontSize())
        try:
            if not renderer.initialize():
                return None
        except Exception:                       # pragma: no cover - broken driver
            log.warning("could not build the overlay font atlas", exc_info=True)
            return None
        if not renderer.char_width or not renderer.char_height:
            return None
        return metrics_for(renderer)

    # -- drawing ----------------------------------------------------------
    def screenTrees(self, metrics: FontMetrics,
                    now: Optional[float] = None) -> List[Any]:
        """Everything to paint over this frame, in the order it is painted.

        The HUD layers, advanced to ``now`` and laid out for the window they
        are about to be drawn in.  ``OverlayMixin`` adds the open panels after
        these, which is what puts a screen over the HUD rather than under it.
        """
        if now is None:
            now = systemtime.systemTime()
        viewport = self.getViewPort()
        trees = []
        for layer in list(self.hudLayers):
            if not layer.visible:
                continue
            layer.tick(now)
            layer.layout(viewport, metrics)
            trees.append(layer)
        return trees

    def renderShaderOverlay(self, pass_: Any) -> None:
        """Draw the HUD and any screens over the finished frame.

        Called by the shader render pass once everything else is done, with its
        program current.  Everything is drawn through one
        :class:`~OpenGLContext.ui.draw.OverlayRenderer`, so a whole HUD and the
        screen over it are two or three draw calls rather than one per element.
        """
        metrics = self.overlayMetrics()
        if metrics is None:
            return
        trees = self.screenTrees(metrics)
        if not trees:
            return
        from OpenGLContext.ui.draw import OverlayRenderer
        renderer = OverlayRenderer.forContext(self, self.overlayFontSize())
        if renderer is not None:
            renderer.drawTrees(trees, self.getViewPort())
