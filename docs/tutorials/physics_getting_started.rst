Tutorial: Add Physics to a Scene
================================

.. rst-class:: introduction

This tutorial builds a small physics scene — a walled room that objects fall
into and stack up — using the same helper the demos use. By the end you will
have an animated, interactive window with a live collision debug overlay. It
mirrors ``tests/physics_room_drop.py``; run that file to see the finished
result.

.. _scene:

1. A world and a floor
----------------------

A ``DemoScene`` keeps a scenegraph and a physics world in lockstep. Static
bodies (``dynamic=False``) never move — they are the world:

.. code-block:: python

   from OpenGLContext.physics.demo import DemoScene
   from OpenGLContext.physics import debugdraw

   scene = DemoScene(debug_flags=debugdraw.PROXIES | debugdraw.CONTACTS)
   scene.add_box(size=(12,1,12), position=(0,-0.5,0), dynamic=False)   # floor
   for sx, sz in ((1,0),(-1,0),(0,1),(0,-1)):                          # four walls
       if sx:
           scene.add_box(size=(0.4,4,12), position=(sx*6,2,0), dynamic=False)
       else:
           scene.add_box(size=(12,4,0.4), position=(0,2,sz*6), dynamic=False)

.. _bodies:

2. Dynamic bodies
-----------------

Dynamic boxes and spheres fall under gravity and collide. A material preset
(``wood``, ``metal``, ``rubber``, ``ice``) sets friction and restitution:

.. code-block:: python

   for k in range(8):
       if k % 2:
           scene.add_box(size=(1,1,1), position=(0, 6+k, 0), material='wood')
       else:
           scene.add_sphere(radius=0.6, position=(0.2, 6+k, 0), material='rubber')

.. _loop:

3. The frame loop
-----------------

Step the world from real elapsed time and let it write the poses back onto the
``Transform`` nodes. Inside an OpenGLContext ``TestContext``:

.. code-block:: python

   import time
   from OpenGLContext.physics.demo import disable_vsync

   class TestContext(BaseContext):
       initialPosition = (0, 7, 18)
       def OnInit(self):
           disable_vsync()                 # uncap fps for a forced-redraw loop
           self.scene = scene              # built as above
           self.scene.advance(0.0)
           self.sg = self.scene.scene_graph()
           self._last = time.time()
       def OnIdle(self, *args):
           now = time.time()
           self.scene.advance(min(now - self._last, 0.05))   # clamp the spiral of death
           self._last = now
           self.triggerRedraw(1)
           return 1

``advance(dt)`` runs the fixed-timestep accumulator internally, so the
simulation stays stable and deterministic regardless of frame rate.

.. _debug:

4. Reading the debug overlay
----------------------------

With the debug flags set above you will see a green wireframe of each
collision proxy and short red stubs at contact points (the contact normals).
Add ``debugdraw.VELOCITY | debugdraw.ACCELERATION | debugdraw.ANGULAR`` to
draw motion vectors: cyan velocity, orange acceleration, and magenta
angular-velocity stubs at the box corners that make spin visible. Colour-code
sleeping bodies with ``debugdraw.SLEEP``.

.. _next:

Next steps
----------

- Load a real physics asset: point the glTF loader at a Godot/Blender export
  with ``OMI_physics_*`` extensions.

- Cook a collider for an un-annotated mesh with ``cookery.cook_shape()`` (see
  ``physics_cook_view.py``).

- Walk around with the character controller (``physics_navigate.py``).

- Read the :doc:`Physics & Collision </physics>` overview for the full model.
