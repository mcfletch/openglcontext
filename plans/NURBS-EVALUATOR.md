# NURBS off GLU and onto the evaluator

**Status: Complete.**

## Why

Every NURBS surface in the engine was tessellated by `gluNurbsSurface` in
callback mode. GLU 1.3 is a compatibility-profile library: asking it to
tessellate makes it read the extension string through
`glGetString(GL_EXTENSIONS)`, which a core profile removed, and the error that
leaves behind lands on whatever the application calls next. The engine's default
profile is core, so that was every NURBS scene.

`opengl_extrusions.nurbs` evaluates a surface from its knot vectors and control
net, which is the same thing without the GL. The sibling swept-geometry nodes
already generate their vertex arrays with that package; this puts the NURBS
nodes on the same footing.

## What landed

`nurbstess.tessellate_surface(surface, trimming_contours, sampling, u_step,
v_step)` reads a surface node and returns a `SurfaceTessellation`: positions,
normals, parametric texture coordinates, colours and triangle indices. It calls
no GL, so it runs with no context current, and the whole of it is under unit
test rather than behind a window.

- **Both profiles draw the same triangles.** The core path uploads an
  interleaved vertex buffer and an index buffer and draws through the pass's
  shader; the compatibility path points client arrays at the same buffers. There
  is no longer a separate GLU render path with its own behaviour.
- **Indexed.** A lattice shares each interior vertex between six triangles;
  the GLU path uploaded six copies of it. A 30 by 30 surface went from 5400
  vertices to 961.
- **`weight` is honoured.** The field was declared and documented as
  not-yet-implemented for as long as the module has existed. A NURBS circle is
  now a circle.
- **A degree-1 direction works.** A cylinder lofted between two rings, or any
  ruled band, is evaluated and shaded like any other surface. This needed a fix
  in `opengl_extrusions`: `basis_derivatives` recursed into a degree-0 basis
  that `basis_functions` refused, so a linear direction had no normals at all.
- **`NurbsCurve` draws in a core profile.** It was `gluNurbsCurve`, which drew
  nothing there. It is evaluated to a polyline and drawn as a line strip.
- **Trimming is the package's constrained Delaunay tessellator**, refined to the
  triangle size the sampling rate asks for, so a trimmed surface is sampled as
  finely across its middle as an untrimmed one.

## Holding the appearance

The GLU tessellator's exact output was measured first --- normal sense, triangle
winding, texture-coordinate orientation, sample counts against step rate and
knot range, colour interpolation, and which side of a trim loop is kept --- and
the replacement is held to it. Every one matches:

| | GLU | evaluator |
|---|---|---|
| normal of a plane with x along u, y along v | (0, 0, -1) | (0, 0, -1) |
| first triangle's winding | clockwise from +z | clockwise from +z |
| texture coordinates | (u, v) | (u, v) |
| triangles at rate 4 / 8 / 16 / 30 | 32 / 128 / 512 / 1800 | 32 / 128 / 512 / 1800 |
| rate 4 over a knot range of 4 | 512 triangles | 512 triangles |
| counter-clockwise trim loop | keeps its inside | keeps its inside |
| clockwise trim loop alone | nothing | nothing |
| clockwise loop inside one | a hole | a hole |

The one deliberate difference is a malformed input GLU has no defined answer
for: two counter-clockwise loops one inside the other, which GLU tessellates
twice and the positive winding rule reads as one region.

One reference image was regenerated: `tests/reference_images/nurbsobject.png`,
the trimmed surface. Its silhouette and its trim outline are in the same places
and the shading through the middle is the same; what moved is which side of a
pixel the boundary falls on, at 2.1% of the frame against a 2% tolerance. The
two renders light 26033 and 26006 pixels, and the pixels each lights that the
other does not (261 and 234) are on both sides of the outline rather than all
on one, which is a boundary landing differently rather than a surface that
grew or shrank. The other ten NURBS scripts match their references untouched.

The parameter conventions this preserves are worth stating, because they are not
the obvious reading. `controlPoint` is v-major, and the evaluator is handed the
net with `vKnot` first, which makes a surface's normal `dp/dv x dp/du`. Trim
coordinates are `(v, u)` for the same reason. Texture coordinates are `(u, v)`,
so they are swapped on the way out.

## What it costs

Tessellation is cached per surface per LOD level, so these are what a scene pays
once as a surface comes into view, not per frame. Measured on the same surfaces
either way:

| | GLU | evaluator |
|---|---|---|
| untrimmed, rate 30 (1800 triangles) | 7.6 ms | 1.2 ms |
| the whole teapot, 32 patches, rate 30 | 293 ms | 56 ms |
| trimmed, rate 30 (about 1100 triangles) | 3.3 ms | 40 ms |

The untrimmed lattice is evaluated as whole rows and columns at once, which is
where its speed comes from and why the teapot loads five times faster.

**The trimmed case is the one that got slower**, and all of it is in
`opengl_extrusions.cdt.refine`, which inserts refinement points one at a time in
Python: 1536 insertions for that surface, at about 0.11 ms each. The coarser LOD
levels ask for far fewer (11 ms, 3 ms and 1 ms for levels 1 to 3), so walking up
to a trimmed surface costs about 55 ms in total, spread over the four frames
where it crosses a level boundary, with the 40 ms at the closest level as the
one visible hitch.

That is worth fixing in the tessellator rather than here: `refine` is what fills
every extrusion cap, text glyph, road surface and water patch as well, so a
faster insertion loop there is worth more than anything this module could do to
avoid calling it.

## What is not done

`solid` and `ccw` are applied by the fixed-function path and not by the shader
path, which is how it was before: culling policy in the core passes is a
question about every geometry node, not about this one.

`NurbsToleranceSample` maps its tolerance to a sampling rate through a fixed
relation rather than measuring deviation. A true error-driven adaptive
tessellation --- subdivide until the mesh is within the tolerance of the surface
--- is a feature in its own right, and would want the same treatment in the
quadrics and the swept geometry.

[GPU-NURBS-TESSELLATION.md](GPU-NURBS-TESSELLATION.md) proposes moving the
evaluation onto the GPU with tessellation shaders. That is unaffected by this:
it replaces where the basis functions are evaluated, and the node fields,
sampling nodes and trimming machinery here are what would feed it.

## Documentation

New [docs/nurbs.html](../docs/nurbs.html), linked from `index.html` and from
`documentation.html`'s feature gallery and topic list. `docs/vrml97.html` and
`docs/testing.html` no longer describe the teapot and the test fixture in terms
of GLU.
