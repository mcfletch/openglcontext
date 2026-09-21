HUD & developer overlay
=======================

.. rst-class:: introduction

A **HUD layer** draws over a live world and never takes an event: a reticule,
a health bar, an ammunition count, a line of text that fades. The **developer
overlay** is one of these, fed by registered providers, and it is where the
frame rate is now drawn. Both are drawn beneath any :doc:`overlay panel
<overlayui>` that is open, by the same batched renderer, in the same handful
of draw calls.

.. _difference:

A HUD is not a panel
--------------------

The :ref:`overlay stack <overlayui-input>` is modal: while a panel is up,
nothing under it hears anything. That is exactly right for a settings screen
and exactly wrong for a health bar. So the two are different things:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - 
     - HUD layer
     - Overlay panel
   * - Input
     - Never receives any
     - The top one takes it; a modal one stops the world hearing it
   * - Focus
     - None — nothing in it is focusable
     - Tab order, accelerators, an Enter default
   * - Drawn
     - Every frame, under the panels
     - When something is open, over the HUD
   * - Laid out
     - Every frame, because its values change
     - When it opens or the window resizes
   * - Placed
     - By anchor: a corner, an edge, the middle
     - Centred in the window

Every context has HUD layers, because every context has a developer overlay. A
context gains panels by mixing in ``OpenGLContext.ui.overlay.OverlayMixin``.

.. _hud-quickstart:

Putting a HUD on the frame
--------------------------

A layer is a tree of widgets, each carrying the corner it belongs in. Add it
to the context and it is drawn from the next frame on:

.. code-block:: python

   from OpenGLContext.ui.hudwidgets import (
       BarMeter, Crosshair, HUDGroup, HUDLayer, LampRow, MessageQueue, MiniMap,
       Readout,
       TextBlock,
   )

   self.health = BarMeter(label='HEALTH', value=100, maximum=100)
   self.ammo = Readout(label='AMMO', value='50', anchor='bottom-right')
   self.messages = MessageQueue(anchor='top', duration=4.0)

   self.hud = HUDLayer(children=[
       Crosshair(shape='cross', gap=5, length=7),        # anchored 'center'
       HUDGroup(anchor='bottom-left', spacing=4, children=[self.health]),
       self.ammo,
       self.messages,
   ])
   self.addHUDLayer(self.hud)

After that it is data: write ``self.health.value = 40`` and the meter turns
amber, ``self.messages.post('PICKED UP A SHOTGUN')`` and a line appears and
fades. Nothing has to be redrawn by hand, because the layer is measured and
painted afresh each frame.

.. _hud-demo:

Seeing it work
--------------

.. figure:: images/demos/hud_demo.jpg
   :alt: A reticule, two bar meters, a lamp row, a message, a mini-map and an ammunition read-out drawn over a dusk world of pillars

   ``python tests/hud_demo.py`` — one ``HUDLayer`` holding a game's whole screen
   furniture over a lit world, every element placed by the corner it names. A
   ``Crosshair`` in the middle, whose ``spread`` opens and closes on the clock
   the way a weapon's accuracy does; two ``BarMeter``\ s bottom left, one reading
   green and one amber because that is where each value sits against its own
   thresholds; a ``LampRow`` of five lives across the top with a ``MessageQueue``
   fading out underneath it; a ``MiniMap`` of the pillar ring with the player
   marked on it; a ``Readout`` bottom right, drawing a nine-slice icon beside its
   number; the key legend top right in a ``TextBlock``; and a ``DamageIndicator``
   washing the right-hand edge, which is the way the last hit came from. The
   meters sweep their whole range on a clock, so each threshold colour comes up
   in turn.

Nothing on that screen is interactive, and the world underneath hears every
event as though the HUD were not there. The keys fire the transient effects:
``x`` takes a hit, ``v`` puts a ``ScreenWash`` over the viewport, ``space``
puts a hit mark on the reticule, ``m`` posts a message, and ``alt-f`` brings
up the developer overlay — where the demo registers a section of its own
numbers, at the top of the plate.

The demo at its smallest is two widgets, which is enough to be worth having on
screen:

.. code-block:: python

   from OpenGLContext.ui.hudwidgets import BarMeter, Crosshair, HUDLayer

   # in OnInit, after the base class's
   self.health = BarMeter(label='HEALTH', value=64, anchor='bottom-left')
   self.addHUDLayer(HUDLayer(children=[
       Crosshair(shape='cross-dot', gap=5, length=8),
       self.health,
   ]))

   # and from then on, wherever the number changes
   self.health.value = 22          # red, from the meter's own thresholds

.. _anchors:

Placement is by anchor
----------------------

Health in one corner, ammunition in another, the reticule in the middle: no
row-and-column arithmetic describes that as well as naming the corner does.
Every HUD widget carries two fields:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Meaning
   * - ``anchor``
     - One of ``top-left``, ``top``, ``top-right``, ``left``, ``center``, ``right``,
       ``bottom-left``, ``bottom``, ``bottom-right``. Anything else is read as
       ``center``, so a typo puts the element somewhere visible.
   * - ``offset``
     - Pixels away from that anchor, **+x right and +y up**, so an offset always
       moves an element away from the corner it is anchored to whichever corner that
       is.

``HUDLayer.margin`` keeps everything clear of the window edge. A child with no
``anchor`` at all — an ordinary ``Row`` or ``Column`` — is given the whole
layer and lays itself out normally, so the ordinary layout containers work
inside a HUD.

Every pixel measurement here — margins, offsets, a reticule's gap, a meter's
height — is **at the reference font size** and is multiplied by the interface
scale, exactly as the skin's are. A HUD authored on a 1080p display is the
same size in the eye at 4K. See :ref:`Everything scales with the window
<scale>`.

.. _widgets:

The widgets
-----------

Crosshair — the reticule
~~~~~~~~~~~~~~~~~~~~~~~~

**The reticule belongs to the weapon, not to the game.** Everything about it
is a field, so a table of weapons names one of these each and switching weapon
is switching this node rather than branching in the drawing code.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Units
     - Default
     - Meaning
   * - ``shape``
     - 
     - ``cross``
     - ``cross``, ``dot``, ``cross-dot``, ``circle`` or ``none``. ``none`` is a real
       choice: some weapons aim down their own sights.
   * - ``gap``
     - px
     - 5
     - Clear space in the middle. The gap is the point of a crosshair: it leaves what
       is being aimed at visible.
   * - ``length``
     - px
     - 7
     - One arm.
   * - ``thickness``
     - px
     - 2
     - Arm width.
   * - ``dotSize``
     - px
     - 2
     - The centre dot, for the shapes that have one.
   * - ``spread``
     - px
     - 0
     - Extra gap from the weapon's current accuracy. Widens the reticule rather than
       moving it, so what the player sees is the size of the area a shot might land
       in.
   * - ``hitDuration``
     - s
     - 0.35
     - How long the hit mark stays up after ``crosshair.hit()``.
   * - ``hitSize``
     - px
     - 4
     - How big it is.

The shape is drawn from axis-aligned rectangles — four arms, or four arcs for
a circle — because that is what the overlay renderer draws, and at the few
pixels a reticule occupies the difference is invisible while the batch stays
one draw call.

BarMeter — health, armour, a charge
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A value against a maximum, coloured by where it sits against two thresholds:
``warnFraction`` (0.5) and ``criticalFraction`` (0.25) pick the skin's
``hudGood``, ``hudWarn`` and ``hudCritical``. Three colours rather than a
gradient, because what a player reads off a meter at speed is a state — fine,
low, about to matter — and a continuous ramp says none of those clearly.
Setting ``color`` overrides the thresholds entirely.

``barWidth``/``barHeight`` are its natural size; the track stretches to
whatever room the meter is given, so a meter in a stretched group stretches
with it. A ``label`` is drawn to its left and takes room from the track;
``showValue`` draws the number over it.

**A meter can react rather than merely update.** ``meter.flash(now)`` lights
the whole track and fades over ``flashDuration`` (0.35 s) from
``flashStrength`` (0.75). A number that changed silently in a corner nobody is
looking at is not feedback, and the flash is what makes the change something a
player notices out of the corner of an eye. *Whether* a change is worth
flashing about is the game's rule and not the meter's — health lost matters
and health gained from a pickup may not — so the game asks:

.. code-block:: python

   if value < float(meter.value):    # a drop, not a pickup
       meter.flash(now)
   meter.value = value

The whole track lights, not the filled part, so a meter that has just been
emptied still flashes: the moment health reaches nothing is the one a player
most needs to see.

.. _lamprow:

LampRow — a count that is seen rather than read
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A row of lamps, ``lit`` of ``count`` of them burning from the left.
``BarMeter`` and ``Readout`` both answer *how much* and a player has to read
them to find out; some counts cannot afford that. A racing start rig is the
case that names this widget — five lamps filling one a second, holding, and
going out — because a driver reads it with their eyes on the road, and a
numeral counting down would take them off it. A round counter, a life count
and a lap tally are the same shape of question.

.. code-block:: python

   self.lights = LampRow(anchor='top-center', offset=(0, -40))
   ...
   self.lights.count, self.lights.lit = 5, burning
   self.lights.visible = starting

``lit`` is clamped rather than checked, so a game may hand it whatever it is
counting without first working out whether the number fits. Every lamp is
drawn in a housing whether it burns or not, so a rig with nothing lit still
reads as a rig rather than as empty screen; a burning one gets a halo, kept
inside the spacing so two lit lamps stay two.

``lampSize`` (26) and ``gap`` (12) are its natural size. ``color`` recolours
the burning lamps and leaves the dark ones to the skin, which is what makes
the same widget a start rig here and a fuel warning elsewhere; without it a
burning lamp takes the skin's ``hudCritical``, which is red everywhere a start
rig exists.

DamageIndicator — which way the hit came from
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**The direction is what this adds.** How much health was lost is already on
the meter and in the number beside it; what a player cannot see, and must act
on within about a second, is *where the shooter is standing*. So a hit is
washed onto the screen edge the player would turn towards to face it.

.. code-block:: python

   indicator.hurt(bearing=-math.pi / 2, intensity=0.6, now=now)   # from the left

A bearing is radians from straight ahead, positive to the right, so ``+pi/2``
is directly to the right and ``pi`` is directly behind — which is the bottom
of the screen, because that is where a player looks for what they cannot see.
Each of the four edges takes the share of a hit that faces it, so the wash
*slides* from one edge to the next as an opponent circles rather than snapping
between them; a flicker at the corner would read as a fault in the game and
not as a shooter moving.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Units
     - Default
     - Meaning
   * - ``duration``
     - s
     - 1.1
     - How long one hit takes to fade to nothing. Long enough to be seen through the
       flinch of being shot, short enough that it is not still up when the player has
       already turned.
   * - ``thickness``
     - px
     - 56
     - How far in from the edge the wash reaches at full strength.
   * - ``steps``
     - 
     - 4
     - How many strips the wash is drawn from. It is a gradient rather than a band
       because a hard-edged block over the world reads as a rendering fault.
   * - ``capacity``
     - 
     - 8
     - The most shown at once. A firefight can ask for dozens and the ones underneath
       contribute nothing a player can see.

``intensity`` is 0 to 1 and an intensity of nothing draws nothing — a hit an
armour absorbed entirely is not a hit to flash about. Several hits are shown
at once and each fades on its own clock, so being caught in a crossfire looks
like being caught in a crossfire. ``clear()`` drops them all, which is what a
respawn wants: a fresh body is not still bleeding from the last one's wounds.

ScreenWash — a colour over the whole viewport
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The counterpart to ``DamageIndicator``, and what separates them is what each
has to say. That one has a *direction* to give and washes the
edge a player must turn towards. This one has none: it is for the states where
the *view itself* has changed rather than where something has happened in it —
being dead, being under water, the moment a screen fades.

.. code-block:: python

   wash = ScreenWash(colour=(0.65, 0.04, 0.04))
   wash.strength = 0.42        # driven per frame; 0 draws nothing at all

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - Units
     - Default
     - Meaning
   * - ``colour``
     - rgb
     - (1, 0, 0)
     - What colour the world is seen through.
   * - ``strength``
     - 0–1
     - 0.0
     - How solid it is, and the whole of the design decision. A wash a player can
       still read the room through is information; one they cannot is a curtain, and
       the only state that earns a curtain is one where there is nothing left to
       read.

A strength of nothing draws nothing rather than a transparent rectangle: this
covers the whole screen and is up on most frames of most games at zero, so
being switched off has to cost a comparison and not a draw. Drive ``strength``
per frame rather than switching it on at the event, so it can rise with
whatever it accompanies — a wash that snapped on ahead of the camera movement
it belongs to reads as a screen effect rather than as the thing that happened.

Readout — an icon and a number
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``label``, ``value`` and an optional ``icon`` (a ``NineSlice``, drawn at
``iconSize``). ``critical`` is the game saying “this one matters now” — the
last few rounds, the last seconds — and it is a flag rather than a colour so
the skin still decides what that looks like.

TextBlock — several lines in a corner
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The counterpart to ``Readout``, which is one line built from a label and a
value. This is prose the application composed itself — what is loaded and what
the keys do — and the lines are a field rather than one string with newlines
in it, so a caller can rewrite one of them. ``critical`` marks the whole block
as saying something has gone wrong.

.. code-block:: python

   caption = TextBlock(anchor='bottom-right', align='right',
                       lines=['model.glb', '[1/3] aerial'])

:doc:`oglc-view <viewer>`'s caption is one of these: see
``OpenGLContext.viewer.caption``. Note the corner — the developer overlay is
anchored top-left and grows *down* the left edge as sections are registered,
so a status line anywhere along that side is a status line written over it.

.. _minimap:

MiniMap — a route, and what is on it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A driver on an eight-kilometre circuit cannot see round the next bend and has
no idea how much of the lap is left. A map answers both, and it is the same
widget whether the route is a race circuit, a rally stage or a delivery round:
it takes a polyline in world XZ and a list of marks, and knows nothing about
either.

.. code-block:: python

   self.map = MiniMap(anchor='bottom-left', size=150)
   self.map.route = course.centreline            # (N,2) or (N,3): XZ is read
   self.map.marks = [(car.x, car.z, 'crosshair')]   # each names a skin colour

**The fitting is the whole of it.** The route is scaled to the box by
whichever axis needs it more and centred in the other, so it keeps its shape:
a map that stretches the circuit to fill its box is a map of a different
circuit. A mark outside the route's extent is clamped to the edge rather than
dropped, because a car that has left the road is somewhere and where it went
off is worth seeing.

A long route is thinned to ``detail`` segments. A circuit written down every
six metres is two thousand quads for a line nobody can see the corners of.

It is the one widget that draws something that is not axis-aligned, which is
what ``Renderer.segment(start, end, width, colour)`` is for: a thick line as a
single turned quad, in the same batch as everything else. A compass rose, a
trajectory or a radar sweep wants the same primitive.

MessageQueue — pickups, frags, warnings
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Newest first, each line carrying its own clock, so a warning posted with a
long life is not cut short by a pickup posted after it:

.. code-block:: python

   queue.post('YOU HAVE THE FLAG', duration=6.0)
   queue.post('PICKED UP A SHOTGUN')          # the queue's own duration

``duration`` is how long a line is shown and ``fade`` is how much of the end
of that is spent fading out; the fade arrives in the colour's alpha, so
nothing downstream has to know about time. ``capacity`` is how many are shown
at once — older ones are dropped when a new one arrives, because a HUD that
scrolls is a HUD nobody reads.

.. _hud-clock:

The clock
---------

Anything that fades, expires or flashes is driven by ``HUDLayer.tick(now)``,
which the context calls once a frame before drawing. Passing the time in
rather than reading a clock inside each widget is what makes all of this
testable — and what lets a game drive its HUD from its own simulation clock
rather than from the wall.

**One clock, and it must be the layer's.** The context ticks with
``time.monotonic()``, so a game that marks a hit with ``time.time()`` and lets
the layer expire it computes every fade from the difference between two clocks
— about fifty years. On screen that is a hit mark and a damage wash that never
go away, and an alpha of a hundred million. Give the widgets the same clock
the layer gets, and give it from one place:

.. code-block:: python

   def now():
       """The clock every reading on this HUD is taken against."""
       return time.monotonic()

.. code-block:: python

   queue.post('PICKED UP A SHOTGUN', now=100.0)
   layer.tick(101.0);  assert queue.entries(101.0)      # still up
   layer.tick(105.0);  assert not queue.entries(105.0)  # gone

.. _hud-debug:

The developer overlay
---------------------

One panel holding everything a developer wants to see and a player never
should, so that a game's HUD can be built out of game information only. It is
a HUD layer, so it can be left up while playing: it takes no input and blocks
nothing.

**It is fed by registered providers.** A provider is a callable returning
name/value pairs and knowing nothing about drawing, so a new subsystem appears
in the overlay by registering rather than by anyone editing the overlay:

.. code-block:: python

   context.debugOverlay.register('Map', lambda: [
       ('name', loaded.name),
       ('family', loaded.family),
       ('position', tuple(camera.position[:3])),
   ], order=40)

Values are formatted by the overlay, so a provider hands over whatever it has:
a float becomes ``0.33`` (and ``60`` rather than ``60.00``), a bool becomes
``yes``/``no``, a vector becomes its components, ``None`` becomes ``-``.
``order`` sorts the sections, low first; equal orders keep the order they
registered in. Registering a title twice replaces it, so a reloaded subsystem
does not grow a second copy of its section.

A provider that raises becomes an ``error`` row rather than taking the frame
down, and a provider with nothing to say is left out entirely rather than
drawn as an empty heading. This is diagnostic equipment: a diagnostic that
breaks the thing it is measuring is worse than none.

What ships with it
~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Section
     - Rows
   * - Frame
     - Frame rate (the *windowed median*, not the lifetime average), frame time in
       milliseconds, frames drawn, the viewport.
   * - Loop
     - Wall-clock cost of the whole main loop, and where it went — see :ref:`below
       <hud-loop>`. Left out by backends that run their own loop and never open an
       iteration.
   * - Render
     - Profile, and whether shadows, IBL, bloom, transmission, instancing and vsync
       are on; then what the last frame cost — shapes gathered, draw calls issued,
       and how many shapes collapsed into how many instanced groups.
   * - View
     - Camera position, and a character controller's grounded state, velocity and
       mode when there is one.

``physics_provider(lambda: world)`` is also supplied, for body and contact
counts, and ``simulation_provider(lambda: manager)`` for a background physics
thread (``OpenGLContext.physics.threaded.ThreadedPhysicsManager``) — the rate
it is achieving against the rate it asked for, its total ticks, and any it had
to drop. A thread that is not getting the turns it asked for produces a world
moving in slow motion, which is indistinguishable from wrong gravity or a
wrong timestep until those two numbers are side by side. Both take a callable
rather than the object because a world is replaced when the next level loads,
and a provider holding the first would report on it forever. Neither is
registered by default: a context does not necessarily have either.

**Triangle counts are deliberately absent.** The render pass does not know
them — a geometry node does — and instrumenting every ``render()`` in the
system to find out would cost more than the answer is worth. A number that is
not counted is not reported rather than guessed at. See
``OpenGLContext/passes/renderstats.py``.

.. _hud-loop:

When the frame rate says everything is fine and it is not
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**The frame rate answers a narrower question than it looks like it answers.**
``FrameCounter`` times the inside of ``OnDraw``, it is only told about frames
that produced a visible change, and the rate it publishes is a *median* over a
window — deliberately outlier-proof, so that a first-frame shader compile or a
synchronous model load does not drag the number down for ever. Each of those
is right for “how fast is the renderer”, and each of them hides a stutter.

A backend’s loop does more than draw. It pumps the window system’s events, it
runs ``OnIdle`` — which is where an application’s whole simulation usually
lives — and it waits for a redraw request. None of that is inside the frame
counter’s stopwatch, so an application can crawl visibly at a few updates a
second while the overlay reports sixty, with no number on the screen
contradicting the other.

``OpenGLContext.looptrace.LoopTrace`` measures the other thing: **wall-clock
time per loop iteration**, divided among named phases. Every context has one
as ``context.loopTrace``; the GLFW backend drives it from ``MainLoop`` and
``OnDraw`` divides its share further. The Loop section reports:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Row
     - What it says
   * - ``loop fps``
     - Iterations per second of wall clock — the rate the player’s hands feel. This
       disagreeing with ``fps`` above is the diagnosis: the renderer is keeping up
       and something outside it is not.
   * - ``loop ms``, ``worst ms``
     - Median and worst iteration in the window. A healthy median beside a worst ten
       times larger is a loop that stutters, which is what the median alone can never
       say.
   * - ``stalls``
     - How many iterations crossed the stall threshold, counted since the loop
       started so it outlives the window it happened in.
   * - ``last stall``
     - The phase that ate the most recent one, as ``idle 812ms``.
   * - ``poll``, ``repeats``, ``idle``, ``wait``, ``draw``, ``cascade``, ``render``
     - Mean milliseconds per iteration in each phase, worst first.

**Phases divide the iteration; they do not overlap it.** A phase is charged
only its own time and the time inside a nested phase belongs to the child, so
every phase of an iteration adds up to that iteration’s wall clock and the
largest is the culprit by construction. ``wait`` is bounded by
``drawPollTimeout``, so a large ``wait`` is a quiet loop and never a stalled
one.

An application should subdivide ``idle``. The engine’s phases can only ever
name it, because ``OnIdle`` is where an application’s frame goes — true, and
useless. ``context.tracePhase(name)`` opens a phase from anywhere, nests
inside whatever is already open, and answers a do-nothing context manager when
nothing is measuring, so the caller writes the ``with`` and not the branch:

.. code-block:: python

   def OnIdle(self):
       with self.tracePhase('character'):
           self.player.update(dt)
       with self.tracePhase('match'):
           self.arena.step(dt)

Those divide ``idle`` rather than adding to it, so ``idle``\ ’s own row falls
to whatever is left over. A phase that is always under a millisecond costs one
clock read and earns its place the first time it is not.

**Counting is always on** and costs a few clock reads per iteration. Reporting
is opt-in:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Effect
   * - ``OPENGLCONTEXT_STALL_MS``
     - What counts as a stall, in milliseconds; the default is ``50`` (twenty frames
       a second). Setting it also switches logging on — asking for a threshold is
       asking to be told when it is crossed. A value that is not a number is a
       warning and the default, never a failure to start.
   * - ``OPENGLCONTEXT_TRACE_STALLS``
     - Log every stall’s phase breakdown at ``WARNING``, keeping the default
       threshold.

.. code-block:: bash

   OPENGLCONTEXT_STALL_MS=40 python -m twig_bb
   WARNING OpenGLContext.looptrace: main loop stalled 912ms: idle 901ms, render 9ms, poll 1ms

Neither variable changes what a frame looks like, so both are inherited by a
subprocess capture rather than cleared with the rendering variables — a
diagnostic a subprocess silently dropped would be no diagnostic.

.. _stalltrace:

Recording a slow period, and reading it back
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The phase breakdown names a *subsystem*. It cannot name the code inside it,
and it never will: by the time the iteration closes, the stack that would have
said has already unwound. The overlay has the same limit from the other end —
it shows the present, and a stutter is something you want to look at
*afterwards*, from a recording.

``OPENGLCONTEXT_STALL_TRACE=<path>`` records one. ``OpenGLContext.stalltrace``
puts a watcher thread on the main thread’s Python stack, sampling it **only
while an iteration is already overrunning** — a profiler that runs during the
frames that are fine would be spending the one currency the question is about
— and writes a JSON-lines file:

.. code-block:: bash

   OPENGLCONTEXT_STALL_TRACE=/tmp/stalls.jsonl python -m twig_bb
   python -m OpenGLContext.stalltrace /tmp/stalls.jsonl

*\ *The unit is an *\ episode\ *, not a frame.*\ * Consecutive slow iterations
are gathered into one record, because “the game went unplayable for four
seconds” is one thing that happened, not two hundred, and a file with a line
per frame is a log rather than a diagnosis. A run of slow frames with the odd
good one in it stays a single episode.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - In each record
     - What it says
   * - ``at``, ``seconds``, ``iterations``, ``stalled``
     - When the slow period began, how long it lasted, and how much of it was
       actually slow.
   * - ``worst_ms``, ``mean_ms``, ``baseline_ms``
     - The worst and mean iteration, and **what the loop had been managing before it
       went wrong** — without which “slow” has nothing to be slow compared to.
   * - ``phases_ms``
     - The breakdown, averaged over the episode.
   * - ``functions``
     - **The answer.** Per function, the share of samples where it was running
       (``self``) and the share where it was anywhere on the stack (``cumulative``).
   * - ``hot``
     - The whole stacks that held the most samples — the evidence, and the route by
       which the expensive function was reached.
   * - ``context``
     - Every section of the developer overlay at the moment the episode opened, so
       the trace records the map, the player, the renderer’s counts and whatever the
       game registered, without anyone writing a second description that can drift
       from the first.
   * - ``samples``
     - How many were taken, and ``incomplete`` when the start of the episode fell out
       of the sampler’s buffer. A truncated record that does not admit it reads as
       the whole story.

**Report per function, not per stack.** One expensive function is usually
reached by a dozen routes and from a dozen lines; grouping only by whole stack
splits it across all of them, so something holding sixty per cent of a stall
reads as a dozen entries at five per cent and the trace looks like it found
nothing. ``functions`` undoes that fragmentation, and ``hot`` keeps the routes
as evidence:

.. code-block:: python

   where 28 samples were, by function:
         self    cum  function
        53.6%  53.6%  collide.py _closest_point_on_triangle
        10.7%  75.0%  collide.py capsule_triangle
        10.7%  10.7%  collide.py _closest_segment_segment

**An episode is written as it closes, and flushed**, so a run that ends in a
``kill -9`` keeps every episode before the last. A slow period is also cut and
written every few seconds even while it continues (the next part is marked
``continues``), because a session that ends *while* it is struggling is the
commonest way for one to end — and that final episode is the one worth having.

A path that cannot be written is a warning and a disabled journal. This is
diagnostic equipment: it does not get to be the reason a game will not start.

Showing and hiding it
~~~~~~~~~~~~~~~~~~~~~

:kbd:`Alt`+:kbd:`f` toggles it on every context;
``context.toggleDebugOverlay()`` does the same in code, and can be bound to
any key a game prefers.

``OPENGLCONTEXT_DISABLE_FPS_DISPLAY`` means what it always meant — no numbers
over my screenshot — and now means it here: the overlay **starts hidden**. The
key still brings it up, because a capture run is not the only thing that sets
the variable.

.. rst-class:: technical

``FrameCounter`` measures the frame rate and does not draw it: the provider
reads its number and the HUD puts it on screen. Drawing it from there would
mean ``glOrtho``/``glPushAttrib``, which mean nothing in a core profile.

.. _viewpinned:

Things pinned to the view
-------------------------

A first-person weapon is *not* HUD: it is geometry, it wants the scene’s
lighting and it should be occluded by the world. What it shares with the HUD
is that it must not move on screen. Put it on a transform, and write that
transform’s pose from the camera in ``placeViewAttachments``:

.. code-block:: python

   class Game(OverlayMixin, Context):
       def placeViewAttachments(self, pass_):
           "Called once the camera is settled, before any geometry is gathered."
           aim_at_camera(self.hand, self.getViewPlatform())

**The timing is the whole feature.** The render pass calls this from
``__call__``, after the view platform is settled and before the scene is
gathered — the only moment both are true. Posed from an idle callback or an
event handler instead, the transform carries the *previous* frame’s camera:
the weapon hangs back as the player walks and then slides forward to catch up,
which is the most distracting thing a held model can do.

**Written there it is pinned exactly, not approximately.** The renderer draws
a node with ``modelview = view × model``. A node placed at the camera’s own
pose carries ``model = cameraPose × local``, and the view matrix *is* that
pose inverted — so the two cancel and what is left is ``local``, whatever the
camera is doing. The object is fixed in view space by construction rather than
by keeping up.

The hook is optional and costs nothing: a context that does not define it is
never asked.

.. _hud-skinning:

Colours
-------

A HUD is read at a glance over a world whose colours nobody controls, so its
skin fields are brighter and more opaque than the panel ones. They live on the
same :ref:`Skin <overlayui-skinning>` node:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Field
     - What it colours
   * - ``hudText``, ``hudFill``
     - HUD text and the plate behind it.
   * - ``hudGood``, ``hudWarn``, ``hudCritical``
     - A meter reading normally, low, and about to matter.
   * - ``hudTrack``
     - Behind the filled part of a meter, so an empty bar is still a bar.
   * - ``crosshair``, ``crosshairHit``
     - The reticule, and the mark that says a shot connected.
   * - ``debugFill``, ``debugTitle``, ``debugLabel``, ``debugValue``
     - The developer overlay. Deliberately unlike the HUD's colours — the two must
       never be mistaken for each other.
   * - ``hudPadding``, ``hudSpacing``
     - Pixels inside a HUD element, and between one and the next.

.. _hud-modules:

Where things are
----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - What is in it
   * - ``ui.hudwidgets``
     - ``HUDLayer``, ``HUDGroup``, ``Crosshair``, ``BarMeter``, ``LampRow``,
       ``Readout``, ``TextBlock``, ``MessageQueue``, ``MiniMap``, and ``place()``.
   * - ``ui.debugoverlay``
     - The overlay, the provider registry, value formatting and the providers shipped
       with it.
   * - ``ui.screen``
     - The context mix-in: ``hudLayers``, ``debugOverlay``, and the one drawing hook
       both kinds of layer go through.
   * - ``ui.widgets``
     - ``RootWidget``, which a HUD layer and a panel are both kinds of: the children,
       the skin and the scaled copy of it.
   * - ``telemetry``
     - The whole session, not just its slow parts: input, frame times, exceptions and
       this overlay's own sections, in a file that can be :doc:`read back or replayed
       <telemetry>`.
   * - ``stalltrace``
     - The recording: a stack sampler gated on the stall itself, the episode journal
       it writes, and the report that reads the file back.
   * - ``looptrace``
     - ``LoopTrace``: wall-clock cost of a whole loop iteration, divided among named
       phases, with the worst and the stall count a median throws away.
   * - ``framecounter``
     - ``FrameCounter``: how long the frames inside ``OnDraw`` took. Measures; does
       not draw.
   * - ``passes.renderstats``
     - What one frame cost, counted where the pass knows the answer.
   * - ``passes._flat``
     - ``placeViewAttachments``: the one window in a frame where something can be
       pinned to the camera.

The design and its reasoning are in ``plans/HUD-DEBUG-OVERLAY.md``.
