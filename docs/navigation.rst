Movement Modes & Navigation
===========================

.. rst-class:: introduction

A **movement mode** is one way of moving through a scene: walking, flying,
swimming, or first-person mouse-look. Each mode is a scenegraph node with its
own speeds and its own key bindings. A context lists the modes it offers on
its ``ContextDefinition``, and a ``NavigationManager`` chooses which mode is
in force each frame. Because the modes are nodes, a settings screen can list
and edit them without knowing the application, and a game can retune a mode
by setting a field.

This page also covers the examine gestures (orbit, pan and dolly), which
every interactive context has without declaring any modes.

.. _modes:

Declaring the modes
-------------------

The modes are in ``OpenGLContext.move.modes``. Each is a ``PROTO`` like any
other node, so it can be written into a parsed file, held in an ``SFNode``
field, and watched for changes.

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
     - Its own fields (default)
     - Moves by
   * - ``WalkMode``
     - ``walkSpeed`` (3.0), ``runSpeed`` (6.0)
     - gravity and collision, with a jump
   * - ``FlyMode``
     - ``flySpeed`` (8.0), ``boostSpeed`` (32.0)
     - three axes, ignoring gravity and geometry
   * - ``FPSMode``
     - ``WalkMode``'s, with ``capturePointer`` on
     - walking, steered by the pointer
   * - ``SwimMode``
     - ``swimSpeed`` (2.0), ``buoyancy`` (0.9), with ``capturePointer`` on
     - three axes, while submerged

Every mode also has ``name``, ``enabled``, ``bindings``,
``capturePointer``, ``turnRate`` (2.0), ``turnAcceleration`` (1.0),
``sensitivity`` (0.003) and ``invertLook``. The four modes above also have
``lookRate`` (1.0). Speeds are in scene units per second, ``turnRate`` and
``lookRate`` in radians per second, and ``sensitivity`` in radians of turn
per pixel of pointer motion.

Each mode declares its own typed fields. One game's swim speed is 3 and
another's is 10, and in both it is an ``SFFloat`` on ``SwimMode``, so the
field system supplies validation, defaults and serialisation.

The mode sets the speed. A mode passes its speed to the character controller
with every frame's ``set_move``, ``set_fly_move`` or ``set_swim_move`` call,
and the body moves at that speed. A speed changed on the :doc:`settings
screen <overlayui>` is written to the live mode node, and the next step uses
it, with no restart. Code that drives a platform directly, without a mode,
passes no speed, and the body keeps the speed it was built with. Crouching is
the exception: it belongs to the body, so ``crouchSpeed`` overrides the mode's
speed.

Chosen modes and imposed modes
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

There are two kinds of mode:

- A user-selected mode, such as walk, fly or first-person, is one that
  ``NavigationManager.cycle()`` steps through.
- A world-imposed mode overrides ``enter_when(platform)`` to return true
  while it applies. ``SwimMode`` returns true while ``platform.submerged`` is
  set. An imposed mode is never part of the cycle. It takes over while its
  condition holds and hands back to the chosen mode afterwards.

The game sets the condition. ``platform.submerged`` says the avatar is in a
liquid; which volumes are liquid, and which part of the body must be in one,
is for the game to decide. ``PhysicsViewPlatform`` provides two positions to
test: ``camera_position()`` for the eye and ``feet_position()`` for the
bottom of the body. They differ by the eye height, and the difference matters
when entering or leaving a volume, because the eye is often above a surface
the feet are below.

Each mode sets up the body
~~~~~~~~~~~~~~~~~~~~~~~~~~

Whether the avatar falls, floats or swims is a property of the body, not of
the velocity it is given. A mode that only set a velocity would fly into the
floor. When a mode takes over, it calls ``applyTo(platform)`` to put the
body into the state it needs:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Mode
     - Puts the body into
   * - ``WalkMode``, ``FPSMode``
     - on its feet: gravity, ground contact and jumping
   * - ``FlyMode``
     - noclip: no gravity and no collision
   * - ``SwimMode``
     - swimming: it collides, and is pulled down by the fraction of gravity its
       ``buoyancy`` leaves

The platform methods are optional. Most platforms are a plain camera with no
body, and every mode works with one of those unchanged.

Swimming
~~~~~~~~

``SwimMode`` captures the pointer and steers with the same mouse-look as the
other modes (``MovementMode._mouseLook``). A player's sensitivity and
inverted-look settings therefore mean the same thing walking and swimming.

Forward is the direction of the gaze, including up and down, through
``PhysicsViewPlatform.set_swim_move``. Walking flattens movement onto the
ground plane, so that looking down does not push the avatar into the floor.
Swimming does not, so a swimmer reaches the surface or the bottom by looking
at it. Strafing stays level whatever the gaze, and the up and down keys hold
depth while the swimmer looks elsewhere.

Swimming is not flying. Flying is noclip, and a swim built on it would let a
player leave a pool through its wall. ``SwimMode.buoyancy`` is the fraction
of gravity that pushes back up: 1.0 hangs in place, 0.0 sinks, and a value
above 1.0 rises. It reaches the physics through
``set_swim(True, buoyancy=...)``.

.. _navigation-bindings:

Key bindings and modifiers
--------------------------

A ``KeyBinding`` node has a ``command`` as the mode names it, a ``label`` for
a settings window to show, the ``keys`` that trigger it, and an optional
``modifier`` of ``shift``, ``ctrl`` or ``alt``.

.. code-block:: python

   from OpenGLContext.move import modes

   walk = modes.WalkMode(name='walk')
   walk.bindings = list(walk.bindings) + [
       modes.KeyBinding(command='lookup', label='Look up',
                        keys=['<up>'], modifier='ctrl'),
   ]

A binding with a modifier fires only while that modifier is held. A binding
without a modifier loses its key only while another binding in the same mode
claims that key with a modifier that is down. So :kbd:`ctrl`\ +\ :kbd:`↑`
tilts the view without also walking forward, while :kbd:`shift`\ +\ :kbd:`w`
still walks, because no binding claims :kbd:`w` with shift.

For a rebinding screen, ``NavigationManager.binding_table()`` returns
``(mode name, binding)`` for every command, and ``rebind(mode, command,
keys)`` assigns new keys to one. The change takes effect at once, because
modes look up a command's keys each time they sample input. The
:ref:`key-binding page <overlayui-bindings>` of the overlay UI is built on
these calls and saves the result.

.. _navigation-input:

Sampling input
--------------

A controller that acts on key events acts once per event. Holding one key and
tapping another then loses whichever event the handler did not expect, and
"jump while running" has to be handled as a special case.
``OpenGLContext.events.inputstate.InputState`` records key presses, key
releases and pointer motion as they arrive. A mode reads it once per frame.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Call
     - Returns
   * - ``held(*names)``
     - whether any of these keys is down now
   * - ``pressed(*names)``
     - whether any was pressed since the last call. Reading consumes the press,
       so a jump fires once per press
   * - ``axis(positive, negative)``
     - +1, −1 or 0 from two opposed sets of keys. Holding both gives 0
   * - ``modifiers(name)``
     - the shift/ctrl/alt triple recorded when that key was last pressed
   * - ``mouse_delta()``
     - pointer motion since the last call, then resets

.. rst-class:: technical

``ViewPlatformMixin`` feeds the sampler from the keyboard and pointer events
every backend already sends, so no backend-specific code is needed. Pointer
events carry an absolute position and mouse-look needs a change in position,
so the difference is taken there. The first event sets the origin and reports
no motion, so the pointer entering the window does not jerk the view.

.. _context:

What the context does
---------------------

A context that declares no ``movementModes`` keeps whatever movement manager
it had. A context that declares them gets a ``NavigationManager`` and drives
it once a frame:

.. code-block:: python

   def OnIdle(self, *args):
       self.updateNavigation(dt)          # settle the mode, give it the frame
       return 1

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - Purpose
   * - ``getNavigation()``
     - the manager, or None when no modes are declared
   * - ``getNavigationPlatform()``
     - the platform the modes drive. ``PhysicsWalkMixin`` defines it: the walking
       avatar when there is one, otherwise the view platform. A game with a
       different controller overrides it, and the manager switches to the new
       platform when the return value changes. See :ref:`Walking any scene
       <walking>`
   * - ``updateNavigation(dt)``
     - runs one frame
   * - ``setPointerCapture(capture)``
     - grabs or releases the pointer. Returns False where the backend cannot
   * - ``suspendPointerCapture(suspend)``
     - releases the pointer while an overlay needs it, and grabs it again after

The mode in force is published on ``contextDefinition.movementMode``, an
``SFNode``. A HUD, a settings screen or an animation state machine can watch
that field instead of polling.

A platform driven by the modes needs ``set_move``, ``set_fly_move``,
``turn``, ``look`` and ``jump``. ``ViewPlatform`` and ``PhysicsViewPlatform``
both have them.

.. _pointer-capture:

Pointer capture
~~~~~~~~~~~~~~~

While a mode whose ``capturePointer`` field is set is in force, the pointer
is grabbed. Mouse-look needs unbounded motion: a visible cursor stops at the
edge of the screen, and the view stops turning with it. The GLFW backend
hides the cursor and switches on raw, unaccelerated motion where the platform
supports it, so that the angle of a turn does not depend on how fast the
mouse moved. The grab is applied only when capture is switched on or off,
not every frame. On a backend that cannot capture, the view turns until the
pointer reaches the window edge.

Two things make mouse-look work, and both come from ``ViewPlatformMixin``
rather than from the mode:

- The pointer is grabbed through the backend's ``setPointerCapture``. The
  mix-in is listed before the backend in every shipped context, so the call
  passes down the MRO to the backend.
- The backend reports pointer motion by calling
  ``recordPointerMotion(x, y)`` as it happens.

Motion is not taken from the pick pipeline. A move delivered as a pick event
arrives only after the selection pass resolves it, is dropped when the
pointer is over nothing, and never arrives with ``pickEnabled`` off. Every
backend reports motion directly. How each makes the motion unbounded
differs: a relative-motion mode under SDL, a grab under GLFW and Qt, and
warping the pointer back to the middle of the window under GLUT, Tk and wx.
:ref:`What every backend offers <backend-capabilities>` lists them.

``recordPointerMotion`` takes coordinates with the pick point's origin:
pixels from the bottom left, with y counting upward. A backend whose window
system counts y downward, as GLFW does, flips y before calling it.

An overlay panel needs the same pointer for clicking. Opening one calls
``suspendPointerCapture(True)``, and closing the last one gives the pointer
back to the mode. Pointer motion is suspended as well. The backend reports
motion straight to the sampler, not through the event queue, so the overlay
cannot stop it by holding back events; without the suspension the view would
keep turning behind the open panel. The position is still tracked while
capture is suspended, so the movement across the panel does not arrive as
one jump when capture resumes. See :ref:`overlayui-input`.

.. _keyboard-navigation:

Navigating without declared modes
---------------------------------

A context that declares no modes still moves. The :py:mod:`ViewPlatform
<OpenGLContext.move.viewplatform>` and :py:mod:`ViewPlatformMixin
<OpenGLContext.move.viewplatformmixin>` classes provide keyboard navigation:
the arrow keys walk or fly, and Alt with the arrow keys pans or slides. They
also provide the examine gestures below.

.. _examine:

Examining: orbit, pan and dolly
-------------------------------

Every interactive context also has three mouse gestures for looking at an
object rather than moving through the scene. They need no declaration: any
context that mixes in ``ViewPlatformMixin`` has them.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Gesture
     - Does
   * - Right-drag
     - Orbits the camera about the point under the cursor
   * - Middle-drag
     - Pans: the pivot and the camera slide across the view together, so the
       point under the cursor stays under it
   * - Wheel
     - Moves the camera toward or away from that point, by 20% of the distance
       per notch

The pivot is the world point the click landed on. A click that hits nothing
uses the centre of the scene's bounding sphere. If the camera is inside those
bounds, it uses a point a little ahead of the camera instead, so that the
camera does not swing around the far side of a building it is standing in.
``Context.examineCenter`` chooses the pivot, and an application can override
it.

The orbit is a turntable. Horizontal motion swings the camera about the
world's up axis. Vertical motion raises and lowers it, and stops just short
of the pole. These two rotations add no roll, so the horizon stays level and
the view never turns upside down. A camera that was deliberately rolled keeps
its roll. Dragging the height of the window turns the camera half a turn, at
the same rate across the whole window and in both directions.

The camera keeps its aim. The pivot is rarely at the centre of the screen, so
turning the camera to face it would make the view jump when the button went
down. Instead the gesture records the angle between the view direction and
the pivot when the drag begins, and keeps it. The view starts moving from
where it was.

``OpenGLContext.move.orbit.TurntableOrbit`` does the arithmetic. It holds no
GL and no events: it takes a camera, a pivot and pixel coordinates, and
returns a new position and orientation. ``ExamineManager`` drives it from the
events, and ``MovementManager.commandBindings`` names the three buttons, so
an application rebinds them there. To change the behaviour, override
``ExamineManager.OnBuildOrbit``. Any object with ``rotate(x, y)`` and
``cancel()`` methods can take the orbit's place.
``OpenGLContext.move.trackball.Trackball`` is a free-spinning arcball: it
does not keep the horizon level, and it can turn a model end over end.

The :doc:`viewer <viewer>` describes these gestures as a user meets them, and
:doc:`multiview` describes the per-view gestures of a window with several
views.

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
     - yes, in walk mode. The modes move the character controller and the
       camera follows
   * - twig-bb (BSP map viewer)
     - walk, fly, first-person, swim
     - yes
   * - ``oglc-ui-demo`` (``bin/ui_demo``)
     - walk, fly, first-person
     - declared, so the overlay demo has modes to show
   * - ``oglc-forest`` (the forest demo)
     - first-person, walk, fly
     - yes. The modes move an avatar standing on a height field; see
       :ref:`Terrain <terrain-heightfield>`

``OpenGLContext.move.modes.walk_fly_modes(scale=1.0)`` returns the walk and
fly modes. ``oglc-view`` and any application embedding the :ref:`viewing
component <viewer-embedding>` declare these; ``oglc-ui-demo`` declares its own.
``scale`` multiplies the speeds, because a viewer frames anything from a bolt
to a city and no one walking speed suits both. A walking context passes the
same scale it sizes its avatar by (``physicsAvatarScale``), and twig-bb
converts from map units. A viewer keeps the free-fly navigator for its
non-walking mode. The two never drive the camera at the same time: the
free-fly navigator is unbound while the modes are in charge.

``walk_fly_modes(scale, first_person=True)`` puts ``FPSMode`` ahead of the
pair. The manager starts in the first selectable mode, so a session then
starts in mouse-look. This suits a world the player is inside, such as a
landscape or an arena. :kbd:`m` cycles to the walk mode, which turns with
:kbd:`q` and :kbd:`e` and leaves the pointer free.

The viewer scales the speeds to the scene it framed
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Speeds are in scene units per second. The flying speed of 8 that suits a
model crawls across a city-sized 3D Tiles dataset: fifteen kilometres takes
half an hour at that rate. When it mounts a scene, the viewer multiplies the
speeds of its own modes by the framed radius divided by
``sceneviewer.MOVEMENT_REFERENCE_RADIUS`` (80 units), and never by less than
1. Crossing any dataset then takes about twenty seconds, and a model-sized
scene keeps the default speeds. Flying the 41 MB Toronto tileset (framed
radius 7.9 km) this way moves at 785 units a second.

The mode objects are kept and only their speeds change, so the mode in force,
the bound keys and anything watching ``movementMode`` are unaffected. The
speed sliders on the settings screen widen to match. Modes a host application
declared itself are not scaled.

Settings screens
----------------

The :doc:`Overlay UI <overlayui>` provides settings screens for all of this:
a page per mode generated from the mode's own fields, and a key-binding page
built from ``binding_table()``. The key-binding page saves to the per-user
app-data directory through ``OpenGLContext.move.bindingstore``.
