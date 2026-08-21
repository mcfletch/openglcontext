# Water as a first-class feature

Status: **Complete** — 2026-08-20. Medium, volumes, submersion, the three
styles, the ribbon, the glints and the GPU path have landed; twig-bb runs on
it, and a baked world carries its rivers.

Water is in the engine twice over and neither half knows about the other. A
lake is a flat sheet with a ripple in its normals
(`scenegraph/water.py`); being *inside* a liquid is a fog colour and an audio
muffle in a game (`twig-bb/twig_bb/underwater.py`). A river has neither: the
track editor routes one, carves its bed, and draws a blue hairline on the map,
because nothing in the engine can make a surface that runs downhill.

Three things are wrong with that, and they are the same thing:

- **Water is a medium, not a texture.** What it does to a body inside it — the
  view closing in, the mix muffling, what it costs to be there — belongs with
  what it looks like from outside, because they are two views of one substance.
  Splitting them is why a game had to write its own.
- **Water moves, and how it moves is what it is.** A pond, a river and a
  choppy lake are the same material under three motions. There is one ripple in
  the engine and it is neither still nor flowing.
- **A surface that only exists at one height is not water.** A river descends.
  A sheet at `level=` cannot follow it, so the only water a world can have is
  the sea.

## What lands

**`OpenGLContext/scenegraph/water/`**, a package, because this is a subsystem
and not a helper. The existing `water_surface` import keeps working.

| Module | Holds |
|---|---|
| `surface.py` | `WaterStyle` and the three named ones; the wave field; meshing a sheet or a ribbon at a time |
| `medium.py` | `Medium` — what a substance does to a body inside it; the standard three |
| `volumes.py` | Where the media are: boxes, and what is at a point |
| `submersion.py` | Putting a context into a medium: the fog and the mix |

### Still, flowing, choppy

One `WaterStyle`: an amplitude, a wavelength, a speed, a steepness and a flow.
The three named styles are three settings of it, and a caller who wants a
fourth writes one rather than choosing from an enumeration.

| Style | What it is |
|---|---|
| **still** | A pond. No displacement; a long shallow swell in the normals, which is what breaks the highlight into glitter. |
| **flowing** | A river. Small crests travelling **along the flow**, and the surface itself drifting, so what a body floating on it does is visible. |
| **choppy** | Weather. Real vertical displacement from crossing wave trains, so a shoreline moves and a boat pitches. |

The field is **a sum of directional waves evaluated from world position and
time**, so two sheets that meet agree along their seam, a world baked twice is
the same world, and a caller can ask what the height is at a point — which is
what floating on it needs.

### Water you are inside

`Medium` is what a substance does to a body in it: how far you can see, what
colour the view closes to, how much of the mix's high end goes, and how much it
costs per second to be there. The three the games use — water, slime, lava —
ship as data, with the numbers twig-bb arrived at and the reasoning that
produced them.

`Volumes` is a set of boxes with a medium each and `medium_at(point)`; how a
game *finds* those boxes stays with the game, because a BSP's contents flags
and a track's lake are not the same question. `submersion.apply` puts a context
into whatever is at a point: the fog node it already binds, and the mix's
muffle.

**twig-bb keeps the BSP extraction and loses the rest.** Its `underwater.py`
becomes a shim over the engine, and its liquid look-up table moves into
`medium.py` where the second game can reach it.

### Water that runs downhill

`water_ribbon` sweeps a surface along a path at a width and a height per point,
which is what a river is: the channel the hydrology already routes, at the top
of the bed it already carves. It is the same `WaterStyle` machinery, so a river
is flowing water and a lake is still water and neither is a special case.

A river's **level of detail is a glint**. Beyond a tile error of 24 metres
`water_glints` replaces the ribbon with a scattering of quads along the same
course: at that range a river is two pixels wide and mostly hidden by what
stands over it, and what the eye gets is the surface flashing between the
trees. The spacing between glints grows with the tile's error, so a coarse tile
covering more ground carries about as many as a fine one — a budget rather than
a fade — and where they fall is a function of distance along the course, so a
world baked twice glints in the same places.

## Moved on the card

The character work left the hook this needed: a vertex shader that already
takes a mesh's own animation before anything transforms it, and a pass that
turns it on and off with a uniform. Water is the same shape of problem, so it
uses the same arrangement.

`shaders/_wave_inc.glsl` carries `applyWave(position, normal)` and is included
by **both** the PBR program and the shadow depth program, so a wave casts the
shadow of the shape it is in rather than of the plane it was meshed as -- which
is exactly what skinning does for a pose. `PBRShaderProgram.set_wave(style,
when)` uploads the style; `Shape` answers it for every shape, so the hillside
after a lake does not ripple.

**The mesh is uploaded once.** `water_surface(..., on_gpu=True)` meshes flat and
hands the style to the card; moving it is then setting `mesh.wave_time`. A mesh
built with the wave already in it *and* moved on the card would have the wave
applied twice, so it is one decision rather than two.

**The two copies of the field are held together by a test.** The trains and the
ripple scale are read out of the GLSL and compared with the module's, because a
surface that floats a boat at one height and draws it at another is worse than
one that does neither.

## Order

1. `medium.py` and `volumes.py` — the medium, standalone and tested.
2. `submersion.py` — fog and mix, generalised from twig-bb.
3. twig-bb on top of both, its own copies deleted.
4. `surface.py` — the wave field and the three styles, with the existing sheet
   rebuilt on it.
5. `water_ribbon`, and the world generator's rivers using it.
6. `water_glints` and `bake/rivers.py`, so a baked tileset carries the rivers
   the hydrology routed — a ribbon near to, glints far off.

Every step is headless-testable: a wave field is arithmetic, a medium is a
table, and what is at a point is a box test.

## What this is not

**Not a simulation.** No fluid solver, no reflections beyond what the material
already does, no refraction beyond the transmission the PBR pass has. The wave
field is analytic, which is what makes it cheap, seamless and reproducible.

**Not a physics body.** Buoyancy and drag read the height field this provides;
what they do with it belongs to whatever moves the body.

## What was left for later

Three things the wave field does not do, each with a plan of its own:

- [WATER-GERSTNER-CRESTS.md](WATER-GERSTNER-CRESTS.md) — the field is a sum of
  sines, so it is symmetric about its mean and `choppy` is a bigger swell
  rather than a choppier sea. Gerstner displacement gives it narrow crests and
  flat troughs, at the cost of the height-field contract named above.
- [WATER-FOAM.md](WATER-FOAM.md) — nothing goes white. No foam term exists
  anywhere in the package or the shaders.
- [WATER-SHOALING.md](WATER-SHOALING.md) — the field never sees the bed, so a
  swell runs up a beach unchanged and stops at the waterline instead of
  breaking on it.
