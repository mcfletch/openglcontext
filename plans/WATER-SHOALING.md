# Water that knows how deep it is

Status: **Planned** — nothing built, and the largest of the three. Follows
[WATER.md](WATER.md). Steepens what
[WATER-GERSTNER-CRESTS.md](WATER-GERSTNER-CRESTS.md) shapes, and hands the
break to [WATER-FOAM.md](WATER-FOAM.md).

`wave_height(style, x, z, when)` is a pure function of where you are, when it
is, and which style the water has. **It never sees the bed.** The only depth in
the water package is the box a `Volume` occupies, for deciding whether a body is
submerged, and the transparency that lets a pale bed show through the shallows.
Neither reaches the wave field.

So the same swell that crosses forty metres of open water runs straight up a
beach at the same height, the same wavelength and the same direction, and stops
being water at the waterline rather than breaking on it. A lake reads acceptably
because a lake is deep to its edge. A shore does not.

## What lands

**A depth field the wave function can ask.** Everything else follows from that
one interface, and it is the part to get right:

```python
class DepthField(Protocol):
    def depth_at(self, x, z):
        """Metres of water over the bed, vectorised; <= 0 where it is dry."""
```

Backed by the terrain height field a world already has
(`scenegraph/terrain/`), by a baked tile, or by a flat constant for open sea.
A style with no depth field behaves exactly as it does today, which is the
regression guarantee this whole plan hangs on.

### What depth does to a wave

Linear wave theory, evaluated per point. Analytic, no solver, inside
[WATER.md](WATER.md)'s boundary:

| Effect | From | Reads as |
|---|---|---|
| **Shortening** | `ω² = g·k·tanh(k·d)` solved for `k` | crests bunch up as the bed rises |
| **Steepening** | shoaling coefficient `Ks = √(cg_deep / cg_local)` | the same swell stands taller inshore |
| **Refraction** | the heading turning toward the depth gradient | crests swing round to run parallel to the beach |
| **Breaking** | `H/d > γ`, with `γ ≈ 0.78` | the wave stops growing and goes white |

Refraction is the one that sells it. Waves arriving at an angle to a beach turn
until they break along it, and that is the single most recognisable thing water
does near land.

**Breaking is a clamp, not an event.** Past the criterion the amplitude stops
growing and the excess becomes foam — this is the third source
[WATER-FOAM.md](WATER-FOAM.md) leaves a hook for. No overturning geometry, no
tube, no simulation: the wave flattens and whitens, which is what it looks like
from any distance a player is at.

### The cost, and the way round it

The dispersion relation has no closed form for `k`. Solving it per point per
frame is the expensive part of this plan and would put an iteration in the
inner loop of the wave field, on the CPU and in the shader both.

It does not need solving per point. `k` depends only on `d` for a given `ω`, so
it is **one curve per style**, sampled into a small lookup table over depth at
the time the style binds a depth field — a texture on the card, an array on the
CPU. The per-point cost falls to a lookup and a lerp.

### The interface change

`wave_height` and `wave_normal` gain the depth field, either as an argument or
bound to the style. Bound to the style is better: every call site already has
the style, none of them has a depth field, and threading one through the sheet,
ribbon and glint builders and the GPU uniforms is churn at every level. A style
is small and frozen, so binding produces a new style rather than mutating one.

The GPU side needs the depth under each vertex, which means either sampling the
terrain height texture in the vertex shader or carrying depth as a vertex
attribute meshed in. The attribute is simpler and enough: a water sheet is
meshed against a bed that is not moving.

## Order

1. `DepthField` and a flat implementation, so everything downstream has
   something to ask.
2. The dispersion table, tested against the relation it approximates.
3. Shortening and steepening in `wave_height` / `wave_normal`, with the
   deep-water case asserted identical to today.
4. Refraction — the heading turn, which is the most visible and the most
   likely to be got subtly wrong.
5. The breaking clamp, and the foam term it feeds.
6. The terrain-backed depth field, and a sheet meshed with depth per vertex.
7. `_wave_inc.glsl`, agreeing with the CPU form.

## How it is known to work

- **Deep water is unchanged.** With no depth field, or depth past half a
  wavelength, the field is bit-identical to today's. Every existing water test
  and every blessed water capture passes untouched. This is the first test to
  write and the one that makes the rest safe.
- **Shoaling matches theory.** Amplitude against depth follows `Ks` and
  wavelength follows the dispersion relation, to a tolerance, over a ramp.
  Both are closed-form, so the test is arithmetic against arithmetic.
- **Crests turn toward the beach.** On a plane beach with the swell arriving at
  an angle, the crest heading converges on the depth contour as depth falls.
- **Waves break at the right depth.** For a given deep-water height, the break
  happens where `H/d` crosses γ, and the amplitude stops rising past it.
- **A dry point is dry.** Depth ≤ 0 gives no displacement rather than a
  negative-depth arithmetic error, which is what a sheet meshed slightly past
  the waterline will hit on its first frame.

## What this is not

**Not a fluid solver.** No shallow-water equations integrated over a grid, no
advection, no state carried frame to frame. Every effect here is a closed-form
function of local depth, which is what keeps the field seamless, tileable and
reproducible.

**Not run-up.** The water's edge stays where the geometry puts it. A wave that
washes up a beach and drains back is a moving waterline, and a moving waterline
is a different feature: it changes what is dry, which the terrain, the physics
and the audio all have opinions about.

**Not refraction of light.** "Refraction" here is the wave crest turning. What
light does through the surface is the PBR pass's transmission.
