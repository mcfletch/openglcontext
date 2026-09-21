Movement Modes & Navigation
===========================

.. rst-class:: introduction

A **movement mode** is one named way of moving — walking, flying, swimming,
first-person mouse-look — declared as a scenegraph node with its own speeds
and its own key bindings. A context lists the modes it offers on its
``ContextDefinition``, and one manager decides which is in force and gives it
the frame. Because the modes are nodes, a settings screen can enumerate and
rewrite them with no knowledge of any particular application, and a game can
retune a mode by setting a field rather than subclassing anything.

.. _modes:

Declaring the modes
-------------------

The modes live in ``OpenGLContext.move.modes``. Each is a ``PROTO`` like any
other node, so it can be written into a parsed file, carried in an ``SFNode``
field, and watched for change.

.. code-block:: python

   from OpenGLContext.contextdefinition import ContextDefinition
   from OpenGLContext.move import modes

   definition = ContextDefinition(movementModes=[
       modes.WalkMode(name='walk', walkSpeed=3.0, runSpeed=6.0),
       modes.FlyMode(name='fly', flySpeed=8.0),
       modes.FPSMode(name='fps', sensitivity=0.003),
       modes.SwimMode(name='swim', swimSpeed=2.0),
   ])
   MyContext.ContextMainLoop(definition=definition)

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Mode
     - Its own fields
     - Moves by
   * - ``WalkMode``
     - ``walkSpeed``, ``runSpeed``
     - gravity and collision, with a jump
   * - ``FlyMode``
     - ``flySpeed``
     - three axes, ignoring gravity and geometry
   * - ``FPSMode``
     - walk's, plus ``sensitivity`` and ``invertLook``
     - walking, steered by the pointer
   * - ``SwimMode``
     - ``swimSpeed``, ``buoyancy``
     - three axes, while submerged

Every mode also carries ``name``, ``enabled``, ``bindings`` and
``capturePointer``, and the ground-based modes carry ``turnRate`` and
``lookRate``. Speeds are in scene units per second, rates in radians per
second, and ``sensitivity`` in radians of turn per pixel of pointer motion.

Each mode declares *its own typed fields* rather than sharing a free-form
settings mapping: one game's swim speed is 3 and another's is 10, and both are
an ``SFFloat`` on ``SwimMode``. That buys validation, defaults and
serialisation from the field system.

**The speed travels with the move.** What actually scales a step is the
*character controller's* capability, so a mode passes its own figure down with
every frame's ``set_move``\  / \ ``set_fly_move``\  / \ ``set_swim_move`` and
the body moves at what the mode says. That is what makes the number on the
:doc:`settings screen <overlayui>` real: it is written onto the live mode
node, and the next step is taken at the new speed — no restart, and nothing to
keep in step by hand. A caller driving a platform directly, without a mode,
passes no speed and the body keeps whatever it was built with. Crouching is
the exception: it is a property of the body rather than of the way you are
moving, so ``crouchSpeed`` outranks the tier the mode asked for.

Chosen modes and imposed modes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Two kinds of mode share the base class. **User-selected** modes — walk, fly,
first-person — are what ``NavigationManager.cycle()`` steps through. A
**world-imposed** mode overrides ``enter_when(platform)`` to say "I apply
right now"; ``SwimMode`` does, returning true while ``platform.submerged`` is
set. An imposed mode never appears in the cycle — switching into swimming
while standing on dry land is not a thing a player wants — and it takes
precedence while its condition holds, handing the mode back afterwards.

**The condition is the game's to set.** ``platform.submerged`` says the avatar
is in a liquid; which liquids a world has, and which part of the body has to
be in one, is something only the game knows. ``PhysicsViewPlatform`` publishes
both readings a decision like that needs: ``camera_position()`` for where the
avatar looks from, and ``feet_position()`` for where its body ends. They
differ by an eye height, and for entering and leaving a volume that difference
is the whole question — the eye is the part of a body that is regularly
outside whatever the feet are standing in.

A mode also sets the state its movement assumes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Whether the avatar falls, floats or swims is a property of the *body* and not
of the velocity it is given, so a mode that only set a velocity would fly into
the floor. ``applyTo(platform)`` is where a mode puts the body into the state
it needs, and it is called when the mode takes over:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Mode
     - Puts the body into
   * - ``WalkMode``, ``FPSMode``
     - on its feet — gravity, ground contact, jumping
   * - ``FlyMode``
     - noclip: no gravity and no collision at all
   * - ``SwimMode``
     - swimming: *collides*, and is pulled by whatever fraction of gravity its
       ``buoyancy`` leaves

Swimming steers with the pointer, and moves where you look
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Entering water must not change how a player points themselves.** A scheme
that fell back to the turn keys the moment someone's feet left the floor would
take their aim away in the one place they most need it, so ``SwimMode``
captures the pointer and uses the same mouse-look every other mode does —
``MovementMode._mouseLook``, shared, so a player's sensitivity and their
inverted-look setting mean the same thing walking and swimming.

And *forward* means where you are looking, up and down included, through
``PhysicsViewPlatform.set_swim_move``. Walking flattens the move to the ground
plane and rightly so — leaning forward should not push you into the floor —
but under water that flattening leaves the surface and the bottom reachable
only by the dedicated keys, which is walking with the gravity turned off
rather than swimming. Strafing stays level whatever the gaze, because sidling
should not sink you, and the up/down keys remain for holding depth while
looking somewhere else.

**Swimming is not flying**, and conflating them is the easy mistake: a swim
implemented as noclip lets a player leave a pool through its wall.
``SwimMode.buoyancy`` is the fraction of gravity that pushes back up — 1.0
hangs where it is, 0.0 sinks like a stone, above 1.0 rises — and it reaches
the physics through ``set_swim(True, buoyancy=...)``.

Every platform is asked and none is required to answer: most are a plain
camera with no body under them at all, and a mode has to work against one of
those unchanged.

.. _navigation-input:

Input is sampled, not reacted to
--------------------------------

A controller bound to key *events* can only act once per event, so holding one
key and tapping another loses whichever the handler did not see — the reason
"jump while running" has to be special-cased in every application that wants
it. ``OpenGLContext.events.inputstate.InputState`` instead accumulates
key-down/key-up and pointer motion as they arrive, and a mode asks it once per
frame what is currently true.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Ask
     - Answers
   * - ``held(*names)``
     - is any of these down now
   * - ``pressed(*names)``
     - was any pressed since last asked — consumed by reading, so a jump fires once
       per press
   * - ``axis(positive, negative)``
     - +1/−1/0 from two opposed sets; holding both cancels
   * - ``modifiers(name)``
     - the shift/ctrl/alt triple recorded when that key was last pressed
   * - ``mouse_delta()``
     - pointer motion since the last call, then reset

.. rst-class:: technical

``ViewPlatformMixin`` feeds the sampler from the ordinary keyboard and pointer
events every backend already emits, so nothing backend-specific is needed.
Pointer events carry an absolute position and mouse-look wants a delta, so the
difference is taken there; the first event establishes the origin and reports
no motion, or entering a window would read as one violent flick of the view.

.. _examine:

Examining: orbit, pan and dolly
-------------------------------

Beside the movement modes, every interactive context has the three mouse
gestures for looking *at* something rather than moving through it. They need
no declaration: a context that mixes in ``ViewPlatformMixin`` has them.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Gesture
     - Does
   * - Right-drag
     - Orbits the camera about the point under the cursor
   * - Middle-drag
     - Pans: the pivot and the camera slide across the view together, so what is
       under the cursor stays under it
   * - Wheel
     - Moves the camera toward or away from that point, by 20% of the distance a
       notch

**What it orbits is what you touched.** The pivot is the world point the click
resolved to, so examining the thing you pointed at is the whole gesture. A
click that hit nothing falls back to the middle of the scene's own bounding
sphere — and to a point a little ahead of the camera when the camera is
*inside* those bounds, since orbiting the far side of a building you are
standing in is not what the gesture means. ``Context.examineCenter`` decides,
and an application with a better answer overrides it.

**The orbit is a turntable.** Horizontal movement swings the camera about the
world's up axis and vertical movement raises and lowers it, stopping just
short of the pole. Between them those two rotations introduce no roll, so the
horizon stays where the viewer put it and the view never comes out upside
down; a camera that was deliberately rolled keeps its roll rather than being
levelled. A drag the height of the window is half a turn, at one rate over the
whole window and the same rate in both directions.

**The camera keeps its aim.** The pivot is rarely the centre of the screen, so
a camera turned to face it squarely would jump as the button went down. The
gesture measures how far off the pivot the view was pointing when the drag
began and carries that through, so the view starts moving from where it
already was.

The maths is ``OpenGLContext.move.orbit.TurntableOrbit``, which holds no GL
and no events — it is handed a camera, a pivot and pixel coordinates and
answers a new position and orientation. ``ExamineManager`` drives it from the
events, and ``MovementManager.commandBindings`` is where the three buttons are
named, so an application rebinds them there. ``ExamineManager.OnBuildOrbit``
is the customisation point for different behaviour: anything answering
``rotate(x, y)`` and ``cancel()`` fits the slot, and
``OpenGLContext.move.trackball.Trackball`` is the free-spinning arcball
alternative, which trades the level horizon for the freedom to turn a model
end over end.

.. _navigation-bindings:

Bindings, and the modifier rule
-------------------------------

A ``KeyBinding`` node carries a ``command`` as the mode names it, a ``label``
for a settings window to show, the ``keys`` that trigger it, and an optional
``modifier`` of ``shift``, ``ctrl`` or ``alt``.

.. code-block:: python

   from OpenGLContext.move import modes

   walk = modes.WalkMode(name='walk')
   walk.bindings = list(walk.bindings) + [
       modes.KeyBinding(command='lookup', label='Look up',
                        keys=['<up>'], modifier='ctrl'),
   ]

A binding with a modifier needs that modifier held. A binding *without* one
loses its key only while another binding of the same mode claims that key with
a modifier that is currently down — which is what lets :kbd:`ctrl`+:kbd:`↑`
tilt the view without also walking forward, while :kbd:`shift`+:kbd:`w` keeps
walking because no binding claims :kbd:`w` with shift.

For a rebinding screen, ``NavigationManager.binding_table()`` returns ``(mode
name, binding)`` for every command, and ``rebind(mode, command, keys)`` points
one at different keys. It takes effect at once: modes resolve a command to
keys when they sample, not when they are built.

.. _context:

What the context does
---------------------

A context that declares no ``movementModes`` is untouched and keeps whatever
movement manager it had. One that declares them gets a ``NavigationManager``,
and drives it once a frame:

.. code-block:: python

   def OnIdle(self, *args):
       self.updateNavigation(dt)          # settle the mode, give it the frame
       return 1

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it is for
   * - ``getNavigation()``
     - the manager, or None when no modes are declared
   * - ``getNavigationPlatform()``
     - what the modes drive. Defined by ``PhysicsWalkMixin``: the walking avatar when
       there is one, the view platform otherwise. A game with a different controller
       overrides it, and the manager is re-pointed when the answer changes — see
       :ref:`Walking any scene <walking>`
   * - ``updateNavigation(dt)``
     - one frame
   * - ``setPointerCapture(capture)``
     - grab or release the pointer; returns False where the backend cannot
   * - ``suspendPointerCapture(suspend)``
     - hand the pointer back while an overlay wants it, and take it again after

The mode in force is published on ``contextDefinition.movementMode`` (an
``SFNode``), so anything that wants to know — a HUD, a settings screen, an
animation state machine — watches that field rather than polling.

A platform driven by the modes needs ``set_move``, ``set_fly_move``, ``turn``,
``look`` and ``jump``. ``ViewPlatform`` and ``PhysicsViewPlatform`` both have
them.

Pointer capture
~~~~~~~~~~~~~~~

A mode whose ``capturePointer`` field is set has the pointer grabbed for as
long as it is in force. Mouse-look needs unbounded motion: a visible cursor
stops at the edge of the screen and the view stops turning with it. The GLFW
backend disables the cursor and asks for raw, unaccelerated motion where the
platform has it — pointer acceleration is a desktop convenience that would
make how far a turn goes depend on how fast it started. The grab is applied
only when the answer changes, never once a frame, and a backend that cannot
capture simply keeps working with the view turning as far as the window edge.

An overlay is clicked with the same pointer, so opening one calls
``suspendPointerCapture(True)`` and closing the last one hands it back. **The
motion is suspended with it**: a backend that knows where the cursor went
reports it straight to the sampler through ``recordPointerMotion``,
deliberately, because mouse-look must not depend on the pick pipeline — which
means gating the event queue, all an overlay can do, would not reach it, and
the world would keep turning under the dialog the player is reading. The
position is still tracked while suspended, so the journey across the dialog is
not delivered as one flick on the way back.

``recordPointerMotion`` takes its coordinates in the **pick point's origin**:
pixels from the bottom-left, y counting *upward*. A backend whose windowing
system counts y downward (GLFW does) flips it before calling.

.. _viewers:

The shipped viewers
-------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Viewer
     - Modes
     - Driven by them
   * - ``oglc-view`` (``OpenGLContext.viewer``)
     - walk, fly
     - yes, in walk mode — the modes move the character controller and the camera
       follows
   * - twig-bb (BSP map viewer)
     - walk, fly, first-person, swim
     - yes
   * - ``bin/vrml_view``
     - walk, fly
     - declared only; its camera is still the older navigator
   * - ``oglc-ui-demo`` (``bin/ui_demo``)
     - walk, fly, first-person
     - declared, so the overlay demo has modes to show
   * - ``oglc-forest`` (the forest demo)
     - first-person, walk, fly
     - yes — the modes move an avatar standing on a height field, see :ref:`Terrain
       <terrain-heightfield>`

Walking and flying come from
``OpenGLContext.move.modes.walk_fly_modes(scale=1.0)``, which is what
``oglc-view`` and anything else embedding the :ref:`viewing component
<gltf-embedding>` declare; ``bin/vrml_view`` and ``oglc-ui-demo`` still
declare their own ``movement_modes()``. The ``scale`` parameter exists because
a viewer frames models from a bolt to a city and one walking speed cannot suit
both: a walking context passes the same scale it sizes its avatar by
(``physicsAvatarScale``), and twig-bb converts from map units. A viewer keeps
the free-fly navigator for its non-walking mode, and the two never both drive
the camera: the older manager is unbound while the modes are in charge.

**The viewer sizes the speeds to the scene it framed.** Speeds are scene units
a second, so the eight-a-second flight that suits a model is a crawl across a
city-sized 3D Tiles dataset — fifteen kilometres at that rate is half an hour,
and nothing streaming in as you move can be seen happening. On mounting a
scene the viewer scales its own modes by the framed radius over
``sceneviewer.MOVEMENT_REFERENCE_RADIUS`` (80 units), never below 1, so a
traverse of any dataset takes about twenty seconds and scenes at model scale
keep the speeds they have always had. The mode objects are kept and their
speeds rewritten, so the mode in force, the bound keys and anything watching
``movementMode`` survive; the speed sliders on the settings screen widen with
them, and modes a host declared itself are left alone. Flying the 41 MB
Toronto tileset (framed radius 7.9 km) this way is 785 units a second.

``walk_fly_modes(scale, first_person=True)`` puts ``FPSMode`` in front of the
pair, which is what makes mouse-look the mode a session *starts* in: the
manager takes the first selectable mode. That is the right default for a world
someone is inside — a landscape, an arena — where steering with the pointer is
what anyone arriving expects to find; :kbd:`m` cycles to the :kbd:`q`/:kbd:`e`
walk for anyone who would rather keep the pointer.

**A mouse-look mode needs two things from the context beyond the mode
itself**, and both are provided by ``ViewPlatformMixin`` rather than by the
mode: the pointer is grabbed through the backend's ``setPointerCapture``
(passed down the MRO, since the mix-in is listed *before* the backend in every
shipped context), and pointer motion is fed to the sampler by the backend
calling ``recordPointerMotion(x, y)`` as it happens. Motion is deliberately
*not* taken from the pick pipeline: a move delivered as a pick event arrives
only once the selection buffer resolves it, is dropped when the pointer is
over nothing, and never arrives at all with ``pickEnabled`` off — none of
which has anything to do with turning the view. Every backend reports it
directly; what each has to do to make the motion *unbounded* differs — a
relative-motion mode under SDL, a grab under GLFW and Qt, warping the pointer
back to the middle of the window under GLUT, Tk and wx — and :ref:`What every
backend offers <backend-capabilities>` says which does what.

A settings GUI over all of this — widgets, focus, skinning and a rebinding
page built from ``binding_table()`` — is built: see :doc:`Overlay UI
<overlayui>`. It generates a page per mode from the mode's own fields, and its
key-binding page saves to the per-user app-data directory through
``OpenGLContext.move.bindingstore``.
