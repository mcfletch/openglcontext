OpenGLContext Flat Rendering
============================

.. rst-class:: introduction

OpenGLContext renders a scenegraph with a "flat" pass. Instead of traversing
the scenegraph every frame, the pass keeps a flat list of paths to the
renderable nodes. It computes each path's combined transformation matrix on
the CPU, not with the GL matrix stack, and loads that matrix before it draws
the geometry. This page describes how the pass keeps that list, how it culls
and sorts a frame, and how a redraw reaches it.

.. rst-class:: technical

The flat pass has two implementations: a fixed-function path for the
compatibility profile and a shader path for the core profile. For the shader
path's frame steps, shader programs and VRML97 lighting shaders, see
:doc:`Core-Profile Rendering <renderpasses>`. For the physically based
renderer built on it, see :doc:`Physically Based Rendering <pbr>`.

Observables and Tree Updates
----------------------------

PyVRML97 can report changes to node fields. OpenGLContext uses this to watch
every field of every node in the scenegraph. For each path to each node it
records a ``NodePath`` object, which computes and caches the combined
transform matrices along that path.

With this list of matrices and renderable nodes, the pass renders the
scenegraph with a few simple loops instead of a recursive traversal.

The flat pass also does colour-select rendering. It draws a selection pass
whose result is read back to find the object under the mouse for incoming
mouse events. It does not use the legacy GL select render mode.

Gathering and Culling a Frame
-----------------------------

``renderSet()`` turns the flat set of paths into the ordered list a frame
draws. It first reads each path's world matrix, because the path's cache holds
the current value and the scenegraph may have changed it since the last frame.
The rest of the work runs on the whole scene at once:

#. The eight corner points of every bounding volume are stacked into one
   ``(N,8,4)`` array.
#. One matrix product carries them all into world space.
#. One more product tests them against the frustum's clipping planes.

A shape is rejected when all eight of its corners are behind one plane. This
is the same result as the per-shape test, reached with two array operations
instead of one Python call per object.

Culling happens before sort keys are computed, so the rest of the frame costs
in proportion to what is on screen. A sort key reads the appearance and its
textures, and for a transparent shape it needs a projected depth. In a typical
level most shapes are off screen, and the pass never computes their keys.

Two kinds of bounding volume have no corners:

- An *unbounded* volume has an unknown extent. It is never culled, so the
  shape is always drawn.
- A volume with *no* extent bounds nothing. It draws nothing whether it is
  kept or not. An :ref:`InstancedShape <instancedshape>` with no placements
  has this kind of volume.

.. rst-class:: technical

The pass reads bounding volumes from their nodes every frame and does not
store them. A volume can change without the shape changing: an instanced
shape's volume covers all of its placements, so it changes whenever they do.
Corners kept from an earlier frame would cull this frame's copies against last
frame's positions. The node's own volume cache holds the current value and
tracks the dependencies that invalidate it.

Normals Under Scaling
---------------------

.. rst-class:: technical

Both profiles return a transformed normal to unit length, so a ``Transform``
with a ``scale`` lights the shapes under it the same way in either profile.
The shader path normalizes in the vertex shader. The fixed-function path
enables ``GL_NORMALIZE`` (in ``FlatPass.legacyNormalRescale``), because the
fixed function transforms a normal by the inverse transpose of the modelview,
and a scale of ``s`` divides the normal's length by ``s``. Without it, a
half-size shape is lit twice as brightly and a double-size one half as
brightly. A caller that renders geometry on its own through
``renderGeometry`` gets the same state.

How a Redraw Reaches the Pass
-----------------------------

This is the sequence from the GUI library's paint event (``OnPaint`` or its
equivalent) to the flat pass drawing the frame.

#. The Context's event handler for the paint event (for example ``wxOnPaint``
   in the wxPython Context subclasses) calls ``self.triggerRedraw(1)`` to force
   a redraw.

#. ``Context.triggerRedraw`` clears the ``alreadyDrawn`` flag, which marks the
   context as needing a redraw. If the context can draw now, it calls
   ``OnDraw`` directly. Otherwise it sets the ``redrawRequest`` event, and the
   main loop calls ``OnDraw`` at the next opportunity. Whether it can draw now
   depends on the threading state and on whether a frame is already being
   drawn.

#. ``Context.OnDraw``:

   #. runs the event cascade (the ``DoEventCascade`` customization point,
      which does nothing by default) while holding the scenegraph lock. A
      call that was not forced draws only if the cascade changed something
      or a time given to ``Context.redrawAt(when)`` has passed; ``when`` is
      on the session clock (``OpenGLContext.events.systemtime``), and is how
      something that changes with time alone, such as a tooltip waiting for
      its pause, gets its frame in a window that draws on demand

   #. makes this Context the current context: it acquires the OpenGLContext
      ``contextLock`` and makes the GUI library's set-current call

   #. clears the ``redrawRequest`` event

   #. calls the Context's ``renderPasses`` attribute, which returns whether
      the frame changed visibly (the flat pass always returns ``True``); a
      visible change is counted in the frame counter

   #. finally, releases the current context

#. ``defaultRenderPasses.__call__``:

   #. picks the ``FlatPass`` class for the Context's profile and renderer (the
      compatibility pass, the core pass or the PBR pass) and caches the pass.
      It builds a new one only when the scenegraph itself is replaced.

   #. for the core profile, binds the scene's active Viewpoint into the view
      platform (the compatibility path does this inside its own traversal)

   #. calls the ``FlatPass`` with the Context and returns its result

#. ``FlatPass.Render``:

   #. sorts the paths it observes on the scenegraph into background, opaque,
      transparent and, when there are pick events, selection work

   #. draws each group in turn, then presents the frame through
      ``Context.presentFrame``, which takes any pending screenshot and swaps
      the buffers
