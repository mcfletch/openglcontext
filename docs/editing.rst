Building an editor
==================

.. rst-class:: introduction

``OpenGLContext.edit`` is a toolkit for building editors on the engine: track
editors, level editors and scene inspectors. It provides tool modes that share
the pointer with the camera, a plan view and an orbit view, the world point
under the cursor, drag handles, and relief shading for maps. None of it is
specific to tracks, levels or scenes.

A game does not need any of it to play a world, and a shipped game imports
none of it.

.. figure:: images/demos/editing_demo.jpg
   :alt: A plan view looking straight down on green ground, five grey-roofed blocks casting short shadows, and five coloured markers dropped on the ground, one of them standing on the roof of the tallest block

   ``python tests/editing_demo.py``: markers placed on a world in the plan
   view. :ref:`editing-demo` describes the demo.

Tool modes
----------

In an editor the pointer does a different job in each tool: placing a point,
dragging one, measuring, painting. The camera also uses the pointer. The tool
in force sees each event first, and the camera gets whatever the tool does
not take. A tool that only handles the left button leaves the right button
free to orbit the camera.

.. code-block:: python

   from OpenGLContext.edit.tools import Pointer, ToolManager, ToolMode

   class PlacePoint(ToolMode):
       def on_press(self, pointer):
           if pointer.button or not pointer.on_surface:
               return False          # not ours: let the camera have it
           self.route.append(pointer.world)
           return True

   tools = ToolManager([PlacePoint(name='place'), DragPoint(name='drag')])

Each hook (``on_press``, ``on_drag``, ``on_release``, ``on_move``,
``on_key`` and ``on_wheel``) returns ``True`` if the tool used the event. The
base class returns ``False`` from all of them, so a subclass that overrides
one hook passes every other event on to the camera.

A tool that takes a press keeps the pointer until the release. A drag that
wanders off the thing it started on still ends in the same tool.
``ToolManager.select()`` returns ``False`` while a gesture is in progress, so
the tool cannot be switched part-way through one. Escape abandons a gesture
(``ToolMode.cancel``). When no gesture is in progress, Escape goes to the
camera.

``enter`` and ``leave`` are called when a tool comes into force and when it
goes out of force. Use them to show and remove a preview.

.. _tool-palette:

The tool palette
~~~~~~~~~~~~~~~~

:class:`~OpenGLContext.ui.toolpalette.ToolPalette` is a strip of buttons down
one side of the window, one button per tool. The button for the tool in force
is lit, and clicking a button selects that tool. The palette is an
:doc:`overlay UI <overlayui>` panel, not a HUD layer, because a HUD takes no
events. It is not modal, so a click outside it reaches the world underneath.

.. code-block:: python

   from OpenGLContext.ui.toolpalette import ToolPalette

   palette = ToolPalette(tools=tools, reserved=MENU_BAR_ROOM)
   context.overlays.push(palette)
   status.reserved = (MENU_BAR_ROOM, 0.0, 0.0, palette.room(metrics))

``reserved`` is the height at the top of the window already in use, such as a
menu bar, in reference pixels. The strip starts below it. ``edge`` is
``'left'`` (the default) or ``'right'``. ``room(metrics)`` returns the width
of the strip in reference pixels. Pass it to ``HUDLayer.reserved`` so the
:doc:`HUD <hud>` read-outs stay clear of the strip.

The buttons read the tool manager's current tool rather than keeping their
own copy. A tool chosen by a keyboard shortcut or by the application lights
the same button as a click. When the manager refuses a change because a
gesture is in progress, the lit button stays on the tool the pointer is still
using. Call ``rebuild()`` when the set of tools changes.

The strip takes every press inside it, including presses in the gaps between
buttons. A click that misses a button by two pixels does not put a point on
the map underneath.

The pointer a tool receives
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A ``Pointer`` holds the cursor position in window pixels (``x``, ``y``) and
the point in the world under it (``world``). ``world`` is ``None`` over the
sky. ``button`` is the mouse button. ``on_surface`` is ``True`` when
``world`` is set, and ``shifted``, ``controlled`` and ``alted`` report the
modifier keys.

The point under the cursor
--------------------------

The pick already gives the world point under a click. The selection pass
writes depth as well as an object id, so each mouse event carries the depth
of what it hit. Unprojecting that depth gives the point on the surface. This
is exact, costs nothing extra, and works on streamed terrain, because terrain
writes depth like any other geometry.

.. code-block:: python

   from OpenGLContext.edit.surface import pointer_from
   pointer = pointer_from(event)      # pointer.world is where they clicked

A drag cannot use that depth, because the depth under the cursor belongs to
the thing being dragged. A drag intersects the eye ray with a plane instead.
The usual plane is the level plane through the point where the drag began,
so the point moves across the ground without climbing over what it passes:

.. code-block:: python

   from OpenGLContext.edit.surface import horizon_plane, ray_from, ray_plane

   origin, direction = ray_from(event)
   moved_to = ray_plane(origin, direction, *horizon_plane(started_at[1]))

``ray_from`` builds the ray from the near and far clipping planes, not from
the camera position. It is correct under any projection, including an
orthographic map view, where rays are parallel and there is no eye point.

The pick gives a point, not a surface normal. To get the slope of the ground,
use ``surface_normal(height_fn, x, z)``, which takes the gradient of the
editor's height function.

.. _gizmo:

Handles: moving a point along one axis
--------------------------------------

Dragging against the ground plane suits a point on the ground. A point in the
air, such as a control point, a light or a camera, needs a direction to move
in. A gizmo supplies one. It draws three arms at the point, one per axis.
Grabbing an arm constrains the drag to that axis, so the point moves straight
up or straight east.

.. code-block:: python

   from OpenGLContext.edit.gizmo import TranslationGizmo

   gizmo = TranslationGizmo(size=1.5)
   group.children = list(group.children) + [gizmo.node]
   gizmo.attach(point)                    # the arms appear there

   def OnPress(self, event):
       if gizmo.press(event) is not None: # landed on an arm: a drag has begun
           return

   def OnDrag(self, event):
       moved = gizmo.drag(event)          # None when no arm is held
       if moved is not None:
           self.put_it(moved)             # write it wherever it belongs

The arms are ordinary scenegraph nodes, so the pick hit-tests them like any
other geometry. There is no second hit-test to keep in step with what is
drawn. ``press`` reads the axis from the node path the selection pass
returned. ``release`` ends the drag. ``cancel`` abandons it and puts the
point back where it was grabbed; Escape calls it.

A gizmo works in the coordinates of the group it is placed in. That group is
often scaled or rotated. The gizmo reads the group's transform from the same
node path, transforms its anchor and axis to root coordinates for the
calculation, and returns the result in the group's own units.

The calculation is ``axis_parameter(origin, direction, anchor, axis)``. It
returns the point on the arm's line closest to the eye ray, as a distance
along the arm. It returns ``None`` when the ray runs along the arm, since
every point on the arm is then equally close; the handle then stays still.
The press records how far along the arm the pointer took hold, and the rest
of the drag is measured from there, so the handle does not jump to the
cursor.

The arms have a fixed length in the group's units, so a gizmo far from the
camera is drawn small.

The control points of a NURBS surface
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A :doc:`NURBS <nurbs>` surface is one shape, so a pick on it returns the
surface, not a control point. ``ControlNet`` adds a marker on every control
point. A picked marker identifies a control point by index, and moving the
marker edits the geometry.

The net also draws the control cage: a polyline along every row and column
of the control grid (a single polyline for a curve). The cage shows which
points a control point lies between, and so how a pull on it will bend the
surface. The cage moves with the points. It is ``pickable=False``, so a line
lying over a marker does not take a click meant for the marker or for the
surface behind it (see :doc:`click-through picking <instancing>`).

.. code-block:: python

   from OpenGLContext.edit.controlnet import ControlNet

   net = ControlNet(shape.geometry)       # any node with a controlPoint field
   group.children = list(group.children) + [net.node]
   ...
   index = net.index_for(event.getObjectPaths())
   if index is not None:
       net.select(index)                  # the marker takes the selected colour
       gizmo.attach(net.point(index))
   ...
   net.move(index, gizmo.drag(event))     # the surface retessellates

``move`` assigns a new value to the ``controlPoint`` field rather than
writing into the existing array. The cached tessellation watches for the
field being set, so an in-place write would leave the old surface on screen.
VRML97 gives both ``NurbsSurface`` and ``NurbsCurve`` a ``controlPoint``
field, so a net works on either.

The markers share one geometry and one appearance, so the whole net is one
instanced draw (see :doc:`Instanced rendering <instancing>`), and the cage is
a second draw. The selected marker gets its own appearance while it is
selected. That draws it in the selected colour and takes it out of the
instanced batch.

.. figure:: images/demos/molehill_edit.jpg
   :alt: Four coloured NURBS surfaces meeting in a molehill, white spheres marking their control points and thin lines joining the points into a grid, and two control points far above the surfaces with long lines running down to their neighbours

   ``python tests/molehill_edit.py``: the :doc:`Molehill <tutorials/molehill>`
   surfaces with a draggable control net. Click a marker to select it and
   place the three-axis handle on it. Drag an arm and the surface
   retessellates as the point moves. The two markers high above the rest are
   the control points that raise the green and blue hills. Escape abandons a
   drag, or removes the handle.

.. _relief-shading:

Relief shading for plan views
-----------------------------

A map lit from straight overhead looks flat: every surface faces the light
equally, so ridges and valleys come out the same colour. ``shade_colors``
shades the ground by the direction it faces relative to a fixed low sun. This
is the cartographic hillshade. It shows the shape of the land without shadows
falling across the lines drawn on the map.

.. code-block:: python

   from OpenGLContext.edit.relief import shade_colors

   colors = shade_colors(colors, normals)     # then draw the mesh unlit

The sun is a map convention, not a scene light. It sits in the north west at
45° above the horizon, as on printed relief maps. Light from east of north
makes hills look like hollows.

The shading goes into the vertex colours and the mesh is drawn unlit. A plan
view needs no lights and no shadow maps, and the shading costs one dot
product per vertex.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Argument
     - Meaning
     - Default
   * - ``azimuth``
     - degrees clockwise from north
     - 315
   * - ``altitude``
     - degrees above the horizon
     - 45
   * - ``ambient``
     - light reaching ground that faces away from the sun, so no part of the
       map goes black
     - 0.35
   * - ``exaggeration``
     - factor by which slopes are steepened before shading
     - 4

Terrain a road can cross is gentle. A one-in-twenty slope is a hard climb for
a car but barely visible, so unexaggerated shading gives an almost flat
sheet. The exaggeration applies to the shading only: the ground is drawn at
its true height, and contours show that height.

``hillshade(normals, ...)`` returns the shading alone, from 0 to 1, for a
caller that colours the ground another way. ``steepen(normals, k)`` applies
only the exaggeration.

Snapping a point to a contour
-----------------------------

A road held to a constant grade around a hillside follows a contour line.
``snap_to_height`` moves a point onto a contour by stepping along the
gradient, straight up or down the hill:

.. code-block:: python

   from OpenGLContext.edit.surface import height_gradient, snap_to_height

   x, z = snap_to_height(height_fn, x, z, height=None, interval=25.0, reach=250.0)

``height`` is the elevation to land on. With ``None``, the target is the
nearest multiple of ``interval``, which is the contour line on the map.
``reach`` is the furthest the point may move, in metres; a snap that would go
further stops at that distance. On flat ground there is no nearest contour,
and the point stays where it is.

On evenly sloping ground the first step is exact. Curved ground takes a few
more steps. ``height_gradient`` returns the east and north slopes on their
own, for a caller that needs the slope rather than the snap.

.. _plan-view:

The plan view
-------------

:class:`~OpenGLContext.edit.mapview.MapView` is a camera that looks straight
down with an orthographic projection. A metre is the same number of pixels
everywhere on screen, so a click means the same thing at either end of a
straight.

.. code-block:: python

   from OpenGLContext.edit.mapview import MapView, MapViewPlatform

   view = MapView(centre=(0.0, 0.0), span=1200.0)   # 1200 m down the window
   context.platform = MapViewPlatform(view)

``span`` is the number of metres shown down the window's height. A wider
window shows more of the world rather than stretching it. North (``-z``) is
up the screen and east (``+x``) is to the right.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Returns or does
   * - ``world_from_screen(x, y, viewport)``
     - the world ``(x, z)`` under a window pixel
   * - ``screen_from_world(point, viewport)``
     - the window pixel for a world point, for drawing a marker
   * - ``metres_per_pixel(viewport)``
     - the current scale
   * - ``pan(dx, dy, viewport)``
     - moves the map by a pointer movement, so the world follows the pointer
   * - ``zoom(factor, at=..., viewport=...)``
     - scales the view, keeping the world point under ``at`` still
   * - ``frame(minimum, maximum, viewport)``
     - fits a region inside the window

``PanTool`` makes moving the map a tool of its own, so the drawing tool does
not have to decide whether a drag is a pan:

.. code-block:: python

   from OpenGLContext.edit.maptools import PanTool

   tools = ToolManager([DrawTool(...), PanTool(view, context.getViewPort,
                                               on_change=map_moved)])

The pan tool measures each drag step from the pointer's previous position,
not from where the drag started. The map moves under the pointer, so a fixed
origin would make it accelerate away.

``MapViewPlatform`` reads the ``MapView`` rather than copying
it. Panning or zooming the view moves the camera, and there is only one
record of where the editor is looking.

The orbit view
--------------

A plan view is good for drawing and poor for judging how a landscape looks.
:class:`~OpenGLContext.edit.orbitview.OrbitView` is a camera that looks at a
point on the ground from a heading, a pitch and a distance:

.. code-block:: python

   from OpenGLContext.edit.orbitview import OrbitView, OrbitViewPlatform

   view = OrbitView(centre=(0.0, 0.0), ground=42.0, distance=800.0)
   context.platform = OrbitViewPlatform(view, context.getViewPort())
   ...
   view.orbit(dx * 0.4, dy * 0.4)     # a drag: turn and rise, in degrees
   view.dolly(1.0 / 1.25)             # a wheel notch: in or out

``heading`` is in degrees clockwise from north. At zero the camera is south
of the target, looking north, the way a map is read. ``pitch`` is in degrees
above the horizontal. The default of 35° is a three-quarter view, high enough
to read the plan and low enough to show the relief. ``orbit`` turns the
camera around the target without moving the target. The pitch is limited
short of straight overhead and short of the horizon, where the camera has no
unique up vector or sees the ground edge-on.

``frame(minimum, maximum, viewport)`` moves the camera back far enough to see
a whole region, and ``look_at`` moves the target. Like ``MapViewPlatform``,
``OrbitViewPlatform`` reads the view rather than copying it. Setting a
*position* on the platform computes the heading, pitch and distance that put
the camera there, so a bookmark or a saved viewpoint moves this camera too.

An editor can hold both views and swap its ``platform`` between them. It can
also show both at once: a :class:`~OpenGLContext.multiview.views.ViewLayout`
gives each camera its own part of the window, and a click picks through the
camera of the view it lands in. See :doc:`Several views on one window
<multiview>`.

.. _quad-view-pointer:

Top, front and side views
-------------------------

The orthographic top, front and side views, the four-view window, and the
pointer gestures that move each view's camera are part of
``OpenGLContext.multiview``: ``OrthoView``, ``ViewSet``, ``QuadView`` and
``ViewGestures``. See :ref:`Top, front and side <quad-view>` on the
:doc:`multiview` page.

.. _editing-demo:

Example: the editing demo
-------------------------

``python tests/editing_demo.py`` opens a world in the plan view. The demo
places five markers at the point under the pointer, then drags one of them
66 m across the ground, using tool modes that receive the pointer before the
camera. The demo scripts its own clicks and drag through the pick, so the
screenshot at the top of this page is reproducible.

Keys in the demo:

- ``o`` switches to the orbit view, and ``m`` back to the plan view.
- ``1``, ``2`` and ``3`` choose the drop, move and pan tools.
- ``u`` undoes the last action of the tool in force.

Each scripted click is aimed at a world point, converted to a pixel with
``screen_from_world``, and resolved by the pick. The two lines the demo
prints for a click are a round trip:

.. code-block:: python

   click  pixel (674, 510) <- world (22.0, -30.0)
   drop   marker 2 at world (21.88, 20.00, -30.00)

That click is aimed at the middle of a 20 m block, so the point comes back
20 m up and the marker stands on the roof.

An application writes the tool, and routes the pointer to the tool before the
camera:

.. code-block:: python

   from OpenGLContext.edit.surface import pointer_from
   from OpenGLContext.edit.tools import ToolManager, ToolMode

   class DropMarker(ToolMode):
       """Put something on the world where the pointer is."""

       def on_press(self, pointer):
           if pointer.button or not pointer.on_surface:
               return False          # not ours: the camera can have it
           print('drop at %.2f, %.2f, %.2f' % tuple(pointer.world))
           return True

   class Editor(BaseContext):
       def OnInit(self):
           self.tools = ToolManager([DropMarker(name='drop')])
           ...

       def ProcessEvent(self, event):
           """The tool in force is asked before the camera is."""
           if getattr(event, 'type', None) == 'mousebutton' and event.state:
               if self.tools.press(pointer_from(event)):
                   return None       # taken, so it never reaches the camera
           return super(Editor, self).ProcessEvent(event)

To take an event, return without calling the superclass. The camera's
movement sampler reads events in ``ViewPlatformMixin.ProcessEvent``, so an
event that does not reach it does not move the camera. Events the tool does
not take, such as the right button, the wheel and keys it does not handle,
continue to the existing handlers.

Limits
------

- Rotation and scale handles - :ref:`the gizmo <gizmo>` only translates.
  Rotation rings and scale boxes would each be a pickable node per handle
  with a closed-form constraint on the drag.

- Gizmo size - the arms are a fixed length in world units, so a gizmo far
  from the camera is drawn small. Scaling the arms by the distance to the eye
  each frame would keep them a constant size on screen.

- Picking hidden points - the pick reads the depth buffer, so it only finds
  what is drawn. A point hidden behind a hill cannot be picked without moving
  the camera. A CPU ray cast against the terrain would find it; see
  ``plans/RAYCAST-PICKING.md``.
