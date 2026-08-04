# Plan: Movement modes as declared nodes

**Status:** ✅ Complete — shipped with tests; the settings GUI over it is
[OVERLAY-UI.md](OVERLAY-UI.md), still proposed.

## The problem

Navigation was hand-rolled per application. Each viewer bound its own keys,
kept its own "is the run key down" flag, and drove the camera from key
*events* — which cannot express two inputs at once. Holding forward and
tapping jump lost one of them, because a handler sees one event at a time, and
every application that wanted both special-cased it. Nothing could enumerate
"the ways this application lets you move", so a settings screen or a rebinding
page had nowhere to start.

## What was built

**A mode is a node.** `OpenGLContext.move.modes` declares `MovementMode` and
the four concrete modes as `PROTO`s with typed fields, so a mode can be written
into a parsed file, carried in an `SFNode`, watched for change, and edited by
anything that understands fields. Each mode declares *its own* tunables —
`WalkMode.walkSpeed`, `SwimMode.buoyancy`, `FPSMode.sensitivity` — rather than
sharing a free-form settings mapping, which would need a parallel validation
layer.

**Input is sampled.** `OpenGLContext.events.inputstate.InputState` accumulates
key-down/key-up and pointer motion as events arrive; a mode asks once per frame
what is currently true. Walking and jumping in one frame then needs no special
case, and `pressed()` is consumed by reading so a jump is one launch per press.

**Two kinds of mode.** The player chooses walk, fly and first-person;
`enter_when(platform)` is how a mode says the *world* imposes it, which
`SwimMode` uses for being submerged. An imposed mode never appears in the
selection cycle and hands the mode back when its condition lifts.

**Bindings carry a modifier.** `KeyBinding` has `command`, `label`, `keys` and
an optional `modifier`. A plain binding loses its key only while another
binding of the same mode claims it with a modifier that is down — so
<kbd>ctrl</kbd>+<kbd>↑</kbd> tilts the view without walking, while
<kbd>shift</kbd>+<kbd>w</kbd> still walks.

**The context drives it.** `ViewPlatformMixin` feeds the sampler from ordinary
events, builds a `NavigationManager` when the `ContextDefinition` declares
modes, and publishes the mode in force as `contextDefinition.movementMode`.
`getNavigationPlatform()` is the seam for a game whose modes drive a character
controller rather than the camera; the manager is rebuilt when that changes,
because a controller usually appears when a world finishes loading.

**Pointer capture.** A mode with `capturePointer` has the pointer grabbed while
it is in force — GLFW's disabled cursor plus raw motion where available, since
mouse-look needs motion that does not stop at the screen edge.
`suspendPointerCapture()` hands it back while an overlay wants it.

## What uses it

| Application | Modes | Driven by them |
|---|---|---|
| `OpenGLContext.bin.gltf_view` | walk, fly, scaled to the model | yes, in walk mode |
| twig-bb (BSP map viewer) | walk, fly, first-person, swim | yes |
| `OpenGLContext.bin.vrml_view` | walk, fly, scaled to the model | declared only |

twig-bb is the load-bearing case: it replaced its own key bookkeeping with the
declared modes, which is what made running-and-jumping and mouse-look work, and
its swim mode is imposed by the map's liquid volumes. `gltf_view` followed, and
its turn acceleration — a nudge on first press ramping to 3x while held — moved
into `_GroundMode.turnAcceleration` rather than staying in one viewer.
`vrml_view` declares its modes so a settings screen can enumerate them, but its
camera is still driven by the older navigator; wiring it is the same change made
twice already.

## Deliberately not done

- **Gamepad and touch.** `InputState` is keys and pointer. Adding an axis
  source is a change to the sampler, not to the modes.
- **Per-mode camera behaviour** (head bob, FOV on sprint). A mode moves a
  platform; how the camera then behaves is the application's.
- **Persisting rebindings.** `binding_table()`/`rebind()` exist and take effect
  at once; writing them to the per-user app-data directory is stage 5 of
  [OVERLAY-UI.md](OVERLAY-UI.md).
- **Buoyancy.** `SwimMode.buoyancy` is declared and unused: a swimmer is free
  of gravity rather than floating, because partial gravity would have to be a
  character-controller feature.

## Documentation

[docs/navigation.html](../docs/navigation.html), indexed from
`documentation.html` and referenced from `structure.html`.
