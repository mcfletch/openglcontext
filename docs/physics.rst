Physics & Collision
===================

.. rst-class:: introduction

OpenGLContext simulates rigid bodies in real time beside the scenegraph. The
simulation applies gravity and drag, resolves collisions between primitive
shapes and meshes, and supports triggers, gravity zones and joints. Characters
walk, run, jump and swim on the same collision world. The render tree, culling,
shadows and picking work the same with or without it.

The simulation itself is the ``omi_physics`` package, a dependency of
OpenGLContext. OpenGLContext adds the service every context hosts
(``context.physics``), the binding to scene nodes, events, characters, walking
for any context, colliders for streamed worlds, and a debug overlay. The data model is
the `OMI glTF physics extension family
<https://github.com/omigroup/gltf-extensions>`__, so physics authored in Godot
or Blender imports without conversion, and a scene exports back to glTF. The
indented technical notes point at the code.

A game imports what it needs from ``OpenGLContext.physics``: ``Physics``,
``Body``, ``Character``, ``Joint``, ``Proxy``, ``PhysicsDefinition``,
``CharacterCapabilities``, ``Material`` and ``CollisionFilter``. A program that
imports ``omi_physics`` itself reaches the parts of the engine the service has
no call for.

.. _physics-authoring:

Adding physics to a scene
-------------------------

Every context has a physics world, ``context.physics``. It is made the first
time a program mentions it and closed with the window, so a context that never
uses physics pays nothing. A body is added with one call, the world steps
itself, and what happens to a body reaches the program as an event. A program
has no clock, no tick and no redraw request:

.. code-block:: python

   class StairsContext(Context):
       def OnInit(self):
           self.sg = sceneGraph(children=[Background(), DirectionalLight(),
                                          stairs, ball])
           body = self.physics.add_dynamic(ball, translation=(0, 2.26, -1.0),
                                           mass=2.0, restitution=0.4)
           body.apply_impulse((0, 0, 8))                # 4 m/s down the stairs
           body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

The stairs are static because they are in ``sg``: a shape of the scene is a
static body (:ref:`physics-scenery`). The tutorials build this scene a few lines
at a time, and each changes one thing about it:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Tutorial
     - Adds
   * - :doc:`tutorials/physics/physics_stairs`
     - ``add_dynamic``, ``apply_impulse``
   * - :doc:`tutorials/physics/physics_stairs_colour`
     - a ``'hit'`` handler that changes the scene
   * - :doc:`tutorials/physics/physics_stairs_thread`
     - ``@Context.physics_callback`` and ``physics.render.set``
   * - :doc:`tutorials/physics/physics_stairs_shapes`
     - ``proxy=``, ``physics.cook``, ``show_proxies``
   * - :doc:`tutorials/physics/physics_stairs_material`
     - ``physics.materials.define``
   * - :doc:`tutorials/physics/physics_stairs_gravity`
     - ``add_gravity_zone``
   * - :doc:`tutorials/physics/physics_stairs_sound`
     - ``audio.play`` from a handler
   * - :doc:`tutorials/physics/physics_stairs_surface_sound`
     - a ``sound=`` on a material
   * - :doc:`tutorials/physics/physics_stairs_tuning`
     - ``enable``, ``tick_frequency``, ``set_transform``, ``PhysicsDefinition``

A character that runs across a landscape is
:doc:`tutorials/character/character_run`, and the
:doc:`Add physics to a scene <tutorials/physics/physics_getting_started>` page
walks the first tutorial. A ``Physics`` needs no context: a tool, a trace or a
test makes one with ``Physics(PhysicsDefinition(mode='inline'))``, steps it with
``frame(dt)`` and reads it (:ref:`testing-physics`).

.. _physics-bodies:

Bodies
------

Each ``add_*`` call takes a scenegraph node that draws triangles (a ``Shape``,
a ``Transform`` holding shapes, a glTF ``scene.group``) and returns a ``Body``:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Makes a body that
   * - ``add_static(node, proxy=None, **options)``
     - never moves and stops what meets it
   * - ``add_dynamic(node, proxy=None, **options)``
     - the world moves: it falls, collides and answers pushes
   * - ``add_kinematic(node, proxy=None, **options)``
     - code moves (``set_transform``, ``drive``); it pushes dynamic bodies and is
       not pushed
   * - ``add_trigger(node, proxy=None, **options)``
     - reports what enters and leaves it and stops nothing

The body takes its starting pose from the node, and while it is dynamic and
awake the world owns the pose and writes it to the node each frame. A node of
``None`` with a ``proxy`` makes a body that is only a shape, such as a level
cooked elsewhere (``add_static(None, proxy=Proxy.trimesh(points, triangles))``).
The options are keywords:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Option
     - Meaning
   * - ``translation``, ``rotation``
     - set on the node before the body is made, so a body is placed and added in
       one call; the rotation is an axis and an angle in radians
   * - ``mass``
     - kilograms, for a dynamic body; left out, the shape's volume at
       ``density`` (500 kg per cubic metre)
   * - ``material``
     - a preset or defined name (:ref:`physics-materials`) or an
       ``omi_physics.model.Material``
   * - ``friction``, ``restitution``
     - a Coulomb coefficient and the fraction of the closing speed a bounce
       keeps; they make an anonymous material, from ``material`` where that is
       given
   * - ``linear_damping``, ``angular_damping``
     - per second; the world's ``linearDamping`` (0.3) and ``angularDamping``
       (1.5) where left out
   * - ``collision_filter``
     - a ``CollisionFilter``: the systems the body is a member of, and those it
       collides with or not (:ref:`physics-presolve`); or an index in the
       world's own filters
   * - ``blocks_characters``
     - False for a body every character walks through
       (:ref:`physics-characters`)

A value that is not finite, a ``mass`` or ``density`` at or below zero, and a
damping, ``friction`` or ``restitution`` below zero raise ``ValueError`` naming
the option, and no body is made. The commands below, ``physics.gravity``,
``enable(tick_frequency=)`` and ``PhysicsDefinition.validate()`` check their
values the same way.

A body is changed by commands. Each is applied at the start of the next step,
from whichever thread made it, and a command made on the thread that steps the
world is applied at once, so one handler body works in either place:

.. code-block:: python

   body.apply_impulse(impulse, at=None)      # newton-seconds; at is a world point
   body.apply_torque_impulse(impulse)
   body.set_force(force)                     # newtons, held until set again
   body.set_velocity(velocity)               # metres a second
   body.set_angular_velocity(velocity)       # radians a second about the world axes
   body.set_transform(translation=None, rotation=None)   # a teleport
   body.linear_damping = 0.5                 # per second
   body.wake(); body.remove()
   physics.gravity = (0, -9.81, 0)           # may change every frame

Assigning to ``node.translation`` does not move a body: the world owns the
pose and the next frame writes its own. ``set_transform`` is how a body is
moved. Reading answers the last state the world published, which is at most one
step old: ``body.position``, ``rotation`` (an axis and an angle), ``velocity``,
``angular_velocity``, ``speed`` and ``asleep``. A write made but not yet
applied is what ``position`` reads back after ``set_transform``.

A scene with nothing awake costs nothing: the worker blocks until something
moves, the frame asks for no redraw, and the window draws only what else
changed.

.. _physics-scenery:

Scenery and glTF bodies
-----------------------

With ``colliders='scene'``, the default, each shape in the scene graph that no
body claims becomes a static body when the render pass first sees it: a box or a
sphere where the mesh is exactly one, otherwise its triangles. Cooking runs off
the frame, on a worker, and the body joins the world when it is done. A shape is
left out when it

- sits in an X3D ``Collision`` group that is not enabled,
- carries ``collide = False`` (glTF: ``extras.collide`` false),
- draws no triangles, or
- belongs to a body that was added by name, or sits under a node that does.

A shape's body is placed where the shape stood when it was first seen, and it
goes when the shape leaves the scene. A body added with ``add_static`` or
``add_dynamic`` for a shape the scene has already made replaces that body, which
is why a ball appended to the scene and then given ``add_dynamic`` is static for
no more than one frame. A geometry with no vertex arrays of its own, such as a
``Box``, ``Sphere``, ``Cylinder`` or ``Cone``, gives the triangles it draws.
``colliders='explicit'`` makes bodies only of what the program adds, and
``'none'`` makes no colliders at all.

A glTF file with ``OMI_physics_body`` and ``OMI_physics_shape`` blocks needs no
call: its bodies are made when the scene is mounted and removed when it is
unmounted. A program finds one of them, or any scenery, with ``body_for``:

.. code-block:: python

   door = self.physics.body_for(scene.sceneGraph.getDEF('Door'))   # a Body, or None
   door.addEventHandler('hit', function=self.OnDoorHit)
   doors = self.physics.bodies_in(scene.group)                      # every Body under a node

``body_for`` answers the body of the node itself, else of the nearest ancestor
that has one, so a ``Shape`` inside a body's ``Transform`` finds that body, and
it answers the same ``Body`` object each time. It answers None for a node the
rules above leave out. The scene derivation runs in the frame, so a node mounted
this frame has its body made on the first call, and a handler added in the
interval is kept on the handle until the body is in the world. Scenery reports
no contacts until something registers a handler on it, so a world nobody
watches pays nothing for events.

Two costs are held by tests: loading ten thousand shapes adds no work to a
frame after the first, and the derivation grows with the shapes that are new
rather than with the scene.

.. _physics-proxies:

Collision shapes
----------------

The world collides with a shape that stands for a node, its *proxy*, and the
proxy decides what the body costs and how it behaves. ``proxy=None`` cooks one
from the triangles the node draws: a fitted primitive where one fits, the
triangles for a static body and the convex hull for a dynamic one.

.. code-block:: python

   physics.add_dynamic(ball, proxy='sphere')       # fit a sphere to the bounds
   physics.add_dynamic(chair, proxy='convex')      # the hull
   physics.add_dynamic(chair, proxy=chair_low)     # another node: a simpler mesh
   physics.add_static(wall, proxy=Proxy.box((0.2, 3, 8)))   # written by hand
   crate = physics.cook(crate_node, 'box')         # cooked once, shared below
   for each in crates:
       physics.add_dynamic(each, proxy=crate)
   physics.show_proxies(True)                      # draws the proxies

The strategy names are ``'auto'``, ``'sphere'``, ``'box'``, ``'convex'`` and
``'trimesh'``; ``'trimesh'`` is for static bodies only, and a node that draws no
triangles raises ``ValueError``. ``'sphere'`` and ``'box'`` fit the primitive to
the bounds. ``Proxy`` (``OpenGLContext.physics.proxy``) wraps an
``omi_physics.model.Shape`` and adds ``box``, ``sphere``, ``capsule``,
``cylinder``, ``convex(points)``, ``trimesh(points, indices)`` and
``heightfield``. A proxy is shared by every body made with it and the world
holds its shape once, so a hundred crates cost one box. ``show_proxies(True)``
draws each body's proxy as a green wireframe over the scene and
``show_proxies(False)`` takes it out; see :ref:`physics-debug`.

``omi_physics.cookery.cook_shape()`` makes a shape from a vertex array by the
same strategies, with ``primitive`` the best-fitting box or sphere and
``decompose`` a compound of convex pieces for a concave moving body, which a
body of one shape cannot hold. To add colliders to a glTF file ahead of time,
run the ``physics_cook`` module:

.. code-block:: bash

   python -m OpenGLContext.bin.physics_cook scene.gltf -o cooked.gltf

It gives every mesh node that has no physics body an ``OMI_physics_shape`` and
an ``OMI_physics_body``: a static ``trimesh`` by default, or a ``convex`` body
with ``--motion dynamic``. It works on ``.gltf`` JSON documents and leaves nodes
that already have a body unchanged. Without ``-o`` it overwrites the input.

.. _physics-materials:

Materials
---------

A material says how a surface grips, bounces and sounds. ``wood``, ``metal``,
``rubber`` and ``ice`` (``omi_physics.model.MATERIAL_PRESETS``) are defined from
the start:

.. code-block:: python

   physics.materials.define('mud', friction=0.9, restitution=0.0, sound='squelch.ogg',
                            footstep='squelch-step.ogg')
   physics.materials.pair('mud', 'rubber', friction=1.2)     # a rule for that pair only
   physics.add_static(floor, material='mud')

``friction`` sets the static and dynamic coefficients together
(``static_friction`` and ``dynamic_friction`` set them one at a time) and
``restitution`` is the fraction of the closing speed a bounce keeps, from 0 to
1. Where two bodies meet, each coefficient is the average of the two materials'
(the OMI combine modes); ``pair`` replaces that for one pair. A material is
defined before the bodies that take it: a body is told whether to report its
strikes when it is made.

``sound`` is played where a body of the material is struck harder than 1 m/s, at
the contact point, at a gain that reaches 1.0 at 6 m/s, through
``context.audio``. ``footstep`` is played where a character's foot lands on it.
Each is whatever ``audio.play`` takes: a path, a URL, a name given to
``audio.load`` or a decoded clip. ``materials.names`` lists the names and
``materials.get(name)`` answers one.

.. _physics-zones:

Gravity zones
-------------

.. code-block:: python

   from OpenGLContext.physics.zones import Box, Sphere

   physics.add_gravity_zone(Box(center=(0, 3, 0), size=(4, 6, 4)), gravity=(0, 14, 0))
   physics.add_gravity_zone(Sphere((0, 0, 0), 30.0), gravity=12.0, toward=(0, 0, 0),
                            priority=5, replace=True)

A zone is a region with a gravity of its own; ``Box(center, size)`` is
``size`` metres across and ``Sphere(center, radius)`` has a radius in metres.
``gravity`` is an acceleration in metres a second squared: a vector, or one
number for downward, or the strength of a pull toward the point ``toward``.
Inside a zone the zone's gravity is added to the world's. A zone with a higher
``priority`` is applied after the lower, ``replace`` drops the lower ones instead
of adding to them and ``stop`` ends the counting there. ``Zone`` nodes in the
scene that carry gravity, and ``OMI_physics_gravity`` blocks in a loaded glTF
(:doc:`zones`), are registered without a call and follow the zone when it moves.
Zone gravity acts on bodies and characters of ``context.physics`` and not on
the rigid bodies of an X3D collection (:ref:`physics-x3d`).

.. _physics-events:

.. _physics-collisions:

Events
------

A body, or the whole world, tells the program what happened through events. The
names are ``hit`` (a contact begins), ``touching`` (on every step it lasts),
``separate`` (it ends), ``enter``, ``stay`` and ``exit`` (a trigger's overlaps),
``sleep`` and ``wake``:

.. code-block:: python

   ball.addEventHandler('hit', function=self.OnBallHit, above=1.0)     # faster than 1 m/s
   ball.addEventHandler('hit', function=self.OnBallHit, other=crate)   # only that body
   plate.addEventHandler('enter', function=self.OnPlate)
   physics.addEventHandler('hit', function=self.OnAnyHit)              # every body
   self.addEventHandler('physics-hit', body=ball, function=self.OnBallHit)   # the same

   subscription = ball.addEventHandler('hit', function=self.OnBallHit)
   subscription.cancel()

``addEventHandler(event, function=fn, **filters)`` is the spelling the context,
``Timer`` and ``TimeSensor`` use, and ``function=None`` removes the handlers.
``above`` is the closing speed in metres a second a contact must exceed to be
heard; a box resting on the floor closes on it by about ``g`` times the step
(0.08 m/s at 120 steps a second), so ``above=0.5`` hears every blow and nothing
while it rests. ``other`` is a body, or a list, the other side must be. A
handler that covers both sides of a pair hears the event once. Handlers are held
weakly, as every handler on :doc:`eventmodel` is: a bound method of a live
object is called, and a lambda that nothing else refers to is collected as it is
registered. A handler also ends when its body is removed. One that raises is
logged once with its collision, and the registration goes on.

Each handler receives one ``Collision``, turned to face the body it was
registered for:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Meaning
   * - ``kind``, ``phase``
     - ``'contact'`` with ``'begin'``, ``'persist'`` or ``'end'``;
       ``'trigger'`` with ``'enter'``, ``'stay'`` or ``'exit'``
   * - ``body``, ``other``
     - the ``Body`` on each side; ``other`` is always a ``Body``, scenery
       included
   * - ``node``, ``other_node``
     - the node each side drives
   * - ``point``
     - world-space contact point, metres
   * - ``normal``
     - unit vector from ``other`` into ``body``: the way ``body`` was pushed
   * - ``speed``, ``approach``
     - the closing speed along the normal before the solve, m/s
   * - ``impulse``
     - the normal impulse, N*s; a breaking strength compares against this
   * - ``friction_impulse``, ``slip``
     - friction impulse (N*s) and sliding speed (m/s), for scraping sounds
   * - ``depth``
     - the deepest penetration, metres
   * - ``time``, ``step``
     - the simulation time (seconds) and the step count of the step it happened
       on; they place an event whatever frame delivered it
   * - ``solved``
     - False where a contact filter let the pair pass through each other
   * - ``reason``
     - on an ``'end'``: ``'separated'`` or ``'removed'``

The world records every step, so a frame that ran four steps delivers what
happened on all four, and a bounce is heard at any frame rate. Two bodies that
fall asleep against each other are still touching: a crate that settles gets a
``'begin'`` and no ``'end'`` until something moves it off.

.. _physics-thread-rule:

Which thread a handler runs on
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A handler runs on the render thread unless its function is marked as a physics
callback:

.. code-block:: python

   class StairsContext(Context):
       def OnInit(self):
           body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

       @Context.physics_callback
       def OnBallHit(self, hit):
           self.physics.render.set(self.skin, baseColor=(1, 0, 0))

``physics_callback`` only sets an attribute on the function, so a direct call
runs it on the calling thread like any other. The class body of a context has
``Context`` in scope, so no import is needed, and ``OpenGLContext.physics``
provides it for other code.

- A render handler is called by the frame, after the poses are written, and may
  change the scene directly. The step that made the event ended earlier, so the
  handler cannot change that step. Its return value is ignored.
- A physics handler is called on the thread that steps the world, right after
  the step that made the event, with the world as that step left it. A slow
  one slows the simulation. It may call any ``Body`` method and
  ``physics.remove``, which apply to the world at once, and must not assign
  scene fields, since the render thread may be drawing them. The service's
  render-thread tables (the bodies by node, the copy queries read on a
  threaded world) follow such a change in the next frame.

A physics handler sends scene changes with ``physics.render``:

.. code-block:: python

   physics.render.set(node, baseColor=RED)     # coalesced per (node, field); last write wins
   physics.render.call(function, *args)        # runs on the render thread, before the next draw

Called on the render thread itself, ``render.set`` assigns at once, so moving
a handler between threads changes the marker and the line that touches the
scene, and nothing else. ``physics.post(function, *args)`` is the explicit hand-off
the other way, from the render thread to the world's thread.

The world has two events of its own. ``physics.addEventHandler('before-step',
function=fn)`` calls ``fn(step)`` before each fixed step, with a ``Step`` of
``dt``, ``index`` and ``time``, and ``'after-step'`` calls it after. A game that
applies forces, reads contacts or moves bodies between steps does it there. Both
are physics callbacks. In inline mode a physics callback for a body event runs
after the step that made the event, so a frame of three steps calls it three
times in step order with the contacts of each; a render handler runs once after
the last step and receives every event the frame made, in order, each carrying
its step. A controller that needs every contact of every step (``hit.step``,
``hit.impulse``) uses the first.

A session that is recorded writes each event a handler hears to its journal, and
a replay compares them with the recording (:doc:`telemetry`).

.. _physics-hitscan:

Hitscan weapons
~~~~~~~~~~~~~~~

A shot that is a raycast never touches the solver. The shooter casts, pushes
what it hit and says so:

.. code-block:: python

   hit = physics.raycast(muzzle, aim, max_distance=200.0, skip=player.body)
   if hit is not None:
       hit.body.apply_impulse(aim * 4.0, at=hit.point)     # N*s at the point it struck
       self.audio.play(PING, at=hit.point)

``hit`` is a ``Hit`` with the ``body`` (None for a body the service has no
handle for), the ``point``, the surface ``normal``, the ``distance`` and the
``triangle`` struck, or -1 for a shape with none. ``skip`` is a body, or a
list, the ray passes through.

.. _physics-presolve:

Breaking instead of bouncing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A pane that shatters when ``hit.impulse`` passes its strength is removed by its
handler and replaced by fragments; the ball has already bounced off it on that
step. To let the ball carry on through, decide before the solve with a contact
filter:

.. code-block:: python

   def breaks(approach):
       """False lets the ball through the pane the blow breaks."""
       return not (pane in (approach.first, approach.second) and approach.impulse > 5.0)

   physics.set_contact_filter(breaks)

The filter is asked once about each pair as it first touches, where one of the
two bodies has a handler, on the thread that steps the world. ``approach`` is an
``Approach``: ``first`` and ``second`` (bodies, or None for a body with no
handle), ``approach`` (the closing speed in m/s), ``impulse`` (that speed times
the pair's reduced mass, in N*s), ``point`` and ``normal``. True or None solves
the pair; False lets the two pass through each other until they part. An
ignored pair is still delivered, with ``solved`` False, so the handler that
spawns the fragments hears it. A filter that raises is logged once and the pair
is solved. ``physics.set_contact_filter(None)`` removes it. A character's
stand-in passing a body heavier than it can push is decided before the filter
is asked.

The fragments should not deflect the ball either. A collision filter puts bodies
in systems and says which systems meet:

.. code-block:: python

   from OpenGLContext.physics import CollisionFilter

   balls = CollisionFilter(collisionSystems=('ball',))
   shards = CollisionFilter(collisionSystems=('shard',), notCollideWithSystems=('ball',))
   physics.add_dynamic(ball, collision_filter=balls)
   physics.add_dynamic(shard, collision_filter=shards)

Two bodies collide only where each one's filter admits the other.
``collideWithSystems`` names the only systems a body meets; left as None it
meets every system not in ``notCollideWithSystems``. Equal filters given to
several bodies are one filter in the world. Queries and characters do not read
collision filters.

.. _physics-movers:

Doors, lifts and platforms
~~~~~~~~~~~~~~~~~~~~~~~~~~

A kinematic body moves at the velocity it is given and nothing pushes it.
``body.drive(pose)`` steers one by a function of time: at the end of each step
the service calls ``pose(time)`` with the simulation time in seconds, and the
body takes the velocity that carries it to the ``(translation, rotation)`` the
function returns, the rotation an axis and an angle or None to leave it. What
stands on the body is carried, and a hit against it has the right closing
speed. The function is a physics callback:

.. code-block:: python

   door = physics.add_kinematic(door_node, proxy=Proxy.box(DOOR_SIZE))

   @physics_callback
   def pose(time):
       lift = door_lift(time, plate_pressed())      # metres, from the plate's events
       return (x, y + lift, z), None

   door.drive(pose)

``set_transform`` also places a kinematic body, as a teleport that gives it no
velocity. The pressure
plate of ``oglc-physics-events`` is an ``add_trigger`` body whose ``enter`` and
``exit`` handlers keep the set of what is on it, which the door's pose reads.

.. _physics-queries:

Queries
-------

A query answers in the call, on the thread that makes it:

.. code-block:: python

   hit = physics.raycast(origin, direction, max_distance=100.0, skip=body)   # Hit or None
   hits = physics.raycast_many(origins, directions, max_distance=100.0)      # arrays in, a list out
   clear = physics.line_of_sight(start, end, skip=body)                       # nothing between them
   distance = physics.sweep_sphere(origin, direction, distance, radius)      # how far it goes, or None
   touching = physics.overlap(proxy, translation, rotation=None, triggers=False)   # the Bodies it overlaps

In inline mode a query reads the live world. In thread mode the render thread
reads a copy of the bodies it keeps in step with what the world publishes, so a
query sees bodies as they stood at the last step, and a character as it is now.
``sweep_sphere`` answers 0 for a sphere that starts inside a body and steps by
half its radius, so a wall thinner than that can be passed. ``raycast_many``
takes arrays so a program that casts a swarm of projectiles makes one call per
frame.

.. _physics-characters:

Characters
----------

``add_character`` makes a walker: a capsule that slides against the bodies, steps
up ledges, jumps, flies and swims, stepped by the frame on the render thread so
that input reaches the camera with no step between and a query answers in the
call. The world sees a *stand-in*, a kinematic body a little wider than the
capsule that is placed at it each frame with the velocity it moved at:

.. code-block:: python

   me = physics.add_character(position=(0, 1, 0), capabilities=CharacterCapabilities(...))
   hero = physics.add_character(model='hero.glb', animations='ual',
                                position=(0, 0, 0), parent=self.sg)

   me.set_move(direction, mode='walk')       # 'walk', 'run', 'sprint' or 'crouch'
   me.set_move(direction, speed=4.5)         # metres a second, whatever the mode
   me.speed = 2.0; me.speed = None           # set it; None gives the mode's speed back
   me.jump(); me.set_crouch(True); me.slide(0.8)
   me.position, me.eye, me.velocity, me.grounded, me.state, me.heading
   me.addEventHandler('hit', function=fn)    # a body's events; 'landed' and 'footstep' too
   me.remove()

The capsule's size and speeds are an ``omi_physics`` ``CharacterCapabilities``
(:ref:`character`). ``set_move(direction, mode='walk', speed=None)`` moves at
``speed`` metres a second where one is given and at the mode's speed from the
capabilities where it is None; a crouched character goes no faster than
``crouchSpeed``. ``me.speed`` is the speed the moves go at, and setting it
changes it until the next ``set_move``. Neither changes the capabilities. A character with a ``model`` is placed at the feet, turned
toward where it goes and animated by what it does (:doc:`characters`).
``context.follow(hero)`` shows it from behind and moves it from the keys
(:ref:`navigation-follow-character`), and ``context.follow(me, view='eyes')``
puts the camera at its eyes and walks it with the walk and fly modes' keys.
A character that is dead, hidden or between rounds is removed.

A character and a dynamic body act on each other. The stand-in carries the
character's velocity, so the solver pushes a body the character walks into, at
up to ``pushSpeed``, and a body heavier than ``pushMass`` (200 kg) blocks the
character instead. A blow the stand-in takes becomes a change of velocity of
``impulse / mass`` (80 kg) on the character's next step, so a crate thrown at a
walker knocks it back. A character stands on a dynamic body and is carried by
it. A body added with ``blocks_characters=False`` is walked through.

The lone character of an inline service writes its stand-in to the world when
something can see it: a dynamic body, a trigger or a sensor within reach of it
in a step, or a ray, sweep or overlap whose bounds reach it. Until then the
stand-in waits, still, where it was last written, and the write puts it where it
would have been had it been written at every step, so bodies, triggers and
queries meet it as they would. Its pose read from its body is that of the last
write. ``physics.world``, ``physics.run``, ``slot_of``, ``index_of`` and
``body_at`` write every waiting stand-in first, so the raw world holds each one
where its character is. With a second character, a worker
thread or the proxies shown, each write is made as it is asked for.

A character takes the same steps as the world. The frame steps each character
once for each fixed step of ``1 / tickHz`` seconds the frame owes (120 a second
by default), each step with the character's latest ``set_move``, ``jump`` and
other input, so a walk or a jump traces the same path at 30, 60 or 144 frames a
second. Inline, the count is the one the world's own clock gives, whether or not
the world was busy enough to take its steps; with the world on a thread, the
service counts steps at the same rate on the render thread. The node and a
camera at the eyes are drawn between the character's last two steps, by the
part of a step the frame leaves over: ``me.drawn_position`` and
``me.drawn_eye``. ``me.position`` and ``me.eye`` are where the latest step put
it. ``physics.drop_remainder()`` forgets the characters' part step with the
world's.

A game that steps a character on a clock of its own sets its ``framed`` to False
and steps it itself (:doc:`characters`).

.. _physics-ground:

Land
~~~~

``add_ground`` makes a static body of land that answers a height at each
``(x, z)``:

.. code-block:: python

   self.physics.add_ground(land)
   self.physics.add_ground(land, extent=((-500, -500), (500, 500)), material='grass')

``land`` is any object with ``sample(x, z)`` for arrays, such as a
:ref:`HeightField <terrain-heightfield>`, so the surface a body meets is the
surface the terrain node draws. A ``normal(x, z)`` that answers an array of unit
normals saves several samples where the slope is wanted. ``extent`` is
``((x_min, z_min), (x_max, z_max))`` or None for land without an edge,
``height_range`` is ``(lowest, highest)`` and is found by sampling a 65 by 65
grid of the extent (or 1000 m about the origin), widened by 20%, and ``feature``
is the horizontal distance in metres over which the land changes appreciably
(1.0). The same options as ``add_static`` apply. A mesh drawn for the land is
scenery and would be a second body: mark it ``collide = False``.

.. _physics-sources:

Colliders that come and go
~~~~~~~~~~~~~~~~~~~~~~~~~~

A collider source makes bodies as a focus nears them and drops them as it
leaves: ground chunks near a car, road sections, props, rocks near a walker.

.. code-block:: python

   handle = physics.add_collider_source(source, focus=lambda: car.position)
   handle.remove()

``source.update(focus)`` is called once a frame with the position of the focus
and returns a ``Changes``: ``add`` lists ``(key, proxy, position,
orientation)`` for each body to make, ``remove`` the keys of those to drop. The
``orientation`` of a plain tuple is a quaternion ``(x, y, z, w)``, as the world
holds turns; ``sources.Addition(key, proxy, position, rotation=(x, y, z,
angle))`` takes the axis and angle the ``add_*`` calls take instead. A
source returns only what changed, and a key is anything hashable that names a
collider to the source. The focus is the first character's feet where none is
given. ``physics.add_static_instances(proxy, positions)`` makes one static body
of one shape at each row of an ``(n, 3)`` array, for trunks and posts, and its
``remove()`` takes them out together. The classes of :ref:`streamed worlds
<streamed>` are sources.

.. _physics-service-modes:

Modes and settings
------------------

``PhysicsDefinition`` is a scenegraph node, declared on
``ContextDefinition.physics`` the way ``AudioSettings`` is declared on
``ContextDefinition.audio``:

.. code-block:: python

   ContextDefinition(physics=PhysicsDefinition(mode='inline', tickHz=240.0))

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Default
     - Meaning
   * - ``enabled``
     - yes (``OPENGLCONTEXT_PHYSICS``)
     - no starts no world and makes no colliders; bodies stay where they are put
   * - ``mode``
     - ``thread`` (``OPENGLCONTEXT_PHYSICS_MODE``)
     - ``thread`` steps the world on a thread of its own, ``inline`` in the frame
   * - ``backend``
     - ``auto`` (``OPENGLCONTEXT_PHYSICS_BACKEND``)
     - the compute backend (:ref:`below <physics-backends>`); one that cannot
       be made is logged and the world steps on ``auto``
   * - ``tickHz``
     - 120
     - the fixed step, in steps a second, in both modes
   * - ``maxCatchUp``
     - 0.1
     - the most time one frame steps, in seconds; the rest is dropped
   * - ``gravity``
     - ``0 -9.81 0``
     - metres a second squared, global
   * - ``colliders``
     - ``scene``
     - ``scene``: the shapes of the scene are static bodies; ``explicit``: only
       the program's; ``none``
   * - ``linearDamping``, ``angularDamping``
     - 0.3, 1.5
     - per second, for a body that names none

``physics.set_config(definition)`` applies the same node between steps, and
``physics.enable(False)`` pauses the world with every body where it is;
``physics.enable(True, tick_frequency=240)`` runs it again with a finer step. A
paused world takes no steps; bodies added and removed, writes and joints made
while it is paused reach it, in the order they were made, when it runs again,
and so do those of a service that starts with ``enabled`` false. The
variables of :doc:`environment` set the defaults. The settings are the
program's choices; a player's switch is ``OPENGLCONTEXT_PHYSICS`` alone.

In ``inline`` mode the frame reads its time from the engine's clock, adds it to an
accumulator capped at ``maxCatchUp`` and runs as many whole steps of ``1 /
tickHz`` as the accumulator holds. Which step a body was in when something
happened is therefore the same on every run at a given frame time, and
``physics.step(dt)`` and ``frame(dt)`` let a program supply its own time, as a
replay's recorded frame times or a headless trace do. The world is then the
caller's to read: ``physics.world`` is the live ``omi_physics`` world,
``physics.slot_of(body)`` and ``body_at(slot)`` map bodies to rows of its arrays,
``flush()`` applies the commands still waiting, and ``drop_remainder()`` forgets
the time left over from a frame so a game that starts something afresh does not
simulate it. ``physics.run(function)`` calls ``function(world)`` on the thread
that steps the world at the start of a step and returns a future; it is how a
call the service has not named is made in either mode.

In ``thread`` mode the same steps run on a worker at ``tickHz``, which keeps the
render thread free of a heavy world. Under CPython's global interpreter lock the
worker and the render thread share one core's worth of Python: the worker runs
``tickHz`` steps a second of wall time, so while a step costs most of its tick
the render thread's own physics work (characters, queries) runs at a fraction of
its inline speed, and a longer frame lets the worker run more steps in it. At 30
characters among 10 000 static posts, with a world whose step takes 14 ms of a
16.7 ms tick, the characters cost 42 ms of render time a frame against 10 ms
inline. A world whose steps cost a large share of the tick runs better inline. A bounded capture, a recorded session and a
replay run inline whatever the mode says, so a captured frame is the same bytes
on every run. A recording started with ``context.startTelemetry()`` after the
world exists moves it inline, the commands waiting for its thread carried over
in order; a mode given to ``set_config`` meanwhile takes effect once
``stopTelemetry()`` ends the recording. ``physics.pin_inline(True)`` holds a
world inline in the same way for a program of its own. A world held inline
waits for the cooking of its scenery before each step, so scenery the render
pass finds while drawing one frame takes part from the next frame's step on
every run. A game that steps its world on a clock of its own, or only while it
is not paused, sets the class attribute ``stepsPhysics = False`` on its context
and calls ``context.physics.frame(dt)`` where it wants the step.

An exception that ends the worker's thread is logged once with its traceback
and kept as ``physics.error``. The world takes no more steps and bodies stay
where they were. A ``physics.run(fn)`` future fails with that exception, and
``physics.worker.settle()`` answers False at once. The next
``physics.frame(dt)`` raises a ``RuntimeError`` whose cause is that exception,
once. A collider source or a character whose ``update`` raises in the frame is
logged once for each distinct failure, and the frame goes on with the others.
A context's frame hook logs what ``frame`` raises, once for each distinct
failure, and draws the frame, so physics never raises into the draw.

.. _model:

Data model: OMI glTF physics
----------------------------

Every concept in the engine is an OMI concept. The OMI schema is the in-memory
model: there is no separate ``RigidBody`` node mapped onto glTF at load time.
The loader, the nodes and the simulation all use the same structures.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - OMI extension
     - Provides
     - In code
   * - ``OMI_physics_shape``
     - box, sphere, capsule, cylinder, convex, trimesh
     - ``model.Shape``
   * - ``OMI_physics_body``
     - ``motion`` / ``collider`` / ``trigger``, materials, collision filters
     - ``model.Motion``, ``Collider``, ``Trigger``, ``Material``, ``CollisionFilter``
   * - ``OMI_physics_gravity``
     - global gravity *and* per-volume gravity zones; also a zone's gravity
       (:doc:`zones`)
     - ``model.Gravity``
   * - ``OMI_physics_joint``
     - limits + drives between bodies
     - ``model.Joint``, ``joints.*``

An object's physical properties are OMI motion fields. An immovable body, such
as the ground, is ``type:"static"``. Weight is ``mass × |g|``. The centre of
gravity is ``centerOfMass``.

.. rst-class:: technical

The structures are in ``omi_physics/model.py``, with the OMI specification's
defaults. The reader and writer are in ``omi_physics/omi_gltf.py``:
``load_document()`` parses a glTF's extension blocks into these structures, and
``export_extensions()`` writes them back, so a load followed by an export
gives nearly the same document. ``KHR_physics_rigid_bodies`` is not read.

.. _engine:

How the simulation runs
-----------------------

The engine uses the standard real-time methods (Catto's Box2D, and Gaffer on
Games' *Fix Your Timestep*):

- Integration - semi-implicit (symplectic) Euler, which stays stable at low
  cost.

- Timestep - fixed, with an accumulator, independent of the render frame rate.
  The rendered pose interpolates between the last two states, so motion is
  smooth and deterministic.

- Broad phase - a dynamic AABB tree of enlarged boxes, filtered by collision
  groups, removes most of the O(N²) candidate pairs.

- Narrow phase - analytic tests for pairs of primitives, and GJK with EPA for
  convex against convex (cylinders and cones among them) and convex against
  triangle; a compound part by part. A sphere, a capsule or a box against a
  static mesh is tested against all its nearby triangles in one call, and a
  character's capsule against all its nearby static boxes in another.

- Solver - sequential impulses (projected Gauss-Seidel) with warm starting and
  split-impulse position correction. Restitution and Coulomb friction combine
  according to the OMI material modes. Contacts are grouped into islands, and
  bodies that have come to rest sleep.

.. rst-class:: technical

Simulation state is a flat structure of arrays (``world.py``), kept beside the
scenegraph and copied to the ``Transform`` nodes only between steps. The
per-stage kernels run through ``backend.py``, which has two implementations:
``NumpyBackend`` (vectorised, on the CPU) and ``GLComputeBackend``
(``glcompute.py``). The GPU backend runs the per-body force and position
integration as GL 4.3 compute shaders over the same arrays. When a step has no
collisions and no joints, both stages run in one dispatch and the intermediate
velocity stays on the GPU. At 10\ :sup:`5` moving bodies it is about 2.4×
faster than numpy.

.. _physics-backends:

.. rst-class:: technical

The default policy, ``auto``, runs on numpy until the number of awake bodies
reaches ``gpu_threshold`` (default 10 000), and then switches to the GPU. Below
that count, the cost of transferring the data is larger than the per-body work
it saves. The world switches back to numpy when the count falls below 80% of
the threshold, and stays on numpy where GL 4.3 compute shaders are not
available. ``PhysicsDefinition.backend``, whose default is
``OPENGLCONTEXT_PHYSICS_BACKEND``, overrides the policy with one of
``Physics.BACKENDS``: ``auto``, ``numpy`` or its synonym ``cpu``, and ``gpu``
or its synonym ``glcompute``. ``physics.backend`` is the name of the backend in
use (``'numpy'`` or ``'glcompute'``), and assigning one of ``Physics.BACKENDS``
chooses one from the next step. The GPU backend needs GL 4.3 compute
on the thread that steps the world, so it is for an ``inline`` world; a backend
that cannot be made logs a warning and the world keeps the one it has. The GPU computes in float32, so its
trajectories match the numpy backend within a tolerance, not bit for bit. The
broad phase, narrow phase and solver run on the CPU with either backend. In
``tests/tutorials/physics/physics_stress.py``, the ``b`` key switches backends while the demo
runs.

.. _physics-cost:

What a frame costs
------------------

A world at rest costs nothing. When no command has arrived and nothing moves,
neither mode steps: the inline frame returns at once and the worker thread
blocks, and the last published poses stand. A world stays busy, and is stepped,
while a dynamic body is awake, a kinematic body moves, a body is driven by a pose
function, or a ``before-step`` or ``after-step`` handler is registered, so a
game's step handler runs every step whether or not anything moves. Its clock does
not advance while it is not stepped.

What a step costs follows what moves:

- The broad phase sweeps the moving bodies against each other and against the
  static ones near them; the static bodies are sorted once.
- A pair with no awake dynamic body, no kinematic body, no trigger and no sensor
  in it is left out of the step, so a sleeping pile costs its broad phase and
  nothing more.
- Collision filters are compared once per step for each pair of filters in use,
  not once per pair of bodies.

What the render thread does each frame follows what changed: a snapshot lists
the rows of the bodies whose pose or velocity changed since the snapshot before
(``Snapshot.changed``), and only those nodes are written and only those rows of
the replica copied and refitted. A body that falls asleep is published once more,
at the pose the world holds for it, so its node rests exactly where the body
does.

A step reads only the static bodies the world recorded as added, removed or
placed since the step before (``PhysicsWorld.layout_epoch``); the others are not
compared, refitted or copied. The world's ``position`` and ``orientation`` are
read-only: ``PhysicsWorld.place_body`` places a body and records it, and a pose
written through ``PhysicsWorld.pose_arrays()`` into a static body is recorded
with ``PhysicsWorld.moved(rows)``. ``OMI_PHYSICS_CHECK_STATICS=1`` makes a step
raise for one that was not. A
step with no awake dynamic body, trigger, sensor or touching pair skips the
collision pass, as does a step in a world with no dynamic body where no
kinematic body's box meets a trigger's, and a world with a few moving bodies is
swept from them outward. A swept sphere is tested against a fixed body only at
the distances where its box meets that body's.

A character holds the static bodies it gathered across updates while the layout
is unchanged, and depenetrates against them: the few boxes near it one at a time
with numbers, the triangles of a mesh in one call, and a height field as the
column of spheres down its axis, of which only those low enough to touch a
slope that gentle are slid. Its poses agree with the contact solver's to 1e-9 m
a step. Where ``omi_physics``'s compiled accelerator is built, a grid answers
the whole column in one call and a mesh its triangles near the capsule, with the
same numbers as the Python. The lone character's stand-in is written only when
something can see it (:ref:`physics-characters`). On this machine one walker on
a box floor costs about 130 us a frame, 60 us of it the controller; 30 among box
posts about 2.7 ms in a median frame and 5.5 ms on average;
the forest walker about 1.7 ms; twig-bb with 8 bots about 1.8 ms; and the
hill-runner's runner on its streamed height-field hill, stepped at 120 Hz with
the rules and the camera, about 0.59 ms a frame, of which the controller is
85 us a step and the world 63 us a step.

.. _walking:

Walking any scene
-----------------

Any interactive context can walk. ``OpenGLContext.move.physicswalk.PhysicsWalkMixin``
is mixed into ``ViewPlatformMixin``, so any context with a camera can hand that
camera to an avatar. Every physics import is inside a method, so a context
that never turns walking on never imports the physics package.

.. code-block:: python

   class MyWorld( BaseContext ):
       def OnInit( self ):
           self.sg = load_my_world()
           self.setupPhysics( enable=True )    # binds 'g', and starts walking

While walking, the avatar owns ``context.platform`` and the free-fly movement
manager is unbound. Switching back rebinds the movement manager at the place
the avatar left the view. Only one of the two drives the camera at a time; if
both ran, the camera would jump back on every key release.

Walking is switched at run time, not chosen at start-up, so that a viewpoint
that puts the avatar inside geometry cannot trap the user. Press :kbd:`g` to
fly out, and :kbd:`g` again to walk from wherever you are.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it does
   * - ``setupPhysics( enable=False )``
     - Makes walking available, binds the toggle key, and optionally starts
       walking. Returns whether the avatar is walking. It returns False when
       nothing in the scene is walkable; that is not an error.
   * - ``enablePhysics( on )``
     - Switches between walking and free-fly, leaving the camera where it is.
   * - ``stepPhysics( dt=None )``
     - Advances the avatar one frame and moves the camera to it. Call it from
       ``OnIdle``. ``dt`` defaults to the wall-clock time since the last step,
       clamped so that a stall cannot move the avatar through a wall.
   * - ``buildPhysicsWorld()``
     - Returns ``(world, (lo, hi))``, or None if nothing is walkable. The
       default cooks one static collision mesh from ``self.sg``. Override it
       for a context that has its own collision world, such as a terrain height
       field or a level format that ships its own collision; the override does
       not need ``sg``.
   * - ``characterCapabilities( scale )``
     - Returns the avatar's size and starting speeds. Override it for an avatar
       that is not roughly a person. The active :doc:`movement mode
       <navigation>` sets the walk, run, fly and swim speeds while it drives, so
       the mode's values replace the speeds set here. The body's proportions,
       jump and crouch stay as set here.
   * - ``spawnAvatar( lo, hi, caps, viewpoints )``
     - Places the avatar somewhere it can walk from. See
       :ref:`physics-spawn`.
   * - ``moveAvatarToViewpoint( vp )``
     - Places the avatar at a ``Viewpoint``'s position, facing the same way,
       with :ref:`safe placement <character>`. If the viewpoint is in the air,
       the avatar starts flying, so it stays in the shot instead of falling.
   * - ``OnViewpointBound( vp )``
     - Called as the frame moves the camera to a viewpoint bound after the
       first. While walking, the avatar is placed where the viewpoint put the
       camera, with :ref:`safe placement <character>`, looking the way the
       viewpoint looks, pitch included. The camera's
       :ref:`transition <x3d-binding>` to the viewpoint ends at the
       avatar's eye, and ``stepPhysics()`` leaves the avatar there until the
       transition arrives. In free-fly the avatar is not moved. Binding a
       viewpoint, by ``set_bind`` or by the next-viewpoint key, is all a
       walking application does to go to it.
   * - ``resolvePhysicsStep()``
     - Called after the character has solved its step and before the camera
       reads its pose. A host whose ground is not in the collision world
       corrects the avatar's pose here, for example by putting it back on the
       ground. Does nothing by default.
   * - ``getNavigationPlatform()``
     - Returns what the declared movement modes drive: the avatar while
       walking, the camera otherwise.

.. _physics-heightfield:

Walking a landscape
~~~~~~~~~~~~~~~~~~~

``OpenGLContext.move.terrainwalk.TerrainWalkMixin`` is walking for a
landscape. It uses the same avatar, movement modes and keys as any other
walking context, but the ground is a :ref:`HeightField <terrain-heightfield>`
and the obstacles are a field of cylinders (tree trunks). They are bodies in
the context's physics world (:ref:`physics-landscape`), and the avatar is a
character in it that the service steps, so a body dropped on the landscape
lands on the ground and strikes the trunks, and the walker pushes it.

It overrides the methods above that make and resolve the avatar:

- ``ensurePhysicsWorld()`` makes the character in the context's physics world
  and a platform over it, and takes the frame: the movement modes are given the
  frame before the world is stepped, and the camera is put at the avatar's eye
  after.
- ``spawnAvatar()`` stands the avatar on the ground below the camera the scene
  placed. Every point of a height field can be stood on, so there is no
  search.
- ``resolvePhysicsStep()`` lifts a flying avatar to the surface after each
  step.

It also keeps the avatar at one metre to the unit (``physicsAvatarScale()``;
a height field is already in metres), sizes it from its own ``eye_height``,
``player_radius``, ``step_height`` and ``max_slope``
(``characterCapabilities()``), declares mouse-look, walking and flying unless
the host declared movement modes of its own (``applyMovementModes()``), and
holds a free-flying camera on the ground and out of the trunks after each
frame's events (``DoEventCascade()``).

A jump rises, and an avatar arriving from the air falls onto the ground. Trunks
stop a walker but not a flier, because flying has no collision. The
``oglc-forest`` demo uses this mixin, as does anything built on
``scenegraph.terrain`` (see :doc:`terrain`).

The avatar is sized to the world
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A viewer can open anything from a bolt to a city, so the avatar's stride and
gravity have to be in the model's units. The avatar is **1/40 of the world's
longest side** (``physicsAvatarScale()``). ``applyMovementModes()`` declares
the :doc:`movement modes <navigation>` again at the same scale.

.. _physics-spawn:

Finding somewhere to stand
~~~~~~~~~~~~~~~~~~~~~~~~~~

The middle of a model is often solid: a statue, thick walls, or no floor at
all. ``spawnAvatar()`` tries candidate positions in this order:

#. The authored camera viewpoints. The first one also sets the heading.
#. The centre of the model's footprint.
#. Rings further and further out from the centre.

It keeps a candidate only if the avatar lands on the ground without being
stuck. Each kept candidate is scored by how many of the four horizontal
directions have room to move. The most open spot wins, and among equals the
most central. A fully open spot is taken at once. If no spot is walkable, the
avatar goes to the centre anyway: the camera needs a pose, and the user can
press :kbd:`g` to fly out.

.. rst-class:: technical

The clearance test places the whole capsule an arm's length along each
direction and pushes it out of any overlap. This finds walls that the
avatar's centre line would miss. It is a placement test, not a swept move, so
it does not detect a barrier thinner than the capsule. Its reach is a fixed
distance, not scaled to the avatar, so on a small model it reports more
directions as open than a scaled test would.

.. _character:

The character controller
------------------------

Walking uses a kinematic capsule with move-and-slide, configured by a
``CharacterCapabilities`` record, which is not part of the OMI schema. It
supports walk, run, sprint and crouch speeds, jumping when grounded,
fly/noclip, stepping up small ledges, and sliding on steep slopes.

Each time a viewpoint is bound, the controller places the capsule safely: it
pushes the capsule out of any geometry it overlaps, then snaps its base onto
the floor. A camera authored low or inside a wall therefore never leaves the
user stuck in the ground. If there is no free space, the controller switches
to flying.

Fast falls
~~~~~~~~~~

Contact is **discrete**. Each step moves the capsule, then resolves whatever
it overlaps. If one step carries the capsule completely past a floor, nothing
overlaps and nothing stops it. A fall of three or four storeys does this at
ordinary frame rates.

The controller therefore splits each frame into substeps short enough that
the capsule cannot move further than its own size in one of them. Horizontal
and vertical movement have separate limits, because the capsule is taller
than it is wide. An ordinary walk needs no substeps; a fast fall takes small
steps for as long as it is fast.

``CharacterCapabilities.terminalVelocity`` caps the fall speed. The default is
55 m/s, about the terminal velocity of a falling person. The largest number
of substeps is computed from this cap, so raising the cap raises the substep
limit with it. Setting ``terminalVelocity`` to 0 removes the cap and the
guarantee: the fall accelerates without limit, and ``max_substeps()`` returns
``sys.maxsize`` to say the count is unbounded.

Contact against a triangle pushes the capsule out by **how far it reaches past
the triangle's face**, towards the side the capsule is on. The push is not
measured to the nearest point on the triangle. After a hard landing the lower
cap can be below the floor, and a push towards the nearest point would drive
the character down through the floor it hit, with no ground reported. The
side is taken from the capsule's position, not from the triangle's winding,
because a triangle soup has no consistent winding. The same rule makes a
ceiling push the capsule down.

Slopes and steps
~~~~~~~~~~~~~~~~

The move direction is **projected onto the ground surface** before it is
applied. A run up a ramp therefore covers the same distance per second as a
run on the flat, and the climb is the vertical part of that distance. A
horizontal move would push the capsule into the slope, and the slope would
push it back out along its normal, against the motion; steep but walkable
ramps would slow the character down. The step-down snap that keeps the capsule
on the ground moves it only vertically. A snap along the normal would drag the
capsule downhill on every step of a climb.

``maxSlope`` (default 50 degrees) decides what counts as ground. Standing,
snapping to the ground and stepping up all use it, so a face too steep to walk
on cannot be stood on, snapped onto or stepped onto. This stops a fast
character climbing a cliff one ``stepHeight`` at a time.

To mount a step, the capsule's centre has to move past the edge, about one
radius, in a single motion; a shorter move leaves it stopped against the
riser. One such motion is further than a frame of running covers, so without
correction a staircase would be climbed faster than the same distance on the
flat, and faster at higher frame rates. The controller records how far a step
moved the capsule beyond its frame's share, and takes that distance back from
the following frames a little at a time, so the capsule never stalls. Stairs
are climbed at running speed at any frame rate.

Jumping
~~~~~~~

A capsule running over a step, the lip of a ramp or a seam between two
colliders leaves the ground for a frame or two. A jump pressed during one of
those frames would be refused, with no feedback to the player. Two time
windows accept those presses. Both are in seconds, so they behave the same at
any frame rate:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Capability
     - Default
     - What it does
   * - ``coyoteTime``
     - 0.12 s
     - A jump is still allowed for this long after walking off an edge.
   * - ``jumpBuffer``
     - 0.12 s
     - A jump pressed this long or less before landing happens on landing.

Both apply only after the capsule has walked or fallen off something. A
capsule that left the ground by jumping has no coyote time, so there is no
extra double jump, and a buffered press is used once. Set either value to 0 to
turn it off. A jump refused for any other reason, such as crouching or
``canJump`` being off, is not buffered.

**A rising capsule is never grounded**, whatever is below it. When nothing
touched the capsule during a step, the controller looks ``GROUND_PROBE`` (5 cm)
below it for a floor; this keeps a walker on the ground over small gaps. In
the first frame after a jump, the capsule has risen only ``vy × dt``, and at a
high frame rate that is less than the probe distance. The probe would find the
floor, snap the capsule back down and zero its velocity, and whether a jump
worked would depend on the frame time. The capsule is also still touching the
floor it is leaving. The controller ignores both tests while the capsule is
moving upward.

Slides and jumps on a slope
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``slide(duration, rise)`` keeps the momentum the character has and ignores
the input. ``slide(duration, rise, steer=True)`` takes no momentum and no
friction, and the input goes on moving the character at the speed of its mode
(not the crouch speed), which is how a runner slides under a gate and goes on
turning with its path. ``extend_slide(duration)`` makes the slide last
``duration`` seconds more from now and puts the capsule low again;
``end_slide()`` ends it at once and stands, or crouches where there is no room.
Both return whether there was a slide.

A jump from the ground launches at ``sqrt(2 g jumpHeight)`` whatever the
ground does. On a slope that falls away under a runner, the ground has dropped
by the time the jump peaks, so the jump rises higher above the ground than
``jumpHeight``. ``CharacterCapabilities.jumpFollowsSlope`` (default false) adds
the vertical speed of the run along the ground to the launch, and a jump rises
``jumpHeight`` above the ground it left off a falling or a rising slope.

.. rst-class:: technical

The controller is ``omi_physics/character.py``. ``PhysicsViewPlatform`` in
``move/physicsplatform.py`` drives a context's camera from it. See the
``physics_navigate.py`` demo.

.. _streamed:

.. _roadcolliders:

Colliding with a world that streams
-----------------------------------

A :doc:`streamed world <tiles3d>` draws level-of-detail geometry. The streamer
chooses each tile's resolution from its distance to the camera, and changes it
as the camera moves. Colliders built from those tiles are good enough for a
walker, but not for a fast vehicle. Two resolutions of the same curve can
differ by most of a metre, so the surface steps under the wheels each time the
streamer refines a tile. At racing speed that is like hitting a wall in the
middle of an open road.

So colliders are built from what is in the world, not from its tiles: only
drawn tiles get colliders, and roads and props get colliders of their own.

.. _physics-landscape:

Landscapes
~~~~~~~~~~

A landscape of kilometres is too large to hold as a mesh, and the renderer
already answers its height at any point. ``OpenGLContext.physics.landscape``
makes the world's bodies from the same height field the terrain node draws:

.. code-block:: python

   from OpenGLContext.physics.landscape import Landscape, NearbyColliders

   Landscape( context.physics, ground, trunk_positions, trunk_radii )
   context.physics.add_collider_source( NearbyColliders( rocks.mounds_near ),
                                        focus=lambda: walker.position )

``Landscape( physics, ground, trunks=None, radii=None )`` adds the ground as a
static body that answers a height and a normal at each ``( x, z )``, and each
trunk as a cylinder 24 m tall that stands on the ground under it.
``ground`` is anything with ``sample( x, z )`` for arrays, such as a
``HeightField`` or the ``RockyGround`` that stands for a rock-covered field;
``extent`` says where it ends, and is taken from the ground's own ``extent``.
Radii are rounded up to the next 0.05 m, and trunks of one radius share one shape
and are added in one call. A ground that is not a ``HeightField`` is read through
``SampledGround``, which keeps 32 m tiles of its samples on a grid as fine as
its ``spacing``, because a character asks for dozens of heights in a step and
rock displacement is slow to compute. A tile of rocky ground takes a tenth of a
second to make, so ``landscape.follow( focus )`` has the tiles within one of the
focus's made on a thread of their own, ahead of the walker reaching them; a tile
asked for before it is ready is made by the asker.

``NearbyColliders( answer )`` is a collider source for things that come and go:
rocks, posts, a scatter streamed round the focus. ``answer( x, z, reach )``
returns ``( positions, radii )`` for cylinders or ``( positions, radii, rims,
tops )`` for domes. Things within ``reach`` (24 m) of the focus are made, and stay
until the focus is 1.25 times as far, so a focus pacing the edge of one does not
make and drop it again. ``dome_proxy( radius, rim, top )`` is the dome: a
convex solid with a vertical side, half an ellipse over it, and a floor 0.3 m
below the position. Rays are cast at it, as at any hull.

A body added to the world hits the ground and the trunks; the rocks beyond the
focus's reach are not there to be hit. ``oglc-terrain`` builds its avatar this
way (``terrain_view.make_avatar``), with the procedural or DEM height function
as the ground.

Tile colliders
~~~~~~~~~~~~~~

A streamer keeps some tiles that it is not drawing: a coarse parent, so it can
show it again when the camera pulls back, and siblings until the memory budget
needs their space. Left in the physics world, those tiles form a second
surface under the drawn one.
``OpenGLContext.loaders.tiles3d.physics_colliders.TerrainColliders`` connects
its ``on_drawn`` method to the runtime's ``on_drawn`` hook and holds colliders
for exactly the tiles on screen.

Road colliders
~~~~~~~~~~~~~~

A road is a centreline and a cross-section, and a baked world stores both in
its :doc:`tileset extras <roads>`.
``OpenGLContext.physics.road.RoadColliders`` sweeps them into one surface at
one resolution, cuts it into chunks, and keeps the chunks near the car in the
physics world:

.. code-block:: python

   from OpenGLContext.physics.road import RoadColliders
   road = RoadColliders(physics_world, course.centreline, course.road_profile(),
                        closed=True, bank=course.bank)
   road.update(car_position)                # once a frame

Chunks are 120 m long (``chunk``), and those within 260 m along the road on
either side of the car are kept (``reach``).

``bank`` is the road's lean at each centreline point, as a fraction. A baked
world writes it beside the centreline (:ref:`banked corners <banking>`). Pass
it for any banked road: a flat collider under a banked road puts the car
through the surface on the inside of every corner and above it on the
outside. ``widening`` gives the extra carriageway width at each point, in
metres, for stretches built wider than the rest of the road.

The chunks are cut from one road. The frames are swept once for the whole
centreline and each chunk takes its own slice (:ref:`circuits, and roads built
a stretch at a time <circuits>`), so neighbouring chunks meet exactly and
share the same ring of vertices. ``closed=True`` says the road is a circuit,
so the seam between the last point and the first is joined like any other.
That matters on a race circuit, where the start line is usually at that seam.

Barriers on bridges
~~~~~~~~~~~~~~~~~~~

A bridge deck or a causeway has nothing beside it but what it crosses.
``barriers`` takes the stretches of road that are carried, as ``(from, to)``
distances in metres along the centreline (the form a baked world writes
them in), and puts a wall along both edges of each:

.. code-block:: python

   road = RoadColliders(physics_world, course.centreline, course.road_profile(),
                        closed=True, bank=course.bank, barriers=course.edges())

The drawn structure has a barrier at these edges. Without a matching collider,
the car goes through the railing and off the deck. The collider wall is the
drawn barrier's footprint, extended to the barrier's full height
(``OpenGLContext.scenegraph.roadworks.barrier_wall``). It is solid: the gaps in
a railing are there to see through, not to drive through. Leave bores
(tunnels) out of ``barriers``; a tunnel has hillside on both sides.

:ref:`HeightFieldColliders <fieldphysics>` does the same job for ground stored
as a height field. With road colliders and height-field colliders, a game can
turn tile colliders off entirely, as ``glisteel`` does.

.. _physics-props:

Props
~~~~~

A boulder beside the road is drawn from a tile, but its collider must not
come from the tile, or the car drives through the rock when the tile behind
it changes resolution. ``OpenGLContext.physics.props.PropColliders`` reads the
:ref:`prop records <roads-props>` a baked world carries. It adds colliders for
the props within reach (default 220 m) and removes the ones out of reach. A
world has hundreds of boulders, and the broad phase pays for every body it
holds.

.. code-block:: python

   from OpenGLContext.physics.props import PropColliders
   obstacles = PropColliders(physics_world, world.props)
   obstacles.update(car_position)           # once a frame

A prop's collider is the simple shape its record names, at the size the
record gives, not its render mesh; a triangle mesh per rock costs both the
broad phase and the narrow phase. ``Prop.shape`` is one of:

- ``box`` - an obstacle: a boulder, a barrier, a broken-down car. The car
  cannot pass through it.

- ``dome`` - something to drive or walk over, such as a stone lying in the
  grass. The collider is a sphere as wide as the stone, sunk until its top is
  level with the stone's top, so a wheel rides over it and a walker steps onto
  it. As a box, the same stone would be a kerb across the hillside. A stone
  more than twice as tall as its radius has its sphere resting on the ground,
  ``2 * radius`` tall.

A world typically has thousands of stones and hundreds of boulders, and they
need different reaches: a boulder must stop a car from a long way off, while a
stone only matters under the wheel. Use two ``PropColliders``, one for each
table, each with its own ``reach``.

A baked world names its props by channel in its tileset's ``extras``: a
channel of hundreds as a list of prop records, and one of tens of thousands --
the loose stone -- as ``{"table": "stones.npz", "count": n}``, a binary table
beside the tileset (``scenegraph.props.props_table``), since the ``extras`` is
parsed by every reader of the world. ``PropColliders.baked`` reads either form
from the tileset's directory or URL and stands the colliders up:

.. code-block:: python

   from OpenGLContext.loaders.tiles3d import fetch
   from OpenGLContext.physics.props import PropColliders

   base = fetch.dir_of(tileset_path)
   boulders = PropColliders.baked(physics_world, extras, 'props', base)
   stones = PropColliders.baked(physics_world, extras, 'stones', base, reach=40.0)

``OpenGLContext.loaders.tiles3d.props.baked_props`` is the reader on its own.
A table named outside the tileset's reach is refused, as every file a world
names is (:doc:`untrusted`).

.. _physics-joints:

Joints, compound shapes and pair rules
--------------------------------------

A joint holds a body to another body, or to the world, so that it moves only
the way the joint lets it. Each kind is one call on the service, which returns a
``Joint``:

.. code-block:: python

   door = physics.add_hinge(leaf, frame, anchor=(0.0, 1.0, 0.5), axis=(0, 1, 0),
                            limits=(0.0, 1.6))
   rotor = physics.add_hinge(fan, anchor=(6, 4, 0), axis=(0, 1, 0), motor=(4.0, 30.0))
   link = physics.add_ball(lower, upper, anchor=(1.0, 6.0, 0.0))
   drawer = physics.add_slider(box, cabinet, axis=(1, 0, 0), limits=(0.0, 0.4),
                               motor=(0.5, 40.0))
   rod = physics.add_distance(bob, to_anchor=(0.0, 6.0, 0.0), length=2.0)

   rotor.drive(-4.0, 30.0)                     # a new speed and the most torque
   rotor.motor                                 # (-4.0, 30.0)
   door.remove()

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - What it holds
   * - ``add_hinge(body, to, anchor=, axis=, limits=, motor=)``
     - ``body`` turns against ``to`` about ``axis`` through ``anchor``;
       ``limits`` stop the angle, in radians from where it starts; ``motor`` is
       a speed in radians a second and the most torque, in newton-metres
   * - ``add_ball(body, to, anchor=)``
     - ``body`` and ``to`` turn freely about the point ``anchor``
   * - ``add_slider(body, to, axis=, limits=, motor=)``
     - ``body`` slides against ``to`` along ``axis`` and does not turn;
       ``limits`` in metres from where it starts; ``motor`` in metres a second
       and newtons
   * - ``add_distance(body, to, anchor=, to_anchor=, length=)``
     - the point ``anchor`` on ``body`` stays ``length`` metres from
       ``to_anchor`` on ``to``; the anchors default to the bodies' centres and
       ``length`` to the distance between them

``body`` and ``to`` are bodies or the nodes of bodies; ``to`` left out is the
world. Anchors and axes are world coordinates as the bodies stand when the
joint is made, and each body carries them from then on. Bodies a joint holds do
not collide with each other unless ``collide=True``. Removing either body
removes its joints, and ``joint.alive`` says whether it is still in the world.
A joint travels to the world as a command, as a body's changes do, so it works
in ``inline`` and ``thread`` mode alike. The world
reports no events of its own for joints. :doc:`tutorials/physics/physics_joints`
hangs a pendulum and a chain, turns a motor and slides a drawer.

The service makes these from ``omi_physics.joints`` (``HingeJoint``,
``BallJoint``, ``SliderJoint`` and ``DistanceConstraint``). The others there,
``UniversalJoint``, ``TwoAxisHingeJoint`` (a steered, sprung wheel) and
``MotorJoint``, and a joint's angle read back, are reached through
``physics.run``:

.. code-block:: python

   from omi_physics.joints import TwoAxisHingeJoint

   self.physics.run(lambda world: world.add_joint_constraint(TwoAxisHingeJoint(...)))

A collider may be several shapes in one body: ``model.Shape.compound`` places
each at an offset in the body's frame, and the body's mass is shared among
them by volume. A ``cylinder`` has flat ends and narrows to a cone where
``radiusTop`` is 0.

``world.set_pair_rule(rule)`` decides, each step, which pairs collide and
how: ``rule(a, b)`` answers False to let them pass through each other, None
for their materials, or a ``model.ContactParameters`` (restitution and the
speed below which nothing bounces, friction in two directions, a surface
speed, slip, softness and error correction). ``world.set_force``,
``set_torque``, ``set_exact_rotation`` and ``set_sleep`` push, spin and rest
one body. The omi_physics README has the details.

.. _physics-x3d:

X3D rigid bodies
~~~~~~~~~~~~~~~~

An X3D document's ``RigidBodyCollection`` is an omi_physics world of its own
(``OpenGLContext.physics.x3drigid``), stepped once a frame on the engine's
clock: its bodies, their collidables as shapes and compounds, X3D's six joints
on the joints above, and its ``CollisionCollection``\ s and routed ``Contact``
nodes as a pair rule. A ``CollisionSensor`` reports touches without stepping
anything. What each node does, and the units of its fields, are in
:ref:`x3d-rigid-bodies`.

.. _physics-debug:

The debug overlay
-----------------

``physics.show_proxies(True)`` draws each body's collision proxy as a green
wireframe over the scene, and ``show_proxies(False)`` takes it out. The overlay
is ``OpenGLContext.physics.debugdraw.PhysicsDebugDraw`` over the render
thread's copy of the world; it follows the bodies as they move.

``PhysicsDebugDraw`` can draw more of a world that a program owns: a bit-flag
mask selects collision proxies, broad-phase AABBs, contact points and normals,
joint connections (from each body to the anchor it carries), and each body's
velocity, acceleration and angular-velocity vectors. Angular velocity is drawn at
the body's corners, so opposite corners point opposite ways and the rotation is
easy to see. Sleeping bodies are drawn in a different colour.

.. rst-class:: technical

``PhysicsDebugDraw`` builds an ``IndexedLineSet`` with per-vertex colour each
frame, so it renders in both the legacy and the core profile. Flags:
``PROXIES | AABBS | CONTACTS | VELOCITY | ACCELERATION | ANGULAR | SLEEP |
JOINTS``.

.. _physics-demos:

Demos
-----

``oglc-physics-events`` is an installed command that shows every use of
:ref:`events <physics-events>` in one yard. ``CollisionYard``, the object that
holds it, takes a ``Physics`` and an ``Audio`` and is driven by a test with
neither a window nor a sound device:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Key
     - What it shows
   * - ``d``
     - Crates dropped on the floor, each landing thudding at a level set by
       ``speed``
   * - ``c``
     - Caps the frame rate at 20 fps; every landing still thuds
   * - ``l`` / ``L``
     - A ball thrown at each pane of glass, hard or gently. The left pane
       breaks after the solve, on ``impulse``; the right one before it,
       through a contact filter, and the ball carries on through
   * - ``m``
     - Mends the glass
   * - ``space``
     - A hitscan shot from the camera, a ``raycast`` and an impulse; a crate it
       hits is knocked away and pings
   * - ``w``
     - Puts a weight on the pressure plate. The plate is a trigger whose
       ``enter`` and ``exit`` handlers keep what is on it, and the door is a
       kinematic body ``drive`` raises while the plate is occupied and lowers
       when it is not

``oglc-audio-demo`` drops balls that thud where they land, from the same events
(:doc:`audio`). The rest are scripts in ``tests/tutorials/``, each a page in the
tutorials. The test suite also runs each one as a visual-regression test: it
exits after a set number of frames, captures the frame, and compares it with a
reference image.

- The stairs series, from :doc:`tutorials/physics/physics_stairs` to
  :doc:`tutorials/physics/physics_stairs_tuning`: one scene, and a few lines
  more in each.

- :doc:`physics_room_drop.py <tutorials/physics/physics_room_drop>` - objects fall
  into a room and stack; scenery as static bodies and ``show_proxies``.

- :doc:`physics_bounce.py <tutorials/physics/physics_bounce>` - a row of balls with
  restitution from 0 to 1.

- :doc:`physics_friction.py <tutorials/physics/physics_friction>` - boxes on ramps,
  showing the friction at which they start to slide.

- :doc:`physics_gravity_zones.py <tutorials/physics/physics_gravity_zones>` - a planet
  with point gravity.

- :doc:`physics_triggers.py <tutorials/physics/physics_triggers>` - sensor volumes and
  their ``enter`` and ``exit`` handlers.

- :doc:`using_collisions.py <tutorials/physics/using_collisions>` - balls that
  flash as hard as they landed.

- :doc:`physics_events.py <tutorials/physics/physics_events>` - the
  ``oglc-physics-events`` yard, opening on a scene already struck.

- :doc:`physics_joints.py <tutorials/physics/physics_joints>` - a hinged pendulum,
  a chain of ball joints, a hinge's motor and a slider.

- :doc:`physics_cook_view.py <tutorials/physics/physics_cook_view>` - cooks a collider
  and draws it over the mesh.

- :doc:`physics_navigate.py <tutorials/physics/physics_navigate>` - a first-person
  walk past walls, through a doorway, and up stairs and a ramp, with
  ``follow(view='eyes')``.

- :doc:`physics_stress.py <tutorials/physics/physics_stress>` - performance as the
  number of bodies grows, and ``physics.backend``.

- :doc:`using_physics.py <tutorials/physics/using_physics>` - a cannon game in its
  context's world, with kinematic bodies, a trigger and a wind. Its rules also
  run on a standalone ``Physics`` stepped by hand, which is how they are tested.

- The :doc:`Characters on Land <tutorials/character/character_run>` tutorials
  run, jump and walk a rigged character over land.

The :doc:`Add physics to a scene <tutorials/physics/physics_getting_started>` tutorial
walks the first of these. :doc:`navmesh` builds a navigation mesh from the same
collision world.
