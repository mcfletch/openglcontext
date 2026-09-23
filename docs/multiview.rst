Several views on one window
===========================

.. rst-class:: introduction

A context can draw one scene through several cameras at once, each into its
own rectangle of the window: a map beside a three-quarter view, or the top,
front and side orthographic views of an editor around a perspective one. Every
view shows the same scene with the same materials, lights and shadow maps; the
camera, the projection and the rectangle are what differ. The layout also
routes the pointer, so a click in a view picks through that view's camera.

Laying out views
----------------

A :class:`~OpenGLContext.multiview.views.View` is a camera and a style. A
:class:`~OpenGLContext.multiview.views.ViewLayout` is an ordered set of views and the
rule that places them. Assign one to the context and every frame draws it:

.. code-block:: python

   from OpenGLContext.edit.mapview import MapView, MapViewPlatform
   from OpenGLContext.multiview.views import View, ViewLayout, ViewStyle

   class Editor(BaseContext):
       def OnInit(self):
           plan = MapView(centre=(0.0, 0.0), span=400.0)
           self.viewLayout = ViewLayout.split(
               View(MapViewPlatform(plan), name='plan',
                    style=ViewStyle(background=(0.3, 0.3, 0.3))),
               View(name='angled'),
           )

A view's camera is anything with the view platform's matrix interface:
:class:`~OpenGLContext.move.viewplatform.ViewPlatform`,
:class:`~OpenGLContext.edit.mapview.MapViewPlatform`,
:class:`~OpenGLContext.multiview.cameras.OrthoViewPlatform` or
:class:`~OpenGLContext.edit.orbitview.OrbitViewPlatform`. A view with no camera
draws through the context's own view platform, whatever ``getViewPlatform()``
answers that frame, so the navigation, the bound ``Viewpoint`` and any
``self.platform = ...`` replacement keep driving it. A context that never
assigns a layout draws one such view filling the window.

The named arrangements are:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Built with
     - Arrangement
     - Places
   * - ``ViewLayout.single(camera=None)``
     - ``'single'``
     - one view filling the window
   * - ``ViewLayout.split(first, second, fraction=0.5)``
     - ``'split'``
     - two views side by side; ``fraction`` is the first view's share of the width
   * - ``ViewLayout.split(first, second, fraction, vertical=True)``
     - ``'stack'``
     - two views, the first above the second
   * - ``ViewLayout.quad(top_left, top_right, bottom_left, bottom_right)``
     - ``'quad'``
     - four views around a centre

``layout.split_at`` is where the named arrangements divide the window, as
fractions of its width and of its height measured from the top: the line of a
split or a stack, or the centre of a quad. It is what a splitter drag moves,
and each fraction is held between 0 and 1. ``layout.maximise(view)`` gives one
view the whole window and ``layout.maximise(view)`` again gives it back; with
no argument it takes the active view.

Any other arrangement is a function from the window's size to one rectangle
per view, in the order of the views:

.. code-block:: python

   def picture_in_picture(width, height):
       return [(0, 0, width, height), (width - 200, height - 150, 200, 150)]

   context.viewLayout = ViewLayout([main, inset], arrangement=picture_in_picture)

Rectangles are ``(x, y, width, height)`` in window pixels, counted from the
bottom left as ``glViewport`` counts them. Views are drawn in their order, so a
view that overlaps another is drawn over it.

A layout holds at most ``OpenGLContext.multiview.views.MAX_VIEWS`` views, which is 16.

An editor's four views -- top, front and side orthographic views around a
perspective one -- are ``OpenGLContext.multiview.quad.QuadView``, which builds
the layout, frames a model in every view and moves each view's camera with the
pointer; see :ref:`Top, front and side <quad-view>`. ``tests/multiview_quad.py``
loads any glTF model into it. An application laying out its own views takes the
gestures alone, as ``OpenGLContext.multiview.gestures.ViewGestures``, and names
which views they drive.

How a view draws
----------------

``ViewStyle(background=True)`` draws the scene's bound ``Background`` behind the
view; ``ViewStyle(background=(r, g, b))`` or an RGBA colour clears the view to
that instead, as an orthographic editor view usually wants in place of a sky.
``ViewStyle(wireframe=True)`` draws the view's geometry as lines.

A perspective camera is told the size of its view's rectangle whenever that
changes, so its aspect ratio is the rectangle's rather than the window's. A
:class:`~OpenGLContext.edit.mapview.MapViewPlatform` is told the same, and its
scale is then metres per pixel of its own view.

A node that draws differently in each view reads ``mode.view``, the
:class:`~OpenGLContext.multiview.views.View` being drawn, during its render.

The pointer and the keyboard
----------------------------

The context names the view each event belongs to and records it as
``event.view``:

- a pointer event belongs to the view under the pointer;
- a press makes its view the *active* one, and every pointer event after it
  belongs to that view until the last held button is released, so a drag that
  leaves its view keeps talking to it;
- a wheel notch belongs to the view under the pointer and holds nothing;
- a key belongs to the active view.

A pick is resolved through the camera of the event's view, so
``event.unproject()`` returns the world point under the pointer in that view,
and ``event.modelViewMatrix``, ``event.projectionMatrix`` and ``event.viewport``
are that view's. An asynchronous pick that resolves a frame later uses the
camera as it was in the frame the click was drawn in. ``view.local(x, y)``
turns a window pixel into the view's own pixels, the coordinates
:meth:`~OpenGLContext.edit.mapview.MapView.world_from_screen` takes.

``layout.active`` is the active view and ``layout.activate(view)`` changes it.
``layout.view_at(x, y)`` names the view at a window pixel and
``layout.route(event)`` is the routing the context applies.

What a frame shares
-------------------

The scene is walked once a frame. Each view then culls that walk against its
own frustum, sorts what it kept, and draws it through its own camera. What
depends only on the scene is done once for all of them:

- Level of detail is one choice per frame, since choosing a level replaces part
  of the scene. Each LOD node draws the finest level any view asks for. An
  orthographic view judges coverage from the height of the world it shows
  rather than from a distance, so zooming a map out coarsens what it shows and
  moving its camera does not.
- Shadow maps are rendered once and read by every view. Spot and point maps
  depend only on their light. A directional light's cascades are fitted to the
  active view; every other view reads the same cascades, choosing for each
  fragment the finest cascade that holds it. Ground a non-active view shows
  outside every cascade is drawn unshadowed.
- A spot or point light keeps its shadow while any view can see its reach.
- Bloom blurs and composites each view inside its own rectangle, so a bright
  object at the edge of one view does not glow into the next.
- Transparent shapes are sorted back to front for each view's own camera.

Content that is kept resident around the viewer -- streamed 3D Tiles, a
vegetation field -- has to serve every view. ``layout.cameras(default=
context.getViewPlatform())`` lists each camera once for an application to hand
to them.

How the views are drawn
-----------------------

There are three ways to draw several views, and which a context uses depends
on its driver. ``OpenGLContext.multiview.strategy.MultiviewCapabilities`` reads
the GL version, the extension list and ``GL_MAX_VIEWPORTS`` once per GL
context and decides:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Strategy
     - Needs
     - How a draw reaches its views
   * - ``vertex``
     - GL 4.1, and ``GL_ARB_shader_viewport_layer_array`` or
       ``GL_AMD_vertex_shader_viewport_index``
     - one instanced draw, the vertex shader writing ``gl_ViewportIndex``
   * - ``geometry``
     - viewport arrays (GL 4.1, or ``GL_ARB_viewport_array``) and
       instanced geometry shaders (GL 4.0, or ``GL_ARB_gpu_shader5``)
     - one draw, a geometry shader emitting each primitive to its views
   * - ``sequential``
     - GL 3.3
     - the scene drawn once per view, the viewport and scissor set between

``sequential`` runs on every driver the engine supports, on both profiles, and
costs one submission of the scene per view. The other two submit the opaque
scene once, whatever the number of views. A GL 4.1 driver without the
vertex-shader extension, such as Apple silicon's, draws with ``geometry``. A
driver's answer is logged at start-up.

``scripts/multiview_bench.py`` draws a scene through one view and through the
four-view quad under each strategy this driver runs, and reports the median
frame time and the draw calls of each:

.. code-block:: console

   $ scripts/multiview_bench.py --model lantern.glb
   $ scripts/multiview_bench.py --boxes 400 --frames 60

At 1280x960 on a Radeon 8060S (Mesa radeonsi), four views of one glTF model
cost 1.40x a single view under ``vertex``, 1.43x under ``geometry`` and 1.58x
under ``sequential``. Four views of 400 separately drawn shapes -- the
draw-bound case, 400 draws a view -- cost 1.21x, 1.24x and 2.41x; with those
shapes batched into one instanced draw, 1.34x, 1.40x and 2.08x. A shared
strategy issues one draw for four views where ``sequential`` issues four, so
what it adds over a single view is the rasterising of three more views rather
than three more submissions of the scene.

``ContextDefinition.multiview`` (env: ``OPENGLCONTEXT_MULTIVIEW``) asks for one
by name -- ``auto``, ``vertex``, ``geometry`` or ``sequential`` -- so each can be
run and compared on one machine. ``auto`` takes the fastest that can run. A
request that cannot be honoured is logged and the best strategy that can run is
used instead.

A driver can offer a strategy and then fail to compile its programs. The
failure is logged, the frame in which it happens draws each view in turn, and
from the next frame the context uses the next strategy in the table, never
trying the failed one again. ``sequential`` compiles nothing of its own, so a
context always has it to fall back on. A layout of more views than the
driver's ``GL_MAX_VIEWPORTS`` is drawn with ``sequential`` for as long as it
has that many; GL 4.1 and ``GL_ARB_viewport_array`` both provide at least 16.

.. _quad-view:

Top, front and side
-------------------

``OrthoView`` is a plan view that can look along any axis: ``'top'``,
``'bottom'``, ``'front'``, ``'back'``, ``'left'`` or ``'right'``. The camera
stands on the side the name gives -- ``'front'`` stands at +z looking down -z,
the view a VRML or glTF scene opens on -- and ``'top'`` puts -z up the screen,
as a map puts north. The projection is orthographic, and ``centre`` is a point
in the world rather than on the ground:

.. code-block:: python

   from OpenGLContext.multiview.cameras import OrthoView, OrthoViewPlatform

   front = OrthoView('front', centre=(0.0, 1.0, 0.0), span=4.0)
   view = View(OrthoViewPlatform(front), name='front')
   ...
   front.pan(dx, dy, view.size)                     # a drag, in view pixels
   front.zoom(0.8, at=view.local(x, y), viewport=view.size)
   point = front.world_from_screen(*view.local(x, y), view.size)

``span`` is how many units fit down the view and ``depth`` how far along the
axis it reaches, half in front of the centre and half behind. The pointer
conversions work in the view's plane through the centre, so a point dragged in
the front view moves in x and y and keeps its z. ``frame(minimum, maximum,
viewport)`` fits a box, and ``MapView`` is the ``'top'`` view with its centre
given as a map's ``(x, z)``.

``QuadView`` is the window of four an editor opens on: three orthographic views
-- by default the plan, the front and the view from the left -- around an
``OrbitView`` in perspective. It builds the
:class:`~OpenGLContext.multiview.views.ViewLayout`, frames a box in all four views, and
turns the pointer into camera moves: a drag pans an orthographic view, a left
drag orbits the perspective view and any other button pans it, and the wheel
zooms the view under the pointer.

.. code-block:: python

   from OpenGLContext.multiview.quad import QuadView

   class Editor(BaseContext):
       def OnInit(self):
           self.quad = QuadView()
           self.viewLayout = self.quad.layout
           self.quad.layout.arrange(*self.getViewPort())
           self.quad.frame(minimum, maximum)

       def ProcessEvent(self, event):
           if self.quad.handle(event):
               self.triggerRedraw(1)
               return None
           return super(Editor, self).ProcessEvent(event)

``QuadView(directions=('front', 'right', 'bottom'))`` chooses other
orthographic views, and ``background`` the flat colour they clear to; the
perspective view draws the scene's own ``Background``. ``press``, ``drag``,
``release`` and ``wheel`` are the same gestures for an application that reads
its pointer another way. ``OrbitView`` takes ``nearest`` and ``furthest`` for
how close and how far it may be dollied, and ``frame_box`` fits a whole object
rather than a region of ground; ``QuadView.frame`` sets all three from the box.

``python tests/multiview_quad.py model.glb`` puts any glTF model in the four
views; :doc:`tutorials/multiview_quad` walks through it.

Arrangements of one set of views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A window that offers more than one way to look at a scene keeps one set of
cameras and changes which of them are on screen. ``ViewSet`` holds the views,
a layout per arrangement, the gestures and the framing:

.. code-block:: python

   from OpenGLContext.multiview import ViewSet

   views = ViewSet([plan, front, left, angled],
                   arrangements={'map': ('plan',),
                                 'angled': ('angled',),
                                 'split': ('plan', 'angled'),
                                 'quad': ('plan', 'front', 'left', 'angled')},
                   driven=('front', 'left', 'angled'))
   context.viewLayout = views.show('quad')

An arrangement names the views it shows, in order, and is placed by how many
there are: one fills the window, two go side by side, four around a centre.
With no ``arrangements`` given, each view is offered on its own under its own
name, the first two as ``'split'`` and the first four as ``'quad'``.
``show(name)`` changes which is up and answers the layout to draw -- assign it
to ``viewLayout``, since a layout is what the context draws.

The cameras are shared between the arrangements, so a switch shows what was
already being looked at. ``arrange(width, height)`` places the views and tells
each camera the size of its own rectangle; ``size(view)`` answers that size, or
the window's for a view this arrangement hides, so a view can be framed before
it is shown. ``frame(minimum, maximum)`` fits a box in every view, each camera
as its kind is fitted: an orthographic or perspective camera takes the box and
a plan camera the ground it stands on. ``maximise(view)`` gives one view the
whole window and the same call gives it back.

``driven`` names the views whose cameras the pointer moves. A window that
drives one itself -- an editor whose plan view is where its tools draw -- leaves
that view out, and ``handle(event)`` never takes an event in it.
``view_for(event)`` answers which view an event belongs to, for deciding what
else should have it. glisteel-editor's four arrangements are built this way.

What the pointer does in a view
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Each view carries its own navigation: the gestures its camera can be moved by,
and the bindings that say which button raises each. ``view.navigation`` is a
:class:`~OpenGLContext.multiview.navigation.ViewNavigation`, made for the
camera the first time something asks for it.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Command
     - Does
     - Bound to, by default
   * - ``pan``
     - carries the world with the pointer; a camera that turns carries what it
       is looking at
     - the right and middle buttons in a view with a scale; the middle button
       in one that turns
   * - ``rotate``
     - swings a camera that turns about what it is looking at
     - the right button, where the camera turns
   * - ``zoomin`` / ``zoomout``
     - one notch towards the scene or away from it, about the pointer in a
       view with a scale
     - the wheel
   * - ``zoomdrag``
     - the same zoom, driven by a drag; dragging up comes closer
     - nothing, until a view asks for it

**The primary click is left unbound in every view.** It is what an editor's
tools and its selection are reached with, and a camera that took it would take
it from whatever the pointer is being used for; a window with no tools binds it
in a line.

The bindings are :class:`~OpenGLContext.move.modes.KeyBinding` nodes, the same
ones the movement modes carry, and a mouse button is named as the event system
names it. So they are rebound like any other command, saved in the same
bindings file, and changed in a line:

.. code-block:: python

   from OpenGLContext.multiview.navigation import PAN, ROTATE, ZOOM_DRAG

   navigation = view.navigation
   navigation.rebind(ROTATE, ['<mouse-0>'])        # left-drag turns this view
   navigation.rebind(PAN, ['<mouse-2>'])           # ...and the right one pans it
   navigation.rebind(ZOOM_DRAG, ['<mouse-1>'])     # middle-drag zooms
   navigation.rebind(PAN, [])                      # this view does not pan

``commands()`` answers what this view's camera can be moved by, so a control
offering the gestures lists those rather than guessing; ``rebind`` refuses a
command the camera has not got. ``binding_table()`` is what a settings screen
reads. Where two bindings claim one button the first declared has it, which is
the conflict a rebinding screen raises its "steal it?" question about.

A whole set of bindings is a *mode*
(:class:`~OpenGLContext.multiview.navigation.ViewNavigationMode`):
``plan_mode()`` for a view with a scale and ``examine_mode()`` for a camera
that turns are what a view starts with, and ``ViewNavigation(view, mode=...)``
gives it another.

The furniture of a window of views
----------------------------------

A window showing four views needs to say which view is which, which way each
is looking, and how to work it. ``OpenGLContext.ui.viewchrome.ViewChrome`` is
that, drawn inside each view and taking the clicks:

.. code-block:: python

   from OpenGLContext.ui.viewchrome import ViewChrome

   self.chrome = ViewChrome(layout=views.layout, stack=self.overlays,
                            on_arrange=self.placeViews)
   self.overlays.push(self.chrome)

It puts in each view its **name**, an **axis triad** that turns with the
camera, an **expand** button that gives the view the whole window and gives it
back, and a **navigation** button that offers the gestures this view's camera
can be moved by and switches each on or off. Between the views it puts a
**splitter** on each line the arrangement divides the window along -- and, in
a quad, a handle where the two cross that moves both. ``on_arrange`` is called
when a control changed what is on screen, for the window to place its views
again and draw.

It is a panel at the bottom of the overlay stack, like the tool palette, and
it is not modal: a press that lands on none of its controls reaches the scene.
It draws nothing of its own behind the furniture, so nothing is washed over.

Every part is optional. ``labels``, ``axes``, ``expand``, ``navigation`` and
``splitters`` switch a kind off for the window, and ``only`` gives one view a
set of its own -- an editor whose plan view belongs to its drawing tools gives
that view the expand button and nothing else:

.. code-block:: python

   ViewChrome(layout=layout, axes=False,
              only={'map': ('expand',)})

``reserved`` is room something else has taken at each edge of the window --
top, right, bottom, left, in reference pixels, as a
:class:`~OpenGLContext.ui.hudwidgets.HUDLayer` is told it -- so a name drawn
under a menu bar or behind a tool palette is not what a window with either
gets.

``axis_directions(view)`` is the arithmetic on its own: which way each world
axis runs on screen in that view, as unit vectors in the view's own pixels.

Gestures on their own
~~~~~~~~~~~~~~~~~~~~~

An application with a layout of its own, and no use for the rest of a view
set, takes the gestures alone. ``ViewGestures`` moves the camera of whichever
view an event lands in, and ``views`` names the ones it drives, so a view the
application moves itself is left alone:

.. code-block:: python

   from OpenGLContext.multiview.gestures import ViewGestures

   gestures = ViewGestures(layout, views=[elevation, angled])
   ...
   def ProcessEvent(self, event):
       if gestures.handle(event):          # never takes an event in `plan`
           self.triggerRedraw(1)
           return None
       return super(Editor, self).ProcessEvent(event)

Every event goes to the navigation of the view it lands in, so what a button
does is that view's own. ``layout`` and ``views`` can both be assigned, so a
window that rearranges its views hands over the new layout.

One submission for every view
-----------------------------

The shared submission is made as the active view would make it alone: the same
modelviews, lights and shadow matrices, in that camera's eye space. What sends
each triangle on to the other views is a table of views, one record each, that
the programs read -- the matrix from the active camera's eye space to the
view's clip space, where the view's camera is, and how it reads the shadow
cascades. With ``geometry`` a geometry stage, generated from the lit vertex
shader, emits each triangle once per view in the draw's mask; with ``vertex``
the draw is instanced once per view and the vertex stage routes each copy. The
lit programs are compiled a second time for this the first time a layout of
several views is drawn, and the single-view programs are unchanged.

A shape takes part when its geometry says it draws with the pass's lit programs
alone. ``Box``, ``Sphere``, ``Cone``, ``Cylinder``, ``IndexedFaceSet`` and a glTF
mesh of triangles do. Everything else is drawn once per view, as ``sequential``
draws it: transparent and glass shapes, which are sorted and refracted per
view; everything in a wireframe view, since polygon mode holds for every
viewport at once; an appearance with a GLSL program of its own; an octahedral
impostor;
point and line sets; instanced sets that cull their own placements; and nodes
that draw with programs of their own, such as vegetation, terrain, particles
and text.

A geometry node joins the shared submission by declaring
``multiviewShared = True`` and issuing its draw through
``OpenGLContext.multiview.strategy.draw_arrays`` or ``draw_elements``, which
instance it once per view while a ``vertex`` submission is being made.
``OpenGLContext.scenegraph.geometryarrays.render_geometry`` does both for a node
drawn from ``GeometryArrays``. A node that measures its detail by distance from
the camera reads ``mode.viewerEyes`` during a shared draw: the cameras the draw
serves, in the eye space it is drawn in; see
``OpenGLContext.scenegraph.tessellationlod.lod_level``.
