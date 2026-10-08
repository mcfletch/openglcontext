# X3D Support

**Status: IN PROGRESS (from 2026-10-07).** The
maintainer's decisions are recorded in §14: approach C1, `vrml.x3d` in
pyvrml97, X3DUOM 4.1 fetched by download, `PBRMaterial` reworked into the X3D
`PhysicalMaterial`, and no script execution. A throwaway spike (described in
§5) was run to test the central claims; none of it is committed.

**Progress** (branch `x3d` in pyvrml97 and openglcontext, checked out in
their main checkouts; the remaining phases on branch `x3d-complete` in the
worktrees `pyvrml97/.claude/worktrees/x3d-complete` and
`openglcontext/.claude/worktrees/x3d-complete`; `[x]` done, `[ ]` pending):

- [ ] Nodes without an engine implementation (2026-10-08 audit of
  `prototypes()` against `vrml.x3d.nodes.CONCRETE_NODES`: 124 of 266). Below,
  under the phase each belongs to; a grouping node or geometry left to its
  declaration draws nothing (a `StaticGroup`'s children are not drawn)

- Phase 1, pyvrml97 groundwork (§9.1)
  - [x] `ElevationGrid.xSpacing`/`zSpacing` 1.0, `NavigationInfo.type` `["WALK", "ANY"]`
  - [x] `MFVec2d` double precision
  - [x] root adoption stops at rooted subtrees; `ROUTE` roots nothing
  - [x] field types `SFDouble`, `MFDouble`, `SFColorRGBA`, `MFColorRGBA`, `MFBool`, `MFImage`, `SFQuaternion`, `MFQuaternion`
  - [x] `accessType`, bounds, choices and unit category on field descriptors
  - [x] `nodetypes.Sensor` is a `Children`
- Phase 2, vocabulary (§9.2, §9.3)
  - [x] XML field codecs (`vrml.x3d.codecs`)
  - [x] generator `tools/generate_x3d.py`: pinned download, digest, cache
  - [x] generated `vrml/x3d/nodes.py` and `nodes.pyi`
  - [x] `AliasField` for renamed fields
  - [x] `Dialect`/`FieldRename`/`FieldDefault` nodes; VRML97 dialect; 3.x dialects from the version diff
  - [x] `vrml.vrml97.basenodes` re-exports the X3D classes
  - [x] `x3d-generated` tox environment and preflight check
- Phase 3, builder and readers (§9.4, §9.5, §9.7, §9.9)
  - [x] `X3DScene`, `LoadProblem`, `ComponentInfo`, `UnitInfo`, `MetaInfo` nodes
  - [x] `SceneBuilder`
  - [x] XML reader (`.x3d`, `.x3dz`)
  - [x] JSON reader
  - [x] ClassicVRML/VRML97 reader (SimpleParse grammar); VRML97 parsing on the builder (the legacy `vrml.vrml97.parser` is kept)
  - [x] prototypes, `EXTERNPROTO`, `Script` field declarations (builder, XML, JSON)
  - [x] `UNIT` scaling
  - [x] `IMPORT`/`EXPORT`
  - [x] profiles and `validate()`
  - [x] `vrml.x3d.load()` and `loads()`; local `EXTERNPROTO` files
  - [x] corpus fetch script, committed subset, cross-encoding test (XML, JSON and ClassicVRML; Fast Infoset read over both archives, and held to the XML graph for the scenes whose .x3db is the same revision)
- Phase 4, writers (§9.6)
  - [x] XML (with canonical form), ClassicVRML/VRML97, JSON writers; `dump()`/`dumps()`
  - [x] round trip and schema validation tests (1,181 corpus scenes in each encoding; written XML valid against the X3D 4.1 XSD; `.wrl` back to VRML97)
  - [x] dialects record each version's absent fields; reading warns on one, writing refuses a non-default one
- Phase 5, `PhysicalMaterial` (§9.13)
  - [x] `PBRMaterial` reworked into `PhysicalMaterial`; extension and engine fields
  - [x] texture fields and mapping labels; per-channel texture transforms
  - [x] alpha on `Appearance` (AUTO reads the base texture's alpha), sidedness on `solid`; `UnlitMaterial`
  - [x] OpenGLContext callers migrated
  - [x] callers in the other projects migrated, each on branch `x3d` in its own worktree: openglcontext-editor `835f5ec` (`gathered()`/`combined_mesh()` take an appearance), twig-bb `11865b5` (shader animation drives a `TextureTransformMatrix3D` labelled `TEXCOORD_0:tcmod`), glisteel `c30573b` (mesh helpers take no material), glisteel-editor `f825e8b`, marble-demo `16bbf38`, marble-editor `8057c41`
  - [x] glTF material round trip through X3D (`vrml.x3d.extension`: a class's `x3dExtension` set, `x3dEquivalent()`; the set is named `OpenGLContext`, since it carries the engine's fields as well as glTF's)
  - [x] the packed material block and `pbr_material`'s per-appearance view kept in `vrml.cache` (`MATERIAL_BLOCK_KEY`, `VIEW_KEY`)
  - [x] the material blocks: `PBRShaderProgram._material_ubos` is gone; each material's block hangs off the material through `contextresources.ContextNames` (`pbrpass._MATERIAL_BLOCKS`), shared by every program in a context and deleted when the material is collected or the context is lost
  - [x] left as it is: the glTF loader's `_SHARED` is not a memo of a node's data but the identity of a texture node, found by its image's content and held weakly; `vrml.cache` holds data strongly under a client node, and there is no client here. Open for the maintainer if a content-keyed table in `vrml.cache` is wanted all the same. The table: (texture nodes interned by image content, so two documents' copies of one image are one node and instance together)
- [ ] Visual suite (not this plan's, found during Phase 5): `8a81ad99` made
  `ContextDefinition.renderer` default to `pbr`, so 53 VRML97 demo scripts
  draw through the PBR pass against baselines captured from the VRML97 pass.
  Each demo either declares `renderer='vrml97'` or has its baseline re-blessed;
  the maintainer's choice
  - 2026-10-07: the main checkout holds 57 re-blessed baselines, uncommitted;
    this branch's renders of 51 of the failing scripts match them exactly
- [x] `oglc-x3d-regression` (2026-10-07): every .x3d of Web3D's ConformanceNist and
  Vrml2Sourcebook archives (1181) drawn as authored in a plain Context, compared with
  baselines in `tests/reference_images/x3d_baseline`, X_ITE's render beside each
  (`--reference x_ite`, the default), or Web3D's own render of the bound viewpoint
  (1065 have one). Shared machinery with the glTF tool in
  `OpenGLContext.testing.renderregression`; the corpus is `vrml.x3d.corpus`
  - fixed on the way: a document with no viewpoint is seen through X3D's default
    (fieldOfView 0.7854); a viewpoint's fieldOfView spans the smaller dimension;
    MovieTexture is kept and draws nothing (it crashed 57 documents); Billboard has
    identity matrices (it crashed 22); a prototype instance stands for its body's
    first node (3); cube-map faces resampled to one square (5); a prototype body
    holding another instance no longer recurses on copy; resolver content roots,
    so the examples reach images above their folders
  - [ ] baselines not yet blessed: review the report first
    (`oglc-x3d-regression`, then `--bless`)
  - [ ] found by comparing with Web3D's renders, still to fix: a grey plane drawn
    that Web3D does not (SphereSensor/multisensor); Figure20_17a framed differently
  - [x] Inlines naming another archive's scenes: the corpus is one tree
    (`vrml.x3d.corpus.examples`), `--fetch` adds the archives the drawn ones name
    (`with_references`: X3dForWebAuthors), and the folder of every archive's
    examples is the content root. pyvrml97's corpus test reads every fetched
    archive; X3dForWebAuthors brought the ROUTE-to-a-field-the-version-lacks
    warning
  - [x] X_ITE references (`--reference x_ite`): drawn by
    `scripts/x3d_xite_references.py`, a `uv run` tool with Playwright as inline
    script metadata, not part of the installed engine; X_ITE 16.4.3 (MIT) from npm,
    digest-checked, served with the corpus from 127.0.0.1 to Playwright's headless
    Chromium (SwiftShader). The renders are committed to
    `tests/reference_images/x3d_xite`, which the regression reads. Chromium needs
    libnss3, libnspr4, libatk1.0, libatk-bridge2.0, libxdamage1 and libatspi2.0 in
    the container (the workspace's `.devcontainer/Dockerfile` installs them)
  - [x] a document's `Material` in the PBR pass: drawn by X3D's Phong equation
    (below); the vrml97 pass fogs (below)
  - [x] a Shape with no Appearance in a document is drawn unlit white
  - [x] X3D's fog curves fade the displayed colour, after tone mapping
    (`tests/unit/test_fog_render_gl.py`); the aerial-perspective curve stays in
    linear light
  - [x] a document's Appearance with no material is unlit
    (`tests/unit/test_document_unlit.py`)
  - [x] a document with no NavigationInfo has the headlight (Figure23_1's ground
    was lit by its 0.2 DirectionalLight alone)
  - [x] a document is lit without the built-in studio environment
    (`ibl.scene_mode`): Floor 61% -> 0% unlike X_ITE, the temple 57% -> 8%, the
    tree 55% -> 0.05%
  - [x] X3D's attenuation floor of 1 (`lightAttenuationFloor`): the dungeon's
    torch, 0.2 m from a wall with attenuation `0 0.6 0`, lit it eight times over
  - [x] the VRML97 pass fogs (`_x3d_fog_inc.glsl`, `VRML97ShaderProgram.set_fog`,
    `FlatPass.fogSetup`); `oglc-x3d-regression --renderer vrml97`
  - [x] the VRML97 pass draws a mesh's per-vertex colours (ElevationGrid and the
    triangle sets: `hasVertexColor` in its lit shader), and an instanced group's
    texture (`FlatPass._bindGroupTexture`)
  - [x] a viewpoint, background, fog or navigation in an Inline's file is not
    bound first (pyvrml97 `binding.current_path`; 19775-1 7.2.2 rule 4):
    Figure20_09 opened on the vaulted ceiling's own viewpoint
  - [x] the PBR pass draws a document's Material by X3D's Phong equation
    (`PHONG_BIT`, `phong_factors`, `_phong_inc.glsl` shared with the VRML97 pass);
    each light's `ambientIntensity` (`lightAmbientIntensity`), no flat fill in a
    document; an Inline holds the scene its nodes were read into, which they
    hold only weakly (an Inline's nodes had no root, so were not a document's,
    and an Inline among them could not resolve a relative url)
  - [ ] whole corpus against X_ITE (2026-10-07): median 4.9% of pixels unlike
    with the PBR pass, 1.8% with the VRML97 pass, whose worst were the fog
    documents it did not fog;
    to look at next: Background fogged (fogtype_linear: our frame is the fog
    colour), the Snake's background colour, Figure20_09's viewpoint, and the
    SphereSensor tests' framing. X_ITE runs Scripts, so its render of a document
    whose scene a Script builds shows what ours does not draw
  - [x] Background image faces: each side drawn as its own quad once its image
    has loaded, turned as X3D says, transparent parts showing the sky
    (`tests/unit/test_background_faces.py`); the old cube map drew only with
    all six and mirrored each. `CubeBackground.faceLayout "CUBEMAP"` keeps GL's
    layout for the IBL environment and glTF cube map skies
  - [x] Billboard turns toward the first view's camera once a frame
    (`FlatPass.faceBillboards`, `billboard.billboard_rotation`,
    `tests/unit/test_billboard.py`)
  - [x] the cut-out tree drew nothing: a face set with no texCoord had no
    texture coordinates, so every vertex read the image's corner. X3D's default
    (`composedgeometry.default_texcoords`) for IndexedFaceSet and the triangle
    sets (`tests/unit/test_default_texcoords.py`)
  - [x] test_binding5 bound the third Background: the capture clock started at
    0, so TimeSensors with `startTime 0` ran at load and bound it.
    `OPENGLCONTEXT_CAPTURE_START`; the regression starts worlds at 2000-01-01
  - [x] one groundColor with no groundAngle is a ground over the lower
    hemisphere, as X_ITE draws it and as one skyColor with no angle is a sky all
    over (2026-10-07, the maintainer's choice; 106 of the 206 documents over 10%
    unlike X_ITE). The spec allows the pair and does not say how far it reaches;
    NIST's description of verify_clampingsky reads it the other way.
    verify_lastground matches NIST's expected image; X_ITE carries the last
    ground colour up to the equator
  - [x] every PIL-loaded 2D texture was uploaded top row first, which glTF wants
    and VRML97/X3D do not: a texture node now says which row (0, 0) names
    (`_Texture.TOP_FIRST`, true for `ImageDataTexture`), the texture cache keys on
    it, and only cube map faces are always top row first
    (`tests/unit/test_texture_row_order.py`); an `ImageDataTexture` is written to
    X3D upside down to keep its coordinates' meaning
  - [x] a Box's bottom face was turned 180 degrees from X3D's rule
    (`tests/unit/test_box_texture_faces.py`). X_ITE 16.4.3 turns both its top and
    bottom faces 180 degrees from the rule
  - [ ] a `PBRMesh` is written to X3D as an empty `<PBRMesh/>`: its arrays are not
    fields, so the mesh is lost
- [ ] At merge: rebuild pyvrml97's accelerator in the main checkout
  (`accelerate/`, `setup.py build_ext --inplace` or a reinstall); its
  `fieldaccel2` announces sets through `vrml.event.announce` (pyvrml97
  `8f34463`), and the build the venv loads predates it. The tests here ran
  against the worktree's own build.
- [ ] At merge: OpenGLContext's runs on this branch used the opengl_extrusions
  `uv-seam` worktree, which merges with it.
- [ ] Visual suite, this branch (2026-10-07, run with `PYTHONPATH` on the
  worktrees, compared with the main checkout's current baselines): these
  scripts render differently, each traced to a change on the branch;
  re-bless them in the main checkout when this merges
  - `simplerotate`, `nehe6_multi`, `nehe6_timer`, `multitexture_1`,
    `saveimage`, `pbodemo`, `shader_instanced`, `shader_instanced_mapped`,
    `transparentsorted`: an `ImageTexture` is drawn the right way up;
    `shader_instanced` and `shader_instanced_mapped` also turn each sphere's
    facets, which start at the texture seam at the back (2026-10-08)
  - `pygame_font`: its SERIF and TYPEWRITER faces are a serif and a
    monospaced font; the font classes had given both as a sans face
  - `node_modify`: as `timesensorobject`, below
  - `roads_demo`: its LINEAR Fog fades the displayed colour, as X3D says
  - `cubeback_rot`, `cubebackgroundobject`: the teapot is drawn with its own
    material; the former cube left its state behind for the teapot
  - `timesensorobject`: the TimeSensor's fraction is measured from
    `startTime` on the engine clock, one frame ahead of the old Timer's
  - `lightobject`: `cycleTime` is sent when the TimeSensor starts, as X3D
    says, so the demo's random light switch runs at start-up
  - `zones_demo`: its lamps' `radius = 8` is honoured (`f10f71ca`)
  - `hud_demo`: one `groundColor` and no `groundAngle` is the ground
    hemisphere (`2dea754e`)
  - `glelathe`: minified rings are mipmapped, and with opengl_extrusions'
    `uv-seam` branch the spiral and screw no longer squeeze the texture back
    across the contour's seam
  - [x] `spherebackgroundobject` crashed: `bound` restored on the engine's
    backgrounds and Fog (`scenegraph.bindable`), the tutorial's own text
    restored
- Phase 6, OpenGLContext Interchange (§9.11, §9.12, §9.14)
  - [ ] implementations rebased on `vrml.x3d.nodes` (done: the suite passes against them); every X3D node registered (done: CADAssembly, CADLayer, CADPart, PickableGroup, Anchor; left: LayoutGroup, ScreenGroup, Viewport)
  - [x] the render pass skips nodes whose X3D `visible` is false (`FlatPass.onVisibleChange`)
  - [x] an Inline's scene arriving after the world was walked is drawn (`CHILDREN_CHANGE_SIGNAL`, delivered through the render queue)
  - [x] lights: X3D's `shadows` replaces `castShadows` (true for a light made in code, X3D's false in a document: the builder's `declared_defaults`); `shadowIntensity` per shadow slot; `Shape.castShadow` replaces `castsShadow`
  - [x] `InstancedShape`: not in the X3DUOM 4.1 vocabulary the declarations are generated from, so there is no X3D node to implement; the engine's own instancing (`passes/instancing.py`) collapses repeated shapes
  - [x] X3D loader (`loaders/x3d.py`, `prototypes()`), viewer adapter with the `head` as a notice, `.json` sniffing, archive members
  - [x] `Inline` reads any registered format (`SceneReader.nodes()`), X3D's `load` field; the builder roots nodes before their fields are set
  - [x] Interchange geometry: the six triangle sets, `ElevationGrid` (with `creaseAngle`), `LineSet`; `ColorRGBA`, `Tangent`, `MultiTextureCoordinate` mapping labels (`composedgeometry`, `meshgeometry`); data nodes registered as their declarations
  - [x] Geometry2D: Rectangle2D, TriangleSet2D, Disk2D, ArcClose2D as meshes; Circle2D, Arc2D, Polyline2D, Polypoint2D through `DrawnAs` (`loaders.x3d.X3D_ONLY` for the name the NURBS trim curve holds)
  - [x] `Extrusion` rebased on X3D's declaration (its engine fields carried as `OpenGLContext` metadata)
  - [x] `TextureCoordinateGenerator` for a composed geometry's first set (`scenegraph.texgen`, the PBR vertex shader)
  - [x] point/spot `radius`: a cut-off in the shader paths; unbounded for a light made in code, 100 for a document's, a glTF light's `range`
  - [ ] `IndexedFaceSet` and the primitives onto the same arrays; `CoordinateDouble` rebased to a float32 origin
  - [x] `Appearance.texture` as a PhysicalMaterial's or UnlitMaterial's base map where theirs is NULL (X3D 4, 17.2.2.4 and 17.2.2.6; `physicalmaterial.AppearanceTextured`)
  - [x] docs/x3d.rst with the implemented-node list, held to `prototypes()` by a test
  - [x] light scope: `global` false lights only its parent group's descendants (`passes.lightscope`, the per-draw `lightsOff` mask); the engine's DirectionalLight made in code is global; VRML97 dialect default `global FALSE`
  - [ ] the fixed-function pipeline's light scope and radius
  - [x] content that draws nothing: `StaticGroup` (`x3dgroups`),
    `InlineGeometry` (`scenegraph.inlinegeometry`, a file's shapes joined by
    `scenegraph.meshdata.merged_arrays` from each geometry's `meshArrays()`);
    `CoordinateDouble` was already read wherever `Coordinate` is, and its
    precision past float32 waits on Geospatial's origin
  - [x] a shape's bounds followed its geometry's only when the geometry field
    itself was set: a volume cached as the geometry's own object kept it
    alive. `boundingvolume.cacheVolume` depends on the cache entry holding a
    volume it is given (`holdVolume`), so a changed `Coordinate` reaches the
    shape and its groups
  - [ ] `MultiTexture` (and `MultiTextureTransform` in use), `RenderedTexture`
  - [x] `FillProperties`, `LineProperties`, `PointProperties`
    (`scenegraph.drawproperties`; the wide-line program's geometry stage
    `vrml97_wide_line.geom`, `_pointsize_inc.glsl`, `_fill_inc.glsl`, and the
    compatibility profile's line width, line stipple and polygon stipple)
  - [ ] `AcousticProperties` with Sound
  - [ ] `ClipPlane`
  - [ ] `FontLibrary`
  - [x] X3D 4 `Material`'s diffuse, emissive, normal and occlusion textures with mapping labels; `normalScale`, `occlusionStrength`
  - [x] `TwoSidedMaterial` and `backMaterial` (`physicalmaterial.side_material`, the shape drawn a side at a time)
  - [x] `TextureBackground` (`scenegraph.texturebackground`, sharing `background.SkyAndCube`)
  - [x] `LocalFog` (`passes.localfog`, per draw beside the light scope); unlit surfaces are fogged
  - [x] `EnvironmentLight` from its coefficients as the scene's image-based light (`scenegraph.environmentlight`); its cube maps wait on Phase 8's CubeMapTexturing
  - [x] showcase: `oglc-x3d` opens `bin/x3d_gallery.x3d` (metals, marble, brick, sandstone, a scoped lamp, shadows, the triangle sets, ElevationGrid, an Inlined glTF vase); `tests/x3d_demo.py` tutorial and reference capture
- Phase 7, runtime (§9.10, §9.15, §9.16)
  - [x] event utilities, sequencers and `KeySensor` with their behaviour (`vrml.x3d.runtime`); the engine's `TimeTrigger` clock and `KeySensor` keys (`scenegraph/x3druntime.py`, `observeEvents`)
  - [x] every interpolator (`vrml.x3d.interpolation`, `vrml.x3d.runtime`; the engine registers pyvrml97's); `StringSensor`
  - [x] followers (`vrml.x3d.followers`; ticked through the render queue in the engine, `x3druntime.Ticked`)
  - [x] time is the scene's clock (`vrml.x3d.timing`, `Timed.now`; the engine's `SceneGraph.clock` is `systemtime`, so followers and `TimeTrigger` follow a capture's fixed step)
  - [x] bind stacks (`vrml.x3d.binding`): backgrounds (the engine's own too), fogs, viewpoints and NavigationInfo bound by `set_bind`; `next_viewpoint`
  - [x] `OrthoViewpoint` (`ViewPlatform.setOrthographic`), `nearDistance`/`farDistance`
  - [x] NavigationInfo `headlight` and `type` (`move.navigationinfo`), applied as they change; a document with none has X3D's default
  - [x] `ViewpointGroup` (displayed, proximity); NavigationInfo `visibilityLimit`
  - [x] NavigationInfo `speed` (relative to X3D's 1), `avatarSize` for the walking avatar, the viewpoint transitions and `transitionComplete`
  - [x] `centerOfRotation` (the examine pivot with nothing picked), `retainUserOffsets`, `viewAll`
  - [x] environmental sensors (`vrml.x3d.sensors`, sensed once a frame by `scenegraph.x3dsensors`)
  - [x] pointing-device sensors (`vrml.x3d.pointing`, the picked pointer through `scenegraph.x3dpointing`; the hit has no normal or texture coordinate)
  - [x] `TimeSensor` (`vrml.x3d.timesensor`): start, stop, pause, resume, and the engine's `rate`; polled by the context's time manager
  - [x] `LoadSensor` (`vrml.x3d.loadsensor`); `Inline` and `ImageTexture` record their load state
  - [x] `Anchor`: a group; `#viewpoint` bound, other urls through `Context.OnAnchor`
  - [x] the cascade: a field is reached once per cascade, through handlers and their outputs (`vrml.event`)
  - [x] `Collision`: `enabled` and `proxy` in the walk's collision world; `collideTime` and `isActive` from the avatar's touches (`physics.x3dcollision`)
  - [x] `getTimer(context)` back on the engine's TimeSensor, over the X3D sensor (`SensorTimer`; its multiplier is the sensor's `rate`)
  - [ ] Picking: `LinePickSensor`, `PointPickSensor`, `PrimitivePickSensor`,
    `VolumePickSensor`
- Phase 8, engine-mapped components (§9.17)
  - [x] CADGeometry: `CADFace` (`x3dgroups`), `QuadSet`, `IndexedQuadSet`
    (`meshgeometry`, two triangles a quad)
  - [ ] NURBS: the 13 nodes on the NURBS evaluator; the VRML97 extension's
    nodes kept for the worlds that use them
  - [ ] CubeMapTexturing: `ComposedCubeMapTexture`, `ImageCubeMapTexture`,
    `GeneratedCubeMapTexture`
  - [ ] Texturing3D: `ImageTexture3D`, `ComposedTexture3D`, `PixelTexture3D`,
    `TextureCoordinate3D`, `TextureCoordinate4D`, `TextureTransform3D`
  - [ ] TextureProjection: `TextureProjector`, `TextureProjectorParallel`
  - [x] Shaders: `ComposedShader`, `ShaderPart`, `ShaderProgram`,
    `ProgramShader`, `PackagedShader`, the vertex attributes
    (`scenegraph.x3dshaders`, `scenegraph.x3dglsl`): the first alternative
    that is GLSL and links draws, `isSelected`/`isValid` sent, the material
    drawn while loading or where none runs; every GL stage (tessellation as
    patches in a 4.x context); parts read in the background under the
    document's policy, `data:`, url text and 4.1 `sourceCode`; linked on
    first completion and on `activate` (I.5); declared fields as uniforms by
    Table I.3, converted to the declared type, textures as samplers;
    X_ITE's binding names (`x3d_Vertex`, `x3d_ModelViewMatrix`,
    `x3d_NormalMatrix`, `x3d_LightSource[]`, `x3d_Material`,
    `x3d_Texture2D[]`, `x3d_TextureMatrix[]`, ...); `attrib` drawn into the
    mesh at locations 15+, then the per-instance ones; GLSL 1.x translated to
    3.30 core, run as written in the compatibility profile; the object id
    written beside the colour; `PackagedShader` of GLSL as one text with
    `X3D_<STAGE>_SHADER` macros, other languages passed over;
    `oglc-x3d-shaders` and `tests/x3d_shaders.py`. Corpus: Basic/Shaders'
    two `.x3d` have empty `ShaderPart`s and draw their material; their
    `.x3dv`/`.wrl` copies write `language GLSL` unquoted and do not read;
    `TestDiagnosticOverloadedChildNodes` fails on `GeneratedCubeMapTexture`
    (CubeMapTexturing)
  - [ ] ParticleSystems: `ParticleSystem`, the six emitters, the three physics
    models
  - [ ] HAnim: `HAnimHumanoid`, `HAnimJoint`, `HAnimSegment`, `HAnimSite`,
    `HAnimDisplacer`, `HAnimMotion`, `HAnimPose`
  - [ ] RigidBodyPhysics: the 14 nodes on omi_physics
  - [ ] Layering, Layout: `Layer`, `LayerSet`, `Viewport`, `Layout`,
    `LayoutGroup`, `LayoutLayer`, `ScreenGroup`, `ScreenFontStyle`
  - [ ] Sound: the 4.0 audio graph (19 nodes) on omi_audio
- Phase 9, Fast Infoset reader
  - [x] `vrml.x3d.fastinfoset`: X.891 decoder to XML events, iterative over element depth; values in an algorithm without a decoder arrive `Undecoded`
  - [x] `vrml.x3d.fivocabulary`: tables A.2-A.5 as Web3D's files number them (attribute names one past A.3 from 57, a 1025-entry table, 54-56 unknown); delta-zlib integers in the files' layout at index 34
  - [x] `vrml.x3d.readers.fastinfoset` over the XML reader's handlers (`ElementReader`); typed values through `codecs.from_values`
  - [x] all 1071 non-empty `.x3db` files of the two archives read; facts in pyvrml97 `specs/x3d/fast-infoset.md`
  - [x] the engine opens `.x3db`, `.x3db.gz`, `model/x3d+fastinfoset`, `model/x3d+binary`
  - not read: the quantized, zlib float/double and range integer encoders, whose layouts the text leaves open and no sample uses
- [x] SimpleParse speed: the ClassicVRML reader runs at about 7 MB/s against
  16.5 MB/s for XML through expat. SimpleParse should be much faster than that;
  profile the grammar and the result-tree walk and find where the time goes
  - found: the builder work is the same for both readers (about 0.3 s for a
    4.7 MB STEP scene); the difference was `mxTextTools.tag`, about 370 ns per
    number whatever its length, the cost of the nested group calls per value.
    Whitespace runs and a flatter number rule gave 1.45x
  - landed: `numberRun`, a bracketed run of number characters matched as one
    span that the field's codec decodes; parse 22 -> 81 MB/s on that scene,
    whole read 0.52 s -> 0.23 s (XML: 0.17 s). A `serial` test holds the parse
    of a 200 000-number list under 0.75x its NumPy decode
  - [x] the engine's `.wrl` loader reads through `vrml.x3d` (VRML97 dialect)
    rather than `vrml.vrml97.parser`: `vrml97_prototypes()` is the X3D
    vocabulary with the engine's registry and `standardPrototype`
    registrations in place; the 41 `.wrl` files in the repository build the
    same node types, about 3x faster; a prototype instance's `children` no
    longer refers to itself (`proto_is_simple.wrl`); a broken world loads with
    `problems` instead of raising
  - open for the maintainer: `vrml.vrml97.parser`/`parseprocessor` remain in
    pyvrml97, used by its own tests and by any program importing them; the
    engine no longer does
- Phase 10, Geospatial, VolumeRendering, GaussianSplats, `MovieTexture`
  - [ ] Geospatial: the 11 nodes
  - [ ] VolumeRendering: the 13 nodes
  - [ ] GaussianSplats
  - [ ] `MovieTexture` through the optional decoder
- Documentation (§12)

**Touches:** pyvrml97 (the scenegraph model, parsers, field types), OpenGLContext
(loaders, scenegraph implementations, PBR pass, event loop), omi_physics,
omi_audio and opengl_extrusions for the component mappings in §9.17.

**Related plans:** [SCENE-LOADER.md](SCENE-LOADER.md),
[GLTF-COMPLETE-SUPPORT.md](GLTF-COMPLETE-SUPPORT.md),
[PBR-MATERIALS.md](PBR-MATERIALS.md), [RAYCAST-PICKING.md](RAYCAST-PICKING.md),
[MOVEMENT-MODES.md](MOVEMENT-MODES.md), [CHARACTER-ANIMATION.md](CHARACTER-ANIMATION.md),
[PHYSICS-COLLISION.md](PHYSICS-COLLISION.md), [INSTANCED-GEOMETRY.md](INSTANCED-GEOMETRY.md).

## Summary

X3D is VRML97's successor and keeps its scenegraph model: nodes with typed
fields, `DEF`/`USE`, `PROTO`, `ROUTE` and the event cascade. What it adds is a
larger vocabulary (267 concrete nodes in 37 components in 4.1, 260 in 36 in
4.0, against VRML97's 54), four file encodings instead of one, profiles that name subsets,
and in 4.0 a glTF-aligned physically based material model. pyvrml97 already is
a VRML97 scenegraph, and OpenGLContext already renders it through the PBR pass.
X3D support is therefore mostly a vocabulary problem and an encoding problem,
with the rendering largely in place.

The plan is:

1. Generate the X3D node declarations for pyvrml97 (`vrml.x3d`) from the **X3D
   Unified Object Model** (X3DUOM) 4.1, the machine-readable description Web3D
   publishes for every X3D version and that the `x3d` PyPI package is itself
   generated from. The generator downloads the X3DUOM at a pinned revision;
   the generated module is checked in, with a test that it matches what the
   generator produces from that revision.
2. Make that vocabulary **the** pyvrml97 node model. VRML97 and earlier X3D
   versions become *dialects* read into the same classes: dialect nodes listing
   renamed fields and changed defaults, applied at the document boundary on
   read and on write.
3. Put all four encodings (XML, ClassicVRML/VRML97, JSON, Fast Infoset binary)
   in front of **one scene builder** that owns `DEF`/`USE`, prototypes, `IS`,
   routes, `IMPORT`/`EXPORT` and units. Each reader becomes a thin
   tokeniser-to-builder adapter.
4. Rebase OpenGLContext's node implementations onto the generated
   declarations, register the X3D loaders with `SceneLoader`, and map X3D 4's
   geometry and lights onto the existing PBR pass, mesh arrays and caches. The
   engine's `PBRMaterial` becomes its implementation of X3D's
   `PhysicalMaterial`, so glTF and X3D content share one material node.
5. Implement the event model (cascade, sensors, interpolators, sequencers,
   followers, triggers) as renderer-independent Python in pyvrml97, where it is
   testable without a window. OpenGLContext feeds it time, picks and viewer
   pose. `Script` nodes are read, kept and written, and never run.

The `x3d` PyPI package is not used at run time (§3, approach A); X3DUOM, the
same upstream it is built from, is.

## 1. Where things stand

Facts from a survey of the two codebases (October 2026):

- pyvrml97 models VRML97: `vrml.node.Node` with field descriptors
  (`vrml/field.py`, `vrml/fieldtypes.py`), prototypes as generated classes
  (`node.prototype`), `IS` maps, `ROUTE` objects built on PyDispatcher
  (`vrml/route.py`), and per-node caches that invalidate on field change
  (`vrml/cache.py`). The 54 VRML97 node declarations in
  `vrml/vrml97/basenodes.py` are hand-written.
- `vrml/vrml200x/parser.py` is a ClassicVRML header grammar. It fails on every
  one of the 1,181 `.x3dv` files in the Web3D conformance archives (the header
  is written `#X3D V3.0 utf8` where the grammar expects a bare number, and
  comment lines between header statements are rejected). Nothing in
  OpenGLContext uses it.
- `IMPORT`/`EXPORT` productions exist in that grammar but are not reachable
  from `rootItem`. `EXTERNPROTO` records its URL; nothing fetches it. `Script`
  is a stub that declares fields and runs nothing.
- pyvrml97 registers most X3D field types already (`SFVec3d`, `SFMatrix4f`,
  `MFVec4d`, …). Missing: `SFDouble`, `MFDouble`, `SFColorRGBA`, `MFColorRGBA`,
  `MFBool`, `MFImage`. `MFVec2d` is declared over the single-precision
  `_MFVec2f` base (`fieldtypes.py:1065`).
- OpenGLContext reads VRML97 through `loaders/vrml97.py` (the older `Loader`
  registry) and `viewer/adapters/vrml.py` (the `SceneLoader` adapter registry).
  Nothing registers `.x3d`; `viewer/source.py` lists it among archive scene
  suffixes, so an `.x3d` member raises `UnknownSourceType`.
- `Inline` loads through the older `Loader` registry only, so it can inline
  VRML97 and OBJ but not glTF.
- OpenGLContext implements about 40 of the 54 VRML97 nodes; the pointing-device
  sensors, `ProximitySensor`, `VisibilitySensor`, `NavigationInfo` (collected,
  never read), `Anchor` (children never traversed), `MovieTexture`,
  `ElevationGrid` and `NormalInterpolator` are declarations without behaviour.
- The engine has subsystems that X3D components map onto but that are not
  exposed as X3D nodes: `PBRMaterial` (glTF metallic-roughness plus the KHR
  extensions), `ImageBasedLight`, `PBRMesh`, `InstancedShape`, skinning, the
  NURBS evaluator, particles, cube-map reflection probes, picking, omi_physics,
  omi_audio.

The X3D node coverage this gives today, by X3D component (name matches only; a
match counts as implemented if OpenGLContext supplies the class, as a stub if
the class is pyvrml97's bare declaration):

| Component | Nodes | Implemented | Stub |
|---|---:|---:|---:|
| Geometry3D | 7 | 6 | 1 |
| Grouping | 4 | 3 | 0 |
| Lighting | 4 | 3 | 0 |
| Navigation | 7 | 4 | 1 |
| Interpolation | 13 | 5 | 1 |
| Texturing | 11 | 3 | 2 |
| Shape | 10 | 3 | 0 |
| Rendering | 16 | 3 | 2 |
| Text | 3 | 2 | 0 |
| EnvironmentalEffects | 5 | 2 | 0 |
| PointingDeviceSensor | 4 | 0 | 4 |
| EnvironmentalSensor | 3 | 0 | 2 |
| Sound | 21 | 1 | 1 |
| NURBS | 13 | 3 | 0 |
| Time, Networking, Geometry2D | 13 | 3 | 1 |
| Core | 8 | 0 | 1 |
| 19 other components | 125 | 0 | 0 |
| All 37 (X3D 4.1) | 267 | 41 | 16 |

## 2. The upstream source: X3DUOM

The X3D Unified Object Model is an XML file Web3D publishes per X3D version
(`https://www.web3d.org/specifications/X3dUnifiedObjectModel-4.1.xml`, and
3.0 to 4.0 alongside it). It is generated from the X3D XML Schema and is what
Web3D's own Java (X3DJSAIL) and Python (`x3d.py`) libraries are generated
from. The 4.1 file is 2.6 MB and contains (4.0's counts in brackets):

| Section | Entries | Content used here |
|---|---:|---|
| `ConcreteNodes` | 267 (260) | name, inheritance, component and level, default `containerField`, every field |
| `AbstractNodeTypes` | 73 (72) | the `X3D*Node` interface hierarchy with the fields each contributes |
| `AbstractObjectTypes` | 7 (6) | `X3DBoundedObject`, `X3DUrlObject`, `X3DMetadataObject`, … |
| `FieldTypes` | 44 (42) | each `SF*`/`MF*` type, default value, tuple size, lexical regex |
| `Statements` | 17 (17) | `ROUTE`, `IS`, `connect`, `ProtoDeclare`, `field`, `fieldValue`, `IMPORT`, `EXPORT`, `meta`, `unit`, `component`, … and their attributes |
| `SimpleTypeEnumerations` | 90 (88) | profile names, component names, unit categories, enumerated string fields (`alphaMode`, `NavigationInfo.type`, …) |

A field entry carries name, type, `accessType` (`initializeOnly`,
`inputOutput`, `inputOnly`, `outputOnly`), default, `minInclusive`/
`maxInclusive`/`minExclusive`, `acceptableNodeTypes`, `inheritedFrom`, the
enumeration it draws from, and a specification URL. Example (abridged):

```xml
<ConcreteNode name="PhysicalMaterial">
  <InterfaceDefinition specificationUrl="…/shape.html#PhysicalMaterial">
    <componentInfo name="Shape" level="2"/>
    <Inheritance baseType="X3DOneSidedMaterialNode"/>
    <field name="baseColor" type="SFColor" accessType="inputOutput"
           default="1 1 1" minInclusive="0" maxInclusive="1"/>
    <field name="baseTexture" type="SFNode" accessType="inputOutput"
           default="NULL" acceptableNodeTypes="X3DSingleTextureNode"/>
    <field name="metallic" type="SFFloat" accessType="inputOutput"
           default="1" minInclusive="0" maxInclusive="1"/>
    …
    <containerField default="material" …/>
  </InterfaceDefinition>
</ConcreteNode>
```

It does not record which fields are angles, lengths, masses or forces (needed
for the `UNIT` statement, §9.9), nor which components and levels make up each
profile. Both are short tables in the specification, transcribed as facts
(§10).

Driving the vocabulary from X3DUOM means that a new X3D version is a new
X3DUOM file, a regeneration, and a reviewed diff. It is also how two defects in
the hand-written VRML97 declarations surfaced during the spike (§5).

## 3. Approaches considered

### A. Use the `x3d` package (x3d.py) as the object model

x3d.py is Web3D's Python X3D library, one class per node, generated from
X3DUOM by XSLT. Its purpose is authoring and serialising: build a scene in
Python, write it as XML, ClassicVRML, VRML97, JSON or HTML. Version 4.0.65.7
is a single 6.7 MB module of 114,463 lines under the BSD-style Web3D Consortium
Open-Source License, with `xmlschema` as its one dependency.

Advantages:
- Maintained by Web3D, tracks the specification closely, already exists.
- Complete vocabulary with field validation.

Drawbacks:
- It is a parallel object model. Nothing in it is a pyvrml97 node, so it has
  no `vrml.cache` invalidation, no `ROUTE`/`IS` runtime, no PyDispatcher
  events, no `PrototypedNode`; OpenGLContext would need a second tree built
  from it, and every edit at run time would have to be mirrored. Using it only
  as a parser front end means building every scene twice.
- Each property setter runs an `assertValid*` check in Python and stores the
  tuple or list it was given; pyvrml97 coerces multi-valued fields to NumPy
  arrays, which is what the renderer uploads. A 4.6 MB CAD model's coordinates
  would pass through per-element Python validation before reaching NumPy.
- It writes and does not read. Its only XML parsing re-reads its own output to
  validate it against the X3D schema. The parsers would still have to be
  written.
- A 6.7 MB module is a large import for a run-time dependency.

Summary: right for its purpose, which is authoring X3D from Python; the wrong
shape for an engine's run-time scenegraph. Interoperability with it comes free
through files: anything x3d.py writes, the readers here read.

### B. Hand-written X3D declarations in pyvrml97, plus new XML/binary parsers

Extend `vrml/vrml97/basenodes.py` style by hand to 267 nodes, and write the XML
and binary readers.

Advantages:
- No generator, no new data file in the repository.
- Each class can be hand-tuned.

Drawbacks:
- 1,576 field declarations to transcribe and keep current, with the abstract
  types written out (2,741 if each node lists its fields flat, as
  `basenodes.py` does). The 54 hand-written VRML97 declarations contain two
  default-value errors against the VRML97 specification (§5); at five times the
  size, more will appear.
- Every X3D revision becomes a manual diff of the specification.
- Abstract types, `containerField` defaults, content-model constraints and
  ranges would each be transcribed too, or omitted.

Summary: viable, but trades a one-time generator for permanent transcription
work and a known error rate.

### C. Generated declarations from X3DUOM, one builder for all encodings (chosen)

Generate pyvrml97 node classes from the X3DUOM, downloaded at a pinned
revision, at development time; check them in with typed stubs, and put every
encoding in front of one builder.

Advantages:
- Single upstream source, the same one Web3D's own libraries use. New versions
  are regenerations.
- The nodes are ordinary pyvrml97 nodes: caches, routes, prototypes and the
  OpenGLContext render passes work on them unchanged. The spike rendered an
  X3D 4 `PhysicalMaterial` scene through the existing PBR pass (§5).
- Metadata that hand-written classes would drop (abstract types, content
  model, ranges, `containerField`, enumerations, component levels) is present
  and usable for validation, profile checks and the writers.
- One builder means `DEF`/`USE`, `PROTO`, `IS`, `ROUTE`, units and
  `IMPORT`/`EXPORT` are implemented once. VRML97 parsing moves onto it too.

Drawbacks:
- A generator to write and maintain, and a generated module (~10k lines) in
  the repository.
- The X3DUOM is not perfect: some descriptions are placeholders ("TODO
  elaborate"), 4.1 is still developmental, the 4.0 file types four fields with
  an XML Schema type (§9.3), and a few X3D type names (`MFQuaternion`
  in 4.1) need a pyvrml97 type before generation succeeds. The generator has
  to fail loudly on anything it does not map.
- The X3DUOM file is not redistributed (§10): the generator downloads it, so
  regenerating needs the network and Web3D's repository to be reachable.

Summary: the most code up front and the least to maintain afterwards. The
declarations are regenerated from the specification's own data rather than
transcribed, and the run-time model stays pyvrml97's.

### D. Generate the classes at import time from a shipped X3DUOM

Variant of C: ship the XML and build classes when `vrml.x3d` is imported. The
spike does this in 50 ms.

Advantages: no generated code in the repository.

Drawbacks: classes that exist only at run time are invisible to mypy, IDEs and
`help()`, and there is nowhere to put typed constructor signatures. Import cost
and a 2.6 MB data file in every installation.

Summary: rejected in favour of C's checked-in module, which costs nothing at
import and is readable.

### E. Convert X3D to VRML97 or glTF before loading

Run Web3D's `X3dToVrml97.xslt` or an X3D-to-glTF converter, then load with the
existing readers.

Advantages: no new reader.

Drawbacks: XSLT 2.0 needs a Java processor (Saxon). X3D-only nodes have no
VRML97 equivalent and are dropped; glTF has no events, sensors or prototypes.
A lossy pipeline in front of an engine whose goal is correctness.

Summary: rejected.

### F. Embed an existing X3D runtime

FreeWRL (C), X_ITE (JavaScript), Castle Game Engine (Pascal), X3DOM
(JavaScript).

Drawbacks: none is Python or uses this engine's renderer, and most are
copyleft (§10), which rules out reading their source, let alone linking them as
a requirement.

Summary: rejected.

### Comparison

| | A x3d.py | B hand-written | C generated (chosen) | D import-time | E convert | F embed |
|---|---|---|---|---|---|---|
| Runtime model is pyvrml97 | no | yes | yes | yes | yes | no |
| Follows the specification automatically | yes | no | yes | yes | n/a | n/a |
| Static types / IDE help | partial | yes | yes (stubs) | no | n/a | n/a |
| New readers to write | all | all | all | all | none | none |
| Lossless for X3D-only content | yes | yes | yes | yes | no | yes |
| Ongoing maintenance | low | high | low | low | low | n/a |
| Licence | BSD-style | n/a | X3DUOM terms (§10) | same as C | tool licences | mostly copyleft |

### The second decision: one vocabulary, or one per version

Within approach C there are two ways to treat VRML97, X3D 3.x, 4.0 and 4.1.

C1, one vocabulary with dialects (chosen). The run-time classes are the
X3D 4.1 declarations. A document's version is a property of the document: the
reader applies that version's differences (renamed fields, changed defaults)
as it builds, and the writer applies the target version's on the way out. The
differences are small and enumerable (§9.3): between VRML97 and X3D 4.0, three
renamed fields and three defaults; between X3D 3.3 and 4.0, thirteen renamed
fields, nine defaults and a set of fields that became `inputOutput`; between 4.0 and 4.1, nothing changed
and seven nodes were added.

- OpenGLContext implements each node once. `isinstance(node, x3d.Transform)` is
  true whatever file the node came from.
- A VRML97 scene can be written out as X3D, and an X3D 3.3 scene as 4.0, with
  no conversion step.
- Cost: old field names (`LOD.level`, `Switch.choice`, `Collision.collide`)
  become aliases, and a VRML97 node whose default differs carries an explicit
  value rather than an unset field (§9.3).

C2, a vocabulary per version. Four sets of classes; OpenGLContext binds its
implementation to each.

- Each class has exactly its version's defaults and field names.
- Cost: four classes per node name, implementation mixins bound by a registry
  rather than written as subclasses, `isinstance` checks against abstract
  types only, and a scene cannot move between versions without conversion.
  Every one of these is a cost paid by every user of the engine to model a
  difference that amounts to a dozen values.

C1 is the chosen design.

## 4. The design in five diagrams

### 4.1 Layers

```text
        X3DUOM 4.1 (downloaded at a pinned revision)   VRML97 / X3D 3.x deltas
                         │ tools/generate_x3d.py            │ (facts from the specs)
                         ▼                                  ▼
 pyvrml97   ┌─────────────────────────────────────────────────────────────────┐
 (no GL)    │ vrml.x3d.nodes        one class per node, abstract types as the │
            │                       marker hierarchy, typed stubs (.pyi)      │
            │ vrml.x3d.dialects     Dialect nodes: VRML97, X3D 3.x, 4.0, 4.1  │
            ├─────────────────────────────────────────────────────────────────┤
            │ readers   .x3d .x3dz │ .x3dv .x3dvz .wrl │ .json │ .x3db        │
            │              expat   │   simpleparse     │ json  │ fast infoset │
            │                  └──────────┬────────────┴───────┘              │
            │                       SceneBuilder ─────────► X3DScene          │
            │ writers   X3DScene ─► XML │ ClassicVRML/VRML97 │ JSON           │
            ├─────────────────────────────────────────────────────────────────┤
            │ vrml.x3d.runtime      event cascade, TimeSensor, interpolators, │
            │                       sequencers, triggers, followers, sensors' │
            │                       logic, bindable stacks — all given inputs │
            └─────────────────────────────────────────────────────────────────┘
 OpenGLContext
            ┌─────────────────────────────────────────────────────────────────┐
            │ scenegraph   implementations subclass the declarations          │
            │ loaders      X3D adapters on SceneLoader; Inline on SceneLoader │
            │ compile      geometry → Primitive → GeometryArrays (cached)     │
            │              PhysicalMaterial (glTF's material too) → PBR pass  │
            │ frame        clock, picks, viewer pose → runtime → render pass  │
            └─────────────────────────────────────────────────────────────────┘
```

Everything above the OpenGLContext line is usable without OpenGL: a validator,
a converter, a test, or another renderer can load, edit, animate and write X3D
with pyvrml97 alone.

### 4.2 One vocabulary, dialects at the document boundary

```text
  file says            reader applies                 run-time node            writer applies
  ─────────            ──────────────                 ─────────────            ──────────────
  #VRML V2.0 utf8  ─►  VRML97 dialect:            ─►  x3d.LOD             ─►   target dialect:
  LOD { level [..] }     level   → children            children [...]         children → level (VRML97)
                         SpotLight beamWidth π/2       x3d.SpotLight           omit fields equal to
  <X3D version=3.3>      X3D 3.3 dialect:              beamWidth = π/2         the target's default;
  <SpotLight/>     ─►    beamWidth π/4 explicit   ─►   (explicit)          ─►  refuse nodes the
  <X3D version=4.0>      none (4.0 = 4.1 defaults)                             target lacks
```

### 4.3 Four encodings, one builder

```text
   XML (expat)          ClassicVRML / VRML97     JSON (json)          Fast Infoset (.x3db)
   <Transform DEF=T     DEF T Transform {        {"Transform":        binary infoset events,
    translation='0 1 0'>  translation 0 1 0       {"@DEF":"T",         numeric arrays from
                          children [ ... ] }       "@translation":     encoding algorithms
                                                    [0,1,0], ...}}
        │ text values          │ token values         │ typed values         │ typed + text
        └──────────────┬───────┴──────────────┬───────┴──────────┬───────────┘
                       ▼                      ▼                  ▼
       SceneBuilder:  document(profile, version) · component · unit · meta
                      start_node(type, DEF, USE, containerField) · field(name, value)
                      end_node() · route(...) · import_(...) · export(...)
                      proto_declare / proto_field / proto_body / extern_proto
                      proto_instance / field_value / is_(nodeField, protoField)
                       │
                       ├─ resolves types against the scene's prototype namespace
                       ├─ applies the document's Dialect node and UNIT factors
                       ├─ decodes text with the field type's codec (XML, ClassicVRML)
                       └─ builds pyvrml97 nodes, sets each field once, roots the graph once
```

### 4.4 Declaration plus implementation, onto the PBR pass

```text
  vrml.x3d.nodes (generated, no GL)              OpenGLContext.scenegraph (implementation)
  ─────────────────────────────────              ─────────────────────────────────────────
  X3DNode ─► X3DChildNode ─► X3DShapeNode ─► Shape      ◄──  class Shape(ShapeRendering, x3d.Shape)
                 nodetypes.Rendering ┘                         Render(), boundingVolume(), sortKey()
  X3DNode ─► X3DGeometryNode ─► X3DComposedGeometryNode
                 ─► IndexedTriangleSet                   ◄──  primitive()  (pure NumPy, cached)
  X3DNode ─► X3DAppearanceChildNode ─► X3DMaterialNode
                 ─► X3DOneSidedMaterialNode ─► PhysicalMaterial  ◄── class PhysicalMaterial(
                                                                       x3d.PhysicalMaterial)
                                                                    + glTF extension fields
                                                    │                 (the engine's PBR material)
        Shape.Render ─► pbr_material(appearance) ─► PBRShaderProgram uniforms, texture fields
                     ─► geometry.primitive()      ─► GeometryArrays (VBO/VAO) in mode.cache
```

The declaration carries fields and X3D type; the implementation carries
behaviour. OpenGLContext's subclasses keep that split today against
`vrml.vrml97.basenodes`; they move to `vrml.x3d.nodes`.

### 4.5 One frame

```text
  context clock (seconds) ───────────────┐
  pointer ray / picks ───────────────────┤
  viewer pose, frustum ──────────────────┤
                                          ▼
  vrml.x3d.runtime.EventCascade.step(timestamp, inputs)
     1. time-dependent nodes emit (TimeSensor fraction_changed, cycleTime, isActive)
     2. sensors emit from inputs (TouchSensor, PlaneSensor, ProximitySensor, KeySensor …)
     3. events propagate along ROUTEs: each route fires at most once per timestamp,
        interpolators / sequencers / triggers / followers run as they receive
        (a Script node receives nothing: its fields hold their values, its code never runs)
     4. bindable stacks settle (Viewpoint, NavigationInfo, Background, Fog)
                                          │ field sets → vrml.cache invalidations
                                          ▼
  render pass (unchanged): observe scene, walk paths, draw
```

## 5. Spike results

The spike lives in the session scratchpad only. It is four short modules: an
X3DUOM-to-class generator, an expat XML reader and a JSON reader feeding one
builder, a patched copy of the ClassicVRML grammar, and an OpenGLContext script
that renders the result. The corpus is Web3D's ConformanceNist and
Vrml2Sourcebook example archives: 1,181 scenes, each published in all five
encodings (`.x3d`, `.x3dv`, `.json`, `.x3db`, `.wrl`).

| Claim tested | Result |
|---|---|
| X3DUOM can generate pyvrml97 classes | From 4.0, 338 classes (260 concrete, 78 abstract) in 50 ms, fields typed with pyvrml97 field types, inheritance per X3DUOM. Six X3D field types needed stand-ins (§9.1). |
| X3D is a near-superset of the pyvrml97 VRML97 declarations | Every VRML97 node exists in X3D 4.0. Renamed: `Collision.collide`→`enabled`, `LOD.level`→`children`, `Switch.choice`→`children`. Default changes: `SpotLight.beamWidth`/`cutOffAngle`, `NavigationInfo.type`. Several `field`s became `inputOutput`. |
| The comparison finds defects | pyvrml97's VRML97 `ElevationGrid.xSpacing`/`zSpacing` default to 0.0; the VRML97 specification says 1.0. `NavigationInfo.type` defaults to `["WALK"]`; the specification says `["WALK", "ANY"]`. |
| An expat reader can build the graph | 1,028 of 1,181 `.x3d` files built with no warnings; the 153 others use `Script` field declarations or prototypes, which the spike did not implement. 19 MB/s over the corpus (57.7 MB). The largest file, 4.6 MB of CAD geometry, builds in 0.14 s. |
| XML and VRML97 encodings give the same graph | 601 of 618 comparable ConformanceNist scenes structurally identical between the `.x3d` read and the existing VRML97 parser's `.wrl` read. The 17 others are the LOD/Switch renames the comparison did not normalise and six interpolator tests. |
| XML is faster than the current VRML97 path | 5.5 MB/s (XML spike) against 2.1 MB/s (existing SimpleParse VRML97 parser) building the same 618 scenes. |
| JSON feeds the same builder | 1,027 scenes; graphs identical to the XML reader's in every case. |
| ClassicVRML is VRML97's grammar plus a header | The existing `vrml200x` grammar parses 0 of 1,181; with the header fixed, lower-case `true`/`false` accepted, `UNIT`/`IMPORT`/`EXPORT` added and four field types mapped, 1,052 parse through the unchanged VRML97 `ParseProcessor`. Most of the remainder are `Script` nodes. |
| The renderer needs no new pass | An X3D 4.0 file with three `PhysicalMaterial`s, a 3.x `Material`, a `DirectionalLight`, a `PointLight`, and a `TimeSensor`→`OrientationInterpolator`→`Transform` route chain rendered through the existing PBR pass, with OpenGLContext's implementation classes bound onto the generated declarations and `PhysicalMaterial` mapped onto `PBRMaterial` (their factor fields share names). |
| Implementation and declaration hierarchies compose | 52 implementations bound; 6 (`AudioClip`, `Fog`, `MovieTexture`, `ProximitySensor`, `TimeSensor`, `VisibilitySensor`) failed with MRO conflicts because the implementation classes repeat pyvrml97's marker classes in an order that disagrees with X3D's hierarchy. §9.1 resolves this. |
| `.x3db` is Fast Infoset | Files begin `E0 00 00 01` and name the vocabulary `urn:web3d:x3d:fi-vocabulary-3.2`. |

Two pyvrml97 costs showed up in profiling, both independent of X3D:

- Attaching a subtree re-walks it to pass the scene root down, including
  subtrees already rooted in the same scene (`RootScenegraphNode._adopt`,
  `vrml/node.py:498`). Adding a `ROUTE` triggers the same walk from its source
  and destination. On `children500.x3d` (117 KB, 500 children, 8 routes) this
  is 0.43 s of a 0.53 s profiled build; the 8 routes alone are 0.34 s.
- Each `MFNode` append dispatches a PyDispatcher signal per child.

## 6. The API

Building a scene in code, with no OpenGL:

```python
from vrml.x3d import nodes as x3d

scene = x3d.X3DScene(profile='Interchange', version='4.0', children=[
    x3d.DirectionalLight(direction=(-0.5, -1, -0.6), intensity=2.5),
    x3d.Transform(DEF='Gold', translation=(-2.2, 0, 0), children=[
        x3d.Shape(
            appearance=x3d.Appearance(material=x3d.PhysicalMaterial(
                baseColor=(1.0, 0.766, 0.336), metallic=1.0, roughness=0.25,
            )),
            geometry=x3d.Sphere(radius=1.0),
        ),
    ]),
])
```

The stubs give every constructor its keyword arguments with types, so an IDE
completes `x3d.Transform(` with `translation`, `rotation`, `scale`, … and mypy
rejects `x3d.Shape(geometry=x3d.Appearance())` because `geometry` accepts an
`X3DGeometryNode`. At run time, a node field enforces the same content model
through pyvrml97's existing `SFNode.requiredTypes`.

Reading and writing, any encoding, any version:

```python
from vrml import x3d

scene = x3d.load('world.x3d')            # or .x3dv, .x3dz, .json, .x3db, .wrl
scene.profile, scene.version             # ('Immersive', '3.3')
scene.getDEF('Gold').translation         # array([-2.2, 0. , 0. ], dtype=float32)

x3d.dump(scene, 'world.json')                        # encoding from the suffix
x3d.dump(scene, 'world.wrl')                         # VRML97 dialect: renames back,
                                                     # refuses X3D-only nodes
text = x3d.dumps(scene, encoding='xml', version='4.0', canonical=True)

problems = x3d.validate(scene, profile='Interchange')   # ranges, content model,
                                                         # profile/component levels
```

In OpenGLContext, the context's scene loader takes the file, and
`OpenGLContext.scenegraph.basenodes` holds the same names, implemented:

```python
request = context.sceneLoader.load_now('world.x3d')   # or load() on a worker
scene = request.result                                  # an X3DScene
gold = scene.getDEF('Gold')
gold.rotation = (0, 1, 0, 1.2)                          # caches invalidate as today
```

Routing and behaviour are the X3D model, usable from Python:

```python
gold = scene.getDEF('Gold')
clock = x3d.TimeSensor(cycleInterval=4, loop=True)
spin = x3d.OrientationInterpolator(key=[0, .5, 1],
                                   keyValue=[(0, 1, 0, 0), (0, 1, 0, 3.14159), (0, 1, 0, 6.28318)])
scene.addRoute(clock, 'fraction_changed', spin, 'set_fraction')
scene.addRoute(spin, 'value_changed', gold, 'set_rotation')

cascade = x3d.runtime.EventCascade(scene)
cascade.step(timestamp=2.0)          # half a cycle; no window needed
gold.rotation                        # array([0., 1., 0., 3.14159], dtype=float32)
```

## 7. Efficiency

Loading. The readers do their tokenising in C (expat, `json`, mxTextTools) and
decode each numeric attribute with one `split` and one NumPy conversion, so
cost is per attribute, not per number. The spike's 19 MB/s across the corpus is
before the two pyvrml97 fixes in §9.1. After them the builder's cost is
linear in node count: each node is constructed once, each field set once with
`notify=0`, each `MFNode` set as a complete list at `end_node`, and the scene
root assigned to the whole tree in one walk at the end. A C decoder for numeric
text in `vrml_accelerate` (one `strtod` pass into a preallocated array) is the
remaining step for coordinate-heavy files and is worth doing when a profile
says so.

Rendering. X3D content renders through the same passes, caches and GPU paths
as VRML97 and glTF content, so static X3D scenes cost what the engine already
costs. Specifically:

- Every geometry node produces `opengl_extrusions.mesh.Primitive` values
  through a pure NumPy `primitives()` (§9.12), cached in a `CacheHolder` that depends on exactly
  the fields read. `IndexedTriangleSet`, `TriangleSet`, the strip and fan
  sets, `QuadSet`/`IndexedQuadSet` and `LineSet` map directly to index buffers
  with no tessellation. `IndexedFaceSet` keeps its existing compiler.
- `DEF`/`USE` of the same `Shape` under several transforms is instancing
  information the file states outright. The PBR pass's instanced path
  ([INSTANCED-GEOMETRY.md](INSTANCED-GEOMETRY.md)) can draw all uses of one
  `Shape` in one call; this is a pass change, not an X3D one, and benefits
  VRML97 content equally.
- Materials resolve to the PBR pass's existing shader variants. The per-channel
  texture transforms of §9.13 widen the material block, not the set of
  programs, and glTF's `KHR_texture_transform` needs them too.

Events. A cascade costs one Python call per event delivered, and nothing for
nodes not receiving events, so a static scene has no per-frame Python cost from
the event model. Typical X3D animation, one `TimeSensor` driving a handful of
interpolators, is a few dozen Python calls per frame. The case that needs
headroom is exported character or machine animation: hundreds of interpolators
fed by one `TimeSensor`'s `fraction_changed`. The runtime groups interpolators
by their source event and evaluates each group with one vectorised NumPy lookup
and interpolation per field type, then delivers the results. glTF's animation
player evaluates its channels one by one and could share the grouped
evaluator.

Memory. Multi-valued fields are NumPy arrays from the moment they are read;
there is no intermediate Python list per coordinate. Single-precision fields
are stored as `float32` and double-precision (`SFVec3d`, `MFDouble`, the
Geospatial component) as `float64`.

## 8. Feature coverage and what will not be implemented

Targets by component, in the order the phases (§13) reach them. "Engine" means
the component maps onto an existing OpenGLContext subsystem.

| Component | Target | Maps onto |
|---|---|---|
| Core, Grouping, Shape, Geometry3D, Rendering, Texturing, Lighting, Navigation, Time, Interpolation, Networking, EnvironmentalEffects, Text | Full: these make the Interchange and most of the Interactive profile | existing nodes, PBR pass, `SceneLoader`, `ImageBasedLight` |
| EventUtilities, Followers, KeyDeviceSensor | Full, pure Python | `vrml.x3d.runtime` |
| PointingDeviceSensor, EnvironmentalSensor, Picking | Full | engine picking ([RAYCAST-PICKING.md](RAYCAST-PICKING.md)), frustum, occlusion queries |
| Geometry2D, CADGeometry | Full | `opengl_extrusions` tessellation and `Primitive` |
| CubeMapTexturing, TextureProjection, Texturing3D | Full | cube-map probes, shadow-map projection path, 3D textures |
| Shaders | Full for GLSL; `PackagedShader` with non-GLSL languages not | engine `Shader*` nodes, X3D GLSL binding names |
| NURBS | Full | NURBS evaluator ([NURBS-EVALUATOR.md](NURBS-EVALUATOR.md)) |
| HAnim | Full (HAnim 2) | skinning and character animation |
| RigidBodyPhysics | Full | omi_physics |
| ParticleSystems | Full | engine particles |
| Layering, Layout | Full | overlay UI and multi-view rendering |
| Sound (classic `Sound`/`AudioClip`) | Full | omi_audio |
| Sound (4.0 audio graph) | Sources, gain, panning, filters, delay, analyser; see below | omi_audio |
| Geospatial | Full, later phase | double-precision paths, terrain |
| VolumeRendering | Full, later phase | 3D textures, ray-marching pass |
| GaussianSplats (4.1) | Later phase | a new sorted-splat pass |
| Scripting | Read, kept and written; never executed (§9.18) | |
| DIS | Not planned | |

Scripting level 1 is part of the Immersive profile, so the support table
(§9.9) reports Immersive as complete except for Scripting.

What will not work, and why:

- `Script` nodes in any language: ECMAScript, Java, or anything else a `url`
  names. Script support is not part of this plan (§9.18). A `Script` node is
  read with its declared fields, keeps the values its file gives them, can be
  routed to and from, and is written back out unchanged; its code never runs,
  so its output fields never change. Loading reports how many `Script` nodes a
  scene has, once per load.
- `MovieTexture` without a decoder. The specification requires MPEG-1
  (ISO/IEC 11172-1); content also uses MP4 and WebM. Decoding needs FFmpeg or similar,
  which cannot be a hard dependency (licence and size). An optional extra
  (PyAV, a BSD wrapper over a user-installed FFmpeg) supplies frames; without it
  the texture shows a placeholder and loading says so. `MovieTexture`'s audio
  goes to omi_audio when a decoder is present.
- `StreamAudioSource`, `StreamAudioDestination`. These are defined in terms of
  WebRTC media streams, which a desktop engine does not have.
  `MicrophoneSource` maps to device capture where `miniaudio` offers it.
- `Convolver`, `DynamicsCompressor`, `WaveShaper`, `PeriodicWave` are
  implementable in NumPy and are planned last within Sound; they are listed
  here because a first release of the audio graph will not have them.
- DIS (`EspduTransform`, `SignalPdu`, …). These exchange IEEE 1278 network
  packets for military simulation; nothing in an engine for games and
  applications calls for it. The nodes parse and are inert.
- `Anchor` to a non-X3D URL. The engine cannot render a web page; an
  `Anchor` to one calls an application-supplied handler, whose default opens
  the system browser.
- X3D in HTML (`.xhtml`, X3DOM/X_ITE page embedding). Not applicable to a
  native engine.

## 9. Detailed design

### 9.1 pyvrml97 groundwork

Fix the defects found, independent of X3D, with a failing test first in each
case:

- `ElevationGrid.xSpacing`/`zSpacing` default 1.0; `NavigationInfo.type`
  default `["WALK", "ANY"]` (both cited to the VRML97 specification). After
  §9.3 these become VRML97 dialect entries rather than class defaults, but the
  defect is fixed first so the change of mechanism is separately testable.
- `MFVec2d` on a double-precision base.
- Root adoption stops at a subtree already rooted in the same scene, and a
  `ROUTE` does not root its source and destination (they are already in the
  graph the route belongs to). Test: attaching a 1,000-node subtree and 100
  routes visits each node once.

Add the missing field types, each with coercion, `vrmlstr`, copy and equality
tests against the existing field-type test suite:

| Type | Storage |
|---|---|
| `SFDouble` | Python `float` |
| `MFDouble` | `float64` array |
| `SFColorRGBA` | `float32` array, 4 |
| `MFColorRGBA` | `float32` array, n×4 |
| `MFBool` | `bool` array |
| `MFImage` | list of `SFImage` |
| `SFQuaternion`, `MFQuaternion` | added if 4.1 keeps them when published (used by `GaussianSplats`) |

Access types. pyvrml97's `Field(exposure)` and `Event(direction)` already
express the four X3D access types; add an `accessType` property returning the
X3D name, so the generator, writers and validator speak X3D without a
translation table.

One marker hierarchy. pyvrml97's `vrml.vrml97.nodetypes` classes (`Children`,
`Grouping`, `Rendering`, `Geometry`, `Light`, `Bindable`, …) stay as fieldless
marker classes, because engine-only nodes (`ParticleEmitter`, `Zone`, …) use
them without being X3D nodes. The generated abstract types inherit the matching
marker (`X3DChildNode(nodetypes.Children)`, `X3DShapeNode(…,
nodetypes.Rendering)`, `X3DLightNode(…, nodetypes.Light)`, …), so every
generated node satisfies the engine's existing `isinstance` checks.
Implementation classes in OpenGLContext stop listing markers that their
declaration already provides; that removes the MRO conflicts the spike hit, and
`nodetypes.Sensor` is made a `Children` subclass to match X3D, where every
sensor is a child node.

### 9.2 The generator and the generated vocabulary

The X3DUOM is downloaded, not committed. The X3DUOM files on web3d.org are
regenerated in place (the 4.1 file's header reads "Generated 2026-09-27"), so
the generator fetches from Web3D's public Subversion repository at a fixed
revision, where the bytes cannot change:

```python
#: X3DUOM 4.1 as of Web3D's x3d repository revision 40303; the same bytes
#: www.web3d.org served on 2026-10-07.
X3DUOM_URL = ('https://sourceforge.net/p/x3d/code/40303/tree/'
              'www.web3d.org/specifications/X3dUnifiedObjectModel-4.1.xml?format=raw')
X3DUOM_SHA256 = 'e11beae36eadcfc5b165a6d0ddd87fe8f2b4288761f765d55de25521c0c902e4'
```

The download is cached in the user's cache directory and checked against the
digest on every run; a mismatch stops the generator. Moving to a newer X3DUOM
is a change to those two constants in a reviewed commit. The version-diff mode
(§9.3) fetches the 3.0–4.0 files the same way, each at a pinned revision.

`pyvrml97/tools/generate_x3d.py` reads it and writes:

- `vrml/x3d/nodes.py`: abstract types in dependency order, then concrete
  nodes, each with its fields as pyvrml97 field descriptors, `PROTO`,
  `COMPONENT = ('Grouping', 1)`, `CONTAINER_FIELD = 'children'`, and a
  docstring naming the node's component and level, with the specification URL
  X3DUOM gives for it. The X3DUOM's `appinfo` prose is not copied while its
  licence is unconfirmed (§10).
- `vrml/x3d/nodes.pyi`: keyword-only constructor signatures with value types
  (`SFVec3fLike = Sequence[float] | NDArray[float32]`, node fields typed by
  their `acceptableNodeTypes`).

The rest of the X3DUOM's field metadata lives on the field descriptors
themselves, so a node's class is the one place its interface is described:
pyvrml97's `Field` gains optional `minimum`/`maximum` (with inclusive or
exclusive bounds), `choices` (with whether other values are allowed) and
`accessType`, which the validator and the writers read from the field.

Rules:

- `SFNode`/`MFNode` fields get `requiredTypes` from `acceptableNodeTypes`
  (an abstract type, or a tuple of them; `X3DPrototypeInstance` is honoured
  as §9.7 describes).
- Field defaults are decoded from X3DUOM text with the same XML codec the
  reader uses (§9.5), so the generator exercises the codec on every default in
  the specification.
- XML-encoding attributes that are not fields (`DEF`, `USE`, `IS`, `class`,
  `id`, `style`, `containerField`) are not generated as fields; `DEF` is
  pyvrml97's existing `DEF`.
- Any X3DUOM type, attribute or inheritance the generator does not map is an
  error, not a skip. The spike skipped unknown types and lost four fields
  without a message (§9.3).
- Output is deterministic (sorted, no timestamps), formatted, and passes ruff
  and mypy.

The drift check regenerates into a temporary directory and compares
byte-for-byte with the checked-in module. It needs the download, so it is a
tox environment (`x3d-generated`) that pyvrml97 declares among its preflight
`checks` and its CI runs, not a test in the unit suite, which stays runnable
offline. Updating to a new X3DUOM is: change the revision and digest, run the
generator, review the diff, and update the dialect nodes (§9.3) from the
generator's version-diff report.

`vrml/vrml97/basenodes.py` becomes a compatibility module: it re-exports the
54 VRML97 names from `vrml.x3d.nodes` and keeps its import path, so code
written against it continues to work.

### 9.3 Dialects

A dialect is a pyvrml97 node, like the rest of the model, so it can be
inspected, copied, written out as VRML97 or X3D, and extended by an
application with its own:

```python
class Dialect(node.Node):
    """The differences between one X3D or VRML version and the vocabulary"""
    PROTO = 'Dialect'
    name = field.newField('name', 'SFString', 0, '')         # 'VRML97', 'X3D 3.3', …
    version = field.newField('version', 'SFString', 0, '')   # as a header writes it
    nodeTypes = field.newField('nodeTypes', 'MFString', 0, list)
    renamed = field.newField('renamed', 'MFNode', 0, list)   # FieldRename nodes
    defaults = field.newField('defaults', 'MFNode', 0, list) # FieldDefault nodes

class FieldRename(node.Node):
    PROTO = 'FieldRename'
    nodeType = field.newField('nodeType', 'SFString', 0, '')
    old = field.newField('old', 'SFString', 0, '')          # the name in this version
    current = field.newField('current', 'SFString', 0, '')  # the vocabulary's name

class FieldDefault(node.Node):
    PROTO = 'FieldDefault'
    nodeType = field.newField('nodeType', 'SFString', 0, '')
    fieldName = field.newField('fieldName', 'SFString', 0, '')
    value = field.newField('value', 'SFString', 0, '')      # XML encoding of the value
```

A `FieldDefault` stores the value as its X3D XML text and decodes it with the
named field's own codec, so one node type serves every field type.
`vrml.x3d.dialects` holds one `Dialect` instance per version, built by the
generator's version-diff mode and checked in as generated code beside
`nodes.py`.

The X3D 3.0–4.0 dialects come from the X3DUOM files for those versions: the
generator's version-diff mode lists changed defaults, changed access types,
added and removed nodes, and fields that disappeared from a node alongside a
new field of the same type, as rename candidates. Defaults and node sets are
taken as generated; renames are confirmed by hand against the specification,
because a removed field and an added one of the same type are not always the
same field. The VRML97 dialect is short and written by hand, citing VRML97
clauses. Measured deltas:

| From | Renamed fields | Different defaults |
|---|---|---|
| VRML97 → 4.1 | `Collision.collide`→`enabled`; `LOD.level`→`children`; `Switch.choice`→`children` | `SpotLight.beamWidth` (π/2 → 3π/16), `SpotLight.cutOffAngle` (π/4 → π/2), `NavigationInfo.type` (`["WALK", "ANY"]` → `["EXAMINE", "ANY"]`) |
| 3.3 → 4.0 | `ComposedCubeMapTexture.back`, `bottom`, `front`, `left`, `right`, `top` → `backTexture`, …; `ParticleSystem.colorRamp`→`color`, `texCoordRamp`→`texCoord`; `Layer.isPickable` and `LayoutLayer.isPickable`→`pickable`; `LoadSensor.watchList`→`children`; `DISEntityManager.mapping`→`children` | `SpotLight.beamWidth` (π/4 → 3π/16); joint axes on four RigidBodyPhysics joints |
| 4.0 → 4.1 | none | none |

DirectionalLight's scoping and the global PointLight and SpotLight are not
dialect differences: X3D's `global` field defaults (false, true, true) state
VRML97's rules.

The 4.0 X3DUOM types the `name` field of the four vertex-attribute nodes as
`xs:NMTOKEN`, an XML Schema type, where every other field has an X3D field type
(the specification declares it `SFString`). The spike skipped fields of types
it did not recognise and so reported `name` as removed; the generator maps
`xs:NMTOKEN` to `SFString` explicitly and fails on any other type it does not
know.

Reading: after `end_node`, the builder sets, with `notify=0`, every field
whose document-dialect default differs from the current one and which the
document did not set. Writing to a target dialect: rename, omit a field whose
value equals the target's default, and raise `UnsupportedInDialect` for a node
the target lacks (with an option to drop it with a warning instead).

Old field names stay readable from Python through an `AliasField` descriptor in
pyvrml97 (`lod.level` reads and writes `lod.children`), documented as the
VRML97 name, not as a separate field, and not reported by `getFields`.

### 9.4 The scene builder

`vrml.x3d.builder.SceneBuilder` implements the protocol in diagram 4.3. It
owns:

- the prototype namespace stack (standard vocabulary at the bottom, then the
  document's and each `ProtoDeclare`'s);
- the `DEF` table per name scope (document, prototype body, Inline);
- node construction and the `containerField` rule: explicit attribute, else
  the node type's `CONTAINER_FIELD`, else the first node field of the parent
  that accepts the node's type (X3D rule for prototype instances);
- field values: `field(name, value)` takes a typed value (JSON, Fast Infoset
  encoding algorithms, ClassicVRML tokens) or `field_text(name, text)` for XML
  and Fast Infoset strings, decoded by that field type's XML codec;
- the `Dialect` node and the units of the document;
- collected `MFNode` children, set once at `end_node`;
- pending `ROUTE`s and `IMPORT`s that name nodes not yet available (Inline
  content still loading), bound when they become available;
- problems: `LoadProblem` nodes (`severity`, `line`, `column`, `message`, and
  an `SFNode` naming the node concerned) collected on the scene's `problems`
  field rather than printed, with a strict mode that raises on the first
  error. `x3d.validate()` reports through the same node type.

The builder knows nothing about encodings; the readers know nothing about
nodes.

### 9.5 Readers

XML (`vrml.x3d.readers.xml`): expat with external entity and DTD loading
disabled (X3D files carry a `DOCTYPE` naming Web3D's DTD; it must never be
fetched). Elements map to builder calls; `<X3D>`, `<head>`, `<meta>`,
`<component>`, `<unit>`, `<Scene>` to document calls; statements per X3DUOM's
`Statements` section. `.x3dz` is gzip-wrapped; `loaders/base.py` already
detects gzip by magic number.

XML codec per field type (`vrml.x3d.codecs.xml`): `decode(text)` and
`encode(value)`. SF/MF numeric types: commas are whitespace; `true`/`false`;
`MFString` as space-separated double-quoted strings with `\"` and `\\` escapes,
and the single unquoted string that some content writes, accepted with a
warning.

ClassicVRML and VRML97 (`vrml.x3d.readers.classic`): one SimpleParse grammar
covering both, selected by header (`#VRML V2.0 utf8` or `#X3D Vn.n utf8`),
taken from the ClassicVRML specification's grammar annex (ISO/IEC 19776-2).
The `ParseProcessor` becomes a dispatch from productions to builder calls,
replacing its own `DEF`/`USE`/`PROTO`/`ROUTE` handling. `vrml.vrml97.parser`
stays as an import path onto the same machinery. VRML97 loading in
OpenGLContext therefore runs through the builder too, which is how VRML97
content gains `EXTERNPROTO` resolution and the dialect rules. The ClassicVRML
keyword table has only `initializeOnly`, `inputOutput`, `inputOnly` and
`outputOnly`, and its identifiers exclude `:`; files with an `#X3D` header that
use VRML97's `field`/`exposedField`/`eventIn`/`eventOut` are accepted with a
warning in lenient mode and rejected in strict mode.

The EXI-based "Efficient Binary Encoding" (ISO/IEC 19776-4, `.x3de`) is a
working draft with no published files, and is not planned until it is
approved.

JSON (`vrml.x3d.readers.json`): stdlib `json`, the X3D JSON encoding's
`@field`, `-containerField`, `#comment`, `#sourceCode` conventions. Values
arrive typed; numeric lists go straight to NumPy.

Fast Infoset (`vrml.x3d.readers.fastinfoset`): an ITU-T X.891 decoder
producing the same element/attribute event stream the XML reader produces,
plus the X3D encoding algorithms of ISO/IEC 19776-3 for numeric arrays
(decoded with `zlib` and `numpy.frombuffer`). The bit-level decoding is pure
Python; the arrays, which carry nearly all the bytes, are decoded in NumPy.
Its own phase, and lowest priority among the readers (§13), since `.x3db` is
the least-used encoding.

### 9.6 Writers

`vrml.x3d.writers.{xml,classic,json}` walk an `X3DScene` and write it in a
target dialect: header, `head` metadata, nodes with only the fields that
differ from the target's defaults, `containerField` only where it differs from
the node's default, `DEF`/`USE` from the node graph's shared references, routes,
prototypes, imports and exports. The XML writer has a canonical mode following
X3D Canonical Form (attribute order, quoting, number formatting) so written
files diff cleanly. The ClassicVRML writer extends `vrml.vrml97.linearise`
and replaces its VRML97-only path.

As built (pyvrml97 `b4ad359`):

- `vrml.x3d.writers` (`base.SceneWriter` and one subclass per encoding)
  rather than an extension of `vrml.vrml97.linearise`, which is kept for
  `Node.toString()` and existing callers.
- Each `Dialect` gained `absent` (`AbsentFields` nodes): the fields of its
  node types the version does not have. Generated from the X3DUOM for 3.0 to
  4.0; for VRML97, written by hand from the section 6 node clauses. A field
  the target lacks is written only if it has a non-default value, and then
  the write fails with `X3DWriteError` listing every such case, as for node
  types and (VRML97) field types.
- `DEF` names are kept; a node used twice or named by a route without one is
  given `Type`, `Type_2`, ...; a clash between two nodes' names is resolved
  the same way. The scene is not modified.
- Units: a version with `UNIT` (3.3+) writes the statements and divides
  values back into them; an earlier one writes base units.
- Program source: CDATA (XML), `#sourceCode` (JSON), the `sourceCode` field
  (ClassicVRML 4.0 and 4.1), else an inline entry first in `url` (VRML97 and
  X3D 3.x ClassicVRML; prefixed `ecmascript:` for a Script that has no
  scheme).
- Canonical form: attribute order and quoting always; `canonical=True` adds
  the DTD and schema attributes. Apostrophes in an MFString are written
  `&apos;` where 19776-3 4.2.3 says `&#8242;` (a different character).
  Numbers are written positionally below 1e16, because the schema's patterns
  for ranged types (colours) allow an exponent only on a mantissa in [0, 1].
- The XML writer puts a node's `metadata` child first and a Script's `field`
  declarations before its `IS`, as the schema and the readers need.

### 9.7 Prototypes

X3D's XML prototype statements (`ProtoDeclare`, `ProtoInterface`, `field`,
`ProtoBody`, `IS`/`connect`, `ProtoInstance`, `fieldValue`,
`ExternProtoDeclare`) are the same model as ClassicVRML's `PROTO`/`IS`, and map
onto pyvrml97's `node.prototype`, `setSceneGraph` and `ismaps`.

Additions:

- A prototype class inherits the abstract X3D type of the first node in its
  body (the X3D rule for where an instance may appear), so `requiredTypes`
  checks accept prototype instances in the right places and reject them
  elsewhere.
- `ExternProtoDeclare`/`EXTERNPROTO`: the URL list is resolved through the
  loader (`file.x3d#Name`, any encoding). Instances created before the
  declaration arrives have the interface fields and an empty body; when it
  arrives, each instance's body is instantiated and its `IS` wiring connected,
  and the scene's observers are notified as for any child change.
- `Script` nodes are kept, not run (§9.18). Their field declarations (XML
  `<field>` children, ClassicVRML field and event declarations) build a
  per-instance prototype, the mechanism pyvrml97's `script.Script` uses now,
  so routes to and from a `Script` bind and the declared values are readable.
  The `url` field and any inline source (XML `CDATA`, JSON `#sourceCode`) are
  kept verbatim for the writers.

### 9.8 Inline, IMPORT, EXPORT, LoadSensor

`Inline` loads through `SceneLoader` adapters rather than the older `Loader`
registry, so an Inline can name X3D, VRML97, glTF or OBJ content. X3D 4.0
defines Networking component level 4 as glTF support in `Inline` (`.gltf` and
`.glb`), which the engine's glTF reader already exceeds. The Networking clause
asks for Shape level 2 with Lighting level 4 in one place and level 3 in its
support table, and the Full profile caps Lighting at 3; the support table
(§9.9) reports Lighting 3 and cites the discrepancy. The inlined scene is its own `DEF`
scope. `EXPORT` in the inlined file publishes names; `IMPORT InlineDEF.name AS
local` in the parent resolves them when the Inline finishes loading and binds
any routes pending on them. The `load` field unloads and reloads; `LoadSensor`
watches the Inline's (or texture's, or sound's) load state through the same
completion callbacks `SceneLoader` already delivers on the render queue.

### 9.9 Profiles, components, units, validation

- `X3DScene` records profile, version, components with levels, units and
  `meta`, each as fields of the scene (`MFNode` lists of `ComponentInfo`,
  `UnitInfo` and `MetaInfo` nodes, mirroring the XML statements). The profile
  definitions (which components at which level each profile includes) are
  `Profile` nodes with `ComponentInfo` children in `vrml/x3d/profiles.py`,
  transcribed from the specification's profile clauses.
- `UNIT` statements scale fields of the angle, length, mass and force
  categories by the declared factor at read time, and the writer can write them
  back. Each field descriptor carries its `unitCategory`; the generator sets it
  from a list transcribed from the specification, since X3DUOM does not carry
  it.
- `x3d.validate(scene, profile=None)` reports: values outside X3DUOM ranges,
  enumeration values outside a closed enumeration, node types outside the
  declared profile and components, and nodes used beyond the component level
  declared. It is a separate pass, so construction stays fast.
- An engine support table: each OpenGLContext implementation class declares
  the component level it implements. `oglc-x3d-support` prints, and the docs
  build renders, the supported level of every component, generated from those
  declarations and the X3DUOM, so the documentation's claim and the code
  cannot disagree.

### 9.10 The event model

`vrml.x3d.runtime` holds the X3D execution model, renderer-independent:

- `EventCascade`: given a timestamp and the events generated this frame,
  delivers along routes so that each route fires at most once per timestamp,
  evaluates nodes as they receive events, and repeats until no events remain.
  Ordering within a cascade is deterministic (route declaration order), which
  X3D permits and tests need. pyvrml97's PyDispatcher-based `ROUTE` objects
  remain the representation of a route; the cascade replaces their immediate
  forwarding with queued delivery.
- Behaviour classes for the nodes whose semantics are pure functions of their
  inputs and time: `TimeSensor`, every interpolator (including the spline,
  2D, ease-in/ease-out and NURBS interpolators), sequencers, triggers,
  filters, the chaser and damper followers, `BooleanToggle`, `KeySensor`'s and
  `StringSensor`'s state machines, the drag sensors' geometry (given a ray),
  `ProximitySensor`/`TransformSensor` (given a pose), bindable stack rules.
- Interpolator batching as described in §7.

OpenGLContext's existing interpolator and `TimeSensor` implementations move
here; their GL-free logic is what moves, and the engine keeps only the timer
wiring that feeds the cascade.

### 9.11 OpenGLContext binding and loading

- Implementation classes subclass `vrml.x3d.nodes` declarations instead of
  `vrml.vrml97.basenodes`; the `plugins.Node` registry and
  `scenegraph/basenodes.py` namespace keep their names, now X3D names.
  `basenodes.pyi` is regenerated by the existing stub writer.
- Every X3D concrete node is registered. Nodes the engine does not yet
  implement resolve to the bare declaration and are reported once per type per
  load, so every standard X3D file parses.
- `plugins.Loader` and `plugins.Adapter` entries: `x3d` (`.x3d`, `.x3dz`,
  `model/x3d+xml`), `x3dv` (`.x3dv`, `.x3dvz`, `model/x3d+vrml` as the
  ClassicVRML specification writes it and `model/x3d-vrml` as registered), `x3dj`
  (`.x3dj`, and `.json` by content), `x3db` (`.x3db`,
  `model/x3d+fastinfoset`). X3D JSON files are written `.json`, with `.x3dj`
  proposed by Web3D as an alternative, so `formats._sniff` gains an X3D JSON
  test (a top-level `"X3D"` key) beside its 3D Tiles test.
- `viewer/adapters/scenegraph.SceneGraphAdapter` serves X3D as it serves
  VRML97: viewpoints lifted, `WorldInfo` and the `head` metadata shown as
  notices.

### 9.12 Geometry

One interface for every X3D geometry node, in the value type the engine
already uses for generated geometry:

```python
def primitives(self) -> Sequence[opengl_extrusions.mesh.Primitive]: ...
```

A `Primitive` holds `attributes` keyed by glTF semantic (`POSITION`, `NORMAL`,
`TANGENT`, `TEXCOORD_n`, `COLOR_0`, and underscore-prefixed names for the
generic attributes `FloatVertexAttribute` supplies), `indices`, and a glTF
primitive `mode`. `scenegraph/frommesh.py` already turns one into a `PBRMesh`
without copying, so X3D geometry, glTF meshes and `opengl_extrusions` output
reach the GPU by one path. `solid` stays a field of the geometry node, which
`PBRMesh` already has; `ccw="false"` is applied by reversing the winding as the
indices are built.

Each node's implementation is a pure function of its fields, in a module of
NumPy functions with no GL, cached in a `CacheHolder` that depends on those
fields and on its `Coordinate`, `Normal`, `Tangent`, `Color`/`ColorRGBA`,
`TextureCoordinate`/`MultiTextureCoordinate` and `FloatVertexAttribute`
children. A `MultiTextureCoordinate`'s entries become `TEXCOORD_0`,
`TEXCOORD_1`, …, in order, and their `mapping` labels name those sets for the
material (§9.13).

- `IndexedFaceSet`'s existing compiler becomes its `primitives()`.
- Triangle, strip, fan, quad and line sets index directly.
- `ElevationGrid` (now implemented), `Extrusion` and the Geometry2D nodes use
  `opengl_extrusions`.
- NURBS surfaces and curves use the NURBS evaluator.
- Normals are generated with the node's `creaseAngle` where it has one;
  tangents are generated when a normal texture is present and no `Tangent`
  node is.
- `CoordinateDouble` is rebased to a float32 local origin for rendering, with
  the offset folded into the model matrix.

### 9.13 Materials and textures

`PBRMaterial` has not been in a release, so it is reshaped rather than wrapped.
The engine has one physically based material node, and it is X3D's:

```python
class PhysicalMaterial(x3d.PhysicalMaterial):          # scenegraph/physicalmaterial.py
    """The engine's PBR material: X3D 4's fields, plus the glTF extensions"""
    clearcoat = field.newField('clearcoat', 'SFFloat', 1, 0.0)
    clearcoatTexture = field.newField('clearcoatTexture', 'SFNode', 1, node.NULL)
    clearcoatTextureMapping = field.newField('clearcoatTextureMapping', 'SFString', 1, '')
    ...
```

- Name. `PBRMaterial` becomes `PhysicalMaterial`, in OpenGLContext and in
  every caller in the workspace (the glTF loader and writer, `surfaces.py`,
  the tiles foliage, twig-bb, marble-demo, glisteel, the editors and their
  tests) in the same change. No alias is kept.
- Factors. `baseColor`, `metallic`, `roughness`, `emissiveColor`,
  `occlusionStrength`, `normalScale` and `transparency` already have X3D's
  names and come from the declaration. The KHR extension factors (clearcoat,
  sheen, specular, ior, transmission, volume, emissive strength, iridescence,
  anisotropy, dispersion, diffuse transmission) and the engine's own fields
  (lightmap, impostor views, baked light, reflector) are fields the subclass
  adds, named in X3D's style.
- Textures. The `TextureChannels` dictionary of `PBRTexture` holders is
  replaced by `SFNode` texture fields, each with a `…TextureMapping` field,
  following X3D's `baseTexture`/`baseTextureMapping` pattern for the core
  channels and the same pattern for each extension channel. A texture is an
  ordinary `X3DSingleTextureNode`: `ImageTexture` for a URL, and for an image
  that arrives as bytes (a glTF buffer view, a procedural map from
  `surfaces.py`) an engine texture node holding the decoded image, which the
  X3D writer writes as an `ImageTexture` with a `data:` URL or a sidecar file.
  The pass reads a per-material channel table built from the fields and cached
  in a `CacheHolder` that depends on them.
- Alpha and sidedness. X3D puts `alphaMode` and `alphaCutoff` on `Appearance`
  and sidedness on the geometry's `solid`, so `PhysicalMaterial` does not
  carry `alphaMode`, `alphaCutoff` or `doubleSided`. The glTF loader sets them
  where X3D does, sharing one `Appearance` among the primitives that share a
  glTF material.
- Unlit. `KHR_materials_unlit` loads as X3D's `UnlitMaterial` rather than as
  an `unlit` flag.
- Round trip. Writing a scene as X3D writes the standard fields as
  `PhysicalMaterial` attributes and the extension fields in a
  `MetadataSet name='OpenGLContext'` on the material's `metadata` field, which is where
  X3D carries data outside the specification. Reading restores them, so a
  glTF-loaded scene survives being written as X3D and read back.

`pbr_material(appearance)` (`scenegraph/pbrmaterial.py:522`) remains the one
place the PBR pass learns about a surface. A `PhysicalMaterial` is passed
through. The other X3D materials are converted into the same uniform block:

- `Material` (X3D 4.0, with its new texture fields): the existing VRML97
  up-conversion (`material_to_pbr`), plus `diffuseTexture`, `normalTexture`,
  `emissiveTexture`, `occlusionTexture`.
- `UnlitMaterial`: the existing unlit path.
- `TwoSidedMaterial`, and `Appearance.backMaterial`: the pass binds one
  material per draw and uses `gl_FrontFacing` only to flip the normal. A back
  material is a second material block, chosen per fragment by
  `gl_FrontFacing`.
- `Appearance.alphaMode`/`alphaCutoff`: the existing glTF alpha modes, read
  from the appearance.

Texture mapping. A `…TextureMapping` label names a texture coordinate set
and a transform. Every geometry names its sets: X3D geometry by the `mapping`
fields of its `MultiTextureCoordinate` entries, `PBRMesh` by the labels its
loader gives it (the glTF loader uses `TEXCOORD_0`, `TEXCOORD_1`). An empty
label is the first set, as X3D specifies. The transform is the
`MultiTextureTransform` entry with the same label. glTF's
`KHR_texture_transform` attaches a transform to each texture reference, so the
glTF loader makes one label per distinct (set, transform) pair, and `PBRMesh`
maps several labels to one set rather than copying its coordinates. The PBR
shader selects the coordinate set per channel (`TEXCOORD_0` or `TEXCOORD_1`,
`uvFor` in `shaders/pbr.frag`) and has one `uvTransform` matrix per material,
switched on or off per channel; a glTF material whose base colour and normal
maps carry different transforms renders one of them wrongly today. The
material block gains a 3×3 transform per channel and the set selection widens
beyond two, and `texCoordMask` and `uv_transform` are replaced by the
labels.

Implementation detail (2026-10-07, before Phase 5 starts):

- `scenegraph/physicalmaterial.py`: `PhysicalMaterial(x3d.PhysicalMaterial)`.
  The X3D texture fields hold the core channels (`baseTexture`,
  `metallicRoughnessTexture`, `normalTexture`, `occlusionTexture`,
  `emissiveTexture`); the extension and engine channels are SFNode fields of
  the same pattern (`clearcoatTexture`, ..., `lightmapTexture`), each with its
  `…TextureMapping`. `textures` stays as a read-only view, channel name to
  texture node, built from the fields, for the pass and the instancing key.
  `texCoordMask`, `uv_transform`, `unlit`, `alphaMode`, `alphaCutoff` and
  `doubleSided` leave the material.
- Decoded images: `ImageDataTexture(x3d.X3DTexture2DNode)` holds a PIL image
  as an attribute, with `repeatS`/`repeatT` and a `TextureProperties` for the
  glTF sampler's filters and wrap modes. It replaces `PBRTexture`.
- Coordinate sets: a geometry answers `textureCoordinateSet(label)`. X3D
  geometry by the position of the `MultiTextureCoordinate` entry with that
  `mapping`; `PBRMesh` by its `textureMappings` (labels) and
  `textureMappingSets` (the set each names), and otherwise `""` is set 0 and
  `TEXCOORD_n` is set n. The shader keeps two sets (`TEXCOORD_0`/`_1`); a
  label naming a third is reported once and read as set 0.
- Transforms: the appearance's `textureTransform` (a `MultiTextureTransform`
  or a single transform) gives each label its transform; a single transform
  with an empty `mapping` applies to every channel, as in VRML97. glTF's
  `KHR_texture_transform` (scale, then rotation, then translation) is not
  X3D `TextureTransform`'s order, so the glTF loader writes
  `TextureTransformMatrix3D` entries.
- Material block: the one `uvTransform` mat3 becomes four affine transforms
  (two vec4 rows each) and three words of per-channel codes, five bits a
  channel (two for the set, three for the transform slot, 0 for none); 80
  words, so `MAX_INSTANCE_MATERIALS` becomes 51. A material whose channels
  use more than four distinct transforms is reported and the rest read as
  untransformed.

As landed: the codes and transforms are per-draw uniforms
(`channelCodes[4]`, `uvTransformRows[8]`), not material-block words. The
transforms belong to the appearance and the coordinate sets to the geometry,
so two shapes sharing a material can read it differently; in the block they
would have split the instancing material table on state that is not the
material's. `scenegraph/texturemapping.py` computes a `TextureMapping` per
(appearance, geometry), kept in a `vrml.cache` holder on the appearance that
depends on the material's, the appearance's and the transforms' fields; the
instancing key includes it, so members differing in a transform draw apart.
The block keeps its 224-byte layout: word 29 (`texCoordMask`) is
`materialFlags`, the `uvTransform` mat3 is reserved, and so is word 19
(`alphaCutoff`, now a uniform from the appearance). `PBRMesh` has no
`textureMappings` field; `coordinate_set` reads `TEXCOORD_n` labels and asks a
geometry with a `textureCoordinateSet(label)` method.

`ImageTexture`, `PixelTexture`, `ImageCubeMapTexture`, `ComposedCubeMapTexture`,
`ImageTexture3D` load through the existing texture cache; `TextureProperties`
maps to sampler state. `RenderedTexture` (4.1) and `GeneratedCubeMapTexture`
use the offscreen and probe rendering the engine already does for mirrors and
reflections.

### 9.14 Lights, shadows, environment

- Scope. X3D (and VRML97) `DirectionalLight` lights only its siblings and
  their descendants unless `global` is true; `PointLight` and `SpotLight`
  default to global with a `radius`. OpenGLContext's `DirectionalLight` lights
  the whole scene (`scenegraph/light.py:232` says so). The pass computes, per
  drawn path, the lights in scope (the light's parent group is an ancestor of
  the shape), and the shader takes a per-draw light mask. VRML97 specifies the
  same scoping, so this is a correctness fix for the existing format as well.
- Attenuation. X3D lights carry `attenuation` (constant, linear, quadratic)
  and `radius`; glTF punctual lights use inverse-square with `range`. Lights
  pass their attenuation model to the shader; X3D 4 specifies inverse-square
  for `PhysicalMaterial`, which is what the pass does now.
- `shadows`, `shadowIntensity` on lights and `castShadow` on `Shape` map onto
  the shadow subsystem's existing per-light and per-caster switches.
- `EnvironmentLight` (4.1) maps onto `ImageBasedLight`: `diffuseCoefficients`
  is the spherical-harmonic irradiance `ImageBasedLight` already takes,
  `specularTexture` the prefiltered cube map.
- `Background` and `TextureBackground` map onto the existing background nodes;
  `Fog`, `LocalFog` and `FogCoordinate` onto the fog support.
- Lighting rules (landed). `OpenGLContext.lighting` decides whether a scene
  is lit by X3D's rules (its own lights and headlight, X3D attenuation, no
  studio environment, no ambient fill, an `Appearance` with no material
  unlit) or the engine's. `ContextDefinition.lighting` / `OPENGLCONTEXT_LIGHTING`
  chooses `auto` (by whether the scene is a document), `x3d` or `engine`.
  Three separate document-versus-code checks (the material, the pass, the
  flat pass's ambient and headlight) read this one switch.

### 9.15 Bindable nodes and navigation

Bindable stacks (`Viewpoint`, `OrthoViewpoint`, `NavigationInfo`,
`Background`, `TextureBackground`, `Fog`) follow X3D's `set_bind`/`isBound`/
`bindTime` rules in `vrml.x3d.runtime`, extending `passes/viewpointbinding.py`.
`NavigationInfo.type` selects the engine's movement modes (EXAMINE, WALK, FLY,
LOOKAT, NONE; [MOVEMENT-MODES.md](MOVEMENT-MODES.md),
[EXAMINE-NAVIGATION.md](EXAMINE-NAVIGATION.md)); `headlight`, `speed`,
`avatarSize`, `visibilityLimit` and `transitionType` are applied. `ViewpointGroup`
adds a viewpoint menu entry hierarchy to the viewer.

- [ ] Open: a stack per `Layer` (7.2.2). pyvrml97's stacks are per scene, so
  a `LayerSet`'s layers share them; this waits on the engine drawing layers,
  and on a node knowing the layer it is in.

### 9.16 Sensors

- Pointing-device sensors (`TouchSensor`, `PlaneSensor`, `CylinderSensor`,
  `SphereSensor`) take the pick result the engine already produces
  ([RAYCAST-PICKING.md](RAYCAST-PICKING.md)); the sensor whose group contains
  the picked shape is activated per X3D's sensor-selection rule, and the
  dragging geometry is pure runtime code.
- `ProximitySensor`, `TransformSensor`: viewer or target pose against a box,
  per frame, pure runtime code.
- `VisibilitySensor`: frustum test, refined by the occlusion-query path where
  the context has it.
- `KeySensor`, `StringSensor`: fed from OpenGLContext's key events.
- Picking component (`LinePickSensor`, `PointPickSensor`,
  `PrimitivePickSensor`, `VolumePickSensor`): the engine's raycasting and
  physics overlap queries.
- `Collision` and `CollisionSensor`: the avatar collision the walk modes do,
  and omi_physics contacts respectively.

### 9.17 Components that map onto engine subsystems

| Component | Engine subsystem | Notes |
|---|---|---|
| HAnim | skinning, `JointPalette`, character animation | `HAnimHumanoid` builds the skin from `skinCoord`/`skinBindingCoords`; `HAnimMotion` (4.0) drives joints with BVH-style channel data; LOA levels from X3DUOM |
| RigidBodyPhysics | omi_physics | `RigidBodyCollection`, `RigidBody`, `CollidableShape`, the six joint types, `CollisionSensor` contacts |
| ParticleSystems | engine particles | emitters and physics models onto `ParticleEmitter` |
| NURBS | NURBS evaluator | the Blaxxun-era engine nodes become the X3D nodes |
| Shaders | `Shader*` nodes | `ComposedShader`/`ShaderPart`/`ShaderProgram`; X3D's GLSL binding names (`x3d_ModelViewMatrix`, …) bound by the pass |
| Sound | omi_audio | classic `Sound`/`AudioClip`; 4.0 audio graph nodes as an omi_audio processing graph |
| Layering, Layout | overlay UI, multi-view | `LayerSet` order onto overlay layers; `Viewport` onto multi-view; `Layout` onto UI layout |
| CubeMapTexturing | reflection probes | §9.13 |
| TextureProjection | projective texturing in the shadow-map path | |
| CADGeometry | grouping nodes and quad sets | `CADLayer.visible` per child |
| Geospatial | double-precision coordinates, terrain | `GeoOrigin` rebasing, `GeoElevationGrid` via terrain tiles |
| VolumeRendering | a ray-marching pass over 3D textures | later phase |
| GaussianSplats | a sorted-splat pass | later phase |

### 9.18 Scripting

Script execution is not part of this plan, in any language. The `Script`
node is part of the vocabulary so that every X3D file reads:

- Its declared fields exist on the node (§9.7), hold the values the file
  gives them, and can be routed to and from; routes into a `Script` deliver
  and are not acted on, and its output fields never change.
- Its `url` and inline source are kept verbatim, and every writer writes them
  back, so a file passes through load and save unchanged.
- The cascade has no hook for running code from a file, and nothing in
  pyvrml97 or OpenGLContext evaluates a `Script`'s source.
- Loading reports the number of `Script` nodes in a scene once, as a
  `LoadProblem` of warning severity, and the support table lists Scripting as
  not supported.

An application that wants behaviour attached to a `Script` node's interface
writes it in Python against the node's fields, as it would for any node, and
registers it from the application's own code; the file supplies no code.

- [ ] Next, once this plan and its review findings are done (asked
  2026-10-07): look at whether jsrun can run ECMAScript `Script` nodes --
  the sandbox it gives, the X3D ECMAScript binding (19777-1) it would need,
  how a script's events join the cascade, and what that does to the
  untrusted-content rules. A proposal, not an implementation, comes first.

## 10. Licensing and provenance

- X3DUOM. Neither the files nor their page
  (`https://www.web3d.org/specifications/X3DUOM.html`) state a licence. They
  are kept in Web3D's public `x3d` source repository, and the libraries Web3D
  generates from them (X3DJSAIL, x3d.py) are published under the Web3D
  Consortium Open-Source License, a BSD-3-clause-style licence, which the XML
  Schema and DTD beside the X3DUOM in `/specifications/` also cite
  (`https://www.web3d.org/specifications/license.txt`). Field names,
  types, defaults and ranges are facts of the specification and generate code
  under any licence; the `appinfo` descriptions are Web3D's prose. The X3DUOM
  is therefore downloaded at a pinned revision and checked by digest (§9.2),
  never committed, and docstrings carry the specification URL rather than the
  `appinfo` text. If Web3D (the X3DUOM page names Don Brutzman as contact)
  later confirms the Web3D Consortium Open-Source License covers the X3DUOM,
  the file can be vendored in `pyvrml97/specs/x3d/` with the licence text and
  the `appinfo` used in docstrings with attribution.
- x3d.py: Web3D Consortium Open-Source License (BSD-style), version 4.0.65.7.
  Not used.
- The Web3D example archives (the test corpus): Web3D Consortium Open-Source
  License (`https://www.web3d.org/x3d/content/examples/license.html`). The
  committed CI subset keeps the licence file beside it.
- Other implementations. FreeWRL (LGPL-3.0+), Castle Game Engine's core (LGPL
  with a static-linking exception), Titania (GPL-3.0), H3D (GPL-2.0+) and Xj3D
  (LGPL) are copyleft and are not read. X_ITE was relicensed from GPL-3.0 to MIT
  in 2025; only code released under MIT may be read, and an older checkout may
  not. X3DOM's `LICENSE.md` offers MIT or GPL-3.0 while its README says GPL-3.0+,
  so reading it waits on the maintainer's judgement of that discrepancy. CLEAN-ROOM.md
  applies to any behaviour question only a copyleft implementation could
  answer. The specification, the X3DUOM, the XML Schema and the conformance
  archive answer nearly every question this plan raises.

The specification documents (ISO/IEC 19775-1 architecture, 19776-1/-2/-3 XML,
ClassicVRML and compressed binary encodings, 19777-1 ECMAScript binding) are
published free of charge by Web3D. For X3D 4.0 only the architecture,
ISO/IEC 19775-1:2023, is an approved standard; the 4.0 editions of the
encodings and the scene access interface are drafts, and the 3.3 editions are
the approved references for the encodings. The JSON encoding is being prepared as
ISO/IEC 19776-5; until it is published, Web3D's X3D JSON design and the JSON
form of every example in the archives are the reference. Fast Infoset itself
is ITU-T X.891, also freely available. The facts transcribed from them (the
VRML97 dialect, the profile definitions, the unit categories) are cited to
clause numbers in the modules that hold them and in a fact sheet in
pyvrml97's `specs/x3d/`.

## 11. Testing

All in the existing pytest suites, using their fixtures; GL tests through
`gl_context`, scene captures through the existing capture and baseline
tooling.

- Generator: the byte-for-byte drift check (the `x3d-generated` preflight
  check, §9.2); a generated-class test per abstract type (fields, inheritance,
  markers) and a decode of every field default, both in the unit suite against
  the checked-in module.
- Materials: a glTF sample model and its X3D translation render the same
  capture; a glTF material written as X3D and read back has every extension
  field it had.
- Field types and codecs: round trip of every type through each encoding's
  codec, including the X3DUOM regexes as property-based inputs.
- Readers: the conformance corpus is the test set. For every scene published in
  several encodings, every encoding builds a structurally equal graph with
  equal field values; that one test checks four readers against one another
  across 1,181 scenes. The spike used ConformanceNist and Vrml2Sourcebook;
  Basic (745 scenes), HumanoidAnimation (472), Savage (1,233),
  X3dForWebAuthors (271) and X3dForAdvancedModeling (147) are published the
  same way under the same licence and join the corpus with the components they
  exercise. The corpus is fetched by a script into a cache directory (the two
  spike archives alone are ~550 MB packed), and a small committed subset
  covers CI.
- Writers: read → write → read is the identity for every corpus scene in every
  encoding and dialect it can be written in; written XML validates against the
  official XML Schema (a test-only dependency on a permissively licensed
  validator).
- Dialects: a VRML97 file and its X3D 4.0 translation give equal graphs after
  the dialect is applied; writing back to VRML97 restores the old names.
- Runtime: the cascade, every behaviour class and every sensor's logic tested
  in pyvrml97 with no GL, against the specification's stated outputs.
- Rendering: a reference capture per component as it lands (Interchange
  geometry, materials, lights with scope, textures with mapping labels), with
  the established baseline comparison. The conformance archive's own
  screenshots are another browser's output and are for eyeballing, not
  comparison.
- Performance: the builder's linearity test (§9.1), and a load-time budget on
  the largest corpus file.

## 12. Documentation

- New `openglcontext/docs/x3d.rst`: loading, encodings, versions and dialects,
  the supported-component table (generated, §9.9), what is not supported
  (script execution among it, §9.18).
- `docs/pbr.rst` and `docs/gltf.rst`: `PhysicalMaterial` in place of
  `PBRMaterial`, texture fields and mapping labels in place of the texture
  dictionary and `texCoordMask`.
- `docs/loading.rst`: format table gains the four X3D encodings.
- `docs/vrml97.rst`: VRML97 described as a dialect of the same vocabulary; the
  renamed-field aliases.
- `docs/viewer.rst`: archive suffixes.
- pyvrml97 `README.rst` and a pyvrml97 `docs/x3d` page: the vocabulary, the
  builder, readers and writers, the runtime, the generator and how to update
  the X3DUOM.
- `docs/documentation.rst` index, `docs/structure.rst` overview, and the
  directory map in `openglcontext/CLAUDE.md` for any new package.

## 13. Phases

Each phase ends with its tests green, preflight clean for every project it
touched, and its documentation updated.

1. pyvrml97 groundwork (§9.1): defects, field types, `accessType`, marker
   hierarchy, root-adoption fix.
2. Vocabulary (§9.2, §9.3): generator, generated module and stubs, dialects,
   `basenodes` compatibility, alias fields.
3. Builder and readers (§9.4, §9.5, §9.7, §9.9): XML, JSON, ClassicVRML with
   VRML97 moved onto the builder, prototypes including `EXTERNPROTO`, units,
   validation. Exit: the cross-encoding corpus test.
4. Writers (§9.6). Exit: round trip and schema validation.
5. `PhysicalMaterial` (§9.13): `PBRMaterial` renamed and rebased on
   `x3d.PhysicalMaterial`, extension and engine fields, texture fields and the
   engine texture node for decoded images, mapping labels, per-channel texture
   transforms in the shader, alpha and sidedness moved to `Appearance` and
   `solid`, `UnlitMaterial` for `KHR_materials_unlit`, and every caller in the
   workspace migrated. Exit: the glTF conformance captures match their
   baselines, including the sample models whose textures carry different
   transforms, and a glTF material survives an X3D round trip.
6. OpenGLContext Interchange (§9.11, §9.12, §9.14): rebased implementations,
   loader registration, `Inline` on `SceneLoader`, geometry as `Primitive`s,
   the other X3D materials, light scope and attenuation, environment.
   Exit: the Interchange profile renders; reference captures.
7. Runtime (§9.10, §9.15, §9.16): event cascade, behaviours, bindables,
   navigation, sensors. Exit: the Interactive profile, and the Immersive
   profile except its Scripting component.
8. Engine-mapped components (§9.17), in the order HAnim, RigidBodyPhysics,
   Sound, Shaders, CubeMapTexturing, ParticleSystems, Layering/Layout, NURBS,
   CAD, TextureProjection, Texturing3D.
9. Fast Infoset reader (§9.5).
10. Geospatial, VolumeRendering, GaussianSplats, `MovieTexture` add-on.

A showcase lands with phase 6 as an installed `oglc-*` command: an X3D 4
scene with `PhysicalMaterial` metals, stone and wood, lights with scope and
shadows, and an `Inline`d glTF model, then extended in phase 7 with sensors and
animation.

## 14. Decisions

Recorded 2026-10-07:

1. Approach C, generated from X3DUOM with one builder, and within it C1: one
   vocabulary, with VRML97 and older X3D versions as dialects applied at the
   document boundary.
2. Model records are nodes with fields, as everywhere else in the scenegraph,
   not dataclasses: `Dialect`, `FieldRename`, `FieldDefault`, `LoadProblem`,
   `Profile`, `ComponentInfo`, `UnitInfo` and `MetaInfo` are pyvrml97 nodes.
3. X3D lives in pyvrml97 as `vrml.x3d`.
4. The vocabulary is generated from X3DUOM 4.1. The seven nodes 4.1 adds are
   marked as 4.1 in the support table; the generator moves to the approved
   4.1 file when Web3D publishes it.
5. The X3DUOM is downloaded at a pinned revision and digest rather than
   committed (§9.2, §10).
6. `PBRMaterial` is reworked into the engine's `PhysicalMaterial`, without a
   compatibility alias; it has not been in a release (§9.13, phase 5).
7. No script support. `Script` nodes are read, kept and written, and never
   run (§9.18).

Review findings not taken as written, recorded 2026-10-07:

- The generated stubs keep `**fields` on each constructor, documented as the
  extension fields a dialect or a prototype adds.
- Bind stacks per `Layer` are an open item (§9.15); one stack per scene is
  what is implemented.
- pyvrml97 commit messages written before the commit-message rule are
  history and are not rewritten.
- The followers' "first use wakes the node" sub-finding is how 19775-1
  defines a follower, not a defect.
- The writers refuse a scene nested deeper than the interpreter's recursion
  limit with "nested too deeply"; the limit is documented rather than lifted.
- `scripts/x3d_xite_references.py --archive` takes any archive under
  `--corpus`, not only pyvrml97's list, so a test corpus can name its own.
- `loaders.x3d.prototypes()` and `vrml97_prototypes()` are built at each
  parse: 0.014 ms and 0.031 ms against 0.25 ms for the smallest document's
  parse, once per load. A memo would need invalidating on writes an
  application makes to the registries directly.
- `invalidate_material_ubo(None)` repacks every context's blocks. The packed
  block is kept per material in vrml's cache, the same for every context, so
  a counter per context would leave the other contexts' copies stale.
- The engine's callers of `Texture(image)` were checked against the row-order
  default: atlas pages hold `ImageTexture` images, bottom row first, and the
  font atlases are arrays, stored as they are.

Corpus renders that differ from X_ITE by more than 10%, looked at 2026-10-08:

- [x] `unlit_color`: a PointSet with more colours than points drew white;
  the first colours are used (X3D 11.4.11).
- [x] `greyscale_alpha_png`: a greyscale PNG whose transparency is a tRNS
  chunk drew opaque; `Texture.ensureRGB` gives such an image an alpha
  channel.
- [x] Sphere, Cylinder and Cone texture coordinates followed neither the seam
  at the back nor v upward; they are VRML97's now, and the top cap's image
  has its top toward -Z.
- Figure22_2 and other ground colours: X_ITE and Web3D's render draw the
  nadir colour solid up to the first `groundAngle`; VRML97 and X3D
  interpolate the colours between the angles, as drawn here.
- PixelTexture filtering: X_ITE magnifies a PixelTexture with no
  TextureProperties by nearest texel; the specification leaves the default
  filter to the browser, and the engine filters linearly.
- WALK documents: X_ITE drops a walking viewer to the floor at load, before
  the first frame; the engine's capture shows the viewer where the
  Viewpoint places it.
- [x] Text: a document's Text with no FontStyle is SERIF, SERIF and
  TYPEWRITER are found by name where the fonts' classes are wrong, and the
  lines are `size` x `spacing` apart.
- [x] Viewpoint framing, Figure20_17a: a Viewpoint under a rotated
  Transform turned with it (`NodePath.quaternion` from the path's matrix).
- [x] Figure20_17a's floor and the dungeons' ceilings: a light in a version
  without the `shadows` field kept the engine's default, so a VRML97 or X3D 3
  world was shadowed, and a torch's light was shadowed by the torch. A field
  the version lacks takes X3D's default now (pyvrml97 builder and VRML97
  parser), so those lights cast none.
- StopWatch and the other animated documents are captured at another time
  than X_ITE's; `children500` is a WALK view with nothing below it, which
  X_ITE lets fall before its capture.
- The dungeon rooms match apart from the shadows above; X_ITE's
  Figure25_12 viewer has fallen below the floor.
- [x] Instanced batches mixed shapes under different scoped lights and ORed
  their light masks, so a batch spanning two scopes was unlit
  (Figure20_12); records the scoped lights reach differently are batched
  apart (`build_instance_groups(apart=)`).
- X3D 3.0 has no `global` field, so its DirectionalLights are scoped as in
  VRML97. NIST's expected image for `DirectionalLight/test_on` has the
  sphere beside the switched-off light dark, as drawn here; X_ITE and
  Web3D's render light it, and light Figure20_12's two groups with both
  lights.
