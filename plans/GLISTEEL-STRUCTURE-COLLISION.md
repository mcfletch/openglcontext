# Glisteel: structures that stop the car, and control in the air

**Status:** Plan only — awaiting review before implementation.

Three faults reported while driving the baked circuit
([`glisteel-editor/baked-world/`](../../glisteel-editor/baked-world/)), and the
diagnosis of each. Two share a root cause; the third is separate.

## Symptoms

1. **Tunnels do not collide, and the mouth is a solid-looking hillside.** At the
   first tunnel a visible chunk of terrain covers the mouth, and the car drives
   straight through it into the bore.
2. **Causeway and bridge edges do not stop the car.** The barrier along a
   causeway is scenery: the car passes through it and falls to the forest below.
3. **A launched car loses all control and crashes**, and it is easy to launch.

## Diagnosis

### Structures are drawn but never collided (faults 1 and 2)

A world's bridges, causeways and tunnels are generated as **render** geometry by
[`scenegraph/roadworks.py`](../OpenGLContext/scenegraph/roadworks.py) —
`bridge_meshes()` (`deck`, `parapet`, `piers`), `causeway_meshes()` (`body`,
`wall`), `tunnel_meshes()` (`bore`, `portals`) — and baked into the tileset's
tiles by the editor
([`OpenGLContext_editor/world/road.py`](../../openglcontext-editor/src/OpenGLContext_editor/world/road.py)).

At runtime [`glisteel/world.py`](../../glisteel/glisteel/world.py) `RaceWorld`
builds exactly three kinds of collider, and none of them is a structure:

- `HeightFieldColliders` from `terrain.field`, with tunnel **holes** cut out
  ([world.py:320–327](../../glisteel/glisteel/world.py#L320-L327), `_bores()` at
  [L357–376](../../glisteel/glisteel/world.py#L357-L376));
- `RoadColliders` per course, from the centreline + `road_profile()`
  ([L326–331](../../glisteel/glisteel/world.py#L326-L331)) — the flat carriageway
  cross-section only;
- `PropColliders` for boulders ([L334–335](../../glisteel/glisteel/world.py#L334-L335)).

The carriageway profile
([`scenegraph/road.py`](../OpenGLContext/scenegraph/road.py) `RoadProfile`) runs
crown → shoulder → verge and only ever descends; on a deck `on_structure()`
flattens the verge to a bare edge beam. **Nothing in the collider stands up.** So
the parapet, the causeway wall and the tunnel lining — the things a driver is
meant to hit — have no physical presence. The carriageway carries the wheels; the
edges are open air.

### The tunnel mouth is a bake decision (fault 1, visual half)

The baker deliberately leaves the drawn hillside solid where a road enters a
bore: `conform_terrain` masks out tunnel segments so the road surface is not
painted across an untouched hill
([`OpenGLContext_editor/bake/field.py:188–191`](../../openglcontext-editor/src/OpenGLContext_editor/bake/field.py#L188-L191),
[`world/road.py` `conform_terrain`](../../openglcontext-editor/src/OpenGLContext_editor/world/road.py)).
The drawn terrain and the collider therefore disagree: `_bores()` opens the
**collider** heightfield at runtime, while the **drawn** hill is never opened. The
result is a hill you see and pass through. Fixing the look means opening the drawn
terrain at the portal in the baker, which is a re-bake of the world.

### An airborne car is uncontrolled (fault 3)

[`omi_physics` `RaycastVehicle.update`](../../omi_physics/src/omi_physics/vehicle.py#L354-L375)
applies suspension, drive and grip **only through wheels that are on the
ground**. With no wheel grounded it applies nothing but downforce, and there is
no attitude control: whatever spin the launch imparted is carried, damped only by
the body's `angularDamping`, into the landing. There is no auto-righting and no
air steer, so a jump becomes a tumble. "Easy to launch" is a separate question —
crests, and any step where the road-chunk collider meets the heightfield.

## Proposed work

### A. `StructureColliders` — the main fix (no re-bake)

A new streamed collider in
[`OpenGLContext/physics/`](../OpenGLContext/physics/), mirroring `RoadColliders`,
that gives the standing parts of a structure a static trimesh collider and keeps
only the ones near the car in the physics world.

- **Input:** the course centreline + `RoadProfile`, and the structure runs
  (`kind`, `from`, `to` in metres) already carried on `Course.structures`
  ([world.py:80](../../glisteel/glisteel/world.py#L80)). Map a run to a
  centreline index span with `Course.stations` + `Structure.holds`.
- **Geometry:** call the matching `roadworks` builder for the run and take the
  parts that should stop a car — bridge `parapet`, causeway `wall`, tunnel
  `bore`. Each returned mesh is a `PBRMesh` carrying `.positions` (M×3 f32) and
  `.indices` (uint32); feed those straight to `model.Shape.trimesh(positions,
  indices.reshape(-1,3))`, the same call `RoadColliders._add` makes
  ([physics/road.py:152–160](../OpenGLContext/physics/road.py#L152-L160)).
- **Streaming:** chunk by structure run (a run is already a bounded stretch), keep
  runs within `reach` of the car, `add_body(STATIC)` / `remove_body` as they come
  and go, `refit_aabbs()` after each add — the `RoadColliders` pattern verbatim.
- **Care points:**
  - The tunnel **`bore`** is a closed tube; colliding it walls the tunnel while
    the carriageway collider still carries the floor. The **`portals`** are the
    end frames — collide the frame, never a face across the driving opening.
  - Parapet/wall meshes are thin. Confirm the trimesh collider is two-sided for a
    car arriving from the carriageway side, or give the wall thickness.
- **Wiring:** `RaceWorld.__init__` builds one `StructureColliders` over the
  courses; `RaceWorld.stream` updates it with the camera/car position beside the
  road and heightfield updates ([world.py:385–399](../../glisteel/glisteel/world.py#L385-L399)).
- **Engine-first:** the builder is general (any road with structures), lives in
  the engine, and glisteel only calls it — the same split as `RoadColliders`.

**Fixes:** falling off causeways and bridges; a tunnel that walls the car in
rather than letting it drive out through the lining.

### B. Open the drawn terrain at tunnel portals (needs a re-bake)

Carve the drawn terrain where a road enters a bore so the mouth is an actual
opening, matching the collider hole `_bores()` already cuts. This is editor/baker
work in `OpenGLContext_editor` and changes the baked-world assets, so it lands
with a re-bake of [`glisteel-editor/baked-world/`](../../glisteel-editor/baked-world/).
Scope to settle at review: cut the field terrain vs. rely on the portal mesh to
cap the opening; how far up the approach to open (the runtime already uses
`BORE_APPROACH = 24 m`, `BORE_MARGIN = 2 m`).

### C. Control in the air (`omi_physics`)

Give `RaycastVehicle` optional attitude help when no wheel is grounded, off by
default so nothing else changes:

- **Auto-right:** a gentle restoring torque toward upright while airborne, capped
  so it reads as a stabilised car and not a magnet.
- **Air steer:** let the steer input yaw the body a little in the air, so a jump
  can be lined up for its landing.
- Tune both to "a launch is recoverable," not "flight."

Separately, look for the launch sources: measure the step where a road chunk's
edge meets the heightfield, and whether crest geometry or a collider seam throws
the car. Fix the seam where it belongs (collider generation), not by softening the
suspension.

## Testing

Red/Green throughout, against real physics — no mocks of the collider:

- **A:** drive the car at a causeway wall in a `PhysicsWorld` built from a short
  synthetic course with a causeway run, and assert it is stopped inside the
  carriageway rather than passing the edge; the same for a bridge parapet and for
  the tunnel bore wall. Assert the car still drives *through* the tunnel (the bore
  floor/carriageway is clear). Unit-test the distance-run → index-span mapping and
  the mesh→trimesh extraction with no window.
- **B:** a baker test that the drawn terrain has no surface across the portal
  opening over the carriageway, within the opened span.
- **C:** launch a car off a ramp in a `PhysicsWorld`; assert that with auto-right
  on it lands within an upright cone where without it it does not, and that air
  steer changes heading in the air. Guard that grounded behaviour is unchanged
  (the existing vehicle suite stays green).

## Documentation

- `glisteel/README.md`: a line that the structures are solid, and what air help
  the car has.
- `openglcontext/docs/physics.html`: the new `StructureColliders`, beside
  `RoadColliders` and `HeightFieldColliders`.
- `omi_physics` docs: the new airborne tuning fields on `VehicleTuning`.
- This plan records what landed as each part goes in.

## Open decisions (for review)

1. **Order.** A alone (self-contained, cures the worst bug) → then C → then B; or
   A+C together; or all three including the re-bake for B.
2. **B's mechanism** — cut the field terrain, or cap with the portal mesh — and
   whether a re-bake of the shipped baked world is acceptable now.
3. **Whether the tunnel `portals` need any collider at all**, or the `bore`
   plus the carriageway is enough once the mouth is open.
