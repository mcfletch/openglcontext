# Physics and audio as engine services

Status: **Proposed**, 2026-10-25. Nothing is built. The API below is for the maintainer to
accept, change or reject before phase 1.

Every physics demo builds its own wrapper around the simulation (`CollisionYard`,
`AudioYard`, `DemoScene`), steps it from `OnIdle`, drains its collisions and plays
the sounds itself. A game built on the engine repeats all of that. This plan makes
physics and audio part of every `Context`: a body is added with one call, the world
steps itself, collisions arrive as events, results reach the scene before the next
frame, and a sound is played with one call from any thread.

## What a developer writes today

`tests/tutorials/physics/physics_bounce.py` is 59 lines. Eleven of them are tick
plumbing: the `systemtime` import, `disable_vsync()`, the `_last` clock, and a
seven-line `OnIdle` that computes a step, advances the scene and asks for a redraw.
`CollisionYard` and `AudioYard` (`OpenGLContext/bin/physics_events_demo.py`,
`audio_demo.py`) add a `FrameStep`, a `blows` list the subscription fills, a `step()`
that advances the manager, empties the list and calls `engine.play` for each entry,
and a `key -> method` table in the context.

Four facts in the code explain why it looks like this:

- `PhysicsManager.advance(dt)` is the tick, and only the application calls it
  (`physics/manager.py:221`).
- `ThreadedPhysicsManager` runs the world on a thread, but the caller then takes
  `with_world()` around every mutation, calls `start()`, and is refused an
  immediate subscription (`physics/threaded.py`). Threading is the developer's job.
- A body is built from `omi_physics.model` records: `Motion`, `Collider`, a shape
  index, a material index. `PhysicsManager.attach(node, Motion(type=DYNAMIC))` is the
  shortest route and still needs the model import.
- `omi_audio.AudioEngine` is single-threaded by contract ("call all of it from one
  thread"). A collision handler on any other thread cannot call `engine.play`.

The X3D `RigidBodyCollection` already steps itself on the engine clock through the
render queue (`scenegraph/x3drigidbody.py`), and `audio/scene.py` already receives
the scene's audible paths from the render pass each frame. Both are the pattern this
plan generalises.

## Goals

1. An application writes no tick code. No `advance`, no clock, no redraw request.
2. Geometry in the scene is static scenery. One call makes an object dynamic.
3. Changing the world is a method call from any thread. No lock appears in user code.
4. Collisions, entries and sleeps are events. A handler chooses which thread runs it.
5. The same program runs with the simulation inline, on a thread, or in another
   process.
6. A scene with nothing awake costs nothing: no thread ticking, no frame requested.
7. `audio.play(...)` works from any thread and needs nothing pumped.

Not in this plan: changes to the solver or the OMI data model, networking, rollback.

## Design

A context hosts services. Each service has an inbox that any thread writes
commands to, a worker that owns its state (a thread, a process, or the frame hook
itself), and an outbox the render thread drains once a frame, before `OnIdle` and
before anything is drawn.

```text
any thread                      worker (inline | thread | process)
----------                      ----------------------------------
body.apply_impulse(...)  --->   inbox: plain-data commands
                                applied at the start of the next tick
                                tick: step the world, collect events
render thread            <---   outbox: one pose snapshot per tick,
 frame hook                              events as data,
  write poses to Transforms              coalesced scene updates
  deliver 'render' handlers
  apply scene updates
```

The frame hook is one function registered with `RenderQueue.before_run`
(`events/renderqueue.py`), which the main loop already runs at that point. Nothing
new is added to the loop.

Four rules keep the three transports interchangeable:

- Only the worker touches the world. `with_world()` stays inside the worker.
- Everything that crosses is plain data: integer ids, floats, NumPy arrays. A body
  id carries a generation count so a recycled slot cannot be mistaken for the body
  that left it. No `id()` keys.
- Poses cross as one array per tick. Events cross as a list. Scene updates are
  coalesced per (node, field), last write wins.
- A read on a `Body` returns the last published snapshot, which is at most one tick
  old. A write is a command and takes effect on the next tick.

## API: physics

### The service

`context.physics` exists on every context. It is made on first access, so a context
that never mentions it pays nothing. The worker starts when the first dynamic body
is added or `enable(True)` is called.

```python
physics.set_config(definition)              # a PhysicsDefinition, applied between ticks
physics.enable(True, tick_frequency=240)    # False pauses; poses stay where they are
physics.add_static(node, proxy=None, **material)
physics.add_dynamic(node, proxy=None, mass=None, **material)
physics.add_kinematic(node, proxy=None)     # moved by code, pushes dynamic bodies
physics.add_trigger(node, proxy=None)       # reports enter and exit, stops nothing
physics.addEventHandler(event, function=fn, **filters)   # every body
physics.body_for(node)                      # the Body of a node already in the scene
physics.run(function)                       # escape hatch, below
```

Each `add_*` returns a `Body`. `node` is any scenegraph node that draws triangles:
a `Shape`, a `Transform` holding shapes, a glTF `scene.group`. The body takes its
starting pose from the node and the world owns the pose afterwards. `**material` is
either `material='rubber'` (a preset or a defined name), a `Material`, or loose
`friction=`, `restitution=`, `linear_damping=` values that build an anonymous one.

`add_dynamic(..., mass=None)` takes the mass from the proxy's volume and the
material's density. Impulses are in newton-seconds and velocities in metres per second.

### PhysicsDefinition

`PhysicsDefinition` is a scenegraph node, declared on `ContextDefinition.physics` the
way `AudioSettings` is declared on `ContextDefinition.audio`. `set_config` takes the
same node at run time.

| field | type | default | meaning |
|---|---|---|---|
| `enabled` | SFBool | true (`OPENGLCONTEXT_PHYSICS`) | false: no worker, no colliders, bodies are inert |
| `mode` | SFString | `thread` | `thread`, `inline` or `process` |
| `tickHz` | SFFloat | 120 | simulation steps per second |
| `gravity` | SFVec3f | 0 -9.81 0 | m/s squared, global |
| `colliders` | SFString | `scene` | `scene`: shapes under `sg` are static bodies; `explicit`: only `add_static`; `none` |
| `linearDamping`, `angularDamping` | SFFloat | 0.3, 1.5 | per second, as the world's current defaults |
| `materials` | MFNode | presets | `PhysicsMaterial` nodes defined for the context |

`mode='inline'` steps the world in the frame hook by the frame's time step
(`events/framestep.py`). A bounded capture, `OPENGLCONTEXT_CAPTURE_FPS` and a
telemetry replay select it, so a captured frame is the same bytes on every run.

The node is declared in an X3D extension component, so an X3D document can carry it
and the X3D writers write it back.

### Body

```python
body.node                                   # the Transform; touch it on the render thread only
body.position, body.rotation                # last snapshot
body.velocity, body.angular_velocity, body.speed, body.asleep

body.apply_impulse(impulse, at=None)        # N*s; `at` is a world point, default the centre
body.apply_torque_impulse(impulse)
body.set_force(force)                       # held until set again; (0, 0, 0) clears it
body.set_velocity(velocity)
body.set_transform(translation=None, rotation=None)   # teleport
body.move_to(translation, over=1.0)         # kinematic bodies: glide, pushing what is in the way
body.wake(); body.freeze(); body.remove()
body.addEventHandler(event, function=fn, **filters)      # one body
```

Every writer is a command. On the worker thread the same call is applied at once,
so one handler body works in either place.

Assigning `node.translation` or `node.rotation` on a dynamic body's node is a
teleport. The frame hook marks its own writes, and any other write to those fields
becomes a `set_transform`. A snapshot older than the teleport is discarded, as
`ThreadedPhysicsManager._fresh` already does for newly added bodies.

### Scenery is static by default

With `colliders='scene'` the render pass hands the physics service the shapes it
collects, as it hands `audio` the audible paths. A shape that is new since the last
frame becomes a static trimesh body unless it:

- sits inside an X3D `Collision(enabled=False)` group,
- carries `collide=False` (glTF: `extras.collide = false`),
- is a sky, particle, water, text or other non-solid node type, or
- already belongs to a `Body`.

Cooking runs on a worker, never on the frame, and is cached by content in
`omi_physics.cookery`. A glTF with `OMI_physics_body` and `OMI_physics_shape` blocks
needs no call at all: the loader registers its bodies when the scene is mounted and
removes them when it is unmounted.

`add_static(node, proxy='convex')` on a node the scene derivation already covers
replaces that body. `add_dynamic` does the same, which is why a ball appended to `sg`
before its `add_dynamic` is static for no more than one frame.

Two costs have acceptance tests. Loading 10,000 shapes adds no per-frame
work after the first frame (`check_still_frame`), and the derivation grows with the
number of new shapes, not with the scene (`check_scaling` at n and 4n).

### Finding the body of a node

Scenery and glTF-authored bodies are made without a call, so nothing returns their
`Body`. The service looks them up:

```python
node = scene.sceneGraph.getDEF('Door')           # a node found in a loaded scene
door = physics.body_for(node)                    # its Body, or None
door.addEventHandler('hit', function=self.OnDoorHit)

doors = physics.bodies_in(scene.group)           # every Body under a subtree
```

`body_for` returns the body of the node itself, else of the nearest ancestor that has
one, so a `Shape` inside a body's `Transform` finds that body. It returns the same
`Body` object on every call. It returns None for a node under `Collision(enabled=False)`,
marked `collide=False`, or with no triangles, and with `colliders='explicit'` for any
scenery nobody added.

The derivation runs in the frame hook, so a node mounted this frame has no body until
the next. `body_for` therefore creates the body on demand for a node in the scene, and
the cooked shape arrives when the cooking queue reaches it. A handler added in that
interval is kept on the handle and takes effect when the body is in the world.

Static scenery reports no contacts until something subscribes: a handler on a static
body switches reporting on for that body alone (`PhysicsWorld.report_contacts`), so an
unwatched world pays nothing for events.

This needs one static body per `Shape`, not one merged mesh per scene as
`collision_world_from_scene` builds today. The static broadphase is a tree, so many
bodies cost little per frame; phase 3 measures it at 10,000 shapes. If the count
hurts, scenery is merged and `body_for` splits the asked-for node out of its merge.

### Proxies: what the engine collides with

`proxy` says what shape stands for the node. `None` cooks it from the drawn mesh:
a fitted primitive where one fits, the triangles for a static body, the convex hull
for a dynamic one.

```python
add_dynamic(ball, proxy='sphere')            # fit a sphere to the mesh
add_dynamic(chair, proxy='convex')           # hull
add_dynamic(chair, proxy=chair_low)          # another node: a simpler mesh in the same file
add_static(wall, proxy=Proxy.box((0.2, 3, 8)))   # written by hand
crate = physics.cook(crate_node, 'box')      # cooked once, shared by every body below
for each in crates: physics.add_dynamic(each, proxy=crate)
physics.show_proxies(True)                   # draws the proxies, contacts and velocities
```

`Proxy` wraps `omi_physics.model.Shape` and adds the constructors `box`, `sphere`,
`capsule`, `convex(points)` and `trimesh(points, indices)`.
`show_proxies` is the existing `PhysicsDebugDraw` overlay switched on from the service.

### Materials

```python
physics.materials.define('mud', friction=0.9, restitution=0.0, sound='squelch.ogg')
physics.materials.pair('mud', 'rubber', friction=1.2)      # a rule for that pair only
add_static(floor, material='mud')
```

The presets in `omi_physics.model.MATERIAL_PRESETS` (`wood`, `metal`, `rubber`,
`ice`) are defined at start-up. A material with `sound=` plays that clip at each
hit above a small closing speed, at the contact point, with gain from the impulse.
That replaces the hand-written `_collide` loop in `AudioYard`.

### Gravity zones

```python
physics.add_gravity_zone(Box(center=(0, 3, 0), size=(4, 6, 4)), gravity=(0, 2, 0))
physics.add_gravity_zone(zone_node)         # a Zone node that carries gravity
```

`Box`, `Sphere` and the other regions are `omi_physics.gravity`'s. `Zone` nodes
with gravity and `OMI_physics_gravity` blocks in a loaded file are registered
without a call (`physics/zones.py` already reads them).

### Events

Names are `hit`, `touching`, `separate`, `enter`, `exit`, `sleep`, `wake`. A handler
receives one `Collision` (`physics/events.py`): `body`, `other` (always a `Body`, scenery
included), `point`, `normal`, `speed` (the closing speed), `impulse`, `time`.

```python
ball.addEventHandler('hit', function=self.OnBallHit, above=1.0)    # faster than 1 m/s
ball.addEventHandler('hit', function=self.OnBallHit, other=crate)  # only against that body
physics.addEventHandler('hit', function=self.OnAnyHit)             # every body
```

`addEventHandler(eventType, function=fn, **keys)` is the spelling the context, `Timer` and
`TimeSensor` already use, and `function=None` removes a handler as it does there.

Filters are `above=` (closing speed), `other=` (a `Body` or a list) and `where=`.
Handlers are held weakly, as everywhere else in the engine: a bound method of a live
object works, and a lambda or local function with no other reference is collected as
it is registered. The tutorials use bound methods for that reason. Registering returns
the subscription, and `subscription.cancel()` ends it. A subscription also ends when
its body is removed, and when the handler's object is collected.

`where='render'` is the default. The handler runs in the frame hook, on the render
thread, after the poses are written, so it may change the scene directly.
`where='physics'` runs the handler on the worker right after the tick that produced
the event, with the world in the state the event describes. It may call any `Body`
method, which applies at once, and send scene changes with `physics.render`:

```python
physics.render.set(node, baseColor=RED)     # coalesced; applied before the next draw
physics.render.call(function, *args)        # RenderQueue.call; runs on the render thread
```

Called on the render thread, `render.set` assigns at once, so a handler that moves
between `where='render'` and `where='physics'` changes only the word `where`.

Events are data on the worker side: body ids, points, numbers. The frame hook turns
the ids into `Body` handles before it calls a render handler.
`CollisionEvents.dispatch` today resolves objects and calls back in one step; the
work splits at that seam.

### The escape hatch

```python
physics.run(lambda world: world.add_joint(hinge))
```

`run` calls the function with the raw `omi_physics.PhysicsWorld` on the worker, at
the start of a tick, and returns a future. It covers joints, custom contact filters
and anything the service has not named. With `mode='process'` the function must be
an importable `'module:function'` string, because a closure cannot cross the boundary.

### Queries

`raycast` and `overlap` ask the world a question and want an answer. The first form is
a callback, `physics.raycast(origin, direction, on_result=fn)`, answered by the
frame hook on the next frame. A blocking `raycast_now` is added only if a caller needs
it, and costs up to one tick of waiting in `thread` mode.

### Failure

An exception on the worker is logged once with its traceback, the service disables
itself, bodies stay at their last poses and `physics.error` holds the exception. A
handler that raises is logged once per handler and the subscription continues.
Physics never raises into the draw.

## API: audio

`context.audio` exists on every context and is made on first access. The player's
switch, volume and voice budget stay on `contextDefinition.audio`
(`AudioSettings`); `context.audio` is the live manager. The device opens on the first
`play`, as it opens today on the first audible node, and `enabled=False` makes every
call return an inert voice.

```python
audio.play('thud.ogg')                                  # centred
audio.play('thud.ogg', at=hit.point, gain=0.5)          # at a world point
voice = audio.play('engine.ogg', at=car, loop=True)     # follows a Body or a scene node
voice.gain = 0.3; voice.rate = 1.4; voice.stop()
audio.load('thud', 'thud.ogg')                          # a name for a clip, decoded ahead
audio.volume = 0.8                                      # the player's volume
```

A source is a path, URL, loaded name or `omi_audio.Clip`, including the synthesised
clips in `omi_audio.synth`. Clips are cached by path.

`play` is safe from any thread. It returns a `Voice` at once, and the frame hook
starts the underlying engine voice, so the single-threaded contract of `AudioEngine`
holds. `voice.stop()` before the hook runs cancels the start. A sound started from
a physics event is therefore at most one frame late, plus the device buffer. An
event carries its simulation `time`, and a later phase can offset the voice start
inside the mixer block to remove the frame.

`at=` takes a point, a `Body` (followed through its snapshot, which is cheap) or a
scene node (followed through the path found when `play` is called). Scene nodes that
already carry `AudioEmitter` and `AudioSource` keep playing as they do; `audio.play`
adds the call-shaped route beside them.

The per-frame upkeep (`audio.scene.update`: listener from the camera, zones, X3D sound
graph) stays in the render pass. `audio` owns the pending calls and the engine, and the
module functions `engine_for` and `existing_engine` become implementation.

## Tutorials: the ergonomics test

Each tutorial adds a few lines to the one before. The counts are lines of
application code inside `OnInit`, with imports and the `__main__` guard excluded.

### 1. A ball rolls down the stairs (6 lines)

```python
class StairsContext(Context):
    initialPosition = (0, 3, 10)

    def OnInit(self):
        stairs = self.sceneLoader.load_now('stairs.glb').result.group
        ball = self.sceneLoader.load_now('ball.glb').result.group
        ball.translation = (0, 4.5, -2)                  # the top of the stairs
        self.sg = sceneGraph(children=[Background(), DirectionalLight(), stairs, ball])
        body = self.physics.add_dynamic(ball, mass=2.0, restitution=0.4)
        body.apply_impulse((0, 0, 3))                    # 1.5 m/s down the stairs
```

The stairs are static because they are in `sg`. The tutorial teaches loading, a
position, `add_dynamic` and `apply_impulse`. It does not mention a tick, a thread, a
shape, a material index or a redraw.

### 2. The ball changes colour when it hits something (+5 lines)

```python
        loaded = self.sceneLoader.load_now('ball.glb').result
        ...
        self.skin = loaded.materials['Ball']
        body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

    def OnBallHit(self, hit):
        self.skin.baseColor = (1, 0, 0)
```

The handler runs on the render thread and assigns the field.

### 2b. The same, reacting on the physics thread (+0 lines, one line changed)

```python
        body.addEventHandler('hit', function=self.OnBallHit, above=1.0, where='physics')

    def OnBallHit(self, hit):
        self.physics.render.set(self.skin, baseColor=(1, 0, 0))
```

This is the tutorial for threads. It shows why the scene is not assigned from the
worker, and what `render.set` does about it.

### 3. Choosing the collision shape (+1 line)

```python
        self.physics.show_proxies(True)
        body = self.physics.add_dynamic(ball, proxy='sphere')
```

Then a second page: `proxy='convex'` for a chair, a simpler node as the proxy, and
`physics.cook` shared by a hundred crates.

### 4. A new material (+2 lines)

```python
        self.physics.materials.define('wet-stone', friction=0.1, restitution=0.05)
        self.physics.add_static(stairs, material='wet-stone')
```

### 5. A gravity zone (+1 line)

```python
        self.physics.add_gravity_zone(Box(center=(0, 3, 0), size=(3, 6, 3)), gravity=(0, 2, 0))
```

### 6. A sound on every hit (+1 line, or none with a material sound)

```python
    def OnBallHit(self, hit):
        self.skin.baseColor = (1, 0, 0)
        self.audio.play('thud.ogg', at=hit.point, gain=hit.speed / 6)
```

With `sound='thud.ogg'` on the material, no handler is needed.

### 7. Turning it off and tuning it

```python
self.physics.enable(False)                          # pause
self.physics.enable(True, tick_frequency=240)       # finer steps
ContextDefinition(physics=PhysicsDefinition(enabled=False))   # not at all
```

### What a developer writes for each need

| need | writes |
|---|---|
| a static world | nothing, or `add_static(node, proxy=...)` to change its shape |
| a moving object | `add_dynamic(node)` |
| a different shape, material, mass | a keyword on that call |
| a handle on a node already in the scene | `physics.body_for(node)` |
| a reaction to a hit | `body.addEventHandler('hit', function=fn)` |
| a reaction inside the tick | the same, with `where='physics'` |
| a world setting | a field on `PhysicsDefinition` |
| something the service lacks | `physics.run(fn)` against the raw world |

## Process mode

`mode='process'` runs the worker in a child process that imports `omi_physics` and
nothing else: no GL, no scenegraph. The protocol is the one the thread uses.

- Commands and events travel on a pipe as tuples of numbers, ids and arrays.
- Cooked shapes cross once, by content hash, through `multiprocessing.shared_memory`.
- The pose snapshot is two shared-memory buffers with a sequence number: the worker
  fills one while the frame hook reads the other.
- A `where='physics'` handler and a `run` function are given as `'module:function'`
  strings that the child imports. A closure is refused at registration with a message
  that says so.
- A child that dies is reported through `physics.error`; the window keeps drawing.

Two reasons to want it: Python-level work in a tick holds the render thread's GIL on
the GIL builds, and a crash in the native solver ends the child and not the window.
The second does not excuse the crash. The core-dump rule in the workspace
`CLAUDE.md` still applies.

Phase 0 measures the first reason before any process code is written. If a thread
holds 60 frames a second with 5,000 bodies on the GIL build, process mode waits for
a game that needs it.

## Where the code goes

| path | holds |
|---|---|
| `events/handoff.py` | `Inbox` (any thread to a worker) and `Updates` (worker to render thread, coalesced); no GL, shared by physics and audio |
| `physics/service.py` | `Physics`, the facade `context.physics` returns |
| `physics/body.py` | `Body` and the command records it enqueues |
| `physics/worker.py` | the `Worker` protocol and its `Inline`, `Thread` and `Process` forms, built on the existing `PhysicsManager` and `ThreadedSimulation` |
| `physics/colliders.py` | scenery to static bodies: the rules, the cooking queue |
| `physics/settings.py` | `PhysicsDefinition`, beside `audio/settings.py` |
| `audio/manager.py` | `Audio`, `Voice`, and the pending-call list the frame hook drains |

`Physics` and `Audio` hold no GL and take a sink for scene updates, so a unit test
drives them without a window. The context is the thin shell that builds them, hands
them `RenderQueue.before_run` and closes them with the window. `OnQuit` and the
disposal chain close the worker and join the thread.

Changes below the engine, in `omi_physics`:

- `ThreadedSimulation` applies an inbox of commands at the start of each tick, and
  blocks on an event while nothing is awake and the inbox is empty. Goal 6 depends on
  the second.
- `ThreadedSimulation.start()` checks `_thread` without a lock, so two starts spawn
  two threads (`FREE-THREADING.md`, hazards list). The worker owns start and stop.
- Contact events carry body ids and generations, not resolved objects.

## Determinism and tests

- `mode='inline'` is the reference. The same scenario steps to the same poses under
  `inline` and `thread` after `physics.settle()` has drained the inbox, and the suite
  asserts it.
- `physics.wait_ticks(n)` blocks a test until the worker has published `n` more
  ticks. No test sleeps for a duration.
- Unit tests cover: a command issued before the worker starts, a body removed
  between a command and its tick (the stale id is dropped, not applied to its
  successor), a handler that raises, `enable(False)` and back, `set_config` with a
  new `tickHz`, and teleport against a stale snapshot.
- `check_still_frame` on a scene whose bodies have all fallen asleep: no worker tick,
  no redraw request. A physics-driven redraw is asked for only while a body is
  awake.
- `check_scaling` on the frame hook: its cost follows the bodies that moved.
- A script test for each tutorial under `tests/tutorials/physics/`, captured under
  the fixed-step clock.

## Phases

| phase | content | done when |
|---|---|---|
| 0 | Measure: frame time and tick time at 1,000 and 5,000 bodies, inline against thread, on the GIL build and on 3.14t; the idle cost of `ThreadedSimulation` today | numbers are in this plan |
| 1 | `Physics` inline and thread, `Body`, commands, frame hook, `PhysicsDefinition` on `ContextDefinition`, `enable`, `set_config`, `run`; tutorial 1 | tutorial 1 passes as written; idle scene asks for no frame |
| 2 | Events: render and physics delivery, `render.set`, `render.call`, the `Collision` split; tutorials 2 and 2b | both tutorials pass; no handler holds a lock |
| 3 | Scenery as static bodies, glTF OMI bodies registered on mount, teleport by assignment | the two cost tests pass; `physics_bounce.py` loses its `OnIdle` |
| 4 | `Proxy`, `cook`, `show_proxies`, materials, pair rules, gravity zones; tutorials 3 to 5 | tutorials pass |
| 5 | `Audio`, `Voice`, thread-safe `play`, material sounds; tutorial 6 | `AudioYard._collide` deleted |
| 6 | Migrate `CollisionYard`, `AudioYard`, `DemoScene`, the marble, twig-bb and glisteel callers; delete `DemoScene` and the public `ThreadedPhysicsManager` | no caller of `manager.advance` outside the worker |
| 7 | `mode='process'`, only if phase 0 shows the need | the same tests pass in all three modes |

The walking character (`PhysicsViewPlatform`) takes `with_world()` today. It moves
onto the service in phase 6 as `physics.add_character()`, and the walk movement
mode registers the camera body without a call.

## Documentation to change

- `docs/physics.rst`: "Adding physics to a scene" is rewritten around the tutorials;
  `DemoScene` leaves the page.
- `docs/audio.rst`: `audio.play` leads; the engine-level section becomes reference.
- `docs/eventmodel.rst`: physics events and the thread rule.
- `docs/structure.rst` and the directory map in `CLAUDE.md`: `events/handoff.py`,
  the new `physics/` and `audio/` modules.
- `tests/tutorials/physics/`: the tutorials above, written as the `'''`-commentary
  files the doc build turns into pages.
- `docs/x3d.rst`: `PhysicsDefinition` as an extension node.
- `omi_physics/docs/ARCHITECTURE.md`: the command inbox and the idle block.
- `plans/PROJECT-PLAN.md`: a row for this plan, and a pointer from
  `COLLISION-EVENTS.md`, whose subscription layer this builds on.

## Decisions for the maintainer

1. Handler thread. The request describes handlers running on the physics thread.
   This plan makes `where='render'` the default and `where='physics'` the option.
   Reason: a render handler can touch the scene, works unchanged in all three modes,
   and matches how `CollisionEvents` delivers today. A physics-thread handler cannot
   be a closure in process mode. Recommendation: keep the plan's default and teach
   the physics-thread form in tutorial 2b. Reversing the default is a one-word change
   in the API and a documentation change.
2. One node or two. `PhysicsDefinition` carries the player's machine choices
   (`enabled`, `mode`, `tickHz`) and the author's world (`gravity`, `materials`).
   Audio splits the player's settings from the application's mix. Recommendation:
   one node now, and split if a settings screen needs only the first group.
3. Assignment as teleport. `node.translation = ...` on a dynamic body's node moves
   the body. It costs a dispatcher receiver per dynamic body. Recommendation: build it
   in phase 3, measure with 1,000 bodies, and drop it if the frame hook's cost
   rises by more than 5 percent.
4. Context-level events. Handlers on a `Body` or on `physics` use the context's
   `addEventHandler` shape. A further context-level spelling,
   `context.addEventHandler('physics-hit', body=ball, function=fn)`, would put physics
   events in the telemetry journal beside keys and clicks. Recommendation: add it in
   phase 2 as a second route to the same subscription, since the journal needs the
   events to replay a session.
5. "With properties x, y, z". The request's `add_dynamic` line is read as
   physical properties (mass, friction, restitution) given as keywords, since the
   position is set on the node. If it meant position, `add_dynamic(node, at=(x, y, z))`
   is a trivial addition.
6. X3D `RigidBodyCollection` keeps its own world and its own stepping. Moving it
   onto the service means two authoring routes into one world, and is left until
   after phase 6.
