"""The furniture of a window of several views.

A window showing four views of one scene needs to say which view is which,
which way each is looking, and how to work them. :class:`ViewChrome` draws
that inside each view and takes the clicks:

- the view's name, along its top, as a button that opens the view's menu:
  which way it looks, the scene's own cameras, how it is drawn, fitting what
  there is to see into it, and taking the window;
- an axis triad, which says which way the world's axes run in this view and
  turns with the camera;
- an expand button, which gives the view the whole window and gives it back;
- a splitter on each line the arrangement divides the window along, which a
  drag moves.

It is a panel at the bottom of the overlay stack, like
:class:`~OpenGLContext.ui.toolpalette.ToolPalette`, and it is not modal: a
press that lands on none of its controls reaches the scene underneath::

    chrome = ViewChrome(layout=views.layout, stack=context.overlays,
                        on_arrange=context.viewsArranged)
    context.overlays.push(chrome)

``on_arrange`` is called when a control changes what is on screen;
:meth:`~OpenGLContext.multiview.mixin.MultiViewMixin.viewsArranged` places the
views again and redraws.

``cameras`` offers the scene's cameras in that menu -- a list of
:class:`~OpenGLContext.multiview.viewpoints.SceneCamera`, or a callable
answering one, asked each time the menu opens::

    ViewChrome(layout=layout, stack=context.overlays,
               cameras=lambda: scene_cameras(context.getSceneGraph()))

Every part is optional -- ``labels``, ``axes``, ``expand`` and ``splitters``
each switch a kind off for the whole window, and ``only`` gives
one view a set of its own::

    ViewChrome(layout=layout, axes=False,
               only={'map': ('label', 'expand')})

``layout`` is assignable, so a window that rearranges its views hands over the
new layout and the furniture follows.
"""
from __future__ import annotations

from dataclasses import replace

from gettext import gettext as _
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
from vrml import field

from OpenGLContext.multiview.cameras import VIEW_KINDS, point_view, view_kind
from OpenGLContext.multiview.views import View, ViewLayout
from OpenGLContext.multiview.viewpoints import SceneCamera, look_through
from OpenGLContext.multiview.viewset import fit_view
from OpenGLContext.ui.geometry import Rect
from OpenGLContext.ui.menu import Menu, MenuItem
from OpenGLContext.ui.widgets import Separator
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Widget

__all__ = [
    'ViewChrome', 'ViewLabel', 'AxisTriad', 'ExpandButton',
    'Splitter', 'axis_directions', 'fitted', 'PARTS',
]

#: The parts a view can be given, which is what ``only`` names.
PARTS = ('label', 'axes', 'expand')

#: How the axes are coloured: the convention every 3D tool uses.
AXIS_COLOURS = {
    'x': (0.92, 0.36, 0.36, 1.0),
    'y': (0.45, 0.85, 0.45, 1.0),
    'z': (0.42, 0.62, 0.96, 1.0),
}

#: How wide across the triad is drawn, in reference pixels.
TRIAD_SIZE = 46.0

#: Room left between a view's edge and the furniture inside it.
MARGIN = 6.0

#: How wide a splitter is to grab, in reference pixels. Wider than the line
#: looks, because a line two pixels wide is not something a pointer can catch.
SPLITTER_GRAB = 9.0

#: How far apart the three marks of a splitter's grip are drawn, in pixels.
GRIP_PITCH = 6

#: How wide a button in a view's corner is, in characters of the interface
#: font: a square, with room round the glyph drawn in it.
BUTTON_CHARS = 1.6

#: What each kind a view can be pointed at is called in the name menu, in the
#: order it is offered.
KIND_LABELS = {
    'top': _('Top'), 'bottom': _('Bottom'),
    'front': _('Front'), 'back': _('Back'),
    'left': _('Left'), 'right': _('Right'),
    'perspective': _('Perspective'), 'ortho': _('Ortho'),
}

#: What the view's menu calls the things it does rather than the ways of
#: looking, and the two ways what it holds is drawn.
FIT_LABEL = _('Zoom to fit')
SINGLE_TILE_LABEL = _('Single tile')
TILES_LABEL = _('Four tiles')
SHADED_LABEL = _('Shaded')
WIREFRAME_LABEL = _('Wireframe')
CAMERAS_LABEL = _('Cameras')
VIEW_LABEL = _('View')
RENDERING_LABEL = _('Rendering')

#: What says a name was cut to fit the room it had.
ELLIPSIS = '...'


def axis_directions(view: View) -> Optional[Dict[str, Tuple[float, float]]]:
    """Which way the world's axes run on screen in this view, or None.

    Each is a unit vector in the view's own pixels, x to the right and y up.
    A view with no camera answers None: there is no direction to draw.
    """
    camera = view.camera
    if camera is None:
        return None
    matrix = np.asarray(camera.matrix(), 'd')
    width, height = view.size
    width, height = max(int(width), 1), max(int(height), 1)
    found: Dict[str, Tuple[float, float]] = {}
    for name, axis in (('x', (1.0, 0.0, 0.0)),
                       ('y', (0.0, 1.0, 0.0)),
                       ('z', (0.0, 0.0, 1.0))):
        clip = np.append(np.asarray(axis, 'd'), 0.0) @ matrix
        # Clip units are the whole view across and the whole view down, so a
        # direction reads as a screen direction only once each is measured
        # against the view's own rectangle.
        vector = np.array([clip[0] * width, clip[1] * height], 'd')
        length = float(np.linalg.norm(vector))
        found[name] = ((float(vector[0] / length), float(vector[1] / length))
                       if length > 1e-9 else (0.0, 0.0))
    return found


class _ViewWidget(Widget):
    """A widget drawn inside one view of a layout."""

    #: The view it belongs to. Not a field: a view is not something to
    #: serialise, and the widget is rebuilt whenever the arrangement changes.
    view: Any = None
    #: The chrome that built it, which is what its press acts through.
    chrome: Any = None

    def __init__(self, view: Any = None, chrome: Any = None,
                 **named: Any) -> None:
        super(_ViewWidget, self).__init__(**named)
        self.view = view
        self.chrome = chrome

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        return (metrics.char_height, metrics.char_height)


class ViewLabel(_ViewWidget):
    """The view's name on a button, which opens the menu of what the view can be.

    Drawn with the corner buttons' face and a caret after the name, which is
    what says it opens a list.
    """

    PROTO = 'ViewLabel'
    text = field.newField('text', 'SFString', 1, '')
    interactive = True
    focusable = True
    cursor = 'hand'
    #: It paints the skin's button hover fill under the pointer instead.
    washOnHover = False
    tooltip = _('Which way this view looks, through which of the scene\'s '
                'cameras, and how it is drawn')

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        """The name, the caret after it, and a button's padding round both."""
        pad_x = self.activeSkin().buttonPadding(metrics)[0]
        return (metrics.text_width(str(self.text)) + pad_x * 2
                + _caret_width(metrics),
                int(metrics.char_height * BUTTON_CHARS))

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        metrics = renderer.metrics
        fill, image = skin.buttonState(hovered=self.hovered, down=self.armed,
                                       enabled=bool(self.enabled))
        renderer.frame(self.rect, fill, image)
        pad_x = skin.buttonPadding(metrics)[0]
        caret = _caret_width(metrics)
        body = Rect(self.rect.x + pad_x, self.rect.y,
                    max(self.rect.width - pad_x * 2 - caret, 0), self.rect.height)
        colour = skin.titleText if (self.hovered or self.armed) else skin.labelText
        name = fitted(str(self.text), body.width, metrics)
        if name:
            renderer.textIn(body, name, colour, align='left')
        self._paintCaret(renderer, Rect(body.right, self.rect.y, caret,
                                        self.rect.height), colour)

    @staticmethod
    def _paintCaret(renderer: Any, rect: Rect, colour: Any) -> None:
        """A small chevron pointing down, in the middle of ``rect``."""
        half = max(rect.width // 4, 2)
        middle_x, middle_y = rect.centre
        tip = (middle_x, middle_y - half // 2)
        renderer.segment((middle_x - half, middle_y + half // 2), tip, 1.5, colour)
        renderer.segment(tip, (middle_x + half, middle_y + half // 2), 1.5, colour)

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<return>', ' ') and self.enabled:
            self.activate()
            return True
        return False

    def activate(self) -> None:
        if self.chrome is not None:
            self.chrome.open_names(self.view, self.rect)
        super(ViewLabel, self).activate()


def _caret_width(metrics: FontMetrics) -> int:
    """Room for the caret after a view's name: about a character and a half."""
    return max(int(metrics.char_width * 1.5), 6)


class AxisTriad(_ViewWidget):
    """Three arms from a corner, saying which way the world's axes run here."""

    PROTO = 'AxisTriad'

    def paint(self, renderer: Any) -> None:
        directions = axis_directions(self.view)
        if directions is None:
            return
        centre = self.rect.centre
        reach = min(self.rect.width, self.rect.height) / 2.0 - 4.0
        for name in ('z', 'y', 'x'):
            dx, dy = directions[name]
            end = (centre[0] + dx * reach, centre[1] + dy * reach)
            renderer.segment(centre, end, 2.0, AXIS_COLOURS[name])
            renderer.text(name.upper(), int(end[0]) - 3, int(end[1]) - 4,
                          AXIS_COLOURS[name])


class _ChromeButton(_ViewWidget):
    """A small square button in a view's corner, drawn with a glyph on it.

    The glyphs are drawn rather than loaded: a window of views is furniture
    every application built on the engine gets, and one that ships no artwork
    at all still gets buttons that say what they do. They stay crisp at any
    interface scale for the same reason.
    """

    interactive = True
    focusable = True
    #: It paints the skin's button hover fill under the pointer instead.
    washOnHover = False

    def content_size(self, metrics: FontMetrics,
                     available: Optional[int] = None) -> Tuple[int, int]:
        side = int(metrics.char_height * BUTTON_CHARS)
        return (side, side)

    def paint(self, renderer: Any) -> None:
        self.paintFocus(renderer)
        skin = renderer.skin
        fill, image = skin.buttonState(hovered=self.hovered, down=self.armed,
                                       enabled=bool(self.enabled))
        renderer.frame(self.rect, fill, image)
        colour = skin.titleText if self.hovered else skin.labelText
        self.glyph(renderer, self.rect.inset(max(self.rect.width // 4, 2)),
                   colour)

    def glyph(self, renderer: Any, rect: Rect, colour: Any) -> None:
        """Draw what this button does, inside ``rect``."""

    def key(self, name: str, modifiers: Tuple[int, int, int]) -> bool:
        if name in ('<return>', ' ') and self.enabled:
            self.activate()
            return True
        return False


class ExpandButton(_ChromeButton):
    """Gives this view the whole window, and gives the arrangement back.

    One button, and which it is doing is what it draws: an outline where the
    view would be given the window, and the tiles it would be given back to
    where it already has it.
    """

    PROTO = 'ExpandButton'
    cursor = 'hand'

    def maximised(self) -> bool:
        """Whether this view already has the window."""
        layout = getattr(self.chrome, 'layout_of', None)
        return layout is not None and layout.maximised is self.view

    def glyph(self, renderer: Any, rect: Rect, colour: Any) -> None:
        if not self.maximised():
            renderer.border(rect, colour, 1)
            return
        # Back to the tiles: four of them, with the gap the splitters make.
        gap = max(rect.width // 8, 1)
        side = (rect.width - gap) // 2, (rect.height - gap) // 2
        for x in (rect.x, rect.x + side[0] + gap):
            for y in (rect.y, rect.y + side[1] + gap):
                renderer.rect(Rect(x, y, side[0], side[1]), colour)

    @property
    def tooltip(self) -> str:  # type: ignore[override]  # read-only here: it follows the layout
        """What pressing it would do: give the view the window, or give it back."""
        return (_('Give the views back their tiles') if self.maximised()
                else _('Single tile: this view alone in the window'))

    def activate(self) -> None:
        if self.chrome is not None:
            self.chrome.maximise(self.view)
        super(ExpandButton, self).activate()


class Splitter(Widget):
    """A line an arrangement divides the window along, which a drag moves.

    ``vertical`` is True for the line down the window, False for the one
    across it, and None for the place a quad's two lines cross, where a drag
    moves both.
    """

    PROTO = 'ViewSplitter'
    interactive = True
    #: The line lights itself, and it is dragged rather than clicked.
    washOnHover = False
    ripples = False
    tooltip = _('Drag to move the line between the views')

    vertical: Optional[bool] = True
    chrome: Any = None

    def __init__(self, vertical: Optional[bool] = True, chrome: Any = None,
                 **named: Any) -> None:
        super(Splitter, self).__init__(**named)
        self.vertical = vertical if vertical is None else bool(vertical)
        self.chrome = chrome
        # What the pointer says about it: a line that drags one way asks for
        # the arrows that drag that way, and the crossing for either.
        self.cursor = {True: 'resize-x', False: 'resize-y'}.get(
            self.vertical, 'resize')

    def press(self, x: float, y: float) -> bool:
        self.armed = True
        return True

    def drag(self, x: float, y: float) -> None:
        if self.chrome is not None:
            self.chrome.move_split(self, x, y)

    def release(self, x: float, y: float) -> bool:
        taken, self.armed = self.armed, False
        return taken

    def paint(self, renderer: Any) -> None:
        if self.vertical is None:
            # The two lines already cross here; this only takes the drag.
            return
        skin = renderer.skin
        held = self.hovered or self.armed
        colour = skin.titleText if held else skin.labelText
        middle = self.rect.centre
        if self.vertical:
            line = Rect(middle[0], self.rect.y, 1, self.rect.height)
        else:
            line = Rect(self.rect.x, middle[1], self.rect.width, 1)
        renderer.rect(line, colour)
        # Grips along the line, away from where the lines cross: a cursor that
        # says "this drags" is a cursor theme's to provide and some have none,
        # so the line says it itself. One on each half, so a line divided by
        # another shows one either side of the crossing.
        for share in (0.25, 0.75):
            if self.vertical:
                along = self.rect.y + int(self.rect.height * share)
                for offset in (-GRIP_PITCH, 0, GRIP_PITCH):
                    renderer.rect(Rect(middle[0] - 1, along + offset, 3, 2),
                                  colour)
            else:
                along = self.rect.x + int(self.rect.width * share)
                for offset in (-GRIP_PITCH, 0, GRIP_PITCH):
                    renderer.rect(Rect(along + offset, middle[1] - 1, 2, 3),
                                  colour)


class ViewChrome(Panel):
    """Each view's name, axes and controls, and the splitters between them."""

    PROTO = 'ViewChrome'
    #: Which parts every view gets.
    labels = field.newField('labels', 'SFBool', 1, True)
    axes = field.newField('axes', 'SFBool', 1, True)
    expand = field.newField('expand', 'SFBool', 1, True)
    splitters = field.newField('splitters', 'SFBool', 1, True)
    #: Room something else has taken at each edge of the window -- top,
    #: right, bottom, left, in reference pixels, as a
    #: :class:`~OpenGLContext.ui.hudwidgets.HUDLayer` is told it. Furniture in
    #: a view that reaches that edge starts inside it, so a name drawn under a
    #: menu bar or behind a tool palette is not what a window with either
    #: gets.
    reserved = field.newField('reserved', 'SFVec4f', 1, (0.0, 0.0, 0.0, 0.0))

    def __init__(self, layout: Optional[ViewLayout] = None,
                 stack: Any = None,
                 on_arrange: Optional[Callable[[], None]] = None,
                 only: Optional[Dict[str, Sequence[str]]] = None,
                 bounds: Optional[Callable[[], Optional[Tuple[Any, Any]]]] = None,
                 cameras: Union[Sequence[SceneCamera],
                                Callable[[], Sequence[SceneCamera]], None] = None,
                 **named: Any) -> None:
        named.setdefault('modal', False)
        named.setdefault('closeOnEscape', False)
        super(ViewChrome, self).__init__(**named)
        #: The layout whose views are dressed.
        self.layout_of = layout
        #: Where a navigation menu is put up; None draws no menu.
        self.stack = stack
        #: Called when a control changed the arrangement, so the window
        #: places its views again and draws.
        self.on_arrange = on_arrange
        #: Views whose parts are not the window's, by view name.
        self.only = dict(only or {})
        #: What there is to see, as ``(minimum, maximum)``, for the menu's
        #: *zoom to fit*. A window that does not say offers no such item.
        self.bounds = bounds
        #: The scene's cameras, or what answers them, for the menu's
        #: *Cameras*. None, or none answered, offers no such item.
        self.cameras = cameras
        self._splitters: List[Splitter] = []

    # -- what each view gets -----------------------------------------------
    def parts_for(self, view: View) -> Tuple[str, ...]:
        """Which parts this view is given."""
        named = self.only.get(str(view.name))
        if named is not None:
            return tuple(part for part in PARTS if part in named)
        offered = {'label': bool(self.labels), 'axes': bool(self.axes),
                   'expand': bool(self.expand)}
        return tuple(part for part in PARTS if offered[part])

    def rebuild(self) -> None:
        """Make the furniture for the views the arrangement is showing."""
        children: List[Widget] = []
        self._splitters = []
        for view in self._shown():
            parts = self.parts_for(view)
            navigable = view.camera is not None
            if 'label' in parts:
                children.append(ViewLabel(text=str(view.name), view=view,
                                          chrome=self))
            if 'axes' in parts and navigable:
                children.append(AxisTriad(view=view, chrome=self))
            if 'expand' in parts and self._can_maximise():
                children.append(ExpandButton(view=view, chrome=self))
        if self.splitters:
            self._splitters = self._split_widgets()
            children.extend(self._splitters)
        self.children = children

    def _shown(self) -> List[View]:
        layout = self.layout_of
        if layout is None:
            return []
        return [view for view in layout.views if view.visible]

    def _split_widgets(self) -> List[Splitter]:
        """One splitter per line this arrangement divides the window along."""
        layout = self.layout_of
        if layout is None or layout.maximised is not None:
            return []
        arrangement = getattr(layout, 'arrangement', None)
        if arrangement == 'split':
            return [Splitter(vertical=True, chrome=self)]
        if arrangement == 'stack':
            return [Splitter(vertical=False, chrome=self)]
        if arrangement == 'quad':
            # The cross last, so it is in front of the two lines it moves.
            return [Splitter(vertical=True, chrome=self),
                    Splitter(vertical=False, chrome=self),
                    Splitter(vertical=None, chrome=self)]
        return []

    # -- where it all goes --------------------------------------------------
    def layout(self, viewport: Tuple[int, int], metrics: FontMetrics) -> None:
        self.rebuild()
        self.link()
        self.scaleSkin(metrics)
        self._title_height = 0
        width, height = int(viewport[0]), int(viewport[1])
        self.rect = Rect(0, 0, width, height)
        self.arrange_content(metrics)

    def roomIn(self, view: View, metrics: FontMetrics) -> Rect:
        """The rectangle a view's furniture goes in: the view, less what is reserved.

        A view that reaches an edge of the window keeps clear of whatever has
        taken room there; one that does not is the whole of its own tile.
        """
        x, y, width, height = view.rect
        top, right, bottom, left = (metrics.pixels(value)
                                    for value in self.reserved)
        if y + height < self.rect.height:
            top = 0
        if x + width < self.rect.width:
            right = 0
        if y > 0:
            bottom = 0
        if x > 0:
            left = 0
        return Rect(x + left, y + bottom,
                    max(width - left - right, 1), max(height - top - bottom, 1))

    def arrange_content(self, metrics: FontMetrics) -> None:
        """Put each view's furniture in its corners, and the splitters on the lines."""
        margin = metrics.pixels(MARGIN)
        row = metrics.char_height + margin
        triad = metrics.pixels(TRIAD_SIZE)
        for view in self._shown():
            room = self.roomIn(view, metrics)
            top = room.y + room.height - margin - metrics.char_height
            # The buttons first, from the right, so the name has what is left
            # rather than running underneath them.
            cursor = room.x + room.width - margin
            for child in self._parts_of(view, _ChromeButton):
                child.parent = self
                side = int(child.content_size(metrics)[0])
                cursor -= side
                # Square, and hanging from the row the name is on.
                child.arrange(Rect(cursor, top + metrics.char_height - side,
                                   side, side), metrics)
                cursor -= margin
            for child in self._parts_of(view, ViewLabel):
                child.parent = self
                width, side = (int(value) for value in child.content_size(metrics))
                # The size of its name, and no wider than the room the
                # buttons leave; hanging from the row as they do.
                child.arrange(Rect(room.x + margin,
                                   top + metrics.char_height - side,
                                   max(min(width, cursor - room.x - margin), 1),
                                   side), metrics)
            for child in self._parts_of(view, AxisTriad):
                child.parent = self
                child.arrange(Rect(room.x + margin, room.y + margin,
                                   min(triad, max(room.width - margin * 2, 1)),
                                   min(triad, max(room.height - row, 1))),
                              metrics)
        self._arrange_splitters(metrics)

    def _parts_of(self, view: View, kind: Any) -> List[Widget]:
        """This view's furniture of one kind, in the order it was built."""
        return [child for child in self.layoutChildren()
                if isinstance(child, kind) and getattr(child, 'view', None) is view]

    def _arrange_splitters(self, metrics: FontMetrics) -> None:
        layout = self.layout_of
        if layout is None or not self._splitters:
            return
        grab = max(int(metrics.pixels(SPLITTER_GRAB)), 3)
        width, height = self.rect.width, self.rect.height
        across = int(round(width * layout.split_at[0]))
        down = height - int(round(height * layout.split_at[1]))
        for splitter in self._splitters:
            splitter.parent = self
            if splitter.vertical is None:
                splitter.arrange(Rect(across - grab, down - grab,
                                      grab * 2, grab * 2), metrics)
            elif splitter.vertical:
                splitter.arrange(Rect(across - grab // 2, 0, grab, height),
                                 metrics)
            else:
                splitter.arrange(Rect(0, down - grab // 2, width, grab), metrics)

    def paint(self, renderer: Any) -> None:
        """Nothing of its own: the furniture is what is drawn.

        A panel fills its rectangle and draws a border round it. This one
        stands over the whole window, and filling that would put a wash over
        the scene it is labelling.
        """

    # -- what the controls do ----------------------------------------------
    def maximise(self, view: View) -> None:
        """Give ``view`` the whole window, or give the arrangement back."""
        layout = self.layout_of
        if layout is None:
            return
        layout.maximise(view)
        self._changed()

    def move_split(self, splitter: Splitter, x: float, y: float) -> None:
        """Put the line the splitter stands on where the pointer is."""
        layout = self.layout_of
        if layout is None:
            return
        across, down = layout.split_at
        if splitter.vertical is not False:
            across = float(x) / max(self.rect.width, 1)
        if splitter.vertical is not True:
            down = 1.0 - float(y) / max(self.rect.height, 1)
        layout.split_at = (across, down)
        self._changed()

    def open_names(self, view: View, at: Rect) -> Optional[Menu]:
        """Put up what this view can be: its menu; None with no stack to put it on.

        Three lists a level down -- which way it looks (**View**), the scene's
        own cameras (**Cameras**), how it is drawn (**Rendering**) -- and the
        two things a view does: fit what there is to see into it, and take the
        window or give it back, where the arrangement has other views to
        hide. A view drawn through the window's own camera
        has no ways of looking to offer, and a scene with no cameras no
        cameras.
        """
        if self.stack is None:
            return None
        items: List[Any] = []
        if view.camera is not None:
            items.append(MenuItem(text=VIEW_LABEL, submenu=[
                self._kind_item(view, kind) for kind in VIEW_KINDS]))
        cameras = self.sceneCameras()
        if cameras:
            items.append(MenuItem(text=CAMERAS_LABEL, submenu=[
                self._camera_item(view, camera) for camera in cameras]))
        items.append(MenuItem(text=RENDERING_LABEL,
                              submenu=self._drawn_items(view)))
        items.append(Separator())
        if self.bounds is not None and view.camera is not None:
            def fit_it(widget: Any, view: View = view) -> None:
                self.fit(view)

            items.append(MenuItem(text=FIT_LABEL, on_activate=fit_it))
        if self._can_maximise():
            items.append(MenuItem(
                text=(TILES_LABEL if self._maximised(view) else SINGLE_TILE_LABEL),
                on_activate=lambda widget: self.maximise(view)))
        return self._put_up(Menu(items=items, anchor=(float(at.x), float(at.y)),
                                 above=float(at.top), stack=self.stack))

    def sceneCameras(self) -> List[SceneCamera]:
        """The cameras the menu offers: what ``cameras`` is, or answers."""
        found = self.cameras() if callable(self.cameras) else self.cameras
        return list(found or ())

    def _camera_item(self, view: View, camera: SceneCamera) -> MenuItem:
        """One of the scene's cameras, which the view is pointed through when chosen."""
        def chosen(widget: Any) -> None:
            if look_through(view, camera, distance=self._ahead_of(camera)):
                self._changed()

        return MenuItem(text=camera.name, on_activate=chosen)

    def _ahead_of(self, camera: SceneCamera) -> Optional[float]:
        """How far ahead of ``camera`` the middle of what there is to see is, or None."""
        found = self.bounds() if self.bounds is not None else None
        if not found:
            return None
        low, high = (np.asarray(corner, 'd')[:3] for corner in found)
        along = float(((low + high) / 2.0 - np.asarray(camera.position, 'd'))
                      @ np.asarray(camera.forward, 'd'))
        return max(along, float(np.linalg.norm(high - low)) * 0.05, 1e-6)

    def _kind_item(self, view: View, kind: str) -> MenuItem:
        """One way of looking, ticked where the view is looking that way."""
        item = MenuItem(text=KIND_LABELS.get(kind, kind), checkable=True,
                        checked=(view_kind(view) == kind))

        def chosen(widget: Any, kind: str = kind) -> None:
            point_view(view, kind)
            self._changed()

        item.on_activate = chosen
        return item

    def _drawn_items(self, view: View) -> List[MenuItem]:
        """Shaded or wireframe: how what the view holds is drawn."""
        wire = bool(view.style.wireframe)
        items = []
        for label, wanted in ((SHADED_LABEL, False), (WIREFRAME_LABEL, True)):
            item = MenuItem(text=label, checkable=True, checked=(wire == wanted))

            def chosen(widget: Any, wanted: bool = wanted) -> None:
                # A style is a value, not a setting to be poked: the view is
                # given another one.
                view.style = replace(view.style, wireframe=wanted)
                self._changed()

            item.on_activate = chosen
            items.append(item)
        return items

    def fit(self, view: View) -> bool:
        """Fit what there is to see into this view; False with nothing to fit.

        ``bounds`` is what the window says there is: the corners of the world,
        or of what is loaded in it.
        """
        if self.bounds is None:
            return False
        found = self.bounds()
        if not found:
            return False
        minimum, maximum = found
        size = view.size if view.visible else (self.rect.width, self.rect.height)
        fitted_it = fit_view(view, minimum, maximum, size)
        if fitted_it:
            self._changed()
        return fitted_it

    def _can_maximise(self) -> bool:
        """Whether the arrangement has other views for one to be shown without."""
        layout = self.layout_of
        return layout is not None and layout.can_maximise

    def _maximised(self, view: View) -> bool:
        layout = self.layout_of
        return layout is not None and layout.maximised is view

    def _put_up(self, menu: Menu) -> Menu:
        pushed = self.stack.push(menu)
        return pushed if isinstance(pushed, Menu) else menu

    def _changed(self) -> None:
        if self.on_arrange is not None:
            self.on_arrange()


def fitted(text: str, width: int, metrics: FontMetrics) -> str:
    """``text`` cut to the room it has, with an ellipsis where it was cut.

    A name is drawn where there is a corner for it and a view can be a
    quarter of a small window, so what will not fit says so rather than
    running out across the scene: nothing here clips what it draws.
    """
    if not text or metrics.text_width(text) <= width:
        return text
    for end in range(len(text) - 1, 0, -1):
        cut = text[:end] + ELLIPSIS
        if metrics.text_width(cut) <= width:
            return cut
    return ''

