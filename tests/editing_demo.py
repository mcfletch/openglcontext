#! /usr/bin/env python
'''=Editing a world: tool modes, a plan view and the point under the cursor=

[editing_demo.py-screen-0001.png Screenshot]

The editor toolkit (`OpenGLContext.edit`) driving a small world: ground,
five blocks, and markers dropped and dragged onto it by tools.

The camera is a `MapViewPlatform` -- straight down, orthographic, 120 m
down the window -- so a metre is the same number of pixels wherever it is
and the pointer can be aimed at the world.  Press `o` for the
`OrbitViewPlatform`, the three-quarter view the same world is judged on,
and `m` to come back.

The pointer goes to the **tool in force before the camera sees it**.
`ProcessEvent` offers each event to a `ToolManager` and only calls up the
chain with what the tool did not want, so the left button edits and the
right button still moves the camera.  Three tools are declared:

 * `1` *drop* -- put a marker where the pointer is.  The world point comes
   from `pointer_from(event)`: the pick already read the depth back, so
   unprojecting it is exact and costs nothing more.
 * `2` *move* -- grab the marker within 12 m of the pointer and drag it.  A
   drag cannot use the depth, because the depth under the cursor is the
   thing being dragged; it runs against the level plane the drag began on
   instead (`ray_from`, `ray_plane` and `horizon_plane`).
 * `3` *pan* -- `maptools.PanTool`, which drags the plan view about.

`u` takes back the last thing the tool in force did and `r` does it again;
each tool keeps its own history.  The right button orbits the three-quarter
view and drags the plan view, and the wheel dollies or zooms, because no
tool takes either.

Nobody moves the mouse while a screenshot is being taken, so the demo
drives itself: five clicks and one drag, one per frame, through the pick.
Each prints both ends of the round trip -- the pixel `screen_from_world`
draws a world point at, and the world point the pick answers with there:

    click  pixel (674, 510) <- world (22.0, -30.0)
    drop   marker 2 at world (21.88, 20.00, -30.00)

That third click is aimed at the middle of a 20 m block, so it comes back
20 m up and the marker stands on the roof.  The drag then takes the first
marker 66 m across the ground:

    move   marker 0 from (-50.12, 18.00) to (-46.00, -48.00)
'''
import os

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from functools import partial

import numpy as np

from OpenGLContext import testingcontext
from OpenGLContext.edit.maptools import PanTool
from OpenGLContext.edit.mapview import MapView, MapViewPlatform
from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform
from OpenGLContext.edit.surface import (
    horizon_plane, pointer_from, ray_from, ray_plane,
)
from OpenGLContext.edit.tools import ToolManager, ToolMode
from OpenGLContext.events import synthetic
from OpenGLContext.events.mouseevents import WHEEL_BUTTONS, WHEEL_UP
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, Cone, DirectionalLight, Material, Shape,
    Transform,
)

BaseContext = testingcontext.getInteractive('glfw')

#: How far the ground reaches, in metres square.  Wider than any window's
#: worth of map, so the plan view never runs off the edge of the world.
GROUND = 300.0

#: How many metres fit down the height of the window in the plan view.
MAP_SPAN = 120.0

#: The blocks that are in the world before anything is edited: where they
#: stand in ``(x, z)``, their footprint in ``(x, z)``, and their height.
BLOCKS = [
    ((-38.0, -26.0), (24.0, 14.0), 12.0),
    ((22.0, -30.0), (18.0, 18.0), 20.0),
    ((-6.0, 30.0), (30.0, 12.0), 8.0),
    ((80.0, 12.0), (22.0, 26.0), 15.0),
    ((-86.0, 4.0), (26.0, 20.0), 10.0),
]

#: Where the scripted clicks are aimed, in world ``(x, z)`` metres.  The
#: script turns each into the pixel the plan view draws it at, so a marker
#: landing where it was asked for is ``screen_from_world`` and the pick's
#: depth agreeing.  The third is on the roof of the 20 m block.
PLACEMENTS = [(-50.0, 18.0), (-18.0, 44.0), (22.0, -30.0), (52.0, 6.0),
              (2.0, -4.0)]

#: Where the scripted drag takes the first marker, in world metres.
DRAG_TO = (-46.0, -48.0)

#: One colour per marker, in the order they are dropped.
MARKER_COLOURS = [
    (0.90, 0.55, 0.15), (0.30, 0.70, 0.85), (0.85, 0.30, 0.35),
    (0.45, 0.80, 0.40), (0.75, 0.45, 0.85),
]


class MarkerField:
    """The markers an edit puts down, and the arithmetic to find one.

    A plain object holding a scenegraph group: no GL and no window, so the
    rule about which marker the pointer grabbed can be exercised on its own.
    """

    #: How near a marker's centre the pointer must be to grab it, in metres.
    REACH = 12.0

    #: How big a marker is drawn, in metres.
    RADIUS, HEIGHT = 3.2, 9.0

    def __init__(self):
        self.group = Transform(children=[])
        #: Where each marker stands, as world ``(x, y, z)``.
        self.points = []

    def place(self, point):
        """Put a marker on the world at a point.  Answers its index."""
        index = len(self.points)
        colour = MARKER_COLOURS[index % len(MARKER_COLOURS)]
        node = Transform(children=[
            Shape(geometry=Cone(bottomRadius=self.RADIUS, height=self.HEIGHT),
                  appearance=Appearance(
                      material=Material(diffuseColor=colour)))])
        self.group.children = list(self.group.children) + [node]
        self.points.append(np.zeros(3, dtype='d'))
        self.move(index, point)
        return index

    def move(self, index, point):
        """Stand marker ``index`` on a world point."""
        point = np.asarray(point, dtype='d')
        self.points[index] = point
        # The cone's origin is its middle, so half its height puts its point
        # up and its base on the ground.
        self.group.children[index].translation = (
            point[0], point[1] + self.HEIGHT / 2.0, point[2])

    def remove_last(self):
        """Take the newest marker away.  Answers its point, or None."""
        if not self.points:
            return None
        self.group.children = list(self.group.children)[:-1]
        return self.points.pop()

    def nearest(self, point):
        """The marker within :attr:`REACH` of a world point, or None.

        Measured on the ground rather than in three dimensions, because a
        marker standing on a roof is grabbed by pointing at where it is on
        the map, not by how far up it happens to be.
        """
        best, distance = None, self.REACH
        for index, at in enumerate(self.points):
            span = float(np.hypot(at[0] - point[0], at[2] - point[2]))
            if span <= distance:
                best, distance = index, span
        return best


class DropMarker(ToolMode):
    """Put a marker on the world where the pointer is.

    The left button only, and only where there is something under the
    cursor: over the sky there is no point to put anything on, and the
    right button is what the camera orbits with.
    """

    def __init__(self, field, **named):
        named.setdefault('name', 'drop')
        named.setdefault('label', 'Drop marker')
        super(DropMarker, self).__init__(**named)
        self.field = field
        self._taken = []

    def on_press(self, pointer):
        if pointer.button or not pointer.on_surface:
            return False
        index = self.field.place(pointer.world)
        print('drop   marker %d at world (%.2f, %.2f, %.2f)'
              % (index, pointer.world[0], pointer.world[1], pointer.world[2]))
        return True

    def undo(self):
        point = self.field.remove_last()
        if point is None:
            return False
        self._taken.append(point)
        print('undo   marker %d' % (len(self.field.points),))
        return True

    def redo(self):
        if not self._taken:
            return False
        self.field.place(self._taken.pop())
        return True


class MoveMarker(ToolMode):
    """Drag a marker across the ground.

    The press picks whichever marker is under the cursor; every point after
    it arrives resolved against the level plane the drag began on, so the
    marker travels across the world at the height it started at rather than
    climbing whatever it passes over.
    """

    def __init__(self, field, **named):
        named.setdefault('name', 'move')
        named.setdefault('label', 'Move marker')
        super(MoveMarker, self).__init__(**named)
        self.field = field
        self._index = None
        self._from = None

    def cancel(self):
        """Escape part-way through: put it back where it came from."""
        if self._index is not None:
            self.field.move(self._index, self._from)
        self._index, self._from = None, None

    def on_press(self, pointer):
        if pointer.button or not pointer.on_surface:
            return False
        index = self.field.nearest(pointer.world)
        if index is None:
            return False
        self._index = index
        self._from = np.array(self.field.points[index])
        return True

    def on_drag(self, pointer):
        if self._index is None or not pointer.on_surface:
            return False
        self.field.move(self._index, pointer.world)
        return True

    def on_release(self, pointer):
        if self._index is None:
            return False
        moved = self.field.points[self._index]
        print('move   marker %d from (%.2f, %.2f) to (%.2f, %.2f)'
              % (self._index, self._from[0], self._from[2],
                 moved[0], moved[2]))
        self._index, self._from = None, None
        return True


def _block(centre, footprint, height, material):
    """One of the blocks that are in the world to start with."""
    return Transform(translation=(centre[0], height / 2.0, centre[1]),
                     children=[Shape(
                         geometry=Box(size=(footprint[0], height,
                                            footprint[1])),
                         appearance=Appearance(material=material))])


class TestContext(BaseContext):
    """A small world, two editor cameras, and a pointer the tools get first."""

    #: Where the base class would stand its camera.  This one replaces the
    #: platform outright, in :meth:`OnInit`, with the two an editor uses.
    initialPosition = (0, 120, 160)

    #: How many idle passes a scripted step may wait for the pick to answer
    #: the step before it.
    PATIENCE = 90

    def OnInit(self):
        BaseContext.OnInit(self)
        self.markers = MarkerField()
        slate = Material(diffuseColor=(0.55, 0.56, 0.60))
        self.sg = Transform(children=[
            Background(skyColor=[(0.30, 0.45, 0.72), (0.63, 0.75, 0.90),
                                 (0.84, 0.86, 0.86)],
                       skyAngle=[1.15, 1.5708]),
            # A key light just off vertical and a cool fill from the other
            # side.  A light straight overhead leaves a plan view nothing to
            # shade with, and every roof comes out the same colour.
            DirectionalLight(direction=(-0.20, -0.95, -0.24), intensity=0.9),
            DirectionalLight(direction=(0.55, -0.70, 0.45), intensity=0.55,
                             color=(0.70, 0.78, 1.00)),
            Transform(translation=(0.0, -1.0, 0.0), children=[
                Shape(geometry=Box(size=(GROUND, 2.0, GROUND)),
                      appearance=Appearance(material=Material(
                          diffuseColor=(0.38, 0.42, 0.33))))]),
        ] + [_block(*block, material=slate) for block in BLOCKS]
            + [self.markers.group])

        self.mapView = MapView(centre=(0.0, 0.0), span=MAP_SPAN,
                               floor=-20.0, ceiling=60.0)
        self.orbitView = OrbitView(centre=(0.0, 0.0), heading=28.0,
                                   distance=210.0)
        self.mapPlatform = MapViewPlatform(self.mapView, self.getViewPort())
        self.orbitPlatform = OrbitViewPlatform(self.orbitView,
                                               self.getViewPort())
        self.tools = ToolManager([
            DropMarker(self.markers),
            MoveMarker(self.markers),
            PanTool(self.mapView, self.getViewPort, on_change=self.OnMapMoved),
        ], on_change=self.OnToolChanged)

        #: The height a drag runs against, while one is going on.
        self._dragHeight = None
        #: Where the camera's own drag last was, in pixels.
        self._cameraFrom = None
        self._waited = 0
        self.script = [partial(self._clickOn, point) for point in PLACEMENTS]
        self.script.append(self._dragFirstMarker)

        self.OnPlanView()
        self.addEventHandler('keypress', name='m', function=self.OnPlanView)
        self.addEventHandler('keypress', name='o', function=self.OnOrbitView)
        for index in range(len(self.tools.tools)):
            self.addEventHandler('keypress', name=str(index + 1),
                                 function=self.OnSelectTool)
        self.addEventHandler('keypress', name='u', function=self.OnUndo)
        self.addEventHandler('keypress', name='r', function=self.OnRedo)
        print(__doc__)

    # -- the two cameras ---------------------------------------------------
    def OnPlanView(self, event=None):
        """Straight down and orthographic: the view a route is drawn on."""
        self._useCamera(self.mapPlatform)

    def OnOrbitView(self, event=None):
        """Three-quarter: the view the same world is judged on."""
        self._useCamera(self.orbitPlatform)

    def _useCamera(self, platform):
        self.platform = platform
        platform.setViewport(*self.getViewPort())
        self.triggerRedraw(1)

    def OnMapMoved(self):
        self.triggerRedraw(1)

    # -- the tools ---------------------------------------------------------
    def OnSelectTool(self, event):
        index = int(event.name) - 1
        if 0 <= index < len(self.tools.tools):
            self.tools.select(self.tools.tools[index].name)

    def OnToolChanged(self, tool):
        print('tool   %s' % (tool.label,))

    def OnUndo(self, event):
        self.tools.undo()
        self.triggerRedraw(1)

    def OnRedo(self, event):
        self.tools.redo()
        self.triggerRedraw(1)

    # -- the pointer, before the camera ------------------------------------
    def ProcessEvent(self, event):
        """Offer every event to the tool in force before anything else.

        Returning without calling up the chain is what "the tool took it"
        means: the movement sampler reads events here too, so an event a
        tool has taken never reaches the camera.
        """
        if self._toolTakes(event):
            return None
        return super(TestContext, self).ProcessEvent(event)

    def _toolTakes(self, event):
        kind = getattr(event, 'type', None)
        if kind == 'mousebutton':
            if event.button in WHEEL_BUTTONS:
                if not event.state:
                    return True     # a notch is the press; its release is not
                notches = 1 if event.button == WHEEL_UP else -1
                return (self.tools.wheel(self._pointer(event), notches)
                        or self._cameraWheel(notches))
            if event.state:
                return self._press(event)
            return self._release(event)
        if kind == 'mousemove':
            return self._move(event)
        if kind == 'keypress':
            return self.tools.key(event.name, event.getModifiers())
        return False

    def _pointer(self, event):
        """What a tool is handed for an event.

        The pick's depth says where the surface under the cursor is, and the
        event arrives carrying the camera the frame was drawn with, so
        ``pointer_from`` has everything it needs.

        While a drag is going on the depth under the cursor is the thing
        being dragged, so the point comes from the level plane the drag
        began on instead.
        """
        pointer = pointer_from(event)
        if self._dragHeight is not None:
            origin, direction = ray_from(event)
            pointer.world = ray_plane(origin, direction,
                                      *horizon_plane(self._dragHeight))
        return pointer

    def _press(self, event):
        pointer = self._pointer(event)
        if self.tools.press(pointer):
            # Where the drag runs, for as long as it lasts.  A tool that took
            # a press over nothing -- panning the map -- leaves no plane, and
            # wants the pointer's pixels rather than its world point anyway.
            self._dragHeight = (float(pointer.world[1])
                                if pointer.on_surface else None)
            self.triggerRedraw(1)
            return True
        return self._cameraPress(event)

    def _move(self, event):
        if self.tools.move(self._pointer(event)):
            self.triggerRedraw(1)
            return True
        return self._cameraDrag(event)

    def _release(self, event):
        taken = self.tools.release(self._pointer(event))
        self._dragHeight = None
        self._cameraFrom = None
        if taken:
            self.triggerRedraw(1)
        return taken

    def hasMouseMoveHandlers(self):
        """The tools read moves through :meth:`ProcessEvent`.

        The render pass drops mouse moves when nothing is registered for
        them, and the handler registry cannot see a context that reads them
        on the way past.
        """
        return True

    # -- whatever the tools did not want -----------------------------------
    def _cameraPress(self, event):
        if event.button != 1:
            return False
        self._cameraFrom = tuple(event.getPickPoint())
        return True

    def _cameraDrag(self, event):
        if self._cameraFrom is None:
            return False
        x, y = event.getPickPoint()
        dx, dy = x - self._cameraFrom[0], y - self._cameraFrom[1]
        self._cameraFrom = (x, y)
        if self.platform is self.mapPlatform:
            self.mapView.pan(dx, dy, self.getViewPort())
        else:
            self.orbitView.orbit(-dx * 0.3, dy * 0.3)
        self.triggerRedraw(1)
        return True

    def _cameraWheel(self, notches):
        factor = 1.25 ** (-notches)
        if self.platform is self.mapPlatform:
            self.mapView.zoom(factor)
        else:
            self.orbitView.dolly(factor)
        self.triggerRedraw(1)
        return True

    # -- driving it without a hand on the mouse ----------------------------
    def OnIdle(self, *arguments):
        """One scripted step per pass, while there are any left.

        A step answers whether it was dispatched; one still waiting for the
        pick to resolve the step before it stays at the head of the queue.
        """
        if not self.script:
            return 0
        if self.script[0]():
            self.script.pop(0)
            self._waited = 0
        else:
            self._waited += 1
            if self._waited > self.PATIENCE:
                self.script = []
        self.triggerRedraw(1)
        return 0

    def _click(self, x, y, button=0):
        """A press and its release at a pixel, through the pick.

        Both go in before the pick runs: they are one frame's news and the
        context holds them apart by their state, so the tool is handed the
        pair in order.  Two *presses* in one frame would be one press.
        """
        for state in (1, 0):
            event = synthetic.build({'type': 'mousebutton', 'button': button,
                                     'state': state, 'x': x, 'y': y})
            event.context = self
            self.addPickEvent(event)
        self.triggerPick()

    def _clickOn(self, point):
        """Click where the plan view draws a world point."""
        self.tools.select('drop')
        x, y = self.mapView.screen_from_world(point, self.getViewPort())
        print('click  pixel (%d, %d) <- world (%.1f, %.1f)'
              % (x, y, point[0], point[1]))
        self._click(x, y)
        return True

    def _dragFirstMarker(self):
        """Drag the marker dropped first across to :data:`DRAG_TO`.

        Waits until every scripted click has been answered, so the marker it
        grabs is one the pick has already put down.
        """
        if len(self.markers.points) < len(PLACEMENTS):
            return False
        self.tools.select('move')
        viewport = self.getViewPort()
        start = self.mapView.screen_from_world(self.markers.points[0], viewport)
        end = self.mapView.screen_from_world(DRAG_TO, viewport)
        print('drag   pixel (%d, %d) -> (%d, %d)'
              % (start[0], start[1], end[0], end[1]))
        for record in (
            {'type': 'mousebutton', 'button': 0, 'state': 1,
             'x': start[0], 'y': start[1]},
            {'type': 'mousemove', 'buttons': [0], 'x': end[0], 'y': end[1]},
            {'type': 'mousebutton', 'button': 0, 'state': 0,
             'x': end[0], 'y': end[1]},
        ):
            event = synthetic.build(record)
            event.context = self
            self.addPickEvent(event)
        self.triggerPick()
        return True


if __name__ == "__main__":
    TestContext.ContextMainLoop()
