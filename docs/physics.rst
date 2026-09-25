Physics & Collision
===================

.. rst-class:: introduction

OpenGLContext simulates rigid bodies in real time beside the scenegraph. The
simulation applies gravity and drag, resolves collisions between primitive
shapes and meshes, and supports triggers, gravity zones and joints. A
first-person character controller walks on the same collision world. The
render tree, culling, shadows and picking work the same with or without it.

The simulation itself is the ``omi_physics`` package, a dependency of
OpenGLContext. OpenGLContext adds the scenegraph binding, walking for any
context, colliders for streamed worlds, and a debug overlay. The data model is
the `OMI glTF physics extension family
<https://github.com/omigroup/gltf-extensions>`__, so physics authored in Godot
or Blender imports without conversion, and a scene exports back to glTF. The
indented technical notes point at the code.

.. _physics-authoring:

Adding physics to a scene
-------------------------

The demos build their scenes with ``OpenGLContext.physics.demo.DemoScene``.
Each ``add_*`` call creates a scenegraph ``Transform`` and a ``PhysicsBody``
that the world moves:

.. code-block:: python

   from OpenGLContext.physics.demo import DemoScene
   scene = DemoScene()                       # default gravity 9.81 down
   scene.add_box(size=(20,1,20), position=(0,-0.5,0), dynamic=False)  # floor
   ball = scene.add_sphere(radius=0.5, position=(0,6,0), material='rubber')
   # each frame:
   scene.advance(dt)                         # steps the world, writes back Transforms

A ``PhysicsBody`` binds an OMI ``motion`` and ``collider`` to a ``Transform``.
The world writes the transform while the body is dynamic and awake. While the
body sleeps or is kinematic, the world leaves the transform alone.

The :doc:`Add physics to a scene <tutorials/physics_getting_started>` tutorial
builds a scene like this step by step.

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
  convex against convex and convex against triangle (a moving body against a
  static mesh).

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

.. rst-class:: technical

The default policy, ``auto``, runs on numpy until the number of awake bodies
reaches ``gpu_threshold`` (default 10 000), and then switches to the GPU. Below
that count, the cost of transferring the data is larger than the per-body work
it saves. The world switches back to numpy when the count falls below 80% of
the threshold, and stays on numpy where GL 4.3 compute shaders are not
available. Set ``OPENGLCONTEXT_PHYSICS_BACKEND`` to ``numpy``, ``gpu`` or
``auto`` to override the policy. The GPU computes in float32, so its
trajectories match the numpy backend within a tolerance, not bit for bit. The
broad phase, narrow phase and solver run on the CPU with either backend. In
``tests/physics_stress.py``, the ``b`` key switches backends while the demo
runs.

.. _cooking:

Cooking collision shapes from a mesh
------------------------------------

Most authored geometry has no collider of its own.
``omi_physics.cookery.cook_shape()`` makes one from a vertex array, using one
of these strategies:

- ``primitive`` - the best-fitting box or sphere.
- ``convex`` - the convex hull.
- ``decompose`` - a compound of convex pieces, for concave moving bodies.
- ``trimesh`` - the triangles themselves, for static world geometry.
- ``auto`` (the default) - ``trimesh`` for static geometry and ``convex`` for
  moving bodies, changing to ``decompose`` when a moving body is very concave.

To add colliders to a glTF file ahead of time, run the ``physics-cook`` tool:

.. code-block:: bash

   python -m OpenGLContext.bin.physics_cook scene.gltf -o cooked.gltf

It gives every mesh node that has no physics body an ``OMI_physics_shape`` and
an ``OMI_physics_body``: a static ``trimesh`` by default, or a ``convex`` body
with ``--motion dynamic``. It works on ``.gltf`` JSON documents and leaves nodes
that already have a body unchanged. Without ``-o`` it overwrites the input.

.. rst-class:: technical

Convex hulls and approximate convex decomposition are in ``hull.py`` and do
not need scipy. Results are cached per vertex array. The
``physics_cook_view.py`` demo draws the cooked collider over the render mesh
so you can compare the fit.

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
   * - ``resolvePhysicsStep()``
     - Called after the character has solved its step and before the camera
       reads its pose. A host whose ground is not in the collision world
       corrects the avatar's pose here, for example by putting it back on the
       ground. Does nothing by default.
   * - ``getNavigationPlatform()``
     - Returns what the declared movement modes drive: the avatar while
       walking, the camera otherwise.

.. _physics-heightfield:

Ground that is not in the collision world
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OpenGLContext.move.terrainwalk.TerrainWalkMixin`` is walking for a
landscape. It uses the same avatar, movement modes and keys as any other
walking context, but the ground is a :ref:`HeightField <terrain-heightfield>`
and the obstacles are a field of cylinders (tree trunks). Both are tested
analytically, not as meshes. A four-kilometre landscape would be millions of
triangles as a collision mesh, while a height-field lookup costs the same
anywhere on it.

It overrides three of the methods above and adds no work to the frame loop:

- ``buildPhysicsWorld()`` gives the character an empty world.
- ``spawnAvatar()`` stands the avatar on the ground below the camera the scene
  placed. Every point of a height field can be stood on, so there is no
  search.
- ``resolvePhysicsStep()`` lifts the avatar to the surface and pushes it out
  of the trunks after each step.

The surface acts as a floor, not a rail: a jump rises, and an avatar arriving
from the air falls onto it. Trunks stop a walker but not a flier, because
flying has no collision. The ``oglc-forest`` demo uses this mixin, as does
anything built on ``scenegraph.terrain`` (see :doc:`terrain`).

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
record gives, not its render mesh. A triangle mesh per rock would cost both
the broad phase and the narrow phase, for a difference nobody driving past at
forty metres a second can see. ``Prop.shape`` is one of:

- ``box`` - an obstacle: a boulder, a barrier, a broken-down car. The car
  cannot pass through it.

- ``dome`` - something to drive or walk over, such as a stone lying in the
  grass. The collider is a sphere as wide as the stone, sunk until its top is
  level with the stone's top, so a wheel rides over it and a walker steps onto
  it. As a box, the same stone would be a kerb across the hillside.

A world typically has thousands of stones and hundreds of boulders, and they
need different reaches: a boulder must stop a car from a long way off, while a
stone only matters under the wheel. Use two ``PropColliders``, one for each
table, each with its own ``reach``.

.. _physics-debug:

The debug overlay
-----------------

``OpenGLContext.physics.debugdraw.PhysicsDebugDraw`` draws the simulation as a
wireframe overlay. A bit-flag mask selects what it draws: collision proxies,
broad-phase AABBs, contact points and normals, joint connections, and each
body's velocity, acceleration and angular-velocity vectors. Angular velocity
is drawn at the body's corners, so opposite corners point opposite ways and
the rotation is easy to see. Sleeping bodies are drawn in a different colour.

.. rst-class:: technical

``PhysicsDebugDraw`` builds an ``IndexedLineSet`` with per-vertex colour each
frame, so it renders in both the legacy and the core profile. Flags:
``PROXIES | AABBS | CONTACTS | VELOCITY | ACCELERATION | ANGULAR | SLEEP |
JOINTS``.

.. _physics-demos:

Demos
-----

Each demo is a script in ``tests/``. The test suite also runs each one as a
visual-regression test: it exits after a set number of frames, captures the
frame, and compares it with a reference image.

- :doc:`physics_room_drop.py <tutorials/physics_room_drop>` - objects fall
  into a room and stack; the core engine and the debug overlay.

- :doc:`physics_bounce.py <tutorials/physics_bounce>` - a row of balls with
  restitution from 0 to 1.

- :doc:`physics_friction.py <tutorials/physics_friction>` - boxes on ramps,
  showing the friction at which they start to slide.

- :doc:`physics_gravity_zones.py <tutorials/physics_gravity_zones>` - a planet
  with point gravity.

- :doc:`physics_triggers.py <tutorials/physics_triggers>` - sensor volumes and
  their events.

- :doc:`physics_joints.py <tutorials/physics_joints>` - a pendulum, a chain
  and a motor.

- :doc:`physics_cook_view.py <tutorials/physics_cook_view>` - cooks a collider
  and draws it over the mesh.

- :doc:`physics_navigate.py <tutorials/physics_navigate>` - a first-person
  walk past walls, through a doorway, and up stairs and a ramp.

- :doc:`physics_stress.py <tutorials/physics_stress>` - performance as the
  number of bodies grows.

The :doc:`Add physics to a scene <tutorials/physics_getting_started>` tutorial
builds the first of these from scratch. :doc:`navmesh` builds a navigation
mesh from the same collision world.
