# How geometry reaches a shader it did not come with

**Status:** 🚧 Step 1 landed (`vertexsemantics.py`, one table); steps 2-5 proposed.
**Related:** [CORE-PROFILE-DEFAULT.md](CORE-PROFILE-DEFAULT.md) names this as the
gap behind `shaderobjects.py`, `shader_11` and `shader_12`;
[SHADER-TUTORIALS-CORE.md](SHADER-TUTORIALS-CORE.md) waits on it for three of its
tutorials.

## The question

```python
Shape(
    geometry = Sphere( radius=2 ),
    appearance = Shader( objects=[ GLSLObject( shaders=[...] ) ] ),
)
```

A `Shader` is "an `Appearance` that carries its own GLSL program", and this is
the shape of every declarative-shader tutorial the engine has. Under the
compatibility profile it draws: the geometry submits its arrays through
`glVertexPointer`/`glNormalPointer`, and the user's shader reads `gl_Vertex` and
`gl_Normal`, which the driver wires together. **That wiring is what a core
profile removes**, and nothing has replaced it — so the core pass has no way to
connect a `Sphere` to a program it has never seen, and says so rather than
drawing (`Shape._render_shader`).

The general form: **a geometry node and a shader program are written by
different people, and something has to say which array feeds which input.**

## Why the key is a semantic, not a path

The obvious shape for that "something" is a mapping, and the obvious key is a
path to the data: `{'.geometry.vertices': 'vertexInput'}`. It does not survive
contact with the geometry:

- **Procedural geometry has no such field.** `Sphere`, `Box`, `Cone`, `Teapot`,
  `Text` and every `Extrusion` generate their arrays at compile time. There is no
  `.geometry.vertices` to name, and a shader written against one could not be
  pointed at another.
- **The same data sits at a different path in every geometry type.**
  `IndexedFaceSet.coord.point`, `PBRMesh.positions`, `ArrayGeometry.vertices`,
  `IndexedPolygons.coord.point`. A shader keyed on the path is a shader that
  works with one node class.
- **It is the wrong direction.** The shader does not care where the numbers live;
  it cares *what they mean*. A path says where.

So the key is the **meaning** of the array — its semantic — and the value is
what the shader calls it. glTF settled that vocabulary and the engine already
speaks it (`frommesh.ATTRIBUTE_KEYWORDS`):

| Semantic | What it is | Engine array |
|---|---|---|
| `POSITION` | vertex position, vec3 | `positions`, `coord`, `vertices` |
| `NORMAL` | vec3 | `normals`, `normal` |
| `TEXCOORD_0` | vec2 | `texcoords`, `texCoord` |
| `TEXCOORD_1` | vec2 | `texcoords1` |
| `TANGENT` | vec4, w = handedness | `tangents` |
| `COLOR_0` | vec4 | `colors`, `color` |
| `JOINTS_0`, `WEIGHTS_0` | vec4 each, skinning | `skin_joint_floats`, `skin_weights` |

## What was true before step 1

The contract was undeclared, written down in three places that did not reference
each other, and there were two of it.

**The main table**, as `pbrmesh.py` constants and as `layout(location = …)` in
`pbr.vert`, `vrml97_lighting.vert` and `vrml97_unlit.vert`:

| Location | Name | Semantic |
|---|---|---|
| 0 | `aTexCoord` | `TEXCOORD_0` |
| 1 | `aNormal` | `NORMAL` |
| 2 | `aPosition` | `POSITION` |
| 3 | `aTangent` | `TANGENT` |
| 4 | `aColor` | `COLOR_0` |
| 5–8 | `aInstanceModelView` | per-instance mat4 |
| 9 | `aInstanceObjectId` | per-instance uint |
| 10 | `aInstanceMaterial` | per-instance uint |
| 11 | `aTexCoord1` | `TEXCOORD_1` |
| 12, 13 | `aJoints`, `aWeights` | skinning |

**The compact table**, in `vrml97_point.vert` and the line program: location 0 is
`aPosition` and location 1 is `aColor`. `VRML97ShaderProgram.position_location`
exists to choose between the two, and its docstring says what it costs: "a vertex
array bound to the location the shader does not read leaves every vertex at the
origin, and the geometry disappears without a GL error to say so."

**Four ways a geometry node supplies its arrays**, none of which knows about the
others:

| Supply | Nodes | Bound by |
|---|---|---|
| Separate VBOs, one per array | `IndexedFaceSet`, `ArrayGeometry`, `IndexedPolygons` | `shadergeometry.bind_separate_arrays`, by **name** lookup |
| Interleaved, fixed stride | `Box`, `Sphere`, `Cone`, `Cylinder` | `shadergeometry.VertexFormat` + `bind_interleaved_vbo` |
| `_MeshGPU`, one VAO per mesh | `PBRMesh` and everything built on it | fixed **locations**, no lookup |
| Its own raw GL | vegetation, terrain, text, backgrounds | itself |

The first binds by name and so needs a VAO per program; the third binds by
location and so needs only one VAO per mesh, forever. That difference is the
whole performance argument below.

## The proposal

### 1. One declared table, and it is locations

`OpenGLContext/scenegraph/vertexsemantics.py`: the semantic vocabulary, the
canonical location for each, its component count and its GL type, in one module
that the shaders, the geometry nodes and the documentation all cite. The main
table above becomes that module; `vrml97_point.vert` and the line program are
renumbered onto it, and `position_location` goes.

**Locations rather than names, because a VAO records locations.** A VAO built
against name lookups is only valid for the program those names resolved in, so a
scene drawn under the lit program, the unlit program and a shadow pass needs
three of them per geometry. Fixed locations mean one VAO per geometry serves
every conforming program — which is what `PBRMesh` already gets and what the
VRML97 array geometry does not.

### 2. A shader names its own variables; the engine puts them on the right locations

`glBindAttribLocation(program, location, name)` runs *before* linking and says
"whatever the shader called this input, it comes in at this location". So the
shader author writes what reads well:

```glsl
#version 330 core
in vec3 vertexInput;
in vec3 surfaceNormal;
uniform mat4 mat_modelproj;
```

and declares the mapping on the node:

```python
GLSLObject(
    shaders = [ ... ],
    attributes = [
        ShaderInput( semantic='POSITION', name='vertexInput' ),
        ShaderInput( semantic='NORMAL',   name='surfaceNormal' ),
    ],
)
```

`GLSLObject.compile` walks that list and issues one `glBindAttribLocation` per
entry before `glLinkProgram`. A `layout(location = …)` qualifier in the source
takes precedence over `glBindAttribLocation` (GLSL 3.30 §4.3.8.2), so a shader
that states its own locations keeps them and the mapping is ignored rather than
fighting it.

A list of nodes rather than a dict, because that is how `uniforms`, `textures`
and `objects` are already declared on `GLSLObject`, and because a `ShaderInput`
has somewhere to grow (an explicit `location`, a `required` flag, a default value
for a semantic the geometry does not carry).

### 3. The default mapping, so most shaders declare nothing

`ShaderInput` entries are applied **over** a default table — the engine's own
names — so a shader that declares `in vec3 aPosition;` needs no `attributes` at
all, and one that renames only its position declares one entry and still gets
normals and UVs. This is the same composition rule as `Context.profile` over
`contextDefinition`.

### 4. What a geometry node offers: `GeometryArrays`

One object describes what a geometry has to give, by semantic:

```python
class GeometryArrays:
    """Buffers a geometry node offers, keyed by vertex semantic."""
    arrays: dict[str, VertexArray]   # semantic -> (vbo, size, type, stride, offset)
    indices: vbo.VBO | None
    draw_mode: int
    count: int
```

`geometry.vertexArrays(mode)` returns one, cached against the fields it was built
from. The binder is then a single function for the whole engine:

```python
vao = bind_geometry(arrays, program)   # cached on (geometry, program-signature)
```

`_MeshGPU` already *is* this object — `attr_layout` is `arrays` with the
semantics implicit in the location constants — so `PBRMesh` implements
`vertexArrays` by naming what it already has. The three other supply shapes
become three constructors of `GeometryArrays` rather than three binders:
separate VBOs, interleaved with a stride, and raw. `bind_separate_arrays`,
`bind_interleaved_vbo` and `VertexFormat` collapse into it.

### 5. PBR geometry

Nothing changes for it, which is the point of choosing locations over names:

- `_MeshGPU`'s single VAO stays single, because every conforming program reads
  the same locations. A `Shader` appearance over a `PBRMesh` binds that VAO and
  draws.
- Instancing keeps 5–10 and skinning 12–13; the table declares them reserved so a
  user shader that wants a custom per-vertex input is told which locations are
  free rather than discovering it as a silent overwrite.
- `configure_appearance` is about *materials* and is untouched. A `Shader`
  appearance supplies its own uniforms, so `Shape._render_shader` gains one
  branch: use the appearance's program if it has one, the pass's otherwise, and
  bind the geometry's arrays to whichever.

### 6. The legacy default

Two different defaults are worth having, and only the first is required for the
above to work:

**(a) The semantic default** — §3. Any geometry feeds any conforming shader with
nothing declared. This is the one to build.

**(b) A compatibility prelude**, opt-in. A GLSL 1.20 shader — no `#version`, or
`#version 120`, reading `gl_Vertex`, `gl_Normal`, `gl_MultiTexCoord0`,
`gl_ModelViewProjectionMatrix`, `gl_NormalMatrix`, writing `gl_FragColor` — can
be made to link in a core context by prepending a header that declares the
engine's attributes and uniforms and `#define`s the old names onto them:

```glsl
#version 330 core
layout(location = 2) in vec3 _oglc_position;
layout(location = 1) in vec3 _oglc_normal;
uniform mat4 mat_modelproj;
uniform mat3 mat_normal;
#define gl_Vertex vec4(_oglc_position, 1.0)
#define gl_Normal _oglc_normal
#define gl_ModelViewProjectionMatrix mat_modelproj
#define gl_NormalMatrix mat_normal
out vec4 _oglc_fragColor;
#define gl_FragColor _oglc_fragColor
```

That is enough for `shaderobjects.py`, `shader_ng.py` and the toon/Mandelbrot
tutorial shaders to run under core unchanged, and for anyone with a decade-old
`.vert` file in a scenegraph.

**What it costs, stated plainly.** `attribute`/`varying` are still keywords a
core compiler rejects, so the prelude cannot be a pure prepend — it has to
substitute those two words in the source as well, which makes it a *translation*
rather than a header. A translation that mostly works is a poor thing to have
under a tutorial, because the reader learns the old spelling and the engine
quietly rewrites it. So: build it, put it behind an explicit field
(`GLSLObject.legacy = True`, or a `#pragma` in the source), point the migration
path at it, and do not let the tutorials rely on it. The tutorials get rewritten
([SHADER-TUTORIALS-CORE.md](SHADER-TUTORIALS-CORE.md)); this is for content
nobody is going to rewrite.

### 7. Say what is missing rather than drawing nothing

At link time the active attributes of the program are queryable
(`GL_ACTIVE_ATTRIBUTES`). Compare them with what the geometry offers, and a
shader asking for a semantic the geometry has not got is a line naming both,
once, through `RenderFailureLog` — instead of a shape that draws at the origin,
or draws black, with no GL error. This is the same instrument the profile flip
put in, applied one level up.

## What this does not cover

- **`ShaderGeometry` keeps its own path.** A node that supplies raw
  `ShaderBuffer`/`ShaderAttribute` arrays is saying "I am the geometry *and* the
  layout", and that is a legitimate, already-working thing to be. The mechanism
  above is for engine geometry meeting someone else's shader.
- **Per-instance and per-primitive inputs** beyond the reserved locations.
- **Compute and geometry stages.** Vertex inputs only.

## Staging

1. ✅ **Landed.** `vertexsemantics.py`: the table, alone, cited from the shaders,
   from `pbrmesh.py` and from `passes/instancing.py`. The conflicting tables
   became one -- `vrml97_point`, `vrml97_line`, `vrml97_background`,
   `hdr_background` and `terrain_splat` were renumbered onto it,
   `vrml97_vertex_color` moved its colour off the tangent location, and
   `position_location` went. `shadergeometry` binds at the declared locations
   instead of looking names up in a program, so `PointSet`, `IndexedLineSet`,
   the NURBS surfaces, `IndexedPolygons` and the terrain each keep one VAO
   rather than one per program. `tests/unit/test_vertex_semantics.py` holds
   every shader in the package to the table.
2. `GeometryArrays` + `bind_geometry`, with `_MeshGPU` and
   `bind_separate_arrays` reimplemented on it. Still no new capability, and the
   VRML97 array geometry stops rebuilding a VAO per program.
3. `ShaderInput` on `GLSLObject`, the `glBindAttribLocation` pass, the default
   mapping. `Shape._render_shader` binds the appearance's program when it has
   one. `shaderobjects.py` and the declarative tutorials drop their
   compatibility declaration.
4. The missing-attribute report.
5. The legacy prelude, behind its own field.

Steps 1 and 2 are worth doing whether or not 3 follows: they remove the
two-tables wart and a per-program VAO rebuild from the VRML97 geometry path.

### Left standing after step 1

`ShaderGeometry` (`scenegraph/shaders.py`) still binds by name, because a node
that supplies its own `ShaderAttribute` arrays names them itself; it passes the
program as its VAO cache key and gets one VAO per program. That is what step 3
changes, by letting the node declare which semantic each name carries.
