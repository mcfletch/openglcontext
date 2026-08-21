# Crests that are sharp, and troughs that are flat

Status: **Planned** — nothing built. Follows
[WATER.md](WATER.md), which named the three styles and left their shape alone.
[WATER-FOAM.md](WATER-FOAM.md) wants the fold this produces, and
[WATER-SHOALING.md](WATER-SHOALING.md) steepens what this shapes.

`choppy` is not choppy. It is `flowing` with the numbers turned up: amplitude
0.42 m against 0.09, wavelength 7.0 m against 4.5, speed 2.4 against 1.6. The
field itself is the same three crossing sine trains
(`surface._TRAINS`, at turns 0, +0.62 and −1.13 radians with shares 1.00, 0.55
and 0.34), summed as `Σ A·sin(φ)`.

A sum of sines is symmetric about its mean, and measurement says so: over a
60 × 60 m patch the height field skews **−0.006** for `flowing` and **+0.019**
for `choppy` — zero either way. Water does not. A wind sea has narrow crests
and broad flat troughs, and the skew of a real short-crested sea runs around
+0.3 to +0.6. That asymmetry *is* what the eye reads as rough water, which is
why turning the amplitude up gives a bigger swell rather than a choppier one.

## What lands

**Gerstner displacement**, which is the standard analytic answer and stays
inside the boundary [WATER.md](WATER.md) drew: no solver, no simulation, a
closed form evaluated at a point.

A sine train moves the surface up and down. A Gerstner train also moves it
*sideways, toward the crest*, which piles water into the crest and empties the
trough:

```text
x' = x − Σ Qᵢ Aᵢ Dᵢ.x cos φᵢ
z' = z − Σ Qᵢ Aᵢ Dᵢ.z cos φᵢ
y  =     Σ    Aᵢ      sin φᵢ
```

`Q` is the steepness knob, per style. `WaterStyle` already carries a
`steepness` field, but it means something else — the fine ripple folded into
the normals — so this needs its own name (`crest`, say) rather than a
redefinition that would quietly change every existing style.

**The bound that matters.** Past `Q·Σ(kᵢAᵢ) = 1` the surface folds through
itself and renders inside out. The style constructor clamps `crest` to that
bound and says so, rather than leaving a value that looks fine in a still
frame and tears at speed.

### The contract this breaks, and what replaces it

`wave_height(style, x, z, when)` answers *"how far above its level does the
surface stand at this (x, z)"*. Gerstner makes that question ill-posed: the
water that ends up over `(x, z)` started somewhere else, and near a sharp crest
more than one starting point lands on the same spot.

That matters because [WATER.md](WATER.md) promised the height field to whatever
floats on it: *"Buoyancy and drag read the height field this provides."* So the
split has to be explicit:

| Function | Answers | For |
|---|---|---|
| `wave_point(style, u, v, when)` | the world point a surface parameter lands at, `(…, 3)` | meshing a sheet, a ribbon, a glint |
| `wave_normal(style, u, v, when)` | the normal there | the same |
| `surface_height_at(style, x, z, when)` | the height of the surface **over** a world `(x, z)` | buoyancy, a float, a boat, a swimmer |

`surface_height_at` inverts the displacement by fixed-point iteration: start at
`(x, z)`, evaluate the displacement, step back, repeat. Under the fold bound it
contracts, and three iterations hold a tolerance well under a centimetre — cheap
enough to call per body per frame, and vectorised for a crowd of them.

`wave_height` keeps its name and its meaning as the *vertical* term, so nothing
that meshes today changes. What changes is that a caller wanting "the surface
over this point" now has a function that is actually right.

### On the card

`shaders/_wave_inc.glsl` already carries the trains and `applyWave(position,
normal)`, which the GPU sheets use. Gerstner is the same edit there: the
include gains the horizontal terms and the `WAVE_TRAINS` table gains `Q`. The
CPU and GLSL forms must agree to within a millimetre over a test grid, or a
sheet meshed one way and displaced the other will not line up with the floats
sitting on it.

## Order

1. `wave_point` / `wave_normal` in `surface.py`, CPU only, with the fold bound
   and its clamp. Pure arithmetic, headless-testable.
2. `surface_height_at` and its iteration, tested against `wave_point` by
   round-trip.
3. The `crest` field on `WaterStyle`, and values for the three named styles —
   `still` stays at 0, which keeps a pond exactly as it is today.
4. `_wave_inc.glsl`, with a test that the two forms agree.
5. The sheet, ribbon and glint builders meshing through `wave_point`.

## How it is known to work

- **Skew turns positive.** The same 60 × 60 m measurement that reads +0.019
  today should read in the +0.3 to +0.6 band for `choppy`. That is the number
  this plan exists to move, so it is the test.
- **The surface never folds.** The Jacobian of the displacement stays positive
  everywhere on a dense grid, for every named style at its clamped `crest`.
- **A float sits on the water.** `surface_height_at` agrees with the meshed
  surface under it to within a centimetre, which is what stops a boat drawn at
  one height and floated at another.
- **Still water is untouched.** `still` renders pixel-identical, because its
  amplitude and its crest are both zero.

## What this is not

**Not a spectrum.** Three trains, not a Phillips or JONSWAP spectrum with an
FFT behind it. The three-train field is what makes this seamless, tileable and
free of a per-frame transform; a spectrum is a different feature with a
different cost, and it is not this one.

**Not foam.** A Gerstner crest that folds is where foam belongs, and the fold
term is the signal [WATER-FOAM.md](WATER-FOAM.md) reads. Producing it is this
plan; whitening it is that one.
