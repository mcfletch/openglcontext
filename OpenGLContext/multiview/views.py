"""Several cameras on one window: which view goes where, and which one the pointer is in.

A :class:`View` is a camera, a rectangle of the window and a :class:`ViewStyle`.
A :class:`ViewLayout` is an ordered set of views and the rule that places them
in a window: one view filling it, two side by side or stacked, or four in a
quad around a movable centre. The render pass draws every view the layout
places, each through its own camera into its own rectangle, from one gathered
scene; see :mod:`OpenGLContext.multiview.strategy` and ``docs/multiview.rst``.

::

    from OpenGLContext.multiview.views import View, ViewLayout

    context.viewLayout = ViewLayout.split(
        View(MapViewPlatform(plan), name='plan'),
        View(name='angled'),                 # the context's own camera
    )

Nothing here touches GL. Rectangles are window pixels counted from the bottom
left, as ``glViewport`` and an event's pick point count them.

The layout also routes the pointer. :meth:`ViewLayout.route` names the view an
event belongs to: the one under the pointer, except while a button is held,
when every event goes to the view the press began in, so a drag that leaves its
tile keeps talking to it. A press makes its view the *active* one: a key
event is routed to it, and the directional shadow cascades are fitted to its
camera.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import (
    Any, Callable, Iterable, Iterator, List, Optional, Sequence, Set, Tuple,
    Union,
)

from OpenGLContext.events.mouseevents import WHEEL_BUTTONS

__all__ = [
    'MAX_VIEWS', 'Rect', 'View', 'ViewLayout', 'ViewStyle', 'covers', 'tile_of',
]

#: The most views one layout holds: the size of the per-frame view table the
#: faster multi-view strategies upload, and no more than ``GL_MAX_VIEWPORTS``
#: is guaranteed to be on any GL 4.1 driver.
MAX_VIEWS = 16

#: ``(x, y, width, height)`` in window pixels, from the bottom left.
Rect = Tuple[int, int, int, int]

#: ``(width, height) -> [rect, ...]``, one rectangle per view, in order.
Arrangement = Callable[[int, int], Sequence[Rect]]

_NOWHERE: Rect = (0, 0, 0, 0)


@dataclass(frozen=True)
class ViewStyle:
    """How one view draws the scene it shares with the others.

    ``background`` is ``True`` to draw the scene's own bound ``Background``,
    or an RGB or RGBA colour to clear the view to instead -- the flat grey an
    orthographic editor view usually wants behind a sky it has no use for.

    ``wireframe`` draws the view's geometry as lines. It is per view because
    ``glPolygonMode`` is state rather than something a shader decides, so a
    wireframe view is drawn apart from the shaded ones.

    ``grid`` rules the view with the scene's
    :class:`~OpenGLContext.multiview.grid.Grid`, where the scene has one.
    """

    background: Union[bool, Tuple[float, ...]] = True
    wireframe: bool = False
    grid: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.background, bool) and len(self.background) not in (3, 4):
            raise ValueError(
                'a view background is True or an RGB/RGBA colour, not %r'
                % (self.background,))

    def clearColour(self) -> Optional[Tuple[float, float, float, float]]:
        """The RGBA colour this view clears to, or None to draw the scene's background."""
        if isinstance(self.background, bool):
            return None
        colour = tuple(float(channel) for channel in self.background)
        if len(colour) == 3:
            colour = colour + (1.0,)
        red, green, blue, alpha = colour
        return (red, green, blue, alpha)


class View:
    """One camera drawn into one rectangle of the window.

    ``camera`` is anything with the view platform's matrix interface --
    :class:`~OpenGLContext.move.viewplatform.ViewPlatform`,
    :class:`~OpenGLContext.edit.mapview.MapViewPlatform`,
    :class:`~OpenGLContext.edit.orbitview.OrbitViewPlatform` -- or None, which
    draws through the context's own view platform, whatever
    ``getViewPlatform()`` answers that frame. The default layout is one view
    with no camera, filling the window.

    ``rect`` is where the layout last placed the view; a view the layout is not
    showing (the others, while one is maximised) is placed nowhere.

    ``navigation`` is what the pointer moves this view's camera by -- the
    gestures it offers and the buttons that raise them. It is made for the
    camera the first time something asks
    (:func:`~OpenGLContext.multiview.navigation.navigation_for`), so a view
    that nobody navigates carries none.
    """

    def __init__(self, camera: Any = None, name: str = '',
                 style: Optional[ViewStyle] = None,
                 navigation: Any = None) -> None:
        self.camera = camera
        self.name = name
        self.style = style if style is not None else ViewStyle()
        self.navigation = navigation
        self.rect: Rect = _NOWHERE

    def __repr__(self) -> str:
        return '<View %r at %r>' % (self.name, self.rect)

    @property
    def size(self) -> Tuple[int, int]:
        """``(width, height)`` of the view's rectangle."""
        return (self.rect[2], self.rect[3])

    @property
    def visible(self) -> bool:
        """Whether the layout placed the view anywhere it can be drawn."""
        return self.rect[2] > 0 and self.rect[3] > 0

    def contains(self, x: float, y: float) -> bool:
        """Whether window pixel ``(x, y)`` is inside this view."""
        left, bottom, width, height = self.rect
        return left <= x < left + width and bottom <= y < bottom + height

    def local(self, x: float, y: float) -> Tuple[float, float]:
        """Window pixel ``(x, y)`` in this view's own pixels, from its bottom left."""
        return (x - self.rect[0], y - self.rect[1])


@contextmanager
def tile_of(view: View, camera: Any, window: Tuple[int, int]) -> Iterator[None]:
    """Within the block, ``camera`` projects for ``view``'s tile rather than the window.

    For a view drawn through the context's own camera, which the context keeps
    told the size of the whole window: a perspective projection computed
    inside the block has the tile's aspect ratio, and the camera is told the
    window's size again as the block ends. A view with a camera of its own is
    told its tile by :meth:`ViewLayout.arrange`, and is left alone here, as is
    a view that fills the window.
    """
    tell = getattr(camera, 'setViewport', None)
    width, height = int(window[0]), int(window[1])
    if (view.camera is not None or tell is None or not view.visible
            or view.size == (width, height)):
        yield
        return
    tell(*view.size)
    try:
        yield
    finally:
        tell(width or 1, height or 1)


def covers(rects: Sequence[Rect], width: int, height: int) -> bool:
    """Whether these rectangles together cover every pixel of a window this size.

    A layout need not tile the window: an arrangement of an application's own
    can leave a band for a toolbar, or place a view over part of another. What
    no view covers has to be cleared by the frame, since a view clears only its
    own rectangle -- so the frame asks this.
    """
    width, height = int(width), int(height)
    if width <= 0 or height <= 0:
        return True
    edges = sorted({0, width} | {int(x) for x, _y, _w, _h in rects}
                   | {int(x) + int(w) for x, _y, w, _h in rects})
    for left, right in zip(edges, edges[1:]):
        if right <= 0 or left >= width:
            continue
        spanning = [(int(y), int(y) + int(h)) for x, y, w, h in rects
                    if int(x) <= left and int(x) + int(w) >= right]
        reach = 0
        for low, high in sorted(spanning):
            if low > reach:
                break
            reach = max(reach, high)
            if reach >= height:
                break
        if reach < height:
            return False
    return True


def _cut(extent: int, fraction: float) -> int:
    """Where a split at ``fraction`` falls along ``extent`` pixels."""
    return int(round(extent * fraction))


def _single(width: int, height: int, split: Tuple[float, float]) -> List[Rect]:
    return [(0, 0, width, height)]


def _split(width: int, height: int, split: Tuple[float, float]) -> List[Rect]:
    at = _cut(width, split[0])
    return [(0, 0, at, height), (at, 0, width - at, height)]


def _stack(width: int, height: int, split: Tuple[float, float]) -> List[Rect]:
    # ``split[1]`` is measured down from the top, the way a reader sees it;
    # rows count up from the bottom.
    below = height - _cut(height, split[1])
    return [(0, below, width, height - below), (0, 0, width, below)]


def _quad(width: int, height: int, split: Tuple[float, float]) -> List[Rect]:
    across = _cut(width, split[0])
    below = height - _cut(height, split[1])
    return [
        (0, below, across, height - below),
        (across, below, width - across, height - below),
        (0, 0, across, below),
        (across, 0, width - across, below),
    ]


#: The named arrangements, and how many views each places.
_ARRANGEMENTS = {
    'single': (_single, 1),
    'split': (_split, 2),
    'stack': (_stack, 2),
    'quad': (_quad, 4),
}


class ViewLayout:
    """An ordered set of views and the rule that places them in the window.

    ``arrangement`` is one of the named rules -- ``'single'``, ``'split'``
    (two side by side), ``'stack'`` (two, one above the other) and ``'quad'``
    (four, read left to right and top to bottom) -- or a function
    ``(width, height) -> [rect, ...]`` giving one rectangle per view.

    ``split_at`` is where the named rules divide the window, as fractions of
    its width and of its height measured from the top: the vertical line of a
    split, the horizontal line of a stack, the centre of a quad. It is what a
    splitter drag moves.

    The order of ``views`` is the order they are drawn in, and the first is
    active until a press in another makes it so.
    """

    def __init__(self, views: Iterable[View],
                 arrangement: Union[str, Arrangement] = 'single',
                 split_at: Tuple[float, float] = (0.5, 0.5)) -> None:
        self.views: List[View] = list(views)
        if not self.views:
            raise ValueError('a view layout holds at least one view')
        if len(self.views) > MAX_VIEWS:
            raise ValueError('a view layout holds at most %d views, not %d'
                             % (MAX_VIEWS, len(self.views)))
        if len({id(view) for view in self.views}) != len(self.views):
            raise ValueError('a view appears in a layout once')
        if isinstance(arrangement, str):
            if arrangement not in _ARRANGEMENTS:
                raise ValueError('no view arrangement is called %r; the named ones are %s'
                                 % (arrangement, ', '.join(sorted(_ARRANGEMENTS))))
            expected = _ARRANGEMENTS[arrangement][1]
            if expected != len(self.views):
                raise ValueError('a %r arrangement places %d views, not %d'
                                 % (arrangement, expected, len(self.views)))
        self.arrangement = arrangement
        self.split_at = split_at
        self.active: View = self.views[0]
        self.maximised: Optional[View] = None
        #: The view a held button is talking to, and which buttons hold it.
        self._captured: Optional[View] = None
        self._held: Set[int] = set()
        #: The size each camera was last told, by view.
        self._told: dict = {}

    # -- building ----------------------------------------------------------
    @classmethod
    def single(cls, camera: Any = None, name: str = 'main',
               style: Optional[ViewStyle] = None) -> 'ViewLayout':
        """One view filling the window: what every context draws by default."""
        return cls([View(camera, name, style)], 'single')

    @classmethod
    def split(cls, first: View, second: View, fraction: float = 0.5,
              vertical: bool = False) -> 'ViewLayout':
        """Two views, side by side or, ``vertical``, the first above the second.

        ``fraction`` is the share of the window the first view gets.
        """
        if vertical:
            return cls([first, second], 'stack', (0.5, fraction))
        return cls([first, second], 'split', (fraction, 0.5))

    @classmethod
    def quad(cls, top_left: View, top_right: View, bottom_left: View,
             bottom_right: View,
             split_at: Tuple[float, float] = (0.5, 0.5)) -> 'ViewLayout':
        """Four views around a centre that ``split_at`` places."""
        return cls([top_left, top_right, bottom_left, bottom_right], 'quad', split_at)

    # -- the split ---------------------------------------------------------
    @property
    def split_at(self) -> Tuple[float, float]:
        """Where the named arrangements divide the window, each 0 to 1."""
        return self._split_at

    @split_at.setter
    def split_at(self, value: Tuple[float, float]) -> None:
        self._split_at = (min(max(float(value[0]), 0.0), 1.0),
                          min(max(float(value[1]), 0.0), 1.0))

    # -- placing -----------------------------------------------------------
    def rects(self, width: int, height: int) -> List[Rect]:
        """Where each view goes in a window this size, in the order of ``views``."""
        width, height = int(width), int(height)
        if self.maximised is not None:
            return [(0, 0, width, height) if view is self.maximised else _NOWHERE
                    for view in self.views]
        if isinstance(self.arrangement, str):
            rule = _ARRANGEMENTS[self.arrangement][0]
            placed = rule(width, height, self._split_at)
        else:
            placed = list(self.arrangement(width, height))
        if len(placed) != len(self.views):
            raise ValueError('the arrangement placed %d views of %d'
                             % (len(placed), len(self.views)))
        return [(int(x), int(y), int(w), int(h)) for x, y, w, h in placed]

    def arrange(self, width: int, height: int) -> List[View]:
        """Place every view in a window this size; the views to draw, in order.

        A camera of the view's own is told the size of its tile whenever that
        changes, so a perspective view's aspect ratio is that of the rectangle
        it is drawn in. A view with no camera draws through the context's,
        which the context keeps told the window's size; the render pass
        computes that view's projection inside :func:`tile_of`.
        """
        shown = []
        for view, rect in zip(self.views, self.rects(width, height)):
            view.rect = rect
            if view.visible:
                shown.append(view)
                self._tell(view)
        return shown

    def _tell(self, view: View) -> None:
        """Tell a view's camera the size of its tile, if that has changed."""
        camera = view.camera
        tell = getattr(camera, 'setViewport', None)
        if tell is None:
            return
        told = (id(camera), view.size)
        if self._told.get(id(view)) == told:
            return
        self._told[id(view)] = told
        tell(*view.size)

    def cameras(self, default: Any = None) -> List[Any]:
        """Every camera the layout draws through, once each.

        ``default`` stands for a view with no camera of its own -- pass the
        context's view platform. For whatever keeps content resident around
        the viewer, such as streamed tiles or a vegetation field, which have
        to serve every view at once.
        """
        found: List[Any] = []
        for view in self.views:
            camera = view.camera if view.camera is not None else default
            if camera is not None and not any(camera is seen for seen in found):
                found.append(camera)
        return found

    # -- the views ---------------------------------------------------------
    def _member(self, view: View) -> View:
        if not any(view is mine for mine in self.views):
            raise ValueError('%r is not a view of this layout' % (view,))
        return view

    def activate(self, view: View) -> None:
        """Make ``view`` the active one: keyboard input, the cascades' camera."""
        self.active = self._member(view)

    @property
    def can_maximise(self) -> bool:
        """Whether one view can be given the window: there are others to hide."""
        return len(self.views) > 1

    def maximise(self, view: Optional[View] = None) -> None:
        """Give ``view`` (the active one, if None) the whole window, or give it back.

        Maximising the view that is already maximised restores the layout. A
        layout of one view already gives it the window, and is left as it is.
        """
        chosen = self._member(view if view is not None else self.active)
        if not self.can_maximise:
            return
        self.maximised = None if chosen is self.maximised else chosen

    def view_at(self, x: float, y: float) -> Optional[View]:
        """The view drawn at window pixel ``(x, y)``, or None."""
        for view in self.views:
            if view.visible and view.contains(x, y):
                return view
        return None

    def release_all(self) -> None:
        """Let go of the pointer: no button is held and no view has it.

        For a release that will not arrive -- the window lost focus mid-drag,
        or another arrangement was put up -- so the next event goes to the
        view it is over.
        """
        self._captured = None
        self._held.clear()

    def view_of(self, event: Any) -> Optional[View]:
        """The view ``event`` belongs to, routed once and recorded as ``event.view``.

        An event already routed keeps its view, so an event handled twice is
        not routed twice -- a release routed again would find the drag it ended
        already over. An event of an application's own that has no ``view``
        attribute is routed; one that cannot be given the attribute is routed
        every time it is asked about.
        """
        view: Optional[View] = getattr(event, 'view', None)
        if view is None:
            view = self.route(event)
            try:
                event.view = view
            except AttributeError:
                pass
        return view

    def route(self, event: Any) -> Optional[View]:
        """The view an event belongs to.

        A press goes to the view under it and makes that view active, and every
        event after it goes there too until the last held button is released.
        A press of a button already held means its release never arrived, and
        starts a new capture. Wheel notches are presses of a button nobody
        holds, so they go to the view under the pointer and capture nothing. An
        event with no position, such as a key, goes to the active view.
        """
        point = getattr(event, 'getPickPoint', None)
        point = point() if point is not None else None
        if not point:
            return self.active
        under = self.view_at(point[0], point[1])
        if getattr(event, 'type', None) != 'mousebutton':
            return self._captured if self._captured is not None else under
        button = int(getattr(event, 'button', 0))
        if button in WHEEL_BUTTONS:
            return self._captured if self._captured is not None else under
        if getattr(event, 'state', 0):
            if button in self._held:
                self.release_all()
            if self._captured is None:
                self._captured = under
                if under is not None:
                    self.active = under
            self._held.add(button)
            return self._captured
        owner = self._captured if self._captured is not None else under
        self._held.discard(button)
        if not self._held:
            self._captured = None
        return owner
