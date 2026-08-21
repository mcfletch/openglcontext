# Foam: where the water is white

Status: **Planned** — nothing built. Follows
[WATER.md](WATER.md). Reads the fold from
[WATER-GERSTNER-CRESTS.md](WATER-GERSTNER-CRESTS.md), and the break from
[WATER-SHOALING.md](WATER-SHOALING.md).

There is no foam in the engine. Not a texture, not a term, not a threshold:
`foam`, `froth`, `whitecap`, `breaker` and `spray` appear nowhere in any
Python module or any shader.

That is most of why a rough sea does not read as a rough sea. Whitecaps are how
an eye judges wind strength on water — the fraction of the surface that is white
is the cue, more than the amplitude is — and a lake that heaves without ever
breaking white reads as something viscous rather than as water.

It also matters for the shore, which is where a player is most of the time. The
line where water meets ground is the most-looked-at part of any lake, and today
it is a hard edge between a sand material and a water material with nothing
happening along it.

## What lands

**Foam as a scalar field over the surface**, computed from the wave field
rather than painted. A number in 0…1 per point saying how white the water is,
evaluated by the same analytic function on the CPU and on the card, so it costs
no asset, tiles seamlessly and is reproducible frame to frame.

### Where the whiteness comes from

Three sources, each independently useful, summed and clamped:

| Source | Reads | Gives |
|---|---|---|
| **Fold** | the Gerstner Jacobian falling toward zero | whitecaps on the crests that are actually breaking |
| **Steepness** | the surface slope past a threshold | streaks down the face of a steep wave |
| **Shore** | water depth under the point, shallow | the band of white along a beach |

The fold term is the honest one and the reason
[WATER-GERSTNER-CRESTS.md](WATER-GERSTNER-CRESTS.md) comes first: where the
displacement compresses the surface toward folding, that water is
overturning, and that is what a whitecap *is*. A steepness threshold alone
whitens the top of every wave equally, which reads as a painted-on rim.

The shore term needs the depth field that
[WATER-SHOALING.md](WATER-SHOALING.md) introduces, so it lands with that plan
rather than this one. This plan ships fold and steepness, and leaves the hook.

### What foam does to the surface

Not a white tint. Foam is a different substance sitting on the water, and the
material has to say so, or it will read as pale water rather than as froth:

- **albedo** toward white, but a dirty white — sea foam is around 0.8, not 1.0
- **roughness** up hard. Foam is not a mirror, and this is the term that matters
  most: a surface with water's roughness of 0.06 and a white albedo is
  polystyrene
- **the specular lobe down**. Water's F0 of 0.02 belongs to a water surface;
  foam is air and film, and leaving the dielectric reflection at full strength
  is what makes rendered foam look like plastic
- **transmission off** where foam is thick, because froth is opaque

The mixing happens in the fragment shader, between the water material and a
foam material, on the foam scalar.

### Breaking up the white

A flat white patch is worse than no foam. The coverage needs structure at a
scale finer than the mesh, which means either a tiling foam texture or noise
evaluated in the shader. Noise keeps the package asset-free and seamless and
costs a few ALU; a texture looks better and adds a file to ship and a UV scale
to get wrong. **Noise first**, with the material carrying an optional foam
texture for a game that wants to supply one.

Foam also has memory: real foam persists after the wave that made it has passed,
and fades over seconds. A purely instantaneous field pops on and off with the
crest and reads as flicker. Persistence needs state per surface point, which an
analytic field does not have — so the first version is instantaneous with a soft
threshold, and persistence is named here as the thing that will be wanted next
and is not free.

## Order

1. The foam scalar in `surface.py` — fold and steepness, CPU, pure arithmetic.
2. The same in `_wave_inc.glsl`, agreeing with the CPU form on a test grid.
3. `foam_material()` beside `water_material()`, and the mix in `pbr.frag` on a
   per-vertex or per-fragment foam term.
4. The shader noise that breaks the coverage up.
5. The shore term, once [WATER-SHOALING.md](WATER-SHOALING.md) has a depth
   field to read.

## How it is known to work

- **Still water has none.** `still` reports foam 0 everywhere, so a pond is
  exactly as it is today.
- **Coverage rises with amplitude.** The white fraction over a fixed patch
  increases monotonically from `flowing` to `choppy`, and rises with `crest`.
- **Foam is on the crests.** The foam scalar correlates with height over the
  patch; foam in the troughs is a bug, and the test says which.
- **Foam is not a mirror.** A rendered foam patch has a materially lower
  specular response than the water beside it — the failure this is most likely
  to have, given that water read as pale plastic for exactly that reason until
  the surface winding was fixed.

## What this is not

**Not spray or particles.** Foam here is a property of the surface. Droplets
thrown off a breaking crest are `scenegraph/particles.py`'s subject, and a game
that wants them can emit them where this field says the water is white.

**Not a simulation.** No advection, no foam transported by the flow, no history.
The field is a function of position, time and the style, as everything else in
[WATER.md](WATER.md)'s wave field is.
