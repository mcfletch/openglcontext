Physics & Collision, Explained
==============================

.. rst-class:: introduction

OpenGLContext ships a small, fast, game-style rigid-body physics engine that
runs in real time *alongside* the scenegraph. It integrates gravity and drag,
resolves collisions between primitives and meshes, supports triggers, gravity
zones and joints, and drives a first-person character controller — all while
the render tree, culling, shadows and picking stay untouched. The data model
is **not** a private format: it is the `OMI glTF physics extension family
<https://github.com/omigroup/gltf-extensions>`__, so real Godot/Blender
physics assets import with no translation layer and your scenes round-trip
back out to glTF. The indented technical notes point at the code.

.. _model:

The data model is OMI glTF physics
----------------------------------

Every concept in the engine is an OMI concept. Rather than invent a
``RigidBody`` node and map it onto glTF at the loader, the OMI schema *is* the
in-memory model — the loader, the nodes and the simulation all speak the same
structure.

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
     - global gravity *and* per-volume gravity zones
     - ``model.Gravity``
   * - ``OMI_physics_joint``
     - limits + drives between bodies
     - ``model.Joint``, ``joints.*``

.. rst-class:: technical

The structures live in ``omi_physics/model.py`` with the OMI spec defaults.
The reader/writer is ``omi_physics/omi_gltf.py``; ``load_document()`` parses a
glTF's extension blocks into these structures and ``export_extensions()``
writes them back — a near-identity round-trip. A future
``KHR_physics_rigid_bodies`` reader drops onto the *same* structures.

**Object characteristics** are just OMI motion fields: an immobile Earth is
``type:"static"``; weight is ``mass × |g|``; the centre of gravity is
``centerOfMass``.

.. _engine:

How the simulation runs
-----------------------

The engine follows the standard real-time recipe (Catto/Box2D, Gaffer's *Fix
Your Timestep*):

- **Semi-implicit (symplectic) Euler** integration — energy-stable at trivial
  cost.

- **Fixed timestep with an accumulator** decoupled from render fps; the render
  pose interpolates the last two states, so motion is smooth and deterministic.

- **Broad phase**: a dynamic AABB tree with fattened boxes, filtered by
  collision groups, culls the O(N²) pair explosion.

- **Narrow phase**: analytic tests for primitive pairs; **GJK + EPA** for
  convex↔convex and convex↔triangle (dynamic-vs-static mesh).

- **Solver**: sequential impulses (projected Gauss-Seidel) with warm starting
  and split-impulse position correction; restitution and Coulomb friction
  combine per the OMI material modes. Contacts partition into **islands**;
  settled bodies **sleep**.

.. rst-class:: technical

State lives in a flat structure-of-arrays (``world.py``) beside the tree,
synced to ``Transform`` nodes only at step boundaries. The per-stage kernels
sit behind a ``backend.py`` seam with two implementations: ``NumpyBackend``
(vectorized CPU) and ``GLComputeBackend`` (``glcompute.py``), which runs the
per-body force and position integration as GL 4.3 compute shaders over the
same columnar arrays — fused into one dispatch when a step has no collision or
joints, so the intermediate velocity never leaves the GPU. It is ~2.4× faster
than numpy at 10:sup:`5` movers.

.. rst-class:: technical

The default ``auto`` policy runs on numpy and hands off to the GPU only once
the awake-body count crosses ``gpu_threshold`` (10k) — below that, numpy wins
because transfer overhead outweighs the tiny per-body integrate — with
hysteresis on the way back down and a numpy fallback where GL 4.3 compute is
absent. ``OPENGLCONTEXT_PHYSICS_BACKEND=numpy|gpu|auto`` overrides. The GPU
computes in float32, so trajectories match the CPU backend within tolerance
rather than bit-for-bit. The broad phase, narrow phase, and solver still run
on the CPU; a full GPU-resident loop (LBVH broad phase, graph-colored/XPBD
solver) is the next step. ``tests/physics_stress.py`` toggles backends live
with the ``b`` key.

.. _physics-authoring:

Adding physics to a scene
-------------------------

The demos build scenes with the ``physics.demo.DemoScene`` helper, which
mirrors a scenegraph ``Transform`` with a ``PhysicsBody`` the world drives:

.. code-block:: python

   from OpenGLContext.physics.demo import DemoScene
   scene = DemoScene()                       # default gravity 9.81 down
   scene.add_box(size=(20,1,20), position=(0,-0.5,0), dynamic=False)  # floor
   ball = scene.add_sphere(radius=0.5, position=(0,6,0), material='rubber')
   # each frame:
   scene.advance(dt)                         # steps the world, writes back Transforms

Under the hood a ``PhysicsBody`` binds an OMI ``motion``/``collider`` to a
``Transform``; the world owns the transform while the body is a dynamic awake
mover and hands it back when the body sleeps or is kinematic.

.. _cooking:

Cooking collision shapes from a mesh
------------------------------------

Most authored geometry has no hand-made collider, so ``cookery.cook_shape()``
derives one from an arbitrary vertex array: a best-fit ``primitive``, a
``convex`` hull (default for movers), a ``decompose`` compound of convex
pieces for concave movers, or a ``trimesh`` triangle-soup (default for static
world geometry). The ``physics-cook`` CLI bakes these into a glTF so import is
free.

.. rst-class:: technical

Convex hulls and approximate convex decomposition are in ``hull.py`` (no scipy
dependency); results cache on the vertex array. The ``physics_cook_view.py``
demo overlays the cooked proxy on the render mesh so you can see the fit.

.. _streamed:

.. _roadcolliders:

Colliding with a world that streams
-----------------------------------

A streamed world's geometry is *level-of-detail* geometry: the same ground at
whatever resolution the streamer picked for the distance it is at, and that
resolution changes as a camera moves. Turning it into colliders is fine for a
walker and wrong for anything fast, because two resolutions of one curve are
the better part of a metre apart and the surface *steps* under the wheels
every time the streamer refines — which at racing speed is indistinguishable
from hitting a wall in the middle of an open road.

Two things follow, and both are about building the collider from *the thing*
rather than from a drawing of it.

**The set of colliders is the set of drawn tiles.** A streamer keeps tiles it
is not drawing — a coarse parent so it can be shown again the moment the
camera pulls back, siblings until the budget wants their space — and left in
the physics world they are a second surface under everything.
``TerrainColliders.on_drawn`` is wired to the runtime's ``on_drawn`` hook and
holds exactly what is on screen.

**What a vehicle drives on is built from the road, not the tile.** A road is a
centreline and a cross-section, and a baked world carries both in its
:doc:`tileset extras <roads>`. ``OpenGLContext.physics.road.RoadColliders``
sweeps them into one surface at one resolution, cut into chunks and held near
the car:

.. code-block:: python

   from OpenGLContext.physics.road import RoadColliders
   road = RoadColliders(physics_world, course.centreline, course.road_profile(),
                        closed=True, bank=course.bank)
   road.update(car_position)                # once a frame

``bank`` is the road's lean at each centreline point, which a baked world
writes beside the line (:ref:`banked corners <banking>`). It is not optional
decoration: a flat collider under a superelevated road is a surface the car
falls through on the inside of every corner and stands on the outside of.

**The chunks are cut out of one road, not built as separate ones.** The frames
are swept once for the whole centreline and each chunk takes its own slice
(:ref:`circuits, and roads built a stretch at a time <circuits>`), so two
neighbouring chunks meet exactly and the ring they share is the same ring.
``closed=True`` says the road is a circuit, which is what makes the seam the
same as anywhere else on it — worth having where a start line is, since a
circuit's is usually right there.

**And a deck needs its edge.** Beside a bridge or a causeway there is nothing
but the thing it was built to cross, so ``barriers`` takes the stretches that
are carried — as ``(from, to)`` metres along the centreline, which is how a
baked world writes them — and puts a wall along both edges of each:

.. code-block:: python

   road = RoadColliders(physics_world, course.centreline, course.road_profile(),
                        closed=True, bank=course.bank, barriers=course.edges())

The structure is *drawn* with a barrier for exactly this reason, and one that
is drawn and not collided with keeps nothing on anything: the car goes through
the railing and off the deck. The collider's wall is the drawn barrier's
footprint carried to its full height
(``OpenGLContext.scenegraph.roadworks.barrier_wall``) — solid, because what
the holes in a railing are for is seeing through, not driving through. A
*bore* is carried too and gets none: what is beside a tunnel is the hillside
it is driven through.

Its sibling :ref:`HeightFieldColliders <fieldphysics>` does the same for
ground carried as a field. Between them a game can turn tile colliders off
entirely, which is what ``glisteel`` does.

.. _physics-props:

Things standing in the world
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Everything else standing in the world is collided the same way.** A boulder
on the verge is drawn from a tile and must not be *collided* from one, or it
is a rock the car drives through at the moment the tile behind it swaps.
``OpenGLContext.physics.props.PropColliders`` reads the :ref:`prop records
<roads-props>` a baked world carries and stands up the ones within reach,
taking down the ones behind — a world's boulders are hundreds of bodies and
the broadphase pays for every one it holds:

.. code-block:: python

   from OpenGLContext.physics.props import PropColliders
   obstacles = PropColliders(physics_world, world.props)
   obstacles.update(car_position)           # once a frame

A prop's body is the shape the prop says it is, at the size it says it takes
up, rather than the mesh it is drawn as: a triangle soup per rock costs the
broadphase and the narrow phase both for a difference nobody driving past at
forty metres a second can see. ``Prop.shape`` picks between the two:

- ``box`` — a thing that stops you: a boulder, a barrier, a broken-down car.
  What a car needs from one is that there is no way through.

- ``dome`` — a thing you go *over*: a stone lying in the grass, which is part of
  the ground rather than an obstacle in it. A sphere as wide as the stone, sunk
  until its top stands where the stone's does, so a wheel rides over it and a
  walker steps onto it. The same stone as a block is a kerb across the hillside.

A world's loose stone is thousands of domes where its boulders are hundreds of
boxes, and the two want different reaches — a boulder has to stop a car from a
long way off, a stone only has to be there where the wheel is. So they are two
``PropColliders`` over two tables rather than one over a merged one.

.. _walking:

Walking any scene
-----------------

Walking is a capability of **every interactive context**, not something a
particular viewer implements.
``OpenGLContext.move.physicswalk.PhysicsWalkMixin`` is mixed into
``ViewPlatformMixin``, so any context that has a camera can be asked to hand
it to an avatar instead. It costs nothing until it is asked for: every physics
import is inside a method, so a context that never enables it never imports
the physics package at all.

.. code-block:: python

   class MyWorld( BaseContext ):
       def OnInit( self ):
           self.sg = load_my_world()
           self.setupPhysics( enable=True )    # binds 'g', and starts walking

Two navigators want the camera and only one may have it. While walking, the
avatar owns ``context.platform`` and the free-fly movement manager is unbound;
switching back rebinds it where the avatar left the view standing. If both ran
at once the camera would snap back on every key release.

It is a run-time toggle rather than a start-up choice on purpose: a viewpoint
that drops the avatar inside geometry must never be a trap. Press :kbd:`g` to
fly out, and :kbd:`g` again to resume walking from wherever you got to.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it does
   * - ``setupPhysics( enable=False )``
     - Make walking available; bind the toggle key; optionally start walking. Returns
       whether it *is* walking — False when there was nothing walkable, which is not
       an error.
   * - ``enablePhysics( on )``
     - Switch between walking and free-fly, leaving the camera where it is.
   * - ``stepPhysics( dt=None )``
     - Advance the avatar one frame and put the camera where it ended up. Call from
       ``OnIdle``. ``dt`` defaults to wall-clock since the last step, clamped — a
       stall is not a licence to teleport through a wall.
   * - ``buildPhysicsWorld()``
     - **The seam.** Returns ``(world, (lo, hi))``, or None if nothing is walkable.
       The default cooks one static collision mesh from ``self.sg``; a context with a
       world of its own — a terrain heightfield, a level format that ships its
       collision — overrides this and never touches ``sg``.
   * - ``characterCapabilities( scale )``
     - The avatar's size, and the speeds it starts with. Override to make it
       something other than roughly a person. The :doc:`movement mode <navigation>`
       in force retunes the walk, run, fly and swim speeds as it drives, so those are
       what the mode says rather than what was set here; the proportions, the jump
       and the crouch stay the body's.
   * - ``spawnAvatar( lo, hi, caps, viewpoints )``
     - Stand the avatar somewhere it can walk out of — see below.
   * - ``moveAvatarToViewpoint( vp )``
     - Put the avatar where a ``Viewpoint`` looks from, facing where it faces.
       Safe-bound, and it starts *flying* if the viewpoint is aerial, since falling
       out of the shot is not what asking for that view meant.
   * - ``resolvePhysicsStep()``
     - Correct the avatar's pose once the character has solved its own step, and
       before the camera is taken from it — where a host whose ground is not in the
       collision world puts it back on the ground. Empty by default.
   * - ``getNavigationPlatform()``
     - What the declared movement modes drive: the avatar while walking, the camera
       otherwise.

.. _physics-heightfield:

Ground that is not in the collision world
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A landscape is the case the seams above exist for.
``OpenGLContext.move.terrainwalk.TerrainWalkMixin`` is the same capability
with a different ground: the avatar, the declared modes and the keys are the
ones every other program here uses, but the surface is a :ref:`HeightField
<terrain-heightfield>` and the obstacles are a field of cylinders — both
answered analytically. A four-kilometre landscape would be millions of
triangles as a collision mesh, and asking a height field how high the ground
is costs the same wherever you stand.

It fills in three of the seams and adds nothing to the frame loop:
``buildPhysicsWorld()`` hands the character a world with nothing in it,
``spawnAvatar()`` stands it on the ground under the camera the scene placed
(every point of a height field is standable, so there is nothing to search
for), and ``resolvePhysicsStep()`` lifts it to the surface and pushes it out
of the trunks after each step. The surface is a *floor* rather than a rail, so
a jump rises and an arrival from the air falls; trunks stop a walker and not a
flier, since flying is noclip. ``oglc-forest`` is this, and so is anything
else built on ``scenegraph.terrain``.

The avatar is sized to the world
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A viewer opens anything from a bolt to a city, and neither a stride nor
gravity means anything until they are in the same units as the model. The
avatar is built at **1/40 of the world's longest side**
(``physicsAvatarScale``), and the declared :doc:`movement modes <navigation>`
are re-declared at that same scale by ``applyMovementModes()``, so a stride is
in the same units as the model it is taken through.

Finding somewhere to stand
~~~~~~~~~~~~~~~~~~~~~~~~~~

The middle of a model is very often solid — a statue, thick walls, no floor at
all. ``spawnAvatar()`` therefore samples: authored camera viewpoints first
(they are curated open spots, and the first supplies the heading), then the
footprint centre, then rings outwards. Each candidate is kept only if the
avatar lands grounded and unstuck, and scored by how many of the four
horizontal directions it has room to move into, preferring the most open and,
among equals, the most central. A fully open spot is taken at once. If nothing
is walkable anywhere, the avatar goes to the centre regardless — somewhere is
better than nowhere, since flying out is one keypress and an unplaced avatar
has no pose for the camera to take at all.

.. rst-class:: technical

The clearance probe places the whole capsule an arm's length along each
direction and depenetrates it, which catches a wall the avatar's centre line
would miss. It is a placement test and not a swept move, so a barrier thinner
than the capsule is transparent to it, and its reach is a fixed margin rather
than one scaled to the avatar — on a small model it therefore reports "open"
more readily than it should.

.. _character:

The character controller & safe binding
---------------------------------------

Navigation uses a kinematic capsule with move-and-slide: tiered speed
(walk/run/sprint/crouch), jump when grounded, fly/noclip, step-up over small
ledges, and sliding on steep slopes — configured by a non-OMI
``CharacterCapabilities`` node. Crucially, on every viewpoint bind it runs
**safe placement**: depenetrate from any overlapping geometry, then snap the
base onto the floor, so a camera authored low or inside a wall *never* leaves
the user stuck in the ground. If no free space is found it enters fly rather
than wedging.

A fall is caught however fast it arrives
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Contact is **discrete**: each step places the capsule and then resolves
whatever it overlaps. A step that carries the capsule clean past a floor
leaves nothing overlapping, and nothing overlapping is nothing to be stopped
by — a fall from three or four storeys does exactly that at any ordinary frame
rate. So a frame is advanced in **pieces short enough that the capsule cannot
cross its own extent** in one of them. The two axes get different allowances
because the capsule is taller than it is wide, so an ordinary walk is not
substepped at all while a fall is stepped finely for exactly as long as it is
fast.

**How much work that can ever be is calculated, not chosen.**
``CharacterCapabilities.terminalVelocity`` (55 m/s by default, about what a
person reaches) caps the fall, and the ceiling on substeps follows from it:
whatever the capsule is allowed to reach is what the stepping is sized for, so
the two cannot drift apart. A fixed ceiling is a number nobody can check —
raise the fall speed past what it allows and a step outruns collision again,
silently and only at speed. Setting ``terminalVelocity`` to 0 lets a fall
accelerate without limit and gives up the guarantee along with it;
``max_substeps()`` reports that rather than returning a reassuring number.

The other half is which way a contact pushes. Depth against a triangle is
**how far the capsule reaches past the face**, resolved to the side the
capsule is on — not the distance to the nearest point on it. Measuring the
nearest point looks right while the capsule is barely touching and is exactly
wrong once it is not: a hard landing puts the lower cap below the floor, that
cap is then the nearest, and pushing toward it drives the character down
through the surface it just hit while reporting no ground. The side is taken
from the capsule rather than from the triangle's winding, because a triangle
soup does not promise one — and taking it from the capsule is also what makes
a ceiling push down.

Speed is along the ground, not along the horizon
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The move direction is **projected onto the surface underfoot** before it is
used, so a run up a ramp covers the same metres per second as a run along the
flat and the climb is the vertical part of that. Moving horizontally instead
makes the capsule penetrate the slope and be pushed back out along its normal,
whose horizontal component opposes the motion, so the pace falls away as the
ramp steepens — a walkable ramp then feels like wading. The step-down snap
that keeps the capsule on the surface is likewise applied *vertically only*,
since the seating that finds it also travels along the normal and would drag
the capsule back downhill on every step of a climb.

What counts as ground is ``maxSlope``, everywhere. Standing, seating, and
stepping up all ask the same question, so a face too steep to walk cannot be
stood on, snapped onto, or stepped up — without which a cliff is climbable one
``stepHeight`` at a time by anything moving fast enough.

**A step is mounted in one motion, and owes back the difference.** Getting
onto a step means moving the capsule's *centre* past the edge — about a
radius, and it has to happen in one go, because a capsule stopped against the
riser is a radius behind it and a shorter probe never reaches over. That
single motion is further than a frame of running covers, so a staircase taken
one step per frame is climbed faster than the same distance on the flat, and
faster still the better the frame rate. What a step advanced beyond its
frame's due is therefore recorded and taken back out of the frames that
follow, a little at a time so the capsule never stalls: stairs are climbed at
running pace, whatever the frame rate.

Jump fires when the player meant it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A jump refused because ``grounded`` happened to be false on that one frame is
the commonest complaint about a first-person controller, and it is worst where
it is most noticed: running. A capsule at speed over a step, a ramp lip or a
seam between two colliders leaves the ground for a frame or two at a time, and
every press landing in one of those frames is swallowed with no feedback at
all. Two windows fix it, both in seconds so they hold at any frame rate:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Capability
     - Default
     - What it does
   * - ``coyoteTime``
     - 0.12 s
     - A jump is still allowed for this long after walking off something.
   * - ``jumpBuffer``
     - 0.12 s
     - A jump asked for this soon before landing fires on landing rather than being
       dropped.

Both forgive *falling*, never jumping: a capsule that left the ground under
its own power has no coyote time, so there is no free double jump, and a
buffered press is spent once. Set either to 0 to switch it off. A refusal on
any other ground — crouching, ``canJump`` off — is a refusal rather than a
delay, and is not buffered.

**A rising capsule is never grounded**, whatever is beneath it. When nothing
touched the capsule during a step it looks ``GROUND_PROBE`` (5 cm) below
itself for floor, which is what keeps a walker attached over the small gaps a
step opens. One frame after a jump the capsule has climbed only ``vy × dt``,
and on a fast machine that is *less* than the probe reaches — so the launch is
snapped straight back down and its velocity zeroed in the frame it started.
The faster the machine the more jumps vanish, and because frame times vary it
takes some presses and not others. The capsule also still touches the floor it
is leaving, so the contact test says "ground" as well; neither answer applies
to something on its way up.

.. rst-class:: technical

``character.py`` holds the controller; ``move/physicsplatform.py``'s
``PhysicsViewPlatform`` drives a context camera from it. See the
``physics_navigate.py`` demo.

.. _physics-debug:

The debug overlay
-----------------

Physics bugs are visual, so a wireframe overlay draws, per a bit-flag mask:
collision **proxies**, broad-phase **AABBs**, **contact** points and normals,
**joint** connections, and — to make motion legible — per-body **velocity**,
**acceleration**, and **angular-velocity** vectors. The spin vectors are drawn
at the body's corners so opposite corners point opposite ways, making rotation
visible at a glance. Sleeping bodies are colour-coded.

.. rst-class:: technical

``debugdraw.PhysicsDebugDraw`` builds an ``IndexedLineSet`` (per-vertex
colour) each frame, so it renders in both the legacy and core profiles. Flags:
``PROXIES | AABBS | CONTACTS | VELOCITY | ACCELERATION | ANGULAR | SLEEP |
JOINTS``.

.. _physics-demos:

Demos
-----

Every feature ships a runnable demo in ``tests/`` that doubles as its
visual-regression test (auto-exit + screenshot capture):

- ``physics_room_drop.py`` — objects fall into a room and stack; the core engine
  + debug overlay.

- ``physics_bounce.py`` — a row of balls, restitution 0…1.

- ``physics_friction.py`` — boxes on ramps; the slide threshold.

- ``physics_gravity_zones.py`` — a point-gravity planet.

- ``physics_triggers.py`` — sensor volumes and events.

- ``physics_joints.py`` — pendulum, chain and a motor.

- ``physics_cook_view.py`` — cook a collider and compare it to the mesh.

- ``physics_navigate.py`` — first-person walk through walls, a doorway, stairs
  and a ramp.

- ``physics_stress.py`` — scaling under load.

The :doc:`Add physics to a scene <tutorials/physics_getting_started>` tutorial
walks through building the first of these from scratch.
