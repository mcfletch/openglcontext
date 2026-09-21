OpenGLContext Flat Rendering
============================

.. rst-class:: introduction

This document describes OpenGLContext's "flat" rendering process.  This
process uses client-side (not GL-side) calculations to produce composed
transformation matrices which are directly loaded before rendering geometry.
 The rendering process is considerably less involved than the original design,
in which a set of separate "RenderPass" objects each traversed the whole
scenegraph; that system has since been removed.

.. rst-class:: technical

The flat pass carries two implementations: a legacy fixed-function path (the
compatibility profile) and a shader path (the core profile). For how the
shader path works -- its passes, shader programs and the VRML97 lighting
shaders -- read :doc:`Core-Profile Rendering <renderpasses>`; for the
physically based renderer built on it, read :doc:`Physically Based Rendering
<pbr>`.

.. rst-class:: technical

Both paths return a transformed normal to unit length, so a ``Transform`` with
a ``scale`` lights what is under it the same in either profile. The shader
path normalizes in the vertex shader; the fixed-function path asks the GL for
it (``GL_NORMALIZE``, in ``FlatPass.legacyNormalRescale``), because the fixed
function transforms a normal by the inverse transpose of the modelview and a
scale of ``s`` divides the normal's length by ``s``. Without it a half-size
shape is lit twice as brightly and a doubled one half as much. A caller that
renders geometry on its own through ``renderGeometry`` gets the same state.

Observables and Tree Updates
----------------------------

PyVRML97 allows for watching updates to properties of nodes.  OpenGLContext
uses this to watch for all updates to node fields within a scenegraph.  For
each path to each node, it records a NodePath object which can calculate (and
cache) the combined transform matrices for the path.

With this data structure (essentially a list of matrices and Render nodes),
the scenegraph can be rendered with a number of simple iterations, rather than
with a complex traversal mechanism (which traditionally was a significant
factor of OpenGLContext run-time).

The default flat render pass also includes "colour select" rendering.  That
is, it can do a selection rendering pass which can be queried to process
incoming mouse events to find the object under the mouse.  This avoids the use
of the legacy select render mode.

Gathering and culling a frame
-----------------------------

``renderSet()`` turns that flat set of paths into the ordered list a frame
draws. Each path is asked for its world matrix, because a matrix is what the
scenegraph may have changed since the last frame and the path is what knows.
Everything after that is done to the whole scene at once: the corner points of
every bounding volume are stacked into one ``(N,8,4)`` array, carried into
world space by one matrix product, and tested against the frustum's clipping
planes by one more. A shape is rejected when some plane has all eight of its
corners behind it — the same decision the per-shape test makes, taken for the
whole scene in two array operations rather than one Python call per object.

**Culling comes before the sort key**, which is what keeps the rest of the
frame proportional to what is on screen. A sort key involves the appearance,
its textures and, for transparent shapes, a projected depth; in a level most
shapes are not visible, and the keys of shapes nobody can see are never worked
out.

Two kinds of bounding volume decline to give corners, and they are opposites.
An *unbounded* volume is of unknown extent and is never culled: not knowing
where a thing is has to mean drawing it. A volume with *no* extent bounds
nothing — an :ref:`InstancedShape <instancedshape>` with nothing placed is the
ordinary way one arises — and draws nothing whether it is kept or not.

.. rst-class:: technical

Bounding volumes are asked of their nodes every frame rather than remembered
by the pass. A volume is not a property of the shape alone: an instanced shape
bounds all of its placements, so its extent changes whenever they do, and
corners kept from an earlier frame would cull this frame's copies against
where the last frame's were. The node's own volume cache is where that
question is answered, with the dependency tracking to invalidate it.

Triggering the RenderPass
-------------------------

How the rendering process is triggered, from the
moment the GUI library sends the "OnPaint" or equivalent event to the Context
through to the calling of an individual RenderPass.

#. event handler for the Context object, such as wxOnPaint for the wxPython
   Context sub-classes calls self.triggerRedraw(1) to force a redraw of the
   Context

#. Context.triggerRedraw sets the "alreadyDrawn" flag to false, which tells the
   context that it needs to be redrawn at the next available opportunity, if not
   able to immediately draw, sets the redrawRequest event.

   #. at the next available opportunity (which may be within the triggerRedraw
      method, depending on the threading status and/or whether or not we are
      currently in the middle of rendering), the context's OnDraw method will be
      called

#. Context.OnDraw

   #. performs an event cascade (calls the DoEventCascade customization point while
      the scenegraph lock is held (by default this does nothing))

   #. sets this Context instance as the current context

      #. acquires the OpenGLContext contextLock

      #. does the appropriate GUI library set current call

   #. clears the redrawRequest event

   #. calls the Context's renderPasses attribute receiving a flag specifying whether
      there was a visible change (flat \*always\* returns True here)

      #. if there was a change, swaps buffers

   #. finally, un-sets the current context

#. defaultRenderPasses.__call_\_

   #. picks the FlatPass class for the Context's profile and renderer -- the
      compatibility pass, the core pass, or the PBR pass -- and caches it,
      rebuilding only when the scenegraph itself is replaced

   #. for the core profile, binds the scene's active Viewpoint into the view
      platform (the compatibility path does this inside its own traversal)

   #. returns the result of calling that FlatPass with the Context

#. FlatPass.Render

   #. walks the paths it has observed on the scenegraph, sorting them into
      background, opaque, transparent and (when there are pick events) selection
      work

   #. draws each group in turn, then swaps buffers

.. rst-class:: technical

Earlier versions instead built an OverallPass holding a set of sub-passes,
each of which traversed the whole scenegraph in turn. That system was removed
once the flat pass replaced it.
