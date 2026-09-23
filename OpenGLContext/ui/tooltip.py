"""What a control says about itself when the pointer rests on it.

A button drawn as a glyph says what it does in a line of text, shown where the
pointer is after a pause. The pause is what keeps a tip from following the
pointer across a window somebody is only crossing.

A tooltip takes no events: it is drawn over the panels rather than pushed on
the stack, so nothing is under it and nothing about modality changes.
``Widget.tooltip`` is the line, and
:class:`~OpenGLContext.ui.overlay.OverlayMixin` is what watches the pointer
and puts one up.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

from vrml import field

from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Widget

__all__ = ['Tooltip', 'POINTER_GAP', 'TOOLTIP_PAUSE']

#: How long the pointer rests on a control before its tip is shown, in
#: seconds.
TOOLTIP_PAUSE = 0.6

#: How far from the pointer the tip is drawn, in reference pixels, so the
#: cursor does not stand on what it is being told.
POINTER_GAP = 18.0


class Tooltip(Panel):
    """One line about the control under the pointer, drawn beside it."""

    PROTO = 'Tooltip'
    #: What the control says about itself.
    text = field.newField('text', 'SFString', 1, '')
    #: Where the pointer is, in window pixels.
    anchor = field.newField('anchor', 'SFVec2f', 1, (0.0, 0.0))

    def __init__(self, **named: Any) -> None:
        named.setdefault('modal', False)
        named.setdefault('closeOnEscape', False)
        super(Tooltip, self).__init__(**named)

    def widget_at(self, x: float, y: float) -> Optional[Widget]:
        """Nothing: a tip is a note, and the pointer goes through it."""
        return None

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        pad = int(self.activeSkin().panelPadding)
        return (metrics.text_width(str(self.text)) + pad,
                metrics.char_height + pad)

    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        """Beside the pointer, and inside the window wherever the pointer is."""
        self.link()
        self.scaleSkin(metrics)
        self._title_height = 0
        width, height = (int(value) for value in self.content_size(metrics))
        gap = metrics.pixels(POINTER_GAP)
        view_width, view_height = int(viewport[0]), int(viewport[1])
        x = min(max(int(self.anchor[0]) + gap, 0), max(view_width - width, 0))
        top = int(self.anchor[1]) - gap
        if top - height < 0:
            top = min(view_height, int(self.anchor[1]) + gap + height)
        self.rect = Rect(x, max(top - height, 0), width, height)

    def paint(self, renderer: Any) -> None:
        skin = renderer.skin
        renderer.frame(self.rect, skin.panelFill, skin.panelImage)
        renderer.border(self.rect, skin.panelBorder, int(skin.borderWidth))
        renderer.textIn(self.rect, str(self.text), skin.labelText,
                        align='center')
