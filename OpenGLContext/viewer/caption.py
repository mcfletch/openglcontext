"""What the viewer says over the frame.

A line or two in the corner: what is loaded, which camera and animation are
showing, and how you move.  It turns red when a load failed, because the one
thing worse than a blank window is a blank window that says nothing.

This is a :class:`~OpenGLContext.ui.hudwidgets.HUDLayer` like any other, drawn
by :meth:`~OpenGLContext.ui.screen.ScreenMixin.renderShaderOverlay` in the same
batched call as the developer overlay and any panel over the top.  That is what
makes it take the skin and the interface scale for free, and what lets an
application embedding the viewer restyle or replace it without knowing anything
about how text reaches the screen.

    viewer.overlayText = "model.glb\\n[1/3] aerial"
    viewer.overlayError = False
"""
from typing import TYPE_CHECKING, Any, List, Optional

from OpenGLContext.ui.hudwidgets import HUDLayer, TextBlock

__all__ = ['CaptionLayer', 'CaptionMixin']

#: Where the caption sits, and how far in from the corner.
#:
#: The far corner from the developer overlay, which every context shows by
#: default: that one is anchored top-left and grows *down* the left edge as
#: sections are registered, so a caption anywhere along that side is a caption
#: written over it.  Right-aligned to read out from the edge it hangs on.
CAPTION_ANCHOR = 'bottom-right'
CAPTION_ALIGN = 'right'
CAPTION_MARGIN = 12.0


class CaptionLayer(HUDLayer):
    """One block of text in a corner, and nothing else."""

    PROTO = 'ViewerCaption'

    def __init__(self, **named: Any) -> None:
        block = TextBlock(anchor=CAPTION_ANCHOR, align=CAPTION_ALIGN)
        named.setdefault('margin', CAPTION_MARGIN)
        named.setdefault('children', [block])
        super(CaptionLayer, self).__init__(**named)
        #: The block the caption's lines are written into.
        self.block = block


class CaptionMixin(object):
    """Gives a context the viewer's caption.

    :attr:`overlayText` and :attr:`overlayError` are the whole interface, and
    they are properties over the HUD layer rather than plain attributes so that
    writing one both updates the widget and asks for the frame that shows it.
    """

    _captionLayer: Optional[CaptionLayer] = None

    if TYPE_CHECKING:
        hudLayers: List[Any]

        def addHUDLayer(self, layer: Any) -> Any: ...
        def removeHUDLayer(self, layer: Any) -> None: ...
        def triggerRedraw(self, force: int = 0) -> Any: ...

    def setupCaption(self) -> CaptionLayer:
        """Put the caption on the screen.  Calling it again is harmless."""
        layer = self.captionLayer
        if layer not in self.hudLayers:
            self.addHUDLayer(layer)
        return layer

    @property
    def captionLayer(self) -> CaptionLayer:
        """The layer, made on first use and not yet on any screen.

        Making one touches nothing outside itself, so a viewer whose ``OnInit``
        never ran -- one built for a test, or one that failed before it got
        that far -- can still be given a caption to hold rather than raising on
        the way to reporting why.  :meth:`setupCaption` is what shows it.
        """
        if self._captionLayer is None:
            self._captionLayer = CaptionLayer()
        return self._captionLayer

    def showCaption(self, visible: bool = True) -> None:
        """Show or hide it.  A ``--capture`` frame carries no caption."""
        self.captionLayer.visible = bool(visible)
        self.captionChanged()

    def captionChanged(self) -> None:
        """Ask for the frame that will show a new caption.

        Only when the caption is actually on screen: one nobody is showing has
        nothing to redraw for, and a viewer that has not reached ``OnInit`` has
        no frames to ask for yet.
        """
        if self._captionLayer is not None and self._captionLayer in self.hudLayers:
            self.triggerRedraw(1)

    # -- what it says -----------------------------------------------------
    @property
    def overlayText(self) -> str:
        """The caption, as newline-separated lines."""
        return '\n'.join(str(line) for line in self.captionLayer.block.lines)

    @overlayText.setter
    def overlayText(self, text: str) -> None:
        lines: List[str] = str(text).split('\n') if text else []
        block = self.captionLayer.block
        if [str(line) for line in block.lines] == lines:
            return          # recomposed on every camera change; only news counts
        block.lines = lines
        self.captionChanged()

    @property
    def overlayError(self) -> bool:
        """Whether the caption is reporting a failure."""
        return bool(self.captionLayer.block.critical)

    @overlayError.setter
    def overlayError(self, failed: bool) -> None:
        block = self.captionLayer.block
        if bool(block.critical) == bool(failed):
            return
        block.critical = bool(failed)
        self.captionChanged()
