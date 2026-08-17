# OMI glTF Extensions: what is supported

## Goal

One place that answers "do we read *that* one?" for the
[OMI group's glTF extensions](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0),
and records what the remaining ones would take. These are the extensions that
describe a **world** rather than a model — sound, physics, sky, and the things a
player sits in or drives — so they are the ones a viewer that walks around a
scene actually needs.

Support is split across three projects, each of which takes the extension as its
**native** data model rather than converting into one of its own: the glTF
loader here, `omi_audio` and `omi_physics`.

## Status

| Extension | Status | Where |
|---|---|---|
| `KHR_audio_emitter` | ✅ Full | `omi_audio`, [SPATIAL-AUDIO.md](SPATIAL-AUDIO.md) |
| `OMI_audio_ogg_vorbis` | ✅ Full — preferred over the MP3 fallback and decoded | `omi_audio/formats.py` |
| `OMI_audio_opus` | 🟡 Read, preserved and reported; **not decoded** | `omi_audio/formats.py` |
| `OMI_physics_shape` | ✅ Full, read and written | `omi_physics/omi_gltf.py` |
| `OMI_physics_body` | ✅ Full, read and written | `omi_physics/omi_gltf.py` |
| `OMI_physics_gravity` | ✅ Full — global and per-node gravity volumes | `omi_physics/omi_gltf.py` |
| `OMI_physics_joint` | ✅ Full, read and written | `omi_physics/omi_gltf.py` |
| `OMI_environment_sky` | 🟡 Gradient, panorama and plain skies drawn; **physical** read but not rendered | [OMI-ENVIRONMENT-SKY.md](OMI-ENVIRONMENT-SKY.md) |
| `OMI_seat` | ⬜ Future work | — |
| `OMI_spawn_point` | ⬜ Future work | — |
| `OMI_vehicle_body` | ⬜ Future work | — |
| `OMI_vehicle_wheel` | ⬜ Future work | — |
| `OMI_vehicle_thruster` | ⬜ Future work | — |
| `OMI_vehicle_hover_thruster` | ⬜ Future work | — |

## Audio codecs

`KHR_audio_emitter` requires only MP3. The two codec extensions each hang off a
**source** and name a second entry in the same `audio` array holding the same
sound better encoded, leaving the source's own `audio` as the fallback:

```json
{"audio": 0, "extensions": {"OMI_audio_ogg_vorbis": {"audio": 1}}}
```

Both are read, kept and written back unchanged; only decoding differs, and
`formats.decodable()` asks the backend what it reads rather than asserting a
list. `miniaudio` reads Vorbis and not Opus. See
[SPATIAL-AUDIO.md](SPATIAL-AUDIO.md#codec-extensions).

Opus needs a second decoder plus WebM demuxing. libopus is BSD-3 and so
available under this workspace's licensing rules, but it is a new hard
dependency for a codec no content here uses.

## `OMI_environment_sky`

Three of its four sky types describe a background OpenGLContext already draws,
and `loaders/gltf/environment_sky.py` now reads `skies[]` and the scene's `sky`
index into them: gradient → `Background` (the VRML97 gradient sphere), panorama →
`HDRBackground` (equirectangular, which also feeds the IBL probe) or
`CubeBackground` (cubemap), plain → `SimpleBackground`.

Still open, and each for its own reason:

- **The physical sky.** The one type that is a renderer rather than a
  translation: an analytic Rayleigh/Mie single-scattering skydome driven by the
  scene's directional sun, in glTF's inverse-metre units. Read and reported —
  `GLTFScene.sky` carries the record — so a caller can say why the sky is
  missing, and so the parameters are there when the shader arrives.
- **The gradient sun tint** (`sunAngleMax`, `sunCurve`). A disc around the
  scene's directional light, so it varies with azimuth; the gradient sphere's
  colour stops are elevation-only and cannot express it. Would need either a
  term in `vrml97_background.frag` or the physical sky's skydome.
- **The ambient contribution** (`ambientLightColor`,
  `ambientSkyContribution`). Read and kept, not yet wired to the world-up
  ambient term.
- **`KHR_animation_pointer`** on the colour and curve fields.

Full plan, including the phases that landed, in
[OMI-ENVIRONMENT-SKY.md](OMI-ENVIRONMENT-SKY.md).

## Future work

Sketched only so that picking one up starts from something.

### `OMI_spawn_point`

The smallest of the four and the one with the most immediate use: the viewer and
`twig-bb` both place an avatar at load, and both currently do it from their own
format's conventions (glTF camera framing here, Quake entity classnames there).
A document-declared spawn point would give the loader a third source and one
that authors control. It maps onto the existing `Viewpoint` machinery, so the
work is reading the extension and choosing between candidates.

### `OMI_seat`

A place on a node an avatar occupies, with a defined back/foot/knee geometry.
Needs a rider/occupancy concept the movement modes do not have yet — the avatar
stops being driven by `PhysicsWalkMixin` and starts being carried by a node —
which is the same seam a vehicle needs, and the reason to do this one first.

### `OMI_vehicle_*`

`OMI_vehicle_body` plus wheels, thrusters and hover thrusters: a driven rigid
body with powered constraints. `omi_physics` already has the rigid bodies and
the joints, so the missing pieces are the wheel model (suspension, steering,
drive/brake torque, a friction model that is not the character controller's) and
a control seam from the input sampler. Substantially the largest of the four,
and it wants `OMI_seat` to exist first so that there is something to sit in.

## Related

- [SPATIAL-AUDIO.md](SPATIAL-AUDIO.md) — the audio stack and the codec extensions.
- [OMI-ENVIRONMENT-SKY.md](OMI-ENVIRONMENT-SKY.md) — the sky plan.
- [PHYSICS-COLLISION.md](PHYSICS-COLLISION.md) — the physics side.
- [docs/gltf.html](../docs/gltf.html#omi) — the same table, for users.
