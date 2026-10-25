# A character runs across a landscape

Status: **L0 to L6 built; L7 in progress**, branch `physics-services`. This plan builds on the
characters of [PHYSICS-AND-AUDIO-SERVICES.md](PHYSICS-AND-AUDIO-SERVICES.md) and is the engine side
of moving hill-runner onto the engine's physics.

What landed:

- L0, D2. The controller integrates gravity exactly (`omi_physics` `492478c`).
- L1, D1. `add_ground(land)` over any `Ground`, with the optional `normal(x, z)`.
- L2, D3. `slide`, `knock_down`, `get_up`, `state`, `landed`, a slide that steers and ends, and a
  jump that follows the slope.
- L3, D4 and D5. `ClipMap` (`ual()` and `guess`), `Locomotion`, `measure_stride`, `oglc-gait`.
- L4, D6 and D7. `Facing`, `fit_to_height`, footsteps through `footstep` events and a material's
  `footstep=`; tutorials 1, 3 and 4 are `tests/tutorials/character/character_run.py`,
  `character_jump.py` and `character_footsteps.py`.
- L5, D8 and D9. `FollowCamera` look-ahead, damping and the obstacle sweep; `FollowMode` and
  `Context.follow`.
- L6, D10. `Character.run_along`, `hop_to` and `PathMover`.
- Docs: `docs/characters.rst`, `docs/navigation.rst`, `docs/physics.rst`.

Not done:

- D1's `ceiling=` and D11, surfaces overhead: the ground is a single-valued height.
- Tutorials 2 (a different animation set), 5 (a camera that stays out of walls) and 6 (running along
  a trail).
- L7. hill-runner's steps 2 to 4 and twig-bb's switch to `ClipMap` are work in those projects.

A developer who says "this character should run across this landscape with this
animation" gets that from the engine in a few lines. Today each game that does it writes
the same four things again: a collider for its ground, a mapping from what the body is
doing to a clip, a camera that follows, and the keys that move it. This plan finds what
the engine lacks for those four, and fixes it in the engine.

## The test

The finished program for a character on a landscape:

```python
class RunContext(Context):
    def OnInit(self):
        self.sg = sceneGraph(children=[Sky(), Sun(), Terrain(land)])
        self.physics.add_ground(land)
        hero = self.physics.add_character(model='hero.glb', animations='ual',
                                          position=(0, 0, 0), parent=self.sg)
        self.follow(hero)
```

`land` is any `Ground`: a `HeightField` from the terrain tutorials, or land computed
from a function. Four lines after the scene. The character collides with the land the
terrain node draws, plays idle, walk, run, sprint, jump, fall, land and crouch clips as it
moves, faces where it goes, leans on slopes, plants its footsteps, and the camera follows
from behind and is steered by the keys. Each line is an API this plan adds or completes.

## What exists

| piece | where | what it does now |
|---|---|---|
| capsule controller | `omi_physics/character.py` | move-and-slide, jump to a `jumpHeight`, crouch, fly, swim, step-up, slopes |
| rigged model and mixer | `character/model.py`, `mixer.py`, `humanoid.py` | load, layers, masks, cross-fades, speed per clip, bone names |
| gait for crowds | `character/wander.py` (`Gait`) | idle, walk and run layers weighted by speed, with a stride per clip |
| follow camera | `move/followcam.py` | fixed offset, hold, pull back with speed |
| ground | `scenegraph/vegetation/grid.py` (`Ground`), `terrain/heightfield.py` | a height at `(x, z)` |
| course along a road | `scenegraph/roadcourse.py` | station, nearest point and cross direction on a centreline |
| movement modes | `move/modes.py` | `WalkMode`, `FlyMode`, `SwimMode`, `FPSMode`, `ExamineMode` as nodes with key bindings |

## What the games build again

- hill-runner (`cues.py`): `pose_for` maps the runner's state to a clip name, a loop flag, a
  fade and a speed. A `CYCLE` table holds the seconds one cycle of each looping clip lasts, a
  quickening per metre a second keeps the feet on the ground, and `_slide_time` sets where in
  the Slide clip the body stands. `Footsteps` decides when a foot lands from distance run.
- twig-bb (`characters.py`): `Locomotion` picks a movement clip, `rate(clip, speed)` divides
  speed by a `CLIP_SPEED` table and clamps it to `RATE_RANGE`, and `ONE_SHOTS` names the clips
  that do not loop.
- the engine's `Gait` has strides per clip for the same purpose, for crowds only.

That is the same foot-sync arithmetic three times, in three tables, each measured by hand.

- hill-runner (`chase.py`, 162 lines) is a follow camera with look-ahead, sway damping, a
  speed pull-back, ceiling clearance and floor clearance. `FollowCamera` has only the pull-back.
- hill-runner (`app.py`, `_place_runner`) sets yaw from the trail, pitch from the fall of the
  ground and lean from sideways speed, on three nested transforms the game builds.
- hill-runner (`landscape.py`, `footing`) answers the ground height for the runner, and
  `runner.py` integrates its own jump in closed form so the peak does not depend on the frame
  rate. The engine's controller integrates by semi-implicit Euler (`character.py:768`), which
  does depend on it.

## Gaps and fixes

### D1. Land is not a collider

A `Ground` answers a height and nothing collides with it. The physics plan adds
`Proxy.heightfield` (its phase 5); this plan adds the call a developer makes and the shapes
a landscape needs.

```python
physics.add_ground(land)                          # any Ground; sampled as drawn
physics.add_ground(land, ceiling=roof)            # a second surface facing down
```

- `add_ground` makes a static body whose shape is the `Ground`, so a character, a rolling
  ball and a raycast all meet the surface the terrain node draws. What is drawn and what is
  collided cannot disagree, because both call `sample`.
- `Ground` gains `normal(x, z)`, with a default from finite differences, so slopes and
  sliding use the true surface.
- A ceiling is a second `Ground` facing down: the roof of a cave or a tunnel. A mesh that
  a height cannot describe (an overhang, a bridge) is a collider source of trimesh tiles,
  which the physics plan already provides.
- hill-runner's `Landscape` implements `Ground` with `sample(x, z) = footing(x, -z)`.

Test: a sphere dropped on a `HeightField` stops at `sample`, on 50 random points and slopes
up to 60 degrees, in inline and thread modes.

### D2. The controller's jump depends on the frame rate

The controller sets `vy = sqrt(2 g h)` for a `jumpHeight` `h`, so a developer already
declares a height. It then steps `vy -= g dt` and `position += vy dt`. The apex differs from
`h` by about `v dt / 2` and varies with the step.

Fix: integrate a constant acceleration exactly, `position += v dt - g dt^2 / 2` and then
`v -= g dt`, the form hill-runner uses (`runner.py:202-204`). Gravity in water, buoyancy
and terminal velocity keep their own terms.

Test: the apex and the time to land are within 1e-9 of `h` and `2 sqrt(2 h / g)` at steps of
1/30, 1/60, 1/120 and 1/240 s. hill-runner's pinned jump arc passes with `gravity=42` and
`jumpHeight=JUMP_PEAK`.

### D3. States a runner has and the controller lacks

The controller crouches, flies and swims. A runner also slides, is knocked down and gets up,
and lands. The animation needs all of them as state.

```python
hero.slide(duration=0.8, rise=0.3)     # low and carrying its speed; rises over the last 0.3 s
hero.knock_down(); hero.get_up()       # ignores input, speed 0; get_up restarts from a start speed
hero.state                             # an enum: STANDING, CROUCHING, SLIDING, AIRBORNE, DOWN, SWIMMING, FLYING
hero.addEventHandler('landed', function=fn)    # carries the fall speed
```

`slide` is a crouch that keeps momentum and decays by friction for its duration, with the
capsule low until the rise. `landed` is raised when the controller settles on the ground
after a step (it already decides "landed" at `character.py:545`) and reports the speed it
landed at, which is what picks a soft or a hard landing clip and a thud.

Test: a slide of 0.8 s keeps the capsule at `crouchHeight` for 0.5 s and rises over 0.3 s; a
knocked-down character moves no further under input; a fall from 2 m and from 6 m raise
`landed` with different speeds.

### D4. Animation is hand-mapped in every game

`Locomotion` is a GL-free object in `character/locomotion.py` that turns a character's
state into clips on a `CharacterModel`, and `ClipMap` says which clip plays each role.

```python
hero.animate(ClipMap.ual())                       # a shipped vocabulary
hero.animate(ClipMap.guess(model))                # roles found by name; unmatched roles reported
hero.animate(ClipMap(idle='Idle', walk=('Walk', 1.4), run=('Run', 3.8),
                     jump_up='Jump', jump_down='Fall', land='Land'))
```

A role is `idle`, `walk`, `run`, `sprint`, `crouch_idle`, `crouch_walk`, `jump_up`,
`jump_down`, `land`, `slide`, `fall`, `swim`, `down`, `get_up`, `death`. A role maps to a
clip name, or to a clip name and the speed in metres a second the clip was authored for.
`ClipMap.ual()` knows the Universal Animation Library names hill-runner uses (`Jog_Fwd_Loop`,
`Sprint_Loop`, `Jump_Start`, `Jump_Loop`, `Slide`, `Roll`, `Death01`). `guess` matches
lower-cased names against the role words and reports the roles it could not fill, with the
clips that were left over.

What `Locomotion` does each frame, from the character's speed, state and vertical velocity:
- weights idle, walk, run and sprint by speed, with the layers `Gait` already makes;
- sets each looping clip's rate to actual speed over authored speed, within a range, so feet
  do not slide;
- plays `jump_up` while rising and `jump_down` while falling, `land` on `landed`, and holds
  `slide` at a point set by the slide's progress, as hill-runner's `_slide_time` does;
- fades between roles over a time the map can override per role;
- takes an action on an upper layer by name, `hero.play_action('fire', layer='upper')`,
  which is twig-bb's arm layer.

`Gait` becomes the blend inside `Locomotion`, and hill-runner's `pose_for` and `CYCLE`,
twig-bb's `rate` and `CLIP_SPEED`, and the crowd's strides are all `ClipMap` data.

Test: a table of (state, speed) to (clips, weights, rates) with no GL; every clip name in
hill-runner's `CLIPS` resolves under `ClipMap.ual()`; a model with clips `walk`, `run`,
`idle` resolves under `guess`.

### D5. Stride is measured by hand

The strides and cycle lengths are numbers someone worked out by playing a clip against a
known distance (the note at the top of `wander.py`). `ClipMap` takes them, and the engine
should offer a way to get them.

```python
stride = measure_stride(model, 'Jog_Fwd_Loop')      # metres per second at rate 1.0
```

`measure_stride` samples the clip, finds the foot bone (`Humanoid` names it) and takes the
speed of the planted foot relative to the hips, which is the body's speed in that clip. A
clip with root motion reports the root's travel. A command, `oglc-gait model.glb`, prints
the numbers for every locomotion clip in a file.

Test: a synthetic rig whose foot moves at a known speed during stance returns that speed
within 2 percent; UAL's `Jog_Fwd_Loop` agrees with hill-runner's measured table within 5
percent.

### D6. Facing, grounding, lean

hill-runner builds yaw, pitch and lean transforms and fills them every frame. The engine's
character node does it.

- `facing` turns toward the move direction at `turnRate` radians a second, or toward the aim
  in strafing mode, and the node's yaw follows.
- `align_to_ground` (default true) pitches the body to the ground normal, eased, and
  `lean` rolls it into lateral acceleration by a factor; both default small and can be zero.
- `model` is fitted when the character is made: scaled so its bounds match the capsule's
  height and set so its feet are at the capsule's base, unless `fit=False`.

Test: a character on a 30 degree slope has its body pitched within 2 degrees of the slope
once eased; a model 3 units tall in a 1.8 m capsule is scaled by 0.6.

### D7. Footsteps

`Locomotion` raises `footstep` events from the gait's phase, with the foot, the surface point
and the physics material under it. `ClipMap` entries may give the clip times of the foot
contacts; without them they fall at the half cycle. A material's `footstep=` clip (the
physics plan's material `sound=`) is played by default and a handler replaces it.

```python
hero.addEventHandler('footstep', function=self.OnFootstep)
```

hill-runner's `Footsteps` class and its distance arithmetic go.

Test: at a speed of 10 m/s and a 0.933 s cycle, two events a cycle, evenly spaced, at the
times the map names.

### D8. A follow camera that avoids the world

`FollowCamera` has a fixed offset and a pull-back. A third-person game also needs, and
hill-runner's `Chase` builds, look-ahead, damped following, and not standing inside the
scenery.

- `look_ahead`: the look point moves ahead along the target's velocity by seconds.
- `smooth_time`: critically damped following, the model `Chase` uses (`SMOOTH_TIME`).
- obstacle avoidance: a `physics.sweep_sphere` from the look point to the wanted camera
  position shortens the arm to the first hit, and eases back out. The ceiling and floor
  clearances of `Chase` are this sweep with a radius and a minimum height, so tunnels and
  hillsides work without per-game code.
- `constrain(fn)`: a hook for a game's own rule, such as the cave's side step.

`Chase` becomes a `FollowCamera` with settings and one constraint.

Test: a camera behind a character walking at a wall comes in to the sweep's hit and out
again; a camera in a tunnel stays below the ceiling by the clearance; no frame has a step
of more than `max_step` metres.

### D9. Keys that move a third-person character

The movement modes are nodes, so the settings screen and the key-binding page list them. A
third-person character needs a mode beside `WalkMode`.

- `FollowMode` maps keys, the left stick and the d-pad to `set_move` relative to the camera's
  yaw, jump to the jump key, sprint and crouch to their keys, and the mouse or right stick to
  the camera's orbit around the character.
- `Context.follow(character)` binds the follow camera and the mode in one call. It adds one
  method to `Context` that delegates to `move/followmode.py`.
- An auto-running game sets a constant forward and takes only steering from the keys; the
  mode takes `forward=` for that.

Test: with the camera yawed 90 degrees, the forward key moves the character along the
camera's forward; the bindings appear in the key-binding page.

### D10. Running along a trail

A game with a course rather than open land wants the character to follow a line and hop
between parallel lines.

```python
hero.run_along(course, speed=10.0)         # a RoadCourse; the move is along its tangent
hero.hop_to(lane_offset, over=0.16)        # the lateral target; glides across
```

`run_along` sets the move direction from the course at the character's station and steers
back toward the lateral target. The height still comes from the land and the jump from the
controller. `RoadCourse` supplies station and cross direction, so no new line type is added.

Test: a character on a bent course keeps within 5 cm of its lane for 200 m at 10 m/s; a hop
of one lane takes 0.16 s.

### D11. Surfaces overhead

A tunnel or cave has a roof the character's head and the camera must meet. D1's `ceiling`
covers a single-valued roof. hill-runner's tunnel is a bored mesh (`tunnel.py`), which the
physics plan's collider sources serve as trimesh tiles next to the heightfield. The
character's step reads both through the collision view.

Test: a character jumping under a tunnel roof stops at it; a camera in the tunnel is below
it.

## The tutorials

1. A character runs across a landscape: the four lines above.
2. A different model and a different animation set: `animations=ClipMap(...)`, and
   `ClipMap.guess` with its report of unmatched roles.
3. Jump, slide and land: `hero.slide()`, `landed` and a hard-landing clip.
4. Footsteps with a sound per surface: materials with `footstep=`.
5. A camera that stays out of walls.
6. Running along a trail: `run_along` and `hop_to`.

Each is a script under `tests/tutorials/character/` captured under the fixed-step clock.

## hill-runner on the engine

Target: the runner is a character in the engine's world, under the engine's controller and
camera, animated by the engine's locomotion, with the game's course and rules around it.
Audio moves first and independently of everything below (physics plan, phase 6).

| hill-runner today | on the engine |
|---|---|
| `runner.py`: jump, slide, knock-down, hop, speed | `add_character` with `gravity=42` and `jumpHeight=JUMP_PEAK`; `slide`, `knock_down`, `get_up`, `run_along`, `hop_to`; the game keeps acceleration and the lane rules |
| `cues.py`: `pose_for`, `CYCLE`, `Footsteps` | `ClipMap.ual()` and the `footstep` event; `sounds_for` stays, since it maps game events to sounds |
| `chase.py` | `FollowCamera` settings plus one cave constraint |
| `app.py`: `_place_runner` | the character's node |
| `landscape.py`: `footing` | `Landscape` as a `Ground` given to `add_ground`, with the tunnel and crevice tiles as collider sources |
| `game.py`: bands and forgiveness | the character's `hit` events against barrier bodies; forgiveness is a filter on contact depth and approach speed |

Steps, each leaving the game running and its tests green:
1. Audio on `context.audio`.
2. The land and the barriers become bodies: `add_ground(Landscape)` and each barrier a static
   body with its proxy. Coins and jewels become triggers. Spilled coins and tumbling logs are
   dynamic bodies that the rules do not read. The runner is still the game's.
3. The runner becomes a character; `Game.advance` runs in `before-step` and `after-step`
   callbacks at 1/120 s; the rules read `hit` events instead of computing bands.
4. The animation, footsteps and camera move to the engine's, and `pose_for`, `Footsteps`,
   `_place_runner` and most of `chase.py` are deleted.

Acceptance, unchanged from today: the jump arc tests (`test_runner.py`) pass with the same
numbers; the events of a frame arrive in the order `test_game.py` pins; the pilot runs
generated courses to 3,500 m under every fork policy (`test_pilot.py`); `test_cues.py` and
`test_chase.py` are replaced by the engine's tests of the same behaviour, and the game
keeps one test that its clip names resolve.

Risks. The feel of the jump and landing depends on D2 and D3 matching the closed form, which
is tested before step 3. The forgiveness rules judge a hit by where the body overlaps a band,
and a shape contact must give the same verdicts; the pilot and a recorded set of 200 hits
from the current rules decide that. If the verdicts differ, the rules keep the band test and
the engine events only report.

## Other games

twig-bb's `Locomotion`, `rate` and `CLIP_SPEED` become a `ClipMap` and the engine's
`Locomotion`; its weapon arm layers stay its own, played with `play_action`. The crowd's
`Gait` strides read from a `ClipMap`. glisteel is not affected.

## Phases

| phase | content | depends on | done when |
|---|---|---|---|
| L0 | D2: exact ballistic integration | none | apex test passes at four steps; hill-runner's jump numbers hold |
| L1 | D1 and D11: `add_ground`, `Ground.normal`, ceiling | physics phase 5 (`Proxy.heightfield`) | the dropped-sphere test passes |
| L2 | D3: slide, knock-down, landed, `state` | physics phase 4 | the state tests pass |
| L3 | D4 and D5: `ClipMap`, `Locomotion`, `measure_stride`, `oglc-gait`; tutorial 2 | none | the table test passes; UAL resolves hill-runner's clips |
| L4 | D6 and D7: facing, grounding, lean, fit, footsteps; tutorials 1, 3, 4 | L2, L3 | tutorial 1 passes as written |
| L5 | D8 and D9: camera, `FollowMode`, `Context.follow`; tutorial 5 | physics phase 4 (sweeps) | the camera and binding tests pass |
| L6 | D10: `run_along`, `hop_to`; tutorial 6 | L4 | the lane tests pass |
| L7 | hill-runner steps 2 to 4; twig-bb's switch to `ClipMap` | L0 to L6 | the acceptance list above |

## Documentation to change

- `docs/characters.rst`: `add_character`, `ClipMap`, `Locomotion`, `measure_stride` and the
  tutorials; the `Gait` section points at `Locomotion`.
- `docs/navigation.rst`: `FollowMode`, `Context.follow` and the follow camera's settings.
- `docs/physics.rst`: `add_ground`, `Ground.normal` and the ceiling.
- `docs/structure.rst` and the directory map in `CLAUDE.md`: `character/locomotion.py`,
  `move/followmode.py`.
- hill-runner's README table of modules, as its modules go.

## Decisions

1. Where `Context.follow` lives. It adds a method to `Context`. The alternative is
   `hero.follow(context)` on the character, which keeps `Context` as it is and reads a
   little backwards. Recommendation: `Context.follow`, one delegating line.
2. How many vocabularies ship. `ual()` is the one in use. Recommendation: ship that one and
   `guess`, and add others when a game brings a model that needs them.
3. Whether `measure_stride` replaces declared numbers. Recommendation: no. A declared number
   wins, and a clip with none is measured and the result logged once.
