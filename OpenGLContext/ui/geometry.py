"""Screen rectangles for the overlay UI.

Coordinates are pixels in OpenGL's bottom-left origin, which is the origin a
mouse event's pick point already arrives in, so nothing here has to flip
anything.  Rectangles are half-open on their far edges: two panels that abut
never both claim the pixel between them, so a click there is unambiguous.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Rect:
    """A screen rectangle, in pixels from the bottom-left of the window."""

    x: int
    y: int
    width: int
    height: int

    @property
    def right(self) -> int:
        """One past the last pixel column inside the rectangle."""
        return self.x + self.width

    @property
    def top(self) -> int:
        """One past the last pixel row inside the rectangle."""
        return self.y + self.height

    @property
    def empty(self) -> bool:
        """Whether the rectangle can hold anything at all."""
        return self.width <= 0 or self.height <= 0

    @property
    def centre(self) -> Tuple[int, int]:
        """The middle pixel -- what a test clicks and a label centres on."""
        return (self.x + self.width // 2, self.y + self.height // 2)

    def contains(self, px: float, py: float) -> bool:
        """Whether a point is inside, counting the near edges but not the far."""
        return (self.x <= px < self.right and self.y <= py < self.top)

    def intersects(self, other: 'Rect') -> bool:
        """Whether the two rectangles share any pixel."""
        return not (self.right <= other.x or other.right <= self.x
                    or self.top <= other.y or other.top <= self.y)

    def inset(self, left: int, top: Optional[int] = None,
              right: Optional[int] = None,
              bottom: Optional[int] = None) -> 'Rect':
        """Shrink by a margin on each side, clamped at zero size.

        Called with one value it insets every side by it.  The clamp matters
        because a panel can be laid out narrower than its own padding when the
        window is tiny, and a negative width would then invert every hit test
        inside it.
        """
        if top is None:
            top = left
        if right is None:
            right = left
        if bottom is None:
            bottom = top
        return Rect(self.x + left, self.y + bottom,
                    max(0, self.width - left - right),
                    max(0, self.height - top - bottom))

    def expand(self, amount: int) -> 'Rect':
        """Grow by a margin on every side -- the focus glow's ring."""
        return Rect(self.x - amount, self.y - amount,
                    self.width + amount * 2, self.height + amount * 2)

    def offset(self, dx: int, dy: int) -> 'Rect':
        """The same rectangle moved, which is what scrolling does to one."""
        return Rect(self.x + dx, self.y + dy, self.width, self.height)

    def clip(self, other: 'Rect') -> 'Rect':
        """The area common to both, empty (zero-sized) when they are disjoint."""
        x = max(self.x, other.x)
        y = max(self.y, other.y)
        return Rect(x, y,
                    max(0, min(self.right, other.right) - x),
                    max(0, min(self.top, other.top) - y))
