# Collision events: subscribe to a body's collisions and get a callback

Status: **Partial** — 2026-09-24. Phases 1, 2 and 4 have landed, with phase
3's hits; the character controller, phase 5 and the games' migration are open.
See [What landed](#what-landed).

A game wants to be told when something hits something. Today the engine answers
only questions asked after a step, and it only remembers the last one. This plan
adds a per-step contact record to `omi_physics`, and on top of it an
OpenGLContext subscription API. A game registers a callback for one body, a set
of bodies or every body, and receives one event per collision on the main thread,
in step order, with the colliding scenegraph objects already resolved.

The use cases it is measured against:

- A gun hit. A hitscan shot is a raycast rather than a contact. A projectile is a
  body, and its contacts are ordinary contacts.
- A sound when a box hits the floor, at every frame rate, with no bounce lost and
  no thud repeated.
- Deciding whether an object breaks or bounces, either from how hard it was hit
  (after the solve) or before the solve so the blow can be ignored.
- A pickup, pressure plate or kill volume. These already have trigger events, and
  they move onto the same API.

## What there is today

### The contact record is one step deep

`PhysicsWorld.advance(real_dt)` (`omi_physics/world.py:604`) runs as many fixed
steps as the accumulator holds. Each step rebuilds `world.contacts`
(`world.py:917-918`), so after `advance()` only the **last** step's contacts are
left. `impact_on(i, above, skip_static, among)` (`world.py:258`) reads that list
and returns the heaviest blow on body `i` in that one step.

At a 120 Hz step and 60 fps, a frame is two steps. At 30 fps it is four, and a
ball that lands in the first step and is resting by the fourth has made no sound.
`docs/audio.rst:382-386` documents the limitation.

The callers show the cost of that:

| Caller | Pattern | Consequence |
|---|---|---|
| `OpenGLContext/bin/audio_demo.py:184-204` | `advance(dt)`, then `impact_on` for each ball | Bounces below 60 fps make no sound. Two balls meeting are reported for both, so the caller removes the duplicate by index order. |
| `glisteel/glisteel/session.py:539-563, 728, 831` | Its own fixed-step loop that calls `step()` directly, then `impact_on` after each step | Correct, but only because it copied the accumulator loop out of the world. |
| `marble-demo/.../controller.py:316-325` | Scans `world.contacts` after `scene.advance`, flipping `a`/`b` and the normal by hand | Only sees the last step. |
| `marble-demo/.../mechanisms/lever.py:185-192` | Calls `impact_on` from inside a *trigger* callback | Works only because trigger events are dispatched per step, after the solve. It uses a trigger to get a per-step contact hook. |
| `twig-bb/twig_bb/jumppads.py:329-375` | A separate trigger-only world with its own listener | Keeps its own `{index: volume}` map. |
| `openglcontext/tests/physics_triggers.py:45` | `add_trigger_listener(fn(kind, trigger, other))` | Keeps its own `{index: material}` map. |

Every caller keeps its own dict from body index to game object. The world already
holds that back-reference in `world.bodies[i]`, set by `PhysicsBody.register`
(`scenegraph/physicsbody.py:49-50`), and no caller reads it.

### What omi_physics already has

- `Contact` (`collide.py:46`) has `a`, `b` (`a < b`), `point`, `normal` (from A to
  B), `depth`, `normal_impulse`, `tangent_impulse` and `approach`, the closing
  speed along the normal recorded before the solve. There is one `Contact` per
  manifold point, so up to four per box/box pair.
- Trigger events are pushed, per step: `TriggerSystem.update` diffs overlap sets
  and `world.dispatch_trigger` calls every `fn(event_type, trigger, other)`
  (`world.py:826-834`, `triggers.py:26-45`). `stay` fires on every step.
- The solver keeps a warm-start cache keyed by `(a, b)` (`solver.py:101`, rebuilt
  each step). It is private, and filled only when `warm_start` is on.
- `ThreadedSimulation` (`threaded.py`) steps on its own thread and publishes a
  snapshot of poses only. Trigger listeners run on that thread, inside the world
  lock.
- `raycast.raycast` returns a `RayHit(body, distance, point, normal, triangle)`.
  It takes a `skip` set and nothing else, so there is no filter mask.

### Defects the design has to fix, not work around

1. Body indices are reused. `remove_body` puts the slot on a free list
   (`world.py:444-469`) with no generation. Removing a body clears neither its
   trigger overlaps nor its warm-start entries, so the next step reports a stale
   `exit` for a body that is gone, or a `stay` credited to the body that took the
   slot. A queued event that outlives a step has the same problem.
2. Impulses are not always filled. The default native path
   (`_solve_native_full`) writes `normal_impulse` / `tangent_impulse` back only
   when `warm_start` is on (`solver.py:336-343`). `tangent_impulse` is expressed
   in a basis (`solver._basis`) the contact does not carry.
3. A sleeping pair has no contacts. Pairs where neither body is an awake mover
   are not sent to the narrow phase (`world.py:912-916`). Diffing contact lists
   between steps would report a crate that falls asleep on the floor as having
   left it.
4. `Trigger.collisionFilter` is read by the model (`model.py:122`) and dropped by
   `add_body` and `omi_gltf.py:251`.
5. `CharacterController` resolves its capsule against static colliders without
   recording which body it touched (`character.py:435-491`), and it takes no part
   in triggers. A walking avatar produces no collision or trigger events.

## Design

There are two layers, split the way the rest of the physics stack is split.

`omi_physics` records, on every step, which pairs started, kept or stopped
touching, how hard, and where, and makes that record available two ways: to a
listener called inside the step, and as a log a consumer drains when it chooses.
It has no GL, no scenegraph and no threads of its own. Any application built on
the library gets it, whether or not it uses OpenGLContext.

OpenGLContext drains that log once a frame on the main thread, resolves indices
to `PhysicsBody` handles and their scenegraph nodes, and calls the subscribers.
That is what makes the threaded manager and the unthreaded one behave the same.

```
 step k:   narrow phase ─▶ solve ─▶ ContactTracker.update ──▶ step listeners (in-step, physics thread)
                                         │                 └─▶ ContactLog.append
 step k+1: ...                           │
                                         ▼
 frame:    PhysicsManager.advance ─▶ sync poses ─▶ log.drain() ─▶ CollisionEvents.dispatch
                                                                    (main thread, step order)
```

### Layer 1: `omi_physics` records every step

A new module, `omi_physics/contactevents.py`, holds the tracker, the event type
and the log.

#### Body references carry a generation

`PhysicsWorld` gains a `generation` column, incremented by `remove_body`.
`BodyRef(index, generation)` is a small frozen, hashable value, and
`world.ref(i)` / `world.alive(ref)` convert and check. Events name bodies by
`BodyRef`, so an event that crosses a step boundary, a thread or a frame never
lands on the body that took a removed body's slot.

`remove_body` also retires the removed body from the trigger overlaps, the
warm-start cache and the contact tracker. Any pair it was in produces an `end`
event with `reason='removed'` on that step. This fixes defect 1 for triggers as
well as contacts, with a test either way.

#### One event per pair per step, not per manifold point

A game asks about "the ball hit the floor", never about the third of four
manifold points. `ContactTracker.update(world, contacts, dt)` runs after the
solve. It groups the step's contacts by pair and produces a `ContactEvent` for
each pair that has an event this step:

| Field | Meaning |
|---|---|
| `phase` | `'begin'` (touching now, not on the previous step), `'persist'` (touching on both steps) or `'end'` (touching on the previous step, not now) |
| `a`, `b` | `BodyRef`s, `a.index < b.index` |
| `point` | World-space contact point, weighted by each point's normal impulse, or the mean where every point's impulse is zero |
| `normal` | Unit vector from A to B, weighted the same way |
| `approach` | Largest pre-solve closing speed over the pair's points, in m/s. This is the value `impact_on` compares. |
| `impulse` | Sum of the points' normal impulses, in N·s. This is what a break threshold wants: it includes mass, which closing speed does not. |
| `friction_impulse` | Magnitude of the summed tangential impulse, in N·s. Used for scraping and sliding sounds. |
| `slip` | Tangential relative speed at the point before the solve, in m/s |
| `depth` | Deepest penetration of the pair's points, in m |
| `points` | Manifold point count |
| `step`, `time` | The world's step counter and simulation time when it happened |
| `reason` | Set on `end` only: `'separated'`, `'removed'`, or `'filtered'` when a pre-solve verdict dropped it (see below) |

Phase bookkeeping is a set difference over pair keys between consecutive steps,
the same technique `TriggerSystem` already uses. The difference is defect 3: a
pair whose two bodies are both asleep, or asleep and static, is carried forward
as touching without being re-tested. It ends only when one of them wakes and the
narrow phase stops finding it, or when one is removed. A crate that settles and
sleeps gets a `begin` and no `end` until something knocks it off.

`persist` is recorded for every touching pair on every step, and costs nothing
unless someone asked for it (see *Cost*). A subscriber that wants every blow,
including a box already on the floor that tips over and strikes it with an edge,
asks for `begin` and `persist` with an `above` threshold. That combination is
`impact_on`'s semantics, delivered for every step.

Defect 2 is fixed in the solver. `_solve_native_full` writes the accumulated
impulses back whether or not it warm starts, and the tracker converts the
tangential impulse to world space with the pair's own basis at the time it
builds the event. The parity test between the Python, `_solve_native` and
`_solve_native_full` paths gains the impulse fields.

#### Choosing what is recorded

Building an event for every pair in a 10,000-body pile, on every step, to tell
one game object about its own collisions is work the world should not do.
Recording has three levels:

- `world.contact_reporting = 'off'` records nothing, and the tracker does not run.
  This is the default while there is no listener and no log consumer, so a world
  nobody asks about pays nothing.
- `'flagged'` records pairs in which at least one body has its `report_contacts`
  column set (`world.report_contacts(i, True)`, or `report_contacts=True` on
  `add_body`). This is the equivalent of Box2D's per-shape contact-event flag.
- `'all'` records every pair.

The OpenGLContext layer sets flags from subscriptions: subscribing to a body
flags it, and subscribing to every body selects `'all'`. A game using only the
engine API never sets these by hand. `persist` events for a pair are materialised
only when a consumer asked for `persist`. Otherwise the tracker keeps the pair
key and nothing more.

On the native path the tracker reads the contact arrays `_solve_native_full`
already builds (`solver.py:293-296`) instead of `Contact` objects, and groups
them in numpy by pair key. A Cython twin in `_collide_native` follows if the
benchmark below says it is needed. It is the same arrangement the solver and
narrow phase use, behind the same `OMI_PHYSICS_NO_ACCEL` switch.

#### Two ways to receive them

```python
world.add_contact_listener(fn)       # fn(event: ContactEvent), called inside step()
world.contact_log                    # ContactLog: appended every step
events = world.contact_log.drain()   # list[ContactEvent | TriggerEvent], step order
```

A step listener runs inside `step()`, after the solve, on whatever thread is
stepping. It is for logic that must act before the next step, such as a lever
that throws when struck (the marble lever's trigger-hosted `impact_on` becomes an
ordinary contact listener) or a projectile removed on impact. It may read and
modify the world. It may not touch a scenegraph, a GL object or anything else
owned by the main thread, and the docstring says so.

The log is for everything else. It is a bounded deque: `ContactLog(maxlen=...)`
counts what it drops, in `.dropped`, the way `ThreadedSimulation.dropped` does,
so a consumer that stopped draining is visible rather than silent. Under
`ThreadedSimulation` the log is drained under the world lock, beside the pose
snapshot, and `latest()` gains a companion `drain_events()`.

Triggers move onto the same record. `TriggerSystem.update` produces
`TriggerEvent(phase, trigger, other, step, time)` with `phase` in
`'enter' | 'stay' | 'exit'` and `BodyRef`s, and appends it to the same log.
`add_trigger_listener` and its three-argument callback stay as the thin form
existing callers use. Defect 4 is fixed here: `add_body` stores
`Trigger.collisionFilter` and `TriggerSystem` honours it, so a pickup volume can
say it reacts to the player's filter system and nothing else.

`impact_on` keeps its meaning, which is the heaviest blow in the step just run,
and its docstring points at the listener and the log for anything that samples
once a frame. `glisteel` calls it once per step and stays correct.

#### Deciding before the solve (phase 4)

"Break or bounce" has two forms:

- After the solve, from `impulse`. The pane breaks when the blow exceeds its
  strength. The listener or the frame handler removes the pane and spawns the
  pieces. The ball has already bounced off it on that step, which at 120 Hz is
  8 ms of a bounce that should not have happened. For most objects that is
  acceptable, and phases 1-3 provide it.
- Before the solve. The pane is broken by the blow, so the ball should carry on
  through with its momentum. That needs a verdict before the solver sees the
  contact:

```python
world.set_contact_filter(fn)   # fn(pair: PairPreview) -> Verdict
```

`fn` is called for a pair on its `begin` step only, and only for pairs with a
flagged body. `PairPreview` carries the pair, `approach`, the points and normals,
and the effective mass along the normal. From the latter, `approach × mass` gives
the impulse the blow is about to deliver. `Verdict` is `SOLVE`,
`IGNORE_STEP` (skip this step, ask again next step) or `IGNORE_PAIR` (skip until
the pair ends). An ignored pair still produces its `begin` event, flagged
`solved=False`, so the frame handler that spawns the fragments hears about it.
One-way platforms and "ghost until the round starts" use the same hook.

This is Box2D's pre-solve callback, narrowed to the begin step because a verdict
per point per step is where that design's cost and its reentrancy rules come from.

### Layer 2: OpenGLContext subscriptions

A new module, `OpenGLContext/physics/events.py`, holds `CollisionEvents`, owned by
`PhysicsManager` as `manager.events`.

#### Subscribing

```python
from OpenGLContext.physics import events

def thud(hit: events.Collision) -> None:
    audio.play(clip, position=hit.point, gain=min(1.0, hit.approach / 4.0))

manager.events.subscribe(thud, body=crate, phases=('begin', 'persist'), above=0.5)
manager.events.subscribe(on_any_hit, phases=('begin',))              # every body
manager.events.subscribe(on_pickup, body=pad, kinds=('trigger',), phases=('enter',))
manager.events.subscribe(on_glass, body=pane, among=projectiles, above=0.0)
```

`subscribe(callback, *, body=None, among=None, kinds=('contact',), phases=('begin',), above=0.0, skip_static=False)`
returns a `Subscription` with `.cancel()`.

- `body` is a `PhysicsBody`, the `Transform` it drives, a `BodyRef`, a raw index,
  or an iterable of any of them. `None` means every body.
- `among` narrows the other side, matching `impact_on`'s parameter of the same
  name for the same reason: "did I hit one of these".
- `kinds` selects from `'contact'`, `'trigger'` and `'hit'` (see *Hitscan*).
- `above` filters `begin`/`persist` contacts on `approach`. `end` events always
  pass, because an `end` has no blow to measure.
- `skip_static` is the same as on `impact_on`.

A subscription on a body ends when that body is removed, after its `end` events
are delivered. Callbacks are held **strongly**, and the `Subscription` is how
they are released. The input event manager holds callbacks weakly
(`events/eventmanager.py:174-196`), and a lambda subscribed there is collected
and silently never called, and an undelivered collision is the defect this plan
removes. See *Open questions*.

#### What a callback receives

`Collision` is oriented to the subscriber:

| Field | Meaning |
|---|---|
| `kind`, `phase` | As above |
| `body`, `other` | `PhysicsBody` handles (`world.bodies[i]`), or the raw `BodyRef` for a body registered without one |
| `node`, `other_node` | The `Transform` each body drives, for a handler that works in scenegraph terms |
| `normal` | Points from `other` into `body`, the direction `body` was pushed. The a/b flip every caller does by hand now happens once. |
| `point`, `approach`, `impulse`, `friction_impulse`, `slip`, `depth` | As on `ContactEvent` |
| `time` | Simulation time of the step, so a sound can be scheduled at the moment of the blow and not at the start of the frame |
| `solved` | False where a pre-solve verdict ignored the pair |

A subscription covering both bodies of a pair (a world-wide one, or
`body=balls`) receives that pair **once**, oriented to the lower-indexed body it
covers. The audio demo's `other < ball.index` de-duplication moves into the
engine.

#### When callbacks run

`PhysicsManager.advance` steps, syncs poses, drains the log and dispatches, in
that order. Handlers therefore see the scene in the pose the frame will draw, run
on the main thread, and run in step order. `ThreadedPhysicsManager.advance`
drains the events published with the snapshot it adopts. Both managers behave the
same, and a test holds them to it.

An exception in one callback is logged with the subscription and the event, and
does not stop the rest of the frame's dispatch. This follows
`EventManager`'s handling of a failing handler.

`subscribe(..., immediate=True)` registers a step listener instead of a frame
subscriber, for logic that must act between steps. On a `ThreadedPhysicsManager`
it raises: an immediate callback there runs on the physics thread, and a caller
who wants that uses `world.add_contact_listener` and says so.

#### Hitscan

A hitscan shot never touches the contact solver, and the shooter already has the
`RayHit` in hand when `raycast` returns. The target is the side that wants an
event. Every object that reacts to being struck, whether by a crate, a rocket or
a bullet, should need one handler, not two.

```python
hit = raycast.raycast(world, muzzle, aim, max_distance=RANGE, filter=shots)
if hit is not None:
    manager.events.report_hit(hit, source=player, direction=aim, impulse=4.0, payload=weapon)
```

`report_hit` delivers a `Collision` with `kind='hit'` and `phase='begin'` to
subscriptions covering `hit.body`, oriented the same way. Its `approach` is the
round's speed and its `impulse` is what the caller passed. It applies the
impulse to the body at the hit point when one is given, so shooting a crate
pushes it. The event is queued with the step's events and delivered with the
frame's dispatch, in order. It is not called back re-entrantly from inside the
shooter's own code.

`raycast`, `raycast_many` and `bodies_along` gain `filter: CollisionFilter | None`.
This is the same filter a collider carries, so "shots pass through triggers and
the shooter's own team" is data. twig-bb's stage/unstage of player capsules
(`combat.py:306, 395`) is a separate matter and is not changed by this plan.

A projectile that is a physics body (a rocket, a grenade) needs no special case:
its contacts are ordinary contact events. At the speeds such bodies reach, a
discrete step tunnels through thin geometry. That is `PHYSICS-COLLISION.md`'s
speculative contact work and is noted there. twig-bb's projectiles sweep with
raycasts for that reason and would report through `report_hit`.

#### The character controller

Defect 5. `CharacterController` records the body of each collider it pushes out
of during a move, and `PhysicsViewPlatform` reports those through
`CollisionEvents` as `kind='contact'` with `begin`/`end` phases. `body` is the
avatar's `BodyRef`. The avatar registers a kinematic proxy body for that purpose,
and the same proxy is what lets it enter triggers, which twig-bb's jump pads get
today by running a second world. The character's contacts have no solver impulse,
so `impulse` is zero and `approach` is the capsule's speed into the surface.

#### Scenegraph and file-format routing (phase 5)

X3D's *Rigid Body Physics* component already names this: `CollisionSensor`, with
a `contacts` eventOut and an `isActive` output. A `CollisionSensor` node is a
subscription made from a file. Routed from its eventOuts, it plays a sound, lights
a lamp or opens a door with no Python at all. The `physicsbody.py` bodies become
VRML-addressable as part of it.

For glTF, a node-level `OGLC_hook` kind (`GLTF-ENGINE-HOOKS.md`) is the natural
carrier, for example `{"kind": "trigger", "action": ...}`. That design is left to
phase 5. The loader does not yet build physics bodies from `OMI_physics_body`
(`physics/gltf_world.py` names `omi_gltf` in its docstring and never imports it),
which is a precondition recorded rather than solved here.

## Cost

The target is that a world nobody listens to pays nothing, and a game that
listens to a few hundred bodies does not see it in the step.

- `scripts/contact_events_bench.py`, following `scripts/multiview_bench.py`,
  measures the step with reporting `off`, `flagged` on 1%, 10% and 100% of
  bodies, and `'all'` with `persist` materialised, over a 1,000- and a
  10,000-box pile on both the Python and native paths.
- Acceptance: `off` is within noise of the current step. `'all'` without
  `persist` adds no more than 5% to a 1,000-box step on the native path. A
  regression beyond that is a failure of the benchmark's test, marked `serial`
  like the solver's own timing checks.
- The dispatch side is measured the same way: 1,000 events a frame to 100
  subscriptions, filtered by body through a dict from `BodyRef` to its
  subscriptions, not by scanning every subscription for every event.

## Work, in phases

Each phase is test-first. The failing test named first in each is the one that
has to go red before any code.

| Phase | Lands | First red test |
|---|---|---|
| 1: Record every step (`omi_physics`) | `BodyRef` + generation, and `remove_body` retiring overlaps, cache and tracker entries. `ContactTracker`, `ContactEvent`, `ContactLog`, `add_contact_listener`, reporting levels and flags. Native impulse write-back. `TriggerEvent` into the log, and `Trigger.collisionFilter` honoured. | A ball dropped on a floor and advanced at 1/30 s frames with a 1/120 s step produces one `begin` per bounce, and the count equals the bounces a 1/120 s frame loop sees. This is the defect reported by the user. |
| 2: Subscribe (OpenGLContext) | `physics/events.py`: `CollisionEvents`, `Subscription`, `Collision`. Dispatch in `PhysicsManager.advance` and `ThreadedPhysicsManager.advance`. Resolution through `world.bodies`. `immediate=True`. | A subscriber on one crate receives its landing on the floor once, with `normal` pointing up into the crate, whichever of the pair has the lower index. |
| 3: Hits and the avatar | `report_hit`, `filter=` on the raycasts, and character-controller contacts with its proxy body in triggers. | A shot reported with `report_hit` reaches the target's subscription in the same dispatch and the same order as a crate landing on it in that frame. |
| 4: Pre-solve | `set_contact_filter`, `PairPreview`, `Verdict`, and `solved=False` events. | A ball against a pane whose filter returns `IGNORE_PAIR` keeps its velocity through the pane, and the pane's subscriber still receives the `begin`. |
| 5: Authored | `CollisionSensor` node and routes, and a glTF node hook kind. | A `.wrl` with a `CollisionSensor` routed to a `Sound`'s `startTime` plays on impact with no Python. |

Callers move over in the phase that makes their replacement possible, each in its
own repository and commit:

- `bin/audio_demo.py`: `subscribe(..., body=balls, above=IMPACT_FLOOR)`. No
  `impact_on`, no de-duplication, and no lost bounces at 30 fps. Phase 2.
- `tests/physics_triggers.py` and its tutorial: `kinds=('trigger',)` with nodes
  in hand, not an index dict. Phase 2.
- marble-demo: `controller._touches` becomes a subscription on the marble, and the
  lever's effect becomes an immediate subscription. Phase 2.
- glisteel: the crash and bump watches become subscriptions with `among=traffic`
  and `skip`. The session keeps its own step loop, and the log is drained per
  frame from it. Phase 2.
- twig-bb: the jump pads' second world goes once the avatar enters triggers, and
  `combat` reports through `report_hit`. Phase 3.

## Demonstration

The workspace's convention is that a feature's demo is an installed `oglc-*`
command. `oglc-physics-events` covers the use cases above in one scene:

- crates dropped on a floor, each thud placed and scaled by `approach`, correct
  with the frame rate capped at 20 fps (a key toggles the cap);
- a glass pane that shatters on an impulse threshold, with the post-solve form on
  one pane and the pre-solve form on another, side by side;
- a hitscan gun from the camera that knocks crates with `report_hit`;
- a pressure plate that opens a door on `enter` and closes it on `exit`.

The scene has a `tests/` twin that captures as a visual-regression reference, as
the other physics demos do.

## Documentation

- `docs/physics.rst`: a new section, *Responding to collisions*, covering the
  subscription API, the event fields with units, phases and `above`, when
  callbacks run, hits, and the reporting levels' cost. The triggers paragraph
  points to it.
- `docs/audio.rst:347-386`, *Playing a sound when two things collide*, is
  rewritten on `subscribe`. The one-step-per-frame caveat is removed, because it
  no longer holds.
- `docs/eventmodel.rst`: a paragraph placing physics events beside input events
  and timers, and why these are held strongly.
- `tests/physics_triggers.py` commentary, which generates the tutorial.
- `omi_physics`: `README.md`'s `impact_on` section gains the listener and the
  log. `docs/PIPELINE.md` gets the tracker stage in its stage table.
  `docs/ARCHITECTURE.md` gets events and `BodyRef`.
- `plans/PHYSICS-COLLISION.md` §5: triggers "emit into the event system" points
  here.
- `CLAUDE.md`'s directory map: `physics/events.py`.

## What landed

2026-09-24, on the `collision-events` branches of omi_physics and OpenGLContext.

omi_physics (`contactevents.py`, and `world.py`, `solver.py`, `triggers.py`,
`broadphase.py`, `raycast.py`, `threaded.py`, `omi_gltf.py`):

- `ContactTracker`, `ContactEvent`, `ContactLog`, `TriggerEvent`,
  `add_contact_listener` / `remove_contact_listener`, `contact_reporting`
  (`'off'` / `'flagged'` / `'all'`), `report_contacts(i)` and `add_body(...,
  report_contacts=True)`, `report_persist`, `step_count`. The phase 1 red test
  is `test_a_slow_frame_rate_hears_every_bounce` in
  `tests/test_contact_events.py`, run on both solver paths.
- `BodyRef` is a frozen dataclass rather than a named tuple, since a tuple's
  `index` method and the field of that name collide for a type checker.
  `world.ref(i)`, `world.alive(ref)` and `world.handle_of(ref)`.
- `remove_body` ends the body's pairs (`reason='removed'`), exits its triggers
  at once, and drops its warm-start entries (`SequentialImpulseSolver.forget`).
- The compiled solver writes impulses back without warm starting, records
  `Contact.slip`, and hands the tracker its arrays (`last_batch`).
- `Trigger.collisionFilter` is read from glTF, written back and honoured.
- The broadphase pairs a kinematic body with a trigger, so a lift or a proxy
  enters trigger volumes; a pair with no dynamic body is not solved.
- `raycast`, `raycast_many` and `bodies_along` take `filter=`.
- `ThreadedSimulation.latest_and_events()` and `drain_events()`.
- Phase 4: `set_contact_filter`, `PairPreview`, `Verdict`, `solved=False`.
  `IGNORE_STEP` leaves the pair untracked until a step it is solved on, so it
  produces no event; the `'filtered'` end reason is not needed and does not
  exist. `PairPreview.mass` is the linear reduced mass, with no rotational
  term.
- Cost, measured on a resting pile of 300 boxes kept awake: `'all'` adds 1.5%
  to the step and `'all'` with persist 4.8%. `tests/test_contact_events_cost.py`
  holds the 5% budget as a `serial` test, measured as the tracker's share of the
  step rather than as a separate benchmark script.

OpenGLContext:

- `physics/events.py`: `CollisionEvents`, `Subscription`, `Collision`,
  `HitEvent`, `report_hit`, `immediate=True` (contacts only). A subscription
  raises the world's reporting level and never lowers it.
- `PhysicsManager.events`, `remove(body)`, `handle(ref)`, `body_for(transform)`;
  both managers dispatch after writing poses.
- `bin/audio_demo.py` and `tests/physics_triggers.py` subscribe. The audio
  yard's test compares thuds at 20 and 120 fps.
- `oglc-physics-events` (`bin/physics_events_demo.py`), with its yard tested
  in `tests/unit/test_physics_events_demo.py`, and `tests/physics_events.py`,
  its twin in the visual suite, which plays a scripted opening in fixed steps
  before the first frame so the capture shows the struck scene. The reference
  is on the reference-images repository's `bless/physics-events` branch.
- Documentation: `docs/physics.rst` *Responding to collisions*,
  `docs/audio.rst`, `docs/eventmodel.rst`, `docs/documentation.rst`, the
  omi_physics README, `docs/PIPELINE.md` and `docs/ARCHITECTURE.md`.

Still open:

- The `tests/reference_images` gitlink names the reference repository's
  `bless/physics-events` branch (`aeefc92`), which has to reach that
  repository's `main` and GitHub. Nothing is pushed.
- openglcontext's typecheck gate fails on the zone work (`zonepass.py`,
  `zonelayers.py`, `zoneprobes.py`, `physics/zones.py`, `scenegraph/zone*.py`,
  `loaders/gltf/imagebased.py`, `audio/scene.py`), which was being edited,
  uncommitted, when this merged. Nothing in this plan's files is in it.

- Defect 5, the character controller: landed 2026-09-25. The avatar's body is
  a *sensor* (decided: it neither pushes nor is pushed).
  `CharacterController(..., body=True)` and `PhysicsViewPlatform(...,
  body=True)` carry a kinematic sensor capsule that enters triggers and whose
  touches with dynamic bodies are reported unsolved, and the controller
  reports what the capsule begins and stops touching in the static world
  (`world.report_contact_events`). Building it found an EPA defect, fixed in
  omi_physics: a capsule 2 cm into a long flat box was reported as not
  touching it, because GJK's simplex reached EPA wound either way and a face
  through the origin had its normal turned round.
  twig-bb's jump pads keep their own sensor world: its spec (§5.6) tests a
  player-sized box against each volume, not the walking capsule, and its map
  world is a static collision world that is never stepped.
- Phase 5, authored events.
- The games, as far as each could go:
  - marble-demo: the controller listens to the marble's contact events and
    keeps each pair's hardest blow over a frame's steps, so a lethal blow in
    an early step of a slow frame is weighed
    (`test_a_lethal_blow_in_an_early_step_of_a_slow_frame_still_destroys`).
    The lever listens to its own paddle's contacts in-step; its trigger box is
    gone.
  - twig-bb: the jump pads' stand-in for the player is a kinematic body placed
    each frame, not a dynamic one woken by hand.
    Combat does not report through `report_hit`: its shots land on combatants
    staged as capsules for one raycast, not on bodies anything subscribes to.
  - glisteel is unchanged. It steps the world itself so its controls are
    sampled per step, and asks `impact_on` after each step, so it already
    hears every step; its crash and bump watches were also being edited in
    the main checkout, uncommitted, at the time.
- Dependency floors: done 2026-09-25. omi_physics' `develop` is 0.4.0, the
  version that will carry this API, and OpenGLContext, marble-demo and
  twig-bb require `omi_physics>=0.4.0`. OpenGLContext's own `develop` still
  says 3.0.0a5, which is published, so its next release needs a `--bump`.
  The workspace root's `uv.lock` is regenerated with its next change.
- Strong versus weak callback references. The plan holds them strongly and
  returns a `Subscription`, which differs from `addEventHandler`. The
  alternative is weak references with an `owner=` that ties a subscription's life
  to a game object.
- Whether `persist` should be deliverable at all without an `above` threshold.
  Every resting pair on every step is a lot of calls, and no use case above wants
  it unfiltered.
- Whether the engine should also step physics from `DoEventCascade`, as
  `PHYSICS-COLLISION.md` §*The step* intended, so that dispatch happens in one
  place for every application. Today each application steps from its own
  `OnIdle`, and this plan dispatches from wherever `advance` is called.
