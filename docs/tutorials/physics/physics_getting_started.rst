Adding physics to a scene
=========================

.. rst-class:: introduction

This page builds a scene in which a ball rolls down a flight of stairs, one
step at a time, with the lines each step adds. It follows
``tests/tutorials/physics/physics_stairs.py``; run that file to see the
finished result, and the tutorials after it in this path to change what the
ball does, what it is made of and what it hears.

A context has a physics world, ``self.physics``. The world is made the first
time a script mentions it, steps itself, and is closed with the window. A
script has no clock, no tick and no redraw request.

.. _scene:

1. The scene
------------

A shape in the scene is a static body, so the stairs and the floor need no call
to hold something up. The scene is ordinary scenegraph nodes:

.. code-block:: python

   from OpenGLContext.context import Context
   from OpenGLContext.scenegraph import surfaces
   from OpenGLContext.scenegraph.basenodes import (
       Background, DirectionalLight, sceneGraph,
   )

   class StairsContext(Context):
       def OnInit(self):
           self.stairs = make_stairs()      # blocks of sandstone, from surfaces.block
           self.ball = make_ball()          # a steel sphere, from surfaces.sphere
           self.sg = sceneGraph(children=[
               Background(skyColor=[(0.55, 0.65, 0.8)]),
               DirectionalLight(direction=(0.5, -0.7, -0.2), intensity=3.0),
               self.stairs, self.ball,
           ])

A game loads the stairs and the ball from files with
``self.sceneLoader.load_now('stairs.glb').result.group``; a glTF file whose nodes
carry ``OMI_physics_body`` blocks makes their bodies when it is mounted.

.. _body:

2. A body
---------

``add_dynamic`` makes a node a body the world moves. The pose is set with the
call, so the ball is placed and added in one step:

.. code-block:: python

   self.body = self.physics.add_dynamic(
       self.ball, translation=(0, 2.26, -1.0), mass=2.0, restitution=0.4)

``mass`` is in kilograms and ``restitution`` is the fraction of the closing speed
a bounce keeps. A body that names no mass takes it from the volume of its
shape and the density of its material.

.. _push:

3. A push
---------

A body is moved by impulses (newton-seconds), velocities (metres a second) and
forces (newtons), each a call on the ``Body``:

.. code-block:: python

   self.body.apply_impulse((0, 0, 8))       # 4 m/s on a 2 kg ball, down the stairs

Each call is a command, applied at the start of the next step from whichever
thread made it. Reading a body (``body.position``, ``body.velocity``) answers
the last step the world published.

.. _events:

4. What it hit
--------------

A body tells the script what happened to it through events. ``'hit'`` is a body
striking something, ``above`` the closing speed in metres a second a hit must
exceed:

.. code-block:: python

   self.body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

   def OnBallHit(self, hit):
       self.skin.baseColor = (1, 0, 0)

The handler runs on the render thread between frames, so it may change the
scene as any other handler does. Marking it ``@Context.physics_callback`` runs it
on the thread that steps the world instead; it then sends scene changes with
``self.physics.render.set(node, field=value)``.

.. _debug:

5. Seeing the collision shapes
------------------------------

``self.physics.show_proxies(True)`` draws a green wireframe of each collision
proxy over the scene, and ``show_proxies(False)`` takes it out. The proxy is
what the world collides with: a sphere or box where the mesh is exactly one,
otherwise the convex hull of a dynamic body and the triangles of a static one.
``proxy='sphere'``, ``'box'``, ``'convex'`` or another node chooses another.

.. _next:

Next steps
----------

- Change what the ball is made of: ``physics.materials.define`` and
  ``material=``.

- Make a region with gravity of its own: ``physics.add_gravity_zone``.

- Walk around with a character: ``physics.add_character`` and
  ``context.follow`` (see the Characters on Land path).

- Load a real physics asset: point the glTF loader at a Godot or Blender
  export with ``OMI_physics_*`` extensions.

- Read the :doc:`Physics & Collision </physics>` overview for the full model.
