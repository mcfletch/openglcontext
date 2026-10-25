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
5. The same program runs with the simulation inline or on a thread. Commands and events
   are plain data, so a child process can be added later without changing application
   code.
6. A scene with nothing awake costs nothing: no thread ticking, no frame requested.
7. `audio.play(...)` works from any thread and needs nothing pumped.
8. Characters, raycasts and sweeps answer within the call that asks, on the render
   thread, in every mode.
9. The games in this workspace move onto the service without losing a fixed step, a
   replay or a test that runs without a window.

Not in this plan: changes to the solver or the OMI data model, networking, rollback.

## Design

A context hosts services. Each service has an inbox that any thread writes
commands to, a worker that owns its state (a thread, or the frame hook
itself), and an outbox the render thread drains once a frame, before `OnIdle` and
before anything is drawn.

```text
any thread                      worker (inline | thread)
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

Four rules keep the transports interchangeable, the two built now and a process later:

- Only the worker touches the world. `with_world()` stays inside the worker.
- Everything that crosses is plain data: integer ids, floats, NumPy arrays. A body
  id carries a generation count so a recycled slot cannot be mistaken for the body
  that left it. No `id()` keys.
- Poses cross as one array per tick. Events cross as a list. Scene updates are
  coalesced per (node, field), last write wins.
- A read on a `Body` returns the last published snapshot, which is at most one tick
  old. A write is a command and takes effect on the next tick. In inline mode the
  tick is the frame hook's own step, so a write made before the hook is in the step
  that follows it.
- A `Physics` needs no context. A tool, a headless trace or a test builds one, steps it
  with `step(dt)` and reads it; the context's `physics` is the same object with a sink
  for scene updates.

## API: physics

### The service

`context.physics` exists on every context. It is made on first access, so a context
that never mentions it pays nothing. The worker starts when the first dynamic body
is added or `enable(True)` is called.

```python
physics.set_config(definition)              # a PhysicsDefinition, applied between ticks
physics.enable(True, tick_frequency=240)    # False pauses; poses stay where they are
physics.add_static(node, proxy=None, **material)
physics.add_dynamic(node, proxy=None, mass=None, translation=None, rotation=None, **material)
physics.add_kinematic(node, proxy=None)     # moved by code, pushes dynamic bodies
physics.add_trigger(node, proxy=None)       # reports enter and exit, stops nothing
physics.addEventHandler(event, function=fn, **filters)   # every body
physics.body_for(node)                      # the Body of a node already in the scene
physics.gravity = (0, -9.81, 0)             # a command; may change every frame
physics.step(dt)                            # inline and standalone: advance by hand
physics.world                               # inline and standalone only: the live PhysicsWorld
physics.flush()                             # inline and standalone: apply the queued writes now
physics.index_of(body)                      # inline and standalone: the body's slot in physics.world
physics.drop_remainder()                    # inline and standalone: forget the time left over from a frame
physics.add_character(...)                  # a walker; see Characters and view platforms
physics.add_collider_source(source)         # colliders that come and go with a focus point
physics.raycast(origin, direction, ...)     # synchronous queries; see Queries
physics.post(function, *args)               # call function on the worker; returns None
physics.run(function)                       # escape hatch, below
```

Each `add_*` returns a `Body`. `node` is any scenegraph node that draws triangles:
a `Shape`, a `Transform` holding shapes, a glTF `scene.group`. The body takes its
starting pose from the node and the world owns the pose afterwards. `translation=` and
`rotation=`, on any `add_*`, set the node's fields before the body is made, so a body is
placed and added in one call. `**material` is
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
| `mode` | SFString | `thread` | `thread` or `inline` |
| `tickHz` | SFFloat | 120 | the fixed step, in steps per second, in both modes |
| `maxCatchUp` | SFFloat | 0.1 | longest span of time one frame steps, in seconds; the rest is dropped |
| `gravity` | SFVec3f | 0 -9.81 0 | m/s squared, global |
| `colliders` | SFString | `scene` | `scene`: shapes under `sg` are static bodies; `explicit`: only `add_static`; `none` |
| `linearDamping`, `angularDamping` | SFFloat | 0.3, 1.5 | per second, as the world's current defaults |
| `materials` | MFNode | presets | `PhysicsMaterial` nodes defined for the context |

`mode='inline'` steps the world in the frame hook. The hook reads the frame's time
(`events/framestep.py`), adds it to an accumulator capped at `maxCatchUp`, and runs as
many whole steps of `1 / tickHz` as the accumulator holds. Which step a body was in
when something happened is therefore the same on every run at a given frame time. A
bounded capture, `OPENGLCONTEXT_CAPTURE_FPS` and a telemetry replay select it, so a
captured frame is the same bytes on every run. A program that wants its own time, such
as a replay's recorded frame times or a headless trace, calls `physics.step(dt)` itself;
that is also how a `Physics` with no context advances.

`mode='thread'` runs the same steps on the worker at `tickHz`. A game that controls its
bodies between steps (below, under Events) uses `inline`.

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
body.drive(pose)                            # kinematic bodies: pose(t) -> (translation, rotation), each step
body.linear_damping = 0.5                   # per body; commands, like the writers above
body.angular_damping = 2.0
body.wake(); body.freeze(); body.remove()
body.addEventHandler(event, function=fn, **filters)      # one body
```

`drive` takes a physics callback. At each step the service calls it with the simulation
time, moves the body to the pose it returns, and sets the body's velocity from the
distance moved, so a dynamic body resting on it is carried and a hit against it has the
right closing speed. A kinematic body moved by `set_transform` would be a teleport with
no velocity.

Every writer is a command. On the worker thread the same call is applied at once,
so one handler body works in either place.

While a body is dynamic and awake the world owns its node's pose, and the next snapshot
overwrites a write to `node.translation`. `set_transform` is how a body is moved. A
snapshot older than a `set_transform` is discarded, as `ThreadedPhysicsManager._fresh`
already does for newly added bodies.

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

### Collider sources

```python
physics.add_collider_source(HeightFieldColliders(...))     # bodies near a focus point
physics.add_collider_source(scene.rocks)                   # analytic: a floor and pushes
```

A collider source is colliders that come and go with a focus point: ground chunks near
a car, road sections, props, rocks near a walker. The focus is the context's view
platform unless the source names a node. A source has one of two forms:

- Body source. `update(focus)` returns bodies to add and bodies to remove.
  `HeightFieldColliders`, `RoadColliders` and `PropColliders` (`physics/heightfield.py`,
  `road.py`, `props.py`) already work this way; they become sources and the frame
  hook calls them, so their adds and removes are commands and publish a new collision
  view.
- Analytic source. `floor(x, z)` and `push_out(x, z, reach)` answer for characters
  only, with no body at all. A terrain too large to cook (the forest's heightfield and
  trunk cylinders) is this form.

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
`capsule`, `convex(points)` and `trimesh(points, indices)`. `add_static` with a `trimesh`
proxy takes the arrays directly, with no node, for a level whose collision mesh is cooked
elsewhere.
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

### X3D rigid bodies and gravity zones

An X3D `RigidBodyCollection` is a world of its own (`physics/x3drigid.py`) and stays
that. It steps once a frame through the render queue at a fixed step, collides what its
`collider` and its `Contact` nodes name and nothing else, takes its gravity from its own
`gravity` field, and reads no zones. This plan changes nothing in it.

What follows from separate worlds, for the documentation to state:

- Zone gravity (`Zone` gravity, `OMI_physics_gravity`) acts on `context.physics` bodies and
  characters. X3D bodies obey the collection's `gravity`.
- X3D bodies do not collide with `context.physics` bodies, scenery or characters. A
  document that wants a body to meet scenery lists the scenery as a `CollidableShape`
  in the collection's `collider`, which it can do today.
- Characters are stopped by `Collision` groups and not by rigid bodies.
- `CollisionSpace` groups collidables inside one collection. It plays no part in zones or
  in the service.
- `CollisionSensor` keeps routing a collection's touches. `physics.body_for` and
  `addEventHandler('hit')` do not apply to X3D bodies.

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

Filters are `above=` (closing speed) and `other=` (a `Body` or a list).
Handlers are held weakly, as everywhere else in the engine: a bound method of a live
object works, and a lambda or local function with no other reference is collected as
it is registered. The tutorials use bound methods for that reason. Registering returns
the subscription, and `subscription.cancel()` ends it. A subscription also ends when
its body is removed, and when the handler's object is collected.

Render handlers are delivered through the context's event system. The service registers
an event manager for each name, `physics-hit`, `physics-touching`, `physics-separate`,
`physics-enter`, `physics-exit`, `physics-sleep` and `physics-wake`, beside `keypress`
and `mousebutton`. `body.addEventHandler('hit', function=fn)` and
`context.addEventHandler('physics-hit', body=body, function=fn)` register the same
handler. Delivering through one route puts one tap where the telemetry journal needs it.

The journal records each physics event the frame hook delivers: the frame, the step
index, the simulation time, the name, the two bodies, and the point, normal, speed and
impulse. A body is written by the `DEF` name of its node where it has one, else by the
order it was added in. Replay then needs to know when events occurred in order to say
whether it reconstructed the session:

- Recording or replaying a session puts the service in inline mode, as a bounded capture
  does, so the world is a function of the recorded frame times and of what the game
  commanded. A session that was recorded on the thread is replayed inline, and the
  telemetry reader says so.
- During a replay each event the service delivers is compared with the journal's:
  same name, same bodies, same frame and step. The comparison is the `MarkComparison` the
  game's marks already use, and the summary at the end of the replay counts events that
  matched, differed, were missing and were extra.
- `Collision.step` and `Collision.time` are in the event so the record and the comparison
  do not depend on the frame an event happened to be delivered in.

A handler runs on the render thread unless the function is marked as a physics
callback:

```python
class StairsContext(Context):
    @Context.physics_callback
    def OnBallHit(self, hit): ...
```

`physics_callback` only sets an attribute on the function. Registration reads it, and
a direct call runs the function on the calling thread like any other. It lives in
`OpenGLContext.physics` and is also a static method on `Context`, because the class
body of a context subclass already has `Context` in scope and needs no further import.
There is no `render_callback`; render is the default.

What each thread means for a handler:

- Render handler. The frame hook calls it and waits for it to return, after the poses
  are written, so it may change the scene directly. The tick that caused the event ended
  earlier, so the handler cannot change that tick. Its return value is ignored.
- Physics handler. The worker calls it and waits, right after the tick that produced the
  event, with the world in the state the event describes. A slow one slows the
  simulation, and the service logs a handler that outruns a tick. It may call any `Body`
  method, which applies at once, and it must not assign scene fields. Its return value is
  used only where an event asks a question, as a pre-solve contact verdict does.

Two more events belong to the world and not to a body: `before-step` and `after-step`.
`physics.addEventHandler('before-step', function=fn)` calls `fn(step)` before each fixed
step, with a `Step` carrying `dt`, the step index and the simulation time, and
`after-step` calls it after. A game that applies forces, reads contacts or moves bodies
between steps does it here. Both are physics callbacks; in inline mode they run on the
caller's thread at every step, and in thread mode on the worker.

In inline mode a physics callback for a body event runs after the step that produced the
event, so a frame of three steps calls it three times in step order, with the contacts
of each. A render handler runs once per frame after the last step and receives every
event the frame's steps made, in order, each carrying its step index. A controller that
needs every contact of every step (`hit.step`, `hit.impulse`) uses the first.

No handler call is fire-and-forget. What is asynchronous is the event's journey from its
cause to the handler, and calls that cross threads, which return None: a `Body` method
from the render thread, `render.set` and `render.call` from the worker. A function is
never made to forward its own calls to another thread. The operations are thread-agnostic
(`Body` methods are commands) and the handlers are not. `physics.post(fn, *args)` is the
explicit hand-off from the render thread to the worker.

A physics handler sends scene changes with `physics.render`:

```python
physics.render.set(node, baseColor=RED)     # coalesced; applied before the next draw
physics.render.call(function, *args)        # RenderQueue.call; runs on the render thread
```

Called on the render thread, `render.set` assigns at once, so moving a handler between
threads changes the marker and the line that touches the scene.

In a debug run the frame hook records which thread a physics handler runs on, and a
scene field set from the worker thread while it does is logged once, with the field and
the handler. The check is off in release runs.

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
and anything the service has not named. A later process mode would need an importable `'module:function'` string, because a
closure cannot cross the boundary.

### Queries and the collision view

```python
hit = physics.raycast(origin, direction, max_distance=100.0, skip=body)   # RayHit or None
hits = physics.raycast_many(origins, directions)       # arrays in, arrays out
swept = physics.sweep_sphere(origin, direction, distance, radius)
touching = physics.overlap(proxy, translation, rotation)
```

A query answers in the call, on the thread that makes it. On the render thread it reads
the collision view and the last snapshot:

- The collision view is an immutable, versioned copy of the static colliders (their ids,
  shapes, world transforms and broadphase) that the worker publishes whenever the static
  set changes. A reader holds the version it started with, so nothing locks, and a
  streamed collider set (ground chunks near a car) publishes a new version at most once a
  tick.
- The view lists the dynamic bodies' shapes too, versioned the same way, with their
  poses from the last snapshot, one tick old. A character is at its present position,
  because the render thread steps it.
- `RayHit` carries the body, the triangle number and the point, as `omi_physics.raycast`
  does today.
- `raycast_many` takes arrays so a numpy projectile system keeps its per-frame cost in
  one call.

In inline mode the queries read the live world. Called from a physics callback they read
the worker's live world.

The collision view also lets `CharacterController` and `raycast` run without the world.
In `omi_physics` both take a `CollisionQuery` protocol (body ids, proxies, poses,
broadphase queries) that `PhysicsWorld` and the collision view each implement.

### Characters and view platforms

`CharacterController` (`omi_physics/character.py`) is a kinematic capsule. It slides
against colliders, steps up ledges, jumps, flies and swims, and the caller steps it every
frame; `PhysicsViewPlatform` reads the camera from its eye.

```python
me = physics.add_character(node=None, capabilities=None, position=(0, 1, 0))
me.set_move(direction, mode='walk')         # 'walk', 'run', 'sprint', 'crouch'
me.jump(); me.apply_impulse(velocity); me.set_crouch(True)
me.position, me.eye, me.velocity, me.facing, me.grounded, me.swimming
me.addEventHandler('hit', function=fn)      # contacts and triggers; the events of a Body
me.remove()
```

Where a character runs:

- On the render thread, in the frame hook, before the poses are written and before the
  camera is read. Input reaches the camera with no tick between them, and the character's
  queries are synchronous. It reads the collision view and takes no lock.
- In the worker's world it is a kinematic body, placed by a command each frame with the
  velocity it moved at. Its triggers, contacts and events arrive like any body's.
- The capsule's size comes from `CharacterCapabilities`, built from the bound
  `NavigationInfo.avatarSize` as today. Crouching resizes the capsule.

First person: the walk movement mode binds the view platform to a character. The platform
keeps the mouse-look yaw and pitch and takes its position from `me.eye` once a frame.
`PhysicsViewPlatform` becomes a camera adapter over a `Character`, and `PhysicsWalkMixin`
(`setupPhysics`, `enablePhysics`, `stepPhysics`) is removed once the forest has moved.

Third person: `add_character(node=model_group)` places the node at the capsule's feet and
turns it to `me.facing`, which the game sets from the move or the aim. The node's
animation reads `velocity`, `grounded`, `swimming` and the crouch state from the same
object. A boom camera shortens its arm to a `sweep_sphere` from the character to the
camera's wanted place, which also keeps it out of walls; the hill-runner chase camera and
twig-bb's death camera are the two users in this workspace.

A character that is dead, hidden or between rounds is `remove()`d.

#### Characters and dynamic bodies

A character and a dynamic body act on each other. Each direction has its own mechanism,
because the capsule is moved by the render thread and the bodies by the worker.

- The character pushes. The worker's kinematic body carries the character's velocity, so
  the solver pushes a dynamic body the capsule runs into, and reports the contact. A
  capsule blocked by a pushable body would move at zero and push nothing, so while the
  render-thread step is blocked by a pushable body the kinematic body takes the velocity
  the character wanted, up to `pushSpeed`. The body moves off and the character follows
  on the next frames. A body heavier than `pushMass` blocks the character instead.
- The character is pushed. A contact event on the character's body carries an impulse.
  The frame hook turns each into a velocity change of `impulse / mass`, applied before the
  character's next step. `knockback=False` turns it off. It arrives one tick and up to a
  frame after the blow.
- The character stands on, and is blocked by, dynamic bodies. Its step reads the dynamic
  bodies' shapes and last-snapshot poses from the collision view as obstacles and floors.
  A body it stands on carries it by the velocity in the snapshot, which generalises
  `CharacterController._carry_body` from kinematic platforms to any body.
- In inline mode all of this happens in one thread: the character steps, then the world
  steps, and the same rules apply.

`CharacterCapabilities` gains `mass` (80 kg), `pushMass` (200 kg) and `pushSpeed`
(the walk speed). The tests are: a walker pushes a 20 kg crate at walking speed and does
not move a 2,000 kg one; a crate thrown at a walker changes the walker's velocity by
`impulse / mass`; a walker standing on a drifting raft is carried; the same scenarios
agree between `inline` and `thread` within a stated tolerance.

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

`play` is safe from any thread. Called on the render thread it starts the engine voice
in the call, as `engine.play` does today. Called from another thread it returns a
`Voice` at once, and the frame hook starts the engine voice, so the single-threaded
contract of `AudioEngine` holds; `voice.stop()` before the hook runs cancels the start.
A sound started from a physics callback is therefore at most one frame late, plus the
device buffer. An event carries its simulation `time`, and a later phase can offset the
voice start inside the mixer block to remove the frame.

The arguments the games use today are accepted: `play(source, at=, gain=, rate=,
priority=, loop=, emitter=)`, with `emitter` an `omi_audio` `AudioEmitter` for a
positional profile. Further:

```python
audio.listener = platform                   # default: the context's camera
audio.muffle = 1.0                          # everything, as under water or on a pause screen
audio.engine                                # the AudioEngine, render thread only; the escape hatch
```

`OpenGLContext.testing` gains `RecordingAudio`, an `Audio` that plays nothing and records
each `play` call, so a game's tests assert on sounds without a device or a fake engine.

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

### 1. A ball rolls down the stairs (5 lines)

```python
class StairsContext(Context):
    initialPosition = (0, 3, 10)

    def OnInit(self):
        stairs = self.sceneLoader.load_now('stairs.glb').result.group
        ball = self.sceneLoader.load_now('ball.glb').result.group
        self.sg = sceneGraph(children=[Background(), DirectionalLight(), stairs, ball])
        body = self.physics.add_dynamic(ball, translation=(0, 4.5, -2),   # the top of the stairs
                                        mass=2.0, restitution=0.4)
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

### 2b. The same, reacting on the physics thread (+1 line)

```python
        body.addEventHandler('hit', function=self.OnBallHit, above=1.0)

    @Context.physics_callback
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
| a reaction inside the tick | the same, with the handler marked `@Context.physics_callback` |
| a world setting | a field on `PhysicsDefinition` |
| something the service lacks | `physics.run(fn)` against the raw world |

## Migrating the games and demos

The projects read below were surveyed in the main trees, not in worktrees. Each is moved
in phase 7, after the API it needs exists, and each keeps its own checks green at every
commit. Line references are to the code as surveyed.

### marble-demo and the demos that use `DemoScene`

Today. `DemoScene` (`game.py:132`) wraps a `PhysicsManager`. `OnIdle` (`run.py:335-350`)
clamps `dt` to 0.05 and calls `game.advance`, which sets gravity from the tilt rig
(`game.py:227`), runs the `KinematicAnimator`s that move the box spawners, steps the
scene and updates the controller. The controller needs every contact of every step
(`controller.py:378`), resets the marble by writing `position`, `linear_velocity` and
`angular_velocity` (`controller.py:553-556`), and sand and water write per-body damping
(`sand.py:116-125`, `water.py:219-232`). Pair friction is set per marble and surface
(`materials.py:120-126`). Replay and recording depend on the lockstep.

Changes.
- `mode='inline'` with a fixed step; the `run.py` clock moves into the frame hook.
- `physics.gravity = ...` each frame; `body.drive(pose)` in place of each
  `KinematicAnimator`; `body.linear_damping`; `physics.materials.pair(...)`.
- The controller's contact handling becomes physics callbacks, called per step.
- The reset becomes `set_transform` and `set_velocity`.
- `DemoScene` is deleted. Its other callers (`CollisionYard`, `AudioYard`, the physics
  tutorials) move first, since they are the shortest.

### glisteel

Today. One main-thread loop. `Session.advance` (`session.py:581`) accumulates real time,
capped at `MAXIMUM_CATCHUP` 0.1 s, and runs fixed steps of 1/120 s. Each step runs the
driver, `car.update` (a `RaycastVehicle` applying forces), `physics.step`, then
`impact_on` reads that must happen before the next step (`session.py:795`, `:912`).
`trace.drive` runs it with no window. The world (`world.py:1028`) takes its colliders
from `HeightFieldColliders`, `RoadColliders` and `PropColliders`, updated from the
camera in `RaceWorld.stream` (`world.py:1147-1151`). Traffic is kinematic boxes placed,
with their velocity written, every frame (`traffic.py:1003-1022`). Poses reach the scene
by hand (`Car.follow`, `car.py:224-243`). Audio is a `VehicleSoundtrack` node in `sg`
plus `impact.play()` inside the step (`session.py:811`).

Changes.
- `Session` holds a standalone `Physics` (`inline`, 120 Hz, `maxCatchUp` 0.1), so
  `trace.drive` and the diagnostics need no context; the game's context uses its own.
- The driver, `car.update` and the `impact_on` reads move into `before-step` and
  `after-step` callbacks. The step, its order and its length are unchanged.
- The three collider classes become collider sources.
- Traffic becomes `add_kinematic` with `body.drive(pose)`.
- `Car.follow` and the traffic `_follow` go: the car and traffic nodes are the bodies'
  nodes, and the chase camera reads the car body's node so both share one pose.
- The `RaycastVehicle` keeps using the raw world through `physics.world` in inline mode.
- `sound.hit` calls `audio.play`; the soundtrack node stays.

Acceptance. `trace.drive` on each scenario returns the numbers it returned before the
change.

### twig-bb

Today. Two worlds. The map world (`collision.py:82-86`) is one static trimesh cooked from
the drawn triangles, with a `SurfaceIndex` from triangle to material; it is never stepped,
and every character and cast is a synchronous query against it. The player and each bot
are a `CharacterController` (`walkers.py:100`, `viewer.py:1759`). Hitscan and sight
queries (`combat.py:153,214,239`, `projectiles.py:478`, `blast.py:109`) are synchronous and
come back with the body and triangle hit. Combatants are staged into the map world for each
query by writing `collider_shape` (`combat.py:307-406`). The jump-pad world
(`jumppads.py:346`) is a second, zero-gravity world of trigger volumes, stepped by hand.
Projectiles are numpy arrays swept by ray. `OnIdle` (`viewer.py:1830-1891`) orders the
player's walker, the pushes, then the rules, with a variable `dt`. Audio is
`engine.listen(platform)` and `engine.play(clip, emitter=, position=, gain=, priority=)`
(`combatsound.py:475-562`), with an underwater submerge each frame.

Changes.
- The map world is `add_static(proxy=Proxy.trimesh(points, indices))` with `colliders`
  set to `none`; twig-bb keeps its `SurfaceIndex` and reads the triangle from `RayHit`.
- The player and the bots are `add_character`. Their update is the frame hook's, ahead of
  `rules.advance`, so the order in `OnIdle` holds.
- `raycast` and `line_of_sight` become `physics.raycast(..., skip=body)`, which includes
  characters, so the stage and unstage code and its direct `collider_shape` writes go.
  `raycast_many` serves the projectile sweep.
- The jump pads are `add_trigger` volumes in the one world, and their push uses a
  synchronous `overlap`; the second world goes.
- No worker thread starts: nothing in twig-bb is dynamic.
- Audio: `audio.listener = platform`, `audio.play(clip, at=, gain=, priority=, emitter=)`,
  and the submerge through `audio.engine`.
- Its tests that build a bare `PhysicsWorld` build a standalone `Physics` instead.

### openglcontext-forest

Today. The forest uses the engine's walker: `PhysicsWalkMixin` and `terrainwalk.py` are
engine code around `CharacterController`, zone gravity and collider sources. What it does
not use is the physics world for its ground. The world is empty; the ground and trunks
are numpy arrays resolved by `resolveTerrain` (`terrainwalk.py:510-541`) in substeps of
0.35 m, and rocks arrive through `add_collider_source(scene.rocks.mounds_near)`, called at
every substep (`terrainwalk.py:259-271`). The module says why: a landscape of kilometres
is millions of triangles as a mesh, and the engine has no collider that answers
height-field and many-cylinder queries as a body. So a rigid body dropped in the forest
falls through the ground and ignores the trees. The gap is the engine's, and the fix
belongs there. `OnIdle` steps the walker by wall-clock time capped at 0.05 s and redraws
every frame while walking. There is no audio. `run.py` calls `init_walk`,
`add_collider_source` and `setupPhysics(enable=True)` (`run.py:179-183`).

Changes. The engine gains two colliders (phase 5):
- `Proxy.heightfield(field)`, a static body whose shape answers height and normal
  exactly from the same `HeightField` the renderer draws, for characters and for dynamic
  bodies alike. It needs a `heightfield` shape in `omi_physics.model.Shape` and its
  collision against spheres, capsules, boxes and hulls.
- `physics.add_static_instances(proxy, positions)`, one proxy at many places with a grid
  broadphase, for tree trunks, and rock mounds as a body source around the focus.

The forest then builds its world from those, the walker is a `Character` in it, and the
three calls in `run.py` become the walk movement mode. Dynamic bodies roll on the ground
and strike the trunks, and the demo can show it: a keyed ball or log thrown from the
camera, and pushed by the walker. The mixin and the analytic substep path go once nothing
else uses them. The redraw each frame while walking becomes a redraw while the character
moves, falls or has input. The walker stays on the render thread, so `mounds_near` and the
`AsyncStreamer` threads share data as they do today.

### hill-runner

Today. No `omi_physics`. The runner's gravity is a constant integrated in closed form
(`runner.py:19,201-204`), `Game.advance` substeps at 1/120 s and stops at the first hit
(`game.py:90-116`), and the hit rules are bands, lanes and forgiveness (`game.py:148-194`).
The ground is the game's own `Landscape.footing`, built from the tiles the worker
processes make. Tests pin the jump arc (`test_runner.py:90,102,166`) and the order of
events inside a frame (`test_game.py`). The plan (`plans/IMPLEMENTATION.md`) and README give
no reason for hand-rolled physics; the rules were written as plain objects with
deterministic tests, and the engine's physics was not used. Audio is
`Sounds(audioscene.engine_for(self))` (`app.py:123`), with `play(path, gain, rate)`, a
looping music voice with a priority, a muffle for the pause screen (`sound.py:38-55`) and
footsteps (`session.py:91`).

Audio moves in phase 6: `Sounds` takes `self.audio`, calls
`play(..., rate=, priority=, loop=)`, sets `audio.muffle`, and loses its `None` checks
because a disabled `Audio` returns inert voices. `tests/test_sound.py` uses
`RecordingAudio` in place of its fake engine. Calls on the render thread start at once.

The maintainer's decision (9) is that the runner becomes a character in the engine's world,
and that audio moves whatever else happens. The engine features that make this ordinary,
and not special to this game, are in [CHARACTER-LOCOMOTION.md](CHARACTER-LOCOMOTION.md):
land as a collider, an exact jump, slide and knock-down states, a clip map and locomotion
driver, a follow camera that avoids the world, and keys for a third-person character. That
plan lists the steps for hill-runner: audio, then the land and barriers as bodies with the
runner still the game's, then the runner as a character, then the engine's animation and
camera in place of the game's. Its acceptance is that the pinned jump arc, the event order
and the pilot's runs pass unchanged.

## Process mode (deferred)

Not part of the phases below until a game needs it. The rules in Design (plain-data
commands and events, ids with generations, no shared world) keep it possible without
changing the API. `mode='process'` would run the worker in a child process that imports `omi_physics` and
nothing else: no GL, no scenegraph. The protocol is the one the thread uses.

- Commands and events travel on a pipe as tuples of numbers, ids and arrays.
- Cooked shapes cross once, by content hash, through `multiprocessing.shared_memory`.
- The pose snapshot is two shared-memory buffers with a sequence number: the worker
  fills one while the frame hook reads the other.
- A physics callback and a `run` function must be module-level functions, which the
  child imports by the path `physics_callback` records. A method of the context or a
  closure is refused at registration with a message that says so.
- A child that dies is reported through `physics.error`; the window keeps drawing.

Two reasons to want it: Python-level work in a tick holds the render thread's GIL on
the GIL builds, and a crash in the native solver ends the child and not the window.
The second does not excuse the crash. The core-dump rule in the workspace
`CLAUDE.md` still applies.

Phase 0 measures the first reason before any process code is written. If a thread
holds 60 frames a second with 5,000 bodies on the GIL build, process mode waits for
a game that needs it, and the node does not accept `mode='process'` until then.

## Where the code goes

| path | holds |
|---|---|
| `events/handoff.py` | `Inbox` (any thread to a worker) and `Updates` (worker to render thread, coalesced); no GL, shared by physics and audio |
| `physics/service.py` | `Physics`, the facade `context.physics` returns |
| `physics/body.py` | `Body` and the command records it enqueues |
| `physics/worker.py` | the `Worker` protocol and its `Inline` and `Thread` forms, built on the existing `PhysicsManager` and `ThreadedSimulation` |
| `physics/colliders.py` | scenery to static bodies: the rules, the cooking queue |
| `physics/sources.py` | the collider-source protocol, and the focus the frame hook gives each source |
| `physics/collisionview.py` | the immutable, versioned collision view and the queries that run on it |
| `physics/character.py` | `Character`, the handle over `CharacterController`, and the frame-hook step |
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
- A `CollisionQuery` protocol that `PhysicsWorld` and the collision view implement.
  `CharacterController`, `raycast` and the sweeps take it in place of the world.
- The world's fixed-step loop reports each step to a `before-step` and an `after-step`
  hook, and tags every contact event with its step index (it already carries one).

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
- Each game keeps its own determinism check. glisteel's `trace.drive` reproduces its
  recorded numbers on a standalone inline `Physics`. twig-bb's determinism tests and
  marble-demo's replay pass with the same seeds.
- A stress test in thread mode adds and removes static colliders on every tick while the
  render thread casts rays and steps a character; the results match a single-threaded
  run of the same sequence.
- A script test for each tutorial under `tests/tutorials/physics/`, captured under
  the fixed-step clock.

## Phases

| phase | content | done when |
|---|---|---|
| 0 | Measure: frame time and tick time at 1,000 and 5,000 bodies, inline against thread, on the GIL build and on 3.14t; the idle cost of `ThreadedSimulation` today | numbers are in this plan |
| 1 | `Physics`, standalone and in the context. Inline with a fixed step, catch-up and `step(dt)`; thread; `Body`, commands, frame hook, `PhysicsDefinition`, `enable`, `set_config`, `run`, `gravity`, `drive`, damping, `world` (inline). `hit` events through the context's event system, journalled and compared on replay; tutorials 1 and 2 | tutorials 1 and 2 pass as written; an idle scene asks for no frame; a standalone inline `Physics` reproduces glisteel's `trace.drive` numbers; a recorded session replays with its events matched |
| 2 | Physics callbacks, `before-step` and `after-step`, per-step delivery in inline mode, `render.set`, `render.call`; the remaining event names; tutorial 2b | tutorial 2b passes; no handler holds a lock |
| 3 | Scenery as static bodies, glTF OMI bodies on mount, collider sources | the two cost tests pass; `physics_bounce.py` loses its `OnIdle` |
| 4 | Collision view, synchronous queries, characters, characters and dynamic bodies, the walk mode on characters | the concurrency stress test and the push, knockback and raft tests pass; twig-bb's walker tests pass on `Character` |
| 5 | `Proxy`, `cook`, `show_proxies`, materials, pair rules, gravity zones; `Proxy.heightfield` and `add_static_instances`; tutorials 3 to 5 | tutorials pass; a ball rolled over the forest's ground stays on it and strikes a trunk |
| 6 | `Audio`, `Voice`, thread-safe `play`, `RecordingAudio`, material sounds; tutorial 6 | `AudioYard._collide` deleted; hill-runner's audio moved |
| 7 | Migrations, in order: `DemoScene` callers and marble-demo, glisteel, twig-bb, forest, then hill-runner's physics by CHARACTER-LOCOMOTION.md. Then delete `DemoScene`, the public `ThreadedPhysicsManager` and `PhysicsWalkMixin` | each project's suite and determinism checks give the results they gave before; no caller of `manager.advance` outside the service |
| 8 | Deferred: `mode='process'`, taken up if phase 0 or a game shows the need | the same tests pass in every mode |

## Documentation to change

- `docs/physics.rst`: "Adding physics to a scene" is rewritten around the tutorials;
  `DemoScene` leaves the page.
- `docs/audio.rst`: `audio.play` leads; the engine-level section becomes reference.
- `docs/eventmodel.rst`: physics events and the thread rule.
- `docs/structure.rst` and the directory map in `CLAUDE.md`: `events/handoff.py`,
  the new `physics/` and `audio/` modules.
- `tests/tutorials/physics/`: the tutorials above, written as the `'''`-commentary
  files the doc build turns into pages.
- `docs/x3d.rst`: `PhysicsDefinition` as an extension node, and how the rigid-body worlds
  relate to `context.physics`.
- `docs/telemetry.rst`: physics events in the journal and their comparison on replay.
- `docs/navigation.rst`: the walk movement mode on characters, and the third-person
  character and boom camera.
- `docs/testing.rst`: `RecordingAudio` and the standalone inline `Physics`.
- Each migrated project's README or docs, where they describe how its world is stepped.
- `omi_physics/docs/ARCHITECTURE.md`: the command inbox and the idle block.
- `plans/PROJECT-PLAN.md`: a row for this plan, and a pointer from
  `COLLISION-EVENTS.md`, whose subscription layer this builds on.

## Decisions

Settled by the maintainer, 2026-10-25 and 2026-10-26:

1. A handler runs on the render thread unless its function is marked
   `@Context.physics_callback`.
2. `PhysicsDefinition` is one node. Its settings are the game's choices.
3. Assigning to `node.translation` does not move a body. `set_transform` does.
4. Physics events go through the context's event system and the telemetry journal from
   phase 1, so a replay can say whether it reconstructed a session.
5. `add_*` take physical properties as keywords and a starting `translation=` and
   `rotation=`.
6. X3D `RigidBodyCollection` stays its own model.
7. Characters and dynamic bodies interact in both directions.
8. Characters step on the render thread.
9. hill-runner's physics. The runner becomes an engine character and audio moves first, by
   the steps in [CHARACTER-LOCOMOTION.md](CHARACTER-LOCOMOTION.md). Stepping stones that
   put the world around the runner in first are taken where they help.
