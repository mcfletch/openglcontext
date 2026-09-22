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

A :class:`~OpenGLContext.views.View` is a camera and a style. A
:class:`~OpenGLContext.views.ViewLayout` is an ordered set of views and the
rule that places them. Assign one to the context and every frame draws it:

.. code-block:: python

   from OpenGLContext.edit.mapview import MapView, MapViewPlatform
   from OpenGLContext.views import View, ViewLayout, ViewStyle

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
:class:`~OpenGLContext.edit.mapview.MapViewPlatform` or
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

A layout holds at most ``OpenGLContext.views.MAX_VIEWS`` views, which is 16.

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
:class:`~OpenGLContext.views.View` being drawn, during its render.

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
on its driver. ``OpenGLContext.passes.multiview.MultiviewCapabilities`` reads
the GL version, the extension list and ``GL_MAX_VIEWPORTS`` once per GL
context and decides:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Strategy
     - Needs
     - How a draw reaches its views
   * - ``vertex``
     - ``GL_ARB_shader_viewport_layer_array`` or
       ``GL_AMD_vertex_shader_viewport_index``, and viewport arrays
     - one instanced draw, the vertex shader writing ``gl_ViewportIndex``
   * - ``geometry``
     - viewport arrays: GL 4.1, or ``GL_ARB_viewport_array``
     - one draw, a geometry shader emitting each primitive to its views
   * - ``sequential``
     - GL 3.3
     - the scene drawn once per view, the viewport and scissor set between

``sequential`` runs on every driver the engine supports, on both profiles, and
is the one this release draws with: its cost is one submission of the scene
per view. The other two submit the scene once whatever the number of views;
they are recognised on the drivers that offer them, and a driver's answer is
logged at start-up. A GL 4.1 driver without the vertex-shader extension, such
as Apple silicon's, offers ``geometry`` and ``sequential``.

``ContextDefinition.multiview`` (env: ``OPENGLCONTEXT_MULTIVIEW``) asks for one
by name -- ``auto``, ``vertex``, ``geometry`` or ``sequential`` -- so each can be
run and compared on one machine. ``auto`` takes the fastest that can run. A
request that cannot be honoured is logged and the best strategy that can run is
used instead.
