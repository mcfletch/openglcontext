# Code review: the workspace since OpenGLContext 3.0.0a4 (2026-09-25)

This review covers everything written across the workspace since OpenGLContext's last release tag, `v3.0.0a4` (`a864ff7`, 2026-09-12 01:22 -0400). pyopengl is out of scope: it has its own review in `pyopengl/plans/CODE-REVIEW-2026-09-24.md`. The declared gates (`tools/preflight.py`) were run separately and are not reported here. Where a reviewer ran ruff or mypy on specific paths, those results appear in the findings.

## Summary of findings

Every finding has a code, unique across the document: an area prefix, then the reviewer's id. The id's letter gives the severity where it has one: C critical, M major, m minor, n nit, d a documentation finding, t a test gap. `ZON-M4` is major finding 4 in the zones area, and its full write-up is under that code in [Area 2](#area-2-zones-zon). CP, PH, BIN, DOC, LIB and GAME codes are numbered in series instead. The table lists all 496 findings in document order: 5 critical, 89 major, 257 minor and 145 nit. GAME-F3 is a pointer to two other findings and has no severity of its own.

The Status column records the work on each finding: `Fixed` with the commit that fixed it (in the project named, or in openglcontext when none is), `Fixed with CODE` where another finding's fix covers it, `Not a defect` with the reason, `Documented` where the limit is now stated, and `Needs input` where the choice is the maintainer's; the question is at the end of that finding's section, under "Question for the maintainer". `Open` is not yet worked.

The decisions below are the review's proposals, and each is the maintainer's to confirm:

| Decision | Meaning | Count |
|---|---|---|
| Fix | Fix it where it is. | 395 |
| Fix in engine | The fix belongs in OpenGLContext, or in a library other than the one it was found in. | 16 |
| Document | The behaviour stays; the docs or docstring state the limit. | 9 |
| Investigate | The reviewer rated it Possible or could not drive it; confirm first, then fix or close. | 39 |
| Maintainer decision | A choice between behaviours; the remediation names the options. | 22 |
| Duplicate of *code* | Reported again under another code; fixing that one fixes this. | 16 |

| Code | Severity | Summary | Decision | Remediation | Status |
|---|---|---|---|---|---|
| REF-C1 | Critical | Bad reflector values abort a load or fail every frame; reflection pass has no failure isolation | Fix | Catch `OverflowError` and reject non-finite values in `reflector_for`, clamp `scale` and `interval`; sanitise fields in the planner; wrap `renderReflections` to log once and disable planar reflections. | Fixed 2b39a0e |
| REF-M1 | Major | Object `mirror` hook mutates cached shared Shapes, so every node on that mesh mirrors | Fix | Build new `Shape`/`Appearance` per shape sharing the geometry and return them as `(node, True)`, or make `hooks.node` honour `shareable=False`. Test two nodes on one mesh. | Fixed f9051d6 |
| REF-M2 | Major | Mirror over the texel budget is never drawn and forces redraws forever | Fix | Draw an unaffordable must-draw candidate at the largest scale that fits (floored near 1/8); record unaffordable candidates so `unfinished` stops spinning. Add a tight-budget planner test. | Fixed d6cc1c7 |
| REF-M3 | Major | Millisecond target re-applies one stale GPU reading every frame, compounding | Fix | Expose a fresh flag or sequence number on `GpuTimer`, call `measured` once per new reading using the scale that frame drew with. Test that repeated readings leave the scale unchanged. | Fixed d6cc1c7 |
| REF-M4 | Major | `too_small` and `_separateShapes` run per-record Python in every mirror view | Fix | Vectorise `too_small` over the gather's arrays per mirror view; cache `_separateShapes` per frame and path generation, or precompute a per-gather "refused by shared draw" array. | Fixed b05e7f8 |
| REF-M5 | Major | Separate-view budget ignores nested mirror views and approximates top-level ones | Fix | Decide `separate` from the mirror view's own contents, testing a per-gather "refused by shared draw" array against the mirror view's frustum survivors. | Fixed b05e7f8 |
| REF-M6 | Major | Tiles redrawn after a repack bypass texel and separate-view budgets | Fix | Return remaining texels and separate views from `choose`, charge moved tiles against them and drop a moved tile's lookup when it does not fit. Add a repack test. | Fixed d6cc1c7 |
| REF-M7 | Major | Plane-fit cache keyed on `id()` of an array it does not hold | Fix | Store the positions array itself in `_FITS` and compare with `is`; for in-place edits key on a geometry change counter. | Fixed c2bf4ee |
| REF-M8 | Major | `IndexedFaceSet` mirrors ignore `ccw`, and the VRML97 path is untested | Fix | Negate the fitted normal when `ccw` is false; optionally vectorise `_fan`. Add tests for both windings and polygons with more than three corners. | Fixed c2bf4ee |
| REF-m1 | Minor | Rough-mirror mip levels sample the uncleared gutter at tile edges | Fix | Clear the tile's slot including `GUTTER`, clipped to the atlas; optionally inset `planarBounds` by half a texel of the level read. | Fixed 63ebd9c (the gutter is cleared with the tile; planarBounds is not inset further) |
| REF-m2 | Minor | `screen_rect` gives any mirror with a corner behind the camera the whole view | Fix | Clip the box edges against the near plane before projecting and take the rect of what survives; keep `WHOLE` only as fallback. | Fixed 9eb8117 |
| REF-m3 | Minor | Default schedule redraws every mirror every frame in a still scene | Maintainer decision | Options: redraw optional valid low-drift candidates only from leftover budget; add a `reflectionIdleRedraw` setting (default off) with `interval` as idle rate; or document the GPU cost. | Needs input |
| REF-m4 | Minor | Invalid held tile is dropped when unchosen, so the mirror flips to the probe | Fix | Keep an invalid but readable held tile in `kept` with its lookup when not chosen; treat only other-view, plane or size tiles as unreadable. | Fixed d6cc1c7 |
| REF-m5 | Minor | Planning is Python per mirror per view, growing as mirrors^bounces; bounces unbounded | Fix | Clamp `bounces`, stop descending once candidates exceed a multiple of `budget.views`, and pass the per-view eye into `plan_mirror` instead of recomputing inverses. | Fixed d6cc1c7 (descent stops at four candidates per budgeted view rather than a hard clamp on bounces; eye passed to plan_mirror) |
| REF-m6 | Minor | `surface_roughness` converts the whole roughness image on the render thread | Fix | Use `getchannel('G')` and `ImageStat` on a reduced copy, or compute at `PBRTexture` build; declare a `mean_roughness` cache on `PBRTexture`. | Fixed c2bf4ee |
| REF-m7 | Minor | `_water_plane` recomputes mean level and bounds every frame | Fix | Cache it in `_FITS` as `mesh_plane` does, keyed on the positions array (see REF-M7). | Fixed c2bf4ee |
| REF-m8 | Minor | `mirror_generation` does not watch `PBRMesh.waveStyle` | Fix | Add `(PBRMesh, 'waveStyle')` to `_watch_mirror_fields`; document that `PBRMesh.material` is read at load time, or make it a field. | Fixed 12d087e |
| REF-m9 | Minor | Atlas and held tiles stay allocated while reflections are off | Fix | On the transition to off, `release()` the atlas and `reset()` the planner. | Fixed b05e7f8 |
| REF-m10 | Minor | New atlas with draws keeps lookups into undefined texels | Investigate | Confirm reachability; then on `ensure_size() == True` always reset the planner and filter `plan.lookups` to keys in `plan.draws`. | Fixed b05e7f8 (reachable only where the atlas is remade without the planner being reset; every release now resets it, and a new atlas keeps only this frame's tiles and lookups) |
| REF-m11 | Minor | `keep()` blits the whole atlas every frame with a nested mirror | Fix | Blit only the tiles `_previous_lookups` refer to, grown by the gutter. | Fixed 63ebd9c |
| REF-m12 | Minor | Atlas leaves clear colour, texture binding and read framebuffer changed | Fix | Save and restore the clear colour; bind through the atlas's own `REFLECTION_UNIT`; save both framebuffer bindings in `keep` and `begin`. | Fixed 63ebd9c |
| REF-m13 | Minor | Atlas stays bound on unit 31 while it is the draw target | Investigate | Confirm the feedback-loop case; then bind 0 or the `kept` copy on `REFLECTION_UNIT` before `atlas.begin()` when `bounce` is False. | Fixed b05e7f8 |
| REF-m14 | Minor | Mirror-view content selection lives in the window-bound pass, untestable without GL | Fix | Move per-draw selection into a planner method returning `(kept, missing, incomplete)`; `mirrorFrames` only builds `ViewFrame`s. Test it without GL. | Fixed b05e7f8 |
| REF-m15 | Minor | Surfaces normal maps may invert vertical relief; images upside down on walls | Investigate | Render a ramp height map on a `panel` lit from +y and assert the brighter half; if confirmed, flip `dy` (or tangent w) and flip v in the surface geometries. | Fixed d93daab (confirmed by render: images were upside down on walls; the normal map was right for the maps' row-0-top convention, so v was flipped in the geometry and normal_map left alone) |
| REF-m16 | Minor | Reflection code has untested branches across planner, pass, atlas and hook | Fix | Add GL-free planner tests for missing branches, an `IndexedFaceSet` mirror test, a GL test forcing program-set failure, and hook tests for string-bool, bool-number and `LOD`/`Switch`. | Fixed 3390cf2 (with the tests in c2bf4ee, f9051d6, d6cc1c7, b05e7f8: IndexedFaceSet mirrors, the hook's string-bool, bool-as-number and LOD/Switch cases, the moved-tile redraw, the millisecond target in the pass, a GL test where select_program_set fails, and the planner's refusal branches) |
| REF-n1 | Nit | Planner calls private `_texels`; `reflection.__all__` incomplete | Fix | Make `texels` public and add `NDCRect`, `WHOLE`, `TEXEL_STEP`, `TileRect` and `mesh_plane` to `__all__`. | Fixed c2bf4ee |
| REF-n2 | Nit | Draw records are untyped tuples indexed by position | Fix | Introduce a `DrawRecord` `NamedTuple` or `Protocol` (placement, volume, path, node) so mypy checks it. | Needs input |
| REF-n3 | Nit | `_Shelf.slots` holds raw `[x, width, key]` lists | Fix | Replace with a small `NamedTuple` or dataclass. | Fixed 2213c93 |
| REF-n4 | Nit | Mutable class-level defaults on `_FlatEffectsMixin` | Duplicate of PASS-n4 | Fixed with PASS-n4: initialise per instance or default to `None`. | Fixed with PASS-n4 |
| REF-n5 | Nit | `ReflectedView.__getattr__` recurses forever when `source` is unset | Fix | Raise `AttributeError` when the name is `source`. | Fixed b05e7f8 |
| REF-n6 | Nit | Coplanar grouping rounds to three decimals; docs say "within a millimetre" | Maintainer decision | Options: cluster planes by tolerance, or change the docs to say "rounded to a millimetre". | Fixed d6cc1c7 (settled by correctness: grouped by tolerance, as the docs already say) |
| REF-n7 | Nit | Planner `_material` ignores `geometry.material`, reading roughness as 0 | Fix | Fall back to `geometry.material` as `shape_reflector` does. | Fixed c2bf4ee |
| REF-n8 | Nit | `renderReflections` may call `triggerRedraw(0)` twice per frame | Fix | Call `triggerRedraw(0)` at most once per frame. | Fixed b05e7f8 |
| REF-n9 | Nit | `reflectionBudget()` evaluated twice per frame | Fix | Compute the budget once and reuse it for `capacity`. | Fixed b05e7f8 |
| REF-n10 | Nit | `ReflectionPlan.rough` docstring uses a perception verb ("wants") | Fix | Say the mirror "reads" the blurred mip levels. | Fixed b05e7f8 |
| REF-n11 | Nit | `bin/mirrorhall.py` is scenery in the commands package | Fix | Move it beside the demo data or into a `demos`/`scenes` module. | Needs input |
| REF-d1 | Minor | Docs say 32 texture units compiles reflections out; 32 is enough | Duplicate of DOC-07 | Fixed with DOC-07: say "fewer than 32". | Fixed with DOC-07 |
| REF-d2 | Minor | Reflectance missing from `mirrorhooks` docstring and the Blender panel docs | Duplicate of DOC-08 | Fixed with DOC-08 for the Blender step; also add `reflectance` to the `mirrorhooks` module docstring. | Fixed with DOC-08; the mirrorhooks module docstring already lists `reflectance` |
| REF-d3 | Minor | Docs say no mirror is left out for long, contradicted by crowding and REF-M2 | Fix | State which case "none is left out for long" covers in `docs/reflections.rst`. | Fixed d6cc1c7 |
| REF-d4 | Nit | `distortion` described in "view widths" but applied in the mirror's crop | Fix | Say "widths of the mirror's view" in the docstring and docs. | Fixed 2213c93 |
| REF-d5 | Nit | Bold-leader list in `docs/reflections.rst:119-124` | Fix | Rewrite as plain words or hyphenated definitions. | Fixed f9051d6 |
| REF-d6 | Minor | No mirrors tutorial | Fix | Add a short `tests/*.py` walkthrough: a room, one `PlanarReflector`, `varied()`, water and the budget overlay. | Fixed 7e9a516 |
| REF-d7 | Nit | Limits omit that `IndexedFaceSet` mirrors must be counter-clockwise | Duplicate of REF-M8 | Fixing REF-M8 removes the limit; until then state it in the limits section. | Fixed with REF-M8 (c2bf4ee): the limit is gone, and docs/reflections.rst says an IndexedFaceSet mirror faces the side ccw names |
| ZON-M1 | Major | Runtime edits to a zone's settings are ignored until zones are re-keyed | Fix | Observe the `settings` field and each setting's fields; bump `_zoneEpoch` and rebuild tables on change. Test editing `intensity`, toggling `enabled`, adding a setting. | Fixed 41aa5cb |
| ZON-M2 | Major | Object scaled in place, or with changed bounds, keeps its old zones | Fix | Store the scale and bounds identity in `_ObjectZones`; apply the slack shortcut only when the upper 3x3 is unchanged. | Fixed 41aa5cb |
| ZON-M3 | Major | Instanced group compares member matrices by reused `id()`, missing moves | Fix | Hold the matrix objects and compare with `is` (or compare translations); key the group by its stable identity, not the visible subset, and evict with the group. | Fixed 41aa5cb |
| ZON-M4 | Major | Any zone moving evicts every image-light probe layer, so they never light | Fix | Call `keep()` with zone ids plus each live `ZoneEnvironment.light` id, or key reservations by owning zone; use `id(zone.zone)` for liveness. | Fixed 41aa5cb |
| ZON-M5 | Major | One moving zone reclassifies every object every frame | Fix | Move the zone's tree entry and mark stale only objects referencing or overlapping that zone via a reverse index; keep the global epoch for add/remove. | Fixed 41aa5cb (one creeping zone over 5,000 objects: 95 ms a frame before, 3 ms after; first frame 125 ms to 53 ms) |
| ZON-M6 | Major | `classify_many` builds objects x zones x 8 arrays; 443 MB first-frame spike | Fix | Chunk items (about 1,024 at a time) and query the tree per object or bucket rather than by the union box. | Fixed 41aa5cb (20,000 boxes over 56 zones: 434 MB peak before, held under 64 MB by a test) |
| ZON-M7 | Major | Malformed `OGLC_zone` values abort loading the whole document | Fix | Guard `zone_for`, `_environment` and `_reverb` with `(TypeError, ValueError)`, warn once, return None; require three sizes in `read_shape`; add the cases to tests. | Fixed with SG-M1 (69e59f9) |
| ZON-M8 | Major | Zones overwrite the application's audio reverb every frame | Fix | Touch reverb only when a zone has `ZoneReverb`; restore the application's value on leaving, or blend over it; use one default decay. | Fixed b779874 |
| ZON-M9 | Major | Emitter zone gain and reverb stick after the last zone goes | Fix | On zones going to none, reset `zoneGain` to 1.0 and clear reverb, or always call `apply_zones`. | Fixed with PH-05 (d45de01): `audio.scene.update` calls `apply_zones` once more on the first frame with no zones after frames with some |
| ZON-M10 | Major | Zone modules fail the mypy gate with 47 errors | Fix | Use `TYPE_CHECKING` with a pass-surface Protocol, narrow `held`, add a `Region` protocol in `omi_physics.gravity`, type numpy returns. | Fixed 8c0b006 (the typing commit made before this area's work) and bf9facc (`TYPE_CHECKING`); every zone module is clean under `.preflight-venv/bin/mypy`, and `omi_physics.gravity` now declares a `Region` protocol. The one error mypy reports is in `scenegraph/reflector.py`, outside this area (see Observed failures) |
| ZON-M11 | Major | Zone render and cost tests turn a crash into a skip | Fix | Skip only on the no-GL condition; otherwise assert `returncode == 0` and show stderr; harness catches only context-creation failure. | Fixed c260e9c |
| ZON-m1 | Minor | Failed capture discards the whole schedule and retries every frame | Fix | Keep the schedule, mark only that zone failed with retry on `lost()`, and log once with `log.exception`. | Fixed 3b37935 (the schedule's own bookkeeping, per zone, rather than LayerGuard, which switches off a whole layer: one zone's failure leaves the other zones' probes) |
| ZON-m2 | Minor | `probe.convolve` returning False repeats a capture forever | Investigate | Confirm the path; then count attempts and give up with a log line, or call `schedule.lost()`. | Fixed 3b37935 (path confirmed: `convolve` returning False left the capture wanted; given up at the third refusal, retried on `lost()`) |
| ZON-m3 | Minor | Capture cube mipmapped on every partial frame and after failure | Fix | Pass `whole=schedule.drawn(...)` to `target.end`, or mipmap inside the `drawn` branch. | Fixed 3b37935 |
| ZON-m4 | Minor | `CaptureTarget` GL names never released with the context | Fix | Register through `contextresources` like the IBL probe, or release in the pass teardown. | Fixed with PASS-M1 (b3b34b3): `ZonesMixin.disposeResources` releases `_captureTarget` and `drop_pass` reaches it at context loss; 3b37935 adds a test holding it |
| ZON-m5 | Minor | Capture path reads `CaptureSchedule._captures` directly | Fix | Use `schedule.layer_of(key)`. | Fixed bf9facc |
| ZON-m6 | Minor | `zoneCaptureFaces` reads the environment every frame | Fix | Use `renderoptions.number(self, 'zoneCaptureFaces', FACES_PER_FRAME)` and let the field own the environment default. | Fixed bf9facc |
| ZON-m7 | Minor | Mutable class-level defaults on the zone mixin | Fix | Initialise per-instance state in `_initZones()` from `FlatPass.__init__`, or use None sentinels; compute `_ids` in `ZoneTable.__init__`. | Fixed bf9facc |
| ZON-m8 | Minor | Light-zone classification runs numpy per object and per zone | Fix | Classify light zones with `classify_many` via a `ZoneTable`, then run `stacked` per object. | Fixed 41aa5cb |
| ZON-m9 | Minor | Per-frame Python loops over zones for capture and mirror weights | Fix | Compute `point_weights(self._allTable, camera)` once per view and share it; skip zones already `camera_inside`. | Fixed 41aa5cb |
| ZON-m10 | Minor | Zone-owned lights still render shadow maps for every view | Maintainer decision | Either skip shadows for zone lights no visible object is zoned into, or record the gap in the plan and docs Limits. | Fixed 05d8826 (decided: implemented rather than documented, per the headroom rule; a zone-named shadowed light draws its map only while one of its zones' reach is in a view's frustum, all lights kept on frames that may draw reflections) |
| ZON-m11 | Minor | Zones apply only to the PBR program; Limits omits this | Maintainer decision | Either add `lightsOff` to VRML97, terrain and vegetation programs, or document exactly which programs honour zone lights and environments. | Fixed 5cf5e98 (decided: `lightsOff` added to the VRML97 lighting programs, since a zone light lighting outside its zone in the flat pass is a wrong answer; terrain, vegetation and water read no punctual lights and no probe, and the Limits say so exactly) |
| ZON-m12 | Minor | `chosen` keeps `kept[0]` as base even when not inside | Fix | Keep the head only when it is inside; otherwise choose all layers by nearness. | Fixed 41aa5cb |
| ZON-m13 | Minor | Gravity volumes snapshot zones and miss Switch/LOD children | Fix | Give `ZoneRegion` a live zone reference or update per step; walk the pass's child fields; at least document the snapshot. | Fixed 509fcb6 (`scene_zones` follows `renderedChildren`; `GravityZones.follow` keeps a world's zone volumes where the pass places the zones, called every walking step) |
| ZON-m14 | Minor | `TilesTerrain` joins zones file name without containment; loads synchronously | Duplicate of SG-M7 | Reject absolute and `..` names; catch load errors and continue without zones. | Fixed with SG-M7 (1d665f3): names contained, a zones document that is refused or fails to load is logged and the world built without it; the load stays in the constructor like the terrain maps and tree table it sits beside |
| ZON-m15 | Minor | `omi_audio` pin predates the reverb the zones drive | Duplicate of BIN-3 | Release omi_audio with reverb and raise the pin; log once when `ZoneReverb` has no engine reverb. | Fixed with BIN-3 (with the floor raised every engine has a reverb, so the "log once when there is none" half has nothing to report) |
| ZON-m16 | Minor | No numeric test holds GLSL zone distances to Python | Fix | Add a `gl_context` test comparing `zoneDistance` with `zones._distance` for every kind, including tapered cylinder and uneven capsule. | Fixed ccab6c5 (test gap: the GLSL and Python distances agree for every kind, so there was no red to show) |
| ZON-m17 | Minor | Cost test times intensity zones, not the probe-array path | Fix | Add a `probes` mode with four image-lit layers and time it; tighten the intensity-only bound. | Fixed c260e9c |
| ZON-n1 | Nit | Dead code and test-only paths in zone modules | Maintainer decision | Either delete the unused helpers, or document them as public API and have the pass use them. | Fixed 41aa5cb (decided: the dead helpers are deleted; the one-object functions `environment_layers`, `lights_off` stay as documented API built from the functions the pass runs) |
| ZON-n2 | Nit | `_allTable` and `_nearness` declared mid-method list | Fix | Move them with the other state at the top. | Fixed bf9facc |
| ZON-n3 | Nit | `if False:` used instead of `TYPE_CHECKING` | Fix | Use `typing.TYPE_CHECKING`. | Fixed bf9facc |
| ZON-n4 | Nit | Avoidable `# type: ignore` on fixed-length tuples | Fix | Build explicit three-element tuples or a `_vec3()` helper. | Fixed bf9facc (the scenegraph and loader ones were already gone with 8c0b006 and 69e59f9) |
| ZON-n5 | Nit | Bare generic annotations (`frozenset`, `set`, `List[tuple]`) | Fix | Use parameterised types such as `FrozenSet[int]`. | Fixed bf9facc |
| ZON-n6 | Nit | `ZonePack.key` built from `id(PlacedZone)` | Fix | Key on `id(placed.zone)` plus the placement's matrix identity. | Fixed 41aa5cb |
| ZON-n7 | Nit | Three copies of the zone falloff curve | Fix | Share `zones.weight` in `box_gain` and `point_weights`. | Fixed 41aa5cb (`point_weights`), b779874 (`box_gain` is a box zone's weight) |
| ZON-n8 | Nit | `ZoneGravity.type` shadows a builtin | Document | Keep the name for `OMI_physics_gravity`; note the choice in the docstring. | Documented 41aa5cb |
| ZON-n9 | Nit | `pbr.frag` comment carries a review finding number | Duplicate of PASS-n1 | Drop the "(finding 4.4)" parenthesis. | Fixed with PASS-n1 |
| ZON-n10 | Nit | `register_scoped` returns `Any` | Fix | Add `@overload`s for the decorator and call forms. | Fixed bf9facc |
| ZON-n11 | Nit | Unknown `shapeType` silently drops a zone | Fix | Warn once per zone. | Fixed 41aa5cb |
| ZON-d1 | Minor | Zones plan status stale and departures unrecorded | Fix | Update status in `GLTF-SPATIAL-ZONES.md` and `PROJECT-PLAN.md` (four layers), record the hand-off departures, fix `autoPlay` to `autoplay`. | Fixed cb56a4d |
| ZON-d2 | Minor | No shipped zones demo; audio demo still uses `box_gain` | Fix | Add an `oglc-zones` scene with a dim room, straddler, captured probe, door light and audio area; move the audio demo areas to zones. | Fixed with DOC-13 (08f7632, `oglc-zones`: a dimmed room with its lamp, a captured probe, a statue shown from inside, the courtyard floor crossing both zones) and BIN-5 (f79eef5, the audio demo's areas are zones) |
| ZON-d3 | Minor | `zones.rst` says moved zones re-place, true only for rendering | Fix | Qualify the sentence: settings edits (ZON-M1) and gravity (ZON-m13) do not follow. | Fixed 41aa5cb, 509fcb6 (moves and edits are followed by rendering, audio, visibility and mirrors, and by gravity while walking) |
| ZON-d4 | Nit | `zones.rst` extension list omits `EXT_lights_image_based` | Duplicate of DOC-16 | Add `EXT_lights_image_based` to the list at `docs/zones.rst:122-124`. | Fixed with DOC-16 (`docs/zones.rst` lists `EXT_lights_image_based` among the extensions read in a zone) |
| ZON-d5 | Nit | `zones.rst:205-206` flourish restates the reverb | Fix | Delete the sentence. | Fixed 41aa5cb |
| ZON-d6 | Minor | `zones-internals.rst` misstates what moves `_zoneEpoch` | Fix | Say only placement changes move `_zoneEpoch`; captures and probes move `_probeVersion`, light order `_slotVersion`. | Fixed 41aa5cb |
| ZON-d7 | Minor | `zones-internals.rst` names functions the pass does not run | Fix | Name `classify_many`/`stacked`/`chosen` and `light_decision`/`light_mask`. | Fixed 41aa5cb |
| ZON-d8 | Nit | `openglcontext/CLAUDE.md` directory map omits zone modules | Fix | Add `zonepass.py`, `zonelayers.py`, `zoneprobes.py`, `zone.py`, `zones.py` and `imagebasedlight.py`. | Fixed 41aa5cb |
| ZON-d9 | Minor | Spec rule 3 implies lights off for straddlers; code darkens only wholly-inside | Document | State the per-object rule in the `OGLC_zone` spec: only wholly-inside objects lose lights. | Documented cb56a4d |
| PASS-M1 | Major | Pass-owned GL resources (atlas, timer, UBO, IBL probe, program sets) leak on scene swap | Fix | Add `FlatPass.disposeResources()` extended by each mixin through `super()`; call it from `renderpass._dispose` and context teardown; GL test swapping scenegraph twice with a mirror. | Fixed b3b34b3 |
| PASS-M2 | Major | PBR batching memo ignores reflector, waveStyle and in-place texture changes | Fix | Add `mirror_generation()` to the memo signature; give materials a batching generation bumped by `reflector`, `textures`, `octahedralViews`; test that a new mirror becomes a single. | Fixed 12d087e |
| PASS-M3 | Major | LOD memo ignores the LOD node's own range and coverage fields | Fix | Add a per-node version to the key via a dispatcher watch on level-deciding fields bumping a counter; add the repro to `test_lod_multiview.py`. | Fixed 99dde94 |
| PASS-M4 | Major | Multi-view shadows vanish everywhere when the active view has no casters | Fix | Take the early-out from the caster pool or all views' records; fit only directional cascades to the active view; two-view test with the camera turned away. | Fixed 20e28d2 |
| PASS-m1 | Minor | Legacy pick path clears the frame gather, skipping reflections and zone captures | Fix | Split `finishViews` into viewport/scissor restore and end-of-gather; call only the first from `selectRenderViews`, or keep the gather in a frame-scoped object. | Fixed 9f08c1a (described by the empty commit bb53dfa: another agent's commit swept the staged change in) |
| PASS-m2 | Minor | One frame's gather is published through two handoff mechanisms | Fix | Replace `_gathered` and `_frameGather` with one frame-scoped holder created in `Render` and cleared in `finally`; document it in `renderpasses.rst`. | Fixed 9f08c1a (see PASS-m1) |
| PASS-m3 | Minor | Two mypy no-any-return errors in `instancing.py` and `_flat.py` | Fix | Return `[int(s) for s in ...]` in `winding_signs`; annotate the `batchers()` result as a typed callable pair. | Fixed 8c0b006 (both mypy errors) and a2232a5 (the pair typed as instancing.Batchers) |
| PASS-m4 | Minor | Impostor half-texel inset assumes 512-pixel tiles | Fix | Pass the atlas size as a uniform set in `set_impostor`, or use `textureSize` in the vertex stage; GL test with a 256-pixel 8-view atlas. | Fixed 18bde6e |
| PASS-m5 | Minor | Impostors cast shadows as their raw untransformed quad | Maintainer decision | Either skip impostor materials in `_shadowCasterRecords`, or make the depth shaders honour `impostorGrid` with alpha test; document the chosen limit in `lod.rst`. | Fixed 18bde6e (the settled option: impostors are left out of the shadow maps rather than casting the raw quad; a light-facing alpha-tested impostor shadow is a feature, see the question below) |
| PASS-m6 | Minor | Multi-view bloom leaves window areas outside the tiles unwritten | Fix | When tile rects do not cover the target, composite the full window once with zero-strength bloom, or clear the previous FBO first. | Fixed 8dc1976 |
| PASS-m7 | Minor | Mirror planner scans every visible record even in mirrorless scenes | Fix | Return early from `renderReflections` when `sceneMirrors()` is empty; let the planner consider only records in that set. | Fixed 20e28d2 |
| PASS-m8 | Minor | `renderShared` duplicates `setupViewLighting` line for line | Fix | Call `self.setupViewLighting(matrix, lighting, fitted=True)`. | Fixed 20e28d2 |
| PASS-m9 | Minor | Multi-view and reflection orchestration have grown into `_flat.py` and `flateffects.py` | Fix | Extract a `MultiviewPassMixin` and a `ReflectionsMixin`, each with a Protocol for pass needs; pass shared state as one frame object through `Render`. | Fixed 6657acf (ReflectionsMixin, passes/reflectionpass.py) and 8c20e9f (MultiviewPassMixin, passes/multiviewpass.py); the frame's gather is the frame object (FrameState, 9f08c1a). viewFrames and activeFrame stay on the pass because pick routing reads them between frames, and lighting stays an argument |
| PASS-m10 | Minor | Point-light culling ignores mirror views, dropping shadows in reflections | Investigate | Confirm, then include planned mirror frames in `_pointLightInView`, or render spot and point maps whenever any mirror is planned. | Fixed 20e28d2 (confirmed by reading: `_lightInView` tested only the main views' frusta, and mirror views are planned after the maps are drawn; every light keeps its map while the frame may draw reflections) |
| PASS-m11 | Minor | `_instance_divisor` survives VAO release, so a rebuilt VAO mismatches it | Investigate | Confirm, then set `gpu._instance_divisor = 1` in `_build_instance_vao` beside the VAO assignment. | Fixed 0ea2346 (confirmed: a GL test reads the rebuilt VAO's divisor) |
| PASS-m12 | Minor | Geometry-stage generator recognises only the simplest `out` declarations | Investigate | Parse the preprocessed source, or read varyings from one shared include; at minimum raise `ValueError` naming unrecognised `out` forms. | Fixed 1f9837f |
| PASS-m13 | Minor | `IBLProbe.convolve` does not restore program and GL state as documented | Fix | State what is left bound and enabled in the docstring, or save and restore through the pass's state memo. | Fixed 9028bfe (the program and the depth/cull/blend switches are restored, not only documented) |
| PASS-m14 | Minor | IBL rotation uses nearest sampling; `upload_light` fails without specular images | Fix | Sample bilinearly across the face; return False when `light.specular` is empty before touching textures. | Fixed 9028bfe |
| PASS-m15 | Minor | `sceneAmbient` raises IndexError on sequences shorter than three | Fix | Treat a length-1 sequence as grey or validate where set; state the default's reason in the present tense. | Fixed 985053a |
| PASS-m16 | Minor | `mirror_generation` does not watch geometry `waveStyle` | Duplicate of REF-m8 | Add the geometry `waveStyle` field to `_watch_mirror_fields`. | Fixed 12d087e |
| PASS-m17 | Minor | `LoadPool` workers die on BaseException and are never replaced | Investigate | Confirm, then drop dead threads in `submit`, or catch `BaseException`, log and keep the worker, re-raising `KeyboardInterrupt` on the main thread. | Fixed 0f2b557 (confirmed: a SystemExit ended the only worker and the next load never ran) |
| PASS-m18 | Minor | New branches lack tests (batchers, LOD memo, IBL probe, sharesDraw, others) | Fix | Add unit tests with the fixes above; reuse the `_Path` fake in `test_lod_multiview.py` for PASS-M3 and `sharedRecords`. | Fixed 40e887d (with the tests in the commits for PASS-M2, M3, M4, m1, m13-m15 and n11) |
| PASS-n1 | Nit | Review finding numbers and history in comments and docstrings | Fix | State the reason in the present tense and drop finding numbers in `pbr.frag`, `renderSet` and `sceneAmbient`. | Fixed 985053a (every finding number in the shaders, not only pbr.frag) |
| PASS-n2 | Nit | Stale cross-references to modules and methods in comments and docs | Fix | Point `_multiview_inc.glsl` at `multiview/strategy.py` (see MV-m12); correct the `gatherPaths`, `selectLevels` and `MULTIVIEW_PROGRAMS` references. | Fixed 4b8943e |
| PASS-n3 | Nit | `renderShared` parameter `reflection` shadows the `reflection` module | Fix | Rename the parameter to `into_atlas`. | Fixed 4b8943e |
| PASS-n4 | Nit | Mutable class-level defaults on the pass and effects mixin | Fix | Initialise `viewFrames`, `_reflection_lookups`, `_previous_lookups`, `_incompleteMirrors` in `__init__`, or declare the type only. | Fixed 4b8943e (read-only empty defaults; no test: mypy holds the types, and nothing can mutate them) |
| PASS-n5 | Nit | `class GatheredPaths` has no blank lines before it | Fix | Add the two blank lines PEP 8 E302 asks for. | Fixed 4b8943e |
| PASS-n6 | Nit | Silent `except Exception: pass` around draw-state reset and bloom composite | Fix | Log with `log.debug(..., exc_info=True)` at least. | Fixed 8dc1976 (bloom through a LayerGuard, logged once and switched off; the resets log at debug) |
| PASS-n7 | Nit | `chooseLevels` warns once per broken LOD node per frame | Fix | Rate-limit the warning, or mark the path broken. | Fixed 4b8943e |
| PASS-n8 | Nit | `_casterWorldGeometry` stores each entry into `current` twice | Fix | Store each entry once. | Fixed 4b8943e |
| PASS-n9 | Nit | `_textureUnits` caches through `__dict__` with an identity check | Fix | Compute the list once in `compile()` where `ext_channels` is set. | Fixed 4b8943e |
| PASS-n10 | Nit | `set_impostor` does lookups for every shape draw | Fix | Fold impostor flags into the material's `_ubo_version`-keyed state. | Fixed 4b8943e |
| PASS-n11 | Nit | `sharesDraw` detects own-program appearances by `hasattr(appearance, 'objects')` | Fix | Name the capability, for example `appearance.bringsProgram`, or test the concrete class. | Fixed 4b8943e |
| PASS-n12 | Nit | `stats.shapes` counts a shape once per view it appears in | Fix | Say so in `renderstats.py`, or count unique paths. | Fixed 4b8943e |
| PASS-n13 | Nit | `Image.BILINEAR` needs a type-ignore | Fix | Use `Image.Resampling.BILINEAR` and drop the ignore. | Fixed 9028bfe |
| PASS-n14 | Nit | `Any` annotations where concrete types exist | Fix | Type `lighting` as `Tuple[str, Optional[IBLProbe]]`, `GatheredPaths` arrays as `np.ndarray`, and the other listed `Any`s concretely. | Fixed 4b8943e |
| PASS-n15 | Nit | `modelproj` stays untrimmed after `prepareViews` trims the projection | Fix | Recompute `frame.modelproj` where the projection is trimmed. | Fixed 4b8943e |
| PASS-n16 | Nit | `IBLProbe.grow` counts a fallback loss twice | Fix | Count the loss once so the counter matches its docstring. | Fixed 9028bfe |
| PASS-d1 | Minor | `flat.rst` describes the old world-space corner cull | Fix | Describe the per-box local AABB test with planes carried into box space, as `_frustumSurvivors` does. | Fixed 7c01756 |
| PASS-d2 | Minor | `renderpasses.rst` omits `_frameGather`, several pass modules, and once-a-frame stages | Fix | Document the frame gather, list the missing modules, and say which stages run once a frame rather than per view. | Fixed 9f08c1a (see PASS-m1) |
| PASS-d3 | Nit | `openglcontext/CLAUDE.md` map omits `imagebasedlight.py` and `renderstats.py` | Fix | Add both modules to the directory map. | Fixed 7c01756 |
| PASS-d4 | Minor | `lod.rst` does not state impostor shadow or atlas-size limits | Fix | State the impostor shadow behaviour chosen under PASS-m5 and the atlas-size coupling from PASS-m4 in `lod.rst`. | Fixed 18bde6e |
| PASS-d5 | Nit | No page describes the overlay's mirror timing counters | Fix | Describe how the overlay shows `mirrorMilliseconds` and the mirror counters in `overlayui.rst`. | Fixed 7c01756 |
| PASS-d6 | Minor | `ImageBasedLight` node is documented only in its module docstring | Fix | Document its fields, `rotation` and `irradiance_faces` units, and link the node from `gltf.rst` and `zones.rst`. | Fixed 9028bfe |
| MV-M1 | Major | Cached view navigation keeps driving the camera `point_view` / `look_through` replaced | Fix | Rebuild in `navigation_for` when `navigation.camera` is not the view's camera; carry `mode` over within a family; test gestures after `point_view` and `look_through`. | Fixed 9587724 |
| MV-M2 | Major | Camera-less view in a tile uses the window's aspect ratio | Fix | In `layoutViews`, derive the projection from the tile (explicit aspect to `viewMatrix()` or set/restore `setViewport`); add a split render test with a camera-less view. | Fixed 0047be6 |
| MV-M3 | Major | Tooltip is never laid out; draws 0x0 at the origin | Fix | Lay the tip out in `tooltipTree` or `screenTrees` with the viewport and metrics in hand; test the rectangle after `screenTrees`. | Fixed 659843e |
| MV-M4 | Major | On-demand windows never redraw to show a pending tooltip | Investigate | Confirm interactively, then report the overlay as animating while a tip is pending, or schedule a one-shot redraw at `_pointerSince + TOOLTIP_PAUSE`. | Fixed f2a7193 (confirmed in a hidden GLFW window driving _loopIteration: two frames in 1.5 s, neither with the tip; Context.redrawAt added) |
| MV-M5 | Major | `point_view` family change clamps distance to 20 m, losing small subjects | Fix | Build the orbit with `nearest`/`furthest` scaled from `span` and `lowest=-OrbitView.HIGHEST`; test `shown_by` across a round trip. | Fixed cbf8ae6 |
| MV-M6 | Major | `routeEvent` raises `AttributeError` for hand-rolled events `addPickEvent` accepts | Fix | Use `getattr(event, 'view', None)` in `routeEvent` and `ViewGestures.handle`; set the attribute only where possible; add a duck-typed event test. | Fixed 3bfd0af |
| MV-M7 | Major | Multi-view strategy fixed at first frame; live setting does nothing | Maintainer decision | Either keep `(requested, strategy)` on the pass and re-choose when the request changes, or document the field as start-up only and remove it from the settings screen. | Fixed e75a0e3 (settled by the engine-first rules: the field is live, the pass re-chooses when it changes) |
| MV-M8 | Major | `multiview.grid` is public but not drawn, exported or documented | Maintainer decision | Either finish it (node or pass hook drawing `lines_for` per view honouring `ViewStyle`, plus a demo) or remove it; correct the docstring either way. | Fixed 84ab97b (settled by the engine-first rules: finished rather than removed -- ViewStyle.grid, Grid as a Rendering node in both profiles, shown in oglc-view --views quad) |
| MV-M9 | Major | `EGLContext` ignores the definition's profile and version | Fix | Pass `contextAttributes(definition.profile, definition.version, forwardCompatible=...)` to `_createContext`; test `GL_CONTEXT_PROFILE_MASK` on an `EGLContext`. | Fixed 6805708 |
| MV-M10 | Major | Interrupted viewer archive extraction is cached as a complete world | Fix | Use the same staging helper as CP-3: extract to a `.partial-<pid>` directory, `os.replace` on success, remove on failure. | Fixed f3d7771 |
| MV-M11 | Major | Backends apply the mouse-look pointer-shape guard unevenly; GLUT can unhide it | Fix | Guard once in `OverlayMixin.showCursor` (or in every backend), reset `_cursorShown` when capture ends, add the Qt-style test per backend. | Fixed 7b8de6d |
| MV-m1 | Minor | Capability cache keyed by reusable context address, never evicted | Fix | Register with `contextresources` to drop the entry when the context dies, or key by the context object. | Fixed e75a0e3 |
| MV-m2 | Minor | Fly-through path survives a scene change | Fix | Reset `_flyPath = None` where `self.viewpoints` is assigned. | Fixed 5e2dfd8 |
| MV-m3 | Minor | `advanceFlyThrough` requests frames forever after the path ends | Fix | Return False once the fraction reaches 1.0 and the final pose is applied. | Fixed 5e2dfd8 |
| MV-m4 | Minor | Live fly-through timed from viewer start, shared with turntable | Fix | Give the fly-through its own start time, reset on mount. | Fixed 5e2dfd8 |
| MV-m5 | Minor | `ViewChrome` rebuilds every widget per layout, losing drag highlight and focus | Investigate | Confirm, then rebuild only when shown views, parts or arrangement change (keep a key); otherwise re-arrange existing children. | Fixed f80166a (confirmed: a relayout replaced the armed splitter) |
| MV-m6 | Minor | Quad crossing requests `resize-x` instead of `resize` | Fix | Map `vertical is None` to `'resize'`. | Fixed 0e5b9cb |
| MV-m7 | Minor | Pointer capture can stick after a lost release or layout switch | Investigate | Confirm, then add `ViewLayout.release_all()` called from `show()` and focus-out; treat a press of a held button as a new capture. | Fixed 1f2c4f2 (confirmed: a repeated press stayed with the old view, and show() left the drag running) |
| MV-m8 | Minor | Keys do not follow the active view; examine and dolly use whole window | Investigate | Confirm, then state the limit in the docs or give `ViewNavigation` key bindings; pass `frame.rect` to the orbit builders when the event has a view. | Fixed 42426b0 (drag measured against the tile; the keyboard limit documented rather than giving ViewNavigation key bindings) |
| MV-m9 | Minor | `resolve_source` raises for missing or ambiguous archives instead of returning None | Fix | Return None for a missing local archive; document the `UnknownMember` raise and handle it in the viewer, printing its listing. | Fixed 7f1b047 |
| MV-m10 | Minor | Docs and docstring use nonexistent `context.placeViews` | Fix | Name `viewsArranged`, or show a local function. | Fixed 41ccaab |
| MV-m11 | Minor | `backends.rst` method table lacks `setPointerShape` | Fix | Add a row pointing to `CURSORS` and `overlayui.rst#pointer-feedback`. | Documented 9258495 |
| MV-m12 | Minor | `_multiview_inc.glsl` comment names a nonexistent module | Fix | Point the comment at `OpenGLContext/multiview/strategy.py` (`pack_view_table`). | Fixed 6a8ed9c (comment only; no test) |
| MV-m13 | Minor | `viewLayout` doc comment sits above `setPointerShape` | Fix | Move the comment above `viewLayout: Any = None`. | Fixed 41ccaab |
| MV-m14 | Minor | GLFW standard cursors are never destroyed | Fix | Call `glfw.destroy_cursor` on each in `releaseWindow`. | Fixed d67ee87 |
| MV-m15 | Minor | Exception inside a view leaves scissoring enabled | Investigate | Confirm, then wrap the per-view loop in `try/finally: self.finishViews()` and disable scissoring unconditionally in `finishViews`. | Fixed a17d7a1 |
| MV-m16 | Minor | Public multiview API typed `Any` throughout | Fix | Add a `ViewCamera` Protocol; type `View.camera`, `viewLayout` and `routeEvent` with it and `Optional[...]`. | Fixed e39f521 (with the typing done in d67ee87, 11edccd and 41ccaab for _cursors, _DISPLAY_USES and poses_from; ViewNavigation.camera stays Any, being the navigated camera's own heterogeneous interface) |
| MV-m17 | Minor | `ProgressBar` missing from `__all__`; docstring breaks writing rules | Fix | Add to `__all__`; reduce the docstring to what it draws, what it clamps, and that it takes no focus. | Fixed eac9d70 |
| MV-m18 | Minor | Writing-rule breaches in new multiview, viewer, EGL and Qt docstrings | Fix | Run `/ai-isms --fix` over the listed files. | Fixed 41ccaab; the openglcontext-qt test docstring in f7b7321 (openglcontext-qt) |
| MV-m19 | Minor | `display_answers` runs an uncached Tk subprocess per call | Fix | Cache with `functools.lru_cache` keyed on `(display, directory)`. | Fixed 9e19e67 (the client run is cached per display; the cheap socket check is not, so a server that goes away is still seen) |
| MV-m20 | Minor | `draw_arrays` / `draw_elements` import `OpenGL.GL` on every draw | Fix | Import at module level. | Fixed e75a0e3 |
| MV-m21 | Minor | Viewer archive cache has no eviction or extraction race protection | Duplicate of MV-M10 | Atomic extraction via MV-M10 covers the race; also document the cache directory or add an LRU cap. | Fixed f3d7771 (race: lock and staging; eviction: directory documented as removable at any time, no LRU cap) |
| MV-m22 | Minor | GLUT and Tk map `'no'` to misleading cursors | Fix | Leave `'no'` out of the GLUT table so the call returns False. | Fixed 018ed37 |
| MV-n1 | Nit | `ViewChrome.pointer_pressed` only calls `super()` | Fix | Remove it. | Fixed 0e5b9cb (removal of a pass-through; no behaviour to test) |
| MV-n2 | Nit | `ExpandButton.paint` and `Widget.rippleAt` mutate state | Fix | Make `tooltip` a property; let `animating` clear `_ripple`. | Fixed eac9d70 |
| MV-n3 | Nit | camelCase and snake_case mixed within the multiview package | Fix | Choose one naming style per module family. | Fixed 1e7a9a8 (rule: Context and mix-in methods camelCase, node protocol methods as the scenegraph names them, plain classes and the ui widget protocol snake_case; ViewStyle.clearColour is left, since its one caller in passes/_flat.py is mid-edit by another agent -- rename it to clear_colour when that lands) |
| MV-n4 | Nit | Mixin duplicates `QuadView` defaults; `quad` re-exports navigation constants | Fix | Define each default once. | Fixed 78a4d49 (no behaviour change; no test) |
| MV-n5 | Nit | Redundant aliases and defaults in `strategy.py`; failed detection retried each frame | Fix | Drop `IMPLEMENTED` and the `viewport` alias, align `max_viewports` defaults, cache a failed detection. | Fixed e75a0e3 |
| MV-n6 | Nit | `ViewSet.local` and `view_for` repeat `View` and `Context` logic | Fix | Delegate to `View.local` and `Context.routeEvent`. | Fixed 3bfd0af (view_for delegates to ViewLayout.view_of; ViewSet.local is kept, a one-line delegation glisteel-editor calls) |
| MV-n7 | Nit | `cache_dir()` shadowed by `cache_dir` parameters in `source.py` | Fix | Rename the function or the parameters. | Fixed 7f1b047 |
| MV-n8 | Nit | `hoverWash` names both a colour and a bool; comment misleads | Fix | Rename one of them and correct the per-widget comment. | Fixed eac9d70 (the bool is renamed Widget.washOnHover; nothing outside openglcontext used it) |
| MV-n9 | Nit | `MiniMap` cache in `__dict__` uses a redundant `id()` plus `is` key | Fix | Key the cache by identity once. | Fixed 31435b4 (worse than the nit: the __dict__ key shadowed the _strokes method, so a resized map raised TypeError) |
| MV-n10 | Nit | `hasMouseMoveHandlers` always True once views exist | Fix | Return True only while `gestures._held` is set. | Fixed 0244799 |
| MV-n11 | Nit | `requested_strategy` reads the environment without a read-once variant | Fix | Read the environment once, per the CLAUDE.md read-once rule. | Fixed e75a0e3 |
| MV-n12 | Nit | openglcontext-qt `pyproject.toml` comment names the wrong release | Duplicate of GAME-Q1 | Fixed with GAME-Q1: make the comment match `>=3.0.0a5`. | Fixed with GAME-Q1 (f7b7321, openglcontext-qt) |
| MV-n13 | Nit | `PbufferContext.release()` un-currents whatever EGL context is current | Fix | Release only when this context is current, as `_egl_pbuffer` does. | Fixed 11edccd |
| MV-n14 | Nit | `_DISPLAY_USES` module dict modified without a lock | Fix | Guard updates with a module lock. | Fixed 11edccd (no test: a thread race on the count cannot be produced on demand; the lock is shown by reading) |
| MV-n15 | Nit | `flythrough.poses_from` missing from `__all__` | Fix | Add it to `__all__`. | Fixed 41ccaab |
| MV-d1 | Minor | Viewer docs lack the archive cache location and growth; member syntax unverified | Document | State the cache directory and its growth in `docs/viewer.rst`; confirm it names the archive-member syntax and add it if absent. | Fixed with MV-M10 (f3d7771, the other agent's Archives section of viewer.rst names the member syntax, the cache directory and that nothing evicts it) |
| SG-C1 | Critical | `OGLC_hook` sets any `ParticleEmitter` field unbounded, including a local `texture` path | Fix | Whitelist authorable fields; drop or resolve `texture`, drop `externalURL`/`maxParticles`; clamp scale, density, rate, burst to field maxima; hostile-input test; bound `mirrorhooks` scale. | Fixed 36aa17c |
| SG-M1 | Major | One malformed hook, zone or MSFT_lod value aborts the whole glTF load | Fix | Shared log-and-fall-back number helper in water, zoning and lod readers; skip bad ids; catch factory exceptions in `HookRunner`; hostile-input tests. Covers ZON-M7's zone case. | Fixed 69e59f9 |
| SG-M2 | Major | `LOD.boundingVolume` stays cached for the first level drawn | Fix | Clear the cached volume in `show()` when the level changes, or bound the node by the union of all levels; add a test. | Fixed f63b296 |
| SG-M3 | Major | LOD level selection has no hysteresis, so threshold jitter flips levels | Fix | Add a `hysteresis` fraction (default about 0.1) to coverage and distance selection; test with coverage oscillating across a threshold. | Fixed f63b296 (`hysteresis` attribute, default 0.1) |
| SG-M4 | Major | MSFT_lod path skips skin and morph registration for the finest level | Fix | Call `_register_morph` and `_register_skin` in `_lod_node`, passing `node_index`; test with `RiggedSimple` wrapped in MSFT_lod. | Fixed ab5e85c |
| SG-M5 | Major | Streamed tile ground receives its model matrix in the wrong convention | Fix | Pass `model=m.T` as `MatrixTransform` does, or state and test `GroundPatch.model`'s convention; GL test reading back the sampled control-map texel. | Fixed 39bd94d (the uploader passes the transpose; a GL test reads back the layer a placed tile is drawn with) |
| SG-M6 | Major | Every ground tile re-uploads constant uniforms and rebinds five textures per frame | Fix | Move constants into a `ViewPrograms` `setup` callback; keep only per-draw matrices and sun per patch; ideally one begin/end for all ground per frame. | Fixed 39bd94d (constants set by a ViewPrograms setup callback per program form; per patch only placement, view, light and the texture binds) |
| SG-M7 | Major | Tileset-named files (zones, clumps, cards, meshes) joined without containment | Fix | Resolve through `Resolver` containment or a `tiles3d.fetch.beside()` rejecting absolute and `..` names and keeping URLs same-origin; test both. | Fixed 1d665f3 |
| SG-M8 | Major | Remote world's cover clumps and cards are opened as local files | Fix | Fetch species files through `fetch.read_bytes` or `_beside`; let `load_clump_glb` accept bytes; test with a served tileset. | Fixed 1d665f3 |
| SG-M9 | Major | `GroundCover` raises `ZeroDivisionError` at zero density | Fix | Return empty arrays from `_scatter` and `world_grid_scatter` when density is zero or less; add a test. | Fixed 97f90f9 (and 234a6a9: a density_scale or retuned radius set while standing still is scattered at the next update, which the "quality setting" use needs) |
| SG-m1 | Minor | `control_weight` assumes a square control map | Fix | Use `shape[1]` for u and `shape[0]` for v; refuse or resample non-square maps with a clear error. | Fixed 97f90f9 (each axis read by its own size; a non-square map is valid, so it is read rather than refused) |
| SG-m2 | Minor | Portal-face degenerate filter compares indices and removes nothing | Fix | Test for zero area or equal positions, or have `_portal_face` share the index; correct the comment. | Fixed dae49f6 |
| SG-m3 | Minor | `merged_mesh` normals wrong under non-uniform scale; mirrored instances inverted | Fix | Use the inverse-transpose for normals, swap index columns when det < 0, and document what `_merge` skips. | Fixed ff2ca33 (inverse transpose, winding swapped under det < 0, LOD finest level, Switch's chosen child, InstancedShape per placement; one pose test with bounds(); what is left out is documented) |
| SG-m4 | Minor | Stated `MSFT_screencoverage` not reconciled with levels actually built | Fix | Build the coverage list from surviving ids; check its length is levels or levels+1 and warn otherwise. | Fixed ab5e85c |
| SG-m5 | Minor | Screen-coverage definition (height) may differ from MSFT_lod's (area) | Investigate | Quote the MSFT_lod README definition in `gltf/lod.py`; convert if the spec means area. | Needs input (lod.rst corrected in f63b296: the README does not define coverage, and how the engine's height definition differs from Babylon.js's area) |
| SG-m6 | Minor | `ScreenCoverageLOD` discards measured centre, measures distance to origin `center` | Investigate | When `center` is unset and the radius is measured, take the measured centre too. | Fixed f63b296 (radius and center both unset: distance to the measured centre; the pass asks `distanceCentre()`) |
| SG-m7 | Minor | `mesh_bounds` ignores KHR_mesh_quantization | Investigate | Apply the normalization or dequantization to `min`/`max` before use, as the mesh decoder does. | Fixed ab5e85c (in `declared_bounds`, which also fixes the framing bounds in meshes.py) |
| SG-m8 | Minor | Shareable hook result built with the first referencing node's world matrix | Maintainer decision | Either document `world_matrix` as valid only for unshareable hooks or pass `world=None` to shareable ones; run unshareable hooks per instancing placement, or warn. | Fixed 92a9b04 (decided on correctness: a shareable material hook gets no world matrix; an unshareable one under EXT_mesh_gpu_instancing runs per placement, each copy placed on its own; documented) |
| SG-m9 | Minor | `GLTFScene.advance` looks up kinds in the global registry at advance time | Fix | Record each kind's `Registration` in `HookRunner` and store it with `hook_data`; consider a `registry=` argument to `load_gltf`. | Fixed 92a9b04 (registrations recorded per load, advance uses them; a per-load `registry=` argument was not added, the process-wide registry being the documented design) |
| SG-m10 | Minor | Zone naming a hook-replaced node controls a detached `Transform` | Investigate | Have `node_transform` return what stands in the slot, or warn when a zone names a replaced node. | Fixed 92a9b04 (zones resolve what stands in the slot; skins and animation keep the document's Transform) |
| SG-m11 | Minor | `imagebased` skips face validation, decodes eagerly, lets some errors escape | Fix | Validate face sizes, decode only referenced lights lazily, cache per image index, widen the guard to `Exception` with a warning. | Fixed 8dd4a91 (faces checked square, alike and halving; a light decoded when a scene or zone names it; each image decoded once; the guard was already widened in 69e59f9) |
| SG-m12 | Minor | `decode_data_uri` decodes before checking the size cap | Fix | Check `len(payload) * 3 // 4` against the cap before `b64decode`. | Fixed 942b27d |
| SG-m13 | Minor | Resolver private names renamed without aliases | Maintainer decision | Keep deprecated aliases for one release, or note the rename in the changelog; update `_default_cache_dir` users. | Needs input |
| SG-m14 | Minor | `GroundCover._told` swaps `_blocks` while a background scatter may write | Investigate | Guard `_blocks`/`_retired` with a lock, or a generation counter bumped in `_told` and checked before storing. | Fixed 97f90f9 (a scatter keeps the table it began with; one locked block counter) |
| SG-m15 | Minor | `BackgroundCompute` drops failed requests; unshut cover leaks its thread | Fix | Reset `_near_at`/`_far_at` on failure; hold the owner weakly or add `dispose`; document `shutdown()` in `docs/vegetation.rst`. | Fixed 97f90f9 (failures handed back through `failed` in drain and asked for again; the worker holds the cover weakly and a finalizer stops it; documented) |
| SG-m16 | Minor | `GroundCover.select` copies and uploads instance arrays every moving frame | Fix | Keep the cache sorted and upload once with shader-side fade/cut, or re-select only after moving a fraction of the fade band. | Fixed 97f90f9 (subsets chosen with a 1 m margin and re-chosen after 1 m of movement; the shader's live fade hides the margin) |
| SG-m17 | Minor | Without `clumpFarMesh` the mesh uploads twice and the inner disc draws twice | Fix | When near and far are the same mesh, build one node with the far fade window and no near overlay. | Fixed 97f90f9 |
| SG-m18 | Minor | `holes` set after the first draw does not change the drawn ground | Fix | Make `holes` a property that disposes and drops `_patch` so the mesh is re-cut on next draw. | Fixed 39bd94d (`SplatTerrain.holes` is a property; the replaced mesh is released at the next draw, on the GL thread; `TilesTerrain.holes` delegates to it) |
| SG-m19 | Minor | Sun direction documented backwards in ground and canopy code | Fix | Correct the comments and docstrings; rename to `light_direction`. | Fixed 39bd94d (comments and docstrings corrected in ground, splat, heightfield, cover, clumps; the local renamed; the public `sun` parameters keep their names, documented as the direction the light travels) |
| SG-m20 | Minor | `splat.py` keeps dead imports, duplicate constants and a stale docstring | Fix | Import constants from `ground.py`, delete unused imports, rewrite the module docstring. | Fixed 39bd94d |
| SG-m21 | Minor | `PBRMesh._render_legacy` changes cull and texture-env state without restoring | Fix | Route culling through `set_cull_state`; restore the texture env mode in `renderPost`. | Fixed 44a73c5 (culling through the pass's record in the legacy path, which also fixes a mirrored solid mesh; the compatibility pass resets the record per view; apply_winding_cull and IndexedPolygons go through it too. The GL_MODULATE texture env is GL's initial mode and the only one the engine uses, so it is left set) |
| SG-m22 | Minor | mypy reports three errors in imagebased, cover and field | Fix | Annotate `image` as `Image.Image`; fix `children` assignment per other `Group` subclasses or fix the `ChildrenTypedField` stub. | Fixed 50e2944 (the three ChildrenTypedField errors, and the others like them in tilesterrain.py) and 8dd4a91 (imagebased's image typed; mypy was already clean there) |
| SG-m23 | Minor | Seven new `type: ignore`s carry no reason | Fix | Use explicit-length tuple types, a `Protocol` with `copy()` for `Varied`, and give any remaining ignore a reason. | Fixed 92a9b04 (shapes, zone, zones, varied; imagebased in 8dd4a91; zoning's was already gone) |
| SG-m24 | Minor | Hooks API typed loosely (`Any` returns and fields) | Fix | `@overload` `register`/`registered`, type `HookContext` fields, split the two factory return shapes, use `set[str]`. | Fixed 92a9b04 |
| SG-m25 | Minor | Presets moved to Nodes: renamed kwargs, lost hashability, mutable global presets | Maintainer decision | Record renames in the changelog; choose between mutable shared presets and frozen ones (e.g. `style_for` returning `.varied()` copies). | Fixed 1bd7ba4, 03a21f9 (decided: a loaded document's water gets its own copy of the style, so documents never alias the presets; code-built sheets keep sharing presets as documented. The conversion to Nodes follows the maintainer's own "scene state is a node" rule, so the renames and lost hashability stand; openglcontext has no changelog file to record the renames in) |
| SG-m26 | Minor | Water hook does not validate `medium` or `depth` | Fix | Clamp depth to non-negative; map unknown media to `WATER` with a warning, as the mirror hook does. | Fixed 69e59f9 |
| SG-m27 | Minor | `LoadPool` may run `prepare` on a worker; slow fetches starve loads | Investigate | Call `prepare` eagerly for known kinds at import or context start; consider a per-fetch timeout or separate network pool. | Fixed b615b32 (a load that submits loads prepares them with `background.prepare`, and the Inline does so for textures, shaders and panoramas; a preparation reached on a worker is logged. Starvation: a stalled fetch is bounded by the resolver's existing 30 s per-operation timeout; documented, with a separate LoadPool for loads that should not wait. PASS-m17 (0f2b557) was the SystemExit case, a different defect) |
| SG-n1 | Nit | Docstrings break writing rules: history, bold leaders, maxims, selling | Fix | Run `/ai-isms --fix` over the listed files; move the Beacon narrative to the roads plan. | Fixed 5f21b22 (every listed passage rewritten by hand; the Beacon account moved to plans/GLISTEEL-STRUCTURE-COLLISION.md; background.py's bold leaders went with b615b32; the ai-isms scanner reports nothing in those files) |
| SG-n2 | Nit | `loaders/assets.py` reformatted wholesale to double quotes in a feature commit | Maintainer decision | Either restore the package's single-quote style in `assets.py` or keep the reformat as is. | Needs input |
| SG-n3 | Nit | `octahedralHemi` reads the string `"false"` as true | Fix | Parse string booleans as the mirror hook does. | Fixed c69d33b |
| SG-n4 | Nit | glTF 2.1 `shapes` handling targets an unratified version; `read_shape` unchecked | Investigate | Cite the draft followed or keep it behind the extension; check `size` has three positive components. | Needs input (the `read_shape` part -- three positive sizes -- was already done in 69e59f9) |
| SG-n5 | Nit | `_warn_if_displaced` prints the node name twice and reads oddly | Fix | Format the name once and rewrite the message plainly. | Fixed ab5e85c |
| SG-n6 | Nit | `_index_emitters` is O(built x declared) | Fix | Use an `id(emitter)` to index dict. | Fixed ab5e85c |
| SG-n7 | Nit | MSFT_lod listing its own node or a root empties the scene | Investigate | Warn and ignore self-references in `alternative_ids`. | Fixed ab5e85c |
| SG-n8 | Nit | `load_clump_glb` index path accepts negatives, raises `IndexError` not `KeyError` | Fix | Range-check `_mesh_index` and raise `KeyError` as the name path does. | Fixed 97f90f9 |
| SG-n9 | Nit | `GroundCover.species`/`VegetationField.species` writable but never re-read | Maintainer decision | Make `species` read-only, or rebuild the rungs when it changes. | Needs input |
| SG-n10 | Nit | `CoverRung.retune` uses another class's private state; lambda properties | Fix | Give the renderer a public retune method and replace the lambda properties with `@property` definitions. | Fixed 97f90f9 (also a real defect: `retune` called `_commit_constants()` with no arguments on a drawn node, and skipped it for single-mesh species; `refresh_constants`/`ViewPrograms.resend`) |
| SG-n11 | Nit | `scenegraph/terrain/relief.py` imports from the loaders layer | Fix | Move `fbm` to a neutral module such as `arrays` or `noise`. | Fixed 39bd94d (`OpenGLContext.noise`, top level so that procedural.py stays numpy-only rather than importing the terrain package's GL modules) |
| SG-n12 | Nit | `wait_for_loads` can wait up to twice the timeout | Fix | Share one deadline between the runtime and cover waits. | Fixed 39bd94d |
| SG-n13 | Nit | Octahedral docstring says the arithmetic is in one place; `pbr.vert` copies it | Fix | Say the Python and GLSL copies are tested against each other. | Fixed 5ca00aa |
| SG-n14 | Nit | `PBRMesh.unchecked` keys on program ids, which GL reuses | Fix | Clear the entry when a program is deleted, or key on the program object rather than its id. | Fixed 44a73c5 (checked per shader-program set, held weakly) |
| SG-d1 | Minor | `docs/untrusted.rst` omits `OGLC_hook`, `OGLC_zone` and `EXT_lights_image_based` | Fix | State what a downloaded file can make built-in kinds do, give the limits, and point to `OPENGLCONTEXT_GLTF_HOOKS=0`. | Documented 87a45d0 |
| SG-d2 | Minor | `docs/gltf.rst` "never names code" ignores resource paths; kinds table omits `mirror` | Fix | Qualify the guarantee for resources such as particle `texture`; add `mirror` to the engine-kinds table. | Documented 87a45d0 |
| SG-d3 | Minor | `merged_mesh`, `merged_by_material`, `grid.Patches`, `world_noise` are public but undocumented | Fix | Document the functions and exports in the assets and vegetation docs. | Documented ff2ca33 (merged_mesh and merged_by_material in docs/gltf.rst; Patches and world_noise in docs/vegetation.rst; ScatterBlocks and world_grid_scatter were already described there) |
| SG-d4 | Minor | No installed demo for ground cover, MSFT_lod/impostors, holes/bores, zones/IBL | Fix | Add installed `oglc-*` demos, at least for MSFT_lod and ground cover, covering the documented use cases. | Fixed 0a48375, ba67172, ed1ed79 (oglc-lod: LOD, ScreenCoverageLOD, MSFT_lod read from a file, hysteresis; oglc-cover: species, clumps, beds, control-map mask, holes cut live, density; oglc-zones covers zones/IBL (DOC-13). Impostors are left to the pack gallery, since an octahedral atlas is baked by the editor. Tutorials tests/lod_hall.py and tests/cover_meadow.py with baselines in the reference_images submodule, 206636a) |
| CP-1 | Critical | Resolver refuses GitHub's cross-origin redirect, so no shipped pack downloads | Fix | Give content packs their own redirect policy: allow https to public hosts, refuse private addresses and non-https; test with two servers; push `content-v1` before release. | Fixed a9a8616 (pushing the `content-v1` release: Needs input) |
| CP-2 | Major | No installed-version record; URL-keyed cache fails for ever on a changed digest | Fix | Write an install record (key, sha256, url) and compare it in `root_for`; evict and re-download once on `DigestMismatch`; key cache by digest; new URL per rebuild. | Fixed 99b0959 (install record compared in root_for; cached archive evicted and fetched once more on DigestMismatch; cache stays keyed by URL, since the record plus the retry make a rebuild under the same URL work) |
| CP-3 | Major | Extraction not atomic: partial pack counts as installed, concurrent installs interleave | Fix | Extract into a sibling `.partial-<pid>` directory, write the install record, `os.replace` under a lock file; marker last for `within`; remove partial on failure. | Fixed 99b0959 (helper ed05f72) |
| CP-4 | Major | `tar.getmembers()` enumerates everything before entry-count and size checks | Fix | Iterate members with running count and size, stop at the first overrun, and bound decompressed bytes read during enumeration. | Fixed faec2f1 |
| CP-5 | Major | Plain http accepted and sha256 optional, so packs can be replaced in transit | Fix | Require https unless the pack carries a sha256, or require https outright; consider a digest for every pack in a shipped registry. | Fixed 35f2158 (https, or http with a sha256 or on this machine) |
| CP-6 | Major | Documented `requires` field is never parsed or enforced | Maintainer decision | Either validate with `SpecifierSet` and exclude non-matching packs by application version, with tests, or remove the field and its documentation. | Fixed 35f2158 (implemented: validated as a PEP 440 specifier, `ContentPack.readable_by`, `catalog.for_version`; adds `packaging>=22` as a dependency, see notes) |
| CP-7 | Major | A registry that fails validation is kept and breaks every `load_registries()` | Fix | Validate the bundle from a temporary extraction and keep it only on success; remove the kept file and `.unpacked` directory on failure. | Fixed 285c6de |
| CP-8 | Major | `publish.install(within=X, replace=True)` deletes the whole owning pack | Fix | With `within`, remove only the needed pack's listed files or refuse `replace`; stop ignoring removal errors; warn when the root is outside `store.root`. | Fixed 99b0959 |
| CP-9 | Major | Downloads and cache hits hold the whole archive in memory, twice on fetch | Fix | Stream chunks into the `mkstemp` file with cap and cancel checks, hash while streaming, and only touch the file on a hit. | Fixed 998e682 (streamed to the cache file; hit not read; hashing while streaming not done, the digest is read once from the file) |
| CP-10 | Major | Namespace partition bypassable on case-insensitive or dot-stripping filesystems | Fix | Casefold namespace and directory for comparison and path; forbid trailing `.` and Windows reserved names in `_SEGMENT` and `_NAMESPACE`. | Fixed 35f2158 |
| CP-11 | Minor | Registry fields coerced instead of type-checked | Fix | Check `isinstance` per field (bool, list of key strings, int not bool, str); test marker segments with `PurePosixPath(marker).parts`. | Fixed 35f2158 |
| CP-12 | Minor | Refreshed registry bundle extracted over the old one; stale files survive | Fix | Extract into a fresh temporary directory and swap it in; skip extraction when the bundle digest matches the last one recorded. | Fixed 285c6de |
| CP-13 | Minor | `fetch_registry` and `resolver.fetch_url` accept `file://` and plain http | Fix | Check `is_url()`, or require https, at the top of `fetch_url` and in `fetch_registry`. | Fixed a9a8616 (fetch_url refuses non-http(s)), 35f2158 (fetch_registry wants https, http only on this machine) |
| CP-14 | Minor | `missing_base` returns a flat list, losing each pack's `within` | Fix | Return (pack, within) pairs, or add a helper that fetches a base pack's closure with the right `within`. | Fixed 0a30f0c (`fetch.base_fetches` pairs; FetchJob takes pairs; missing_base kept for consent, see notes) |
| CP-15 | Minor | Cancel ignored during extraction; job state never shows failure; traceback dropped | Fix | Pass the cancel predicate into `extract` per member; set `state` to done, failed or cancelled; log with `exc_info`. | Fixed faec2f1, 99b0959 (cancel during extraction), 0a30f0c (job state done/cancelled/failed; failure logged with traceback) |
| CP-16 | Minor | Tar `data` filter missing on older 3.10/3.11 patch releases the floor allows | Fix | Check `hasattr(tarfile, 'data_filter')` once and raise a clear error, or raise the Python floor. | Fixed faec2f1 (clear refusal on an interpreter without tarfile filters) |
| CP-17 | Minor | `archive.extract` uncapped by default; twig-bb relies on it and has its own zip extractor | Fix | Default `max_bytes` to `MINIMUM_UNPACKED`, `None` only when explicit; move twig-bb's zip and nested-pk3 handling onto `archive.extract`. | Fixed faec2f1 (engine default cap); twig-bb's own zip extractor: see notes |
| CP-18 | Minor | `archive.write` stores symlinks as links and drops symlinked directories | Fix | Refuse or dereference symlinks; write to a temporary file and `os.replace` it. | Fixed faec2f1 (symlinks refused by name; archive written atomically) |
| CP-19 | Minor | `packs.json` is not in the wheel and nothing in the engine reads it | Maintainer decision | Either ship it in package-data with a consumer such as `oglc-view --pack openglcontext/gallery`, or move it beside `release-assets.py` as build output. | Fixed 3cf58a6 (shipped in package data, consumer `oglc-view --pack`) |
| CP-20 | Minor | `publish.push` treats any `gh release view` failure as missing; no option terminator | Fix | Distinguish not-found from other failures; pass absolute paths or place them after `--`. | Fixed d902a1e |
| CP-21 | Minor | Refused-redirect error message carries the signed CDN URL | Fix | Pass the target through `safe_url` with the query stripped before building the message. | Fixed a9a8616 |
| CP-22 | Minor | Documented single exception family misses `http.client.InvalidURL` | Fix | Validate URL host and port in `_check_where_it_lands`; have the resolver raise a dedicated size exception and catch that. | Fixed 35f2158 (URL parsed in the catalogue; `resolver.ResourceTooLarge`; HTTPException reported as IOError) |
| CP-23 | Minor | `release-assets.py` staging directories reused, so stale files enter archives | Fix | `shutil.rmtree` the staging directory before staging; fail when `CREDITS.txt` is missing. | Fixed 72b1deb (engine's release-assets.py; forest and glisteel scripts: see notes) |
| CP-24 | Nit | Registry download cap and unpack cap use different constants | Fix | Drive both caps from one constant. | Fixed 285c6de |
| CP-25 | Nit | `progress`/`cancel` typed `Any`; size formatting duplicated and prints `0 MB` | Fix | Use `resolver.Progress` and `resolver.Cancel`; share one size formatter that handles small sizes. | Fixed 3824e37 |
| CP-26 | Nit | `with_needed` is O(n·m) with `pop(0)` and linear lookups | Fix | Build a key-to-pack dict once and use a deque or index. | Fixed 35f2158 |
| CP-27 | Nit | Preview and escape checks use `abspath`, not `realpath` | Fix | Use `realpath` in `_resolve_preview` and `_refuse_escape`. | Fixed 35f2158 |
| CP-28 | Nit | Only the asset-cache leaf gets mode 0700; store directories use the umask | Fix | Apply consistent directory modes, or rely on and state the per-user app-data parent. | Fixed 3824e37 (store root created 0700) |
| CP-29 | Nit | Content-pack docstrings break the writing rules (glosses, insisting, bold leader) | Fix | Rewrite the listed sentences in `store.py`, `fetch.py`, `catalog.py` and `pack.py` as plain statements. | Fixed 3824e37, c03f376 |
| PH-01 | Major | Threaded manager loses a removed body's `'end'` events and prunes the subscription | Fix | In `_remove_body`, under the world lock, publish the world's contact log through a new omi_physics `ThreadedSimulation.flush_events()`; add a threaded removal test. | Fixed e10a78b, with omi_physics 010ef09 (`ThreadedSimulation.flush_events`) |
| PH-02 | Major | Late subscription receives every event logged since reporting was switched on | Fix | Drain the contact log whenever reporting is on and dispatch only if draining; test that a late subscriber gets no old events. | Fixed e10a78b |
| PH-03 | Major | Render-thread code mutates a threaded world without the world lock | Fix | Add a manager `_mutate()` hook taking the world lock for `report_hit` and `_report`; take trigger points from the snapshot; document walker `with_world()`; qualify hit ordering. | Fixed e10a78b, with omi_physics 4ef553c (TriggerEvent.point, re-entrant world lock) |
| PH-04 | Minor | mypy error: `apply_zones` given an ndarray for `Sequence[float]` | Fix | Widen `apply_zones`' `position` to `ArrayLike`. | Fixed 8c0b006 (before this work; `apply_zones` already takes `ArrayLike`, mypy clean) |
| PH-05 | Minor | Zone gain and reverb stick when the zone list becomes empty | Duplicate of ZON-M9 | Fixed with ZON-M9: call `apply_zones` with no zones once when they go, or unconditionally. | Fixed d45de01 (ZON-M9 is the same defect: it can be recorded "Fixed with PH-05") |
| PH-06 | Minor | Threaded manager writes a stale snapshot onto a body in a reused slot | Fix | Record the snapshot version each body was added at and skip it in `_write` until reached, or publish under the world lock in `add`/`remove`. | Fixed e10a78b |
| PH-07 | Minor | A dome taller than its diameter floats above the ground | Fix | Clamp `lift` to at most `radius` or use a capsule; state the rule in `Prop.shape` and add a test. | Fixed 73f5543 |
| PH-08 | Minor | `remove` and `body_for` are linear in the body count | Fix | Keep bodies in an insertion-ordered dict and a transform-id-to-body map maintained in `add`/`remove`. | Fixed e10a78b |
| PH-09 | Minor | No tests for threaded removal events, late subscriptions or zone audio | Fix | Add the tests named under PH-01, PH-02 and PH-05. | Fixed e10a78b (threaded removal and late-subscription tests), d45de01 (zone audio tests) |
| PH-10 | Nit | `_handles` duplicates `world.handle_of` | Fix | Drop `_handles`; have `handle()` consult `world.handle_of` then `_retired`. | Fixed e10a78b |
| PH-11 | Nit | Class attributes declared after `__init__` in the physics managers | Fix | Move `steps_on_this_thread` and `RETIRED_KEPT` to the top of the class body. | Fixed e10a78b |
| PH-12 | Nit | Per-frame import of `apply_zones` in `audio.scene.update` | Fix | Import `apply_zones` at module level. | Fixed d45de01 |
| PH-13 | Nit | Prose in `PropColliders._stand` argues; `gltf_world` comment repeats docstring | Fix | Use the plainer `_stand` wording from the finding; drop the repeated inline comment. | Fixed 73f5543 |
| BIN-1 | Major | Tk and wx demos never open in quad view; `views` default overrides class attribute | Fix in engine | Default `ViewerOptions.views` to None and pass it through so `multiViewArrangement` applies; add a unit test for a `'quad'` subclass. | Fixed 02d72e5 |
| BIN-2 | Major | `profile_view` sets the env var too late; profiles with error checking on | Fix | Assign `OpenGL.ERROR_CHECKING = False` again (or a supported runtime switch); correct the comment; add a subprocess test. | Fixed afc43fa |
| BIN-3 | Major | `omi_audio` pin is below the API the engine calls (`set_rate`, `reverb`) | Fix | Release a new omi_audio version and pin `omi_audio>=` it, coordinated with `tools/release.toml`. | Fixed f9d10f3, with omi_audio b7bf4e6 (version 0.4.0a1); publishing omi_audio 0.4.0a1 is Needs input |
| BIN-4 | Major | `oglc-audio-demo` uses flat single-colour plastic | Fix | Dress the yard with engine `surfaces` PBR materials as `CollisionYard` does and set `OPENGLCONTEXT_RENDERER=pbr`. | Fixed f79eef5 |
| BIN-5 | Minor | Audio demo shows `box_gain`, not zones, and no reverb | Fix | Make the cave and stream `Zone` nodes with `ZoneAudio` and a cave `ZoneReverb`; keep `box_gain` in docs as the no-zone option. | Fixed f79eef5 |
| BIN-6 | Minor | Kinematic door driving and trigger occupancy hand-rolled in the demo | Fix in engine | Add a kinematic mover helper and a trigger-occupancy object to the physics API, test them, and have the yard call them. | Fixed b44ad79, with omi_physics 897ff2a and 7be263a (`KinematicMover`); occupancy is `CollisionEvents.occupancy()` |
| BIN-7 | Minor | Per-frame demo logic sits in an uncovered windowed class | Fix in engine | Add `ViewPlatform.forward()` for the five ray sites; move frame pacing, dt clamp, volume and muffle into the yards. | Fixed acf95bc (`ViewPlatform.forward()` at all five sites), b44ad79 (`events.framestep.FrameStep`), f79eef5 (volume and muffle in `AudioYard`) |
| BIN-8 | Minor | Demos step physics from the wall clock, so captures vary | Fix | Use `systemtime.systemTime()` in both demos, as the tutorial does. | Fixed b44ad79, f79eef5 |
| BIN-9 | Minor | `oglc-audio-demo` picks a GL backend at import, even for `--help` | Fix | Move the context class into `main()` or behind a factory, as `physics_events_demo` does. | Fixed f79eef5 |
| BIN-10 | Minor | `--video-fps 0` and non-positive `--video-seconds` not rejected by the parser | Fix | Use a positive-number `type=` for both options, as `_parse_size` does. | Fixed 4a575fb |
| BIN-11 | Minor | `gltf_regression` rederives the cache key and reads whole files | Fix | Use `resolver.fetch_to_cache` or `cached_path`; make the default cache directory public if tools need it. | Fixed 4ddb329 (`resolver.default_cache_dir` made public) |
| BIN-12 | Minor | `oglc-mirrors --help` opens the demo instead of printing usage | Fix | Add an `argparse.ArgumentParser(...).parse_args()` in `main()`. | Fixed 3e50a13 |
| BIN-13 | Minor | `physics.rst` repeats a sentence; `viewer.rst` omits `archive#member` sources | Fix | Delete the repeated sentence (with DOC-11); add an Archives subsection to `viewer.rst`. | Fixed f3d7771 (viewer.rst Archives section); repeated sentence with DOC-11 |
| BIN-14 | Nit | Trailing "which is what" glosses, one bolded, in `oglc-view` docstring and help | Fix | Rewrite both as plain statements, per the suggested wording. | Fixed 4a575fb |
| BIN-15 | Nit | `--capture-image` and `--capture` are two separate options with one dest | Fix | Declare one argument with both spellings so help shows a single entry. | Fixed 4a575fb |
| BIN-16 | Nit | `--video-seconds` also sets unrecorded fly-through length; help omits it | Document | Say so in the `--video-seconds` help, or add a `--fly-seconds` option. | Documented 4a575fb (help and recording.rst) |
| BIN-17 | Nit | Perception wording ("the game hears") in `physics_events_demo` | Investigate | Confirm it breaks the rule; if so, name the mechanism: "each strike calls the subscriber registered for it". | Fixed 2da1648 |
| DOC-01 | Major | `physics.rst` links a `physics_events` tutorial that is never generated | Fix | Add `physics_events` to the Physics paths in `docbuild/tutorials.py` and commit its screenshot. | Fixed d694709 |
| DOC-02 | Major | README changelog stops at 3.0.0a1 | Fix | Add entries for 3.0.0a5 and the coming release, one item per feature linking its page. | Fixed ae6b376 |
| DOC-03 | Major | Content-pack base-pack example drops `within`, so users are asked every start | Fix | Show a per-base-pack fetch passing `within=`; pair packs with their `within` if needed; reword the sentence after the example. | Fixed 0a30f0c |
| DOC-04 | Minor | `MANIFEST.in` names HTML docs that no longer exist | Maintainer decision | Either include the `.rst` pages, `conf.py`, `_ext`, `_templates` and static files, or drop docs from the sdist deliberately. | Fixed 2092628 (the sdist keeps carrying the documentation, now its rst source, conf, extensions, images, docbuild; the alternative, dropping docs from the sdist, is in the notes) |
| DOC-05 | Minor | `passes/_flat.py` docstring points at a removed HTML tutorial | Fix | Point at the `shadow_1` tutorial (`tests/shadow_1.py`) or its published URL. | Fixed feac428 |
| DOC-06 | Minor | Workspace environment cannot build the docs (missing mermaid, pyyaml) | Fix | Add `OpenGLContext[docs]` to the workspace sync, or put the docs requirements in the dev extra. | Fixed da84d1d (dev extra includes docs; docs names pyyaml; the workspace venv needs a `uv sync` to pick it up) |
| DOC-07 | Minor | `reflections.rst` texture-unit threshold off by one | Fix | Say "fewer than 32 texture units". | Fixed feac428 |
| DOC-08 | Minor | Blender panel description omits Reflectance | Fix | Add Reflectance (`reflectance`) to the panel list. | Fixed feac428 |
| DOC-09 | Minor | Packaging multicall example lacks `import sys` | Fix | Add `import sys` in `packaging.rst` and the `multicall.py` docstring. | Fixed ee585ca |
| DOC-10 | Minor | `environment.rst` misses `OPENGLCONTEXT_CONTENT` and misstates reading rules and a default | Fix | Add the row; restate the reading rule; route flags through `env_flag` or document non-empty; correct the baseline default. | Fixed add8ec6 (the three flags now go through env_flag; page restated) |
| DOC-11 | Minor | A sentence is printed twice on `physics.rst` | Fix | Delete the second copy. | Fixed ee585ca |
| DOC-12 | Minor | `structure.rst` lacks multiview and `__pyinstaller` rows and page links | Fix | Add a `multiview` row linking multiview.rst and extend the "Described in" cells. | Fixed 5104af3 |
| DOC-13 | Minor | Zones have no front-page entry, demo command or tutorial | Fix | Add a Features item linking zones; ship a small zone demo or name a scene, and make it a tutorial. | Fixed 08f7632 (`oglc-zones` command, `ZoneCourt` scene tested without GL, tutorial `tests/zones_demo.py`, Features entry, zones.rst demo section); baseline 31a552a in tests/reference_images |
| DOC-14 | Minor | WebM audio documented as decodable; only Ogg Opus is read | Maintainer decision | Either remove WebM from both tables and `omi_audio/formats.py`, or add a WebM demuxer to omi_audio. | Needs input |
| DOC-15 | Minor | `water.rst` says four `wave_time` writes and transmission; code differs | Fix | Say "five", and "a blended PBR material with an index of refraction of 1.33"; fix `tests/water_demo.py` too. | Fixed 5afe744 |
| DOC-16 | Minor | Zones loader list omits `EXT_lights_image_based` | Fix | Add `EXT_lights_image_based` to the list in `zones.rst`. | Fixed 2b16950 |
| DOC-17 | Minor | API docstrings produce docutils errors in the generated reference | Fix | Widen the two tables, add blank lines before indented blocks, close literals; consider `-W` for non-API pages in CI. | Fixed acf95bc, recorded in d45c1d5 (the fixes were swept into another agent's commit from the shared index; see notes) |
| DOC-18 | Nit | `multiview.rst` overstates `QuadView.frame` and the per-view axis triad | Investigate | Confirm the `QuadView.frame` claim, then reword both sentences. | Fixed dd659f3 (triad reworded; the QuadView.frame sentence is true: fit_limits then frame_box through ViewSet.frame) |
| DOC-19 | Nit | `physics.rst` understates `TerrainWalkMixin` overrides and names a missing command | Fix | Correct the override count, use `python -m OpenGLContext.bin.physics_cook`, and qualify the `auto` trimesh rule. | Fixed ee585ca |
| DOC-20 | Nit | `OGLC_hook` has no extension specification page or schema | Fix | Add `extensions/OGLC_hook.rst` and a schema of each kind's parameters; link it from the four pages. | Fixed 1172e7e (extensions/OGLC_hook.rst and schema, tested against the code) |
| DOC-21 | Nit | `oglc-deb` options list incomplete; reproducibility overstated | Fix | List the missing options and state that reproducible builds need `SOURCE_DATE_EPOCH`. | Fixed 7853728 |
| DOC-22 | Nit | Blender demo worlds named by checkout-only paths | Fix | Say "in a checkout", or publish both worlds as content packs. | Fixed cded500 |
| DOC-23 | Nit | `viewer.rst` omits options, misnames backends in an error, lacks two formats | Fix | Complete the `ViewerOptions` list, correct the error wording, add `.obj.gz` and `#member` archives to the table. | Fixed ea1a871 |
| DOC-24 | Nit | Vegetation block size stated as fixed 32 metres | Investigate | Confirm the far-rung sizing, then say "at least 32 metres wide, wider for the far rungs". | Fixed 9f08c1a |
| DOC-25 | Minor | Writing-rule violations: README bold leaders and six toolkits, bold openers, glosses | Fix | Rewrite the README list with plain leaders and add Tk; remove bold paragraph openers in roads.rst and testing.rst; recast the glosses. | Fixed ae6b376 (README), 8f15e33 (roads, testing, reflections glosses, physics), 99b0959 (contentpacks gloss); environment.rst's italic *Presentation.* cell openers left, see notes |
| DOC-26 | Major | LOD page's demo command cannot work | Duplicate of CP-1 | Fixed with CP-1, plus pushing the `content-v1` release. | Fixed with CP-1 (pushing `content-v1`: Needs input, see CP-1) |
| DOC-27 | Minor | `contentpacks.rst` documents `requires`, http and stable URLs beyond what code gives | Document | State the limits now; bring the page in line once CP-2, CP-5 and CP-6 are fixed. | Fixed 35f2158, 0a30f0c (page matches the code now: requires enforced, http rule, rebuilt packs under one URL) |
| LIB-D1 | Major | `multiple-choice` schedule spends 20 failed draws per initial edge before stopping | Fix | Size the failure budget to the live pool since the last success, or fall back to one exhaustive pass and stop; add a bounded-work test. | Fixed 22a3388 (opengl_decimate) |
| LIB-D2 | Major | Open surfaces reduce to nothing, contrary to README, `survey` floor and tests | Maintainer decision | Either add the boundary link condition in both reducers to keep patches, or let patches vanish and correct README Limits, `Survey.floor`/`reducible`, `test_survey.py` and GALLERY.md. | Fixed 2f3c128 (opengl_decimate). Decided per correctness: both reducers keep an open piece's last triangle (boundary form of the link condition), matching Survey.floor, README and tests; README Limits corrected for closed pieces |
| LIB-D3 | Major | `locked` takes welded-point indices, not the caller's vertex indices | Fix | Map `locked` through `vertex_point` inside `_Engine`; add `locked_points` if welded points are needed; at minimum document zero-tolerance welding and expose the map. | Fixed b8424fb (opengl_decimate): locked maps through vertex_point |
| LIB-D4 | Minor | `import opengl_decimate.survey as m` yields the function, not the module | Fix | Rename the `survey` and `simplify` modules (or the functions) so package attributes do not shadow submodules. | Fixed 00aa189 (opengl_decimate): modules renamed reduction.py and floors.py |
| LIB-D5 | Minor | Default `normal_noise` 1e-3 is too small to condition the 3x3 solve | Fix | Scale the determinant test by the added noise, or test the smallest eigenvalue, or raise the default; test a planar fan solves. | Fixed 3780f81 (opengl_decimate): determinacy is the reciprocal condition number |
| LIB-D6 | Minor | Compiled loop is quadratic in vertex valence (ring, duplicate-face, link scans) | Fix | Deduplicate rings with a per-point epoch stamp array and reuse it for the duplicate-face test. | Fixed 8868dbe (opengl_decimate): epoch stamps, sorted pair duplicate test, qsort; 16k-spoke cone 4.4 s -> 0.12 s |
| LIB-D7 | Minor | Docs say normals accumulate per point; code uses smoothing groups | Fix | Rewrite the `options.py` and API.md passages to describe smoothing groups and point to `crease_angle`. | Documented 4acb2c4 (opengl_decimate) |
| LIB-D8 | Minor | New option, result field and accelerator switches missing from API.md and README | Fix | Add rows for `drop_components_below` and `dropped_away`, and a section on `OPENGL_DECIMATE_NO_ACCEL` and `native.ACCELERATED`. | Documented 4acb2c4 (opengl_decimate) |
| LIB-D9 | Minor | Empty result lacks `NORMAL` although `recompute_normals` was set | Fix | Add an empty `(0, 3)` float32 `NORMAL` in the empty-surface return when `recompute_normals` is set. | Fixed 7f3f32a (opengl_decimate) |
| LIB-D10 | Minor | `survey()` skips input validation and cannot take weld or drop options | Fix | Call `simplify._check` and accept `options: SimplifyOptions \| None` so weld and drop settings apply. | Fixed f0071d9 (opengl_decimate) |
| LIB-D11 | Minor | `seam_share` counts edges onto seams, not the atlas boundary its docstring claims | Fix | Correct the docstring, or add a separate count of edges whose sides disagree on texture coordinates. | Fixed 842b416 (opengl_decimate): docstrings and API.md say it counts edges leading onto a seam |
| LIB-D12 | Minor | `lock_seams` compares only copy counts, so seam points may merge across charts | Investigate | Reproduce with a one-triangle-wide chart; if confirmed, require multi-copy contractions to run along a seam edge. | Fixed 842b416 (opengl_decimate): reproduced (5 torn triangles on a one-quad-wide chart); lock_seams now requires a different chart on each side of the edge, both reducers |
| LIB-D13 | Minor | MESH-DECIMATION plan contradicts itself on M4, coverage and the accelerator package | Fix | Update the status line, milestone table and M4 text, and qualify the 100% coverage claim. | Documented 06a355c (openglcontext plans) |
| LIB-D14 | Minor | Near-singular optimal placement is unbounded and can move a vertex far away | Investigate | Confirm on a curved crease; then reject optima far from the edge midpoint or use a truncated-SVD solve anchored there. | Fixed 3780f81 (opengl_decimate): far optima (up to 266 edge lengths on a noisy tube) confirmed from the solve, not observed reaching a contraction; both reducers now drop a minimiser further from the midpoint than the edge length |
| LIB-D15 | Minor | `certify` counts components removed by `drop_components_below` as deviation | Fix | Certify against the input without the dropped faces, or report both figures. | Fixed 0d594f3 (opengl_decimate) |
| LIB-D16 | Minor | `CollapseSequence.__post_init__` runs a per-contraction Python loop on every `simplify` | Fix | Compute winner and loser inside the compiled loop and return them with the log. | Fixed 878ab24 (opengl_decimate): compiled ends_given_up; 0.28 s -> 0.005 s on 500k triangles |
| LIB-D17 | Nit | Float index arrays are silently truncated to integers | Fix | Refuse a non-integer index dtype with a `DecimateError`. | Fixed f0071d9 (opengl_decimate) |
| LIB-D18 | Nit | CI comments misstate Rosetta and the platform count across five libraries | Fix | Reword to "Intel Macs cannot run an arm64 wheel, so they need one built on x86_64"; correct the platform count in `test.yml`. | Fixed 87885eb (opengl_decimate, also adds the macos-15-intel test row), a2da7e5 (opengl_extrusions), ebb2872 (simpleparse), c9dc8ff (pyvrml97), 41c2100 (omi_physics), 01586baa (pyopengl: the same comment in accelerate-manylinux.yml) |
| LIB-D19 | Nit | Several opengl_decimate passages break the workspace writing rules | Fix | Run `/ai-isms --fix` over `src/` and the workflows; move measurement narrative to GALLERY or plans. | Fixed 17c991b (opengl_decimate): prose only, no test possible; workflow wording is LIB-D18 |
| LIB-D20 | Nit | `REVIEW.md` work ledger is tracked at the library root | Fix | Move it into `plans/` or the engine's plan. | Fixed e807475 (opengl_decimate): moved to plans/REVIEW-0.1.0a1.md |
| LIB-D21 | Nit | Compiled path narrows indices to int32 without a range check | Fix | Refuse meshes whose indices or incidence counts overflow int32 with a `DecimateError`. | Fixed f0071d9 (opengl_decimate) |
| LIB-D22 | Nit | Grid search rebuilds a boolean mask through `np.isin` | Fix | Use the mask `found == np.repeat(closest, sizes)` directly. | Fixed c1a2e3f (opengl_decimate): refactor, no behaviour change, so no Red test; covered by the grid-vs-scan tests |
| LIB-D23 | Nit | Native heap starts at 1,024 entries; sequence fields typed `Any` | Fix | Size the heap from the edge count and give `origin` and `_moved*` their array types. | Fixed 62e5d58 (opengl_decimate): sizing and typing, no behaviour change, so no Red test; the capacity agreement test still grows the queue |
| LIB-D24 | Nit | NumPy and compiled reducers treat an infinite price differently | Fix | Test `isfinite` in both reducers. | Fixed 28d61bc (opengl_decimate) |
| LIB-D25 | Minor | opengl_decimate has no CHANGELOG for a large feature release | Fix | Add a CHANGELOG covering the new reducer, options, fields and switches. | Fixed c59be76 (opengl_decimate): CHANGELOG.md for 0.2.0a1, shipped in the sdist and linked from the README |
| LIB-P1 | Minor | `ContactTracker.ignored` keys can outlive pairs dropped for cleared flags | Investigate | Confirm the re-flag case; then discard those keys from `ignored` where `update` drops unflagged pairs. | Fixed 010ef09 (omi_physics) |
| LIB-P2 | Minor | A raising contact listener leaves the world part-way through a step | Maintainer decision | Either collect the exception, finish the step and re-raise, or log and continue; document which applies. | Fixed 010ef09 (omi_physics): settled by correctness - the step (or removal) finishes, the first listener exception is raised after it, later ones are logged |
| LIB-P3 | Minor | omi_physics 0.4.0 adds public API with no changelog | Fix | Add a changelog covering contact events, sensors, ray filters and trigger filters. | Fixed c15bdaf (omi_physics) |
| LIB-P4 | Nit | `ContactEvent.point` and `normal` are views into one shared per-step array | Fix | Copy each row into its own array, or document that the arrays are shared. | Fixed 010ef09 (omi_physics) |
| LIB-P5 | Nit | Stale `last_batch` is detected by comparing lengths | Fix | Stamp the batch with `step_count` and compare that. | Fixed 010ef09 (omi_physics) |
| LIB-P6 | Nit | Ray `filter` keyword shadows the builtin and is undocumented | Fix | Document the keyword in README and docs; consider a non-shadowing name. | Documented c15bdaf (omi_physics): keyword kept as `filter`, the name of the CollisionFilter it takes; no function uses the builtin |
| LIB-P7 | Nit | `world.alive()` scans the free-slot list | Fix | Keep a boolean liveness array. | Fixed 010ef09 (omi_physics); a cost change has no Red, liveness covered by a new test |
| LIB-P8 | Nit | Ray bundle test allocates `(R, T, 3)` temporaries for widely spread bundles | Document | State the memory cost of wide bundles over dense meshes in the docstring. | Documented c15bdaf (omi_physics) |
| LIB-P9 | Nit | Adding a listener fills `contact_log` although nothing drains it | Fix | Deliver to listeners without retaining events in `contact_log` when no log consumer exists. | Fixed 010ef09 (omi_physics): `PhysicsWorld.log_events` |
| LIB-P10 | Nit | `ContactLog.dropped` miscounts when a drain races on another thread | Fix | Compute the dropped count under the same lock as `extend`. | Fixed 010ef09 (omi_physics); the stress test did not reproduce the race before the fix (the window is a few bytecodes), fixed by reading |
| LIB-A1 | Minor | Reverb comb delays share factors in samples; docs claim they do not | Fix | Choose mutually prime delays in samples per rate (primes nearest the targets), or drop the claim. | Fixed 86797e2 (omi_audio) |
| LIB-A2 | Minor | Reverb omits Schroeder's series allpass diffusers | Fix | Add two allpasses of about 5 ms and 1.7 ms, vectorised the same way as the combs. | Fixed 86797e2 (omi_audio) |
| LIB-A3 | Minor | Wet reverb signal is not normalised against comb gain and can clip | Fix | Scale by (1-g) or an RMS-normalising constant and state the headroom in the docs. | Fixed 86797e2 (omi_audio): RMS-normalised combs, headroom stated in MIXING.md |
| LIB-A4 | Nit | omi_audio CHANGELOG uses bold-leader bullets; README Limits has a defensive preface | Fix | Rewrite the bullets as plain definitions and drop the preface. | Fixed b7bf4e6 (omi_audio) |
| LIB-A5 | Nit | Reverb delay lines can decay into float32 denormals | Investigate | Confirm the slowdown on x86; then flush lines below about 1e-30 to zero. | Fixed 86797e2 (omi_audio): subnormals confirmed in the lines (1e-45); no slowdown measurable on this AMD CPU, flushed anyway |
| LIB-V1 | Minor | `builtOn` gains a dead weak reference for every transient path | Fix | Give each weak reference a removal callback, or compact the list at twice its live count. | Fixed bad831d (pyvrml97); NodePath.children had the same accumulation and is fixed with it |
| LIB-V2 | Nit | Cache lookup inlined twice instead of making `getHolder` fast | Fix | Make `CACHE.getHolder` cheap enough and call it at both sites. | Not a defect: getHolder is already two dictionary reads; the 30 ns the inlined sites save (77 against 107 ns a lookup, measured) is the Python call itself, which no change to getHolder removes, on the per-path-per-frame path |
| LIB-V3 | Nit | Non-transforming path returns its parent's cached matrix array | Fix | State "do not modify the returned array" in the docstring, or return a read-only view. | Documented bad831d (pyvrml97): docstring says not to modify the answered array; a read-only array was not chosen because 26 callers across the workspace were not audited for in-place use |
| LIB-V4 | Nit | Untracked git worktree sits inside pyvrml97's `.claude/` | Fix | Remove the worktree once merged, or add `.claude/` to `.gitignore`. | Fixed 7b476bc (pyvrml97): `.claude/` ignored. The worktree is clean and its branch is at develop's tip, so it holds no unmerged work; it was left in place (removing it is `git worktree remove .claude/worktrees/frame-overhead`, the maintainer's call) |
| LIB-W1 | Minor | pyopengl-video docstrings narrate history and use a bold lead-in | Fix | Keep the reason (a zero duration makes the container length zero) in the present tense. | Fixed 7149e50 (pyopengl-video) |
| LIB-W2 | Minor | Rounded default frame duration drifts against exact timestamps | Investigate | Confirm the drift; then derive durations from the next timestamp or carry the remainder, using `frame_duration` only for the last frame. | Fixed 7149e50 (pyopengl-video): drift confirmed (1000 ticks over 4000 frames at 24000/1001) |
| LIB-W3 | Nit | Zero frame-rate numerator raises `ZeroDivisionError` in `frame_duration` | Fix | Raise `EncoderError` instead. | Fixed 7149e50 (pyopengl-video) |
| LIB-W4 | Nit | `test_mp4` asserts on the private `writer._durations` | Fix | Assert on the written container's durations instead of the private attribute. | Fixed 7149e50 (pyopengl-video) |
| ED-M1 | Major | Leaf tiles meshed with zero grain; the collided landscape has grain | Fix | Build leaf relief at the leaf's nominal error, or pass nominal error to `content()` and write `leaf_error` only to the tileset; test leaf mesh against `landscape().height_fn`. | Fixed f41ac70 (openglcontext-editor) |
| ED-M2 | Major | `bake_card` leaves z unscaled, so plants deeper than tall are clipped | Fix | Scale z into [-1, 1] by the plant's depth extent; choose card width from x extent or horizontal radius explicitly; test a plant deep in z. | Fixed 8bc393d (openglcontext-editor) |
| ED-M3 | Major | Loose stone puts 8 MB of JSON into `tileset.json` extras | Fix in engine | Write stones as a binary npz asset with only name and count in extras; the engine, not glisteel, reads it and builds `PropColliders`. | Fixed 434ba80 (engine props_table, loaders/tiles3d/props.baked_props, PropColliders.baked), 73fa5f8 (openglcontext-editor), 20cc2bf and 0f56a4f (glisteel) |
| ED-M4 | Major | Blender add-on manifest missing from the wheel; `--package` fails | Fix | Add `blender/openglcontext_lod/blender_manifest.toml` to package-data and test it loads through `importlib.resources`. | Fixed 01151a3 (openglcontext-editor) |
| ED-M5 | Major | Zones call omi_audio synth functions no release carries; no floor declared | Fix | omi_audio half is a duplicate of BIN-3. For the opengl_decimate half, bump its version and raise the editor's floor together. | omi_audio half fixed 064b328 (openglcontext-editor); the opengl_decimate half is not in this assignment |
| ED-M6 | Major | Bake and game derive bore openings with different parameters | Fix in engine | One engine function deriving bore openings from the world record (profile, approach, ground), called by bake and game; or record mouth outlines in the world. | Fixed 08da2ef (engine roadworks.BoreCut: the cut as a road record, openings() for every run), 91a9737 (openglcontext-editor: bore_cut() recorded as roads[].bores and used for the tiles), 42135d9 (glisteel: collider cut from the recorded BoreCut) |
| ED-M7 | Major | `bake_probes` sets process env, reads engine privates, loop untestable | Fix in engine | Engine API on the zones pass returning zone lights, scheduling in a plain object, options instead of `os.environ`; module only writes files. | Fixed c1a4439 (engine: passes/zonebake.py bake_zone_lights + ZoneBakePlan, zonepass.zoneCaptureSettled/zoneLightImage, Context.renderer), 7446988 (openglcontext-editor) |
| ED-M8 | Major | glTF read and written by hand in four places beside engine loader/writer | Fix in engine | Read plants through the engine loader or pygltflib; move sidecar reader and zone/emitter writer into the engine; write LOD glb via `GLTFWriter`. | Fixed: plant reader 42b2a66 (openglcontext-editor, engine load_gltf); LOD chain 542cfcf (engine GLTFWriter.add_lod, external buffers, LODAsset in loaders/gltf/lodasset.py) + 5ae19e4 (openglcontext-editor); zone/emitter writer b563ce0 (engine GLTFWriter.add_zone) + e55f0df (openglcontext-editor). The Blender add-on keeps its own writer (it cannot import the engine) |
| ED-M9 | Major | `--canopy` help describes light; the engine reads tree closure | Fix | Rename metavars to LEAST MOST, describe as the engine does, cite `SplatTerrain.canopy_cover` for units. | Fixed 42b2a66 (openglcontext-editor) |
| ED-M10 | Major | `oglce-gallery` accepts a stale glB when Blender fails | Fix | Remove target before running, require the `WROTE:` line from `build.py`, and make `with_sky` replace an existing sky. | Fixed 8b50e29 (openglcontext-editor) |
| ED-M11 | Major | Editor HEAD uses old species dataclass API; engine HEAD has nodes | Fix | Commit the working-tree rename with or right after the engine change, noting the coupling in the message. | Fixed c7a5de6 (openglcontext-editor) |
| ED-m1 | Minor | Poly Haven cache treats any non-empty file as complete | Fix | Write to a temporary name and `os.replace` into place. | Fixed f585d88 (openglcontext-editor) |
| ED-m2 | Minor | Downloaded `.gltf` URIs can read arbitrary local files into assets | Fix | Confine buffer URIs through `Resolver` as `polyhaven._under` and `meshlod.asset` do. | Fixed 42b2a66 (openglcontext-editor) |
| ED-m3 | Minor | Poly Haven slugs used unvalidated in cache paths | Fix | Check slugs against a pattern before joining them into paths. | Fixed f585d88 (openglcontext-editor) |
| ED-m4 | Minor | Redirects followed without re-checking the allowed host | Investigate | Confirm redirects can leave the allow-list; if so, re-check the host on each redirect. | Fixed d0ebb74 (engine AllowedHosts/open_url), f585d88 (openglcontext-editor) |
| ED-m5 | Minor | Two MSFT_lod writers disagree on the coarsest level's coverage | Maintainer decision | Options: coarsest culled below `0.5/2**i` (`meshlod.asset`) or never culled with 0.0 (`msftlod.coverage_series`); align both with the engine reader. | Fixed 542cfcf (engine halving_coverage, add_lod default), 5ae19e4 (openglcontext-editor): settled by the engine reader and the Blender add-on, which both end the series at 0 |
| ED-m6 | Minor | `write_chain(embed_coarsest=0)` writes an invalid glB buffer 0 | Fix | Emit no zero-length buffer 0, or give it a valid BIN chunk. | Fixed 542cfcf, 5ae19e4 (openglcontext-editor) |
| ED-m7 | Minor | `LODAsset` reads any non-float component type as uint32 | Fix | Handle each component type, or raise on unsupported ones. | Fixed 542cfcf (engine LODAsset decodes every component type, refuses unknown), 5ae19e4 (openglcontext-editor) |
| ED-m8 | Minor | `_rewrite` matches zones to nodes by position; reruns append images | Investigate | Confirm against foreign documents; key by node name and replace earlier images. | Fixed 7446988 (openglcontext-editor): keyed by zone node name; a re-bake replaces a zone's light and its images |
| ED-m9 | Minor | `KHR_audio_emitter` use (wav MIME, emitters in OGLC_zone) is outside the extension | Document | State the departure in the engine's OGLC_zone spec. | Documented b563ce0 (OGLC_zone spec) |
| ED-m10 | Minor | Impostor bake names `BLENDER_EEVEE_NEXT`, removed in Blender 5 | Fix | Pick whichever EEVEE identifier the running Blender offers. | Fixed 79056d6 (openglcontext-editor) |
| ED-m11 | Minor | `tomllib` used under a Python 3.10 floor | Fix | Fall back to `tomli` on 3.10, or raise `requires-python`. | Fixed 01151a3 (openglcontext-editor): tomli fallback and conditional dependency |
| ED-m12 | Minor | Card bake renders through the engine's test fixture window | Fix | Use `EGLContext` as `probes.py` does and check framebuffer completeness before drawing. | Fixed 8bc393d (openglcontext-editor): framebuffer completeness checked; hidden_window kept (the engine's cross-platform bare-context helper; EGLContext is a Linux-only full context class) |
| ED-m13 | Minor | `--no-cards` manifest names card files it did not write | Fix | Set `card` only when a card is baked. | Fixed 42b2a66 (openglcontext-editor) |
| ED-m14 | Minor | Variant and species basenames collide across assets | Investigate | Confirm collisions; key cards and `cover.json` by slug and variant, and keep species paths distinct. | Fixed 42b2a66 (openglcontext-editor) |
| ED-m15 | Minor | Grain produces no bands at the shipped defaults | Document | State in the README the depth and field resolution at which grain appears. | Documented f41ac70 (openglcontext-editor) |
| ED-m16 | Minor | Tree depth configured in world and bake with no agreement check | Investigate | Confirm the mismatch in practice; have the bake take depth from the world. | Fixed a653588 (openglcontext-editor): ProceduralWorld.bake() bakes at the world's own depth and refuses another |
| ED-m17 | Minor | Portal funnel height taken from nearest road, possibly another stretch | Investigate | Confirm on a hairpin or spiral; measure from the portal's own run. | Fixed 91a9737 (openglcontext-editor): the portal funnel measures from the nearest point of the portal's own bore run |
| ED-m18 | Minor | A bore across a closed circuit's seam becomes two bores | Investigate | Confirm; join runs across the index 0/n-1 seam on closed circuits. | Fixed 91a9737 (openglcontext-editor): RoadPath.runs joins a run across a closed circuit's start; portals, bore openings and lamps use it |
| ED-m19 | Minor | `flatten` centres a plant on its vertex mean | Fix | Use the bounding-box centre, as `meshlod.chain.bounding_sphere` does. | Fixed 42b2a66 (openglcontext-editor) |
| ED-m20 | Minor | Stone docs say both "no collider" and solid dome | Fix | Correct the `procedural.py` docstring to match the dome colliders. | Fixed 73fa5f8 (openglcontext-editor) |
| ED-m21 | Minor | `SHIPPED` and `COVER` are shared mutable module-level nodes | Investigate | Confirm mutation leaks; build them in a function, or document `varied()` as the way to change one. | Fixed 3e7a6a8 (openglcontext-editor): shipped_trees()/default_cover() build fresh nodes per call |
| ED-m22 | Minor | `rewrap` rasterises per triangle in Python with nearest sampling | Fix | Vectorise rasterisation and use filtered sampling where the atlas is denser than the source. | Fixed 46c199c (openglcontext-editor) |
| ED-m23 | Minor | Tile content boxes closed on both sides, duplicating boundary items | Investigate | Confirm; make the package-wide box test half-open across stones, props and scatter. | Fixed 73fa5f8 (openglcontext-editor): BoundingBox.holds is half-open, used by stones, props, signs, gantry and instance layers; the root cell is widened one ulp on its high faces |
| ED-m24 | Minor | `with_sky` embeds JPEG as base64 data URI in a glB | Fix | Store the image in the BIN chunk through a bufferView. | Fixed 8b50e29 (openglcontext-editor) |
| ED-m25 | Minor | Public editor APIs typed as `Any` | Fix | Use the existing concrete types (`Scatter`, `StoneLayer \| None`, `Holes \| None`, `HeightFn`, a `Literal`). | Fixed cf35d34 (openglcontext-editor) |
| ED-m26 | Minor | `_SEARCH` comment describes something else | Fix | Say it is the executable name searched on PATH. | Fixed 01151a3 (openglcontext-editor) |
| ED-n1 | Nit | Bold-leader lists and bold-sentence paragraphs in docstrings | Fix | Rewrite as plain definitions per the workspace rule. | Fixed f585d88, 42b2a66, 5ae19e4, 01151a3, 73fa5f8, 37a3fc6 (openglcontext-editor): every passage the finding names |
| ED-n2 | Nit | History note ("Measured on Beacon") in a structures docstring | Fix | Keep the present-tense reason and drop the narrative. | Fixed 37a3fc6 (openglcontext-editor) |
| ED-n3 | Nit | History phrasing in species docstrings | Fix | Remove the "before there were sets" wording. | Fixed 3e7a6a8 (openglcontext-editor) |
| ED-n4 | Nit | Commentary on the fact in polyhaven docstrings | Fix | State the rate limit and attribution facts plainly. | Fixed f585d88 (openglcontext-editor) |
| ED-n5 | Nit | Anecdote and character verbs in rewrap docstrings | Fix | Remove the anecdote and describe the unwrapper's output. | Fixed 46c199c (openglcontext-editor) |
| ED-n6 | Nit | Comment explaining a `raise` sits after it | Fix | Move the comment above the `raise`. | Fixed f585d88 (openglcontext-editor) |
| ED-n7 | Nit | `import io` inside `bake()` | Fix | Move to module imports. | Fixed 42b2a66 (openglcontext-editor) |
| ED-n8 | Nit | `del path` silences an unused parameter | Fix | Drop the parameter. | Fixed 5ae19e4 (openglcontext-editor) |
| ED-n9 | Nit | `LevelReport` exposes `_share` as a constructor argument | Fix | Make the field public or compute it privately. | Fixed 2498953 (openglcontext-editor) |
| ED-n10 | Nit | Console scripts use both `oglce-` and `oglc-` prefixes | Maintainer decision | Options: rename `oglce-gallery` to `oglc-gallery`, or move the editor's bake commands to `oglce-`. | Needs input |
| ED-n11 | Nit | Docstring summaries narrate instead of naming the return | Fix | Name what `fetch`, `bake` and `main` return. | Fixed f585d88 (polyhaven.fetch), 42b2a66 (plants.bake, bin/plants.main) (openglcontext-editor) |
| ED-n12 | Nit | Per-kind stone filtering re-reads attributes per stone per kind | Fix | Keep a kind index array beside `_plan`. | Fixed 73fa5f8 (openglcontext-editor) |
| ED-n13 | Nit | `wav_bytes` lives in the editor although omi_audio owns audio | Fix in engine | Move `wav_bytes` into omi_audio and import it from there. | Fixed cc3f824 (omi_audio Clip.wav_bytes), e55f0df (openglcontext-editor) |
| ED-d1 | Minor | README omits zones, places, ambient sound and probe bake | Fix | Add README sections for them and document `ProceduralWorld.places`. | Fixed a17e096 (openglcontext-editor) |
| ED-d2 | Minor | No README section for `oglc-bake-plants`, `cover.json`, Poly Haven | Fix | Add a section and list `oglc-bake-plants` in the Layout table's `bin/` row. | Fixed a17e096 (openglcontext-editor) |
| ED-d3 | Minor | "What a bake writes" lists only `world.json` | Fix | Add `zones.gltf`, `audio/*.wav`, `probes/`, the stones record and `terrain.drawn`. | Fixed a17e096 (openglcontext-editor) |
| ED-d4 | Minor | pyproject and blender module point to `docs/blender.html`; file is `.md` | Fix | Point both references at `docs/blender.md`. | Fixed 01151a3 (openglcontext-editor) |
| ED-d5 | Minor | README says funnel keeps `PORTAL_SOIL`; code never reads it | Fix | Describe the funnel with `tunnel.clearance + tunnel.portal_border`, or make the code use `PORTAL_SOIL`. | Fixed a17e096 (openglcontext-editor) |
| ED-d6 | Nit | README calls stone module constants knobs on the world | Fix | Call them module constants, or make them `ProceduralWorld` fields. | Fixed f41ac70 (openglcontext-editor) |
| ED-t1 | Minor | No round-trip test of `ZonesLayer.document()` through `ZoneReader` | Fix | Add a test reading the written document back with the engine's `ZoneReader`. | Fixed b563ce0: tests/unit/test_gltf_zone_writer.py reads every written zone back through the loader's ZoneReader; the editor's test_world_places already loads ZonesLayer's document through the loader |
| ED-t2 | Minor | Interleaved, normalized and strip branches of `plants._accessor` untested | Fix | Add tests for interleaved, quantized/normalized accessors and strip primitives. | Fixed 42b2a66 (openglcontext-editor) |
| GAME-X1 | Major | release-assets.py build, install, push and parser copied across three games | Fix in engine | Add `publish.main(spec, argv)` owning flags, install, push and `bundle_registry`; each script keeps only `declare()`. Move `refuse_pointers` into `archive.write()`. | Fixed 4253ba8 (publish.Release/publish.main/bundle_registry; engine's own release-assets.py), 3cb8d1a (openglcontext-forest), 0f74834 (twig-bb), b7144f9 (glisteel); LFS check in archive.write b4d9a22 |
| GAME-X2 | Major | Three copies of the pack-or-wheel resolver, each bound at import | Fix in engine | Add `contentpacks.Application` with `registry()`, `store()`, per-call `base_directory()` and `ensure_base()`; games read paths at use time. Add a download panel to `OpenGLContext.ui`. | Fixed f358383 (contentpacks.Application, AssetLibrary with a function root); games moved onto it in their own commits (see GAME-F1, GAME-G3, GAME-T2, GAME-T3) |
| GAME-G1 | Major | Driving and Downloads screens never close; panels stack up | Fix | Close the panel in `chose`, `cancel` and `start` with an `answered` guard; name and drop the track screen; replace an existing `downloads` panel; add screen tests. | Fixed 471f1bc (glisteel) |
| GAME-G2 | Major | Failed or stopped download never shown; job cleared before rebuild | Fix | Keep the last finished job or pass it to the rebuild; add a Stop button wired to `FetchJob.cancel()`; refresh the library when a job finishes. | Fixed 471f1bc (glisteel; engine ContentScreen 43dc4fb, job reopening 2bffa2f) |
| GAME-G3 | Major | Base pack documented as fetched before the menu; nothing fetches it | Fix | Fetch the base pack with consent before a session is built and resolve `ART` lazily (GAME-X2); until then correct the README. | Fixed ab0314c (glisteel: first-run fetch with consent before any world is built; ART resolved at each load) |
| GAME-G4 | Major | `_note_a_touch` hold-off drops later, separate traffic contacts | Fix | Decrement `_touched` once per physics step, as `_watch_for_a_bump` does; test two touches separated by a gap. | Fixed 2dcc045 (glisteel) |
| GAME-G5 | Major | Journal stretches open at run end are lost; refusals merge across passes | Fix | Add `Autopilot.flush(session)` called from `_mark_the_end` and `_pull_out`; record the start station; merge flip-flopping reasons into one stretch. | Fixed 66d72f7 (glisteel) |
| GAME-G6 | Minor | `drive_it(journal=...)` returns a report with no marks | Fix | Use a tee recorder that forwards each mark to both the journal and the report. | Fixed 1017d6d (openglcontext), 34bfeef (glisteel) |
| GAME-G7 | Minor | `diagnose` sets the private `Traffic._rng` | Fix | Add `Traffic.reseed(seed)`. | Fixed 34bfeef (glisteel) |
| GAME-G8 | Minor | Hitting a parapet, portal or tree makes no sound | Fix | Call `self.sound.hit(closing)` in `_watch_for_a_bump`, rate-limited by the same hold-off. | Fixed 2dcc045 (glisteel) |
| GAME-G9 | Minor | Stuck recovery teleports a player pushing against something on purpose | Maintainer decision | Options: require contact with something static or nothing within `following_gap` ahead, or offer recovery through the HUD for a human driver. | Fixed 6e4c1be (glisteel): decided by the correctness rule rather than asked - a car queued behind another (within 20 m up its lane) is not recovered; a car pushing on the world with nothing in front still is. Offering recovery through the HUD instead of doing it is left as a possible design change, not needed for correctness |
| GAME-G10 | Minor | Remembered preference overrides an explicit `--control` naming the default | Fix | Default `Options.control` to None and resolve it after preferences are read. | Fixed cf4ba16 (glisteel) |
| GAME-G11 | Minor | `Preferences.save()` can raise `OSError` inside a button handler | Fix | Catch the error, log it and keep the in-memory choice. | Fixed cf4ba16 (glisteel) |
| GAME-G12 | Minor | `content.py` parameter shadows `store`, reached via `globals()` | Fix | Rename the parameter (for example `into`) or the function (`default_store`). | Fixed f54d819 (glisteel) |
| GAME-G13 | Minor | Orphaned comment line in driver.py; `PASSED_BY` comment narrates a bug | Fix | Delete the orphan line and drop the history from the `PASSED_BY` comment. | Fixed 55fe664 (glisteel) |
| GAME-G14 | Minor | `traffic.PASSING_SECONDS` duplicates `driver.PASS_SECONDS` | Fix | Import one from the other or move both into a shared constants module; drop the agreement test. | Fixed 55fe664 (glisteel) |
| GAME-G15 | Minor | `_pulled_off` and `_room_beside` use different car widths | Fix | Use `self.kind.width` in both. | Fixed 55fe664 (glisteel) |
| GAME-G16 | Minor | Nearest-point queries scan the whole centreline at physics rate | Fix | Windowed search around a per-caller previous index, full scan only on teleport; compute `road_speed` once in `controls`. | Fixed f52f33e (openglcontext: windowed search in RoadCourse/Tracker), eb87f4f (glisteel: Course uses it; road_speed once per step) |
| GAME-G17 | Minor | Refusal-stretch logic implemented twice, in `Autopilot` and `StandIn` | Fix | One small `Stretch` recorder object used by both classes. | Fixed 66d72f7 (glisteel) |
| GAME-G18 | Major | Content download consent and progress UI lives in both games | Fix in engine | Add `OpenGLContext.ui.contentscreen` taking registry and store and returning a panel; glisteel and twig-bb call it. | Fixed 43dc4fb, 2bffa2f, 62f1ecd (OpenGLContext.ui.contentscreen.ContentScreen); glisteel calls it in 471f1bc, twig-bb in 0a651ab |
| GAME-G19 | Minor | Vehicle sound synthesis lives in glisteel | Fix in engine | Move synthesis into `omi_audio` or the scene nodes into `OpenGLContext.audio`; glisteel supplies its constants. | Fixed 36ab752 (omi_audio: omi_audio.vehicle), ea7e869 (openglcontext: OpenGLContext.audio.vehicle.VehicleSoundtrack), b6a9a9f (glisteel: sound.py is the car's tuning over them) |
| GAME-G20 | Minor | Runtime road-course queries live in glisteel `Course` | Fix in engine | Add an engine `RoadCourse` query object beside `road.py`, hosting the GAME-G16 windowed search. | Fixed f52f33e (openglcontext: OpenGLContext.scenegraph.roadcourse.RoadCourse, docs/roads.rst#roadcourse), eb87f4f (glisteel) |
| GAME-G21 | Minor | glisteel carries its own in-memory recorder and atomic JSON writer | Fix in engine | Add `telemetry.Keeping` and a `userpaths.write_json_atomically` or settings-document helper. | Fixed 1017d6d (openglcontext: telemetry.Keeping, telemetry.Tee), cf4ba16 and 34bfeef (glisteel: preferences and records write through OpenGLContext.atomicfiles, diagnose uses Keeping/Tee) |
| GAME-G22 | Major | glisteel docstrings and comments narrate history and journal anecdotes | Fix | Run `/ai-isms --fix` over glisteel; move measurements and journal evidence into `plans/DRIVING-AND-PLACE.md`. | Fixed 84e56c9 (glisteel), with the sound.py docstring in b6a9a9f; journal evidence moved to plans/DRIVING-AND-PLACE.md section 8; ai-isms scan of glisteel/ clean |
| GAME-G23 | Minor | glisteel README omits diagnose, telemetry, preferences; two wrong claims | Fix | Add a "Recording and diagnosing a run" section, correct the impacts and first-run claims, convert bold leads to plain headings or prose. | Fixed 6548223 (glisteel); the impacts claim was corrected with GAME-G8 (2dcc045) and the first-run claim by the GAME-G3 agent (ab0314c) |
| GAME-G24 | Minor | Every release-assets.py run rewrites the shipped registry | Fix | Write the shipped registry only with `--push` or `--write-registry`; local installs use a registry under `--into`. | Fixed 4253ba8 (registry written under --into; shipped one only with --push/--write-registry), applied in 3cb8d1a (openglcontext-forest), 0f74834 (twig-bb), b7144f9 (glisteel) |
| GAME-G25 | Nit | Markdown relative link in an in-game copyright string | Fix | Strip the Markdown link when `_credits()` copies the credit into `packs.json`. | Fixed cb056ab (glisteel) |
| GAME-G26 | Nit | Three blank lines after `passable_count` in traffic.py | Fix | Remove the extra blank lines. | Fixed 55fe664 (glisteel) |
| GAME-G27 | Minor | `Session.restart()` keeps journal hold-offs and driver state | Fix | Reset `_bumped`, `_sampled`, `_touched` and the driver's `passing`, `_refusing` and `_crawled_for` on restart. | Fixed 2dcc045, 66d72f7 (glisteel) |
| GAME-G28 | Minor | Bore mouth mask does not wrap across a closed circuit's start | Investigate | Check whether structures can span station 0; if so, build the bore run as a wrapped span. | Fixed a168995 (glisteel): openglcontext-editor's structure_runs() does split a structure across a closed circuit's start into two, so it is reachable |
| GAME-G29 | Nit | Dead `getattr`/`hasattr` fallbacks for `width_at` in the protocol | Fix | Call `width_at` directly everywhere and drop the fallbacks. | Fixed 55fe664 (glisteel) |
| GAME-E1 | Minor | Recipe validation truncates floats given for integer settings | Fix | For `kind is int`, refuse a float that is not integral. | Fixed e1d2bf1 (glisteel-editor) |
| GAME-E2 | Minor | glisteel-editor README says there is no splitter; bold-leader list | Fix | Remove the splitter limitation and rewrite the limitations list without bold leaders. | Fixed 2645089 (glisteel-editor) |
| GAME-E3 | Minor | `--no-probes`, `--no-places` and zone probes missing from the README | Fix | Document the flags and the bake's GPU requirement, including for `glisteel/release-assets.py`. | Documented 2645089 (glisteel-editor), 3a860fe (glisteel) |
| GAME-E4 | Minor | Bake date in `world.json` makes release archives date-dependent | Fix | Take the date from `SOURCE_DATE_EPOCH` when set, or leave it out of the packed manifest. | Fixed e1d2bf1 (glisteel-editor), 3a860fe (glisteel) |
| GAME-E5 | Nit | `WHEEL_BUTTONS` redefined although the engine exports it | Fix | Import `OpenGLContext.events.mouseevents.WHEEL_BUTTONS`. | Fixed e1d2bf1 (glisteel-editor) |
| GAME-E6 | Minor | `WORLD_SETTINGS` restates `ProceduralWorld` parameters in the game editor | Fix in engine | Have `ProceduralWorld` declare a `SETTINGS` table in openglcontext-editor and have `recipe.py` read it. | Fixed c3bcb71 (openglcontext-editor: ProceduralWorld.SETTINGS), 92091a9 (glisteel-editor: recipe.WORLD_SETTINGS built from it) |
| GAME-F1 | Critical | First forest run from the wheel cannot find its art | Fix | Resolve asset paths at use time or fetch before importing `scene`; test import with an empty store then install and build paths. Engine fix is GAME-X2. | Fixed 725ab76 (openglcontext-forest) |
| GAME-F2 | Minor | `fetch_art` downloads 66 MB unasked; network failure is a traceback | Fix | Prompt with a `--yes` for scripts, catch fetch errors, and print the `OPENGLCONTEXT_CONTENT` hint. | Fixed 20e4c89 (openglcontext-forest; engine ask_on_console/console_progress in f358383, 55ca54c) |
| GAME-F3 | — | Pointer to the release-assets and content duplication | Duplicate of GAME-X1 | See GAME-X1 and GAME-X2. | Fixed with GAME-X1 (3cb8d1a, openglcontext-forest) |
| GAME-F4 | Nit | `--reinstall` README sentence contradicts itself, in all three games | Fix | Use "`--install` keeps a pack that is already installed; `--reinstall` replaces it with the one just built." | Fixed 3cb8d1a (openglcontext-forest), 0f74834 (twig-bb), b7144f9 (glisteel); the engine docs and script in 4253ba8 |
| GAME-F5 | Nit | History in forest configuration and workflow comments | Fix | Drop the "57 LFS pointers reached PyPI" narrative from pyproject, `refuse_pointers` and the workflows. | Fixed 3cb8d1a (openglcontext-forest) |
| GAME-F6 | Minor | Git LFS pointer check is local to the forest | Duplicate of GAME-X1 | Fold `refuse_pointers` into `OpenGLContext.contentpacks.archive.write`. | Fixed b4d9a22 (archive.write refuses LFS pointers), 3cb8d1a (openglcontext-forest drops its own check) |
| GAME-d1 | Minor | Forest README omits the 66 MB first-run download and offline behaviour | Document | State in the README that a first run downloads 66 MB and what happens offline, with the `OPENGLCONTEXT_CONTENT` route. | Documented 20e4c89 (openglcontext-forest README, "The first run") |
| GAME-T1 | Critical | Legacy adoption moves the player's downloads into any cache_dir store | Fix | Adopt only for the default per-user store or a legacy tree under the same root; never move into a caller root; test legacy tree untouched. | Fixed a6c8b26 (twig-bb) |
| GAME-T2 | Minor | Legacy adoption runs as an import side effect | Fix | Resolve the asset root lazily and run adoption from the application's start-up path. | Fixed 0a651ab (twig-bb: download.adopt_on_start() from twig-bb/twig-bb-fetch start-up; store() and import write nothing) |
| GAME-T3 | Minor | twig-bb base pack documented as fetched; nothing fetches it | Fix | Fetch the base pack before the first match and resolve `ASSETS` lazily (GAME-X2), or correct the README. | Fixed 0a651ab (twig-bb: art resolved per use; first-run fetch with consent when neither pack nor package copy is present) |
| GAME-T4 | Nit | `release-assets.py install()` gives `AttributeError` on a missing entry | Fix | Check the `pack_for_key` result and raise a message naming the key. | Fixed 0f74834 (twig-bb: install() is gone; publish.main installs from the entries the build wrote) |
| GAME-T5 | Minor | Level target short name resolves only in the twig-bb namespace | Investigate | Confirm added registries serve maps; if so keep the full key quoted, or shorten only `twig-bb/` keys. | Fixed d309076 (twig-bb: valid but latent, since the game offers only its own registry; targets keep the whole key for another namespace, and a registered whole key parses) |
| GAME-T6 | Nit | `CONTENT_SUBDIR` and `LEGACY_CONTENT` share one value | Fix | Keep one constant, or make the distinction between the two explicit. | Fixed 0a651ab (twig-bb: CONTENT_SUBDIR removed; purge() clears the store's packs and LEGACY_CONTENT) |
| GAME-T7 | Nit | History in twig-bb docstrings | Fix | Rewrite the art.py, download.py and fetcher.py docstrings in the present tense. | Fixed 0a651ab (twig-bb) |
| GAME-M1 | Major | Touches recorded while the marble is lost destroy it on respawn | Fix | Clear `_touched` and `_last_touches` in `destroy()`, `_begin_fall()` and `_respawn()`, or ignore events unless ACTIVE; add the reproduction as a test. | Fixed da2d769 (marble-demo) |
| GAME-M2 | Major | `world.contact_log` grows to 65 536 events and is never drained | Fix in engine | Give omi_physics listener delivery without logging (`log_events=False`); meanwhile drain the log once per frame in `MarbleGame.advance`. | Fixed in engine: omi_physics 010ef09 (`log_events`), openglcontext e10a78b (the manager drains every frame) and 4ee44f4 (the manager keeps no log until a subscription); marble-demo f2ea92f holds it with a test |
| GAME-M3 | Minor | Listeners set world-wide persist reporting; lever fires on any body | Fix | Filter on the marble's index in `struck`; scope persist reporting per body if omi_physics can. | Fixed f2ea92f (marble-demo): the lever answers only the marble. Persist reporting stays world-wide (omi_physics has no per-body persist); under the 'flagged' reporting marble-demo uses it covers only the flagged marble's and paddles' pairs. A reset also left a thrown paddle lying over for good; fixed in the same commit |
| GAME-Q1 | Minor | openglcontext-qt pyproject comment names the wrong release | Fix | Make the comment name 3.0.0a5, the contentpacks release the floor requires. | Fixed f7b7321 (openglcontext-qt) |
| GAME-Q2 | Minor | Pointer shape stale after capture release | Duplicate of MV-M11 | Invalidate `_cursorShown` in the engine when pointer capture changes state. | Fixed with MV-M11 (7b8de6d) |
| GAME-Q3 | Nit | Insisting test docstring; untyped `CURSOR_SHAPES` class attribute | Fix | Rewrite the test docstring plainly and annotate `CURSOR_SHAPES` as `ClassVar[dict[str, str]]`. | Fixed f7b7321 (openglcontext-qt) |
| GAME-W1 | Major | verify-everything.py does not run opengl_decimate | Fix | Add `opengl_decimate` after `opengl_extrusions`; add a `tools/tests` check that `PROJECTS` covers the workspace directories minus explicit exclusions. | Fixed 37ff30c (workspace root) |
| GAME-W2 | Minor | preflight `checks` gate hard-codes the POSIX venv `bin` layout | Fix | Use `venv_tool(dev_venv, 'tox')`. | Fixed bbc5415 (workspace root) |
| GAME-W3 | Minor | Multi-file version bump can leave the tree half-bumped | Fix | Compute every replacement first, raise if any fails, then write them all. | Fixed a290b2e (workspace root) |
| GAME-W4 | Minor | `declared_path` strips every leading dot, not the `./` prefix | Fix | Use `removeprefix('./')` in a loop, or `os.path.relpath`. | Fixed bbc5415 (workspace root) |
| GAME-W5 | Minor | tools/issues.py: offline traceback, lost pages, open-only fetch, non-atomic save | Fix | Catch `URLError`, save pages collected before the rate-limit stop, fetch or document open-only, and save the cache atomically. | Fixed d0b0c02 (workspace root); shared tools/atomicwrite.py in bba63a9 |
| GAME-W6 | Nit | History in preflight tool docstrings | Fix | Rewrite the `venv_tool` and `declared_path` docstrings in the present tense. | Fixed bbc5415 (workspace root) |
| GAME-W7 | Nit | Entry with no version key raises a bare `KeyError` | Fix | Raise a `ReleaseError` naming the project in `_version_files`. | Fixed a290b2e (workspace root) |
| GAME-W8 | Nit | Missing blank lines before a section comment in doc_images.py | Fix | Add the blank lines; consider selecting ruff's E30x rules at the root. | Fixed 2425a64 (workspace root) |
| GAME-d2 | Minor | Workspace CLAUDE.md has no entry for tools/issues.py | Fix | Add a `tools/issues.py` entry to the "Other" list in CLAUDE.md. | Documented 5d5f6b7 (workspace root) |

## Work status (2026-09-25, end of the first pass)

Every finding has a status above. Still to do before a release:

- Publishing steps, each the maintainer's: omi_audio 0.4.0a1 (BIN-3), then opengl_decimate 0.2.0a1 (LIB-D25, ED-M5; its first PyPI release, before the editor), push the engine's `content-v1` release (CP-1, DOC-26), then an OpenGLContext release carrying the new APIs glisteel now calls (`telemetry.Keeping`, `scenegraph.roadcourse`, `audio.vehicle`, `contentpacks.Application`, `ui.contentscreen`), and raise glisteel's floor to it.
- `tools/preflight.py --rebuild-env` over every project: 69 of 69 gates green after the fixes it prompted (the ground-cover and LOD tutorials added to the docs build, the editor typed against the engine's new types, `zones_demo` re-blessed for the surface texture-coordinate fix, and a first baseline for `tests/mirrors_room.py`).
- The questions for the maintainer are under each `Needs input` finding.
- Follow-up: [DEFECT-PREVENTION.md](DEFECT-PREVENTION.md), the plan for gates that catch the recurring defect classes, with the catalogue in [DEFECT-CATALOGUE.md](DEFECT-CATALOGUE.md). It is parked with items 1 to 6 done; its "Parked, 2026-09-25" section lists what is pending (openglcontext's own ruff ratchets and engine APIs, pyopengl's selection waiting on uncommitted work, unclaimed viewer edits that fail `test_viewer_component`, publishing openglcontext-checks, and a full preflight run).
- Publishing, added since: openglcontext-checks 0.1.0a1 (its mypy plugin is enabled in openglcontext, whose tox typecheck environment needs it installed).

## Scope and method

The review was read-only. Nothing in any working tree was modified. Every suspected defect was reproduced where it could be, using scripts in the session scratchpad and the workspace venv. Findings rest on reading alone only where the confidence says so. One reviewer made a single live request to a public GitHub release asset to confirm how its redirect behaves (CP-1).

| Project | Range reviewed | Size of the change |
|---|---|---|
| openglcontext | `v3.0.0a4..7ed85dc` (212 commits) | 801 files, +86.8k / −31.0k (engine code about +24.4k) |
| openglcontext-editor | `e557177^..c911b86` + uncommitted | 83 files, +13.9k |
| opengl_decimate | `a133686^..cf1f72d` | 113 files, +8.7k |
| glisteel | `bbc2916^..4a2137f` + uncommitted | 44 files, +6.9k |
| omi_physics | `4d94b53^..8d745c5` | 30 files, +2.3k |
| glisteel-editor | `997fcbd^..e4e71ef` + uncommitted | 19 files, +1.5k |
| openglcontext-forest | `5c077f8^..de3821c` + uncommitted | 36 files, +1.1k |
| twig-bb | `b299750^..8d7df60` + uncommitted | 22 files, +0.9k / −0.8k |
| omi_audio | `44e70b5^..fbb7c10` | 11 files, +0.7k |
| pyvrml97 | `4d7a800^..0d0fe98` | 8 files, +0.3k |
| pyopengl-video, openglcontext-qt, marble-demo, marble-editor, opengl_extrusions, simpleparse | since 2026-09-12 | under 150 lines each |
| workspace root | `tools/`, `verify-everything.py`, packaging, commits since 2026-09-12 + uncommitted | |

`f6a8d63` ("PBR A material's maps each land on their own unit…") landed in openglcontext while the review was running. It is not covered here.

## Verdict

The range adds a great deal of engine capability: planar reflections, spatial zones, multi-view rendering, content packs, collision subscriptions, mesh LOD with impostors, procedural surfaces, glTF engine hooks, terrain holes and ground cover, and the move of the documentation to Sphinx. Most of it follows the workspace's own rules well. The per-frame decisions of the new subsystems (the reflection planner, the zone tables, the multi-view layout and cameras, the capture schedule, the demo "yards") are plain objects that can be tested without GL, and they are tested. The arithmetic was checked independently wherever it was checkable, and it holds: the mirror matrices and oblique projection, the zone signed-distance functions, the frustum box test, the std140 packing, the octahedral maps, the quadric mathematics, and the tile and hole geometry. Nearly every new feature has a reference page.

**It is not ready to release as it stands.** There are five critical defects:

- Two reach users on first contact: the forest demo cannot start from PyPI, and no content pack hosted on GitHub can be downloaded.
- One destroys user data: twig-bb moves a player's downloads into a temporary directory.
- Two let a downloaded model reach outside what the engine promises: a particle hook opens any local path and allocates without bound, and a malformed mirror value stops every frame.

Behind these, the most common major defect is a cache that answers after its question has changed. Several stale-answer caches return wrong results, and each was reproduced. There are also frame costs that grow with scene size, which the workspace headroom rule does not allow.

## Totals

| Area | Critical | Major | Minor | Nit |
|---|---|---|---|---|
| 1. Reflections and mirrors (REF) | 1 | 8 | 20 | 14 |
| 2. Zones (ZON) | 0 | 11 | 23 | 14 |
| 3. Render passes and shaders (PASS) | 0 | 4 | 22 | 18 |
| 4. Multi-view, overlay UI, viewer, backends, openglcontext-qt (MV) | 0 | 11 | 23 | 15 |
| 5. Scenegraph content and loaders (SG) | 1 | 9 | 31 | 14 |
| 6. Content packs, physics, demos, packaging, documentation (CP, PH, BIN, DOC) | 1 | 20 | 44 | 21 |
| 7. Libraries: opengl_decimate, omi_physics, omi_audio, pyvrml97, pyopengl-video (LIB) | 0 | 3 | 23 | 22 |
| 8. openglcontext-editor (ED) | 0 | 11 | 33 | 14 |
| 9. Games, glisteel-editor, workspace tools (GAME) | 2 | 12 | 38 | 13 |
| Total | 5 | 89 | 257 | 145 |

The totals count every coded finding. 16 are marked as duplicates of another finding in the summary table, so there are somewhat fewer distinct defects than 496.

## The critical findings

1. GAME-F1: the forest demo cannot find its art on a first run from the wheel. The art moved to a content pack, but `scene.ASSETS = content.art_directory()` is evaluated at import, before `main()` fetches the pack. `HEIGHTMAP`, `CONTROL` and `COVER` keep pointing at a wheel directory that no longer exists, so `oglc-forest` from PyPI fails on the first run and works on the second (`openglcontext-forest/src/openglcontext_forest_demo/scene.py:46`).
2. GAME-T1: twig-bb moves a player's downloaded content into whatever root a store is opened with. `adopt_legacy_content` always reads the real per-user legacy tree and moves each pack into `store.directory_for(pack)`, whatever root the store has, including `--cache-dir` and pytest's `tmp_path`, which is deleted afterwards (`twig-bb/twig_bb/download.py:68-110`). On this machine `~/.config/OpenGLContext/twig-bb-content/` exists and is empty. That is consistent with the defect but does not prove it.
3. CP-1: every GitHub-hosted content pack fails to download. The resolver refuses any cross-origin redirect (`loaders/resolver.py:181-229`), and GitHub release assets always redirect to `release-assets.githubusercontent.com`. Every shipped registry points at GitHub (engine, glisteel, forest, twig-bb), as does the LOD demo command in `docs/lod.rst`. The engine's own `content-v1` release also returned 404.
4. SG-C1: a downloaded glTF can set any `ParticleEmitter` field through `OGLC_hook`, with no bounds. `FIELDS` is every field except `externalURL`, so a file sets `maxParticles` to 4×10⁹ and `texture` to any local path (`/etc/hostname`, `../`, a device file), which `Image.open` then reads (`scenegraph/particlehooks.py:64-103`). Hooks are on by default, so `oglc-view some.glb` is exposed. This contradicts the "a file names a kind; it never names code" guarantee in `docs/gltf.rst`, and `docs/untrusted.rst` does not mention hooks at all.
5. REF-C1: one reflector value, from a model or from code, can stop loading or stop every frame. `reflector_for` catches `TypeError`/`ValueError` but not `OverflowError` (`{"interval": 1e999}`), and it accepts NaN for `scale`. The planner then raises on every frame the mirror is in view. `renderReflections` is called with no guard (`passes/_flat.py:1666`), so the whole frame is lost. The same applies to an incomplete atlas framebuffer on a driver that refuses the format.

## Cross-cutting themes

These patterns recur across areas, and each is better fixed once, as a rule, than finding by finding.

### Input from a document is converted with bare `float()`/`int()`

- The zone reader (ZON-M7), the water hook, the `MSFT_lod` reader and hook factories (SG-M1), and the mirror hook (REF-C1) each let one malformed value abort a whole load, or a whole frame.
- `particlehooks._number` and `mirrorhooks.reflector_for` already contain the right pattern, and each of the others has written its own weaker version.

Fix: one shared "number from a document" helper that logs, falls back and rejects non-finite values. `HookRunner` should isolate a failing factory.

### Tileset- and document-named files bypass `Resolver` containment

- Zones and cover species files (SG-M7, ZON-m14).
- Remote species paths opened as local files (SG-M8).
- The particle `texture` (SG-C1).
- The editor's plant glTF reader (ED-m2).
- `fetch_url` accepting `file://` (CP-13).

The glTF loader itself routes every reference through the resolver. The layers around it do not.

### Caches keyed on `id()` or on identity, without holding the object or covering every input

- `_FITS` keeps `id(positions)` (REF-M7).
- Instanced groups compare `id(matrix)` (ZON-M3).
- The multi-view capability cache is keyed on a raw context address (MV-m1).
- The zone placement key omits settings (ZON-M1), and scale and bounds changes go unnoticed (ZON-M2).
- Image-light layers are evicted by zone id (ZON-M4).
- The PBR batching memo misses `reflector` and in-place texture edits (PASS-M2).
- The LOD memo misses the node's own fields (PASS-M3), and `LOD.boundingVolume` stays cached for the first level (SG-M2).
- A shared glTF mesh turns every instance into a mirror (REF-M1).
- A view's navigation outlives its camera (MV-M1).
- `mirror_generation` misses `waveStyle` (REF-m8, PASS-m16).

Fix: a written rule for caches in `openglcontext/CLAUDE.md`. Hold the key object, or key on a generation counter bumped by the field-observer mechanism the scenegraph already has. A test should edit each input and assert the answer changes.

### GL resources and frame state without an owner

- A scene swap leaks the reflection atlas, GPU timers, view UBO, zone capture targets, IBL probe array and program sets, because `renderpass._dispose` only disposes shadow maps (PASS-M1).
- Capture targets are never released with the context (ZON-m4).
- The atlas stays allocated while reflections are off (REF-m9).
- GLFW cursors are never destroyed (MV-m14).
- The frame's gather has two hand-off mechanisms, and the legacy pick path clears one part-way through a frame (PASS-m1, PASS-m2).
- An exception inside a view leaves scissoring on (MV-m15).

Fix: a `disposeResources()` chain through the pass mixins, and a frame-scoped state object that `Render` owns and clears in `finally`.

### No failure isolation for optional frame layers

- Reflections (REF-C1).
- A zone capture that fails is retried every frame (ZON-m1, ZON-m2).
- A mirror the budget can never afford keeps asking for frames forever (REF-M2).

The engine already follows disable-on-failure elsewhere (`instancedgl.ensure_gl`, the IBL fallback). Every optional layer should follow it.

### Writes that are not atomic

- Content-pack installs (CP-3), refreshed registries (CP-12), kept failed registries (CP-7) and `archive.write` (CP-18).
- The viewer's archive cache (MV-M10).
- The Poly Haven cache (ED-m1).
- The multi-file version bump (GAME-W3).
- The issues cache (GAME-W5).

Fix: stage to a sibling temporary path and `os.replace`, under a lock where two processes can race. This belongs in one engine helper.

### Paths and settings bound at import time

- The forest's art (GAME-F1), glisteel's and twig-bb's art (GAME-X2, GAME-G3, GAME-T3), and twig-bb's adoption running during import (GAME-T2).
- `profile_view`'s error-checking switch set after `OpenGL` is imported (BIN-2).
- The audio demo choosing a GL backend at import (BIN-9).

### Dependency floors below the sibling APIs actually called

- `omi_audio>=0.2.0a1` while the engine calls `set_rate` and `reverb`, and the editor calls `synth.birdsong`, none of which any omi_audio release carries (BIN-3, ZON-m15, ED-M5).
- opengl_decimate is untagged at 0.1.0a1, and newer API is used (ED-M5).
- The editor's committed HEAD does not work against the engine's committed HEAD until the uncommitted species rename lands (ED-M11).
- `verify-everything.py` does not run opengl_decimate's suite (GAME-W1).

Release order matters here: omi_audio and opengl_decimate need releases before OpenGLContext's pins can name them.

### Engine capability living in demos and tools

- Three copies of `release-assets.py` (GAME-X1) and three import-bound art resolvers (GAME-X2).
- Two download consent screens (GAME-G18).
- Vehicle sound synthesis (GAME-G19) and road-course queries (GAME-G20).
- The zone-light bake loop reading pass privates (ED-M7).
- Four hand-written glTF readers and writers beside the engine's (ED-M8).
- The stones record read by glisteel (ED-M3) and bore openings derived twice (ED-M6).
- A kinematic door driver and trigger occupancy in a demo (BIN-6).
- `ProceduralWorld`'s parameters restated in glisteel-editor (GAME-E6).

### Frame costs that grow with scene size in Python

- One moving zone reclassifies every object, at 125 ms a frame for 5,000 objects (ZON-M5).
- The first zone classification allocates 443 MB (ZON-M6).
- Per-record Python for each mirror view: 77 ms at 2,000 records × 4 views (REF-M4).
- Every ground tile re-uploads about 20 constant uniforms and five textures (SG-M6).
- Ground cover re-selects and uploads on every moving frame (SG-m16).
- Each visible record is scanned for mirrors in scenes with none (PASS-m7).
- An import inside the per-draw functions (MV-m20).
- Full-line nearest-point scans at the physics rate (GAME-G16).

In the libraries:

- opengl_decimate's `multiple-choice` schedule takes 28 s where `heap` takes 0.02 s (LIB-D1).
- Its compiled loop is quadratic in vertex valence (LIB-D6).
- marble-demo's contact log grows to 65 MB (GAME-M2), with an engine-side fix in omi_physics (LIB-P9).

### The typecheck and test gates

- mypy reports real errors, not venv artefacts: 47 in the zone modules (ZON-M10), and others in PASS-m3, SG-m22 and PH-04.
- Public APIs are typed `Any` where the concrete types exist: the multi-view cameras (MV-m16), the hooks API (SG-m24), editor world queries (ED-m25).
- Seven new `type: ignore` comments give no reason (SG-m23, ZON-n4).
- The zone render and cost tests turn a crash into a skip (ZON-M11).
- Logic sits in `# pragma: no cover - needs a window` classes: glisteel's menu screens, where GAME-G1 went unseen for that reason, the physics demo's frame pacing (BIN-7), and mirror-view content selection (REF-m14).

### Documentation

Every new page is in a toctree and most were checked claim by claim. The gaps:

- No changelog entry since 3.0.0a1 (DOC-02). omi_physics 0.4.0 and opengl_decimate also have none.
- A broken tutorial link (DOC-01).
- A content-pack example that asks the user again on every start (DOC-03).
- `untrusted.rst` is silent on `OGLC_hook`, `OGLC_zone` and `EXT_lights_image_based` (SG docs).
- No demo or tutorial for zones (DOC-13), MSFT_lod, ground cover or holes.
- `multiview.grid` is public and undrawn (MV-M8).
- Several statements contradict the code: tile aspect (MV-M2), `placeViews` (MV-m10), the reflection unit threshold (DOC-07), the zone epoch (ZON docs), the open-surface floor (LIB-D2), `locked` indices (LIB-D3), and the `--canopy` help (ED-M9).
- The writing rules are broken widely in new docstrings, and in glisteel above all (GAME-G22): history and journal anecdotes, bold-leader paragraphs, and "which is the whole point" glosses. `/ai-isms --fix` over the new modules would clear most of it.

## Order of work before a release

1. The five critical findings: GAME-F1, GAME-T1, CP-1 (and push `content-v1`), SG-C1, REF-C1.
2. Untrusted input: SG-M1, ZON-M7, SG-M7, SG-M8, CP-4, CP-5, CP-13, ED-m2, with a section in `docs/untrusted.rst` covering hooks, zones and image-based lights.
3. Installed state and user data: CP-2, CP-3, CP-7, CP-8, MV-M10.
4. Floors and release order: release omi_audio and opengl_decimate, then raise the pins (BIN-3, ZON-m15, ED-M5). Commit the editor's species rename (ED-M11), and add opengl_decimate to `verify-everything.py` (GAME-W1).
5. Stale caches: ZON-M1, ZON-M2, ZON-M3, ZON-M4, PASS-M2, PASS-M3, SG-M2, REF-M1, REF-M7, MV-M1.
6. Resource lifetime: PASS-M1, then the rest of the lifecycle theme.
7. Headroom: ZON-M5, ZON-M6, REF-M4, SG-M6, LIB-D1, LIB-D6, GAME-M2 / LIB-P9.
8. Gates: ZON-M10 and the other mypy errors, ZON-M11's skip-on-crash.
9. Game defects a player meets: GAME-G1, GAME-G2, GAME-G4, GAME-G5, GAME-M1, BIN-1, MV-M2, MV-M3, MV-M4, MV-M5, MV-M6.
10. Documentation: DOC-01, DOC-02, DOC-03, the zones demo, and a prose sweep with `/ai-isms --fix`.

## Findings reported from two sides

| Defect | Reported as |
|---|---|
| `omi_audio` floor below the API called | BIN-3, ZON-m15, ED-M5 |
| Malformed `OGLC_zone` values abort a load | ZON-M7, SG-M1 |
| Zones file named by the tileset joined without containment | ZON-m14, SG-M7 |
| `waveStyle` not watched by `mirror_generation` | REF-m8, PASS-m16 |
| Zone gain and reverb stick when zones go | ZON-M9, PH-05 |
| Archive extraction not atomic | MV-M10, MV-m21, CP-3 |
| Reflection unit threshold off by one in the docs | REF docs, DOC-07 |
| Blender panel lacks Reflectance in the docs | REF docs, DOC-08 |
| `_multiview_inc.glsl` names a module that does not exist | PASS-n2, MV-m12 |
| `pbr.frag` review numbers in comments | ZON-n9, PASS-n1 |
| Mutable class-level defaults on the effects mixin | REF-n4, PASS-n4 |
| openglcontext-qt pyproject comment names the wrong release | MV-n12, GAME-Q1 |
| Pointer-shape cache stale across a capture | MV-M11, GAME-Q2 |
| `physics.rst` repeats a sentence | BIN-13, DOC-11 |
| `EXT_lights_image_based` missing from the zones loader list | ZON docs, DOC-16 |
| LOD demo URL cannot work | CP-1, DOC-26 |
| Stone metadata and bore openings owned by the wrong layer | ED-M3, ED-M6, and GAME's glisteel findings |

---

The full findings follow, one area per section, as each reviewer reported them, with each finding under its code from the summary table. They have been checked against the code but not rewritten.

## Area 1: reflections and mirrors (REF)

Scope: `OpenGLContext/passes/reflection.py`, `reflectionplanner.py`,
`reflectiontiles.py`, `reflectionatlas.py`, the reflection half of
`passes/flateffects.py` (`renderReflections` through `clearPlanarReflection`),
`renderShared(reflection=)` in `passes/_flat.py`, the planar block of
`shaders/pbr.frag` and `PBRShaderProgram.set_planar_reflection`,
`scenegraph/reflector.py`, `scenegraph/mirrorhooks.py`, `scenegraph/surfaces.py`,
`bin/mirrorhall.py`, `bin/mirrors_demo.py`, their tests, `docs/reflections.rst`,
`docs/surfaces.rst`, `plans/PLANAR-MIRRORS.md` and the workspace hand-off
`plans/2026-09-24-planar-mirrors-handoff.md`. All paths below are relative to
`openglcontext/`.

### Overall assessment

The design is sound and most of it is well executed. The per-frame decision
lives in plain objects with no GL (`ReflectionPlanner`, `TilePacker`,
`ReflectionSchedule`), the arithmetic checks out (mirror matrix, eye-space
plane, Lengyel oblique projection with an off-centre crop, projective atlas
lookup), identity guards against `id()` reuse are in the planner, and the
feature ships with a reference page, a shipped `oglc-mirrors` demo, a Blender
authoring path and 213 targeted tests that pass. mypy and ruff are clean on
every file in scope. The problems are at the edges. Nothing isolates the
reflection pass from failure, so one bad reflector value or a GL failure stops
the whole frame. The object-level `mirror` hook turns every other instance of
a shared glTF mesh into a mirror as well. A still scene can ask for frames
forever. The millisecond feedback loop re-applies a stale reading every frame.
Per-record Python in the mirror views (`too_small`, `_separateShapes`) grows
with scene size, which the hand-off already measured at 16 ms of a 23 ms
frame. Two budget paths skip the texel and separate-view limits. The fitted
plane cache is keyed on `id()` of an array it does not hold. A few doc
statements are inaccurate. Coverage misses the VRML97 `IndexedFaceSet` mirror
path entirely, and that path ignores `ccw`.

Counts: Critical 1, Major 8, Minor 16, Nit 11.

---

### Critical

#### REF-C1. A reflector value from a model file can stop loading or stop every frame, and the reflection pass has no failure isolation

References: `OpenGLContext/scenegraph/mirrorhooks.py:76-93`,
`OpenGLContext/scenegraph/reflector.py:56-62`,
`OpenGLContext/passes/reflection.py:465-466`,
`OpenGLContext/passes/flateffects.py:311-404`, `OpenGLContext/passes/_flat.py:1663-1666`,
`OpenGLContext/passes/reflectionatlas.py:106-110`

Problem: `reflector_for` says a value that cannot be read is reported and left
at its default, "a model to load rather than a file to refuse". It catches only
`TypeError` and `ValueError`. `int(float('inf'))` raises `OverflowError`, so
`{"interval": 1e999}` (which Python's `json` reads as `inf`) fails the whole
load. `float('nan')` and the string `"nan"` are accepted as `scale`, and the
planner then raises `ValueError` in `_texels` on every frame the mirror is in
view. `PlanarReflector`'s own fields are not validated either, so the same
thing happens when an application sets `scale = float('nan')`. None of it is
caught: `renderReflections` is called bare from the frame (`_flat.py:1666`),
so the exception leaves the render and the frame is lost, every frame. A
`RuntimeError` from an incomplete atlas framebuffer (`reflectionatlas.py:108-110`)
does the same on a driver that refuses `RGBA16F` plus `DEPTH_COMPONENT24`.
The engine's own convention for optional layers is disable-on-failure
(`instancedgl.ensure_gl`, the IBL build degrading to `analytic`).

Evidence (scratch reproductions):

```text
{'interval': inf} raised OverflowError cannot convert float infinity to integer
{'scale': 'nan'} -> nan 3
  texels raised ValueError cannot convert float NaN to integer
plan raised ValueError cannot convert float NaN to integer     # ReflectionPlanner.plan
```

Confidence: Confirmed (hook and planner). The frame-level effect follows from
reading `_flat.py:1663-1666`, where there is no handler.

Suggested fix: in `reflector_for`, catch `OverflowError` too and reject
non-finite numbers (`math.isfinite`), clamping `scale` to the UI hint's
`[0.05, 1.0]` and `interval` to `>= 1`. Have the planner read reflector fields
through one sanitising helper (finite, clamped) so code-set values cannot
reach `int()` as NaN. Wrap the body of `renderReflections` so an exception
logs once, sets `_planar_reflections = False` (every mirror falls back to the
probe), and clears `_reflection_lookups`, following the pattern
`ensure_gl` already uses.

---

### Major

#### REF-M1. An object tagged `mirror` makes every other node that uses the same glTF mesh a mirror too

References: `OpenGLContext/scenegraph/mirrorhooks.py:127-143`,
`OpenGLContext/loaders/gltf/scene.py:600-627`, `OpenGLContext/loaders/gltf/hooks.py:341-360`

Problem: the object form of the hook assigns a new material to
`shape.appearance.material` and `shape.geometry.material` for every shape
under the node. Those shapes come from `mesh_shapes`, which caches them per
glTF mesh and hands the same `Shape` objects to every node that references the
mesh. `shareable=False` is only consulted on the material-hook path
(`hooks.material` returns it; `hooks.node` ignores it), so it does not keep
node-hook results out of the cache. The comment at `mirrorhooks.py:141-142`
says the opposite. A second, untagged node that shares the mesh becomes a
replace-mirror, and so do earlier ones.

Evidence (two nodes, one mesh, only `tagged` carries the hook):

```text
meshes in file 1 [('plain', 0, {}), ('tagged', 0, {'OGLC_hook': 'mirror'}), ...]
136234877302736 PlanarReflector( @0x7BE7A87AF470 )
136234877302736 PlanarReflector( @0x7BE7A87AF470 )   # the same Shape, both mirrors
```

Confidence: Confirmed.

Suggested fix: have the object hook replace, not mutate. Build a new `Shape`
(and `Appearance`) for each shape under the node, sharing the geometry, and
return the rebuilt children as the hook's `(node, True)` result. Alternatively,
make `hooks.node` honour `shareable=False` by asking the loader for uncached
shapes before it runs the factory. Add a test with two nodes on one mesh.

#### REF-M2. A mirror too large for the texel budget is never drawn, and the pass asks for a new frame forever

References: `OpenGLContext/passes/reflectiontiles.py:314-320`,
`OpenGLContext/passes/reflectionplanner.py:512-515`,
`OpenGLContext/passes/flateffects.py:355-361`

Problem: `ReflectionSchedule.choose` tries full scale, then half scale, and
otherwise skips a must-draw candidate. A skipped candidate is not in
`decisions` and not in `_crowded` (`_crowded` is filled only in `_pack` for
tiles that were chosen), and it is not valid, so `plan.unfinished` is True on
every frame. `renderReflections` then calls `triggerRedraw(0)`, so a still
scene that only redraws on change never goes idle, and the mirror shows the
probe. This is easy to reach. A mirror that fills the view has a crop of 1.2x
the view each way (the guard band), so its tile is 1.44 x window pixels x
`scale`^2, against a budget of `atlas share x FILL` = 0.25 x window pixels by
default. A `scale=1.0` mirror close up (the demo's replace window, any "magic
window") needs 0.36 of the window even at half scale. `reflectionMilliseconds`
lowers the budget to a quarter of that.

Evidence:

```text
0 draws 0 lookups 0 unfinished True [(167040, False)]
...
5 draws 0 lookups 0 unfinished True [(167040, False)]      # budget 5000 texels
```

Confidence: Confirmed.

Suggested fix: in `choose`, for a must-draw candidate that does not fit at
half scale, draw it at the largest scale that fits (`sqrt(texels_left /
candidate.texels)`, floored at a minimum such as 1/8) instead of skipping it.
Independently, record a candidate the schedule could not afford the way
`_crowded` records one the packer could not place, so `unfinished` does not
spin on it. Add a planner test with a budget smaller than a quarter of the
mirror's tile.

#### REF-M3. The millisecond target re-applies one stale measurement every frame

References: `OpenGLContext/passes/flateffects.py:337-342`,
`OpenGLContext/passes/reflectiontiles.py:283-289`, `OpenGLContext/passes/gputimer.py:53-66`

Problem: `GpuTimer.milliseconds` keeps its newest value until another query
returns, and queries are read only inside `begin()`. So on frames with no
mirror views the value never changes, and on frames with them it is two
frames old. `renderReflections` calls `schedule.measured(timer.milliseconds,
target)` every frame regardless. `measured` computes `wanted = time_scale *
target / ms` from the current `time_scale`, so each re-application compounds.
One reading 20% over target drives the scale all the way to `FLOOR` instead of
to 0.83. The control law also ignores the two-frame latency between a scale
and its measurement, so it overshoots whenever readings do arrive.

Evidence:

```text
after 20 frames of the same 6ms reading: 0.508     # target 5 ms; the right answer is ~0.83
```

Confidence: Confirmed.

Suggested fix: have `GpuTimer` expose a sequence number or a "fresh" flag for
each reading and call `measured` once per new reading. Record the
`time_scale` the measured frame was drawn with (a ring alongside the queries)
and compute `wanted = scale_then * target / ms`. Add a test that re-applying
the same reading leaves the scale unchanged.

#### REF-M4. Per-record Python in every mirror view: `too_small` and `_separateShapes`

References: `OpenGLContext/passes/flateffects.py:457-477` (`too_small` at 474-475),
`OpenGLContext/passes/reflection.py:541-559`, `OpenGLContext/passes/flateffects.py:406-410`

Problem: `mirrorContents` runs `too_small` in a Python loop over every record
that survives each mirror view's cull. `too_small` makes about six small NumPy
calls per record. `_separateShapes` walks the whole `toRender` of every view
with a mirror, calling `is_reflector` and `sharesDraw` (a chain of `getattr`)
per record, each frame. Cost grows as records x mirror views, which is the
scaling the workspace's headroom rule warns about. The hand-off records this
as 16 ms of a 23 ms frame at one pose with three mirror views and names
`too_small` specifically. The fix there merged the demo's scenery into fewer
shapes, which moves the demo but leaves the engine path unchanged.

Evidence: `too_small` measures 9.6 us per call here, so 2,000 records x 4
mirror views is about 77 ms per frame spent in that function alone.

Confidence: Confirmed (cost measured; scaling follows from the loops).

Suggested fix: vectorise `too_small` over the gather. The gather already holds
`matrices`, `points` (bounding corners) and `volumes` as arrays (`mirrorsIn`
indexes them), so compute each survivor's centre, radius and distance in one
NumPy expression per mirror view and mask. Cache `_separateShapes` per frame
list by `id(frame)` and `_pathGeneration`, or compute a per-gather boolean
array "refused by a shared draw" once per path generation and index it.

#### REF-M5. The separate-view budget is not charged for nested mirror views, and only approximated for top-level ones

References: `OpenGLContext/passes/reflectionplanner.py:467-470`,
`OpenGLContext/passes/reflectionplanner.py:376-403`, `OpenGLContext/passes/flateffects.py:406-410`

Problem: `plan` calls `separate(entry.frame)` for every candidate's frame.
For a mirror seen in a mirror, that frame comes from `_inside`, whose
`toRender` holds only the mirrors `mirrorsIn` found. Every record in it is a
reflector, so `_separateShapes` returns False, and nested mirror views are
never counted against `reflectionSeparateViews`, although drawing one draws
the particles and text it sees. For a top-level mirror, `separate` inspects
what the viewer's view draws, not what the mirror view will draw (which
includes what stands behind the camera), so the flag can be wrong either way.

Confidence: Confirmed for nested views (by reading). Likely for top-level
views.

Suggested fix: decide `separate` from the mirror view's own contents. The
cheapest correct form is a per-gather boolean array ("refused by a shared
draw", see REF-M4) tested against the mirror view's frustum survivors, which
`mirrorsIn` shows how to compute without a full cull.

#### REF-M6. Tiles redrawn after a repack bypass the texel and separate-view budgets

References: `OpenGLContext/passes/reflectionplanner.py:475-481`

Problem: after `_pack`, every kept tile that moved is added to `decisions`
while `spare` (views left) is positive. Neither the texel budget nor
`separate_views` is checked, so a repack can push the frame's drawn texels
and separate draws past what the schedule allowed. With
`reflectionMilliseconds` set, that is the spike the target exists to prevent.
This path is also uncovered by tests (lines 477-481 are in the coverage
report's missing list).

Confidence: Confirmed (by reading).

Suggested fix: carry the schedule's remaining texels and separate views out
of `choose` (return them with the decisions) and charge moved tiles against
them, dropping a moved tile's lookup when it does not fit. Add a planner test
that forces a repack under a tight texel budget.

#### REF-M7. The plane-fit cache is keyed on the `id()` of an array it does not hold

References: `OpenGLContext/passes/reflection.py:239-298`

Problem: `_FITS[geometry] = (id(positions), fitted)` keeps only the id. When
`positions` is replaced and the old array is freed, the new array can get the
same address, and `mesh_plane` then returns the old plane. An in-place edit of
the array is never noticed at all. The planner has the right pattern already
(`held.path is not record[4]`, with the `_Held` keeping a strong reference).

Evidence (the quad replaced by one in the xz plane, whose normal is +/-y):

```text
[0. 0. 1.]
reused id; normal says [0. 0. 1.]
```

Confidence: Confirmed.

Suggested fix: store the array itself, `_FITS[geometry] = (positions, fitted)`,
and compare with `is`. The geometry already holds a reference, so this costs
nothing until the array is replaced. If in-place edits are to be supported,
key on a geometry change counter (the field's `set` signal, as
`mirror_generation` does).

#### REF-M8. `IndexedFaceSet` mirrors ignore `ccw`, and the VRML97 path has no tests

References: `OpenGLContext/passes/reflection.py:245-269`, `OpenGLContext/passes/reflection.py:201-213`

Problem: `_geometry_points` fans `coordIndex` into triangles and `fit_plane`
orients the normal by their winding, but it never reads the node's `ccw`
field. An `IndexedFaceSet` with `ccw FALSE` (common in exported VRML97) gets
a normal on its back side, so `plan_mirror` finds the camera "behind" the
mirror and it reflects nothing. The `IndexedFaceSet` path (`_fan`, the
`coord.point` branch, `_facing` without indices) is in the coverage report's
missing lines: 204-207, 251-255, 260-269.

Evidence:

```text
ccw True  reflector True plane (array([0., 0., 0.]), array([0., 0., 1.]))
ccw False reflector True plane (array([0., 0., 0.]), array([0., 0., 1.]))   # should be -z
```

Confidence: Confirmed.

Suggested fix: negate the fitted normal when `getattr(geometry, 'ccw', True)`
is false. `_fan` is a Python loop over `coordIndex`; it runs once per
geometry, but a NumPy split on the `-1` markers would suit large meshes. Add tests for an
`IndexedFaceSet` mirror at both windings and for polygons with more than
three corners.

---

### Minor

#### REF-m1. The rough-mirror mip levels read the uncleared gutter at the tile edge

References: `OpenGLContext/passes/reflectionatlas.py:156-162`,
`OpenGLContext/passes/flateffects.py:557-558`, `OpenGLContext/passes/reflection.py:581-588`,
`OpenGLContext/shaders/pbr.frag:413-419`

Problem: `atlas.clear(frame.rect)` clears the tile only, not its gutter.
`glTexStorage2D` leaves contents undefined, and a tile that moves leaves its
old image in what becomes a neighbour's gutter. `planarBounds` is half a
level-0 texel in. At level 1 a sample at the bound takes 25% from the gutter
texel, and at level 2 it takes 37.5%. So a rough mirror's reflection can show
a fringe of stale colour, or undefined memory, where a lookup reaches the edge
of the crop. The plan says the 4-texel gutter "keeps those levels inside it",
but it does not while the gutter holds garbage.

Confidence: Likely (by reading; the guard band makes the edge rarely sampled).

Suggested fix: clear the slot (the tile grown by `GUTTER` each side, clipped
to the atlas) instead of the tile. Optionally inset `planarBounds` by half a
texel of the level being read (`0.5 * 2^lod`).

#### REF-m2. `screen_rect` gives a floor the whole view, plus a guard band past the screen

References: `OpenGLContext/passes/reflection.py:411-433`, `OpenGLContext/passes/reflection.py:497-527`

Problem: any corner behind the camera plane returns `WHOLE`, and `plan_mirror`
then grows it by 10% each side. A floor, the most common mirror, always has
corners behind the camera, so its tile is 1.44 x the view x `scale`^2
regardless of how much of the view it covers. That is what pushes floors to
half scale under the default budget, and it feeds REF-M2.

Confidence: Confirmed (by reading).

Suggested fix: clip the box's edges against the near plane (w > epsilon)
before projecting, adding the intersection points, and take the rect of what
survives. Keep `WHOLE` only as the fallback when clipping leaves nothing.

#### REF-m3. Rule 4 spends the whole budget on a still scene

References: `OpenGLContext/passes/reflectiontiles.py:321-323`, `docs/reflections.rst:350-352`

Problem: every optional candidate is drawn while there is room, so with the
default budget every mirror is redrawn every frame even when nothing moved.
This is documented as intended, and the scratch run shows it (12 mirrors with
`interval=3`, all valid at age 1, all six drawn on every frame). The GPU
headroom a game needs is then spent on redraws that produce the same picture.

Confidence: Confirmed (behaviour). The severity is a judgement.

Suggested fix: count redraws of optional, valid, low-drift candidates only
while the frame has budget left after the main views' expected cost, or add a
`reflectionIdleRedraw` (default off) and let `interval` be the redraw rate
when nothing asks for more. At the least, the docs could state the GPU cost
of the default.

Question for the maintainer (REF-m3): With room in the budget, every mirror in view is redrawn every frame, even in a
still scene; `interval` only matters when the budget is short. Should optional
redraws stay the default? The options: (a) keep it and state the GPU cost in
docs/reflections.rst (a moving object's reflection is never stale while the
budget has room); (b) add a `reflectionIdleRedraw` setting, default off, under
which a mirror is redrawn only when rules 1-3 ask (no tile, its `interval`
reached, or its camera moved a texel) - reflections of moving objects then lag
by up to `interval` frames (3 by default), and the GPU time a game would spend
on identical redraws is left free; (c) the same as (b) but spending optional
redraws only while `reflectionMilliseconds` shows time to spare. I recommend
(b), for the headroom rule: the budget is a ceiling, and a still scene spending
all of it on redraws that produce the same picture leaves a game nothing. It
changes what every mirror looks like around moving objects, so it is yours to
choose.

#### REF-m4. `redo()` says the old reflection "is still passed on meanwhile", but an invalid tile is dropped when the budget skips it

References: `OpenGLContext/passes/reflectionplanner.py:270-280`,
`OpenGLContext/passes/reflectionplanner.py:357-361`, `OpenGLContext/passes/reflectionplanner.py:534-536`,
`OpenGLContext/passes/reflectionplanner.py:489-503`

Problem: `redo` and `missing` make `valid` False. An invalid held tile is not
in `kept`, so it is not placed. If the schedule does not choose it this frame
(view budget exhausted), it gets no tile and no lookup, and the mirror flips
to the probe for that frame. That is the flashing the hand-off describes
fighting. The same applies to a crop change: the old tile is still a
reasonable projection but is thrown away.

Confidence: Likely.

Suggested fix: keep an invalid-but-readable held tile in `kept` (placed at its
size) when it is not chosen, and give it a lookup. Only a tile from another
view, plane or size is unreadable.

#### REF-m5. Planning cost is Python per mirror per view, and grows as mirrors^bounces

References: `OpenGLContext/passes/reflectionplanner.py:293-363`,
`OpenGLContext/passes/reflectionplanner.py:455-459`, `OpenGLContext/contextdefinition.py:210-216`

Problem: `plan()` measures 1.65 ms for 12 mirrors in one view (about 140 us
per mirror: plane placement, a 4x4 inverse per view in `plan_mirror`, the
oblique projection, the dataclasses). Each bounce multiplies the entries by
the mirrors each mirror view sees. `reflectionBounces` is an unbounded
`SFInt32`: the settings hint stops at 3, but code or the environment variable
can set 6, and a hall of facing mirrors then plans thousands of views before
the budget throws them away.

Confidence: Confirmed (timing). Likely for the growth.

Suggested fix: clamp `bounces` (to 3, or to what the view budget can draw),
and stop descending once the candidate count exceeds a multiple of
`budget.views`. Hoist per-view inverses (the eye is already computed in
`_seen`; pass it to `plan_mirror`).

#### REF-m6. `surface_roughness` converts the whole roughness image on the render thread

References: `OpenGLContext/passes/reflection.py:115-134`

Problem: the first time a textured mirror is seen, `image.convert('RGB')` plus
`np.asarray` copies the full image (about 50 MB for 4K) inside the frame. It
also stores the result as an ad-hoc `_mean_roughness` attribute on another
class's object.

Confidence: Confirmed (by reading).

Suggested fix: use `image.getchannel('G')` with `PIL.ImageStat.Stat(...).mean`
on a `reduce()`d copy, or compute it when the `PBRTexture` is built. Give
`PBRTexture` a declared `mean_roughness` cache instead of a monkeypatched
attribute.

#### REF-m7. `_water_plane` recomputes the mean level and bounding box every frame

References: `OpenGLContext/passes/reflection.py:301-313`, `OpenGLContext/passes/reflection.py:316-323`

Problem: unlike `mesh_plane`, the water plane is not cached. Each frame, for
every water record in every view, it takes the mean and min/max of the whole
sheet's positions and builds the eight corners in a Python comprehension. A
256x256 sheet is 65k points per view per frame. With `on_gpu=True` the
positions do not change.

Confidence: Confirmed (by reading).

Suggested fix: cache it in `_FITS` exactly as `mesh_plane` does (keyed on the
positions array, see REF-M7).

#### REF-m8. `mirror_generation` misses `PBRMesh.waveStyle`

References: `OpenGLContext/passes/reflection.py:161-173`, `OpenGLContext/passes/flateffects.py:412-427`

Problem: `shape_reflector` answers from the geometry's `waveStyle` (water), but
setting `waveStyle` on an existing mesh does not bump the counter, so
`sceneMirrors` keeps an answer without it. Water made at runtime by giving an
existing mesh a style is then not found inside mirror views. `PBRMesh.material`
is a plain attribute, so a runtime change there is likewise invisible. The
watch is also a process-wide global connected at import time, which couples
every context and any test that imports `passes.reflection`.

Confidence: Confirmed (by reading).

Suggested fix: add `(PBRMesh, 'waveStyle')` to `_watch_mirror_fields`.
Document that `PBRMesh.material` is read at load time, or make it a field.

#### REF-m9. The atlas stays allocated while reflections are switched off

References: `OpenGLContext/passes/flateffects.py:321-326`

Problem: turning `planarReflections` off returns early and keeps the atlas
(`RGBA16F` plus depth, about 15 MB at 1440p, more with the `kept` copy) and
the planner's held tiles. On re-enabling, those held tiles are treated as
valid at whatever age they have.

Confidence: Confirmed (by reading).

Suggested fix: on the transition to off, `release()` the atlas and `reset()`
the planner.

#### REF-m10. A new atlas with draws keeps lookups into undefined texels

References: `OpenGLContext/passes/flateffects.py:364-373`

Problem: when `ensure_size` makes a new atlas and the plan has no draws, the
planner is reset. When the plan does have draws, kept tiles' lookups remain
and read a freshly allocated texture. Today the planner's own size check
usually clears them first, so this is only reachable when the atlas is
recreated without a size change. The two branches are still inconsistent.

Confidence: Possible.

Suggested fix: on `ensure_size() == True`, always `planner.reset()` and filter
`plan.lookups` to the keys in `plan.draws`.

#### REF-m11. `keep()` blits the whole atlas every frame a mirror is seen in a mirror

References: `OpenGLContext/passes/reflectionatlas.py:114-138`

Problem: a full-atlas `RGBA16F` blit (8 MB at 1328x752) runs on every frame
with a nested mirror, even when only one small tile is read.

Confidence: Confirmed (by reading).

Suggested fix: blit only the tiles `_previous_lookups` refer to (their rects
grown by the gutter), which the pass already knows.

#### REF-m12. GL state left behind by the atlas

References: `OpenGLContext/passes/reflectionatlas.py:156-162` (clear colour),
`OpenGLContext/passes/reflectionatlas.py:83-92` and `168-171` (texture unbound on the active unit),
`OpenGLContext/passes/reflectionatlas.py:118` and `138` (read framebuffer set to the old draw binding)

Problem: `clear` sets `glClearColor(0,0,0,0)` and never restores it. `ensure_size`
and `end(mipmap=True)` bind and then unbind `GL_TEXTURE_2D` on whatever unit
is active. `keep` restores `GL_FRAMEBUFFER` to the previous draw binding,
which also overwrites a distinct read binding. None of these is known to break
a frame today, but they rely on every later user setting its own state.

Confidence: Confirmed (by reading).

Suggested fix: save and restore the clear colour (or set it in the caller
that clears the main target). Bind through a unit the atlas owns
(`REFLECTION_UNIT`) when it manipulates the texture. Save both framebuffer
bindings in `keep`/`begin`.

#### REF-m13. The atlas is bound on unit 31 while it is the draw target

References: `OpenGLContext/passes/flateffects.py:400`, `OpenGLContext/passes/flateffects.py:548-554`

Problem: at the end of each frame `atlas.bind()` leaves the atlas on
`REFLECTION_UNIT`. On the next frame, with no nested mirror (`bounce` False),
mirror views draw into that same texture while the lit program's
`planarReflection` sampler still names unit 31. The spec calls that a
rendering feedback loop if the program can sample the texture. The
`hasPlanarReflection` branch keeps it from sampling in practice, but the
behaviour is formally undefined.

Confidence: Possible.

Suggested fix: bind 0 (or the `kept` copy) on `REFLECTION_UNIT` before
`atlas.begin()` whenever `bounce` is False.

#### REF-m14. The logic that picks each mirror view's contents lives in the window-bound pass

References: `OpenGLContext/passes/flateffects.py:479-529`

Problem: `mirrorFrames` decides which inner mirrors are left out, which are
drawn without (and reported with `drawn_without`), and which views go into
`_incompleteMirrors`. This is the part of the feature that caused the recorded
flashing, and it can only be exercised through GL tests. The workspace rule is
to hoist such logic into a plain object.

Confidence: Confirmed.

Suggested fix: move the per-draw selection into a planner method that takes
the draw, the candidate records, `earlier`, `drawing` and `canonical`, and
returns `(kept, missing, incomplete)`. `mirrorFrames` then only builds
`ViewFrame`s and calls it. Test it without GL.

#### REF-m15. Surfaces' normal maps appear to invert vertical relief for the geometry they ship with

References: `OpenGLContext/scenegraph/surfaces.py:264-276`, `OpenGLContext/scenegraph/surfaces.py:342-353`,
`OpenGLContext/texture.py:239-242`

Problem: textures are uploaded with image row 0 at t = 0 (`pilAsString` flips
and then writes bottom-up). `surfaces.Geometry` sets v increasing up the
surface with tangent handedness +1, so the shader's bitangent points along +v,
which is increasing image row. `normal_map` writes green as `-dy`, where `dy`
is the slope toward row 0, so green is +dh/dv where the bitangent frame wants
-dh/dv. Horizontal joints (mortar, grout) would then light as if raised when
lit from above. The images are also shown upside down on walls (row 0 at the
bottom), which matters only for patterns with an up.

Confidence: Possible (derived from conventions; not rendered).

Suggested fix: render a one-sided ramp height map on a `panel` under a light
from +y, and assert the brighter half. If it confirms, flip `dy` in
`normal_map` (or write tangent `w = -1`) and flip v in `_facing_z`, `prism`
and `cylinder` so row 0 is the top.

#### REF-m16. Test gaps

References: coverage from the in-scope suites (213 passed):
`reflection.py` 90% (missing 204-207, 225, 251-255, 260-269, 280, 310, 320, 336-337, 340, 432, 509, 518),
`reflectionplanner.py` 95% (missing 267-268, 299, 324, 330, 333, 345, 410, 477-481, 503),
`reflectionatlas.py` 97% (missing 109-110), `mirrorhooks.py` 93% (missing 82, 85, 123-124),
`flateffects.py` reflection lines 329, 342, 371-373, 439, 471, 574 uncovered

Problem: untested behaviour includes the `IndexedFaceSet` path (REF-M8), the
moved-tile redraw (REF-M6), the millisecond target in the pass (REF-M3), zone
`allowed` refusal, the wireframe skip, `reset()`, the incomplete-atlas path,
a failed shared-program compile falling back to per-view draws (`break` at
`flateffects.py:574`), the hook's string-bool and bool-as-number branches,
and the hook's recursion into `level`/`choice`. `test_reflection_pass_logic.py`
builds `_FlatEffectsMixin()` bare, which is fine for the budget but means
`renderReflections`' own branches are only reached through GL tests.

Confidence: Confirmed.

Suggested fix: add planner tests for each missing branch (they need no GL),
an `IndexedFaceSet` mirror test, a GL test that forces `select_program_set`
to fail, and hook tests for `{"replace": "yes"}`, `{"scale": true}` and a
tagged `LOD`/`Switch`.

---

### Nit

- REF-n1. `OpenGLContext/passes/reflectionplanner.py:241-242` calls the private
  `reflection._texels`. `NDCRect`, `WHOLE`, `TEXEL_STEP`, `TileRect` and
  `mesh_plane` are public in use but missing from `reflection.__all__`
  (`reflection.py:44-53`), while `__all__` re-exports `WATER_DISTORTION` from
  another module. Make `texels` public and complete `__all__`.
- REF-n2. Draw records are untyped tuples read as `record[2]`, `record[3]`,
  `record[4]` and `record[5]` across `reflection.py`, `reflectionplanner.py`
  and `flateffects.py`. A `DrawRecord` `NamedTuple` or `Protocol` (placement,
  volume, path, node) would make this code readable and let mypy check it.

Question for the maintainer (REF-n2): Draw records are 6-tuples read by position across the passes. A `DrawRecord`
NamedTuple (sortKey, modelview, tmatrix, volume, path, node) made in
`FlatPass.renderSet` would let mypy check them and let code say `record.node`.
It is an engine-wide change: every pass and many tests build or index these
tuples, and constructing a NamedTuple costs about 0.05-0.1 us more per record
per view than a tuple (measured: 0.10-0.16 us against 0.05 us), on the hottest
loop of the frame. Positional reads keep working, so the change can be made
module by module. Do you want records to become a NamedTuple engine-wide (my
recommendation, built with `tuple.__new__` to keep the cost to ~0.05 us), or
kept as tuples with a documented layout?
- REF-n3. `_Shelf.slots: List[list]` holding `[x, width, key]`
  (`reflectiontiles.py:90-91`) is C-style. Use a small `NamedTuple`/dataclass.
- REF-n4. `_FlatEffectsMixin` declares mutable class-level defaults
  (`_reflection_lookups: Dict = {}`, `_previous_lookups = {}`,
  `_incompleteMirrors: set = set()` at `flateffects.py:115-120`). Each is
  reassigned before use today, but one in-place `.update()` would share state
  between passes. Initialise them per instance or use `None`.
- REF-n5. `ReflectedView.__getattr__` (`reflectionplanner.py:103-104`) recurses
  forever if `source` is not yet set (copy, pickle). Guard with `if name ==
  'source': raise AttributeError`.
- REF-n6. The `COPLANAR` grouping rounds to three decimals
  (`reflectionplanner.py:306-309`), so two planes 0.1 mm apart can straddle a
  rounding boundary and not group. The docs say "within a millimetre"
  (`docs/reflections.rst:72-73`). Cluster by tolerance, or say "rounded to".
- REF-n7. `_material` (`reflectionplanner.py:236-238`) reads only
  `appearance.material`, while `shape_reflector` falls back to
  `geometry.material`. A `PBRMesh` drawn without an appearance material has
  its roughness read as 0.
- REF-n8. `renderReflections` can call `triggerRedraw(0)` twice in one frame
  (`flateffects.py:359-361` and `394-396`).
- REF-n9. `reflectionBudget()` is evaluated twice per frame with mirrors
  (`flateffects.py:347` via `plan`, and again for `capacity` at 564).
- REF-n10. `ReflectionPlan.rough`'s docstring says a mirror "wants the blurred mip
  levels" (`reflectionplanner.py:152`), a perception verb. "reads" is the fact.
- REF-n11. `OpenGLContext/bin/mirrorhall.py` is scenery in the `bin` package of
  commands (the directory map says as much). It would sit better beside the
  demo data, or in a `demos`/`scenes` module, so `bin/` stays commands.

---

Question for the maintainer (REF-n11): `OpenGLContext/bin/mirrorhall.py` is the room `oglc-mirrors` hangs its mirrors
in; the directory map in CLAUDE.md already describes it as scenery in the
commands package. `OpenGLContext/demos/` is described as embedding samples
(a view inside a Tk or wx window), so moving it there would widen that
package's purpose. Options: leave it in `bin/` as documented; move it to
`OpenGLContext/demos/` and widen that package's docstring to "sample
applications and the scenery they share"; or add a `bin/scenery/` (or
`OpenGLContext/scenes/`) package for demo scenery (the mirror hall, and the
zones court in `bin/zones_demo.py` if wanted). I recommend leaving it in
`bin/` unless a second piece of shared scenery appears, at which point a
`scenes` package earns its place. Imports to update if moved:
`bin/mirrors_demo.py`, `tests/unit/test_mirror_hall.py`, docs/reflections.rst,
docs/surfaces.rst, CLAUDE.md.

### Documentation, demos and tutorials

Coverage is good. `docs/reflections.rst` explains the node and each field with
defaults, both hook placements with Blender and raw glTF examples, how
reflections are drawn, nested mirrors, settling, each budget setting with its
environment variable and default, the schedule's rules, the demo's keys, and
the limits. It is linked from `docs/index.rst` (toctree line 313, and the
feature list at 144), `docs/documentation.rst`, `docs/renderpasses.rst`,
`docs/multiview.rst`, `docs/water.rst`, `docs/gltf.rst`, `docs/telemetry.rst`
and `docs/overlayui.rst`. `docs/surfaces.rst` covers the procedural surfaces.
`oglc-mirrors` is a shipped console script (`pyproject.toml:99`) with the
documented keys, uses textured metal, marble, brick and water (which meets the
"interesting materials" preference), and has a docs picture. The plan
records what landed and where it departed from the design.

Inaccuracies and gaps:

- REF-d1 - `docs/reflections.rst:425-426` says "A driver whose fragment stage has 32
  texture units or fewer compiles reflections out". The gate is
  `texture_budget >= REFLECTION_UNITS_NEEDED` (32) at `pbrpass.py:403-404`, so
  32 units is enough. It should say "fewer than 32". (Confirmed)
- REF-d2 - The `mirrorhooks` module docstring (`mirrorhooks.py:21-39`) lists `scale`,
  `interval`, `priority`, `distortion` and `replace` but not `reflectance`,
  which `PARAMETERS` accepts. The Blender step at `docs/reflections.rst:148-152`
  lists the panel's fields without *Reflectance*, which the hand-off says was
  added to the panel. (Confirmed for the docstring; Likely for the panel)
- REF-d3 - `docs/reflections.rst:335-337` says a mirror's rising score means "none is
  left out for long". Lines 339-348 then describe mirrors crowded out of the
  atlas being left out on every frame, and REF-M2 leaves an unaffordable mirror
  out indefinitely. Say which case the first statement covers.
- REF-d4 - The `PlanarReflector.distortion` docstring and the docs say "view widths".
  The shader applies it in the mirror view's crop, whose width is the
  mirror's own rectangle, and uses the same factor for height. "Widths of the
  mirror's view" would be accurate.
- REF-d5 - `docs/reflections.rst:119-124` is a two-item list with bold in each item
  ("On a **material**", "On an **object**"). By the workspace rule on bold,
  plain words or a definition with a hyphen would read better.
- REF-d6 - There is no tutorial (a `tests/*.py` walkthrough) for mirrors. For a
  feature this central to the engine's showcase, a short one would help:
  a room, one `PlanarReflector`, `varied()`, water, and a look at the budget
  overlay.
- REF-d7 - The limits section does not say that a mirror drawn with an
  `IndexedFaceSet` must be counter-clockwise, which is true until REF-M8 is fixed.

---

### Checked and found sound

- `mirror_matrix`, `eye_plane` and `place_plane` are correct for the engine's
  row-vector convention. The normal goes through the inverse of the linear
  part, which is right under non-uniform scale and shear.
- `oblique_projection` is correct for the cropped, off-centre projection. With
  a diagonal-positive x/y scale, the sign of the clip-space plane matches the
  eye-space one, so Lengyel's corner choice holds. Numerically, points on the
  mirror map to NDC z = -1, points in front fall inside the range, and points
  behind fall outside it.
- `tile_transform`, `tile_bounds` and `atlas_lookup` agree with
  `planarSample` in `pbr.frag`. `planarMatrix` is uploaded untransposed from a
  row-major row-vector matrix, which is the GLSL column-vector form.
- Identity handling in the planner: `_Held` keeps strong references to the
  view and path, and validity checks `is`. `ReflectedView` keys by a
  never-reused serial. Both guard against `id()` reuse.
- `TilePacker` is stable in a crowded scene. In a scratch run with six mirrors
  and an atlas with room for two, the same two keep the same tiles on every
  frame and nothing oscillates.
- `ReflectionSchedule.choose` orders must-draw candidates with unusable tiles
  first (a stable sort on `valid` after sorting by score) and honours the view
  and separate-view counts it is given.
- Settling (`SETTLE_FRAMES`) and provisional lookups: provisional reflections
  are filtered from `_previous_lookups`, so they are never passed on to another
  mirror.
- GPU timing uses a ring of queries and never waits. Only one
  `GL_TIME_ELAPSED` user exists, so there is no nesting.
- `_drawMirrorViews` restores front face, `PBRMesh` draw state, HDR output,
  scissor and the active frame in a `finally`.
- mypy (`--follow-imports=silent`) and ruff are clean on all nine in-scope
  modules. There are no new `# type: ignore` comments.
- The 213 tests in the in-scope suites pass in 21 s. The GL tests use the
  shared `render_scene`/`gl_context` machinery and not hand-rolled GLFW.
- Prose: no history, selling, daring or apology phrasing in the in-scope
  docstrings or pages beyond REF-n10. `PlanarReflector` is registered in
  `basenodes` and declared in `basenodes.pyi`.
- Security: hook parameters are parsed by type without `eval`. No file paths
  or dynamic imports come from model content.

## Area 2: zones (ZON)

Scope: `OpenGLContext/scenegraph/zones.py`, `scenegraph/zone.py`, `passes/zonepass.py`,
`passes/zonelayers.py`, `passes/zoneprobes.py`, `loaders/gltf/zoning.py`, `loaders/gltf/shapes.py`,
`shaders/_zone_inc.glsl` and the zone parts of `pbr.frag`/`pbrpass.py`/`_flat.py`, `audio/areas.py`,
`audio/scene.py`, `physics/zones.py`, `scenegraph/tilesterrain.py` (zones mount), their tests
(`tests/unit/test_zones.py`, `test_zone_layers.py`, `test_pbr_zones.py`, `test_gltf_zones.py`,
`test_audio_areas.py`, `test_tilesterrain_zones.py`, `tests/helpers/_zone_*.py`), the docs
(`docs/zones.rst`, `docs/zones-internals.rst`, `docs/extensions/OGLC_zone.rst`) and the plans
(`plans/GLTF-SPATIAL-ZONES.md`, `plans/GLTF-SPATIAL-ZONES-HANDOFF.md`).

Reproductions are in the scratchpad (`zrepro1.py` to `zrepro4.py`); each runs with the workspace
venv and no GL, using the `ZonedPass` fake from `tests/unit/test_pbr_zones.py`.

### Overall assessment

The arithmetic layer is good. `scenegraph/zones.py` has correct signed-distance functions for every
shape (checked against the standard box, round-cone, capped-cone and ellipsoid-bound formulations),
a clean layering model that the CPU and GLSL implement the same way, and a thorough spec with
examples that the tests load. The GL-free split (`zones` / `zonelayers` / `CaptureSchedule`) follows
the "hoist the logic out of the window" rule.

The weak part is the render pass's per-object cache in `zonepass.py`. It is keyed on `id()` of
objects that die and on matrix identity. It does not include the zone *settings*, and it has no
way to see a change in an object's scale or bounds. Six of the findings below are stale-answer
bugs that come from this. I reproduced all six. Three of them have clear visual consequences: a
runtime edit to a zone does nothing, an image-lit zone never lights while any zone moves, and an
instanced group keeps the wrong zones after a member moves. The cache also fails under load:
one moving zone reclassifies every object every frame (125 ms/frame for 5,000 objects), and a
first frame of 20,000 objects allocates 443 MB. Other findings:

- The loader lets a malformed optional extension abort the whole document.
- Any scene with zones overwrites the application's audio reverb every frame.
- The typecheck gate fails on these modules (47 errors).
- The render and cost tests turn a crash into a skip.

The documentation is broad and clean of the prose signs. It needs corrections in several places,
the plan status is stale, and there is no shipped demo.

Findings: 0 Critical, 11 Major, 17 Minor, 11 Nit.

---

### Major

#### ZON-M1. A zone's settings changed at runtime are ignored until the zones are re-keyed

- `OpenGLContext/scenegraph/zone.py:262-292` (`placed_zones` cache key)
- `OpenGLContext/passes/zonepass.py:157-187` (`placeZones`: tables rebuilt only on `keys != self._tableKeys`)
- `OpenGLContext/passes/zonepass.py:270-275` (pack reused unless probe layers changed)

The placement cache key is the shape fields plus priority and blend; the `settings` MFNode and
each setting's own fields are not part of it. `_environmentTable`/`_slackTable`/`_allTable` are
rebuilt only when the tuple of `PlacedZone` ids changes, and `_zoneEpoch` only moves then too. So:

- editing `ZoneEnvironment.intensity` (or `enabled`, `capture`, `light`) has no effect on any object
  already classified: the intensity is baked into the cached `ZonePack` (`pack_reach`), and a repack
  happens only when `_probeVersion` moves *and* the probe layers differ;
- adding a `ZoneEnvironment` (or `ZoneLights`) to an existing zone puts it in `_environmentZones`
  but not in `_environmentTable`, so no object is ever classified against it.

`docs/zones.rst:31-38` and the plan both present zones as scene state "edited in the editor like any
other scene state"; `openglcontext-editor` builds zones.

Evidence (`zrepro1.py`):

```
1. before edit intensity 0.2
1. after edit intensity (expected 0.9) 0.2
1b. env zones before 0 table 0
1b. env zones after 1 table 0
1b. pack for object inside the newly-lit zone (expected a pack): None
```

Confidence: Confirmed.

Fix: observe the zone's `settings` field and each setting node's fields. The scenegraph's
field-observer cache that `boundingvolume` and `transformMatrix` use would serve. Bump
`_zoneEpoch` and rebuild the tables when anything changes. At minimum, fold a settings signature
(ids and field values of each setting) into the `placed_zones` key and into `keys`. Add a test that
edits `intensity`, toggles `enabled`, and adds a setting to a placed zone.

#### ZON-M2. An object that scales, or whose bounds change, while its origin stays put keeps its old zones

- `OpenGLContext/passes/zonepass.py:278-295` (`_current`)
- `OpenGLContext/passes/zonepass.py:386-405` (`_sphere`)

`_current` accepts a new matrix whenever the new *origin* is within `slack` of the old one. It never
compares scale or rotation-with-offset changes to the radius it measured, and it never looks at
`bvolume`. A node that grows in place (an animated scale, a door that swings open about a hinge
at its origin with its geometry far from it) and a node whose bounds change under the same
matrix both keep a classification that is no longer true. Examples of the second are an
`InstancedShape` whose placements move, a particle system, and a skinned mesh. `_walkPaths`
itself says the volume "is asked of every node every frame rather than remembered" for exactly
the `InstancedShape` case (`passes/_flat.py:1375-1381`).

Evidence (`zrepro1.py`): a 2 m box at the centre of a 10 m zone, then scaled by 20 in place:

```
2. small object inside: kinds [0 0 0 0] slack 3.267949192431123
2. scaled x20 object (crosses the edge, expected kind 1): [0 0 0 0]
2. fresh classification of the same: [1 0 0 0]
```

The 40 m object is still treated as wholly inside, so its outside faces take the room's
lighting. Confidence: Confirmed (scale). Likely (bounds change under an unchanged matrix, from
reading).

Fix: store the radius-determining scale (`max row norm`) and the bounds object's identity or
version in `_ObjectZones`. `_current` returns False if the new scale exceeds the stored one or the
bounds changed. The simplest sound rule is that the slack shortcut applies only when the upper
3x3 is unchanged, which is one `np.array_equal` on nine floats.

#### ZON-M3. Instanced groups compare member matrices by `id()`, which CPython reuses, so a moved member goes unnoticed

- `OpenGLContext/passes/zonepass.py:485-495`

`placed = tuple(id(record[2]) for record in members)` is stored and compared on the next frame.
The matrices are not kept alive by the cache, so a moved member's new transform array is often
allocated at the address of the one it replaced. The group then keeps its old box and zones.
The existing test (`test_pbr_zones.py:469-487`) keeps the old matrices alive in `members`, so it
cannot see this.

Evidence (`zrepro2.py`, new record list per frame as the pass builds it):

```
3. matrix ids reused: True kinds after member moved out (expected kind 1 straddle): [0 0 0 0]
```

Confidence: Confirmed.

Two related smells. The group key is the tuple of *visible* member path ids, which changes as
culling changes, so a camera panning over a forest makes a new `_GroupBox` and a new
`_zoneObjects` entry for almost every frame's subset. Those accumulate until `KEPT_LIMIT`
(50,000). A dead `_GroupBox`'s id can then be reused by a new one, and `_current` accepts it
whenever the old slack is positive, because both are centred at the world origin under an
identity `where`. Separately, the two generator passes over every member, every group, every view,
every frame, are O(instances) of Python.

Fix: hold the matrix objects themselves (a tuple of references) and compare with `is`, or compare
the stacked translation rows with `np.array_equal`. Key the group entry by the group's stable
identity (geometry and appearance key from `build_instance_groups`) rather than by the visible
subset, and evict entries with the group.

#### ZON-M4. Any zone moving evicts every `EXT_lights_image_based` zone's probe layer, so those zones never light

- `OpenGLContext/passes/zonepass.py:167-175` (`placeZones` calls `self._zoneCaptures.keep(alive)` with zone ids)
- `OpenGLContext/passes/zonepass.py:585-590` (image lights are keyed by `id(light)`, not zone id)
- `OpenGLContext/passes/zonepass.py:598-603` (an evicted light is dropped from `_imageLights`)

`keys` is the tuple of `id(PlacedZone)`, and a new `PlacedZone` is made whenever any zone moves.
Adding or removing a zone changes it too. `keep(alive)` is then called with the *zone* ids. Image
lights reserve their layer under `id(light)`, so every image-light reservation is freed. The
next `uploadImageLights` drops the light, the draw reserves it again (reading `SCENE_PROBE` that
frame), and the next frame's `placeZones` evicts it again. With one moving zone in the scene
(a lift, a vehicle interior, a zone under an animated transform), every image-lit zone reads the
scene probe permanently and nothing is ever uploaded. With a zone added or removed, every image
light re-uploads and flickers to the sky for a frame. The baked glisteel worlds use exactly this
path for all 56 zones.

Evidence (`zrepro3.py`, fake probe, one image-lit room and one other zone):

```
still: probe layer read ... [-1.0, 1.0, 1.0, 1.0, 1.0, 1.0]   uploads: [1]
move:  probe layer read ... [-1.0, -1.0, -1.0, -1.0, -1.0, -1.0]   uploads: []
```

Confidence: Confirmed.

Fix: call `keep()` with every live key, which is the zone ids plus `id(light)` for each live
zone's `ZoneEnvironment.light`. Better, key reservations by the owning zone. Also, a zone moving
should not change the key set used for liveness: compare `id(zone.zone)`, not `id(PlacedZone)`,
for eviction, and keep the epoch bump for "moved".

#### ZON-M5. One moving zone reclassifies every object in the scene every frame

- `OpenGLContext/passes/zonepass.py:167-184` (every placement change bumps `_zoneEpoch` and rebuilds all three tables and the AABB tree)
- `OpenGLContext/passes/zonepass.py:278-281` (`held.epoch != self._zoneEpoch` makes everything stale)

The epoch is global, so a zone that moves by a millimetre invalidates every object's answer,
including objects hundreds of metres away. The rebuilt tables include the `DynamicAABBTree`.
The class docstring and the plan promise "a static level pays for it once", which holds only
while nothing zoned moves.

Evidence (`zrepro2.py`): 10 zones, 5,000 static objects, one zone creeping:

```
5. objects reclassified per frame with one zone moving: [5000, 5000, 5000] 125.4 ms/frame
```

That alone is below 8 fps on the CPU. Confidence: Confirmed.

Fix: make invalidation spatial. When a zone moves, update its tree entry
(`DynamicAABBTree.move`) and mark stale only the objects whose cached `kept`/`reach` includes that
zone, or whose box overlaps the old or new reach of the zone. That needs a reverse index from zone
to objects, which the classification already produces. Keep the global epoch for add/remove only.

#### ZON-M6. `classify_many` materialises objects x zones x 8 corners at once, which gives a large first-frame spike

- `OpenGLContext/passes/zonelayers.py:181-223`

The candidate zones are found from the union box of *all* the moved boxes
(`self.near(low_in.min(axis=0), high_in.max(axis=0))`). On the first frame, and after any epoch
bump (ZON-M5, `KEPT_LIMIT`), that union covers the whole world. The code then builds several
`(W, M*8, 3)` float64 arrays (`local`, its transpose, `low`, `high`) and loops over rows in
Python.

Evidence (`zrepro2.py`): 56 box zones strung along a line, 20,000 objects on the first frame:

```
4. first-frame classify of 20000 objects over 56 zones: 2.89s, peak 443 MB
```

Confidence: Confirmed.

Fix: chunk `items` (for example 1,024 at a time), and query the tree per object or per spatial
bucket instead of by the union box. The tree query is cheap, and a per-object candidate list keeps
W small. The inner `for at in np.flatnonzero(...)` Python loop could build `(zone, inside)` lists
from the boolean arrays with `np.nonzero` over the whole `(M, W)` matrix.

#### ZON-M7. A malformed `OGLC_zone` block aborts loading of the whole document

- `OpenGLContext/loaders/gltf/zoning.py:266-292` (`zone_for`: `int(...)`, `float(...)`, SFVec3f
  coercion, `_environment`, `_reverb`, none guarded)

The spec (rule 8) makes `OGLC_zone` an `extensionsUsed`-only extension that a viewer can ignore.
The borrowed-extension readers are guarded (`finish` catches `TypeError`/`ValueError`), but the
zone's own fields are not. Any of these raises out of `load_gltf`:

```
priority "high"            -> load raised ValueError invalid literal for int() ...
blend "x"                  -> load raised ValueError could not convert string to float: 'x'
2-element box size         -> load raised ValueError Field exposedField SFVec3f size ... could not accept value (2.0, 3.0)
environment intensity "dim"-> load raised ValueError could not convert string to float: 'dim'
capture position short     -> load raised ValueError Field ... captureCentre ... could not accept value (1.0,)
```

(`zrepro4.py`). The box case comes from `shapes.read_shape`, which accepts `size[:3]` of any
length, so its own `try` never fires. Confidence: Confirmed.

Fix: wrap the body of `zone_for` (from the shape lookup to `Zone(...)`, plus `_environment` and
`_reverb`) in the same `(TypeError, ValueError)` guard, `warn` once, and return None. In
`read_shape`, require exactly three sizes. Add the cases above to `test_gltf_zones.py::TestReading`.

#### ZON-M8. Any scene with zones writes the audio engine's reverb every frame, overwriting the application's

- `OpenGLContext/audio/areas.py:76-80`
- `OpenGLContext/passes/zonelayers.py:556-579` (`reverb_at` returns `Reverb()` with level 0 when no zone has a reverb)

`apply_zones` always sets `engine.reverb.level/decay/damping`. A scene whose zones only dim
lighting (the Parthenon without its reverb, a cave with a `ZoneEnvironment`) therefore forces the
reverb to 0 each frame. Code that sets `engine.reverb` itself sees its setting last one frame.
This is the pattern `audio/scene.py:95-99` warns against for `master_gain`. It also writes
`decay=1.2` (the `Reverb` default) while the node's default is 1.5 (`zone.py:132`).

Confidence: Confirmed (from reading; `reverb_at` with no `REVERB` candidates returns `Reverb()`).

Fix: touch the reverb only when some zone carries a `ZoneReverb`, and restore the application's
value when the listener leaves every reverb zone. That means remembering the value found before
the first write, or blending the zones over it rather than over zero. Use one default decay.

#### ZON-M9. When the last zone goes, emitters keep their zone gain and the reverb keeps its level

- `OpenGLContext/audio/scene.py:105-108` (`if zones:` guards the call)

`apply_zones` is skipped once `zones` is empty. Emitters named by a zone that was just removed
keep `zoneGain` at whatever it was (often 0, so they stay silent for the rest of the session).
The reverb also stays at the last zone's level. Unloading a world's zones document, switching a
level, or an editor deleting the last zone all reach this. Confidence: Confirmed (from reading).

Fix: when zones go from some to none, reset `zoneGain = 1.0` on every emitter and clear the
reverb (see ZON-M8). Alternatively, always call `apply_zones`, which handles an empty list correctly.

#### ZON-M10. The zone modules fail the project's own mypy gate

`mypy --follow-imports=silent` with the project config over the nine zone modules reports 47
errors in 5 files. These do not come from the editable-install `Any` problem: they are local
optionals, missing mixin attributes and a real argument-type mismatch.

- `OpenGLContext/passes/zonepass.py`: 14 `union-attr` on `_ObjectZones | None` (`zoneState`, 252-276),
  `call-overload` on `dict.get(Hashable)` (658, 661), `var-annotated` for `_reflection_lookups`
  (745), and `attr-defined` for every pass method the mixin calls (`applyViewFrame`, `renderSet`,
  `setupViewLighting`, `shaderRenderOpaque`, `clearPlanarReflection`, `currentBackground`). The
  `if False:` declaration block at 95-101 lists attributes but none of these methods.
- `OpenGLContext/passes/zonelayers.py:412,475`: `setting.intensity` / `setting.enabled` on `ZoneSetting | None`.
- `OpenGLContext/physics/zones.py:58`: `GravityVolume(field, ZoneRegion(...))` is an `arg-type`
  error. `omi_physics` declares the region as `SphereRegion | BoxRegion | InfiniteRegion | None`.
  Either omi_physics needs a `Region` protocol or this is using an undeclared extension point.
- `OpenGLContext/scenegraph/zones.py` (7) and `zone.py` (2): `no-any-return`.

The hand-off (`plans/GLTF-SPATIAL-ZONES-HANDOFF.md:49-51`) records that preflight was not run.
Confidence: Confirmed in the workspace venv. The errors listed are independent of sibling
resolution, so they will reproduce in `.preflight-venv`.

Fix: use `if TYPE_CHECKING:` with a `Protocol` for the pass surface the mixin needs. Narrow
`held` after `_classify` (return the `_ObjectZones` from `_classify`). Add a `Region` protocol to
`omi_physics.gravity` (the right place, per "fix it where it belongs") and implement it in
`ZoneRegion`. Wrap numpy returns in `np.asarray(..., dtype=float)` or annotate.

#### ZON-M11. The zone render and cost tests turn a crash into a skip

- `tests/unit/test_pbr_zones.py:300-307` (`if not os.path.exists(out): pytest.skip(...)`)
- `tests/helpers/_zone_cost_harness.py:94-100` (every exception exits 3) and `test_pbr_zones.py:363-364` (exit 3 means skip)

A traceback in the capture helper (a zones bug, a shader compile error, a segfault) produces no
PNG, and the four `TestRenders` tests skip. In the cost harness *any* exception, including one
from the zone code, becomes "no usable GL context", and the performance test skips. The workspace
rules say a test that has to be skipped to get a green run is a broken suite. A crash here must
fail.

Confidence: Confirmed (from reading).

Fix: skip only on the specific "no GL" condition (`testing.glcontext.gl_available()` checked in
the parent, or a dedicated exit code raised only from context creation). Otherwise assert
`returncode == 0` and show `stderr`. In the harness, catch only the context-creation failure.

---

### Minor

#### ZON-m1. A failed capture throws away the whole schedule and retries every frame

- `OpenGLContext/passes/zonepass.py:769-772`

`except Exception` logs `'zone capture failed: %s'` without `exc_info` and sets
`self._zoneCaptures = None`. That forgets every zone's layer and every image-light reservation.
The next draw requests the capture again and `_askForFrame()` keeps frames coming, so a
persistent failure logs an error and redraws six whole-scene faces every frame. Confidence:
Likely.

Fix: keep the schedule and mark only that zone failed (stop asking after one failure, with a
retry on `lost()`). Log with `log.exception` once.

#### ZON-m2. `probe.convolve` returning False repeats a capture forever

- `OpenGLContext/passes/zonepass.py:675-680`

If the cube is whole but `convolve` returns False (a layer out of range after a failed `grow`,
or `probe.ready` flipping), `finished` is never called. `wanted` stays positive, and `next()`
returns the same zone every frame, redrawing six faces. Confidence: Possible.

Fix: count attempts per capture and give up with a log line, or call `schedule.lost()` to
reallocate.

#### ZON-m3. `_drawCapture` mipmaps the capture cube on every partial frame and after a failure

- `OpenGLContext/passes/zonepass.py:774`, `OpenGLContext/passes/zoneprobes.py:265-272`

`target.end(whole=True)` is unconditional. With `zoneCaptureFaces < 6` (the documented way to
spread cost) every frame runs `glGenerateMipmap` on a half-drawn cube, and it runs again after
an exception. The `whole` parameter exists but the caller never passes False. Confidence:
Confirmed.

Fix: `target.end(whole=schedule.drawn(...))`, deciding `drawn` before `end`, or mipmap inside the
`if schedule.drawn(...)` branch.

#### ZON-m4. `CaptureTarget` GL names are never released with the context

- `OpenGLContext/passes/zoneprobes.py:209-285`, `OpenGLContext/passes/zonepass.py:732-736`

`release()` is called only when the probe size changes. Nothing registers the cube, the depth
renderbuffer or the FBO with `contextresources`, so a context torn down while zones exist leaks
them, and a pass reused on a new context would bind names from a dead one. Confidence: Likely.

Fix: register through `OpenGLContext.contextresources` as the IBL probe and the selection
buffers do, or release in the pass's teardown.

#### ZON-m5. The capture path reaches into `CaptureSchedule` internals

- `OpenGLContext/passes/zonepass.py:676` (`schedule._captures[key].layer`)

`layer_of(key)` already exists. Confidence: Confirmed. Fix: use `schedule.layer_of(key)`.

#### ZON-m6. `zoneCaptureFaces` reads the environment every frame, bypassing the read-once memo

- `OpenGLContext/passes/zonepass.py:620-625`

`renderoptions.env_number(...)` is evaluated as the default argument on every call. The project
rule is `env_number_once` ("each is read once"). The `ContextDefinition` field default already
reads the variable (`contextdefinition.py:240-243`), so the fallback here duplicates it with its
own default (`FACES_PER_FRAME` against a literal 6). Confidence: Confirmed.

Fix: `renderoptions.number(self, 'zoneCaptureFaces', FACES_PER_FRAME)` and let the field own the
environment default. Import `FACES_PER_FRAME` in `contextdefinition`, or define it there.

#### ZON-m7. Mutable class-level defaults on the mixin, patched with `__dict__.setdefault`

- `OpenGLContext/passes/zonepass.py:104-154`, `587`, `649`

`_zones = []`, `_environmentZones = []`, `_controlledLights = {}`, `boundLights = []` and
`_imageLights = {}` are class attributes shared across every pass instance. `_imageLights` is
protected only by `self.__dict__.setdefault('_imageLights', {})` at two call sites.
`uploadImageLights` deletes from `self._imageLights` without that guard, which is safe today only
because the class dict is empty. `ZoneTable.nearness` uses the same `'_ids' not in self.__dict__`
trick (`zonelayers.py:285`). Confidence: Confirmed (smell; no live bug found).

Fix: initialise per-instance state in one `_initZones()` called from `FlatPass.__init__`, or use
`None` sentinels as `_zoneObjects` does. Compute `_ids` in `ZoneTable.__init__`.

#### ZON-m8. Light-zone classification is per object and per zone, in numpy calls

- `OpenGLContext/passes/zonelayers.py:454-479` (`light_decision`), called per object from `zonepass.py:351-355`

`_classify` batches the environment zones through the table, but then calls `light_decision` for
each object. That runs `zone.shape.classify` (several numpy calls) for every light zone. With
many lit rooms and many moving objects, this dominates `_classify`. Confidence: Confirmed (from
reading).

Fix: keep a `ZoneTable` of the light zones (the `_slackTable` already contains them) and classify
with `classify_many` in the same pass, then run `stacked` per object.

#### ZON-m9. Per-frame Python loops over zones with a numpy call each

- `OpenGLContext/passes/zonepass.py:652-656` (every capturing zone's `weight(camera)`, every frame, even after `camera_inside` has fired)
- `OpenGLContext/passes/zonepass.py:858-887` (`mirrorAllowed`: every zone's `weight(eye)` for every mirror, plus an import per call)

These are O(zones) numpy calls per frame, and O(mirrors x zones) for mirrors. `ZoneTable` already
answers all weights at a point in one pass (`point_weights`). Confidence: Confirmed.

Fix: compute `point_weights(self._allTable, camera)` once per view and pass it to both, as
`apply_zones` does. Skip zones whose `camera_inside` has already been recorded.

#### ZON-m10. Zone-owned lights still render shadow maps for every view

The plan's phase 3 includes "no shadow pass for a zone-owned light that no visible object is
zoned into" (`plans/GLTF-SPATIAL-ZONES.md:347-348`). Nothing in `passes/shadow*.py` consults
zones, and the hand-off does not list this as a departure. A level with a door spot per room pays
every room's shadow map every frame. Confidence: Confirmed (grep finds no zone use in the shadow
passes).

Fix: have the shadow planner skip a light in `_controlledLights` when no `_zoneObjects` entry
visible this frame has it in its `lights` decision. Otherwise record the gap in the plan and in
the docs' Limits.

#### ZON-m11. Zones apply only to the PBR program; the Limits section does not say so

- `docs/zones.rst:253-267`

`set_zones`/`set_lights_off` exist only on `PBRShaderProgram`. `applyZones` duck-types on
`hasattr`, so in the flat core pass (`flatcore.py`) and for geometry drawn with the VRML97
programs (`vrml97_lighting.frag`, `vrml97_vertex_color.frag`, both of which read the light block)
zone lights stay on everywhere. The terrain and vegetation programs are also unaffected by
`ZoneLights`. The Limits section mentions only the environment, and says the terrain, vegetation
and water shaders "have environment lighting of their own". Only `pbr.frag` samples the IBL
probes. Confidence: Confirmed (grep for `_lights_inc`, `iblMode`, `irradianceMap`).

Fix: add `lightsOff` to `_vrml97_lighting_inc.glsl`, and to the terrain and vegetation programs
where they take punctual lights, or state precisely which programs honour zone lights and
environments.

#### ZON-m12. `chosen` keeps `kept[0]` as though it were the zone the object is inside

- `OpenGLContext/passes/zonelayers.py:367-385`

The docstring and the warning ("crosses %d zones", `len(kept) - 1`) assume that `kept[0]` is the
wholly-inside base. When the object is inside no zone, `kept[0]` is the lowest-priority, largest
straddled zone, and it is kept regardless of distance from the camera. The warning count is then
one short. Confidence: Confirmed (from reading).

Fix: keep the head only when `kept[0][1]` (inside) is true. Otherwise choose all
`MAX_ZONE_LAYERS` by nearness.

#### ZON-m13. Gravity volumes are built once and never follow a moving zone

- `OpenGLContext/physics/zones.py:37-75`, `physics/gltf_world.py:204-206`

`collision_world_from_scene` snapshots the zones. A zone moved at runtime changes where lighting,
audio and visibility apply but not where gravity does. `docs/zones.rst:96-98` says "A zone moved
at runtime is placed again on the next frame" without qualification. `scene_zones` also walks only
`children`, so a zone under a `Switch`'s `choice` or an LOD `level` is found by the render pass
but not by physics. Confidence: Confirmed (from reading).

Fix: give `ZoneRegion` a live reference to the zone and its path (or update volumes per step from
the pass's placed zones), and walk the same child fields the pass gathers. At least document the
snapshot.

#### ZON-m14. `TilesTerrain` loads the zones document synchronously and joins its name without checks

- `OpenGLContext/scenegraph/tilesterrain.py:234-250`

`name` comes from the tileset's `extras` and is joined with `os.path.join(base_uri, name)` or
`base_uri + name`, with no check that it stays under the tileset. An absolute path or `../` loads
any local glTF. The load is on the constructing thread and any failure propagates, so a missing
or corrupt `zones.gltf` fails the whole world rather than loading it without zones. Confidence:
Confirmed (reading). The path escape matters only for untrusted tilesets.

Fix: reject absolute names and `..` components, as `contentpacks`' safe extraction does. Catch
load errors, warn and continue without zones. Consider the background load pool.

#### ZON-m15. `omi_audio` pin does not cover the reverb the zones drive

- `pyproject.toml:44` (`omi_audio>=0.2.0a1`)

`omi_audio.reverb` (omi_audio `fbb7c10`) is not in any omi_audio tag; `v0.3.0a1` does not contain
it. `apply_zones` degrades silently (`getattr(engine, 'reverb', None)`), so against any released
omi_audio every `ZoneReverb` does nothing and nothing reports it. Confidence: Confirmed
(`git merge-base --is-ancestor fbb7c10 v0.3.0a1` is false).

Fix: release omi_audio with the reverb and raise the pin. Log once when a scene has a
`ZoneReverb` and the engine has no `reverb`.

#### ZON-m16. No numeric test holds the GLSL distances to the Python ones

- `tests/unit/test_pbr_zones.py:62-67`

The only check is that the string `kind == N` appears in the include, and the cylinder is excused
as a fall-through. The GLSL and Python versions already differ in small ways: the ellipsoid guard
is `1e-6` against `1e-12`, and the capsule guards `h` differently. The renders exercise only box
zones. A transcription error in the capsule, cylinder or ellipsoid branches would pass every test.
Confidence: Confirmed.

Fix: a `gl_context` test that draws a full-screen quad through `zoneDistance` for sample points
(or uses transform feedback) and compares with `zones._distance` for every kind, including a
tapered cylinder and an uneven capsule.

#### ZON-m17. The cost test measures only intensity zones, not the probe-array path the hand-off names as the gap

- `tests/helpers/_zone_cost_harness.py:59-64`, `plans/GLTF-SPATIAL-ZONES-HANDOFF.md:90-96`

The hand-off attributes glisteel's 68-to-40 fps drop to per-fragment probe-layer sampling in
`envIrradiance`/`envRadiance`: up to four layers, twice for irradiance. The harness uses
`ZoneEnvironment(intensity=0.3)` only, which folds into the scene probe, so the expensive path is
untimed. The ratio (`1.6x + 0.5 ms`) could not catch that regression anyway. Also, `irrBack`
still samples all layers whenever diffuse transmission is on. Confidence: Confirmed.

Fix: add a `probes` mode with four image-lit layers (the `imagelight` scene from
`_zone_capture.py`) and time it, with a tighter bound on the intensity-only case.

---

### Nit

#### ZON-n1. Dead code and test-only paths in the engine modules

- `OpenGLContext/passes/zonepass.py:910` `CAMERA_KEYS` (unused, not in `__all__`).
- `zonepass.py:407-412` `_classifyObject` (used only by a test).
- `zonepass.py:53-70` `_ObjectZones.local` and `.radius`: always `None`/unused. `_sphere` returns
  `(None, radius, centre)` with a vestigial `None` (386-405).
- `zonelayers.py:289-301` `ZoneTable.distances` (unused; duplicates `_signed`) and `reaching`.
- `zonelayers.py` `environment_layers`, `reach`, `classified`, `lights_off` are exported and
  tested, but the pass uses `classify_many` + `stacked` + `chosen` + `light_decision`. The unit
  tests of `TestEnvironmentLayers` and `TestLightsOff` therefore exercise a path production does
  not run. `test_pbr_zones.py:420-440` partly bridges it.
- `zonepass.py:890-906` `cameraShares`, `zoneReverb`, `zoneControlled`: no caller in the
  workspace and not documented.

Fix: delete, or document as public API and have the pass use the same functions.

#### ZON-n2. `_allTable` and `_nearness` are declared in the middle of the method list

`zonepass.py:189-190`, `421-423`. Put them with the other state at the top.

#### ZON-n3. `if False:` instead of `typing.TYPE_CHECKING`

`zonepass.py:95`.

#### ZON-n4. Avoidable `# type: ignore`s

`scenegraph/zones.py:223-224`, `scenegraph/zone.py:205`, `loaders/gltf/shapes.py:68`,
`loaders/gltf/zoning.py:230`, `passes/zoneprobes.py:248`. Each builds a `tuple(... for v in x)`
where a fixed-length tuple is required. Write `(float(a[0]), float(a[1]), float(a[2]))` or a small
`_vec3()` helper.

#### ZON-n5. Bare generic annotations

`zonepass.py:813,815` `frozenset`, `898` `set`, `zonelayers.py:455` `Tuple[frozenset, bool]`,
`zoning.py:257-258` `List[tuple]`, `set`. Use `FrozenSet[int]` and similar.

#### ZON-n6. `ZonePack.key` built from `id(PlacedZone)`

`zonelayers.py:98`. It is safe within a view today because packs are recomputed on an epoch
change, but it depends on the lifetime of the old `PlacedZone`. `id(placed.zone)` plus the
placement's matrix identity is the stable key.

#### ZON-n7. Two falloff curves for the same idea

`audio/areas.py:24-41` `box_gain` is linear. Zones are smoothstep (`zones.weight`). The plan said
`box_gain` becomes the axis-aligned case of the zone distance. The hand-off records keeping it.
`point_weights` (`zonelayers.py:510-519`) repeats the smoothstep formula a third time. Share
`zones.weight`.

#### ZON-n8. `ZoneGravity.type` shadows a builtin as a field name

`zone.py:171`. It matches `OMI_physics_gravity`, so keep it, but note the choice in the docstring.

#### ZON-n9. Review bookkeeping in shader comments

`OpenGLContext/shaders/pbr.frag:511` `"(finding 4.4)"`. This is text moved into the new
`envIrradiance` in this range, so it is newly written text. CLAUDE.md lists bare finding numbers
as history. Drop the parenthesis.

#### ZON-n10. `register_scoped` returns `Any`

`zoning.py:89`. Use `@overload` for the decorator and call forms so an application's reader keeps
its type.

#### ZON-n11. `placed_zones` silently drops a zone with an unknown `shapeType`

`zone.py:282-285`. A typo in code-built zones (`shapeType='Box'`) makes the zone vanish with no
log line. Warn once per zone.

---

### Documentation, demos and tutorials

Coverage is broad. `docs/zones.rst` is the guide, `docs/zones-internals.rst` covers internals,
and `docs/extensions/OGLC_zone.rst` is a Khronos-style spec with a JSON schema and 2.0/2.1
example files that the tests load. All three are indexed from `docs/index.rst` and
`docs/documentation.rst`. `docs/pbr.rst`, `docs/environment.rst` and `docs/audio.rst` link to
them. The `/ai-isms` scanner (`--all`) finds nothing in any of the 13 zone files. Problems:

- ZON-d1 - The plan is stale. `plans/GLTF-SPATIAL-ZONES.md:3` still says "Planned — Plan only, awaiting
  review". `plans/PROJECT-PLAN.md:40` says "📋 Planned ... at most two zones per draw ... Plan only
  — awaiting review", while the code ships four layers (`MAX_ZONE_LAYERS = 4`). The hand-off
  (item 7) lists the departures to record and they have not been recorded. The plan's `autoPlay`
  (line 280) should be `autoplay`.
- ZON-d2 - There is no demo. No `oglc-*` command or `tests/*.py` tutorial shows zones. The workspace
  convention is that a feature's demo is an installed `oglc-*` command covering the documented
  uses. The only examples cited are the external Parthenon and glisteel. Plan phase 2 said
  `bin/audio_demo.py`'s cave and stream areas become zones; the demo still uses `box_gain`
  (`bin/audio_demo.py:181-184`). A small `oglc-zones` scene covering all four would serve as both
  showcase and visual regression: a dim room with a doorway straddler, a captured probe, a door
  light and an audio area.
- ZON-d3 - `docs/zones.rst:96-98` ("A zone moved at runtime is placed again on the next frame") is true for
  rendering only. Settings edits are not picked up (ZON-M1), and gravity is a snapshot (ZON-m13).
- ZON-d4 - `docs/zones.rst:122-124` lists the extensions read in a zone but omits
  `EXT_lights_image_based`, which `zoning.py:198` registers and the same page documents at 175-181.
- `docs/zones.rst:264-266` claims that the terrain, vegetation and water shaders "have
  environment lighting of their own". Only `pbr.frag` samples the IBL. The same section should
  state that zone lights do not apply to the VRML97, terrain or vegetation programs, or to the
  flat core pass (ZON-m11).
- ZON-d5 - `docs/zones.rst:205-206` reads as a flourish: "A car in a tunnel hears its own engine and tyres
  come back off the walls." The sentence before it already states what the reverb does.
- ZON-d6 - `docs/zones-internals.rst:111-116` says the per-object answer is cached against `_zoneEpoch`,
  "which counts ... a capture finishing, a probe being lost, the lights being bound in a different
  order". Those events move `_probeVersion` and `_slotVersion`. Only placement changes move
  `_zoneEpoch`, and settings changes move nothing (ZON-M1).
- ZON-d7 - `docs/zones-internals.rst:99` and `130` name `environment_layers` and `lights_off` as what the
  pass runs. The pass runs `ZoneTable.classify_many`/`stacked`/`chosen` and
  `light_decision`/`light_mask`.
- ZON-d8 - `openglcontext/CLAUDE.md` directory map ("Keep this list complete"): `passes/` lists `ibl.py`,
  `reflection*.py` and others, but not `zonepass.py`, `zonelayers.py` or `zoneprobes.py`, and
  `scenegraph/` does not list `zone.py`/`zones.py` or `imagebasedlight.py`.
- ZON-d9 - The spec's rule 3 says `"KHR_lights_punctual": false` turns lights off "for what is inside". The
  code darkens only an object *wholly* inside (`light_decision`'s `dark = dark or inside`). A
  straddling object keeps every light. State the per-object rule in the spec.

### Checked and found sound

- Signed distances in `zones.py` and `_zone_inc.glsl`: box, sphere, ellipsoid bound, round cone
  (including the one-sphere-swallows-the-other and zero-height cases) and capped cone match the
  standard formulations. The shifts of the capsule's and cylinder's origins to the shape centre
  are correct.
- `place()`: row-norm scale extraction for row-vector matrices, SVD orthonormalisation (a mirror
  stays a mirror), and the world-to-local inverse are correct. The `reach` for each kind encloses
  the shape.
- `ZoneTable` world boxes: `sum_i |R_ij| * reach_i` is the correct extent of an oriented box in
  row-vector form.
- `layers()` / `named_shares()` and the GLSL `zoneShares` agree: bottom-first packing, top-down
  accumulation, and disabled layers taking share and giving it to nothing.
- `stacked()` correctly drops everything below the topmost wholly-inside zone.
- `sphere_slack` is sound as a conservative bound for pure translation. The reach-box OUTSIDE test
  can mis-sort an object only between "outside" and "straddles", which changes cost, not the
  weight.
- `set_zones` uploads a row-vector matrix untransposed, which GLSL reads as the column-vector
  matrix it multiplies by. The uniform arrays are sized by `MAX_ZONE_LAYERS`, which the pass
  injects as a define and a test holds equal.
- `lightsOff` bit width: `maximumLights` is capped at 8 (`contextdefinition.py:305`) and
  `_flat.MAX_LIGHTS` is 8, so `1 << slot` fits an `int` uniform.
- `refreshZones` and `applyZones` rely on matrix identity, which `_walkPaths` documents as stable
  while a node is unmoved (`_flat.py:1393-1400`). The shortcut is correct for pure translation;
  ZON-M2 and ZON-M3 cover where it breaks.
- `_drawCapture` restores the planar-reflection lookups, the HDR output flag, the draw state and
  the active view frame in `finally`. `CaptureTarget.begin/end` restore the caller's FBO and
  viewport.
- `CaptureSchedule` is GL-free and its layer reuse, bounces, camera-inside recapture and loss
  recovery are unit tested (`test_zone_layers.py::TestCaptureSchedule`).
- `loaders/gltf/shapes.py` version selection (2.1 core against 2.0 `KHR_implicit_shapes`, 2.1
  preferring core) matches the spec and is tested against its examples. Reader errors in borrowed
  extension blocks are contained and reported once per document.
- ruff is clean over every zone module.

## Area 3: render passes and shaders (PASS)

Scope: `OpenGLContext/passes/` (`_flat.py`, `flateffects.py`, `flatcompat.py`, `flatcore.py`, `pbrpass.py`, `shaderpass.py`, `shaderpass_shadow.py`, `shadersource.py`, `shadowmixin.py`, `shadowmath.py`, `ibl.py`, `bloom.py`, `instancing.py`, `gputimer.py`, `renderstats.py`, `selection.py`, `asyncpick.py`, `viewpointbinding.py`, `renderpass.py`), the changed shaders (except `_zone_inc.glsl`), `scenegraph/imagebasedlight.py`, `octahedral.py`, `hdrbackground.py`, `spherebackground.py`, `shaders.py`, `loaders/hdr.py`, `loaders/background.py`, `renderoptions.py`, `frustum.py`, and the PERF commits (`1b9d2b6`, `51948ab`, `42acffc`, `68ed4be`, `55c449c`, `a754a50`, `7e1b051`). Paths are relative to `openglcontext/`. Line numbers are for HEAD.

### Overall assessment

The range turns a single-camera pass into a frame of several views with one walk of the scene, adds planar reflections, zone probes, image-based lights, octahedral impostors and multi-view program sets, and reworks the hot loops (frustum test, caster geometry, winding signs, texture mask) into array expressions. Most of the arithmetic holds up: I checked `frustum.boxes_outside` against a brute-force eight-corner test on 5000 random affine boxes and got 0 mismatches, and the cube-face, SH and octahedral mappings are consistent with each other. The problems are in lifecycle and cache invalidation. Two new memos (the PBR batching memo and the level-of-detail memo) return stale answers, and I reproduced both. The pass now owns several new per-context GL resources that nothing releases when a scene swap replaces the pass. The frame gather has two handoff mechanisms, and one of them is cleared part-way through a frame by the legacy pick path. With several views, shadows depend on the active view's draw list. `_flat.py` is now 2497 lines. Multi-view orchestration and planar-reflection orchestration (in `flateffects.py`) have both grown into the pass and its effects mixin rather than into mixins of their own, and `renderShared` repeats `setupViewLighting` line for line. Two genuine mypy errors are in the gate. `1b9d2b6` (the batching memo) shipped without a test. The docs are broadly present (`multiview.rst`, `reflections.rst`, `lod.rst`, `pbr.rst`, `renderpasses.rst`, `loading.rst`), but `flat.rst`, `lod.rst` and `renderpasses.rst` still describe some code paths as they were before this range.

### Critical

None found.

### Major

#### PASS-M1. The pass's new GL resources are never released when a scene swap replaces the pass
- `OpenGLContext/passes/renderpass.py:89-100` (`_dispose`), `:103-124` (`cached_pass`)
- `OpenGLContext/passes/flateffects.py:~381` (`_reflection_timer = GpuTimer()`), `:~364` (`_reflection_atlas = ReflectionAtlas()`)
- `OpenGLContext/passes/_flat.py:1913-1934` (`_viewTable`)
- `OpenGLContext/passes/ibl.py` (arrayed probe, `_convolvers`)
- `OpenGLContext/passes/shaderpass.py:409-456` (`_program_sets`)

Problem: `cached_pass` builds a new pass whenever the scenegraph reference changes, which is every level or scene load. On the old pass, `_dispose` calls only `disposeShadowMaps`. This range adds pass-owned GL objects that nothing frees:
- the reflection atlas: a window-sized, mip-mapped HDR texture plus its FBO and a "kept" copy (`atlas.keep()`)
- the `GpuTimer` query ring
- the multi-view `ViewBlock` UBO
- the zone-capture target
- the IBL probe, now possibly a cube-map array grown to a power of two of layers, plus its kept convolution programs
- the multi-view program sets compiled per `(strategy, views)`

`ReflectionAtlas.release`, `GpuTimer.release` and `IBLProbe.release` exist, but no caller reaches them. None of these classes has a finalizer, which is deliberate so that GC never calls GL. A game that loads levels leaks tens of MB of GPU memory per load once mirrors or zone probes are in use.

Evidence: `grep -n "\.release()" OpenGLContext/passes/*.py` finds only internal self-calls (`reflectionatlas.py:82,109`, `ibl.py:425,437`, `zonepass.py:735`). `_dispose` reads `if hasattr( pass_, 'disposeShadowMaps' ): pass_.disposeShadowMaps()` and nothing else.

Confidence: Confirmed (by reading).

Fix: give `FlatPass` a `disposeResources()` that each mixin extends through `super()`. The shadow pool, reflection atlas and timer, view table, zone targets, IBL probe and bloom targets each release their own objects. Call it from `renderpass._dispose` and from context teardown. Add a GL test that swaps the scenegraph twice with a mirror in it and checks that `glIsTexture` returns false for the old atlas.

#### PASS-M2. The PBR batching memo (`1b9d2b6`) returns stale answers when a shape becomes a mirror or its textures change in place
- `OpenGLContext/passes/pbrpass.py:1034-1063` (`batchers`)
- `OpenGLContext/scenegraph/pbrmaterial.py:151-162` (`_UBO_FIELDS`)

Problem: the memo signature is `(id(geometry), id(appearance), id(material), material._ubo_version, id(appearance.texture), collapse)`. `_instanceable` also depends on `reflection.shape_reflector(shape)`: `material.reflector`, `reflector.enabled` and `geometry.waveStyle`. None of those is in the signature, and `reflector` is not in `_UBO_FIELDS`, so setting it does not bump `_ubo_version`. The same gap applies to the batch key: `geometry_texture_key` reads the material's `textures` dict, and an in-place `material.textures['baseColor'] = t` does not bump the version either. Once memoised, a mesh that becomes a mirror is still batched. `shaderRenderOpaque` then calls `clearPlanarReflection()` for every instanced group, so the mirror draws with no reflection. Several identical mirror tiles are exactly the case that batches.

Evidence (`scratchpad/review/repro/batchers2.py`, a geometry without `instanceContentKey`, as `PBRMesh` has none):
```
before: instanceable True direct True
after reflector: instanceable (memo) True direct False
```
The commit touches no test file (`git show --stat 1b9d2b6`), so it was never red/green.

Confidence: Confirmed.

Fix: add `reflection.mirror_generation()` to the signature, or clear the memo when it moves. Add `'reflector'` to `_UBO_FIELDS`, or better, give the material a separate "batching generation" bumped by `reflector`, `textures` and `octahedralViews`. Add a test that memoises, sets `material.reflector`, and asserts that the next grouping makes the mirror a single.

#### PASS-M3. The level-of-detail memo ignores the LOD node's own fields
- `OpenGLContext/passes/_flat.py:1223-1250` (`_levelsAlreadyChosen`)

Problem: the memo key is the path generation, the identities of the world matrices, and the camera bytes. A change to `range`, `screenCoverage`, `radius`, `center`, or any other field that decides the level is invisible to it. A settings screen that changes LOD distances, or a tool editing a node, has no effect until the camera or the object moves.

Evidence (`scratchpad/review/repro/lodrange.py`):
```
level at 15m, range [10,20]: 1
after range -> [30,40], nothing moved: 1 (expected 0)
```

Confidence: Confirmed.

Fix: include a per-node version in the key. A dispatcher watch on LOD's level-deciding fields, bumping a module counter as `reflection.mirror_generation` does, would serve. Add the repro above as a test in `tests/unit/test_lod_multiview.py`.

#### PASS-M4. With several views, spot/point/directional shadows disappear from every view when the active view draws nothing that casts
- `OpenGLContext/passes/_flat.py:1627-1631`
- `OpenGLContext/passes/shadowmixin.py:166-204`

Problem: `Render` calls `self.renderShadowMaps(toRender)` with `toRender = active.toRender` only. `renderShadowMaps` resets `_shadow_bindings = []`, then returns early when that list is empty after the `castsShadow` filter, or when `_occluderPoints` finds nothing bounded. Every view, and every mirror view, then binds zero shadow maps. `docs/shadows.rst:135-139` and `docs/multiview.rst:602-607` say that spot and point maps do not depend on the camera and that every view reads them. That does not hold when the active view looks at the sky, at an empty tile, or at an overlay-only view.

Evidence: code path as quoted. No test in `tests/unit/test_multiview_shadows.py` covers an empty active view.

Confidence: Likely (the control flow is confirmed; the visual consequence was not rendered).

Fix: separate "is there anything to cast" from "what are the cascades fitted to". Take the early-out from the caster pool (`_refreshCasterData`) or the union of all views' records. Only the directional cascade fit should use the active view's points, falling back to the pool's bounds. Add a two-view test with the active camera turned away.

### Minor

#### PASS-m1. The legacy pick path clears the frame's gather, so reflections and zone captures are skipped on frames with a pick event
- `OpenGLContext/passes/_flat.py:1600-1604` → `selectRenderViews` (`:2034-2055`) → `finishViews` (`:2489-2495`, `self._frameGather = None`)
- `OpenGLContext/passes/flateffects.py:327-329`
- `OpenGLContext/passes/zonepass.py:726`

Problem: in the shader path with `use_mrt_selection = False`, a pick event runs `selectRenderViews`, and its `finishViews()` drops `_frameGather` before `renderZoneProbes` and `renderReflections` run. `renderReflections` has already set `_reflection_lookups = {}` and returns, so every mirror shows only the probe for that frame, and the flicker follows the mouse. The capture schedule stalls the same way.

Confidence: Confirmed (by reading).

Fix: split `finishViews` into "restore the window's viewport and scissor" and "end the frame's gather", and call only the first from `selectRenderViews`. Or keep the gather in a frame-scoped object that `Render` owns.

#### PASS-m2. Two handoff mechanisms for one frame's gather
- `OpenGLContext/passes/_flat.py:159-162` (`_gathered`), `:1335-1358` (`gatherPaths`/`takeGather`), `:1845` (`_frameGather`)
- `docs/renderpasses.rst:352-362`

Problem: `prepareViews` publishes the same table twice. `_gathered` is consumed once by the shadow pool, and `_frameGather` is read by mirror views and zone captures until `finishViews`. The `takeGather` docstring argues that a table must never be left lying about, and `_frameGather` is exactly such a table. The docs describe only `takeGather`. PASS-m1 is the consequence.

Confidence: Confirmed.

Fix: one frame-scoped holder, for example a `FrameState` created in `Render` and cleared in a `finally`, passed to the shadow pool, mirrors and zones. Document it in `renderpasses.rst`.

#### PASS-m3. mypy errors in the declared gate
- `OpenGLContext/passes/instancing.py:647` (`winding_signs` returns `ndarray.tolist()` → Any)
- `OpenGLContext/passes/_flat.py:731` (`batchingFunctions` returns `getattr(...)()` → Any)

Evidence (run with `.preflight-venv/bin/python -m mypy --follow-imports=silent` on the working-tree files):
```
OpenGLContext/passes/instancing.py:647: error: Returning Any from function declared to return "list[int]"  [no-any-return]
OpenGLContext/passes/_flat.py:731: error: Returning Any from function declared to return "tuple[Any, Any]"  [no-any-return]
```

Confidence: Confirmed.

Fix: `return [int(s) for s in np.where(d < 0, -1, 1)]`, or `cast(List[int], ...)`. Declare `batchers` on a Protocol, or annotate the local: `found: Tuple[Callable[[Any], Any], Callable[[Any], bool]] = batchers()`. The same fix types the `(key, instanceable)` pair properly rather than as `Tuple[Any, Any]`.

#### PASS-m4. Octahedral impostor half-texel inset is hard-coded for a 512-pixel tile
- `OpenGLContext/shaders/pbr.vert:~135` (`float inset = 0.5 / float(impostorGrid * 512);`)

Problem: the inset assumes an atlas of `grid*512` pixels, which is 4096 for 8 views. The documented and default bake is a 256-pixel atlas with 8 views, or 32-pixel tiles (`docs/lod.rst:239-244`; `openglcontext-editor/.../impostor.py: bake_atlas(image=256)`). The inset is then 1/8192 where half a texel is 1/512, so bilinear filtering and mip levels read across into the neighbouring view along every tile edge.

Confidence: Confirmed (by reading).

Fix: pass the atlas size as a uniform (for example `impostorTexels`, set from the texture's width in `set_impostor`), or compute `textureSize(baseColorTexture, 0)` in the vertex stage. Add a GL test with a 256-pixel, 8-view atlas whose tiles have saturated edges.

#### PASS-m5. Impostors cast shadows as their raw quad
- `OpenGLContext/scenegraph/shape.py:117-123` (depth path from `7e1b051`)
- `OpenGLContext/shaders/shadow_depth.vert`
- `OpenGLContext/passes/pbrpass.py:842-848`

Problem: the billboard transform lives only in `pbr.vert` and is switched by `impostorGrid`, which is set on the lit program in `configure_appearance`. The depth pass (`depthDraw` / `use_depth`) draws the authored quad in model space with no turn-to-viewer and no alpha test. An impostor therefore casts a fixed rectangle, or a sliver when seen edge-on from the light. The glTF loader does not set `castsShadow = False` for impostor materials.

Confidence: Likely.

Fix: either skip impostor materials in `_shadowCasterRecords`, or have `shadow_depth.vert` and `.frag` honour `impostorGrid`, turning the quad to the light and alpha-testing the atlas. Document whichever limit is chosen in `lod.rst`.

Question for the maintainer (PASS-m5): Impostors are now left out of the shadow maps (18bde6e), because the depth
pass drew the authored quad, not the card turned to the viewer, and cast a
fixed rectangle. The fuller answer is a light-facing impostor shadow: the depth
program honours impostorGrid, turns the card to the light, picks the tile for
the light's direction and alpha-tests the atlas, which needs the base colour
texture and texcoords bound in the depth pass (no depth-pass alpha test exists
for any material today). Should distant impostors cast shadows? Recommendation:
not now. At impostor distances a shape is usually past the finest cascades,
and the coarse mesh levels before the impostor already cast; revisit together
with alpha-tested shadows for foliage.

#### PASS-m6. Bloom with several views leaves the uncovered part of the window unwritten
- `OpenGLContext/passes/flateffects.py:862-877` (`_end_bloom`)
- `OpenGLContext/passes/bloom.py:318-341`
- `OpenGLContext/passes/_flat.py:2379-2394` (`clearUncovered`)

Problem: `clearUncovered` runs inside the bloom FBO and clears the HDR target. With more than one view, `composite(rects)` draws only the tiles into the window. A layout that leaves a band (the case `clearUncovered` exists for) shows whatever the back buffer held. With a single partial view `rects` is None and the whole window is composited, so that case is correct.

Confidence: Likely.

Fix: when `rects` do not cover the target, composite the full window once with a zero-strength bloom, or `glClear` the previous FBO before the tile composites.

#### PASS-m7. Every visible record is scanned for mirrors every frame, even in a scene with none
- `OpenGLContext/passes/flateffects.py:259-352` (`renderReflections`)
- `OpenGLContext/passes/reflectionplanner.py:293-315` (`_seen`)

Problem: with planar reflections enabled, which is the default wherever the program compiled them in, `planner.plan` walks `frame.toRender` for every view and calls `reflector_for` (0.23 µs a call, measured) plus the loop overhead. That is about 1 to 2 ms a view a frame at 5000 visible shapes, spent on a scene without a single mirror. `sceneMirrors()` already caches the scene's mirror indices.

Confidence: Confirmed (cost measured on the call; the whole-frame figure is estimated).

Fix: in `renderReflections`, return early when `not len(self.sceneMirrors())`, and let the planner consider only records whose gather index is in that set.

#### PASS-m8. `renderShared` repeats `setupViewLighting`
- `OpenGLContext/passes/_flat.py:1983-1990` versus `:885-901`

Problem: the eight lines from `setupShaderLights` to `setupZones` are copied, with `fitted=True`. The next lighting stage added to one will be missed in the other.

Confidence: Confirmed.

Fix: `self.setupViewLighting(matrix, lighting, fitted=True)`.

#### PASS-m9. `_flat.py` and `flateffects.py` are absorbing whole subsystems
- `OpenGLContext/passes/_flat.py` (2497 lines; multi-view orchestration at `:1845-2055` and `:2326-2495`)
- `OpenGLContext/passes/flateffects.py` (planar-reflection orchestration at `:257-594`)

Problem: `layoutViews`, `prepareViews`, `applyViewFrame`, `sharesViews`, `sharesDraw`, `sharedRecords`, `uploadViewTable`, `renderShared`, `frameForEvent`, `eventsByView`, `selectRenderViews`, `clearUncovered`, `finishViews` and `chooseMultiview` are a multi-view subsystem, and `OpenGLContext/multiview/` already exists. Planar reflections are about 350 lines of the "effects" mixin, whose `TYPE_CHECKING` block now declares more than 20 attributes of the pass it assumes. `Render()` is still one long phase list with shader/legacy, MRT/async/legacy-pick and bloom branches interleaved. The zones are already a `ZonesMixin`, which is the pattern to follow.

Confidence: Confirmed.

Fix: extract a `MultiviewPassMixin` (in `multiview/` or `passes/multiviewpass.py`) and a `ReflectionsMixin` (beside `reflection.py`), each with a Protocol for what it needs from the pass. Turn the shared state (`viewFrames`, `activeFrame`, gather, lighting) into one frame object passed through `Render`.

#### PASS-m10. Directional cascades, and point-light culling, follow the main views only
- `OpenGLContext/passes/shadowmixin.py:519-532` (`_pointLightInView`)

Problem: `_pointLightInView` tests the point light's sphere against `viewFrames`, which excludes mirror views. A point light behind the camera but visible in a mirror gets no cube map, so its shadow disappears in the reflection. This is the same family as PASS-M4.

Confidence: Possible.

Fix: include the planned mirror frames. Or, since spot and point maps are camera-independent and cached, render them whenever any mirror is planned.

#### PASS-m11. `_instance_divisor` is stored on the mesh GPU object, not with the VAO whose state it is
- `OpenGLContext/passes/instancing.py:986-991`
- `OpenGLContext/scenegraph/pbrmesh.py:185-194`, `indexedlineset.py:425-433`

Problem: `release()` resets `_instance_vao = None` but keeps `_instance_divisor`. A rebuilt VAO has divisor 1 while the memo may say `copies`, so the next shared `vertex` draw sends every instance's data to the wrong copies.

Confidence: Possible.

Fix: set `gpu._instance_divisor = 1` in `_build_instance_vao`, beside `gpu._instance_vao = vao`.

#### PASS-m12. The geometry-stage generator's parse of vertex outputs is narrow
- `OpenGLContext/passes/shadersource.py:52-53` (`_OUTPUT_RE`), `:71-79`

Problem: only `[flat] out type name;` is recognised. `layout(location=…) out`, `smooth`/`noperspective`/`centroid`, arrays, multi-declarators and interface blocks are missed. An `out` inside a disabled `#if` block is picked up, and the generated stage then declares an input the vertex stage never writes, which is a link error. Today's shaders avoid all of these, but the multi-view docs invite custom lit shaders. The failure is a compile error that silently degrades the frame to sequential views.

Confidence: Possible.

Fix: run the parse on the preprocessed source after the defines are resolved, or have lit vertex shaders declare their varyings in one include that the generator reads. At minimum, raise a `ValueError` naming any unrecognised `out` form.

#### PASS-m13. `IBLProbe.convolve` state handling does not match its docstring
- `OpenGLContext/passes/ibl.py:~736-773`

Problem: the docstring says "the caller's framebuffer, viewport and program are restored either way". The program is set to 0, not restored. `GL_DEPTH_TEST` and `GL_CULL_FACE` are force-enabled whatever they were, and `GL_BLEND` is left disabled.

Confidence: Confirmed.

Fix: say what is left ("no program bound; depth test and culling on, blending off"), or save and restore with the pass's own state memo.

#### PASS-m14. `ImageBasedLight.specular_faces` rotates by nearest-texel lookup, and `upload_light` fails on a light with no specular images
- `OpenGLContext/scenegraph/imagebasedlight.py:552-571`, `598-606`
- `OpenGLContext/passes/ibl.py:~810-818`

Problem: a rotated environment is resampled with `_sample` (nearest), which aliases visibly on the high-resolution mips. With `specular == []`, `min(level, count - 1)` indexes `specular[-1]` and raises. The exception is caught, but only after the irradiance map has been uploaded, leaving a half-filled layer.

Confidence: Confirmed (by reading).

Fix: sample bilinearly across the face; check `if not light.specular: return False` before touching the textures.

#### PASS-m15. `sceneAmbient` indexes three elements of any tuple or list
- `OpenGLContext/passes/_flat.py:903-917`

Problem: `context.gltf_scene_ambient = [0.1]` raises an IndexError every frame. The docstring also carries history ("DirectionalLight, PointLightIntensityTest read pale grey instead of dark + crisp lights").

Confidence: Confirmed.

Fix: accept a length-1 sequence as grey, or validate where the attribute is set. State the reason for the default in the present tense.

#### PASS-m16. `sceneMirrors` misses water geometry that becomes water
- `OpenGLContext/passes/flateffects.py:360-375`
- `OpenGLContext/passes/reflection.py:145-170`

Problem: `shape_reflector` treats any geometry with `waveStyle` as a mirror, but `mirror_generation` watches only `appearance`, `geometry`, `material`, `reflector` and `enabled`. Setting `waveStyle` on existing geometry is not picked up until the path set changes.

Confidence: Likely.

Fix: add the geometry `waveStyle` field to `_watch_mirror_fields`.

#### PASS-m17. `LoadPool` loses workers for good on a `BaseException`
- `OpenGLContext/loaders/background.py:180-195`

Problem: `except Exception` lets `SystemExit` (from a `sys.exit` in a callback, for example) end the worker thread. `_threads` still counts it, so no replacement starts. If every worker dies, queued work never runs and `wait_for_idle()` with no timeout blocks forever.

Confidence: Possible.

Fix: drop dead threads from `_threads` in `submit`, or catch `BaseException`, log it, and keep the worker alive, re-raising only for `KeyboardInterrupt` on the main thread.

#### PASS-m18. Test gaps for new branches
Nothing tests:
- `batchers`, including invalidation (PASS-M2)
- LOD memo invalidation (PASS-M3)
- an empty active view with shadows (PASS-M4)
- the legacy pick path with mirrors (PASS-m1)
- `sh_fit` / `encode_rgbd` in the engine (exercised only through the editor's bake)
- `IBLProbe.grow` / `convolve` / `upload_light` / `read_layer`
- `_pointLightInView` across several frames
- `sceneAmbient`
- `shadowmixin._local_box` caching
- `sharesDraw` / `sharedRecords` as units: they are pure-Python predicates and easy to test without GL, but are exercised only through rendered multi-view tests

Confidence: Confirmed (by grep of `tests/`).

Fix: add unit tests alongside the fixes above. The `_Path` fake in `tests/unit/test_lod_multiview.py` is reusable for PASS-M3 and for `sharedRecords`.

### Nit

#### PASS-n1. Review bookkeeping and history in comments and docstrings
- `OpenGLContext/shaders/pbr.frag:511`: "(finding 4.4)", moved into the new `envIrradiance` in this range. `pbr.frag:3` still says "(finding 5.3)".
- `_flat.py` `renderSet` docstring: "A frame of a few thousand objects was making tens of thousands of them".
- `sceneAmbient` (PASS-m15).

Fix: state the reason in the present tense and drop the finding numbers.

#### PASS-n2. Wrong or stale cross-references
- `OpenGLContext/shaders/_multiview_inc.glsl:2` names `OpenGLContext/passes/multiview.py`, which does not exist. The packer is `multiview/strategy.py: pack_view_table`.
- `_flat.py:114` says `SGObserver.gatherPaths`; `gatherPaths` is a `FlatPass` method.
- `_flat.py:163` says `_levelChoice` is what "the last `selectLevels` chose for"; it is set by `chooseLevels`, and the engine no longer calls `selectLevels` at all (only tests do).
- `scenegraph/lod.py:17` and `docs/lod.rst:103` say `FlatPass.selectLevels` chooses the levels each frame; `prepareViews` → `chooseLevels` does.
- `shaderpass.py:407` `MULTIVIEW_PROGRAMS`: "Each is compiled a second time with a geometry stage". The `vertex` strategy compiles without one.

#### PASS-n3. `renderShared(..., reflection: bool)` shadows the module-level `from OpenGLContext.passes import reflection`
`OpenGLContext/passes/_flat.py:1936-1939`. It works because the body never uses the module, but it is a trap for the next edit. Rename the parameter to `into_atlas`.

#### PASS-n4. Class-level mutable defaults
`_flat.py:2233` (`viewFrames: List['ViewFrame'] = []`) and `flateffects.py:107-112` (`_reflection_lookups: Dict = {}`, `_previous_lookups = {}`, `_incompleteMirrors: set = set()`). Each is reassigned before mutation today, but one in-place `.add`/`.update` would share state across passes. Initialise them in `__init__`, or declare the type only.

#### PASS-n5. `class GatheredPaths` follows a function body with no blank lines
`_flat.py:110-111`. PEP 8 E302; ruff's selected rules do not cover it.

#### PASS-n6. Silent `except Exception: pass`
Around `PBRMesh.reset_draw_state` in `renderViewShader` and `renderShared` (`_flat.py:~1834-1838`, `~2011-2014`), and in `_end_bloom` (`flateffects.py:874-876`). A failure in the reset or the composite leaves GL state wrong with no log. Use `log.debug(..., exc_info=True)` at least.

#### PASS-n7. `chooseLevels` logs a warning per broken LOD node per frame
`_flat.py:1195-1199`. It was `pragma: no cover` before. Rate-limit the warning, or mark the path `broken` as other code does.

#### PASS-n8. `_casterWorldGeometry` stores each entry into `current` twice
`shadowmixin.py:935-947`: once in the miss loop and again in the final loop.

#### PASS-n9. `PBRShaderProgram._textureUnits` caches through `self.__dict__` and an identity check on `ext_channels`
`pbrpass.py:814-821`. Compute the list once in `compile()`, where `ext_channels` is set.

#### PASS-n10. `set_impostor` runs for every shape
`pbrpass.py:842-848`. Two `getattr`s and two cache lookups per draw, ahead of the same-material early-out. Folding the impostor flags into the material's `_ubo_version`-keyed state would make it free for ordinary materials.

#### PASS-n11. `sharesDraw` detects "an appearance with its own program" as `hasattr(appearance, 'objects')`
`_flat.py:1874`. Name the capability, for example `appearance.bringsProgram`, or test the concrete class.

#### PASS-n12. `stats.shapes` now sums visible shapes across views
`_flat.py:1573`. A shape seen in two views counts twice. Say so in `renderstats.py`, or count unique paths.

#### PASS-n13. `Image.BILINEAR  # type: ignore[attr-defined]`
`ibl.py:~815`. Use `Image.Resampling.BILINEAR` and drop the ignore.

#### PASS-n14. `Any` where concrete types exist
- `lighting: Any` in `setupViewLighting` / `renderViewShader` / `renderShared` / `renderReflections` is `Tuple[str, Optional[IBLProbe]]` (`iblSetup` already says so).
- `GatheredPaths.matrices` / `points` / `bounded` / `drawing` are `np.ndarray`.
- `link_program` returns `Any`.
- The flateffects `TYPE_CHECKING` block types `_frameGather`, `activeFrame` and `stats` as `Any`.

#### PASS-n15. `modelproj` stays the untrimmed product after `prepareViews` trims `frame.projection`
`_flat.py:2445-2447`. This carries the pre-existing inconsistency. Recompute `frame.modelproj` where the projection is trimmed.

#### PASS-n16. `IBLProbe.grow` counts a fallback loss twice
Once in `grow`, and again in `release()` on the following rebuild. This is harmless because `lost` is only compared for change, but it makes the counter's docstring inexact.

### Documentation, demos and tutorials

The new behaviour has user-facing pages:
- `docs/multiview.rst`: layouts, strategies, the `OPENGLCONTEXT_MULTIVIEW` choice, shadows, bloom and picking per view, and the `viewpointPaths` / `OnViewpointsChanged` hooks.
- `docs/reflections.rst` and `docs/water.rst`: planar reflections and their budget options.
- `docs/zones.rst` and `docs/zones-internals.rst`: zone probes, including `EXT_lights_image_based`.
- `docs/lod.rst`: octahedral impostors, the atlas-size guidance and the cost table.
- `docs/pbr.rst:449-480`: the IBL controller's new 30-frame down-streak.
- `docs/loading.rst`: `load_in_background` / `wait_for_idle`.
- `docs/environment.rst`: the new environment variables.
- `docs/renderpasses.rst`: the gather, the six-element record, and the node-taking hooks.

A `tests/multiview_quad.py` demo exists, with a doc image (`docs/images/demos/multiview_quad.json`).

Gaps and inaccuracies:
- PASS-d1 - `docs/flat.rst:39-58` still describes the cull as "one matrix product carries [the corners] into world space; one more product tests them against the planes". It is now a per-box local AABB with the planes carried into box space (`frustum.boxes_outside`). The docstring of `_frustumSurvivors` is right; the page is not.
- `docs/lod.rst:103` names `FlatPass.selectLevels` as the per-frame chooser; see PASS-n2.
- PASS-d2 - `docs/renderpasses.rst:356-362` documents only `takeGather`, not `_frameGather`, which mirror views and zone captures read (PASS-m2). Its passes list (`:404-425`) omits `bloom.py`, `gputimer.py`, `shadersource.py`, `renderstats.py`, the `reflection*.py` modules and the `zone*.py` modules. The closing "the sequence above runs once for each view" is wrong for shadows, IBL preparation, zone captures and reflections, which run once a frame.
- PASS-d3 - `openglcontext/CLAUDE.md`'s directory map does not list `scenegraph/imagebasedlight.py` or `passes/renderstats.py`.
- PASS-d4 - The impostor shadow limit (PASS-m5) and the atlas-size coupling (PASS-m4) are not stated in `lod.rst`.
- PASS-d5 - `renderstats.py` documents the mirror counters. I found no page describing how the overlay shows `mirrorMilliseconds`, beyond the `overlayui.rst` mention of `planarReflections`.
- PASS-d6 - `ImageBasedLight` itself (fields, `rotation`, units of `irradiance_faces`) is described only in its module docstring. `gltf.rst` and `zones.rst` mention the extension without linking the node.

### Checked and found sound

- `frustum.boxes_outside` equals the eight-corner "all behind one plane" test for arbitrary affine row-vector transforms: 5000 random boxes, 0 mismatches (`scratchpad/review/repro/boxes.py`). `_frustumSurvivors`' corner min/max is conservative for non-AABB corner sets.
- `shadowmath.world_bounds` and `_CORNER_ENDS` broadcasting; `_casterGeometryBatch` grouping by point count and its `_casterGeometry` single-record wrapper.
- `instancing.winding_signs`: the determinant expression matches `_winding_sign`, and the non-stackable input falls back to the per-matrix form.
- The `imagebasedlight` cube conventions: `face_directions` matches the GL cube-map sc/tc/ma table for all six faces, `_sample` inverts it, and the `sh_fit` solid-angle weight `4/n² / (1+u²+v²)^1.5` is right. The editor multiplies by π before fitting, so the π factor in `irradiance_faces` round-trips.
- `encode_rgbd` / `decode_rgbd` bounds (D ≥ 1/255, rgb·D ≤ 1).
- `octahedral` hemi and full mappings are mutual inverses, and `pbr.vert: octahedralUV` matches `direction_to_uv`.
- `bloom.scaled_rect` / `tile_uniforms` clamp bounds at texel centres, and every tile ends its ping-pong in the same buffer, so `blurred` is shared correctly.
- `GpuTimer` never waits: it reads only `GL_QUERY_RESULT_AVAILABLE` queries, oldest first, and `end()` without `begin()` is a no-op.
- `hdr.py` header-line and pixel-count limits are applied before any allocation.
- `asyncpick._pickCamera` records each event's own view camera at submission, not at resolution.
- `renderShared` restores `glFrontFace(GL_CCW)`, `mirroredDraw` and the program set in its `finally`. `_drawMirrorViews` restores the scissor, HDR output and active view in its `finally`.
- `shaderpass._bind_program` always issues `glUseProgram`, so passes that bind their own programs mid-frame (IBL build, convolve, bloom) cannot leave it stale.
- `IBLController`'s down/up streak hysteresis with cooldown matches `pbr.rst`.
- `select_program_set` caches failures (`None`) so a broken set is not recompiled every frame, and `multiviewFailed` moves on to the next strategy.
- `spherebackground` enables and disables `GL_DEPTH_CLAMP` symmetrically.
- `ShaderURLField.subLoad` now closes the fetched file.
- `publish_viewpoints` notifies only on a changed set of path identities.
- ruff is clean on every file in scope.

## Area 4: multi-view, overlay UI, viewer, backends and openglcontext-qt (MV)

### Overall assessment

The multiview package is a well-factored piece of work. The GL-free parts
(`views`, `cameras`, `navigation`, `gestures`, `viewset`, `grid`, the
`strategy` capability decision, and the `ViewRecord` / std140 packing) are
hoisted out of the windowed classes and have unit tests. The layout arithmetic,
the ortho camera maths and the view-table maths all hold up when checked
numerically. `ruff` and `mypy --follow-imports=silent` pass on the new
modules. `docs/multiview.rst` is thorough.

The defects are at the seams between parts:

- A view's cached navigation keeps driving the camera it replaced.
- A view drawn through the context's own camera keeps the window's aspect
  ratio when it is given a tile.
- The new tooltip is never laid out, and is never woken up in a window that
  draws on demand.
- `point_view` loses the subject's size for anything smaller than about 20 m.
- `Context.routeEvent` breaks the hand-rolled events that `addPickEvent`
  promises to accept.
- The multi-view strategy is frozen at the first frame, although the settings
  screen offers it as a live field.
- `Grid` is public, but nothing draws it.

Across the backends, the pointer-shape guard for mouse-look is applied
unevenly. EGLContext still ignores the definition's profile and version, even
though a helper to honour them now exists beside it. The documentation also
has a few false statements (the aspect claim, a `placeViews` method that does
not exist, a GLSL comment naming a module that does not exist), and a number
of docstrings break the workspace writing rules.

### Findings

#### Critical

None.

#### Major

##### MV-M1 - A view keeps navigating the camera `point_view` / `look_through` replaced

`OpenGLContext/multiview/navigation.py:192-202`, `:305-317`;
`OpenGLContext/multiview/cameras.py:320-356`;
`OpenGLContext/multiview/viewpoints.py:120-150`;
`OpenGLContext/ui/viewchrome.py:677-687`, `:659-665`.

`ViewNavigation.__init__` captures `view.camera.view` and `turns` once.
`navigation_for` then returns the cached `view.navigation` whenever no `mode`
is passed. There are two ways a view's camera gets replaced with a new
platform:

- `point_view` replaces it when the family changes (ortho to perspective, or
  the reverse), which is the view chrome's *View* menu.
- `look_through` replaces it when an elevation is pointed through a scene
  camera, which is the *Cameras* menu.

Nothing clears `view.navigation` in either case. From then on every drag and
wheel notch moves the old, undrawn camera, and the new camera cannot be moved
with the pointer.

Reproduction (scratch `nav_stale.py`):

```
before OrthoView False ('pan', 'zoomin', 'zoomout', 'zoomdrag')
after OrbitView OrthoView False ('pan', 'zoomin', 'zoomout', 'zoomdrag')
True True                      # press + drag "taken"
orbit target moved? [0. 0. 0.] [0. 0. 0.]   # the drawn camera did not move
```

- Confidence: Confirmed.
- Fix: have `navigation_for` rebuild when `navigation.camera is not
  getattr(view.camera, 'view', None)`. To keep an application's rebinds, carry
  the old `mode` over when the new camera is of the same family. Add a test
  that drives `ViewGestures` after `point_view(view, 'perspective')` and after
  `look_through` on an elevation.

##### MV-M2 - A view drawn through the context's camera keeps the window's aspect ratio in a tile

`OpenGLContext/multiview/views.py:302-330` (`arrange` / `_tell`);
`OpenGLContext/passes/_flat.py:2345-2365` (`layoutViews`);
`OpenGLContext/move/viewplatformmixin.py:333`; `docs/multiview.rst:181-184`.

`ViewLayout._tell` tells only a view's *own* camera the size of its tile, and
the context's platform is told the whole window. `layoutViews` then calls
`setViewPlatform(context.getViewPlatform())` for a camera-less view, so the
projection uses the window's aspect ratio inside a tile of a different shape.

This affects several layouts that the documentation offers:

- `MultiViewMixin`'s perspective view, as soon as a splitter is dragged off
  centre.
- Every `ViewLayout.split(View(plan), View(name='angled'))`, which is the
  example in `views.py`'s module docstring and in `docs/multiview.rst:103`.
  There the tile is half the width, so the view is stretched 2x.
- A picture-in-picture inset drawn through the context's camera.

Reproduction (`aspect.py`, window 1600x900, quad split at 0.25):

```
tile (400, 0, 1200, 450) tile aspect 2.666 platform aspect 1.777
```

The docs say "A perspective camera then uses the rectangle's aspect ratio
rather than the window's", which is false for this case.
`test_multiview_render.py::test_a_perspective_view_takes_the_aspect_of_its_tile`
covers only views that have their own camera.

- Confidence: Confirmed.
- Fix: in `layoutViews`, derive the camera-less view's projection from its
  tile. One way is to call `viewMatrix()` with an explicit aspect. Another is
  to set and then restore `platform.setViewport(*view.size)` around the matrix
  computation. Add a render test that uses a camera-less view in a split.

##### MV-M3 - The tooltip is never laid out, so it draws as a 0x0 rectangle at the window's origin

`OpenGLContext/ui/overlay.py:566-586`, `:624-647`;
`OpenGLContext/ui/tooltip.py:59-71`; `OpenGLContext/ui/draw.py:676-706`.

`tooltipTree` returns a newly built `Tooltip` and `screenTrees` appends it to
`trees`. Nothing calls `Tooltip.layout`:

- `layoutOverlays` lays out only the panels on the stack.
- `ScreenMixin.screenTrees` lays out only the HUD layers.
- `drawTrees` never lays anything out.

The unit tests call `tip.layout(...)` by hand, which hides this.

Reproduction (`tip.py`, with the test module's `FakeContext`):

```
Tooltip rect Rect(x=0, y=0, width=0, height=0) anchor (400.0, 291.0)
```

- Confidence: Confirmed.
- Fix: lay the tip out in `tooltipTree`, or in `screenTrees` before it is
  appended, using the viewport and metrics already in hand. Add a test that
  asserts the tip's rectangle after `screenTrees`, not after a manual
  `layout`.

##### MV-M4 - In a window that draws on demand, the tooltip never appears

`OpenGLContext/ui/overlay.py:505-517`, `:624-647`;
`OpenGLContext/ui/screen.py:167-178`; `OpenGLContext/glfwcontext.py:560-575`.

The pause is measured from the last `mousemove`. That movement redraws once,
before the pause has elapsed. After that nothing asks for a frame:

- `redrawWhileAnimating` asks each tree's `animating(now)`, and a pending tip
  is not a tree.
- `OnDraw(force=0)` renders nothing when nothing changed.

The tip therefore shows only if something else happens to redraw. Moving the
pointer to trigger that redraw restarts the pause.

- Confidence: Likely (reasoned from the loop; not driven interactively).
- Fix: while `_pointerAt` is set, the hovered widget has a tooltip, and the
  pause has not expired, have `OverlayMixin` report itself as animating. The
  simplest place is to make `redrawWhileAnimating` also ask the overlay for a
  pending tip. Better still, schedule a one-shot redraw at
  `_pointerSince + TOOLTIP_PAUSE`.

##### MV-M5 - `point_view(view, 'perspective'|'ortho')` loses the subject's size below about 20 m

`OpenGLContext/multiview/cameras.py:349-355`;
`OpenGLContext/edit/orbitview.py:72` (`NEAREST = 20.0`).

The new `OrbitView` is built without `nearest`, so the distance is clamped to
20 m and dolly-in stops there. A 2-unit object in a front view becomes a
14.6-unit view that cannot be brought closer. The docstring promises
"showing as much as it showed". `look_through` passes `nearest=1e-6` and
`QuadView` fits `nearest` to the box, but `point_view` does neither. It also
leaves the pitch floor at `LOWEST = 1` (the view cannot go below the model),
while QuadView and `look_through` use `-HIGHEST`.

Reproduction (`pv.py`):

```
before ((0,0,0), 2.0)
after ((0,0,0), 14.558809370648094) distance 20.0 nearest 20.0
after dolly in 20.0
```

- Confidence: Confirmed.
- Fix: build the orbit with `nearest` and `furthest` scaled from `span` (as
  `QuadView.frame` does from the radius) and with `lowest=-OrbitView.HIGHEST`.
  Add a test asserting `shown_by` before and after a round trip.

##### MV-M6 - `Context.routeEvent` raises `AttributeError` for a hand-rolled event, which `addPickEvent` promises to accept

`OpenGLContext/context.py:1593-1604`, `:1620-1643`;
`OpenGLContext/events/eventhandlermixin.py:266-268`;
`OpenGLContext/multiview/gestures.py:406`.

The `addPickEvent` docstring says "An event object that does not offer one is
keyed as it always was, so a hand-rolled event still records". Its first line
is now `self.routeEvent(event)`, which reads `event.view` unguarded.
`ViewGestures.handle` does the same.

Reproduction (`route.py`):

```
raised AttributeError 'Ev' object has no attribute 'view'
```

- Confidence: Confirmed.
- Fix: in both places, use `getattr(event, 'view', None)` and set the
  attribute only where it can be set. Add a test with a duck-typed event.

##### MV-M7 - The multi-view strategy is fixed at the first frame; the settings screen's "Multi-view drawing" changes nothing

`OpenGLContext/passes/_flat.py:2231-2257`, `:2376-2377`;
`OpenGLContext/passes/flateffects.py:283-284`;
`OpenGLContext/contextdefinition.py:261-265`, `:337-339`, `:363`.

`multiviewStrategy` is set once on the pass, and the pass is cached per
scenegraph (`renderpass.cached_pass`). Nothing resets it when
`ContextDefinition.multiview` changes, yet the field is listed in
`DIAGNOSTIC_FIELDS` with `UI_HINTS` as a live choice. `Context.settingsChanged`
only triggers a redraw. The docs say the field "lets each be run and compared
on one machine", but that only works at start-up.

- Confidence: Confirmed (by reading).
- Fix: re-choose the strategy when the requested one differs from the one the
  current strategy was chosen for. Keep `(requested, strategy)` on the pass
  and compare each frame; `requested_strategy` is cheap. Otherwise, document
  the field as start-up only and take it off the settings screen.

##### MV-M8 - `multiview.grid` is public but not drawn, not exported, and not documented

`OpenGLContext/multiview/grid.py:1-181`.

The module docstring says "The grid is a node the application puts in its
scene, and each view is told whether to draw it". However:

- `Grid` is a plain class, not a node.
- Nothing in the engine calls `linesFor` / `lines_for`; the only users are
  `tests/unit/test_multiview_grid.py`.
- It is absent from `multiview/__init__`, from `docs/multiview.rst`, and from
  any demo.

The CLAUDE.md directory map does list it. As it stands, a game developer who
finds it gets arithmetic and no grid.

- Confidence: Confirmed.
- Fix: either finish it (a node or pass hook that draws `lines_for` per view,
  honouring `ViewStyle`, and a demo) or remove it until it is. In either case
  correct the docstring.

##### MV-M9 - `EGLContext` ignores the definition's profile and version

`OpenGLContext/eglcontext.py:565`, `:607-608`, `:243-279`.

`_createContext` calls `createContext(self.display, config)` with no
attributes, so the driver's default context is used. On Mesa and NVIDIA that
is a compatibility profile. It is used even for a `profile = 'core'` class, or
a definition asking for 4.x.

`contextAttributes()` and `PbufferContext` in the same module, added in this
range, do honour the profile. CLAUDE.md says every backend resolves the
definition first "since the profile, version and buffer formats are all
window-creation parameters". An offscreen EGL run of a core program therefore
accepts fixed-function calls that every windowed backend rejects.

- Confidence: Confirmed (by reading).
- Fix: `self._createContext(self.config, contextAttributes(definition.profile,
  definition.version, forwardCompatible=definition.profile == 'core'))`, with
  a test asserting `GL_CONTEXT_PROFILE_MASK` on an `EGLContext`.

##### MV-M10 - An interrupted archive extraction is cached as a complete world

`OpenGLContext/viewer/source.py:117-127`;
`OpenGLContext/contentpacks/archive.py:78-107`.

`_unpack` treats `os.path.isdir(where) and os.listdir(where)` as "already
unpacked". `archive.extract` writes straight into `where`. A failure partway
through leaves a non-empty directory, and every later open uses the partial
tree without complaint. Failures that can do this include a corrupt member, a
full disk, Ctrl-C, or a checksum failure after the size check passed.

- Confidence: Likely.
- Fix: extract into `where + '.partial-<pid>'` and `os.replace` it into place
  on success. Optionally write a completion marker and check for it. Remove
  the partial directory on failure.

##### MV-M11 - Backends handle the pointer-shape guard differently; under GLUT a hover can show the hidden mouse-look pointer

`OpenGLContext/glutcontext.py:223-236` versus `:253`;
`OpenGLContext/glfwcontext.py:380-402`; `OpenGLContext/pygamecontext.py:261-275`.

Tk, wx and Qt refuse `setPointerShape` while `_pointerGrabbed`. openglcontext-qt's
test states the rule: "Mouse-look hides the pointer; a hover must not put it
back". GLUT, GLFW and pygame have no such check. On GLUT, mouse-look hides the
pointer with `glutSetCursor(GLUT_CURSOR_NONE)`. Any `showCursor` that follows
calls `glutSetCursor(<shape>)` and makes it visible again. For example, the
warped pointer sits at the window centre, and in a quad that is the splitter
crossing. `OverlayMixin._cursorShown` also goes stale across a grab: GLUT's
release sets `GLUT_CURSOR_INHERIT` while the cache still says `'hand'`.

- Confidence: Likely for GLUT; Confirmed that the backends are inconsistent.
- Fix: put the `_pointerGrabbed` guard in every backend, or once in
  `OverlayMixin.showCursor` via `getattr(self, '_pointerCaptured', False)`.
  Reset `_cursorShown` when capture ends. Add the Qt-style test to
  `test_pointer_shapes.py` for each engine backend.

#### Minor

##### MV-m1 - The per-context capability cache is keyed by a raw handle and never evicted

`OpenGLContext/multiview/strategy.py:84-90`, `:212-229`.

`_DETECTED` is keyed by `platform.GetCurrentContext()`, which is an address.
Nothing hooks `contextresources.context_lost`, and `reset_detected` has no
caller. `testing/glcontext.py:449-454` says drivers "hand the same address out
again" over a suite's hundreds of contexts, so a context can inherit another's
answer. On macOS a legacy 2.1 context and a 4.1 core one differ completely.

- Confidence: Confirmed (by reading).
- Fix: register with `contextresources` so the entry is dropped when the
  context dies, or key by the context object.

##### MV-m2 - The fly-through path survives a scene change

`OpenGLContext/viewer/sceneviewer.py:205`, `:1001-1011`, `:473`.

`_flyPath` is computed once. `mountScene` replaces `self.viewpoints`, but
`_flyPath` is never reset, so a catalogue browser flies the previous model's
cameras.

- Confidence: Confirmed.
- Fix: reset `_flyPath = None` where `self.viewpoints` is assigned.

##### MV-m3 - `advanceFlyThrough` keeps asking for frames after the path ends

`OpenGLContext/viewer/sceneviewer.py:1027-1036`.

It returns True on every idle call once a path exists, even after the
fraction has reached 1.0. An interactive `--fly-through` session therefore
redraws continuously forever.

- Confidence: Confirmed.
- Fix: return False once the fraction is 1.0 and the pose has been applied.

##### MV-m4 - A live fly-through is timed from the viewer's start, not from the scene's

`OpenGLContext/viewer/sceneviewer.py:1023`.

It shares `_turntableStart`, which is set at `__init__` and on a turntable
toggle. An asynchronously loaded scene opens partway along its path, and
toggling the turntable restarts the fly-through.

- Confidence: Confirmed.
- Fix: give it its own start time, reset on mount.

##### MV-m5 - `ViewChrome` rebuilds every widget on every layout, which loses state mid-drag

`OpenGLContext/ui/viewchrome.py:456-473`, `:499-506`, `:605-616`;
`OpenGLContext/ui/panel.py:309-313`.

`layout()` calls `rebuild()`. A splitter drag calls `on_arrange`, then
`stack.invalidate()`, then a relayout, which builds new `Splitter` nodes on
every pointer move. The drag carries on through the detached `_armed` widget.
The visible line is the new, un-armed widget, so its highlight goes, and
keyboard focus on a `ViewLabel` is lost on any arrangement change. It also
constructs VRML nodes on every mouse move.

- Confidence: Likely.
- Fix: rebuild only when the set of shown views, their parts, or the
  arrangement changed (keep a key). Otherwise re-arrange the existing
  children.

##### MV-m6 - The quad crossing asks for a resize-x cursor although its comment says "either"

`OpenGLContext/ui/viewchrome.py:354-357`.

`'resize-x' if self.vertical is not False else 'resize-y'` gives `resize-x`
when `vertical is None`. The comment says "and the crossing for either", and
`CURSORS` has `'resize'`.

- Confidence: Confirmed.
- Fix: map `None` to `'resize'`.

##### MV-m7 - Pointer capture can stick

`OpenGLContext/multiview/views.py:392-423`; `OpenGLContext/multiview/viewset.py:362-373`.

If a release is never delivered (focus loss, or a drag ending outside a
window with no grab), `_held` and `_captured` persist, and every pointer event
goes to the old view until that button is pressed and released again. Also,
`ViewSet.show` switches layouts without clearing the old layout's capture or
`gestures._held`. The `v` key during a drag leaves a gesture panning a view
that is now hidden.

- Confidence: Possible.
- Fix: add `ViewLayout.release_all()` and call it from `show()` and from
  focus-out. Treat a press of a button already in `_held` as a new capture.

##### MV-m8 - Keys follow the active view only on paper; the context navigation treats a tile as the whole window

`OpenGLContext/multiview/views.py:21-27`; `docs/multiview.rst:202`;
`OpenGLContext/move/examinemanager.py:36-51`, `:78-84`.

"A press makes its view the active one, which is where keyboard input goes":
routing sets `event.view`, but nothing sends keys to an elevation's
navigation. The arrow keys always move the context camera, even with 'top'
active. `ExamineManager` and `_dolly` measure the drag and build the dolly ray
from `getViewPort()` (the whole window) using window pixel coordinates, so in
a quad tile the examine rate halves and the dolly ray is off-axis.

- Confidence: Possible.
- Fix: state the limit in the docs, or give `ViewNavigation` key bindings.
  Pass `frame.rect` to the orbit builders when the event has a view.

##### MV-m9 - `resolve_source` raises for an archive instead of returning None

`OpenGLContext/viewer/source.py:181-200`.

The contract is to return None for a source that is not there ("Answering
rather than exiting"). A missing local `world.zip` instead raises
`FileNotFoundError` from `_digest`, and an ambiguous archive raises
`UnknownMember`. `sceneviewer.py:274`, `:310` and `bin/view.py:300` call it
without a handler.

- Confidence: Confirmed.
- Fix: return None for a missing local archive. Document the
  `UnknownMember` raise and handle it in the viewer, printing its listing.

##### MV-m10 - The docs and a docstring use `on_arrange=context.placeViews`, which does not exist

`OpenGLContext/ui/viewchrome.py:21-22`; `docs/multiview.rst:488-489`.

No `placeViews` exists anywhere. The mixin's method is `viewsArranged`.

- Confidence: Confirmed.
- Fix: name `viewsArranged`, or show a local function.

##### MV-m11 - `docs/backends.rst`'s table of methods every backend provides lacks `setPointerShape`

`docs/backends.rst:183-200`.

- Confidence: Confirmed.
- Fix: add a row pointing to `CURSORS` and `overlayui.rst#pointer-feedback`.

##### MV-m12 - A GLSL include cites a module that does not exist

`OpenGLContext/shaders/_multiview_inc.glsl:1-2`.

The comment says "the std140 layout OpenGLContext/passes/multiview.py packs".
Packing is in `OpenGLContext/multiview/strategy.py` (`pack_view_table`).

- Confidence: Confirmed.
- Fix: correct the path.

##### MV-m13 - A doc comment sits on the wrong member

`OpenGLContext/context.py:1561-1564`.

The comment block "The views this context draws, or None for one view… Assign
a ViewLayout to draw several." sits directly above `def setPointerShape`, not
above `viewLayout: Any = None` at line 1580.

- Confidence: Confirmed.
- Fix: move it.

##### MV-m14 - GLFW cursors are never destroyed

`OpenGLContext/glfwcontext.py:378-402`.

Each context creates its own `glfw.create_standard_cursor` objects, and they
live until `glfw.terminate`. A process that opens many windows accumulates
them.

- Confidence: Confirmed.
- Fix: `glfw.destroy_cursor` each one in `releaseWindow`.

##### MV-m15 - An exception inside a view leaves scissoring on

`OpenGLContext/passes/_flat.py:1670-1677`, `:2511-2518`.

`finishViews` is not in a `finally`. `renderViewShader` restores the polygon
mode in its own `finally`, but if it raises, `GL_SCISSOR_TEST` stays enabled
with the last tile. If the next frame is single-view, `_scissorViews` is False
and nothing disables it, so the clear and the overlay are clipped until a
multi-view frame runs.

- Confidence: Possible.
- Fix: wrap the per-view loop in `try/finally: self.finishViews()`, and
  disable scissoring unconditionally in `finishViews`.

##### MV-m16 - The public multiview API is typed `Any` throughout

The camera is typed `Any` in all of these places:

- `View.camera`, `navigation` and `rect` users: `views.py:106-118`.
- `Context.viewLayout`, `getViewLayout` and `routeEvent`:
  `context.py:1580-1604`.
- `ViewLayout._told: dict`: `views.py:246`.
- `ViewNavigation.camera`: `navigation.py:198`.
- `_ViewWidget.view: Any`: `viewchrome.py:151`.
- `GLFWContext._cursors: Any`.
- `_DISPLAY_USES: dict`.
- `flythrough.poses_from(viewpoints: Sequence)`.

There is no `Protocol` for "anything with the view platform's matrix
interface", which the docs lean on. As a result, mypy's clean result on these
modules checks little across their boundaries.

- Confidence: Confirmed.
- Fix: add a `ViewCamera` Protocol (`matrix`, `modelMatrix`, `viewMatrix`,
  optional `setViewport`, `view`). Type `View.camera: Optional[ViewCamera]`,
  `viewLayout: Optional[ViewLayout]` and `routeEvent -> Optional[View]`.

##### MV-m17 - `ProgressBar` is public but missing from `__all__`, and its docstring breaks the writing rules

`OpenGLContext/ui/widgets.py:624-666`.

It is not in `__all__`. The docstring is sales and maxim:

- "a wait with no end in sight is the one that feels broken"
- the bold leader "**Not a disabled slider.**"
- "its value is somebody else's news"
- "a bar is not the place to raise about arithmetic somewhere else"
- the balanced pair "says more than a bar alone, and a bar alone says more
  than a number"

- Confidence: Confirmed.
- Fix: add it to `__all__`. Reduce the docstring to what it draws, what it
  clamps, and that it takes no focus.

##### MV-m18 - Writing-rule breaches in the new docstrings

Confidence: Confirmed. Fix: apply `/ai-isms --fix` to these files. The
breaches:

- A maxim or balanced pair: "a window that cannot say 'this drags' is better
  than one that says it with the wrong picture". It is in
  `context.py:1571-1575` (`setPointerShape`) and again in
  `glfwcontext.py:383-386`.
- Continuity reassurance:
  - "which is how an application that never mentions views renders exactly
    as it did" (`views.py:104-105`)
  - "go on driving it exactly as they did with one view" (`mixin.py:12-15`)
  - "go on working whichever arrangement is up" (`sceneviewer.py:142-147`)
- A bold maxim leader: "**The window's own camera stays the window's.**"
  (`mixin.py:12`).
- Bold items:
  - Bold on nearly every item of the part list in the
    `viewchrome.py:7-15` module docstring.
  - "**How closely it is ruled follows the view's scale.**" (`grid.py:8`).
  - "**a member of an archive**" (`viewer/source.py:3`).
  - "**The primary (left) button is unbound in every view.**"
    (`docs/multiview.rst:421`).
- Aphorisms and trailing glosses in `viewer/flythrough.py`:
  - "A recording of a scene that does not move is a picture with a file
    size." (`:3`)
  - "which is what makes it checkable" (`:9-10`)
  - "which is what makes a turn … look like a turn rather than a tumble"
    (`:53-55`)
- Trailing glosses in `eglcontext.py`:
  - "which is what a test asking 'did that one take the display down with it'
    wants to know" (`closeDisplay`)
  - "which is the difference between it and…" (`testing/glcontext.py`,
    `_egl_pbuffer`)
- In openglcontext-qt: "a widget class that already has that name is exactly
  why…" (`tests/test_pointer_shape.py:3-7`).

##### MV-m19 - `display_answers` runs a Tk subprocess on every call

`OpenGLContext/testing/glcontext.py:134-165`.

It is called at import time by three test modules (`test_tk_backend`,
`test_glut_initialisation`, `test_demo_viewers`), so it runs three times per
collection with a 30 s timeout each. It is not cached.

- Confidence: Confirmed.
- Fix: `functools.lru_cache` keyed on `(display, directory)`.

##### MV-m20 - The per-draw functions import on every call

`OpenGLContext/multiview/strategy.py:400-423`; `scenegraph/geometryarrays.py:222`.

`draw_arrays` and `draw_elements` run `from OpenGL.GL import …` on every draw.
That measured at 217 ns per call, against 12 ns for a module-level reference.
At 10k draws that is about 2 ms per frame, which falls under the workspace's
"headroom" rule.

- Confidence: Confirmed.
- Fix: import at module level. `strategy.py` is already imported by the
  passes.

##### MV-m21 - The archive cache has no eviction and no protection against a race

`OpenGLContext/viewer/source.py:84-127`.

Every distinct archive ever opened stays under app-data. Two viewers opening
the same archive race while extracting it (see MV-M10).

- Confidence: Possible.
- Fix: extract atomically (MV-M10). Document the directory, or add an LRU cap.

##### MV-m22 - Some cursor mappings contradict the stated "no wrong picture" policy

`glutcontext.py:219`, `tkcontext.py:241`.

GLUT maps `'no'` to `GLUT_CURSOR_DESTROY` (a skull) and Tk maps `'no'` to
`X_cursor`.

- Confidence: Confirmed.
- Fix: leave `'no'` out of the GLUT table, so the call answers False.

#### Nit

##### MV-n1 - `ViewChrome.pointer_pressed` does nothing

`OpenGLContext/ui/viewchrome.py:742-744`. It only calls `super()`. Remove it.

##### MV-n2 - Query and paint methods mutate state

`ExpandButton.paint` assigns `self.tooltip` on every paint
(`viewchrome.py:320-323`), and `Widget.rippleAt` clears `_ripple` as a side
effect of a query. Make `tooltip` a property, and let `animating` do the
clearing.

##### MV-n3 - Naming mixes camelCase and snake_case within one package

Examples: `lines_for` and `linesFor` / `shownIn` (`grid.py`);
`roomIn`, `sceneCameras` against `arrange_content`, `open_names`, `move_split`
(`viewchrome.py`); `clearColour` against `view_at` and `can_maximise`
(`views.py`). Choose one style per module family.

##### MV-n4 - Defaults are duplicated between the mixin and `QuadView`

`mixin.ELEVATIONS` and `FLAT_BACKGROUND` repeat `QuadView`'s defaults
(`quad.py:88-89`). `quad.__all__` also re-exports navigation's `ROTATE_RATE`
and `ZOOM_STEP`. Define each once.

##### MV-n5 - Small redundancies in `strategy.py`

- `IMPLEMENTED == STRATEGIES`.
- `ViewFrame.viewport` is an alias of `rect`.
- `from_features` defaults `max_viewports=16` where `__init__` defaults it to 1.
- `detect()` asks the driver again every frame when detection fails.

##### MV-n6 - `ViewSet` repeats what `View` and `Context` already do

`ViewSet.local` wraps `View.local`, and `ViewSet.view_for` repeats
`Context.routeEvent` (`viewset.py:177-190`).

##### MV-n7 - A module function is shadowed by parameters of the same name

In `source.py`, the module function `cache_dir()` is shadowed by the
`cache_dir` parameters of `open_archive` and `resolve_source`.

##### MV-n8 - `hoverWash` means two different things

`Skin.hoverWash` (a colour, `skin.py:141`) and `Widget.hoverWash` (a bool,
`widgets.py:136`) share a name. The per-widget comment "The skin's hover fill
lights it." on `hoverWash = False` reads as the opposite of what it does.

##### MV-n9 - `MiniMap` caches through `self.__dict__`

The cache in `hudwidgets.py:1260-1331` has a redundant `id()` plus `is` key.

##### MV-n10 - `MultiViewMixin.hasMouseMoveHandlers` is always True once views exist

`mixin.py:218-222`. It could be True only while `gestures._held` is set. The
overlay already answers True when visible, so the practical cost is small.

##### MV-n11 - `requested_strategy` reads the environment directly

It uses `renderoptions.env_choice`, and there is no `_once` variant, contrary
to the read-once rule in CLAUDE.md.

##### MV-n12 - A stale comment in openglcontext-qt's `pyproject.toml`

`pyproject.toml:37-42`: the comment explains "3.0.0a4 rather than 2.3.0",
while the specifier is `>=3.0.0a5`.

##### MV-n13 - `PbufferContext.release()` releases whatever EGL context is current

It un-currents that context even when it is another `PbufferContext`
(`eglcontext.py:477-495`). `_egl_pbuffer` works around this; the public class
does not.

##### MV-n14 - `_DISPLAY_USES` is an unlocked module dict

It is modified from whichever thread builds a context.

##### MV-n15 - `flythrough.poses_from` is missing from `__all__`

### Documentation, demos and tutorials

`docs/multiview.rst` (767 lines) covers:

- the mixin, the layout, the named arrangements, maximising, custom
  arrangements, per-view styles and event routing;
- QuadView and choosing its opening camera, ViewSet, and per-view navigation
  with rebinding;
- the view controls and their menu, and the scene's cameras;
- what is shared between views, the three strategies with a measured table,
  and how a node joins the shared submission.

`index.rst`, `documentation.rst`, `viewer.rst` and `overlayui.rst` link to
it. `overlayui.rst#pointer-feedback` documents the cursor names, the tooltip
pause and the ripple. The shipped showcase is `oglc-view --views quad`
(the `v` key), which follows the "demos are installed commands" rule, and
`tests/multiview_quad.py` feeds the `tutorials/multiview_quad` walkthrough.
`plans/` was not reviewed.

The gaps and errors:

- The statement that a perspective view takes its tile's aspect ratio is
  false for camera-less views (MV-M2).
- The ViewChrome example calls a `placeViews` method that does not exist
  (MV-m10).
- `backends.rst` lacks `setPointerShape` (MV-m11).
- Nothing documents `Grid` (MV-M8).
- "A key belongs to the active view" overstates what happens (MV-m8).
- The "Multi-view drawing" setting is presented as live but applies only at
  start-up (MV-M7).
- `offscreen.rst` does not say that EGLContext ignores `profile` (MV-M9).
- MV-d1 - The archive-member syntax is documented in the `source.py` docstring. It
  was not checked whether `docs/viewer.rst` names it, and neither the cache
  location nor its growth appears in the docs.
- Some docstrings break the style rules (MV-m17, MV-m18).

### Checked and found sound

- `views._split`, `_stack` and `_quad` rectangle maths, including
  `split_at[1]` measured from the top.
- `covers()`, the slab-sweep coverage test.
- Maximise and restore, `can_maximise`, member validation, and
  `MAX_VIEWS` / duplicate-view checks.
- `ViewLayout.route` for press/drag/release capture, wheel non-capture and
  keyed-to-active behaviour.
- `ViewLayout._tell`, which tells a camera its size only on change and
  catches a replaced camera through `id(camera)`.
- `OrthoView`, checked numerically for all six directions:
  - right x up = back for each (right-handed);
  - `zoom(at=…)` keeps the world point under the pointer fixed;
  - `world_from_screen` and `screen_from_world` are inverses;
  - `frame()` picks the limiting axis.
- `OrbitView.stand_at`, which reproduces the eye exactly (`ortho.py`).
  `frame_box` fits the bounding sphere against the narrower field-of-view
  angle, and the orthographic projection is symmetric in depth.
- `view_records` / `pack_view_table`:
  - `inv(ref) @ view @ proj` is right for row-vector matrices;
  - the eye in reference space is `inv(view)[3] @ refMV`;
  - bytes go in untransposed for GLSL column-major;
  - the std140 offsets (0/64/80, stride 96) match `ViewData`.
- `program_views` power-of-two sizing, `view_list` padding, and `view_mask`.
- `MultiviewCapabilities.available()` and `choose()` fallback ordering and
  logging.
- `routeToView` in the GLSL include (`gl_InstanceID % viewCount`, packed
  `ivec4` list).
- Menu access-key assignment (word starts first, uniqueness, mnemonic
  override), the upward-opening placement with `above`, linger and tick
  dismissal, and choosing-state input swallowing.
- The ripple easing and its per-tree effect list.
- `Panel.walksWithArrows` modeless gating.
- EGL display reference counting (`openDisplay` / `closeDisplay`, keyed by
  handle), and `PbufferContext` cleanup on a half-built context.
  `_egl_pbuffer` makes the context current before `context_lost`.
- `release_current` for EGL.
- The removal of wx's forced `PYOPENGL_PLATFORM=egl`, which is consistent
  with CLAUDE.md's guidance.
- `_display_listens` parsing of `host:N.s`, `unix:N` and `:N`.
- The `viewer/source.py` member resolution goes through `Resolver`, which
  refuses escapes, and extraction uses the content-pack bounded extractor.
- `flythrough.segment_at`, `pose_at` (slerp, clamped fraction) and `ease`.
- `ViewerOptions.window()` fullscreen and size defaults.
- openglcontext-qt: `setPointerShape` names the engine's `CURSORS`, guards
  on `_pointerGrabbed`, and its events go through
  `EventHandlerMixin.addPickEvent` / `ProcessEvent`, so routing applies to Qt
  unchanged. Its tests hold the table to `CURSORS`.
- `ruff check` and `mypy --follow-imports=silent` are clean on
  `OpenGLContext/multiview`, `ui/viewchrome.py`, `ui/tooltip.py`,
  `viewer/flythrough.py` and `viewer/source.py`.
- The new code has no `# type: ignore`. Its only `pragma: no cover` lines are
  two explained ones in `testing/glcontext.py`.

## Area 5: scenegraph content nodes and loaders (SG)

Scope: `OpenGLContext/scenegraph/{vegetation,terrain,water}/*`, `lod.py`,
`tessellationlod.py`, `roadworks.py`, `pbrmesh.py`, `pbrmaterial.py`,
`instancedgl.py`, `instancedshape.py`, `tilesterrain.py`, `imagetexture.py`,
`particlehooks.py`, `particles.py`, `audio.py`, `props.py`, `varied.py`,
`winding.py`, `inline.py`, `appearance.py`, `geometryarrays.py`,
`octahedral.py`, `basenodes.pyi`; `loaders/gltf/*` (`scene.py`, `hooks.py`,
`lod.py`, `zoning.py`, `imagebased.py`, `shapes.py`, `writer.py`,
`materials.py`, `meshes.py`, `fastdecode.py`), `loaders/assets.py`,
`resolver.py`, `background.py`, `cc0.py`, `obj.py`, `hdr.py`, `tiles3d/*`.
Line numbers are from `HEAD` and paths are relative to `openglcontext/`.
Reproduction scripts are beside this file in the scratchpad (`hookcrash.py`,
`lodbv.py`, `ring.py`, `dens.py`).

### Overall assessment

The work is large, mostly careful and well tested. The new modules come with
unit tests (hooks, MSFT_lod, zones, holes, relief, scatter blocks, water hook,
particle hooks, ground patches) and the docs pages were updated alongside the
code. The main weakness is untrusted input. The hook, zone and LOD readers
convert values from the document with bare `float()`/`int()`, so one malformed
value in a downloaded model aborts the whole load. The particle hook accepts any
`ParticleEmitter` field from the file, which includes an unbounded
`maxParticles` and a `texture` path that bypasses the resolver's containment.
This contradicts the "a file names a kind; it never names code" guarantee the
hooks documentation makes. The LOD node has three correctness problems: no
hysteresis, a bounding volume that stays cached for the first level drawn, and
a glTF path that drops skin/morph registration for the finest level. In the
terrain refactor, the tile ground's model matrix appears to be passed in the
wrong convention, and every constant uniform is re-uploaded for every tile on
every frame. Smaller problems are listed below: edge cases (zero density,
non-square control maps, degenerate portal triangles), a set of writing-rule
violations in docstrings, three mypy errors and several `type: ignore`s with no
reason given.

Counts: Critical 1, Major 9, Minor 27, Nit 14.

---

### Critical

#### SG-C1. A downloaded model sets any `ParticleEmitter` field, with no bounds, including a local file path

- `OpenGLContext/scenegraph/particlehooks.py:64-66, 82-103`
- `OpenGLContext/scenegraph/particles.py:303, 394-396, 666-671`
- `OpenGLContext/loaders/gltf/hooks.py:41-48` (the guarantee this breaks)

Problem: `FIELDS` is every field of `ParticleEmitter`, and `emitter_for`
`setattr`s any of them from the tag's params. `density` and `scale` are
multiplied in with no upper bound. The results:

- `maxParticles` (directly, or via `density`) becomes as large as the file
  says. `ParticlePool(capacity=self.maxParticles)` allocates against it at the
  first draw. The field metadata declares a maximum of 20000 (`particles.py:361`)
  and nothing enforces it.
- `texture` is a free string, opened later by `texture_rgba(self.texture)`, which
  is `Image.open(path)`. It is not resolved relative to the document or checked
  by `Resolver`, so a model can make the viewer open any local path (absolute or
  `../`), including device files.

The hooks are on by default (`OPENGLCONTEXT_GLTF_HOOKS` defaults to on) and
`fire`/`smoke`/`sparks` are built-in kinds, so `oglc-view some.glb` is exposed.

Evidence (`hookcrash.py`):
```
data = doc(node_ext={"OGLC_hook": {"kind": "fire", "density": 1e7, "texture": "/etc/hostname"}})
fire maxParticles 4000000000 texture /etc/hostname
```

Confidence: Confirmed that the values reach the node. The out-of-memory at
first draw is Likely; it was not run, to protect the machine.

Fix: give the tag a whitelist of *authorable* fields: colour, alpha, lifetimes,
direction, spread and similar. Leave out `texture`, `externalURL` and
`maxParticles`, or resolve `texture` through the document's `Resolver`. Clamp
`scale`, `density`, `rate`, `burst` and `maxParticles` to documented ceilings,
using the `maximum` the field metadata already declares. Add a test in
`tests/unit/test_gltf_particle_hooks.py` that feeds hostile values. Document the
limits in `docs/untrusted.rst`, which does not mention `OGLC_hook` at all.
Apply the same review to `mirrorhooks.PARAMETERS['scale']`, which is also
unbounded.

---

### Major

#### SG-M1. One malformed value in a hook, zone or MSFT_lod block aborts the whole glTF load

- `OpenGLContext/scenegraph/water/gltf.py:108-120, 162-163`
- `OpenGLContext/loaders/gltf/zoning.py:282-285, 224-241`
- `OpenGLContext/loaders/gltf/lod.py:49-62, 65-69, 80-84`
- `OpenGLContext/loaders/gltf/hooks.py:338, 355` (factory exceptions propagate)

Problem: the readers call `float()`/`int()` on document values with no guard,
and `HookRunner.material/node` does not catch exceptions from factories. The
water hook's own docstring says "a misspelling in a custom property is a model
to load rather than a file to refuse", and `mirrorhooks.reflector_for`
validates its values. The water hook, the zone's own properties and the
MSFT_lod reader do not.

Evidence (`hookcrash.py`):
```
ABORT water depth "deep" ValueError could not convert string to float: 'deep'
ABORT water amplitude "x" ValueError could not convert string to float: 'x'
ABORT zone priority "hi" ValueError invalid literal for int() with base 10: 'hi'
ABORT zone reverb level "x" ValueError could not convert string to float: 'x'
ABORT MSFT_lod ids ["a"] ValueError invalid literal for int() with base 10: 'a'
ABORT MSFT_lod not dict AttributeError 'list' object has no attribute 'get'
```
`MSFT_screencoverage` given as a non-list (`"abc"`, `0.5`) fails the same way
once `ids` names a real node (`lod.py:83`).

Confidence: Confirmed.

Fix: add one shared "number from a document" helper, like the one
`particlehooks._number`/`mirrorhooks.reflector_for` already contain, that logs
and falls back. Use it in `water/gltf.py`, `zoning._environment/_reverb/zone_for`
and `gltf/lod.py`. `alternative_ids`/`level_ids` should skip non-dict
extensions and non-integer ids. In `HookRunner`, wrap `entry.factory(ctx)` so
that an exception from one hook is logged with the kind and the holder, and that
holder loads as an ordinary shape. Add parametrised hostile-input tests.

#### SG-M2. `LOD.boundingVolume` stays cached for the first level drawn

- `OpenGLContext/scenegraph/lod.py:291-324`

Problem: the volume is cached with dependencies `(self,'level')` and
`(self,'range')` only. `whichLevel` is a plain attribute, and `show()` does not
invalidate the cache. The docstring says "Bounds of the level being drawn". In
practice it is the bounds of whatever level was drawn when the volume was first
asked for, and it never changes after that. For an impostor chain, where the
card's extent differs from the mesh's, this culls the coarse level by the fine
level's box, or the reverse.

Evidence (`lodbv.py`, levels are a 1 m box and a 10 m box):
```
level0 [[-0.5 -0.5 -0.5  1. ] ...
level1 True [[-0.5 -0.5 -0.5  1. ] ...     # same cached object after show(1)
```

Confidence: Confirmed.

Fix: in `show()`, call `boundingvolume.clearCachedVolume(self)` (or the
equivalent that invalidates dependants) when the level changes. Alternatively,
bound the node by the union of all levels, which never changes with the level.
That union is cheaper and gives a stable parent volume. Add a test.

#### SG-M3. Level selection has no hysteresis, so a viewer on a threshold flips levels every frame

- `OpenGLContext/scenegraph/lod.py:267-280` (`levelFor`)
- `OpenGLContext/scenegraph/lod.py:377-390` (`levelForCoverage`)

Problem: both choose a level with a hard comparison against the threshold. A
camera hovering at a switch distance, or one with head-bob or physics jitter,
toggles between two levels. Each toggle sends `SWITCH_CHANGE_SIGNAL`, and that
makes the pass re-walk its flattened scenegraph (`lod.py:253-265`). The cost is
visible popping plus a re-flatten on every frame. The tiles3d traversal has a
`hysteresis` parameter (`loaders/tiles3d/traversal.py:47-99`). The LOD nodes
have nothing equivalent, and the `ScreenCoverageLOD` docstring does not mention
the limitation.

Confidence: Likely. The code has no hysteresis; the frame cost depends on the
pass.

Fix: add a `hysteresis` fraction (field or class attribute, default around
0.1). A node switches to a coarser level only when coverage falls below
`threshold * (1 - h)`, and back to the finer level only above `threshold`.
Distance ranges get the mirror rule. Test it with a coverage oscillating across
a threshold.

#### SG-M4. The MSFT_lod path drops skin and morph registration for the finest level

- `OpenGLContext/loaders/gltf/scene.py:715-719` versus `794-837`

Problem: the plain mesh branch calls `_register_morph` and `_register_skin`
after collecting shapes. The `lod_ids` branch calls `_lod_node`, which builds
the finest level from `mesh_shapes` and never registers either. A skinned or
morphed character exported with MSFT_lod loads in its bind pose and does not
animate. Coarser levels built through `build(..., replacing=True)` do register,
but under an identity `Transform` recorded in `node_transforms`.

Confidence: Likely, from reading the code. No test covers MSFT_lod on a skinned
mesh.

Fix: call `_register_morph(node, node_index, finest, ...)` and
`_register_skin(...)` in `_lod_node`, which means passing `node_index` in. Add
a test using `RiggedSimple` with an MSFT_lod wrapper.

#### SG-M5. A streamed tile's ground is given its model matrix in the other convention

- `OpenGLContext/loaders/tiles3d/gltf_uploader.py:255-271`
- `OpenGLContext/scenegraph/terrain/ground.py:176-177`
- `OpenGLContext/shaders/terrain_splat.vert` (`uModel * vec4(aPosition,1.0)`)

Problem: the uploader documents `tile.content_transform` as column-vector
(`M·p`) and gives `m.T` to `MatrixTransform`. It then gives the untransposed `m`
to `mount_ground(..., model=m)`. `GroundShading.begin` uploads `model` with
`GL_FALSE`, the same way it uploads the row-vector `mode.matrix`. The shader
computes `uModel * v`, which comes out as `mᵀ·v`. The translation goes into
`w`, and the rotation is transposed. `vWorldPos` and `vWorldNormal` are then
wrong for every tile whose content transform is not the identity. The control
map and the baked light are sampled at the wrong world XZ. The tests only check
that `patch.model` is stored (`tests/unit/test_terrain_ground.py:81-89, 147-154`),
not what the shader receives.

Confidence: Likely. The conventions do not match; the result was not rendered.

Fix: pass `model=m.T` (row-vector, like `MatrixTransform`), or state and test
`GroundPatch.model`'s convention. Add a GL test that draws a patch with a
translated model and reads back which control-map texel it sampled.

#### SG-M6. Each tile's ground re-uploads every constant uniform and rebinds five textures on every frame

- `OpenGLContext/scenegraph/terrain/ground.py:159-222, 309-327`

Problem: `GroundPatch.render` calls `shading.begin()` for each patch. `begin`
binds the program and sets about 20 uniforms: five sampler units,
`numLayers`, `worldMin`, `worldSize`, three scales, three colours, fog and
more. All of these are constant for the life of the program. It also binds five
textures and restores the program in `end()`. A streamed world with a few
hundred ground tiles pays roughly 20 × N `glUniform*` calls and 5 × N texture
binds per frame, where one bind per frame and one `uModel` per patch would do.
`ViewPrograms` has a `setup` hook for exactly this case (`instancedgl.py:84-87`),
and `GroundShading._init_gl` does not pass one (`ground.py:151-152`). The
project standard is headroom for real games, not this demo.

Confidence: Confirmed by reading.

Fix: move the constants into a `setup` callback handed to `ViewPrograms`,
which also covers each multi-view form. Keep per-draw only `uModel`,
`uModelView`, `uProjection`, `uNormalMatrix` and `sunDirEye`. Better still,
group patches so that one begin/end brackets all ground drawn in a frame.

#### SG-M7. Files named by a tileset are joined without containment

- `OpenGLContext/scenegraph/tilesterrain.py:234-251` (`_mount_zones`, new)
- `OpenGLContext/scenegraph/tilesterrain.py:349-358` (`_beside`)
- `OpenGLContext/scenegraph/vegetation/cover.py:239-243` (`CoverSpecies.beside`)
- `OpenGLContext/scenegraph/vegetation/field.py` (`TreeSpecies.beside`)

Problem: world extras name `zones.document`, cover `card`/`clump` and tree
`mesh`/textures. These are joined with `os.path.join(base_uri, name)` or
`posixpath.join(directory, name)`. An absolute `name` replaces the base, and
`../` is not rejected, so a tileset can make the application load any local
glTF, `.glb` clump or image. Remote worlds use `base_uri + name` with no
same-origin check. The glTF loader itself routes every reference through
`Resolver` (commit `3fae062`, "Every reference goes through the resolver"), and
the tileset layer does not.

Confidence: Confirmed by reading.

Fix: resolve each tileset-named file through the same containment the glTF
`Resolver` applies: `Resolver(base_dir|base_url).resolve(name)`, or a small
`tiles3d.fetch.beside()` that rejects absolute paths and `..` escapes and keeps
URLs same-origin. Test it with `../` and absolute names.

#### SG-M8. A remote world's cover clumps and cards resolve to URLs that are opened as local files

- `OpenGLContext/scenegraph/tilesterrain.py:272-275`
- `OpenGLContext/scenegraph/vegetation/clumps.py:147-148` (`open(path, 'rb')`)
- `OpenGLContext/scenegraph/instancedgl.py:183` (`Image.open(source)`)

Problem: `_mount_cover` joins species against `base_uri` when it is a URL
(`beside = base_uri if fetch.is_url(base_uri)`), so `species.clump` and
`species.card` become `https://…` strings. `load_clump_glb` calls
`open(url)`, which fails with `FileNotFoundError` inside `CoverRung.__init__`
and aborts the whole `TilesTerrain` construction. The card fails later in
`texture_rgba` at GL init. `_beside` in the same file already fetches remote
bytes for the control map; the species files do not go through it.

Confidence: Confirmed by reading.

Fix: fetch species files through `fetch.read_bytes`, or `_beside`, and pass
bytes or a `BytesIO`. `load_clump_glb` should accept bytes. Add a test that
serves the tileset over an `http.server`, as the tiles tests already do for
tiles.

#### SG-M9. `GroundCover` crashes with `ZeroDivisionError` at zero density

- `OpenGLContext/scenegraph/vegetation/grid.py:306` (`1.0 / math.sqrt(self.density)`)
- `OpenGLContext/scenegraph/vegetation/grid.py:210`
- `OpenGLContext/scenegraph/vegetation/cover.py:616, 635`

Problem: `density_scale` is documented as "what a quality setting moves".
Setting it to 0, the obvious "cover off" setting, or giving a species
`density=0`, reaches `ScatterBlocks(0)` and raises. On the inline path this
propagates out of `update()` into the frame. On the background path it is
logged, and the rung is never drawn.

Evidence (`dens.py`): `density 0: ZeroDivisionError float division by zero`

Confidence: Confirmed.

Fix: in `_scatter`, return empty arrays when `density <= 0`, and have
`world_grid_scatter` do the same. Add a test.

---

### Minor

#### SG-m1. `control_weight` assumes a square control map

- `OpenGLContext/scenegraph/vegetation/cover.py:294-301`

`size = weight.shape[0]` is used for both axes. With a 64×16 map, a point at
x=90 of a 200 m extent reads column 14 instead of about 60. A map taller than
it is wide raises `IndexError`. `dens.py`: `non-square control [1.]` (wrong
texel). Confirmed. Fix: use `shape[1]` for `u` and `shape[0]` for `v`, and
refuse or resample non-square maps with a clear error.

#### SG-m2. The portal-face degenerate filter never removes anything

- `OpenGLContext/scenegraph/roadworks.py:1138-1146`

`flat` compares *indices*, and in `_ring` the indices `a, b, c, d` are always
distinct slots. The duplicated arch point that `_portal_face` inserts has equal
*positions*, not equal indices. `ring.py`: `triangles 76 zero-area 4`.
Confirmed. Fix: test for zero area (or equal positions), or have
`_portal_face` share the index. The comment above it describes behaviour the
code does not have.

#### SG-m3. `merged_mesh`/`merged_by_material`: wrong normals under non-uniform scale and inverted winding under mirroring

- `OpenGLContext/loaders/assets.py:245-269`

Normals are multiplied by `world[:3,:3]` rather than its inverse-transpose; the
comment acknowledges this. A negative-determinant transform flips triangle
orientation, and the indices are not reversed to compensate. These functions
exist to feed a decimator, and a mirrored instance becomes inside-out geometry
in the merged mesh. `_merge` also ignores `LOD.level`, `Switch.choice` and
`InstancedShape` placements, and uses a different pose test from `_measure`
(`hasattr` versus `getattr(...) is not None`). Confirmed by reading. Fix: use
`np.linalg.inv(world[:3,:3]).T`, swap two index columns when `det < 0`, and
document what is skipped. Neither function is in the docs (see the
documentation section).

#### SG-m4. Stated `MSFT_screencoverage` is not reconciled with the levels actually built

- `OpenGLContext/loaders/gltf/lod.py:72-84`
- `OpenGLContext/loaders/gltf/scene.py:794-837`

`_lod_node` skips invalid ids but uses the file's coverage list unchanged. With
one id skipped, the list is one entry longer than the levels, and the object is
`CULLED` one threshold early. The list's type and length are not checked
either. Likely. Fix: build the coverage list from the ids that survived, and
check `len(stated) in (levels, levels + 1)` with a warning on mismatch.

#### SG-m5. The definition of screen coverage may not match MSFT_lod's reference implementation

- `OpenGLContext/scenegraph/lod.py:148-161, 338-342`
- `docs/lod.rst:92-99, 148-149`

The engine uses *height* fraction (`r / (d·tanθ)`). Babylon.js, where MSFT_lod
originated, compares the projected bounding-sphere *area* to the screen area.
If files are authored against the area definition, every switch happens at a
very different distance (for example, 0.5 area is about 0.7 height). The docs
say "as MSFT_lod specifies" without quoting the spec. Possible. Fix: quote the
MSFT_lod README's definition in `gltf/lod.py`, and convert if the spec means
area.

Question for the maintainer (SG-m5): The MSFT_lod README gives `MSFT_screencoverage` values but does not define
screen coverage. `ScreenCoverageLOD` measures the share of the window's height
the bounding sphere spans (`radius / (distance * tan(fov/2))`); Babylon.js,
where the extension is implemented, is understood to compare the projected
sphere's area with the screen's area. A threshold authored for one switches at
a different distance in the other (in a square window an area of 0.5 is a
height of about 0.8). `docs/lod.rst` now states this rather than claiming the
spec defines it. Options: (a) keep height, documented as the engine's own
definition (files authored against Babylon.js switch later, i.e. keep detail
further out); (b) switch to area to match Babylon.js, converting inside
`ScreenCoverageLOD` so files authored there behave the same here, at the cost
of changing where every existing hand-built `screenCoverage` switches; (c) keep
height as the node's definition and convert area to height only in the glTF
loader for `MSFT_screencoverage`, so glTF files match Babylon.js while
hand-built nodes keep their meaning. Recommendation: (c), after confirming the
Babylon.js definition from its documentation (not its source), since
`MSFT_screencoverage` values in the wild are authored against Babylon.js and
the loader is the one place that knows a figure came from that extension.

#### SG-m6. `ScreenCoverageLOD` measures its radius around the level's own centre and its distance to `center`

- `OpenGLContext/scenegraph/lod.py:392-405`

`coverageRadius()` takes `boundingSphere(self.level[:1])`, which gives a
centre and a radius, and throws the centre away. `center` defaults to the
origin. A hand-built node whose geometry sits away from the origin measures
distance to the wrong point. The glTF loader sets `center`; hand-built nodes do
not. Possible. Fix: when `center` is unset and the radius is measured, take
the measured centre as well.

#### SG-m7. `mesh_bounds` ignores KHR_mesh_quantization

- `OpenGLContext/loaders/gltf/lod.py:87-111`

With quantized, normalized POSITION accessors, `min`/`max` are in integer
units, so the LOD radius and centre are off by the quantization scale. Possible.
Fix: apply the normalization (or the node's dequantization) before using
`min`/`max`, as the mesh decoder does.

#### SG-m8. A shareable hook's result is built with the first referencing node's world matrix

- `OpenGLContext/loaders/gltf/scene.py:596-635`
- `OpenGLContext/loaders/gltf/hooks.py:270-279`

`mesh_shapes` caches by `(mesh, casts)`, so a shareable hook runs once, with the
first node's `world`. `ctx.world_bounds()` is documented as "where this copy of
the primitive stands", which is untrue for every later copy. Under
`EXT_mesh_gpu_instancing` the placements are never included, so a water volume
covers only the un-placed copy. Likely. Fix: document that `world_matrix` is
meaningful only for `shareable=False`, or pass `world=None` to shareable hooks.
For instancing, have unshareable hooks run per placement, or warn.

#### SG-m9. `GLTFScene.advance` looks kinds up in the process-global registry at advance time

- `OpenGLContext/loaders/gltf/scene.py:181-199`

`hook_data` was written by the factory registered at load time, but `advance`
uses whatever is registered now. If an application re-registers or unregisters
a kind after loading, another code path advances its records, or none does.
The registry is also process-wide, with no per-load scope: two viewers in one
process cannot bind a kind differently. Likely. Fix: have `HookRunner` record
the `Registration` used for each kind and store it with `hook_data`. Consider
an optional `registry=` argument to `load_gltf`.

#### SG-m10. A zone naming a node whose hook took its slot controls a detached `Transform`

- `OpenGLContext/loaders/gltf/scene.py:739-767`
- `OpenGLContext/loaders/gltf/zoning.py:151-180`

`_place` keeps the loader's `Transform` in `node_transforms` when a hook returns
`(node, True)`. `ZoneVisibility`/`ZoneMirrors` resolve nodes through
`node_transforms`, so they toggle a node that is no longer in the scene.
Animation channels have the same problem, which the `_place` docstring
acknowledges. Possible. Fix: have `node_transform` return what stands in the
slot, or warn when a zone names a replaced node.

#### SG-m11. `imagebased`: faces are not validated, decode is eager, and some errors escape

- `OpenGLContext/loaders/gltf/imagebased.py:33-90`

Face sizes are not checked against `specularImageSize >> mip` or for
squareness, so a bad file fails later at upload. Every light is decoded at load
time, including lights no scene or zone names. A repeated image index is
decoded again each time. Only `OSError`/`ValueError` are caught, so a
`TypeError` from a scalar `rotation` or a non-list coefficient row, or PIL's
`DecompressionBombError`, aborts the load. mypy reports `imagebased.py:43`
(`Image` assigned to `ImageFile`). Likely. Fix: validate the sizes, decode
lazily or only lights that are referenced, cache per image index, and widen the
guard to `Exception` with a logged warning.

#### SG-m12. `decode_data_uri` decodes before checking the cap

- `OpenGLContext/loaders/resolver.py:262-274`

`base64.b64decode(payload)` allocates the full result before `check_size`
runs. The allocation is bounded by the JSON already in memory (0.75×), so the
risk is modest, but `len(payload) * 3 // 4` can be checked first at no cost.
Confirmed by reading.

#### SG-m13. The resolver's private names were renamed without aliases

- `OpenGLContext/loaders/resolver.py:30-35`

`_fetch_url`, `_decode_data_uri`, `_check_size`, `_resolver_max`, `_stream`
and `_user_agent` were removed, not aliased. Siblings were updated, but any
external code that imported them now breaks, in a release series that has
downstream users. `bin/gltf_regression.py` and `userpaths.py` still reach
`resolver._default_cache_dir`. Confirmed. Fix: keep deprecated aliases for one
release, or note the rename in the changelog.

Question for the maintainer (SG-m13): 3.0.0a4 shipped `resolver._fetch_url`, `_decode_data_uri`, `_check_size`,
`_resolver_max`, `_stream`, `_user_agent` and `_default_cache_dir`; they are now
public (`fetch_url`, `decode_data_uri`, ..., `default_cache_dir`) with no
underscore aliases. Every caller in this workspace (including
`bin/gltf_regression.py` and `userpaths.py`, which the review named) already
uses the public names. Options: (a) leave it: the old names were private by
convention and the release was an alpha; (b) keep underscore aliases for one
release with a DeprecationWarning; (c) note the rename in release notes, of
which openglcontext has none yet. Recommendation: (a), and (c) if a changelog
is started for 3.0.

#### SG-m14. `GroundCover._told` swaps `_blocks` while a background scatter may be writing to it

- `OpenGLContext/scenegraph/vegetation/cover.py:475-484, 555-584`

The worker can read `self._blocks` (the old dict), build a `ScatterBlocks` whose
`_suits` closure captured the *old* mask, and then insert it into the *new*
dict with `self._blocks[slot] = held`. That stale block is then reused for as
long as its key matches. `_retired +=` also runs from both threads. Possible
(timing-dependent). Fix: guard `_blocks`/`_retired` with a lock, or bump a
generation counter in `_told` that `_scatter` checks before storing.

#### SG-m15. `BackgroundCompute` loses a failed request, and a cover that is never shut down leaks its thread

- `OpenGLContext/scenegraph/vegetation/streaming.py:93-113`
- `OpenGLContext/scenegraph/vegetation/cover.py:688-702`

When `compute` raises, the request is dropped. `update()` has already moved
`_near_at`, so nothing re-requests until the camera travels another
`SETTLED_METRES`, and the cover has a hole until then. The daemon thread holds
`self._compute_both`, so a `GroundCover` built with `background=True` and
dropped without `shutdown()` stays alive, along with its thread and block
cache. Only `TilesTerrain.shutdown` calls it. Likely. Fix: on failure, reset
`_near_at`/`_far_at` through an error callback. Hold the owner weakly, or give
`GroundCover` a `dispose`/`__del__` that stops the worker. Document the
`shutdown()` obligation in `docs/vegetation.rst`.

#### SG-m16. `GroundCover.select` copies arrays and uploads them on every moving frame

- `OpenGLContext/scenegraph/vegetation/cover.py:647-672`

Each frame with movement computes `away` over the whole cached disc and
fancy-indexes four arrays twice per species, allocating new arrays each time,
then uploads through `update_instances`. At the default density, a 45 m cache
radius is about 14k plants per species. Several species give roughly 100k
element copies plus uploads per frame. The docstring calls this "cheap enough
for every frame", but the demo is a thin slice. Likely. Fix: keep the cache
sorted by block or distance ring and upload once; let the shader do the
distance fade/cut against the live camera, since the fade uniforms exist
already. Or re-select only when the camera has moved a fraction of the fade
band.

#### SG-m17. With no `clumpFarMesh`, the same mesh is uploaded twice and the inner disc is drawn twice

- `OpenGLContext/scenegraph/vegetation/cover.py:341-345`

`far = near` builds two `InstancedClumps` from one mesh, with two VBO/IBO
uploads. The inner disc is drawn by both, the near layer over the far one. The
docstring's "costs what it costs" covers this without saying so. Confirmed by
reading. Fix: when both are the same mesh, build one node with the far node's
fade window and no near overlay.

#### SG-m18. `TilesTerrain.holes`/`SplatTerrain.holes` set after the first draw have no effect

- `OpenGLContext/scenegraph/terrain/splat.py:139, 242-255`
- `OpenGLContext/scenegraph/tilesterrain.py:188-211`

`patch` is built once on first access, from `render` or `render_depth`, and
`holes` is a plain attribute after that. `GroundCover.holes` re-scatters, so a
late `holes` changes the cover and the colliders but not the drawn ground. The
limitation is in the docstring. Confirmed by reading. Fix: make `holes` a
property that disposes and drops `_patch`, so the mesh is re-cut on the next
draw.

#### SG-m19. Sun direction is documented backwards in ground and canopy code

- `OpenGLContext/scenegraph/terrain/ground.py:58-60, 188`
- `OpenGLContext/scenegraph/terrain/heightfield.py` (`canopy_density` docstring)
- `OpenGLContext/scenegraph/vegetation/cover.py:154-157`

`DEFAULT_SUN = (-0.5, -0.72, -0.48)` is documented as "Where the sun is, as a
direction to it", but its y component is negative and the shader uses
`L = -sunDirEye`, so it is the direction the light travels. `towards` in
`begin()` is misnamed for the same reason. `canopy_density` says the cover is
"offset toward it [the sun]", but the code offsets along the light, away from
the sun, which is where shade falls. Confirmed. Fix: correct the comments and
rename to `light_direction`.

#### SG-m20. `splat.py` keeps dead imports and duplicate constants after the move to `ground.py`

- `OpenGLContext/scenegraph/terrain/splat.py:1-70`

After rendering moved into `GroundShading`/`GroundPatch`, `splat.py` still
imports `ctypes`, `GL_CCW`, `glDrawElements`, `glUniform*`,
`glVertexAttribPointer` and others, and redefines `DETAIL_SCALE`,
`MACRO_SCALE`, `NORMAL_STRENGTH`, `SUN_COLOR`, `SKY_COLOR`,
`GROUND_AMBIENT`, `FOG_*` and `DEFAULT_SUN`, which `ground.py` also defines.
The module docstring still says the node "drives raw core-profile GL in
render (its own program, VAO and textures)". Ruff passes, so F401 must be
suppressed for this path. Confirmed. Fix: import the constants from `ground.py`
(or the reverse), delete the unused imports and rewrite the module docstring.

#### SG-m21. `PBRMesh._render_legacy` changes GL state it does not restore

- `OpenGLContext/scenegraph/pbrmesh.py:742-794`
- `OpenGLContext/scenegraph/appearance.py:70-79, 87-89`

A non-solid mesh re-enables `GL_CULL_FACE` unconditionally in `finally`, even
when it was disabled before, and it bypasses the pass's cull memo
(`set_cull_state`). `glTexEnvi(..., GL_MODULATE)` is set and never restored.
Likely. Fix: route through `set_cull_state` as the core path does, and restore
the env mode in `renderPost`.

#### SG-m22. mypy reports three errors in these paths in the workspace venv

- `OpenGLContext/loaders/gltf/imagebased.py:43`
- `OpenGLContext/scenegraph/vegetation/cover.py:470`
- `OpenGLContext/scenegraph/vegetation/field.py:238`

```
imagebased.py:43: error: Incompatible types in assignment (expression has type "Image", variable has type "ImageFile")
cover.py:470: error: Incompatible types in assignment (expression has type "list[Any]", variable has type "ChildrenTypedField")
field.py:238: ...same
```
Confirmed with `mypy --follow-imports=silent`. The preflight venv may differ,
per the stale-venv memory note. Fix: annotate `image` as `Image.Image`. For
`children`, use the pattern the other `Group` subclasses use, or fix the
`ChildrenTypedField` stub so that assignment accepts a list.

#### SG-m23. Seven new `type: ignore`s have no reason, against `CLAUDE.md`

- `loaders/gltf/imagebased.py:62`
- `loaders/gltf/shapes.py:68`
- `loaders/gltf/zoning.py:230`
- `scenegraph/varied.py:25`
- `scenegraph/zone*.py` (three)

Confirmed. Fix: build the tuples with an explicit length, for example
`Tuple[float, float, float]`. Give `Varied` a `Protocol` with `copy()`. Add a
reason to any that remain.

#### SG-m24. Loose typing on the hooks API

- `OpenGLContext/loaders/gltf/hooks.py:143, 168-202, 239-259, 297`

`register()` and `registered()` return `Any`. They should use overloads:
decorator versus call, and `Registration | None` versus
`Dict[str, Registration]`. Every `HookContext` field except `at`, `kind` and
`params` is `Any`, `_unknown: set` has no element type, and `Factory` returns
`Any`, so a mis-shaped node-hook return is caught only at runtime. Confirmed.
Fix: type the fields (`PBRMesh`, `PBRMaterial`, `Shape`, `Transform`,
`np.ndarray`), split the two return shapes with `@overload` or two factory
types, and add `set[str]`.

#### SG-m25. Converting presets from frozen dataclasses to Nodes breaks API and makes the presets mutable globals

- `OpenGLContext/scenegraph/water/surface.py` (`WaterStyle`)
- `OpenGLContext/scenegraph/water/medium.py` (`Medium`)
- `OpenGLContext/scenegraph/water/volumes.py` (`Volume`)
- `OpenGLContext/scenegraph/vegetation/field.py` (`TreeSpecies`)

`TreeSpecies(solid_texture=..., card_width=...)` keyword arguments were renamed
to camelCase with no alias, and `dataclasses.replace` callers break.
Hashability was lost. `STILL`, `LAKE`, `MEDIA[...]` and the others are now
process-wide mutable nodes. A hook or game doing
`ctx.mesh.waveStyle.amplitude = 1` changes every water body in every loaded
scene. The docstrings say this is intended. `Volumes.contains` now reads SF
fields through descriptors in a per-frame loop. Confirmed. Fix: record the
renames in the changelog, and consider freezing the module presets, for
example by having `style_for` return `.varied()` copies so a document's water
never aliases the global.

#### SG-m26. The water hook does not validate `medium` or `depth`

- `OpenGLContext/scenegraph/water/gltf.py:162-163, 123-137`

A negative `depth` inverts the box. An unknown `medium` string is stored as is,
and `Volumes` then reports a medium that `MEDIA` does not have. Confirmed by
reading. Fix: clamp depth to be non-negative, and map unknown media to `WATER`
with a warning. The mirror hook already has this pattern.

#### SG-m27. `LoadPool` can run `prepare` on a worker, and a few slow fetches starve every load

- `OpenGLContext/loaders/background.py:64-92`

A load running on a worker, such as an Inline scene, submits nested loads, so
`prepare` (the first-use import this pool exists to keep off workers) runs on a
worker thread whenever that is the first submission of its kind. Four fetches
that hang, for example to a dead host, occupy all `WORKERS`, and every other
texture queues behind them. Possible. Fix: call `prepare` eagerly for the known
kinds at import or at context start. Consider a per-fetch timeout, or a
separate network pool.

---

### Nit

#### SG-n1. Writing-rule violations in docstrings (history, narrative, bold leaders, selling)

Confirmed by reading.

- `scenegraph/roadworks.py` `BarrierProfile` docstring (around lines 84-104). It
  has bold-leader paragraphs ("**And it has to hold a car**", "**The two pull
  against each other…**"). It carries project history: "the shipped Beacon
  track at 69 km/h … it was the whole of why the autopilot could not finish a
  lap there". It names a test class as the justification. Game-specific history
  belongs in `plans/`. The rule and its reason fit in two sentences.
- `scenegraph/vegetation/grid.py:201-207`: "the default is the half-to-full
  spread this has always had", "The default is the one grid there has always
  been". `grid.py:62-64`: "an unsalted scatter is the scatter that was there
  before there were salts to ask for".
- `scenegraph/water/surface.py` `water_surface`: "is there because a caller that
  had one before this had styles still means it".
- `scenegraph/tilesterrain.py` `_mount_cover`: "which is what a world baked
  before there were sets of them carries".
- `loaders/resolver.py:24-30`: a bold "**These are public names**" and a
  maxim ("a containment rule with a second implementation somewhere else is a
  containment rule with a hole in it").
- `loaders/background.py:9-23`: bold-leader paragraphs.
- `scenegraph/vegetation/cover.py:43, 181`: bold leaders. There are also
  literary flourishes where plain statements would do: "A wood with bare
  ground under it is trees standing on a lawn", "a row of lamps on the forest
  floor", "which costs what it costs".
- `scenegraph/terrain/relief.py:19, 95, 101`: a bold heading, and cute error
  messages ("a feature smaller than nothing is not a feature").
- `scenegraph/terrain/heightfield.py` `canopy_density`: "Unclamped, and that is
  the point"; `mesh`: "agreeing by construction rather than by care".
- `loaders/gltf/hooks.py:173-177`: "A convention, read by nothing, so that…".
- `loaders/gltf/scene.py:407-412` (`_meter_exposure`): "so the room lit the way
  a room is lit comes out over by about the number of lamps in it".

Fix: `/ai-isms --fix` over these files, and move the Beacon narrative to the
roads plan.

#### SG-n2. `loaders/assets.py` was reformatted wholesale to double quotes in a feature commit

The rest of the package uses single quotes, and the reformat buries the change
to merged meshes in style noise. Confirmed.

Question for the maintainer (SG-n2): `loaders/assets.py` is in double quotes (a formatter pass in d6ee031) while the
rest of the package uses single quotes. Options: (a) keep it as it is;
(b) convert it back to single quotes in a commit of its own that changes
nothing else. Either is a whole-file change to style only. Recommendation:
(a) unless the package is to be held to one quote style by a formatter, in
which case the formatter's choice, applied package-wide, settles it. The fixes
to assets.py in ff2ca33 follow the file's current style.

#### SG-n3. `octahedralHemi` reads the string `"false"` as true

`loaders/gltf/materials.py:251-252`: `bool(extras.get(IMPOSTOR_HEMI, True))`,
while the mirror hook parses such strings. Confirmed.

#### SG-n4. glTF "2.1" core `shapes` handling targets an unratified version

`loaders/gltf/shapes.py:1-14, fastdecode.py:37-41`: this code targets a glTF
version with no published specification. Cite the draft it follows, or keep it
behind the extension until 2.1 is ratified. `read_shape` does not check that
`size` has three components or that dimensions are positive. Possible.

Question for the maintainer (SG-n4): `loaders/gltf/shapes.py` and `fastdecode.py` read a core top-level `shapes`
array when `asset.version` is 2.1 or later, and docs/extensions/OGLC_zone.rst
specifies zones against that. There is no ratified glTF 2.1 specification this
code can cite. Options: (a) keep the 2.1 path and cite the draft or proposal
it follows in shapes.py and OGLC_zone.rst (which document is it?); (b) read
only `KHR_implicit_shapes` until 2.1 is published, dropping the 2.1 example
from the OGLC_zone specification. Recommendation: (a), citing the draft by
name and date, since the 2.0 path is unaffected and a 2.1 file would otherwise
lose its zones.

#### SG-n5. `_warn_if_displaced` prints the node name twice and reads oddly

`loaders/gltf/scene.py:839-860`: the message formats the node's name twice and
ends "which is what the extension offers alternatives for". Confirmed.

#### SG-n6. `_index_emitters` scans every declared emitter for each built node

`loaders/gltf/scene.py:925-930`: this is O(built × declared). Use an
`id(emitter) → index` dict. Confirmed.

#### SG-n7. An `MSFT_lod` that lists its own node or a scene root empties the scene

`loaders/gltf/lod.py:49-62`: `ids: [0]` on root node 0 puts 0 in
`alternative_ids`, so the root is filtered out and the scene loads empty with
no warning. Possible. Warn, and ignore self-references.

#### SG-n8. `load_clump_glb` index handling is inconsistent

`scenegraph/vegetation/clumps.py:106-124`: `_mesh_index` returns an int
unchecked, so a negative value indexes from the end and an out-of-range one
raises `IndexError` instead of the `KeyError` the name path raises. Confirmed.

#### SG-n9. `GroundCover.species` is a writable field that nothing re-reads

`scenegraph/vegetation/cover.py:418, 467-471`, and `VegetationField.species` is
the same: the rungs are built once. Setting `species` after construction does
nothing, and the docstring says only "read when the cover is built". Make it
read-only, or rebuild the rungs on change.

Question for the maintainer (SG-n9): `GroundCover.species` and `VegetationField.species` are writable MFNode fields,
read only when the node is built. Options: (a) rebuild on change: a field
observer rebuilds the rungs (cover) or the near mesh and cards (field) from
the new species; the replaced nodes' GL objects then need releasing on the GL
thread at the next draw, as SplatTerrain.holes now does, and for
VegetationField the new list must still match `species_id`; (b) make the
fields read-only after construction (a custom field whose set raises once
built), so a caller learns at once that a new set of species means a new
node. Recommendation: (b) for VegetationField, whose species are tied to the
table's species_id, and (a) for GroundCover, whose rungs depend on nothing
else.

#### SG-n10. `CoverRung.retune` reaches into private state, and properties are built from lambdas

`scenegraph/vegetation/cover.py:386-388, 486-497`: `retune` touches another
class's private `_gl`/`_commit_constants()`, and the four property/lambda pairs
over `__dict__` are harder to read than ordinary `@property` definitions.

#### SG-n11. `scenegraph` imports from `loaders`

`scenegraph/terrain/relief.py:42` imports
`OpenGLContext.loaders.tiles3d.procedural.fbm`, so a scenegraph module depends
on the loaders layer. Move `fbm` to a neutral module such as `arrays` or
`noise`.

#### SG-n12. `wait_for_loads` can wait up to twice the timeout

`scenegraph/tilesterrain.py:313-323` gives the full timeout to the runtime and
then the full timeout again to the cover.

#### SG-n13. The octahedral docstring overstates where the arithmetic lives

`scenegraph/octahedral.py:22-24` says "the arithmetic is in one place", but
`pbr.vert` has its own GLSL copy. Say that the two are tested against each
other.

#### SG-n14. `PBRMesh.unchecked` keys on program ids, which GL reuses

`scenegraph/pbrmesh.py:125-135`: a new program that gets a freed program's id
is never checked for missing inputs. The practical risk is low.

---

### Documentation, demos and tutorials

Coverage is good for most of the new work. `docs/gltf.rst` has an "Engine
hooks" section covering both spellings, Blender authoring, the registration
API, the return table and `hook_data`/`advance`. `docs/lod.rst` covers
`ScreenCoverageLOD` and octahedral impostors. `docs/zones.rst`,
`docs/zones-internals.rst` and `docs/extensions/OGLC_zone.rst` specify zones.
`docs/water.rst` covers the `water` hook. `docs/particles.rst` covers authored
effects. `docs/terrain.rst` covers `GroundShading`, holes, `Relief` and
`bore_opening`. `docs/vegetation.rst` covers `CoverSpecies`, `ScatterBlocks`
and `BackgroundCompute`. `docs/shadows.rst`/`baking.rst` cover
`OGLC_castsShadow`. `docs/audio.rst` covers `useClip` and `scene.sounds`.

Gaps and inaccuracies:

- SG-d1 - `docs/untrusted.rst` does not mention `OGLC_hook`, `OGLC_zone` or
  `EXT_lights_image_based`. It should say what a downloaded file can make the
  engine do through the built-in kinds, give the limits, and point to
  `OPENGLCONTEXT_GLTF_HOOKS=0` (see SG-C1, SG-M1).
- SG-d2 - In `docs/gltf.rst`, the "What a file may ask for" subsection states that "a
  file names a kind; it never names code". That holds for code but not for
  resources: the particle `texture` field is a path (SG-C1). The engine-kinds
  table lists `water` and `fire/smoke/sparks` but not `mirror`, which the
  preceding paragraph names.
- SG-d3 - `loaders.assets.merged_mesh` and `merged_by_material` are public (`__all__`)
  and undocumented. `grid.Patches`/`world_noise` are exported from
  `vegetation/__init__` and not mentioned by name.
- `docs/lod.rst` says the coverage is "as MSFT_lod specifies" without quoting
  the specification (SG-m5), and says nothing about the lack of hysteresis (SG-M3).
- `docs/vegetation.rst` does not say that `GroundCover(background=True)` needs
  `shutdown()` (SG-m15), or that `density_scale=0` is invalid (SG-M9).
- The `splat.py` module docstring is stale (SG-m20). The `DEFAULT_SUN`,
  `canopy_density` and `CANOPY_SPREAD` docs describe the sun direction
  backwards (SG-m19).
- SG-d4 - Demos and tutorials: water (`water_demo.rst`), roads (`roads_demo.rst`),
  particles, mirrors (`oglc-mirrors`) and audio (`oglc-audio-demo`) have them.
  Ground-cover species and patches, MSFT_lod/impostors, holes/tunnel bores and
  zones/IBL have no `oglc-*` demo or tutorial page. The LOD bust hall and the
  lakeside `.glb` are content, not installed demos. Per the workspace's "Demos
  are shipped showcases" guidance, at least MSFT_lod and ground cover each want
  an installed command that covers the documented use cases.

### Checked and found sound

- `InstancedShape.cull` rewritten as two 2-D products (`instancedshape.py:172-186`):
  I checked the reshape/transposition algebra, and it equals the previous
  per-placement product. Placements are affine, so dropping the `w` reset is
  safe.
- `holes.cut` (`terrain/holes.py`): edges are keyed once per shared edge, so
  there are no cracks. Both triangle-orientation cases in `_trimmed` keep the
  original winding. `_row_of`'s searchsorted is valid because every queried edge
  is a crossed edge in `edges`, and the int64 key cannot overflow for realistic
  vertex counts.
- The octahedral mapping (`octahedral.py`): the hemi and full forward and
  inverse transforms are consistent, including the lower-hemisphere fold.
- `world_grid_scatter`/`ScatterBlocks`: the jitter reach covers cells whose
  instance can land inside the disc, blocks are keyed on whole cells, the
  uint32 hashing of negative indices is deterministic, and `_salted(0)` is the
  identity as documented.
- `Relief` (`terrain/relief.py`): band seeds are indexed from the coarsest band,
  so filtering by spacing leaves the surviving bands' seeds unchanged, and the
  amplitude clamps to the tile error as documented.
- `HookRunner`: the unknown-kind warning is reported once, `(node, bool)` is
  validated, and the DEF moves to the replacing node.
  `BUILTIN` imports come only from a fixed table, and no entry-point scan
  exists.
- `require_host` (`resolver.py`): exact host match, https only, a non-default
  port refused, and userinfo cannot spoof the host. `cc0` now caps the API body
  and pins the download hosts. The `hdr.py` header-line cap and pixel check are
  correct.
- `LoadPool`: the pending count and notify are correct, `wait_for_idle` covers
  work submitted while waiting, and `prepare` runs outside the lock.
- `winding.front_face` with `mirrored`: XOR with the determinant sign is
  correct, and `PBRMesh._front_face` now delegates to it, so the two copies are
  merged.
- `lod.viewer_for`: orthographic detection uses the GL-memory layout
  consistently, and `uniform_scales` takes row norms, which suits the
  row-vector convention.
- `particles._placement`: renormalising the direction to its authored length
  under a scaled parent is correct.
- `obj.py` `d`/`Tr` map to VRML `transparency` correctly.
- `GLTFWriter` hook/extras round-trip: an `OGLC_hook` extension is declared in
  `extensionsUsed`, and extras pass through uninterpreted.
- `ImageTexture.loadBackground` now tries each URL in turn, decodes eagerly,
  closes the file, and turns decode failures (including decompression bombs)
  into warnings.

## Area 6: content packs, physics, demos, packaging and the documentation audit (CP, PH, BIN, DOC)

Range: `v3.0.0a4..HEAD` in `openglcontext/`. Paths are relative to `openglcontext/` unless another project is named. Reproductions are in the scratchpad (`cp/`, `physrev/`, `binrev/`, `docrev/`). Nothing in the working tree was modified.

### Overall assessment

The content-pack package is carefully written. Member names are checked before anything is written, tar extraction uses the `data` filter, sizes are capped using the headers, digests are checked before extraction, the frame-loop polling contract is clear, and `mypy --strict` and ruff are clean. Its tests all run against a local server, though, and that hides the one defect that matters most. The resolver refuses any cross-origin redirect, and every GitHub release asset redirects to a CDN host. So no pack in any shipped registry (engine, glisteel, forest, twig-bb) can be downloaded, and the documented LOD demo command (`oglc-view <github release URL>`) fails (CP-1). The engine's own `content-v1` release also returns 404 today.

Behind that are design gaps that will show up in the field:

- There is no notion of an installed version, and the download cache is keyed only by URL. A rebuilt pack is never picked up, and a changed digest under the same URL fails on every attempt (CP-2).
- Installs are not atomic (CP-3).
- Tar enumeration is unbounded before the entry-count check (CP-4).
- `http` URLs are allowed without a digest (CP-5).
- `requires` is documented but not implemented (CP-6).
- One bad added registry blocks `load_registries()` until the user deletes a file by hand (CP-7).
- `publish.install(replace=True, within=…)` deletes a whole world (CP-8).
- A download holds up to twice the archive size in memory (CP-9).

In physics, the new threaded manager has three real event-delivery and locking defects (PH-01…03). The demos run and are well factored into testable "yard" objects. Their notable problems:

- The Tk and wx embedding demos never open in quad view (BIN-1).
- `profile_view` measures with error checking on (BIN-2).
- The `omi_audio` pin is below the API the engine now calls (BIN-3).
- The audio demo is flat plastic (BIN-4).

On documentation: every page is in a toctree, and coverage is broad. The gaps:

- One broken tutorial link (DOC-01).
- A contentpacks example that asks the user again on every start (DOC-03).
- No changelog for this range (DOC-02).
- No zones demo or tutorial (DOC-13).
- Several stale statements, and a group of writing-rule violations, mainly bold sentence leaders and trailing glosses.

Findings by severity. Unique ids; BIN-13 and DOC-11 overlap on one duplicated sentence.

| Area | Critical | Major | Minor | Nit |
|---|---|---|---|---|
| Content packs (CP) | 1 | 9 | 13 | 6 |
| Physics, move, character, audio (PH) | 0 | 3 | 6 | 4 |
| bin/, demos/, packaging (BIN) | 0 | 4 | 9 | 4 |
| Documentation (DOC) | 0 | 4 | 16 | 7 |
| Total | 1 | 20 | 44 | 21 |

The code findings follow, by area, each area ordered Critical, Major, Minor, Nit.

### Code findings

### Content packs


Reproduction scripts for this section are in `scratchpad/cp/repro1.py`, `repro2.py` and `repro3.py`.

##### Critical

CP-1. Every GitHub-hosted pack fails to download, and so does the documented LOD demo
- Refs: `OpenGLContext/loaders/resolver.py:185-229,477`, `OpenGLContext/contentpacks/fetch.py:178`, `OpenGLContext/packs.json:5`, `docs/lod.rst:21`, `docs/contentpacks.rst:446-452`, `OpenGLContext/viewer/source.py:118`
- Problem: `fetch_pack`, `fetch_registry` and the viewer's archive source all download through `resolver.fetch_to_cache`, which goes through `fetch_url` → `_urlopen_same_origin(url, url)`. That refuses any redirect that leaves the original origin. A GitHub release-asset URL (`https://github.com/<owner>/<repo>/releases/download/<tag>/<file>`) always answers 302 to `https://release-assets.githubusercontent.com/...`, which is a different origin. Every registry in the workspace points at GitHub release assets: engine `packs.json`, glisteel, openglcontext-forest and twig-bb. The docs recommend GitHub releases as the host. So no pack in any shipped registry can actually be fetched, and `oglc-view https://github.com/.../gallery-world.tar.gz` (the LOD demo in `docs/lod.rst`) fails the same way.
- Evidence: I ran `resolver.fetch_to_cache('https://github.com/cli/cli/releases/download/v2.40.0/gh_2.40.0_checksums.txt', ...)` and it raised `HTTPError 302: fetch refused cross-origin redirect to 'https://release-assets.githubusercontent.com/...'`. The tests do not catch this because every fetch test serves from `127.0.0.1` and none of them redirects (`tests/unit/test_contentpacks_fetch.py:33`).
- Separately, the engine's own registry URL (`.../mcfletch/openglcontext/releases/download/content-v1/gallery-world.tar.gz`) returned 404 at review time. The `content-v1` release has not been pushed, so the shipped registry and the documented demo point at nothing.
- Confidence: Confirmed.
- Suggested fix: the content-pack path needs its own redirect policy. The pack's URL comes from a trusted registry, and the integrity check is the digest, so the origin lock is the wrong control here. Allow https→https redirects to any public host, keep refusing redirects to non-https schemes and to private, loopback and link-local addresses, and keep the same-origin lock for document-relative references (glTF buffers and similar). Add a test with two local servers where one redirects to the other. Push the `content-v1` release before tagging the engine release, or keep `packs.json` out of the release until then.

##### Major

Question for the maintainer (CP-1): The redirect fix is in, and a real GitHub release asset now downloads through
`resolver.PUBLIC_HOSTS`. The engine's own `content-v1` release is still not
pushed, so `OpenGLContext/packs.json` and the `oglc-view` command in
`docs/lod.rst` still point at a 404. Pushing it is a publishing step
(`./release-assets.py --push` in openglcontext). Push it before tagging the
engine release, or hold `packs.json` and the lod.rst command back until it is
pushed?

CP-2. Content is never updated after a publisher rebuilds a pack, and a changed digest under the same URL fails for ever
- Refs: `OpenGLContext/contentpacks/store.py:344-364,448-457`, `OpenGLContext/contentpacks/fetch.py:172-190`, `OpenGLContext/contentpacks/publish.py:109-132`, `OpenGLContext/contentpacks/pack.py:66-69`, `OpenGLContext/loaders/resolver.py:457-463`
- Problem, in three linked parts:
  1. `root_for` treats "the marker exists" as "installed". No record is kept of which digest or URL was installed. When a registry names a new `sha256` or URL for a pack, every machine that already has the old content keeps it silently.
  2. The download cache is keyed only by URL, and a cache hit is returned without re-validation. `publish.push` re-uploads rebuilt archives to the same tag with `--clobber`, so the URL stays the same while the bytes and the registry digest change. Any machine with the old archive cached then gets `DigestMismatch` on every attempt. `fetch_pack` does not evict the cached entry on a mismatch, so nothing recovers short of deleting the cache by hand. A truncated or corrupted cache entry has the same effect.
  3. `pack.py:66-69` says an empty digest is for "a pack hosted by somebody who may replace it under the same URL". The engine's own publish flow does exactly that while recording a digest.
- Evidence: `repro2.py` seeds the cache entry with wrong bytes while the server holds the right ones. Two consecutive `fetch_pack` calls both raise `DigestMismatch`.
- Confidence: Confirmed.
- Suggested fix: write a small install record (key, sha256, url) into the pack directory and have `root_for` compare it with the pack when the pack carries a digest. On `DigestMismatch`, delete the cached file and download once more before failing. Key the cache by digest when there is one. Either version the release tag per content build or document that a rebuilt pack must get a new URL.

CP-3. Installation is not atomic: a failed extraction can leave the pack "installed", and concurrent installs interleave
- Refs: `OpenGLContext/contentpacks/archive.py:205-250`, `OpenGLContext/contentpacks/store.py:448-457`, `OpenGLContext/contentpacks/fetch.py:265`
- Problem: `extract` writes directly into the final directory. If extraction stops part way, whatever was already written stays, including the marker if it came early in the archive. Causes include a `FilterError` on a later member, `ENOSPC`, a daemon `FetchJob` thread killed at interpreter exit, or a crash. The next run's `root_for` then reports the pack as present. A pack with an empty `marker` counts as installed as soon as any file exists. Extracting over an existing directory (an update, or `within` packs) leaves stale files from the previous content. Two processes of the same game extract into the same directory with no lock.
- Evidence: `repro1.py` step 2 builds a tar with `m.txt`, then an escaping symlink, then `rest.bin`. `extract` raises `UnsafeArchive`, yet `store.root_for(pack)` then returns the directory, with `rest.bin` missing.
- Confidence: Confirmed.
- Suggested fix: extract into a sibling temporary directory (`<dir>.partial-<pid>`) under the store. After extraction completes, write the install record from CP-2, then `os.replace` it into place under a lock file. For `within` extractions, stage the combined set, or at least write the marker last. Remove the partial directory on failure.

CP-4. Archive enumeration is unbounded before the entry-count and size checks run (tar "entry bomb")
- Refs: `OpenGLContext/contentpacks/archive.py:233-239`
- Problem: `_extract_tar` calls `tar.getmembers()`, which decompresses the whole stream and builds a `TarInfo` for every member, and only afterwards compares the count with `MAX_ENTRIES` and the sum with `max_bytes`. For a gzip stream, getting past each member's data also means decompressing it. A small archive can therefore use a lot of memory and CPU before it is refused. This matters for packs without `sha256` and for packs from added registries, where the digest check does not stop the archive first.
- Evidence: `repro3.py` builds a 1.86 MB `.tar.gz` of 300,000 empty members. Refusing it took 14.9 s and a peak of 131 MB of Python allocations, about 440 bytes per member. At the 256 MB `FLOOR` cap that scales to tens of millions of members and many GB of RAM. The tarball is also decompressed twice: once to enumerate and again for `extractall`.
- Confidence: Confirmed (scaling extrapolated).
- Suggested fix: iterate `for member in tar:` with a running count and running size, and stop at the first overrun. Then extract the collected members, or extract member by member with the `data` filter. Also bound the decompressed bytes read during enumeration.

CP-5. Plain `http` is accepted and `sha256` is optional for non-base packs, so content can be replaced in transit
- Refs: `OpenGLContext/contentpacks/catalog.py:307-311,347-352`, `docs/contentpacks.rst:74`
- Problem: a registry may name an `http://` URL and leave out `sha256` for any pack that is not a base pack. That is every track in glisteel and every pack an added registry offers. An on-path attacker can then substitute the archive, and loaded content (glTF, images, and VRML with its Script nodes) is an attack surface. `resolver.require_host` already states the policy of refusing plaintext for data that is written to a cache and read as content. The catalogue does not apply it.
- Confidence: Confirmed (by reading).
- Suggested fix: require `https` unless the pack carries a `sha256`, or require https outright. Consider requiring a digest for every pack in a registry the application ships.

CP-6. The documented `requires` field is never enforced or validated
- Refs: `OpenGLContext/contentpacks/pack.py:77-79`, `OpenGLContext/contentpacks/catalog.py:59`, `docs/contentpacks.rst:116-118`
- Problem: the docs say that with a `requires` specifier "a pack built for a later format is declined rather than loaded". Nothing in the engine or in any caller reads `pack.requires` (grep across openglcontext, glisteel, twig-bb and forest). The value is not even parsed as a PEP 440 specifier, so `"requires": 5` loads (`repro1.py` 1d). A reader relying on it gets no protection.
- Confidence: Confirmed.
- Suggested fix: validate it with `packaging.specifiers.SpecifierSet` in `_pack`. Have `ContentStore` or `catalog.offered` take the application version and exclude packs that do not match, and test it. Otherwise remove the field and its documentation.

CP-7. A registry that fails to load is kept, and every later `load_registries()` then raises
- Refs: `OpenGLContext/contentpacks/fetch.py:134-135`, `OpenGLContext/contentpacks/store.py:391-439`
- Problem: `fetch_registry` copies the bundle into `registries/` before loading it. If validation fails, the file stays. `load_registries()` refuses loudly by design, so from then on the application's chooser cannot load any added registry, and the user has to find and delete a hashed file by hand. One bad URL, or a publisher's typo, is enough to cause this.
- Evidence: `repro1.py` step 5: after `keep_registry` and a failed `load_bundle`, `store.load_registries()` raises `BadCatalog` on every call.
- Confidence: Confirmed.
- Suggested fix: validate the bundle from a temporary extraction first and keep it only on success. Remove the kept file and the `.unpacked` directory when validation fails.

CP-8. `publish.install(..., within=X, replace=True)` deletes the whole owning pack's directory
- Refs: `OpenGLContext/contentpacks/publish.py:77-80`
- Problem: with `within`, `store.directory_for(pack, within)` is the directory of the pack that needs this one, such as the world. `replace=True` on a needed art pack therefore deletes the world and every other pack unpacked into it, then extracts only the art. The docstring promises to throw away "what is installed under this key". `ignore_errors=True` also hides a failed removal, and the new build is then extracted over leftovers. If the pack was found through the `OPENGLCONTEXT_CONTENT` search path, the store copy is deleted and re-extracted, but `root_for` still returns the search-path copy, so the rebuilt content never opens.
- Evidence: `repro1.py` step 3: a world plus art, then `install(art, within=world, replace=True)`. Afterwards the directory holds only `['art']`, and `root_for(world)` is None. glisteel's `--reinstall` avoids this only because it happens to install the chosen pack before its needs (`glisteel/release-assets.py:203-206`).
- Confidence: Confirmed.
- Suggested fix: when `within` is given, remove only the files the needed pack's archive lists, or refuse `replace` with `within` and replace the owner as a unit. Do not ignore errors. Warn or refuse when the found root is outside `store.root`.

CP-9. Whole-archive buffering in memory on download and on every cache hit
- Refs: `OpenGLContext/loaders/resolver.py:457-483,517-547,573-590`, `OpenGLContext/contentpacks/fetch.py:178`
- Problem: `fetch_to_cache` calls `fetch_url`, which collects every chunk in a list, joins it (a second full copy), writes it, and returns the bytes. `fetch_to_cache` then discards them. On a cache hit, `_read_cached` reads the whole file into memory just to return a path. For the 450 MB texture pack `fetch.py` mentions, peak memory is about 900 MB. The `stream_capped` docstring gives avoiding this as its reason for chunking.
- Evidence: `repro2.py`: for a 42 MB archive, Python allocations peaked at 83.9 MB during the fetch and 42 MB on a pure cache hit.
- Confidence: Confirmed.
- Suggested fix: give `fetch_to_cache` its own path. Stream chunks straight into the `mkstemp` file with the cap and cancel checks, `os.replace` at the end, and on a hit just touch the file. Compute the SHA-256 while streaming so `check_digest` does not read the file again.

CP-10. Namespace partitioning can be bypassed on case-insensitive or trailing-dot-stripping filesystems
- Refs: `OpenGLContext/contentpacks/catalog.py:68-70,202-219`, `OpenGLContext/contentpacks/store.py:341-342`
- Problem: `_refuse_shared_namespaces` compares namespaces as exact strings. On macOS (case-insensitive APFS by default) and on Windows, an added registry declaring namespace `Glisteel` gets the same `packs/glisteel/` tree as the shipped `glisteel`, and can write into a shipped pack's directory. That is the case the docstring says cannot happen. On Windows the regexes also accept a trailing `.` (`glisteel.`, `ashdown.`), which Win32 strips.
- Confidence: Likely (the logic is certain; I could not test it on this Linux container).
- Suggested fix: normalise namespace and directory to lower case, or `casefold()`, for both the comparison and the path. Forbid a trailing `.` and Windows reserved names (`CON`, `NUL`, …) in `_SEGMENT` and `_NAMESPACE`.

##### Minor

CP-11. Registry fields are coerced instead of validated
- Refs: `OpenGLContext/contentpacks/catalog.py:249-259,336-344`
- Problem: the module promises strict validation, but `bool("false")` is True, so `"base": "false"` with a digest produces a base pack. `"needs": "ns/b"` becomes `('n','s','/','b')`, and `merge` then reports a confusing "incomplete without 'n'". `approximate_bytes` accepts `true`, `1.9` and `"12"`. `title`, `family`, `requires`, `notes`, `url_page` and `copyright` are not type-checked: `title=None`, `family=7` and `copyright=['x']` all load. The `'..' in marker` test rejects legitimate names such as `v1..2.glb`, while `marker` is not checked for being a string before `os.path.isabs`.
- Evidence: `repro1.py` 1–1e.
- Confidence: Confirmed.
- Suggested fix: check `isinstance` per field: bool for `base`, a list of key strings for `needs`, int but not bool for size, str for the text fields. Check marker path segments with `PurePosixPath(marker).parts` rather than a substring test.

CP-12. A refreshed registry bundle is extracted over the old one, so stale files survive
- Refs: `OpenGLContext/contentpacks/catalog.py:113-133`
- Problem: `load_bundle` extracts into a directory that already holds the previous bundle. A new bundle without `packs.json` loads the old manifest. Old thumbnails the new bundle dropped still resolve as previews. `load_registries` also re-extracts every bundle on every call, which rewrites disk on each application start.
- Evidence: `repro1.py` step 4: a bundle with no manifest loads `['ns/a']` from the earlier bundle.
- Confidence: Confirmed.
- Suggested fix: extract into a fresh temporary directory and swap it in. Skip extraction when the bundle's digest matches the one recorded from the last extraction.

CP-13. `fetch_registry` and `resolver.fetch_url` accept any scheme urllib opens, including `file://`
- Refs: `OpenGLContext/contentpacks/fetch.py:110-135`, `OpenGLContext/loaders/resolver.py:442-483`
- Problem: pack URLs are held to http(s) by the catalogue, but a registry URL is not, and the public primitive `fetch_url` does not check the scheme either. The resolver module docstring claims it "blocks `file://` reads". `fetch_registry('file:///...zip', store)` and `resolver.fetch_url('file:///etc/hostname')` both succeed and copy the local file into the cache. A plain-http registry URL is also accepted.
- Evidence: I ran both calls in the scratchpad and both succeeded.
- Confidence: Confirmed.
- Suggested fix: check `is_url()`, or better require https, at the top of `fetch_url` and in `fetch_registry`.

CP-14. `missing_base` returns a flat list, so the `within` it depends on is lost
- Refs: `OpenGLContext/contentpacks/fetch.py:87-107`, `openglcontext-forest/src/openglcontext_forest_demo/run.py:504-507`
- Problem: the docstring says the caller must pass the base pack as `within` when fetching the result. With two base packs, or one base pack with `needs`, a flat list cannot say which `within` each entry belongs to. The forest demo already calls `fetch_pack(pack, store)` without `within`. It works today only because its base pack has no `needs`. If it gains one, the needed pack lands beside the base and `missing_base` asks for it again on every run.
- Confidence: Confirmed (API hazard; latent in callers).
- Suggested fix: return `list[tuple[ContentPack, ContentPack]]` of (pack, within), or give `FetchJob` and `fetch_pack` a helper that takes the base pack and fetches its closure.

CP-15. Cancel is not honoured during extraction, and a failed job's state never says so
- Refs: `OpenGLContext/contentpacks/fetch.py:284-337`, `OpenGLContext/contentpacks/archive.py:78-107`
- Problem: `cancel()` is checked only between download chunks and between packs. Unpacking a 450 MB pack cannot be stopped. `state` holds the last pack title after the job ends, whether it succeeded, failed or was cancelled. `_work` logs a failure with `log.warning('%s', error)`, which drops the traceback.
- Confidence: Confirmed (by reading).
- Suggested fix: pass the cancel predicate into `extract`, check it per member, and clean up through the staging directory from CP-3. Set `state` to `'done'`, `'failed: …'` or `'cancelled'` in `poll`. Use `log.warning(..., exc_info=error)`.

CP-16. `tarfile` extraction filters are required but `requires-python = ">=3.10"` allows interpreters without them
- Refs: `OpenGLContext/contentpacks/archive.py:241-244`, `pyproject.toml:19`
- Problem: `extractall(filter='data')` and `tarfile.FilterError` exist only from 3.10.12, 3.11.4 and 3.12. On an older 3.10 or 3.11 patch release, `extractall` raises `TypeError`, and evaluating the `except tarfile.FilterError` clause raises `AttributeError`, which masks it. The user sees a confusing error instead of a clear refusal.
- Confidence: Likely.
- Suggested fix: check `hasattr(tarfile, 'data_filter')` once and raise a clear `UnreadableArchive` or `RuntimeError`, or raise the Python floor.

CP-17. `archive.extract(max_bytes=None)` defaults to no unpacking cap, and the twig-bb caller relies on that default
- Refs: `OpenGLContext/contentpacks/archive.py:78-80`, `twig-bb/twig_bb/download.py:300-343,398-405`
- Problem: the safe behaviour has to be requested. `twig_bb.download._extract_tar` calls `engine_archive.extract(archive, directory, 'tar')` with no cap. `twig_bb.download.unpack` has its own zip extractor (`_safe_names` plus `extractall`) with no size or entry bound, and it recurses into nested archives. That is a second, weaker copy of engine code, which conflicts with engine-not-demo.
- Confidence: Confirmed.
- Suggested fix: default `max_bytes` to `MINIMUM_UNPACKED` and require `None` explicitly to mean unbounded. Move twig-bb's zip and nested-pk3 handling onto `archive.extract`.

CP-18. `archive.write` stores symlinks as links and silently drops symlinked directories
- Refs: `OpenGLContext/contentpacks/archive.py:138-171`
- Problem: `gettarinfo` uses `lstat`, so a symlinked file in the staging tree becomes a SYMTYPE entry with its absolute target, still forced to mode 0644. The resulting pack is then refused by every installer (`UnsafeArchive: 'link.txt' is a link to an absolute path`). `os.walk` does not descend symlinked directories, so their content is left out without any warning. `write` also writes in place rather than atomically.
- Evidence: I ran `write` on a tree containing `link.txt -> /etc/hostname` and `dirlink -> real`. The output held `link.txt` as a symlink entry and nothing under `dirlink`, and extracting it failed.
- Confidence: Confirmed.
- Suggested fix: refuse symlinks with a clear message, or dereference them (`handle.gettarinfo(fileobj=open(full,'rb'), arcname=name)`). Write to a temporary file and `os.replace` it.

CP-19. `packs.json` is not shipped in the wheel, and nothing in the engine reads it
- Refs: `pyproject.toml:131-151`, `OpenGLContext/packs.json`
- Problem: `packs.json` is not in `[tool.setuptools.package-data]` or `MANIFEST.in`, and the fresh `build/lib/OpenGLContext/` has `contentpacks/` but no `packs.json`. No engine code loads it: the LOD demo is reached through `oglc-view <url>`. So the engine carries a registry file in its source tree that no installed copy has and no code consumes. `CLAUDE.md` describes it as part of the package.
- Confidence: Confirmed.
- Suggested fix: either ship it (add it to package-data) and give the engine a consumer, for example `oglc-view --pack openglcontext/gallery` through `ContentStore`, so the demo gets the store, the digest check and the consent size, or move it beside `release-assets.py` as build output.

CP-20. `publish.push` treats any `gh release view` failure as "no release yet", and passes paths and tags without an option terminator
- Refs: `OpenGLContext/contentpacks/publish.py:120-139`
- Problem: an authentication or network failure on `view` goes on to `create`, which fails with a less useful message. A path or tag starting with `-` would be read by `gh` as an option. Low risk, since the arguments come from the author's own script.
- Confidence: Likely.
- Suggested fix: tell "not found" apart from other failures (capture stderr, or `gh api repos/{repo}/releases/tags/{tag}`). Pass paths as absolute paths or after a `--`.

CP-21. Error messages include the signed redirect URL
- Refs: `OpenGLContext/loaders/resolver.py:203-206`
- Problem: the refused-redirect `HTTPError` message contains the whole pre-signed CDN URL, including `sig=` and `jwt=`. It reaches `FetchJob.failed` and, through `log.warning`, the logs and telemetry journals.
- Confidence: Confirmed (seen in the CP-1 reproduction).
- Suggested fix: pass the target through `safe_url` with the query stripped before putting it in the message.

CP-22. The documented "one family to catch" is not complete
- Refs: `OpenGLContext/contentpacks/archive.py:53-58`, `OpenGLContext/contentpacks/fetch.py:184-189`
- Problem: `http.client.InvalidURL` (for example `https://localhost:abc/x`, which the catalogue's prefix check accepts) is an `HTTPException`, not an `IOError`, so it escapes a caller that catches `IOError`. The comment "the one ValueError this path can reach" holds for now, but it depends on the resolver never raising another `ValueError`. It would be clearer for the resolver to raise a dedicated `ResourceTooLarge`.
- Confidence: Confirmed.
- Suggested fix: validate the URL with `urllib.parse` in `_check_where_it_lands` (hostname present, port parses). Have the resolver raise a specific size exception and catch that.

CP-23. `release-assets.py` staging directories are reused between runs
- Refs: `openglcontext/release-assets.py:184-192`, and the same pattern in the forest and glisteel scripts
- Problem: `dist/content/gallery` is created with `exist_ok=True` and never cleared. Files from an earlier build, such as a `CREDITS.txt` the new `--world` does not have beside it, go into the next archive and its digest. `stage()` copies `CREDITS.txt` only when one sits beside the glB, while `credits()` promises "Full attribution in CREDITS.txt inside the pack".
- Confidence: Confirmed (by reading).
- Suggested fix: `shutil.rmtree` the staging directory before staging. Fail when `CREDITS.txt` is missing.

##### Nit

CP-24. Registry cap mismatch: a bundle is downloaded under 16 MB (`fetch.py:56`) but unpacked under `MINIMUM_UNPACKED` = 64 MB (`catalog.py:127-128`). One constant should drive both.

CP-25. Loose typing: `progress: Any` and `cancel: Any` in `fetch_pack` and `fetch_registry` (`fetch.py:110-112,150-153`), although `resolver.Progress` and `resolver.Cancel` exist. `FetchJob.human_total` duplicates `ContentPack.human_size`, and both print `0 MB` for anything under 0.5 MB.

CP-26. `with_needed` uses `list.pop(0)` and a linear `pack_for_key` for each need (`catalog.py:186-199`). This is O(n·m). It is harmless at current sizes; a dict built once would be cleaner.

CP-27. `_resolve_preview` and `_refuse_escape` use `abspath` rather than `realpath` (`catalog.py:284-290`, `archive.py:253-259`). A symlink inside a local registry directory can point a preview anywhere. The tar `data` filter covers the extraction side; zip extraction has no symlinks to follow.

CP-28. The asset-cache directory gets mode 0700 only on the leaf (`resolver.py:458`). Content-store directories use the umask. Neither is a problem for content that is not secret, but the "per-user" property depends on the app-data parent.

CP-29. Docstring writing-rule issues in this package:
- `store.py:427`: "which is the whole reason validation is strict". This is a named banned phrase, also flagged by `ai-isms`.
- `fetch.py:10`: "That single rule is the whole of the thread safety here".
- `fetch.py:15-18`: "The consequence is worth stating plainly because it looks like a bug and is not … which is correct -- there is nothing to tell". This is the defensive register.
- `catalog.py:18`: "**Validation is strict on purpose.**" This insists.
- `store.py:330-333`: "makes that impossible rather than forbidden" is a balanced pair. The CP-10 bypass also makes it inaccurate.
- `store.py:453`: "is the whole of the proof there is".
- `fetch.py:68-70` (`Cancelled`): "telling somebody their own decision was an error is a poor way to answer it".
- `pack.py:43`: "has no business being offered".
- `fetch.py:205` (`FetchJob`): the class docstring opens with a bold leader.

### Physics, move, character, audio

#### PH-01 (Major): a threaded manager loses the `'end'` events of a removed body, and ends the subscription first

Paths: `OpenGLContext/physics/threaded.py:76-79` (`_remove_body`), `OpenGLContext/physics/threaded.py:83-92` (`advance`), `OpenGLContext/physics/manager.py:75-92` (`remove` docstring), `OpenGLContext/physics/events.py` `_prune`.

Problem. `world.remove_body` writes the `reason='removed'` contact ends and trigger exits into `world.contact_log`. On a threaded manager nothing moves them into `ThreadedSimulation.events` until the simulation thread's next `_publish`. If `advance` runs before that tick, it delivers nothing about the removal, and `dispatch` then calls `_prune`, which finds `world.alive(ref)` False, takes the subscription out of `_by_body` and sets `active = False`. When the ends arrive with the next snapshot there is no one left to hear them. The `remove` docstring says "the subscriptions on it hear those ends at the next advance and then finish", which holds only for the unthreaded manager.

A removal done in the frame (OnIdle, a pickup handler) followed by that frame's `advance` is the usual order, and at 60 fps against a 120 Hz tick there is about a 50% chance no tick lands in between. On a stopped simulation (paused game) the loss is certain. A world-wide subscription (`_everything`) is not pruned, so it hears the ends one frame late instead; body subscriptions lose them.

Evidence (`remove_threaded.py`, same body/phases, advance immediately after remove):

```
PhysicsManager         [('begin', None), ('end', 'removed')] active False
ThreadedPhysicsManager [('begin', None)] active False
```

Confidence: Confirmed.

Suggested fix: in `ThreadedPhysicsManager._remove_body`, while still holding the world lock, move the world's log into the simulation's published events (a public `ThreadedSimulation.flush_events()` / `publish_events()` in omi_physics that does `self.events.extend(world.contact_log.drain())` under `self._lock`, so the ordering "no event before the snapshot it belongs to" still holds: removal ends belong after every step already published). Add a `TestRemoving` case that drives the threaded manager as `TestThreaded` does, removes, and advances with no tick in between.

#### PH-02 (Major): a subscription added late is handed every event recorded since reporting was switched on

Paths: `OpenGLContext/physics/manager.py:120-124` (`advance`), interacting with `events.py` `_listen`/`_index`.

Problem. `PhysicsManager.advance` drains `world.contact_log` only while `events.draining` is True, and `draining` is set only by a non-immediate subscription. Anything that switches reporting on without setting it leaves the log filling on every step: an `immediate=True` subscription (its `_report` sets `'flagged'`/`'all'`), a game's own `world.add_contact_listener`, or `world.contact_reporting` set directly. The log grows to its 65536 cap (one `ContactEvent`, with numpy point/normal, per reported pair per step with persist on) and then churns. When a normal subscription is later added, the first `dispatch` delivers the entire backlog, seconds or minutes old, as if it happened this frame.

Evidence (`immediate_log.py`: one crate resting on the floor, an immediate `('begin','persist')` subscription, 3 s run, then a normal subscription and one frame):

```
draining False
contact_log held 360 dropped 0
new subscriber heard 362 oldest time 0.0 world time 3.0166666666666586
```

The threaded manager does not have this: `latest_and_events` drains every frame regardless of `draining`.

Confidence: Confirmed.

Suggested fix: in `PhysicsManager.advance`, drain whenever the world records anything and discard when nobody is subscribed, e.g. `events = self.world.contact_log.drain() if self.world.contact_reporting != 'off' else ()` followed by `if self.events.draining: self.events.dispatch(events)`; or clear the log in `CollisionEvents._index` on the first subscription. Test: immediate subscription, run, add a normal subscription, assert the first delivery has no event older than the frame.

#### PH-03 (Major): render-thread code mutates the world of a threaded manager without the world lock

Paths: `OpenGLContext/physics/threaded.py:13-18` (module docstring: only `remove` takes the lock), `OpenGLContext/physics/events.py` `report_hit` (impulses), `_report` (reporting flags), `_collision` trigger branch (reads live `world.position`), `OpenGLContext/move/physicsplatform.py:25-44` (`body=True`).

Problem. Delivery was made thread-correct, but the calls around it were not:

- `CollisionEvents.report_hit(..., impulse=...)` does `world.apply_impulse` / `apply_angular_impulse`, a read-modify-write of `_linear_velocity[i]` / `_angular_velocity[i]`, from the render thread while the solver (which releases the GIL) is writing the same rows. The shot's impulse can be lost or half-applied. `world.position[hit.body]` for the lever arm is also read unlocked.
- `subscribe` → `_report` flips `world.contact_reporting`, `report_persist` and `_report[i]` mid-step. Mostly benign flags, but `'off'`→`'all'` part-way through `_record_contacts` is an unsynchronised change of what the tracker sees.
- For a trigger event, `_collision` takes `point` from the live `world.position[other]`, not from the snapshot the event was published with, so it can be torn and is a later pose than the one drawn. The module docstring promises the snapshot.
- `PhysicsViewPlatform(body=True)` makes `CharacterController._carry_body` call `world.place_body` (pose, prev pose and a broadphase refit) and write `linear_velocity` on every `update`, from whichever thread drives the walker. Nothing says this needs `with_world()` on a threaded world.

The hit ordering promise is also wrong for the threaded manager: `report_hit` says the hit is delivered "ahead of that frame's contacts, which all happened after it", but `latest_and_events` can hand over contacts from ticks published before the hit was reported.

Confidence: Likely (by reading; the race window is inside the native solver, not reproduced deterministically). The ordering point is Confirmed by reading.

Suggested fix: have the threaded manager take `with_world()` around `report_hit`'s impulse (a manager hook such as `_mutate()` returning a null context on the plain manager and the world lock on the threaded one, used by `report_hit` and `_report`); take the trigger `point` from the snapshot (`snap[0][other.index]`) in the threaded path, or store the position on the `TriggerEvent` in omi_physics at record time; document on `PhysicsViewPlatform` that a walker with a body in a threaded world updates under `with_world()`; qualify the hit-ordering sentence for the threaded manager.

#### PH-04 (Minor): mypy error in `audio/scene.py`

Path: `OpenGLContext/audio/scene.py:106-108`.

Problem. `apply_zones(..., engine.listener.position, table)` passes an `ndarray` where `apply_zones` declares `position: Sequence[float]`.

Evidence: `OpenGLContext/audio/scene.py:108: error: Argument 4 to "apply_zones" has incompatible type "ndarray[...]"; expected "Sequence[float]"  [arg-type]`.

Confidence: Confirmed.

Suggested fix: widen `apply_zones`' `position` to `ArrayLike` (or `Sequence[float] | np.ndarray`), which is what it already accepts, rather than converting at the call.

#### PH-05 (Minor): zone gain and zone reverb stick when the zone list becomes empty

Path: `OpenGLContext/audio/scene.py:105-108`.

Problem. `apply_zones` runs only `if zones:`. The engine is per context and outlives a scene, and `zoneGain` lives on the emitter nodes. When a scene with zones is replaced by one without (a viewer loading another file, a level whose zones are unloaded while its emitters stay), the engine's `reverb.level/decay/damping` keep the last zone's values indefinitely, and any emitter a zone had faded keeps `zoneGain` at its last value. `apply_zones` with an empty list would reset both (reverb to none, uncontrolled emitters to 1.0).

Confidence: Likely (by reading; `reverb_at([])` resetting to zero is what `test_zone_emitters_are_heard_inside_and_the_reverb_is_the_zones` shows at the outside-every-zone position).

Suggested fix: remember on the engine (or in a `WeakKeyDictionary` beside `_engines`) that zones were applied, and call `apply_zones(engine, ..., (), ...)` once when they go away; or call it unconditionally, since with no zones it is one pass over the emitters plus a no-op reverb. The branch in `scene.update` has no test: `test_audio_scene.py` never passes `zones=`.

#### PH-06 (Minor): a threaded manager writes a stale snapshot onto a body added in a reused slot

Paths: `OpenGLContext/physics/threaded.py:104-115` (`_write`), `OpenGLContext/physics/manager.py:68-73` (`add`).

Problem. `remove` makes slot reuse an ordinary thing. A snapshot published before a remove/add pair but not yet adopted has the old tenant's pose at that index, and `_write` writes it onto the new body's Transform for a frame (visible as a one-frame flash at the removed body's position; for a streaming world, every re-used slot).

Evidence (`slot_reuse.py`: old crate at (100, 50, 0) published, then remove + add a new crate at (0, 1, 0) in the same slot, then `advance`):

```
slot 0
new crate transform after advance: (100.0, 49.99932, 0.0)
```

Confidence: Confirmed.

Suggested fix: record the snapshot version (or the world's step count) at which each body was added, e.g. `body._since = self._sim.version + 1` in a threaded `add`, and skip it in `_write` while `version < body._since`; or publish under the world lock in `add`/`remove` so the next adopted snapshot already reflects the change (the same publish PH-01 wants).

#### PH-07 (Minor): a `dome` taller than its diameter floats above the ground

Path: `OpenGLContext/physics/props.py:107-109`.

Problem. The dome is a sphere of `prop.radius` centred at `height - radius`. For `height > 2 * radius` the sphere's bottom is `height - 2 * radius` above the foot: a walker or wheel passes under it, and a thrown body lands on a ball hanging in the air. `Prop` validates `shape` but not the proportions, and nothing documents the limit. The tests cover `height == radius` and `height < radius + radius` only.

Confidence: Confirmed (arithmetic; e.g. `radius=0.3, height=1.0` leaves a 0.4 m gap).

Suggested fix: clamp `lift` to at most `radius` (the sphere rests on the ground, top below the measured height) or stand a capsule for a tall dome; state the rule in the `Prop.shape` docstring and add a test.

#### PH-08 (Minor): `remove` and `body_for` are linear in the body count

Paths: `OpenGLContext/physics/manager.py:90-91`, `manager.py:107-112`, used by `events.resolve`.

Problem. `remove` does `body in self.bodies` and `self.bodies.remove(body)`: two scans per removal, so unloading k bodies from a world of n is O(k·n). A streaming world removes whole tiles at once. `body_for(transform)` is a scan per Transform, and `resolve` of an iterable of Transforms is O(m·n). Not per-frame, but the engine's stated bar is headroom for heavy games.

Confidence: Confirmed (by reading).

Suggested fix: keep `self.bodies` as an insertion-ordered dict (or a set beside the list) and a `transform id → body` map maintained in `add`/`remove`.

#### PH-09 (Minor): no test for the threaded removal and zone-audio paths

Paths: `tests/unit/test_physics_events.py:453-460`, `tests/unit/test_audio_scene.py`.

Problem. `test_a_threaded_manager_removes_between_ticks` only asserts the body left the world; nothing asserts a threaded subscription hears the removal (PH-01 would have failed it). No test calls `audioscene.update(..., zones=...)`, so the new branch, its mypy error and PH-05 are uncovered. There is no test that a late subscription does not receive old events (PH-02).

Confidence: Confirmed.

Suggested fix: add the three tests named under PH-01, PH-02 and PH-05.

#### PH-10 (Nit): `_handles` duplicates what the world already holds

Path: `OpenGLContext/physics/manager.py:58`, `72`, `86`, `100`.

`PhysicsBody.register` passes `handle=self` to `world.add_body`, so `world.handle_of(ref)` already answers the body for every live one. `_handles` is a second copy kept in step by `add`/`remove`; only `_retired` adds anything. Drop `_handles` and let `handle()` consult `world.handle_of` then `_retired`. Confidence: Confirmed.

#### PH-11 (Nit): class attributes declared after `__init__`

Path: `OpenGLContext/physics/manager.py:63-66`, `OpenGLContext/physics/threaded.py:73-74`.

`steps_on_this_thread` and `RETIRED_KEPT` sit between `__init__` and `add`, and the threaded override sits among the render-thread methods. Move them to the top of the class body. Confidence: Confirmed.

#### PH-12 (Nit): per-frame import in `audio.scene.update`

Path: `OpenGLContext/audio/scene.py:106`.

`from OpenGLContext.audio.areas import apply_zones` runs every frame a scene has zones. Cheap, but there is no import cycle to avoid here (`areas` imports `passes.zonelayers` lazily itself); a module-level import is the plain form. Confidence: Likely (no cycle found by reading `areas.py`'s imports).

#### PH-13 (Nit): prose in `PropColliders._stand` and `gltf_world`

Paths: `OpenGLContext/physics/props.py:95-106`, `OpenGLContext/physics/gltf_world.py:204`.

`_stand`: "Not the mesh it is drawn as, either way." is a fragment that comments on the previous sentence; "for a difference nobody driving past at forty metres a second can see" argues the choice rather than stating it; "The same stone as a block is a kerb across the hillside." restates the reason as a maxim. Plainer: "A static box or sphere, not the drawn mesh: a triangle mesh per rock costs the broad and narrow phases. A `box` stops what hits it. A `dome` is a sphere as wide as the stone, sunk so its top is at the stone's height, so a wheel or walker goes over it." In `collision_world_from_scene` the inline comment repeats the docstring sentence just above it. Confidence: Confirmed.

---


### bin/, demos/, packaging
#### Critical

None.

#### Major

##### BIN-1 The Tk and wx embedding demos never open in four views

- Where: `OpenGLContext/demos/tk_viewer.py:60`, `OpenGLContext/demos/wx_viewer.py:80`;
  cause at `OpenGLContext/viewer/sceneviewer.py:237` and
  `OpenGLContext/viewer/options.py:50`.
- Problem: both demos set `multiViewArrangement = 'quad'`, and their comments
  say the window opens in four views. `SceneViewerMixin` calls
  `self.startViews(arrangement=str(self.options.views or 'single'), ...)`.
  `ViewerOptions.views` defaults to `'single'`, so a non-empty arrangement is
  always passed, and `MultiViewMixin.startViews` evaluates
  `arrangement or self.multiViewArrangement` to `'single'`. The class
  attribute is never read on the viewer path. No test covers it.
- Evidence: I ran `ViewerApplication(source=None)` from `tk_viewer` under
  `xvfb-run` and inspected the view after 3 s. It printed
  `class attr quad mode single`. The script is at
  `scratchpad/binrev/tkquad.py`.
- Confidence: Confirmed.
- Suggested fix: fix it in the engine, not in the demos. Make
  `ViewerOptions.views` default to `None` and have `sceneviewer` pass
  `self.options.views`, which is None unless set, so the mixin's class
  attribute takes effect. Or have the viewer read `multiViewArrangement` when
  `--views` was not given. Add a unit test that a `SceneView` subclass
  declaring `'quad'` starts in quad. `test_viewer_options` already asserts
  what `views` defaults to.

##### BIN-2 `profile_view` no longer turns error checking off

- Where: `OpenGLContext/bin/profile_view.py:5-11`.
- Problem: the old code assigned `OpenGL.ERROR_CHECKING = False` before any
  API namespace was imported, and that worked. The new code sets
  `PYOPENGL_ERROR_CHECKING=0` with `os.environ.setdefault`. PyOpenGL reads
  that variable once, in `OpenGL/__init__.py:316`, when the `OpenGL` package
  is imported. Running `python -m OpenGLContext.bin.profile_view` imports
  `OpenGLContext/__init__.py` first, which imports `OpenGLContext.plugins`,
  which imports `OpenGL.plugins`, so the package has already been imported
  when the `setdefault` runs. The profiling harness therefore measures with
  error checking on, which is what it exists to avoid. The new comment ("an
  assignment after that has no effect") is the opposite of what happens: the
  assignment worked and the environment variable does not.
- Evidence: `import OpenGLContext.bin.profile_view` in a clean environment,
  then read `OpenGL._configflags.ERROR_CHECKING`: it is `True`. With the old
  approach (import `OpenGLContext.bin`, set `OpenGL.ERROR_CHECKING=False`,
  import `testingcontext`), `_configflags.ERROR_CHECKING` is `False`, because
  `_configflags` has not been imported by then. `-X importtime` shows that
  `OpenGL` is imported under `OpenGLContext.plugins`.
- Confidence: Confirmed.
- Suggested fix: go back to assigning `OpenGL.ERROR_CHECKING = False`, which
  is valid until `_configflags` is imported. Or use
  `OpenGL.dispatch.set_error_checking` if that is the supported runtime
  switch. Correct the comment. Add a unit test that imports the module in a
  subprocess and asserts that `_configflags.ERROR_CHECKING` is false.

##### BIN-3 The `omi_audio>=0.2.0a1` pin is below what the engine and `oglc-audio-demo` call

- Where: `pyproject.toml:44`. The use is at `OpenGLContext/scenegraph/audio.py:475`
  (`handle.set_rate(...)`, added in this range by f52db25), and
  `OpenGLContext/audio/areas.py` reads `engine.reverb`.
- Problem: `VoiceHandle.set_rate` came in with omi_audio commit 44e70b5
  ("A playing sound's rate can change"), and `AudioEngine.reverb` with
  fbb7c10. Both commits are after `RELEASE 0.3.0a1` (2e36601), the only
  omi_audio release. `set_rate` is called on every frame for every playing
  `AudioSource`, so an install that resolves omi_audio 0.3.0a1 raises
  `AttributeError` as soon as any scene sound plays. That includes
  `oglc-audio-demo`'s motor, bell and areas. In the same diff the
  `omi_physics` and `PyVRML97` pins were raised to match their sources; this
  one was left alone.
- Evidence: `git -C omi_audio log --oneline` shows 44e70b5 and fbb7c10 above
  2e36601. The pin is unchanged from `v3.0.0a4`. The workspace venv reports
  omi_audio 0.3.0a1 metadata while the editable source has `set_rate`.
- Confidence: Confirmed. The `AttributeError` itself is inferred from the
  missing method rather than reproduced against a 0.3.0a1 wheel.
- Suggested fix: bump omi_audio's version, release it, and pin
  `omi_audio>=<that version>`. Coordinate this with the release tooling in
  `tools/release.toml`.

Question for the maintainer (BIN-3): omi_audio's source is now 0.4.0a1 and OpenGLContext and openglcontext-editor require
`omi_audio>=0.4.0a1`. Nothing has been tagged or uploaded. Publishing 0.4.0a1 (tag
v0.4.0a1 on omi_audio's main and let its release workflow upload, or
`tools/release.py omi_audio`) has to happen before an OpenGLContext release that carries
the new floor; tools/release.toml computes that order from the requirement, so no edit
there was needed. Recommendation: release omi_audio 0.4.0a1 in the next release round.

##### BIN-4 `oglc-audio-demo` uses flat single-colour plastic

- Where: `OpenGLContext/bin/audio_demo.py:79-82` (`_marker`, VRML
  `Material(diffuseColor=...)`), `:105-110` (floor and balls through
  `DemoScene(color=...)`), `:135`, `:155`, `:159`, `:164`, `:168`.
- Problem: every surface in the shipped demo is an untextured Phong colour: a
  grey-green floor, orange balls, a yellow bell, a grey rotor and flat pads
  (see `scratchpad/binrev/audio_demo.png`). The workspace standard is that
  demos use textured metals, stone and wood. The sibling
  `physics_events_demo.py` shows how in 20 lines with `Finishes` and
  `surfaces.pbr_material(...)`. The audio demo also stays on the non-PBR
  renderer.
- Evidence: I ran it with `OPENGLCONTEXT_AUTO_EXIT_FRAMES=30` and a hidden
  window, and captured `audio_demo.png`.
- Confidence: Confirmed.
- Suggested fix: dress the yard the way `CollisionYard` is dressed, using the
  engine's `surfaces`. Suggested materials: a sandstone or checkered-marble
  floor, bronze or steel balls, a gold bell, a brushed-steel rotor, dark slate
  for the cave pad and a water-blue tiled pad. Set
  `OPENGLCONTEXT_RENDERER=pbr` as `physics_events_demo.main` does.

#### Minor

##### BIN-5 `oglc-audio-demo` shows `box_gain` instead of the engine's zones

- Where: `OpenGLContext/bin/audio_demo.py:66-72`, `:181-184`; `docs/audio.rst:414-455`, `:698`.
- Problem: `docs/audio.rst` presents zones as the way to do area ambience
  (`Zone` + `ZoneAudio`, fades over `blend`, `ZoneReverb`, set by the render
  pass). It gives `box_gain` in application code as the fallback "without
  zones". The demo, which the docs call "the working code for each recipe",
  only exercises the fallback. `ZoneAudio`/`ZoneReverb` and `apply_zones`
  have no shipped demo, and reverb is not shown at all.
- Confidence: Confirmed.
- Suggested fix: make the cave and the stream `Zone` nodes with `ZoneAudio`
  (and a `ZoneReverb` in the cave), and let the pass drive them. Keep
  `box_gain` in the docs as the no-zone alternative.

##### BIN-6 A door driven to a target and "is anything on this trigger" are hand-rolled in the demo

- Where: `OpenGLContext/bin/physics_events_demo.py:284-293` (`_on_plate`
  set, `plate_pressed`), `:372-386` (`_drive_door`).
- Problem: moving a kinematic body toward a target at a set speed and
  stopping exactly on it is how every door, lift and moving platform in a game
  works. Keeping a trigger's occupancy from `enter`/`exit` is how every
  pressure plate and volume works. Neither exists in
  `OpenGLContext.physics` or `omi_physics`: a search for
  kinematic/occupancy helpers found none. So the demo implements
  capabilities a game wants, and every game will reimplement them.
- Confidence: Likely. This is a design judgement, but the gap is confirmed by
  search.
- Suggested fix: add an engine helper, for example
  `PhysicsManager.drive_kinematic(body, target, speed, dt)` or a
  `KinematicMover`, and a trigger-occupancy object
  (`events.occupancy(trigger)` → a live set with `.occupied`). Test both in
  `tests/unit`, and have the yard call them.

##### BIN-7 `oglc-physics-events` keeps its per-frame logic in an uncovered windowed class

- Where: `OpenGLContext/bin/physics_events_demo.py:400-452`.
- Problem: the whole context class is defined inside `main()` under
  `# pragma: no cover - needs a window`. It holds the frame-cap sleep, the
  dt clamp (`min(now - last, 0.1)`) and the camera-forward ray for the gun
  (`platform.quaternion * [0, 0, -1, 0]`). `tests/physics_events.py:77-81`
  repeats that ray, `move/physicswalk.py:434` and `move/terrainwalk.py:409`
  have it too, and there is no public `ViewPlatform` accessor for the view
  ray. `audio_demo.py:284-293` likewise keeps volume clamping and the muffle
  toggle in the window class.
- Confidence: Confirmed.
- Suggested fix: add a `ViewPlatform.forward()` (or `viewRay()`) and use it
  at all five sites. Move the frame-cap pacing and dt clamp into the yard (for
  example `yard.frame(now)`, returning the dt and the sleep) so they are
  tested. Move `_volume` and `OnMuffle` into `AudioYard` or the audio
  settings API.

##### BIN-8 The shipped physics demo reads the wall clock, so its captures are not deterministic

- Where: `OpenGLContext/bin/physics_events_demo.py:427`, `:443-445`;
  `OpenGLContext/bin/audio_demo.py:255`, `:260-261`.
- Problem: both demos step their simulation from `time.time()`.
  `OPENGLCONTEXT_AUTO_EXIT_FRAMES` puts the engine on a `FixedStepClock`
  that only `systemtime.systemTime()` follows. The tutorial
  `tests/physics_events.py:83-88` uses `systemtime` for exactly this reason
  and says so. The shipped commands therefore give a different frame on each
  capture, and on a hidden run the physics can advance by the wall-clock
  startup time.
- Confidence: Confirmed by reading the code against the CLAUDE.md contract
  for `OPENGLCONTEXT_CAPTURE_FPS`.
- Suggested fix: use `systemtime.systemTime()` in both, as the tutorial does.

##### BIN-9 `oglc-audio-demo` picks a GL backend at import, including for `--help` and unit tests

- Where: `OpenGLContext/bin/audio_demo.py:35`, `:45`, `:238`.
- Problem: `BaseContext = testingcontext.getInteractive()` and
  `class AudioDemoContext(BaseContext)` run when the module is imported.
  `oglc-audio-demo --help` prints `No default context type in
  ~/.config/OpenGLContext/defaultcontext.txt` before the usage, and
  `tests/unit/test_audio_yard.py`, which only wants `AudioYard`, pulls in
  backend selection. `physics_events_demo.py` defers this to `main()`.
- Evidence: the `--help` output shown above.
- Confidence: Confirmed.
- Suggested fix: move the context class into `main()` as
  `physics_events_demo` does, or behind a factory function.

##### BIN-10 `oglc-view --video-fps 0` / `--video-seconds <= 0` are not validated at the command line

- Where: `OpenGLContext/bin/view.py:180-185`.
- Problem: both are plain `type=float`/`type=int`. `--video-fps 0` reaches
  `FixedStepClock` (`video/clock.py:72`), which raises `ValueError` from
  inside `OnInit` after the window has opened, instead of producing a
  `parser.error`. A negative `--video-seconds` gives a negative frame limit
  (`recorder._frame_limit`). The handler around `load_encoder_api` shows the
  intent to fail before a window opens.
- Confidence: Likely. Traced through the code; not run, because recording
  needs the encoder.
- Suggested fix: use a positive-number `type=` for both, as `_parse_size`
  does.

##### BIN-11 `gltf_regression` rederives the cache key and reads whole files to learn a path

- Where: `OpenGLContext/bin/gltf_regression.py:169-173`, `:166`, `:199`.
- Problem: `_cached_url_path` calls `resolver.fetch_url` (which returns the
  whole file's bytes, discarded) and then recomputes the sha1 key by hand.
  `resolver.cached_path` exists and its docstring says it is "the single
  definition of the on-disk key ... so no caller re-derives the path". The
  module also calls the private `resolver._default_cache_dir()`.
- Confidence: Confirmed.
- Suggested fix: use `resolver.fetch_to_cache` (or `fetch_url` followed by
  `resolver.cached_path(url, cache_dir)`), and make the default cache
  directory public if tools need it.

##### BIN-12 `oglc-mirrors --help` opens the demo and runs until killed

- Where: `OpenGLContext/bin/mirrors_demo.py:171` (entry point
  `pyproject.toml` `oglc-mirrors`). The file belongs to another reviewer.
  It is reported here because the entry-point check found it.
- Problem: `main()` has no argument parser, so `--help` is ignored and the
  window opens.
- Evidence: `timeout 20 oglc-mirrors --help` exits 124 and prints no
  `usage`.
- Confidence: Confirmed.
- Suggested fix: add `argparse.ArgumentParser(description=...).parse_args()`
  as the other demos do.

##### BIN-13 Docs: `physics.rst` repeats a sentence, and `viewer.rst` does not document `archive#member`

- Where: `docs/physics.rst:784-788`; `docs/viewer.rst`, where there is no
  mention of `#member` or archives.
- Problem: "The test suite also runs each one as a visual-regression test:
  it exits after a set number of frames, captures the frame, and compares it
  with a reference image." appears twice in a row. `oglc-view`'s docstring
  sends the reader to `docs/viewer.rst` for the new archive sources, but only
  `docs/lod.rst` uses `tar.gz#`, and the viewer page does not describe the
  syntax, the per-user extraction directory or the "exactly one scene needs
  no `#`" rule.
- Confidence: Confirmed.
- Suggested fix: delete the repeated sentence. Add an "Archives" subsection
  to `viewer.rst`.

#### Nit

##### BIN-14 Glosses and bold in `oglc-view`'s docstring and help

- Where: `OpenGLContext/bin/view.py:50` ("-- **which is what an archive is
  for**"), `:172-174` (help: "which is what makes a recording of a world
  rather than of a still").
- Problem: these are trailing "which is what..." glosses, one of them bolded,
  and the workspace writing rules name that form.
- Suggested fix: "A world of several files travels as an archive: naming a
  member with `#` ..." and "with --fly-through the camera walks the scene's
  own cameras in order".
- Confidence: Confirmed.

##### BIN-15 `--capture-image` and `--capture` are two spellings of one option

- Where: `OpenGLContext/bin/view.py:189-194`.
- Problem: both have `dest='capture'`. Both appear in `--help`, and if both
  are given the later one wins silently.
- Suggested fix: make one an alias in a single `add_argument('--capture',
  '--capture-image', ...)` so help shows one entry.
- Confidence: Confirmed.

##### BIN-16 `--fly-through` without `--capture-video` takes its length from `--video-seconds`, which the help does not say

- Where: `OpenGLContext/bin/view.py:180-188`, `viewer/sceneviewer.py:1024`.
- Problem: the help for `--video-seconds` says "how long the recording is",
  but it is also the wall-clock length of a fly-through that is not being
  recorded.
- Suggested fix: say so in the help, or add a `--fly-seconds`.
- Confidence: Confirmed.

##### BIN-17 Perception wording in `physics_events_demo` summary

- Where: `OpenGLContext/bin/physics_events_demo.py:2` ("...and the game
  hears about it"), `:258` (`# -- what the game hears`).
- Problem: the workspace rules ask for the mechanism to be named rather than
  giving the software a sense.
- Suggested fix: "each strike calls the subscriber registered for it".
- Confidence: Possible. It is borderline as a figure of speech in a demo.


### Documentation coverage and findings
#### Coverage table

The "indexed?" column records whether the page is in an `index.rst` toctree (T), described in `documentation.rst` (D), shown in the `index.rst` Features list (F), and named in `structure.rst` (S).

| Feature (commits) | Reference doc | Tutorial (docs/tutorials from tests/*.py) | Demo command | Indexed? | Issues |
|---|---|---|---|---|---|
| Planar reflections / mirrors (`REFLECTION*`, `MIRRORS`) | reflections.rst; surfaces.rst for the hall | none | `oglc-mirrors` | T D F; S no | DOC-07, DOC-08, DOC-22 |
| Zones: IBL, lights, audio, visibility, gravity; `OGLC_zone`; `EXT_lights_image_based` | zones.rst, zones-internals.rst, extensions/OGLC_zone.rst | `physics_gravity_zones` covers gravity only | none | T D; F no; S no | DOC-13, DOC-16, DOC-17 |
| Multiview and view chrome | multiview.rst | `multiview_quad` | `oglc-view --views quad` | T D F; S no (package missing) | DOC-12, DOC-18 |
| Content packs | contentpacks.rst | none | none of its own (`oglc-view <archive URL>`, `release-assets.py`) | T D F S | DOC-03, DOC-10 |
| Collision subscriptions; walker body in triggers | physics.rst (`physics-collisions`) | `tests/physics_events.py` has `'''` commentary but no page is generated: broken link | `oglc-physics-events` | T D F S | DOC-01, DOC-11, DOC-19 |
| Audio: application clips, areas, demo | audio.rst, audio-internals.rst | `audio_spatial` | `oglc-audio-demo` | T D F S | DOC-14 |
| Mesh LOD, `MSFT_lod`, impostors | lod.rst | none (`tests/lod_demo.py` has no commentary) | `oglc-view <gallery-world URL>` (content pack) | T D F; S no | none found |
| Procedural surfaces | surfaces.rst | none | `oglc-mirrors` (the hall) | T D F; S no | none found |
| Water: reflection, ripple, styles as nodes, hooks | water.rst | `water_demo` | `oglc-view tools/blender/demos/lakeside.glb` (checkout only) | T D F; S no | DOC-15, DOC-22 |
| Terrain holes, ground relief, stone | terrain.rst | none | `oglc-terrain`, not named on terrain.rst; `oglc-forest` (sibling project) | T D F; S no | none found |
| Vegetation ground cover, plant sets, canopy | vegetation.rst | none | `oglc-forest`, `oglc-bake-plants` (sibling projects) | T D F; S no | DOC-24 (Possible) |
| Engine hooks `OGLC_hook`: fire, smoke, sparks, water, mirror; Blender panel | gltf.rst (hooks), particles.rst, water.rst, reflections.rst | none | via `oglc-view` on the Blender demos | T D | DOC-20 |
| Resolver as public API | untrusted.rst | none | n/a | T D F | none found |
| Offscreen: EGL pbuffer suite, WGL | offscreen.rst, testing.rst | none | n/a | T D F | none found |
| PyInstaller hooks, `oglc-deb` | packaging.rst | none | `oglc-deb` | T D F S | DOC-09, DOC-21 |
| UI pointer shapes, tooltips, `ProgressBar` | overlayui.rst | `using_ui` | `oglc-ui-demo` | T D F S | none found |
| Viewer fills the screen, opens without the dev overlay | viewer.rst | n/a | `oglc-view` | T D F S | DOC-23 |
| `castsShadow=false`, still casters | shadows.rst (`castsshadow`) | `shadow_3` (existing) | n/a | T D F | none found |
| Telemetry | telemetry.rst | `telemetry_demo` | `python -m OpenGLContext.telemetry` | T D F S | none found |
| Sphinx documentation set | index, documentation, structure | generator `docbuild/tutorials.py` | `build-docs.py` | n/a | DOC-02, DOC-04, DOC-05, DOC-06, DOC-25 |

`documentation.rst` describes every page in every toctree, and no `.rst` page is outside a toctree. Every `[project.scripts]` command appears in the `documentation.rst` command list.

#### Findings

#### DOC-01 Major: physics.rst links a tutorial that is never generated
- Location: `docs/physics.rst:805`
- Problem: ``:doc:`physics_events.py <tutorials/physics_events>` `` has no target. `tests/physics_events.py` has `'''` tutorial commentary, but `docbuild/tutorials.py` `PATHS` does not list `physics_events`, so no page is written. The collision-events feature has no tutorial page, and the published link is broken.
- Evidence: the Sphinx build reports `physics.rst:805: WARNING: unknown document: 'tutorials/physics_events'`. The Physics `PATHS` entry in `docbuild/tutorials.py` lists ten scripts and not this one. My link checker found the same.
- Confidence: Confirmed
- Fix: add `'physics_events'` to the Physics path in `docbuild/tutorials.py`, after `physics_triggers`, and commit its screenshot `docs/tutorials/physics_events.py-screen-0001.png`.

#### DOC-02 Major: README changelog stops at 3.0.0a1
- Location: `README.md:131-133`
- Problem: `## Changelog` has only `### 3.0.0a1`. Nothing records 3.0.0a5 (released at `b67aaf5`) or the current range: mirrors, zones, multiview, content packs, collision subscriptions, LOD/`MSFT_lod`/impostors, surfaces, hooks, `oglc-mirrors`, `oglc-audio-demo`, `oglc-physics-events`, `oglc-deb`, PyInstaller hooks, telemetry, or the Sphinx set.
- Evidence: `grep -ci` in README.md finds 0 matches for reflect, mirror, multiview, content pack, telemetry, pyinstaller, oglc-deb, oglc-mirrors and oglc-physics-events.
- Confidence: Confirmed
- Fix: add entries for 3.0.0a5 and the release being cut, one short item per feature, each pointing at its `docs/*.rst` page.

#### DOC-03 Major: the content-pack base-pack example drops `within`
- Location: `docs/contentpacks.rst:359-366`
- Problem: the example is `wanted = fetch.missing_base(packs, store)` followed by `fetch.FetchJob(wanted, store)`. `missing_base` checks what a base pack needs *within* that pack, and its docstring says a caller fetching the set "passes the base pack as `within`". Following the page as written unpacks the needed packs into their own directories. The next run's `missing_base` still reports them missing, so the application asks the user again on every start. The prose "returns every base pack that is not on this machine, together with the packs those need" also misstates the check.
- Evidence: `OpenGLContext/contentpacks/fetch.py:96-104`: `store.missing(catalog.with_needed(pack, packs), within=pack)`.
- Confidence: Confirmed
- Fix: show a per-base-pack fetch that passes `within=`, as in `fetch.FetchJob(needed, store, within=base)`. If several base packs each need a different `within`, give `missing_base` a return value that pairs each pack with its `within`. Then reword the sentence after the example.

#### DOC-04 Minor: MANIFEST.in still names the HTML docs
- Location: `MANIFEST.in` (`include docs/*.html`, `include docs/style/*`, `exclude docs/tutorials/*.xhtml`)
- Problem: `docs/*.html` and `docs/style/` no longer exist. The sdist carries no `.rst` pages, `conf.py`, `_ext` or `_templates`. It also still ships `tests/*.py` and `tests/*.png`.
- Evidence: `ls docs/*.html` and `ls docs/style` both find nothing.
- Confidence: Confirmed
- Fix: replace those lines with `include docs/*.rst docs/conf.py`, `recursive-include docs/_ext *.py`, `recursive-include docs/_templates *.html` and the static files, or drop the docs from the sdist on purpose.

#### DOC-05 Minor: a docstring still points at an HTML tutorial
- Location: `OpenGLContext/passes/_flat.py:2102`
- Problem: "See docs/tutorials/shadow_1.html." That file is gone, and the tutorials are generated `.rst` under `docs/tutorials/` (not in git).
- Evidence: `ls docs/tutorials/shadow_1.html` finds nothing.
- Confidence: Confirmed
- Fix: "See the ``shadow_1`` tutorial (``tests/shadow_1.py``)", or the published URL `https://mcfletch.github.io/openglcontext/tutorials/shadow_1.html`.

#### DOC-06 Minor: the workspace environment cannot build the docs
- Location: `openglcontext/pyproject.toml:88` (the `docs` extra); the workspace `pyproject.toml` and `requirements-dev.txt`
- Problem: `docs/conf.py` loads `sphinxcontrib.mermaid`, which needs `pyyaml`. The workspace `.venv` has neither, because `uv sync` pulls each project's dev extra and not `docs`. `build-docs.py` and plain Sphinx both stop with `ExtensionError: Could not import extension sphinxcontrib.mermaid`.
- Evidence: the first two scratch builds failed with exactly that error, then with `No module named 'yaml'`.
- Confidence: Confirmed
- Fix: add `OpenGLContext[docs]` to the workspace sync, or put the docs requirements in the dev extra.

#### DOC-07 Minor: the reflection texture-unit threshold is off by one
- Location: `docs/reflections.rst:425-426`
- Problem: "A driver whose fragment stage has 32 texture units or fewer compiles reflections out." A driver with exactly 32 units keeps reflections.
- Evidence: `passes/reflection.py:57,61`: `REFLECTION_UNIT = 31` and `REFLECTION_UNITS_NEEDED = 32`. `passes/pbrpass.py:404` tests `texture_budget >= REFLECTION_UNITS_NEEDED`.
- Confidence: Confirmed
- Fix: "fewer than 32 texture units".

#### DOC-08 Minor: the Blender panel description leaves out Reflectance
- Location: `docs/reflections.rst:149-150`
- Problem: the panel is said to offer Resolution, Redraw Every, Priority and Distortion. It also offers Reflectance, which commit `3c503d5` added.
- Evidence: `tools/blender/oglc_hook/tag.py:91-94` has `MIRROR_PARAMETERS` including `'reflectance'`, and `__init__.py:139,172-174` draws it.
- Confidence: Confirmed
- Fix: add *Reflectance* (`reflectance`) to the list.

#### DOC-09 Minor: the packaging multicall example cannot run
- Location: `docs/packaging.rst:84-93`; the same gap is in the `OpenGLContext/packaging/multicall.py:12-20` docstring
- Problem: the example calls `sys.exit(run(COMMANDS))` but never imports `sys`.
- Evidence: the example as printed has no `import sys`.
- Confidence: Confirmed
- Fix: add `import sys` in both places.

#### DOC-10 Minor: environment.rst misses a user-facing variable and states a wrong reading rule
- Location: `docs/environment.rst`, whole page and lines 24-27, 34-38, 297-301, 334-337, 417-431
- Problem:
  - `OPENGLCONTEXT_CONTENT` is read by `contentpacks/store.py:30` and documented on contentpacks.rst, but it is not on the page that says it lists every variable.
  - Lines 34-38 say "Each is read the first time it is needed and then kept". Many variables are re-read on every call: `passes/bloom.py:53`, `scenegraph/tessellationlod.py:54`, `scenegraph/skinning.py:65`, `passes/shadowpool.py:76`, `passes/zonepass.py:624`, and the `ContextDefinition` defaults. `bin/gltf_demo.py:336` relies on bloom being read per frame.
  - Lines 24-27 name three variables as parsed without the warning. At least `DISABLE_FPS_DISPLAY`, `TRACE_STALLS` and `DEBUG_WHEEL` are also parsed that way, and any non-empty value, `0` included, turns them on. The page gives their values as yes/no.
  - `OPENGLCONTEXT_GLTF_BASELINE`'s default is `tests/reference_images/gltf_baseline` (`bin/gltf_regression.py:106`), not `tests/reference_images`.
- Evidence: the files and lines above. I re-checked `CONTENT` (0 matches on the page) and `GLTF_BASELINE` myself.
- Confidence: Confirmed
- Fix: add a `OPENGLCONTEXT_CONTENT` row. Restate the reading rule, or move those variables to the `_once` readers. Route the three flags through `env_flag`, or document "any non-empty value". Correct the baseline default.

#### DOC-11 Minor: one sentence is printed twice on physics.rst
- Location: `docs/physics.rst:784-788`
- Problem: "The test suite also runs each one as a visual-regression test: it exits after a set number of frames, captures the frame, and compares it with a reference image." appears twice in a row.
- Evidence: I read the page source.
- Confidence: Confirmed
- Fix: delete the second copy.

#### DOC-12 Minor: structure.rst has no row for the multiview package
- Location: `docs/structure.rst:117-255`
- Problem: the "packages inside OpenGLContext" diagram and table have no row for `OpenGLContext/multiview/`, which is new in this range. They also have none for `__pyinstaller`. The `passes` row links only renderpasses and profiles, not shadows, pbr, reflections, zones or lod. The `scenegraph` row does not link terrain, water, vegetation, surfaces or zones, although it names them.
- Evidence: `ls -d OpenGLContext/*/` against the table.
- Confidence: Confirmed
- Fix: add a `multiview` row that links multiview.rst, and extend the "Described in" cells.

#### DOC-13 Minor: zones have no front-page entry, demo or tutorial
- Location: `docs/index.rst:118-280` (Features); `pyproject.toml [project.scripts]`
- Problem: zones are one of the larger features in this range, but the front-page Features list mentions only "gravity zones" under physics. No installed command or tutorial shows lit rooms, local lamps, local ambience or visibility. The workspace rule is that a feature's demo is an installed `oglc-*` command. The Parthenon work (`68ac35c`) uses zones, but it lives outside the package.
- Evidence: `grep zones index.rst` finds only line 211 and the toctree. zones.rst names no command.
- Confidence: Confirmed
- Fix: add a Features item that links `zones`. Ship a small zone demo, or name an existing scene that shows zones, and make it a tutorial.

#### DOC-14 Minor: WebM audio is documented as decodable
- Location: `docs/audio.rst:48-51` and `310-312`
- Problem: `.webm` / `audio/webm` are listed as Opus inputs, but only Ogg Opus is recognised. WebM bytes go to miniaudio, which does not read WebM.
- Evidence: `omi_audio/src/omi_audio/_opus.py:146-158` requires `OggS`. There is no WebM demuxer in omi_audio. `omi_audio/formats.py:66-70` makes the same claim.
- Confidence: Likely
- Fix: remove WebM from both tables, or add a WebM/Matroska demuxer. Fix `formats.py` in the same change.

Question for the maintainer (DOC-14): omi_audio's `formats.OPUS` declares `audio/webm`, `video/webm` and `.webm`,
and audio.rst repeats it in both tables, but omi_audio's Opus decoder reads
only Ogg (`_opus.looks_like_opus` requires `OggS`) and nothing demuxes WebM,
so a `KHR_audio_emitter` source offering Opus in WebM is chosen where libopus
is present and then fails to decode instead of falling back to its MP3.
Options: (a) remove WebM from `omi_audio/formats.py` and from both audio.rst
tables, so such a source falls back to MP3 as any undecodable one does -- a
two-line change in omi_audio plus its tests, and an omi_audio release; or
(b) add a WebM/Matroska demuxer to omi_audio (EBML parsing of SimpleBlocks
into Opus packets, a few hundred lines with tests) and keep the claim.
Recommendation: (a) now, since glTF audio in the wild is Ogg or MP3, and (b)
only if a WebM source turns up. omi_audio belongs to the audio agent's area,
so I left both files unchanged.

#### DOC-15 Minor: two water.rst statements disagree with the code
- Location: `docs/water.rst:421-422` and `579-581`
- Problem:
  - Lines 421-422 say "a frame costs four `wave_time` writes". The demo updates five meshes: three pools, the lake and the ribbon. `tests/water_demo.py:46` repeats "four".
  - Lines 579-581 say water is "a PBR material with transmission". `water_material()` sets `transparency=0.10`, `alphaMode='BLEND'` and `ior=1.33`, and no transmission.
- Evidence: `tests/water_demo.py:210-214,282-291,331-333`; `scenegraph/water/surface.py:392-395`.
- Confidence: Confirmed for the count, Likely for transmission
- Fix: "five"; "a blended PBR material with an index of refraction of 1.33".

#### DOC-16 Minor: the zones loader list leaves out `EXT_lights_image_based`
- Location: `docs/zones.rst:122-124`
- Problem: the list of extensions the loader reads inside a zone omits `EXT_lights_image_based`. That extension is registered, and line 175 of the same page relies on it.
- Evidence: `loaders/gltf/zoning.py:198`.
- Confidence: Likely
- Fix: add it to the list.

#### DOC-17 Minor: API docstrings produce docutils errors in the generated reference
- Location: module docstrings behind `docs/api/`
- Problem: the build reports 75 warnings or errors, and 74 come from generated API pages. The engine's own are:
  - malformed tables in `OpenGLContext/demos/__init__.py` and `OpenGLContext/nav/navmesh.py` (the table's first column is narrower than its entries);
  - "Unexpected indentation" in `video/recorder.py`, `passes/instancing.py`, `contextconfig.py`, `character/crowd.py`, `bin/gltf_demo.py`, `bin/ui_demo.py`, `events/systemtime.py`, `events/eventhandlermixin.py`, `debug/state.py`, `scenegraph/polygonsort.py` and `scenegraph/teapot.py`;
  - unterminated inline literals in `ui/widgets.py`, `ui/session.py` and `passes/_flat.py`;
  - field-list ends in `scenegraph/terrain/heightfield.py`, `scenegraph/vegetation/billboards.py` and `move/terrainwalk.py`.

  The sibling packages add more: opengl_extrusions, opengl_decimate, pyopengl_video and OpenGLContext_editor.
- Evidence: `scratchpad/docrev/warnings.txt`.
- Confidence: Confirmed. The local `docs/api/` was generated on Sep 24 and lacks newer modules such as `scenegraph/zone`, `scenegraph/reflector`, `scenegraph/surfaces` and `physics/events`, so a fresh generation may add more.
- Fix: widen the two table columns, add blank lines before indented blocks, and close the literals. Consider `-W` for the non-API half in CI.

#### DOC-18 Nit: multiview.rst overstates two behaviours
- Location: `docs/multiview.rst:291-292` and `491-494`
- Problem:
  - Lines 291-292 say "`QuadView.frame` sets all three from the box". It sets `nearest` and `furthest` and calls `views.frame`, not `frame_box`.
  - Lines 491-494 say the chrome draws an axis triad in each view. The triad is drawn only where `view.camera is not None`, so the mixin's perspective view has none.
- Evidence: `multiview/quad.py:125-141`; `ui/viewchrome.py:459-463`.
- Confidence: Possible for the first, Likely for the second
- Fix: reword both.

#### DOC-19 Nit: physics.rst understates what `TerrainWalkMixin` overrides and names a command that does not exist
- Location: `docs/physics.rst:443`, `342`, `339`
- Problem:
  - Line 443 says the mixin "overrides three of the methods above and adds no work to the frame loop". It also overrides `characterCapabilities`, `physicsAvatarScale`, `applyMovementModes` and `DoEventCascade`, which clamps every frame.
  - Line 342 says "run the `physics-cook` tool". There is no such console command; it is `python -m OpenGLContext.bin.physics_cook`.
  - Line 339 says `auto` gives `trimesh` for static geometry. That holds only when indices are passed.
- Evidence: `move/terrainwalk.py:214-231,258-288`; `pyproject.toml [project.scripts]`; `omi_physics/cookery.py:52-59`.
- Confidence: Likely
- Fix: correct each sentence.

#### DOC-20 Nit: `OGLC_hook` has no extension specification
- Location: `docs/extensions/`
- Problem: `OGLC_zone` has a specification page, a JSON schema and examples. `OGLC_hook` is a vendor glTF extension that files in the wild carry, and its kinds and parameters are spread across gltf.rst, particles.rst, water.rst and reflections.rst.
- Evidence: `ls docs/extensions/schema` shows only `node.OGLC_zone.schema.json`.
- Confidence: Likely
- Fix: add `extensions/OGLC_hook.rst` and a schema listing each kind's parameters and defaults, and link it from those four pages.

#### DOC-21 Nit: the `oglc-deb` options list is incomplete and one statement is too strong
- Location: `docs/packaging.rst:192-238`
- Problem:
  - The options list leaves out `--distribution`, `--menu`, `--maintainer`, `--build-directory` and `-q/--quiet`.
  - The page says building the same input twice gives the same package. Without `SOURCE_DATE_EPOCH` the timestamp is `int(time.time())`, so two builds a second apart differ.
- Evidence: `packaging/deb.py:281-282,752-825`.
- Confidence: Likely
- Fix: list the options, and say that reproducibility needs `SOURCE_DATE_EPOCH`.

#### DOC-22 Nit: the Blender demo worlds are named by checkout paths
- Location: `docs/reflections.rst:404`, `docs/water.rst:567`
- Problem: `oglc-view tools/blender/demos/mirrors.glb` and `.../lakeside.glb` work only in a source checkout. `tools/` is not in the wheel or the sdist, and the page does not say so.
- Evidence: `MANIFEST.in` and `[tool.setuptools.packages.find]` include only `OpenGLContext*`.
- Confidence: Confirmed
- Fix: say "in a checkout", or publish both worlds as content packs, as the gallery is.

#### DOC-23 Nit: the viewer page is incomplete in three places
- Location: `docs/viewer.rst:444-458`, `478-479`, `6-10`
- Problem:
  - The `ViewerOptions` field list leaves out `views`, `list_cameras`, `sse`, `memory`, `no_recenter`, `cache_dir`, `capture_video`, `video_seconds`, `video_fps` and `fly_through`.
  - The "backend not installed" error names the *registered* backends, not the installed ones.
  - `.obj.gz` and archives with `#member` are not in the format table.
- Evidence: `viewer/options.py:48-156`; `viewer/__init__.py:83-89`; `bin/view.py:12,36-37`.
- Confidence: Likely
- Fix: complete the list, correct the error wording, and add the two input forms.

#### DOC-24 Nit: the vegetation block size is stated as fixed
- Location: `docs/vegetation.rst:151-153`
- Problem: "squares about 32 metres wide". The block size is `max(BLOCK_METRES, radius / BLOCKS_ACROSS)`, so the far rungs use wider blocks.
- Evidence: `scenegraph/vegetation/cover.py:570`.
- Confidence: Possible
- Fix: "at least 32 metres wide, wider for the far rungs".

#### DOC-25 Minor: writing-rule violations
- `README.md:24-61` has a bold-leader list. Every item of "What it does" opens with a bolded phrase and runs on ("- **Renders into five GUI toolkits** — GLFW …"). The changelog items at 139-199 have the same shape. Confirmed.
- `README.md:24` says "five GUI toolkits" and omits Tk. `index.rst`, `documentation.rst` and `backends.rst` say six. Confirmed.
- Bold sentence-leaders run paragraph after paragraph on some pages. `docs/roads.rst:304, 617, 644, 690, 736, 791, 798, 832, 839, 909` each opens with a bolded sentence (for example "**The whole marker is one draw.**"), and `testing.rst:426,476` does the same. This is the "bold in every item" shape the workspace CLAUDE.md warns against. Likely.
- Trailing glosses:
  - `reflections.rst:58` ("…, which is what tells it from an opening onto the same room.")
  - `reflections.rst:191` ("…, which is what a Blender …")
  - `reflections.rst:310` ("…, which is what its shelves pack.")
  - `contentpacks.rst:469` ("…, which is why it is a separate option.")

  Possible: each carries some fact, but has the form the rules name.
- Anthropomorphic wording: `physics.rst:167` ("a body that cares what it hit"). Nit, Likely.
- `environment.rst:274,281` open table cells with an italic leader ("*Presentation.* Render …"). It is a table rather than a list, so this is a Nit, Possible.
- The ai-isms scanner found two items, and both are false positives. `overlayui.rst:7` "licence notice" was flagged as perception. `viewer.rst:65` "refers to" is a literal reference.
- Fix: rewrite the README list with plain leaders ("Renders into six GUI toolkits - …") and add Tk. Take the bold off the roads.rst paragraph openers. Recast the glosses as plain facts.


#### Documentation findings added by the content-pack review

#### DOC-26 Major: the LOD page's demo command cannot work
- Location: `docs/lod.rst:21`; also `docs/contentpacks.rst:446-452`, which recommends GitHub releases as the host
- Problem: `oglc-view https://github.com/mcfletch/openglcontext/releases/download/content-v1/gallery-world.tar.gz` fails for two reasons. The asset returns 404, because the release has not been pushed. And even once it is pushed, the resolver refuses GitHub's redirect to `release-assets.githubusercontent.com` (CP-1). The documentation audit rated lod.rst as having no contradiction because it checked the page text against the code, not by running the command.
- Confidence: Confirmed
- Fix: fix CP-1, push the release before the engine release, and add a test that follows a cross-host https redirect.

#### DOC-27 Minor: contentpacks.rst documents protections the code does not give
- Location: `docs/contentpacks.rst:74`, `116-118`
- Problem: the page says `requires` makes an incompatible pack "declined rather than loaded", but nothing reads it (CP-6). It also presents "http or https" as equivalent for `url`, with no warning that a plain-http pack without `sha256` can be substituted in transit (CP-5). And it says a GitHub release asset has "a stable URL" while `publish.push --clobber` changes the bytes behind that URL (CP-2).
- Confidence: Confirmed
- Fix: bring the page in line once CP-2, CP-5 and CP-6 are fixed. Until then, state the limits.

### Checked and found sound

#### Content packs

- Zip-slip and tar path traversal: every member name is resolved against the destination before anything is written, and absolute names are refused (`archive.py:253-259`). Tar `filter='data'` refuses links pointing outside the tree, device nodes, and ownership and permission bits. Python's `zipfile` does not create symlinks.
- Zip bombs: sizes are summed from the headers before anything is written. CPython's `ZipExtFile` and `tarfile` both stop reading at the declared size, so an understated header cannot overrun the cap.
- The digest is checked before extraction, from the cached file, and a mismatch writes nothing into the store.
- The download cache write is atomic (`mkstemp` then `os.replace`). In-process single-flight prevents duplicate concurrent downloads of one URL.
- TLS: urllib's default HTTPS context verifies certificates and hostnames.
- `publish` handles no tokens itself: credentials stay with `gh`, and `subprocess.call` is given an argv list with no shell.
- `directory`, `namespace` and `key` regexes rule out `..`, absolute paths and separators. `directory_for` partitions content by namespace under `packs/`, so an added registry cannot address `registries/`.
- `FetchJob`: everything the worker writes is written under the lock, and `poll` copies it out. No shared state is read without the lock. The empty-job and double-start cases are handled.
- mypy (including `--strict`) and ruff are clean on `OpenGLContext/contentpacks/` and on the four `release-assets.py` scripts.
- `archive.write` is deterministic: entries are sorted in POSIX separator order, mtimes and gzip header are fixed at `EPOCH`, ownership is zeroed, and no file name is stored in the gzip header.

#### Physics, move, character, audio

- `ThreadedPhysicsManager.advance` takes snapshot, version and events under one lock (`latest_and_events`), so no event precedes its snapshot; events are drained every frame even with no subscriber, so the simulation's log cannot back up.
- `ThreadedPhysicsManager._remove_body` holds the world lock across `remove_body`; the world lock is the one `_loop` holds across step and publish, so a removal lands between ticks. `stop()` leaves undelivered published events for the next `advance`.
- `_write` skips bodies with `index is None` (removed) and `i >= len(pos)` (added after the snapshot).
- `PhysicsManager.remove` is idempotent, clears `body.index`, keeps a bounded `_retired` (FIFO eviction, tested), and `handle()` resolves a removed body's final events to the `PhysicsBody` (unthreaded case tested).
- Collision callbacks run after `sync`, on the thread calling `advance`, and exceptions in one callback do not stop the others.
- `immediate=True` is refused on the threaded manager via `steps_on_this_thread` before any world flag is changed (tested).
- `HeightFieldColliders._patch` now uses `terrain.holes.cut`, which keeps the original vertices in place and appends crossing corners, so the collider matches the drawn cut; indices stay valid (`test_heightfield_holes.py`).
- `collision_world_from_scene` adds zone gravity volumes before the early return, so a scene with zones and no triangles still gets them (`test_pbr_zones.py::TestGravity`); `scene_zones` walks the same `children` graph `_collect` does.
- `PhysicsViewPlatform.body` forwards `CharacterController.body` (None without one) and is tested with a trigger subscription in `test_physicsplatform.py`.
- Docstring link changes in `audio/__init__.py`, `humanoid.py`, `physicswalk.py`, `terrainwalk.py` point at files that exist (`docs/audio.rst`, `characters.rst`, `physics.rst`, `terrain.rst`, `navigation.rst`).
- ruff clean on all eleven files; mypy clean on all but `audio/scene.py`.

#### bin/, demos/, packaging

- Entry points: all 15 `[project.scripts]` targets import and resolve to a
  callable `main`. `--help` works for `oglc-view`, `oglc-gltf-regression`,
  `oglc-ui-demo` and `oglc-audio-demo` (the last with the BIN-9 noise).
  `oglc-physics-events` is in the installed metadata, but
  `.venv/bin/oglc-physics-events` is missing: the venv's console scripts are
  stale (metadata version 3.0.0a5, omi_physics 0.3.2 against source 0.4.0).
  That is an environment issue that `uv sync` fixes, not a code defect;
  `python -m OpenGLContext.bin.physics_events_demo --help` works.
- Short runs: `physics_events_demo` and `audio_demo` both exit 0 under
  `OPENGLCONTEXT_HIDDEN=1 OPENGLCONTEXT_AUTO_EXIT_FRAMES=30` and render (captures in
  `scratchpad/binrev/`). The physics yard is dressed in marble, brushed metals,
  brick, sandstone, plaster and glass, which meets the materials standard.
- ruff: clean on every file reviewed. mypy (`--follow-imports=silent`, per
  file): clean. As the workspace notes say, siblings resolve to `Any` in
  `.venv`, so that result says little across package boundaries.
- Testability: `CollisionYard` and `AudioYard` hold all of the demos'
  simulation and sound behaviour with no GL, and are exercised with real
  physics and a `NullDevice` engine in `tests/unit/test_physics_events_demo.py`
  and `tests/unit/test_audio_yard.py`. That covers the frame-rate
  independence of thuds, both pane-breaking paths, the gun, the plate and
  door, the areas, the motor pitch reaching the voice, and running without
  a device. `tests/physics_events.py` reuses the yard as the tutorial and
  visual test.
- Subscriptions on panes that `mend()` replaces are ended by
  `CollisionEvents._prune` once the body is removed, so repeated mending does
  not leak callbacks.
- Upper-case `L` keypress works on GLFW, where keypress events come from the
  character callback.
- Docs: `oglc-physics-events`, `oglc-audio-demo`, `oglc-mirrors`,
  `oglc-ui-demo` and `oglc-character-sheet` are listed in
  `docs/documentation.rst`, with demo sections in `docs/physics.rst` and
  `docs/audio.rst`. The `oglc-view` options `--views`, `--capture-video`,
  `--fly-through`, `--video-*`, `--capture-image` and `--fullscreen` are
  documented in `viewer.rst`/`capturing.rst`/`recording.rst`. Every
  `.html`→`.rst` link rewritten in `bin/` and `demos/` points at a page that
  exists.
- `view.py`: `ViewerOptions.window()` keeps a capture or recording out of
  fullscreen, and `test_viewer_options.py` tests that.
  `load_encoder_api()` is checked before a window opens.
  `test_viewer_archive_source.py` covers the archive source resolution.
- `gltf_regression.py`: `spec.shadows` exists on `SceneSpec`
  (`loaders/gltf_demos.py:54`), and shadowed captures stay deterministic
  because the run pins `OPENGLCONTEXT_SHADOW_CASCADES=3` (`:278`).
  `resolver.fetch_url` is the public name.
- `ui_demo.py`, `gltf_demo.py`, `demos/__init__.py`, `demos/packaging/*`:
  only doc-link changes, all to existing pages.
- `pyproject.toml` pins for `omi_physics>=0.4.0`, `PyVRML97>=2.4.0a2` and
  `pyopengl-video>=1.0.0a1` match the versions in the sibling sources.
  `timeout_method = "thread"` is explained and suits a suite that loads on
  worker threads.

#### Documentation

- Toctrees: every `docs/*.rst` and `docs/extensions/OGLC_zone.rst` is in an `index.rst` toctree. No orphans. `documentation.rst` has an annotated entry for every toctree page.
- Links: all `:doc:` targets resolve except DOC-01. All `:ref:` labels exist, and all image and figure paths exist. No relative `.html` links or `:target: *.html` leftovers point at missing pages; the Features figures' `:target: terrain.html` and similar resolve to built pages. `:mod:`/`:class:`/`:func:` targets for `OpenGLContext.*` import. The one exception is `OpenGLContext.wxcontext` (`backends.rst:285`), which fails only because wx is not installed here, and `nitpicky=False` renders it as text.
- No `docs/*.html` references remain in `pyproject.toml`, `CLAUDE.md` or `README.md`. The one in code is DOC-05. README's `docs/renderprocess.rst` mention is changelog history of a withdrawn page, which is appropriate there.
- Every `[project.scripts]` command appears in `documentation.rst` under Console commands. `oglc-view` has the `--views`, `--anim-time`, `--capture-video` and `--fly-through` flags the pages name.
- The hand-written `tutorials/physics_getting_started.rst` API matches the code: `DemoScene(debug_flags=…)`, `add_box`, `add_sphere`, `advance`, `scene_graph`, `debugdraw.PROXIES|CONTACTS` and `disable_vsync`. `cookery.cook_shape` is `omi_physics.cookery` (Nit: name the package).
- Pages with no contradiction found: terrain.rst, lod.rst, surfaces.rst (all four examples ran), zones-internals.rst, and most of reflections, multiview, contentpacks, physics, audio, zones, water, vegetation and packaging. The sub-audits verified more than 25 named claims per page: field defaults, env vars, key bindings, signatures, constants and demo files.
- History words: none of the "previously / no longer / used to / until now" kind in docs/*.rst. The matches for "replaces" and "no longer" describe run-time behaviour. No selling words ("blazingly", "the whole point", "exactly why") and no defensive clauses ("nothing here can") in the reference pages. `recording.rst:136`'s "nothing here can encode" is a code comment in an example about a missing encoder.

## Area 7: libraries (LIB)

Scope: opengl_decimate (a133686^..HEAD), omi_physics (4d94b53^..HEAD), omi_audio
(44e70b5^..HEAD), pyvrml97 (4d7a800^..HEAD, plus untracked state),
opengl_extrusions (40baea7^..HEAD), simpleparse (429f3dc^..HEAD), pyopengl-video
(363ec9b^..HEAD). Read-only review. Reproductions are in the scratchpad
(`dec_perf.py`, `dec_valence.py`, `mc2.py`, `np_check.py`), all run with
`/workspaces/OpenGL-dev/.venv/bin/python`.

Severity counts: Critical 0 · Major 3 · Minor 22 · Nit 22.

---

### opengl_decimate

Assessment: the heap path is in good shape. The compiled reducer and the NumPy
loop make the same decisions in the same order (direction choice, locked
placement, link condition, duplicate-face test, staleness by per-point version
against per-pair stamp all check out on reading). A 1,005,362-triangle noisy
grid reduces to 10% in 7.4 s on this machine (4.6 s in the compiled loop, 1.4 s
building the sequence, 0.9 s of that in a Python loop), and `at()` answers in
40-140 ms. Packaging is careful: sdist carries the tests, wheels are required
to carry the extension, the NumPy floor is exercised, both reducers run in tox.
The defects are in the `multiple-choice` schedule's stopping rule, in what the
documentation promises about floors, and in the `locked` API. The prose has
several of the forbidden constructions.

#### Major

LIB-D1. `multiple-choice` spends 20 × (initial edge count) failed draws before it stops
- Where: `opengl_decimate/src/opengl_decimate/simplify.py:378-410`
- Problem: the loop stops only when `failures` reaches `budget = max(1000, 20 * len(pool))`, and `budget` is fixed from the initial pool. Once the mesh is at its floor, or every drawn candidate is over `target_error`, every draw fails, so the reduction then spins through twenty draws per original edge, each one a `candidates()` pricing pass in Python. `collapse_sequence(..., schedule='multiple-choice')` always runs to exhaustion, so it always pays this, as does every `target_error` run on this schedule (the comment at 395-401 makes the failure budget the stopping rule on purpose).
- Evidence: `mc2.py`, closed icosphere with `target_count=0`: 1,280 triangles take 0.01 s on `heap` and 6.59 s on `multiple-choice`; 5,120 triangles take 0.02 s and 28.30 s. Both stop at 4 triangles. The cost grows with the edge count, so a 1M-triangle mesh would take hours.
- Confidence: Confirmed.
- Fix: stop on a failure budget sized to the *live* pool (for example a small multiple of `len(pool)` counted since the last success), or, once failures pass a threshold, fall back to one exhaustive `candidates()` pass over the pool and stop if nothing in it is finite and within budget. Add a test that bounds the work on a closed mesh run to exhaustion.

LIB-D2. An open surface reduces to nothing, which is the opposite of what README, `survey` and the tests say
- Where: `opengl_decimate/README.md:201-207`; `opengl_decimate/src/opengl_decimate/survey.py:7-9,84-92,120-129`; `opengl_decimate/tests/test_survey.py:83`; the missing check is in `collapse.py:38-50` and in `_reduce_native.pyx:479-516`
- Problem: the link condition has no boundary term. For a border edge `(a, b)` whose triangle's third corner `c` is also joined to both ends by border edges (a lone triangle), shared = {c} = opposite, so the contraction is allowed and the last triangle of a patch goes. The README's Limits section says "An open surface cannot be reduced past its own boundaries. Each border loop has a floor of three vertices", and also that "A reduction run to exhaustion will take a closed surface down to nothing". Both statements are wrong, and in opposite directions. `Survey.floor` documents "each open piece keeps at least one triangle" and `reducible` is computed from it, so the survey reports a floor that the reducer goes below.
- Evidence: a 10×10 open grid run to exhaustion gives 0 triangles on both paths, while `survey(...).floor == 1`. A closed octahedron stops at 4. A two-triangle square with `target_count=0` returns 0 triangles.
- Confidence: Confirmed.
- Fix: decide which behaviour is wanted. To keep a patch, add the boundary form of the link condition (treat a virtual vertex as joined to every border point, so a contraction whose three corners are all on one border loop is refused) in both reducers and in the equivalence tests. To let patches vanish, which leaf cards may want, correct the README Limits bullets, `Survey.floor`/`reducible`, `test_survey.py:83` and GALLERY.md, and state that a far LOD can drop whole open pieces.

LIB-D3. `locked` takes welded-point indices, and these differ from the caller's vertex indices on almost every real model
- Where: `opengl_decimate/src/opengl_decimate/options.py:140-141`; `opengl_decimate/docs/API.md` (`locked` row); `opengl_decimate/src/opengl_decimate/topology.py:410-419`
- Problem: welding at the default `weld_tolerance=0.0` still merges exactly coincident vertices, which is every UV seam and every hard edge. Points are numbered by first appearance, so every index after the first duplicate shifts. A caller who passes their own vertex indices, which the docs say are "the caller's own vertex indices unless vertices were welded", either gets an error or silently locks a different point.
- Evidence: two quads sharing an edge that is split for a UV seam (8 vertices, 6 welded points). `locked=[7]` (the caller's vertex (2,1,0)) raises "locked index 7 is past the end". `locked=[5]` (the caller's vertex (1,1,0)) locks welded point 5, which is (2,1,0), and the caller's (1,1,0) is moved to (0,0.5,0).
- Confidence: Confirmed.
- Fix: make `locked` take input vertex indices and map them through `vertex_point` inside `_Engine`. If welded points are also needed, add a separate `locked_points`. At minimum, state in the docs that seams and hard edges weld at zero tolerance, and expose the welding map before a reduction so a caller can translate.

#### Minor

LIB-D4. `import opengl_decimate.survey as m` returns the function, not the module
- Where: `opengl_decimate/src/opengl_decimate/__init__.py:23-26`
- Problem: `from opengl_decimate.survey import Survey, survey` rebinds the package attribute `survey` over the submodule. Since 3.7, `import a.b as c` resolves through `getattr(a, 'b')`, so it yields the function and `m.Survey` fails. `simplify` has the same collision, from before this change.
- Evidence: `import opengl_decimate.survey as m; type(m)` gives `<class 'function'>` and `hasattr(m, 'Survey')` is False.
- Confidence: Confirmed.
- Fix: rename the modules (`_survey.py`/`reduce.py`) or the functions. API.md already documents `opengl_decimate.certify`/`.topology` as modules, which makes the inconsistency visible.

LIB-D5. The default `normal_noise` does not condition the solve that the docs say it conditions
- Where: `opengl_decimate/src/opengl_decimate/options.py:108-113` and `DEFAULT_NORMAL_NOISE`; `quadrics.py:204-242`; `_reduce_native.pyx:975`
- Problem: `minimize` treats a matrix as determined only where `|det| > 1e-10 · max|a|³`. For coplanar planes with noise σ, det/mag³ ≈ σ⁴, so σ must exceed about 3.2e-3. The default is 1e-3, so under the default probabilistic metric a flat neighbourhood is still "undetermined" and falls back to endpoint or midpoint placement. The option docstring says of `normal_noise` "it is what conditions the 3x3 solve, so a single plane has a minimum".
- Evidence: `plane_quadric(..., normal_noise=s)` then `minimize`: determined is False for s=0.001 and 0.002 and True for 0.004 and 0.01.
- Confidence: Confirmed.
- Fix: scale the determinant test by the noise that was added (or test the smallest eigenvalue against σ²·weight), or raise the default. Add a test that the default probabilistic metric solves a planar fan.

LIB-D6. The compiled loop is superlinear in vertex valence
- Where: `opengl_decimate/src/opengl_decimate/_reduce_native.pyx:451-477` (`_ring` deduplicates by linear scan, O(d²)), `:539-556` (`_would_duplicate` is O(k²)), `:479-516` (link condition is O(|ring_a|·|ring_b|))
- Problem: every candidate touching a high-valence point re-derives that point's ring quadratically. The file's own comments name lathe poles, fan-triangulated n-gons and CAD hubs as inputs.
- Evidence: `dec_valence.py`, cone with one pole, reduced to 8 triangles on the compiled path: N=4000 takes 0.21 s, 8000 takes 0.86 s, 16000 takes 3.85 s, 32000 takes 5.84 s.
- Confidence: Confirmed (timings); Likely (attribution to the O(d²) scans).
- Fix: deduplicate the ring with a per-point stamp array (`seen[point] == epoch`) instead of a scan, and use the same stamp for the duplicate-face test (hash the sorted triple, or stamp the opposite-point pairs).

LIB-D7. The docs say normals are accumulated per point; the code accumulates per smoothing group
- Where: `opengl_decimate/src/opengl_decimate/options.py:132-135`; `opengl_decimate/docs/API.md:101`
- Problem: both say "Accumulated per point, so vertices split by a texture seam share a normal". `sequence._surface_normals`, README:76 and ALGORITHM.md:271 say it is per smoothing group, bounded by `crease_angle` and the input normals. The options text also says the result "carries a NORMAL whether or not the input did", which LIB-D9 contradicts.
- Confidence: Confirmed.
- Fix: rewrite both passages to describe smoothing groups and point to `crease_angle`.

LIB-D8. API.md and the README omit new public options, fields and switches
- Where: `opengl_decimate/docs/API.md` options tables and the `SimplifyResult` table; `opengl_decimate/README.md`
- Problem: `drop_components_below` (option), `dropped_away` (result field), `OPENGL_DECIMATE_NO_ACCEL` and `native.ACCELERATED` (how a user finds out whether the compiled reducer is active, which the README says decides whether a scan is feasible) appear in neither API.md nor the README.
- Evidence: grep counts are 0 in README, API.md and ALGORITHM.md for each of them.
- Confidence: Confirmed.
- Fix: add rows for the option and the field, and a short "Is the compiled reducer active?" section covering both names.

LIB-D9. An empty result with `recompute_normals` has no `NORMAL`
- Where: `opengl_decimate/src/opengl_decimate/sequence.py:289-301`
- Problem: the empty-surface early return copies the input's attributes, so an input without `NORMAL` comes back without one, although `recompute_normals` promises one. An open patch can reach zero triangles (LIB-D2), so this case does occur.
- Evidence: a single triangle with `target_count=0, recompute_normals=True` returns keys `['POSITION']` only.
- Confidence: Confirmed.
- Fix: add an empty `(0, 3)` float32 `NORMAL` when `recompute_normals` is set.

LIB-D10. `survey()` does not validate its input as `simplify` does, and cannot be told the options
- Where: `opengl_decimate/src/opengl_decimate/survey.py:132-143`
- Problem: a missing `POSITION` raises `KeyError` rather than `DecimateError`, and mismatched attribute lengths fail inside NumPy (`_check` is not called). `survey` accepts no `weld_tolerance` or `drop_components_below`, so for a scan, which is its target use, it reports pieces and floors for a different mesh from the one `simplify` will reduce.
- Evidence: `survey({'X': P}, F)` raises `KeyError 'POSITION'`.
- Confidence: Confirmed.
- Fix: call `simplify._check`, and accept `options: SimplifyOptions | None` so weld and drop settings are applied.

LIB-D11. `seam_share` does not measure the atlas boundary its docstring says it does
- Where: `opengl_decimate/src/opengl_decimate/survey.py:72-75,181-184`
- Problem: it counts edges whose two ends have different copy counts. Those are the edges leading from a chart's interior onto a seam. An edge running along a seam has both ends at two copies and is not counted. So the figure is "what `lock_seams` refuses", as the second clause says, and not "the boundary of the texture atlas".
- Confidence: Likely.
- Fix: correct the docstring, or add a separate count of edges whose sides disagree on texture coordinates (the complement of `atlas_charts`' `shared`).

LIB-D12. `lock_seams` compares only the number of copies at each end
- Where: `opengl_decimate/src/opengl_decimate/collapse.py:71-72`; `_reduce_native.pyx:800-801`
- Problem: a seam point may merge with any other point drawn at the same number of coordinates, including a point on a different seam across a chart one triangle wide, or a chord between two separate seam lines. The docstring's promise ("shortens a seam along its own length and never lets it wander off into a chart") needs the edge itself to lie on the seam: both sides disagree on UV across it, or its two faces are in different charts.
- Confidence: Possible (not reproduced).
- Fix: require, under `lock_seams`, that a contraction between two multi-copy points be along a seam edge. Add a test with a one-triangle-wide chart.

LIB-D13. The plan contradicts itself on M4 and on coverage
- Where: `openglcontext/plans/MESH-DECIMATION.md:3-5,9,21` against `:97-123`
- Problem: the status line says "Everything from M4 (the compiled accelerator) on is still plan" and the table lists M4 as plan, while the section below says "M4 landed". "100% statement coverage" does not cover the 980-line `.pyx` every wheel runs (REVIEW.md #14 "partly"). The plan also still describes an `opengl_decimate_accelerate` Rust package (`:804`) that was built as Cython inside the package.
- Confidence: Confirmed.
- Fix: update the status line, the table and the M4 milestone text, and qualify the coverage claim.

LIB-D14. Optimal placement has no bound, so near-singular solves can place a vertex far from its edge
- Where: `opengl_decimate/src/opengl_decimate/quadrics.py:233-242`; `_reduce_native.pyx:957-980`
- Problem: the solve is accepted at a relative determinant of 1e-10, which is a condition number near 1e10. Along a gently curved crease the minimiser slides along the valley direction to wherever rounding puts it. The cost there is small, so it can win against the endpoints, and only the normal-flip test guards the result.
- Confidence: Possible (from the construction; not reproduced).
- Fix: reject an optimum farther than some multiple of the edge length from the midpoint, or use Lindstrom's truncated-SVD solve anchored at the midpoint.

LIB-D15. `certify` counts the components `drop_components_below` removed as deviation
- Where: `opengl_decimate/src/opengl_decimate/simplify.py:64-72`
- Problem: the forward samples come from the whole input, dropped crumbs included, so `measured_error` reports the distance from each removed crumb to the subject. A caller who asked for the crumbs to go gets an error bound inflated by them.
- Confidence: Likely.
- Fix: certify against the input without the dropped faces (the `Topology` knows which they are), or report both figures.

LIB-D16. Every `simplify` call pays a per-contraction Python loop in `CollapseSequence.__post_init__`
- Where: `opengl_decimate/src/opengl_decimate/corners.py:198-256`; `sequence.py:121-135`
- Problem: `_ends_given_up` walks every contraction in Python. `simplify()` builds a full `CollapseSequence` only to call `.at()` once.
- Evidence: 0.86 s of the 7.4 s for a 1M-triangle reduction to 10% (`dec_perf.py --profile`).
- Confidence: Confirmed.
- Fix: compute winner and loser inside the compiled loop, which already has the positions and the placement, and return them with the log.

#### Nit

LIB-D17. Float index arrays are truncated silently
- Where: `opengl_decimate/src/opengl_decimate/topology.py:705-708`
- Problem: indices `[0, 1, 2.7, ...]` are accepted and cast to `[0, 1, 2, ...]`.
- Confidence: Confirmed.
- Fix: refuse a non-integer dtype with a `DecimateError`.

LIB-D18. The CI comments get Rosetta and the platform count wrong
- Where: `opengl_decimate/.github/workflows/release.yml` (runner table, "run the arm64 wheel through no translation: there is no Rosetta for a Python extension module"); the same claim in `opengl_extrusions/.github/workflows/release.yml`, `simpleparse/.github/workflows/build_and_publish.yml`, `pyvrml97/.github/workflows/build_and_publish.yml` and `omi_physics/.github/workflows/wheels.yml`. Also `opengl_decimate/.github/workflows/test.yml:23` ("Wheels are published for three platforms"; the release has four rows).
- Problem: Rosetta runs x86_64 code on Apple silicon. An Intel Mac cannot execute arm64 at all. The reason for the Intel runner is that simple fact.
- Fix: "Intel Macs cannot run an arm64 wheel, so they need one built on x86_64."

LIB-D19. Several passages break the workspace writing rules
- Where and what:
  - `topology.py:488`: "The difference is the whole cost on anything but a fan."
  - `pyproject.toml` `[tool.cibuildwheel]` comment: "which is the whole point".
  - `survey.py:7-24`, `corners.py:19-32` and `tools/gallery.py:11`: bold-leader paragraphs.
  - `options.py` `crease_angle` and `lock_seams` docstrings: measurement narrative ("costs a coastal-rock scan seventy per cent more vertices", "a third fewer extra vertices than forty does") that belongs in GALLERY/plans.
  - `certify.py:94-96` and `:143-146`: "not a slow measurement but one nobody waits for" and "not a slow measurement but a dead process" (negative parallelism).
- Confidence: Confirmed.
- Fix: `/ai-isms --fix` over `src/` and the workflows.

LIB-D20. `REVIEW.md` (1,228 lines) is tracked at the library root
- Where: `opengl_decimate/REVIEW.md`
- Problem: it is a work ledger with statuses, and it will go stale. It belongs in `plans/` (or the engine's plan) and not in the package's root.
- Confidence: Confirmed.

LIB-D21. The compiled path narrows indices without a check
- Where: `opengl_decimate/src/opengl_decimate/native.py:430-445`; `_reduce_native.pyx:398`
- Problem: `np.ascontiguousarray(..., dtype=np.int32)` wraps point indices above 2³¹ silently, and an incidence `3*i+slot` overflows `int` above about 715M faces.
- Fix: refuse such a mesh up front with a `DecimateError`.

LIB-D22. One step in the grid search is roundabout
- Where: `opengl_decimate/src/opengl_decimate/certify.py:277-286`
- Problem: `np.isin(np.arange(len(found)), at_best)` rebuilds the boolean mask `found == np.repeat(closest, sizes)` through a sort.
- Fix: use the mask directly.

LIB-D23. The heap and the sequence are loosely sized and typed
- Where: `_reduce_native.pyx:755` (`heap_init(&heap, 1024)`); `sequence.py:106-115`
- Problem: the heap starts at 1,024 entries although `edges.shape[0]` is known before seeding. `CollapseSequence.origin` and the `_moved*` fields are typed `Any`.
- Fix: size the heap from the edge count, and give the fields their array types.

LIB-D24. The two reducers treat an infinite price differently
- Where: `simplify.py:360` against `_reduce_native.pyx:838,863`
- Problem: the NumPy path skips an infinite price and the compiled path queues it (`fresh >= 0.0`). They diverge only where quadric arithmetic overflows.
- Fix: `isfinite` in both.

#### Documentation coverage

README, API.md, ALGORITHM.md and GALLERY.md were extended with the change and are mostly accurate. The gaps are:
- stale text (LIB-D7, LIB-D2 Limits);
- missing options, fields and switches (LIB-D8);
- a plan that contradicts itself (LIB-D13).

LIB-D25 - The CHANGELOG is absent. The project has none, and a feature this size lands without one.

#### Checked and sound

- Quadric math: the probabilistic `A`, `b` and `c` match the isotropic expectation, including `3σn²σp²`, and so does the note on what `s_p` changes.
- Local-origin shift: the Sterbenz argument holds under the `|c| ≥ 2h` rule.
- Border wall quadrics and area weighting.
- Heap staleness equivalence between the two reducers.
- Direction choice under BORDER and LOCKED kinds.
- Prefix replay:
  - `steps_for` uses a monotone `searchsorted` on remaining faces and on the running maximum deviation.
  - Pointer-jumped roots, and the placement taken from the last survival.
- Exactness of the grid nearest-triangle search (ring radius against `radius*side`).
- Memory handling in the `.pyx`: realloc through a temporary, and cleanup in `__dealloc__` and `heap_free`.
- MANIFEST and sdist contents.
- The tox accel/fallback assertions.

---

### omi_physics

Assessment: contact events are a well-built feature. They work over arrays and reuse the compiled solver's batch. Removal and generations are handled, and reporting that is off costs nothing (a test holds that). With every pair reported and persist events on, the tracker costs 4.5% of a step on a 300-box pile. Ray filters, sensor bodies, the character body and the EPA winding fix read correctly. The findings are edge cases in the tracker's state and failure handling.

#### Minor

LIB-P1. Keys in `ContactTracker.ignored` can outlive their pair
- Where: `omi_physics/src/omi_physics/contactevents.py:449-452,391-393`
- Problem: under `'flagged'` reporting, a pair whose flags are cleared is dropped without an `'end'` (by design), but its key stays in `ignored`, which only `_ends` or `reset` discard. If the two bodies meet again after being re-flagged, `presolve` excludes the pair without consulting the filter, although the pair "parted".
- Confidence: Possible.
- Fix: discard those keys from `ignored` where `update` drops unflagged pairs.

LIB-P2. An exception from a contact listener leaves the world part-way through a step
- Where: `omi_physics/src/omi_physics/world.py` `_deliver`, and `_CollisionStages` after `_record_contacts`
- Problem: a listener that raises aborts the step after the solve. The trigger update, sleep update, `time` and `step_count` do not advance, and the tracker's state already reflects the step. The next `step()` then runs from an inconsistent point. The docstring says listeners may remove bodies, so they are expected to do real work and can fail.
- Confidence: Likely.
- Fix: collect the exception, finish the step, and re-raise at the end; or log it and continue. Document which of the two applies.

LIB-P3. Version 0.4.0 has no changelog
- Where: `omi_physics/src/omi_physics/__init__.py:25`
- Problem: the release adds a public API (contact events, sensors, ray filters, trigger filters) and has no changelog. omi_audio keeps one.
- Confidence: Confirmed.

#### Nit

LIB-P4. Event arrays are shared views
- Where: `omi_physics/src/omi_physics/contactevents.py:431-433,478`
- Problem: `ContactEvent.point` and `normal` are views into one per-step array. The dataclass is frozen, but mutating one event's `point` changes the others, and each logged event keeps its whole step's array alive.
- Fix: copy each row into its own small array, or document that the arrays are shared.

LIB-P5. A stale `last_batch` is detected by comparing lengths
- Where: `omi_physics/src/omi_physics/world.py` `_record_contacts`
- Problem: `len(batch.a) != len(contacts)` is a coincidence test. It holds only because `solve()` resets `last_batch`.
- Fix: stamp the batch with `step_count`.

LIB-P6. The ray `filter` keyword is shadowed and undocumented
- Where: `raycast.py:85-100` and its siblings
- Problem: the keyword shadows the builtin `filter`, and it appears in neither README nor docs.

LIB-P7. `alive()` searches a list
- Where: `world.alive()`
- Problem: `i not in self._free` scans a list, so the cost is O(free slots) per call.
- Fix: keep a boolean array.

LIB-P8. The ray bundle test can be wide
- Where: `raycast.py` `_hit_triangles_many` with `dedup=False`
- Problem: the pass allocates `(R, T, 3)` temporaries, and duplicate cells inflate `T`. A widely spread bundle over a dense mesh pays memory for every candidate triangle once per ray.

LIB-P9. The contact log fills even when only listeners consume events
- Where: `world.py` `add_contact_listener`
- Problem: adding a listener switches reporting to `'all'`, so `contact_log` fills (up to 65,536 retained events, then drops) although nothing drains it.

LIB-P10. `ContactLog.dropped` is not exact under concurrency
- Where: `ContactLog.extend`
- Problem: the count is computed from `len()` before `extend`, so a drain racing on another thread miscounts it.

#### Documentation coverage

README gains a section on contact events, filters, sensors, the character body, `ContactLog` and `latest_and_events`. PIPELINE.md and ARCHITECTURE.md are updated. The ray `filter` keyword (LIB-P6) is missing, and so is a changelog (LIB-P3).

#### Checked and sound

- Tracker diffing: begin/persist/end, carrying of sleeping pairs by box overlap, retire on removal, generation bump.
- Delivery: listeners are queued re-entrantly, in step order.
- The contact filter's IGNORE_STEP and IGNORE_PAIR semantics against their docstrings.
- The kinematic-at-trigger broadphase rule. The character body sensor and the character's own static-touch reports do not double-report, because a kinematic-against-static pair never reaches the broadphase.
- `mathutil.cross` against `np.cross`.
- The EPA orientation fix.
- The trigger `collisionFilter` glTF round trip.

---

### omi_audio

Assessment: small and clean. `set_rate`, `surf` and `birdsong` are straightforward. The reverb is correctly vectorised: the stretch-length argument holds, and it allocates nothing per block. The issues are in its acoustics and in claims about it.

#### Minor

LIB-A1. The comb delays share a factor in samples
- Where: `omi_audio/src/omi_audio/reverb.py:43-46`; `omi_audio/docs/MIXING.md` Reverb section
- Problem: "no two share a factor" is not a property of real-valued seconds. At 48 kHz the delays round to 1426/1781/1973/2098 samples, and 1426 and 2098 share 2.
- Confidence: Confirmed.
- Fix: choose delays in samples that are mutually prime per sample rate (primes nearest the targets), or drop the claim.

LIB-A2. The reverb omits Schroeder's allpass stage
- Where: `omi_audio/src/omi_audio/reverb.py:7-13`
- Problem: Schroeder's reverberator is parallel combs followed by series allpass diffusers. Four combs alone give a sparse, metallic, fluttering tail. The docs call the design "Schroeder's arrangement".
- Confidence: Likely (on acoustic grounds; not auditioned).
- Fix: add two allpasses (about 5 ms and 1.7 ms). They vectorise by the same stretch argument.

LIB-A3. The wet signal is not normalised against the comb gain
- Where: `omi_audio/src/omi_audio/reverb.py:132-143`
- Problem: a feedback comb's gain near resonance is about 1/(1−g), and `level` is described as "how loud the reverb is against the dry mix".
- Evidence: with `level=1` and decay 1.2 s, a 0.2-peak 440 Hz tone comes out at a 0.39 peak, and 0.43 at 4 s decay. A near-full-scale mix clips at the device.
- Confidence: Confirmed.
- Fix: scale by (1−g), or by an RMS-normalising constant, and state the headroom in the docs.

#### Nit

LIB-A4. Bold-leader bullets and a defensive preface
- Where: `omi_audio/CHANGELOG.md`; `omi_audio/README.md` Limits
- Problem: the new CHANGELOG entries are bold-leader bullets. The edited README Limits bullet sits under "Stated up front, because finding out later is worse".

LIB-A5. The delay lines can decay into float32 denormals
- Where: `omi_audio/src/omi_audio/reverb.py`
- Problem: with `level > 0` and silent input, the lines decay through the denormal range and can slow the per-block NumPy operations on x86.
- Confidence: Possible.
- Fix: flush lines below about 1e-30 to zero.

#### Documentation coverage

CHANGELOG, README (module table and limits) and MIXING.md (a new Reverb section with a units table) are all updated. The one inaccurate statement there is LIB-A1.

#### Checked and sound

- The feedback formula for a 60 dB fall.
- The ring read and write at one delay.
- The level ramp and the clear-at-zero idle path.
- `set_rate` relative to the clip's native rate.
- The seamless wrapping in `surf` and `birdsong`.

---

### pyvrml97

Assessment: path matrices built on the parent path's matrix are correct. A comparison against the previous whole-path `compressMatrices` construction agrees for forward and inverse matrices, over a chain Transform/Group/Transform/Transform/Shape, before and after field changes (`np_check.py`). The cascade clear is sound. There are no tracked uncommitted changes. The untracked item is `.claude/worktrees/frame-overhead`, a registered git worktree.

#### Minor

LIB-V1. `builtOn` gains a dead weak reference for every transient path
- Where: `pyvrml97/vrml/cache.py:196-211` (`depend_holder`); `vrml/vrml97/nodepath.py:113-129`
- Problem: every new path holder appends a weak reference to its parent path holder's and each Transform's local-matrix holder's `builtOn`. The lists are pruned only when that source is cleared, so a static transform under which paths are created and discarded grows without bound.
- Evidence: 10,000 transient `base + [t]` paths leave 10,000 entries in `t.localMatrices().builtOn` and in the base path holder's `builtOn`. `NodePath.children` has the same accumulation, which predates this change.
- Confidence: Confirmed.
- Fix: give each weak reference a callback that removes it, or compact the list when it reaches twice its live count.

#### Nit

LIB-V2. The cache lookup is written out twice rather than made fast once
- Where: `vrml/vrml97/basenodes.py:587-588`; `vrml/vrml97/nodepath.py:72-75,86-87`
- Problem: the two call sites inline `CACHE.get(id(x)).get(key)`. The workspace rule is to fix a slow call at its source.
- Fix: make `CACHE.getHolder` cheap enough and call it.

LIB-V3. A path whose own nodes do not transform returns its parent's matrix array
- Where: `vrml/vrml97/nodepath.py:143-150`
- Problem: this is documented, but a caller that modifies the result in place now corrupts the parent's cached matrix as well as its own.
- Fix: say "do not modify the returned array" in the docstring, or return a read-only view.

LIB-V4. A git worktree sits untracked inside the submodule
- Where: `pyvrml97/.claude/`
- Problem: `pyvrml97/.claude/worktrees/frame-overhead` is registered in `git worktree list`, and `.claude/` is not ignored.
- Fix: remove the worktree once merged, or add `.claude/` to `.gitignore`.

#### Documentation coverage

The docstrings on `transformMatrix`, `depend_holder` and `_clearBuiltOn` describe the behaviour. No user docs were needed.

#### Checked and sound

- Forward and inverse product order (`dot(own, base)` against `dot(base, own)`) under compressMatrices' `dot(item, first)` accumulation.
- The cascade stops at already-clear holders.
- The fast path of `NodePath.__getitem__`.

---

### opengl_extrusions and simpleparse

CI only: an Intel macOS row (`macos-15-intel`) was added to the wheel matrices. The rows are correct. The Rosetta explanation in the comments is inaccurate (see LIB-D18). Nothing else changed.

---

### pyopengl-video

Assessment: a real fix. VAAPI passed zero durations through, which produced unplayable MP4s. The default now lives on the base class and all three backends call it, with tests at the container level and on real VAAPI.

#### Minor

LIB-W1. The new docstrings narrate history
- Where: `pyopengl-video/src/pyopengl_video/encoder.py:186-200`; the class docstrings in `tests/test_mp4.py` and `tests/test_vaapi_encode.py`
- Problem: "two of the three had the same three lines and the third did not, and the one that did not was the one writing unplayable files" and "the default was wrong: this backend passed the zero straight through" are history, which the workspace rules forbid in docstrings. There is also a bold lead-in ("**Every backend puts an incoming duration through this**").
- Fix: keep the reason (a zero duration makes the container's length zero), in the present tense.

LIB-W2. A rounded default duration drifts against exact timestamps
- Where: `encoder.py:201-204`
- Problem: at 24000/1001 fps in a 90 kHz timescale, each frame is rounded to 3754 ticks instead of 3753.75. MP4 derives decode time from the sample durations (stts), so a long recording drifts about 0.24 s per hour from the caller's timestamps.
- Confidence: Possible.
- Fix: derive a frame's duration from the next frame's timestamp where one follows (or carry the rounding remainder), and use `frame_duration` only for the last frame.

#### Nit

LIB-W3. A zero frame-rate numerator raises `ZeroDivisionError`
- Where: `frame_duration`
- Fix: raise `EncoderError` instead.

LIB-W4. A test reads a private attribute
- Where: `tests/test_mp4.py::test_while_the_pictures_are_all_there`
- Problem: it asserts on `writer._durations`.

#### Documentation coverage

No user documentation was changed. The behaviour (a duration of 0 means one frame) is in the `encode` docstring, which is where a user of this API looks.

## Area 8: openglcontext-editor (ED)

Scope: `git -C openglcontext-editor diff e557177^ HEAD` (20 commits, 83 files,
+13.9k/-0.4k: Poly Haven fetching and plant baking, billboard cards, rewrap,
meshlod chain/quality/asset, the Blender LOD add-on and bust gallery, zones and
probe baking, loose stone, road places, portal funnels and bore openings, grain
in tiled ground) and the uncommitted working tree (six files: the species
field rename to the engine's camelCase node fields).

Method: read every new source module in full or in the parts that carry logic;
reproduced suspected defects under the scratchpad with the workspace venv
(scripts `stones_size.py`, `card_clip2.py`, `leaf_grain.py` beside this file).
`ruff check src tests tools` is clean. No suites or preflight were run.

### Assessment

The geometry is careful and mostly well-reasoned: the place boxes, the node
TRS order, the MSFT_lod plan, the gap-closing rule and the hole cutting all
check out. The weak points are at the seams between systems: what the bake
draws and what the game collides against are derived by two different code
paths with different parameters (grain at leaf tiles, bore openings); a bake
step that renders (`bake_card`) has an untested clip-space error that empties
the card of any spreading plant; one new layer puts 8 MB of JSON into
`tileset.json`, against a rule the vegetation layer states for itself; and the
packaging does not ship what two of the new features need (the add-on
manifest, the omi_audio that has `synth.birdsong`). Several glTF readers and
writers are hand-rolled here beside the engine's own. The README covers the
grain, stone, clearing, portal, meshlod, Blender and rewrap work, but not the
zones/ambience/probe bake or `oglc-bake-plants`.

Counts: Critical 0, Major 11, Minor 26, Nit 12.

### Critical

None found.

### Major

#### ED-M1 - Leaf tiles are meshed with no grain; the collided landscape has it
`openglcontext-editor/src/OpenGLContext_editor/bake/layers.py:243` (`height_fn_for`),
`openglcontext-editor/src/OpenGLContext_editor/bake/driver.py:234`,
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:1074` (`detail_error`)

Problem: the driver bakes leaf cells at `leaf_error` (default 0.0, and
glisteel-bake passes none). `HeightfieldLayer.height_fn_for(footprint, error)`
hands that error to `Relief.over`, whose amplitude is `min(wanted, error)`, so
every leaf tile - the finest, the one drawn up close - is meshed with zero
grain. The landscape beside the tileset (what a car is driven on) is built by
`ProceduralWorld.detailed()` at `detail_error()` = root error / 2**depth, which
is non-zero. The README and `grain_drawn()` promise "the finest tile and the
surface under it are one surface"; in practice grain appears at mid distance,
vanishes as the tile refines to its leaf, and the car rides relief that is not
drawn.

Evidence: `leaf_grain.py` with `ProceduralWorld(ground="tiles", depth=7)` on a
32 m cell: `error 0.00 -> max |grain| 0.000 m`, `error 1.45 -> 0.442 m`,
landscape grain 0.442 m.

Confidence: Confirmed.

Fix: the layer should hold relief for a leaf at the leaf's *nominal* error
(`cell.geometric_error(root_error)` without the leaf override), or the driver
should pass the nominal error to `content()` and write `leaf_error` only into
the tileset. Add a test that bakes a two-level tree and compares the leaf
mesh to `landscape().height_fn`.

#### ED-M2 - `bake_card` clips away any plant deeper than it is tall
`openglcontext-editor/src/OpenGLContext_editor/assets/card.py:192`

Problem: the orthographic matrix scales x by `1/half_width` and y by
`2/height`, but passes z through unscaled (`[0, 0, -1, 0]`). Positions are
height-normalised to 1, so any vertex with |z| > 1 lies outside clip space and
is discarded. `half_width` is taken over x *and* z, so the same plant also gets
a card as wide as its depth. A spreading ground cover (periwinkle, a shrub,
any plant wider than tall in plan) comes out partly or entirely transparent -
and it is exactly the ground cover this module bakes.

Evidence: `card_clip2.py`: two unit cards at z = +/-0.2 give width 1.0,
coverage 0.276; the same cards at z = +/-2.0 give width 4.0, coverage 0.0.

Confidence: Confirmed.

Fix: scale z into [-1, 1] by the plant's own depth extent (for example
`-1/half_width`), and decide explicitly whether the card width comes from the
x extent (the view) or the horizontal radius (the billboard), then test a
plant deep in z.

#### ED-M3 - Loose stone writes 8 MB of JSON into `tileset.json` extras
`openglcontext-editor/src/OpenGLContext_editor/bake/stones.py:135`,
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:741`

Problem: `StoneLayer.metadata()` returns every stone's `Prop.to_json()`, and
the driver folds layer metadata into the tileset's `extras`. The default world
places about 58,000 stones (STONE_DENSITY 0.004 over 4096 m square), so every
client that opens the world parses 8 MB of JSON before streaming anything. The
vegetation layer states the rule this breaks
(`bake/vegetation.py`, `_table`: "four megabytes of binary and eighty of JSON,
and the tileset's extras is read by everything that opens the world") and
writes an `.npz` asset instead.

Evidence: `stones_size.py`: `stone_layer 3.7 s, 58011 stones`,
`metadata bytes 8122568`.

Confidence: Confirmed.

Fix: write the stones as a binary asset (npz of position/yaw/scale/kind index,
radius and height per kind) and put only its name and count in extras; have
the engine, not glisteel (`glisteel/world.py:888`), read it and build the
`PropColliders`.

#### ED-M4 - The Blender add-on's manifest is not in the wheel
`openglcontext-editor/pyproject.toml:105`,
`openglcontext-editor/src/OpenGLContext_editor/blender/__init__.py:146`

Problem: `package-data` lists only `py.typed`, so
`blender/openglcontext_lod/blender_manifest.toml` is not installed.
`addon_version()` then raises, so `python -m OpenGLContext_editor.blender
--package` (the documented route for an author) fails from any pip install, and
`install()` copies an add-on without the manifest Blender 4.2's extension
installer requires.

Evidence: in the non-editable `.preflight-venv`, `blender.addon_version()` ->
`FileNotFoundError ... openglcontext_lod/blender_manifest.toml`; the
site-packages directory holds only the `.py` files.

Confidence: Confirmed.

Fix: add `"blender/openglcontext_lod/blender_manifest.toml"` to package-data,
and a test that the manifest is importable as package data
(`importlib.resources`), which the preflight's non-editable install would then
exercise.

#### ED-M5 - Zones need an omi_audio no release carries, and the editor names no floor
`openglcontext-editor/src/OpenGLContext_editor/bake/zones.py:139`,
`openglcontext-editor/pyproject.toml:44`

Problem: `place_sounds()` calls `omi_audio.synth.birdsong` and `synth.surf`,
added in omi_audio fbb7c10 (2026-09-24), after the latest tag v0.3.0a1. The
editor imports omi_audio directly but does not declare it; the engine's floor
is `omi_audio>=0.2.0a1`. `ProceduralWorld.places` defaults to True, so a
released-stack bake of any world with a forest or causeway fails in
`ZonesLayer.assets()` with an AttributeError. The same pattern may hold for
`opengl_decimate` (`certify.nearest_triangle`, 2026-09-16, while the version
string is still 0.1.0a1 and nothing is tagged).

Confidence: Confirmed (omi_audio); Possible (opengl_decimate).

Fix: declare `omi_audio>=<next release>` in the editor's dependencies and bump
opengl_decimate's version and the floor together.

Question for the maintainer (ED-M5): The source is ready for opengl_decimate 0.2.0a1 (version bumped, CHANGELOG
written, editor floor raised to >=0.2.0a1), and nothing is tagged or pushed.
0.1.0a1 was never published (PyPI answers 404 for the project), so 0.2.0a1
would be the first release. Pushing opengl_decimate's main to GitHub cuts it
through release.yml. Should it be published now, and before or with the
editor's next release? Until it is, a released-stack install of the editor
cannot resolve its opengl_decimate floor. Recommendation: publish 0.2.0a1
first, then the editor.

#### ED-M6 - The bore opening the tiles are cut with is not the one the game collides with
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:1041`,
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:1185`,
`glisteel/glisteel/world.py` (`_bores`)

Problem: the bake cuts tile holes with `bore_opening(points[first:last+1],
self.height_fn(), tunnel=tunnel_profile(), approach=BORE_APPROACH_CELLS *
ground_spacing())`, where `tunnel_profile()` widens `portal_border` to the
finest tile spacing and `ground_spacing()` is the tile spacing (8 m at
defaults). The game rebuilds its collider holes from the road record with the
default `TunnelProfile`, `field.sample` (the gridded landscape) as ground,
station-selected centreline points and `approach` from the *field* spacing
(4 m). `bore_opening` sizes the mouth from `tunnel.portal_border`
(`roadworks.py:598-600`), so the two masks differ in width, crown height and
approach length. Nothing about the bake's choice is recorded in the world, so
no consumer can reproduce it.

Confidence: Likely (the parameters differ by reading; the size of the visible
mismatch was not measured).

Fix: one engine function that derives a world's bore openings from what the
world file records (tunnel profile, approach, ground), called by both the bake
and the game; or write the mouth outlines into the world.

#### ED-M7 - `bake_probes`: process-wide environment, engine privates, untestable loop
`openglcontext-editor/src/OpenGLContext_editor/bake/probes.py:54-157`

Problem: it sets `OPENGLCONTEXT_RENDERER/PROFILE/IBL` in `os.environ` and never
restores them, so every later context in the process (an editor session, a
test) renders differently. It drives the capture by reading
`flat._zoneCaptures` and `flat._ibl_probe`, private members of the engine's
pass, so any engine refactor breaks the bake silently. The capture loop (frame
budget, the `captured >= bounces + 1 and not waiting` condition, the zone to
light mapping) lives inside the `with Baker(...)` block where no test reaches
it; `test_bake_probes.py` covers only `_rewrite`, `_png` and the no-zones exit.
Baking a zone's image-based light from a loaded world is something a game
(bake-on-first-run, a level editor) wants too.

Confidence: Confirmed.

Fix: an engine API on the zones pass (for example `bake_zone_lights(context,
terrain) -> [(zone, irradiance, mips)]`) with the scheduling hoisted into a
plain object, environment passed as context options rather than `os.environ`,
and this module reduced to writing the files.

#### ED-M8 - glTF is read and written by hand in four places beside the engine's loader and writer
`openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:114-188`,
`openglcontext-editor/src/OpenGLContext_editor/meshlod/asset.py:108-388`,
`openglcontext-editor/src/OpenGLContext_editor/bake/zones.py:934-974`,
`openglcontext-editor/src/OpenGLContext_editor/blender/openglcontext_lod/sky.py:190-241`

Problem: `plants._document/_accessor/_local_matrix` is a private glTF reader
that ignores sparse accessors, `normalized` (KHR_mesh_quantization texcoords),
accessors without a bufferView, primitive `mode` (a strip is read as a list)
and non-indexed primitives (skipped silently). `meshlod.asset` writes GLB
chunks by hand and `LODAsset` reads them, beside the engine's `GLTFWriter` and
its MSFT_lod loader (`OpenGLContext/loaders/gltf/lod.py`). `ZonesLayer.document`
builds the `OGLC_zone` / `KHR_audio_emitter` JSON whose reader is the engine's
`loaders/gltf/zoning.py`, so the format has two owners in two repositories.
The Blender add-on is exempt (it cannot import the engine), the rest are not.

Confidence: Confirmed.

Fix: read plants through the engine loader (or pygltflib, already an engine
dependency); move the lazy sidecar reader and the zone/emitter document writer
into the engine next to their readers; write the LOD glb through `GLTFWriter`.

#### ED-M9 - `--canopy` is documented as the opposite of what the engine reads
`openglcontext-editor/src/OpenGLContext_editor/bin/plants.py:65-68`,
`openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:335`

Problem: the CLI help says the band is "canopy light ... 0 under a closed
canopy to 1 in the open" (metavars DIM, BRIGHT), and `bake()` calls it "the
band of canopy light it grows in". `CoverSpecies.canopy` is tree *closure*: 0
on open ground, rising with cover (the forest's own `cover.json` uses
`[3.0, 16.0]`). An author following the help puts shade plants in the open and
sun plants under the canopy.

Confidence: Confirmed.

Fix: rename the metavars to LEAST MOST, describe it as the engine does, and
cite `SplatTerrain.canopy_cover` for the units.

#### ED-M10 - `oglce-gallery` accepts a stale glB as a successful build
`openglcontext-editor/src/OpenGLContext_editor/bin/gallery.py:124-133`

Problem: `blender.run` documents that Blender exits 0 after a Python traceback
in `--background`. `build()` treats `returncode == 0 and exists(output)` as
success, so when `build.py` raises, a glB left by an earlier run passes, and
`roof()` then appends a second sky image, texture and sampler to it
(`with_sky` is not idempotent).

Confidence: Likely.

Fix: remove or rename the target before running, and require the `WROTE:`
line from `build.py` (it already prints one); make `with_sky` replace an
existing sky.

#### ED-M11 - (uncommitted) The committed editor does not match the committed engine
`openglcontext-editor/src/OpenGLContext_editor/world/species.py:43-63`,
`openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:386-406`,
`openglcontext-editor/src/OpenGLContext_editor/bake/vegetation.py:161-197`

Problem: engine e6f3ddd (2026-09-24) turned `TreeSpecies`/`CoverSpecies` into
scenegraph nodes with camelCase fields and `varied()`. Editor HEAD still
constructs them with `solid_texture=`, `card_width=`, `clump_mesh=` and
`dataclasses.replace`; the working-tree diff is the fix. Until it is committed
the editor's HEAD is broken against the engine's HEAD, and a bisect across
either repository lands on a tree that does not import-and-bake.

Confidence: Likely (by reading; HEAD was not run).

Fix: commit the rename together with, or immediately after, the engine change,
and note the coupling in the commit message. The diff itself reads correctly.

### Minor

#### ED-m1 - Poly Haven cache trusts any non-empty file
`openglcontext-editor/src/OpenGLContext_editor/assets/polyhaven.py:113-129,195-203`
`_save` and `_asked` write in place and treat `getsize(path) > 0` as complete,
so an interrupted download or a partly written JSON answer is cached for good
(the JSON one then raises on every later run). Write to a temporary name and
`os.replace`. Confirmed.

#### ED-m2 - A downloaded `.gltf` can read any local file into a baked asset
`openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:140`
`os.path.join(beside, unquote(uri))` follows `../` and absolute URIs from a
document fetched off the network; the bytes are read as a buffer and can end up
in the shipped `.glb`. `polyhaven._under` and `meshlod.asset` already confine
through `Resolver`; this reader does not. Confirmed.

#### ED-m3 - Slugs are used unvalidated in cache paths
`openglcontext-editor/src/OpenGLContext_editor/assets/polyhaven.py:120,239`
`'%s-%s.json' % (kind, slug)` and `join(directory, slug)` accept `../`. The slug
comes from the command line, so the risk is low, but a slug pattern check is
one line. Confirmed.

#### ED-m4 - Redirects are followed without re-checking the host
`openglcontext-editor/src/OpenGLContext_editor/assets/polyhaven.py:92-99`
`require_host` checks the first URL; `urlopen` follows redirects anywhere.
Possible.

#### ED-m5 - Two MSFT_lod writers disagree on default coverage
`openglcontext-editor/src/OpenGLContext_editor/meshlod/asset.py:291` writes
`0.5/2**i` for every level, so the coarsest is culled below its threshold;
`blender/openglcontext_lod/msftlod.py:74` (`coverage_series`) ends with `0.0`
so the coarsest is never culled, and its comment says halving "matches what
OpenGLContext's reader assumes". One of them is wrong for the engine. Confirmed.

#### ED-m6 - `write_chain(embed_coarsest=0)` writes an invalid glB
`openglcontext-editor/src/OpenGLContext_editor/meshlod/asset.py:368`
Buffer 0 is emitted with `byteLength: 0`, no `uri` and no BIN chunk; glTF
requires `byteLength >= 1` and buffer 0 without a uri to be the BIN chunk.
Confirmed.

#### ED-m7 - `LODAsset` misreads any component type but float and uint32
`openglcontext-editor/src/OpenGLContext_editor/meshlod/asset.py:172`
Anything not 5126 is read as `<u4`, so a glB with 16-bit indices from another
tool loads garbage instead of raising. Confirmed.

#### ED-m8 - `_rewrite` matches zones to nodes by position
`openglcontext-editor/src/OpenGLContext_editor/bake/probes.py:159-177`
The light index comes from `terrain.zones.zones` order, which the engine's
`ZoneReader` builds in scene-walk order and skips zones with a bad shape; the
rewrite enumerates every node carrying `OGLC_zone`. Correct for documents this
package writes, wrong for any other. A second run also appends another set of
images without removing the first. Key by node name. Possible.

#### ED-m9 - `KHR_audio_emitter` usage is outside the extension
`openglcontext-editor/src/OpenGLContext_editor/bake/zones.py:224`
The draft defines `audio/mpeg` as the audio MIME type; `audio/wav` is not in it,
and emitters are referenced from inside `OGLC_zone.extensions` rather than from
a node or scene. Fine for the engine's reader; a third-party reader will not
play them. Document it in the engine's OGLC_zone spec. Likely.

#### ED-m10 - Impostor bake uses a render-engine name Blender 5 removed
`openglcontext-editor/src/OpenGLContext_editor/blender/openglcontext_lod/impostor.py:53`
`BLENDER_EEVEE_NEXT` is the 4.2-4.x identifier; Blender 5.0 uses
`BLENDER_EEVEE` again, and the manifest sets no `blender_version_max`. Pick
whichever the running Blender offers. Likely.

#### ED-m11 - `tomllib` on Python 3.10
`openglcontext-editor/src/OpenGLContext_editor/blender/__init__.py:153`
`requires-python >= 3.10` and CI runs 3.10, where `tomllib` does not exist, so
`addon_version()` and `package()` fail there. Confirmed.

#### ED-m12 - A bake step renders through the engine's test helper
`openglcontext-editor/src/OpenGLContext_editor/assets/card.py:151,166`
`OpenGLContext.testing.glcontext.hidden_window` is the suite's fixture; the
engine has `EGLContext` for headless work, and `probes.py` uses it. No
framebuffer completeness check before drawing. Confirmed.

#### ED-m13 - `oglc-bake-plants --no-cards` writes a manifest naming files it did not write
`openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:387`
`card='%s_card.png'` is set whether or not a card is baked;
`world.species.shipped_cover` then raises LookupError on the missing file.
Confirmed.

#### ED-m14 - Name collisions across assets
`openglcontext-editor/src/OpenGLContext_editor/bin/plants.py:115-122`,
`openglcontext-editor/src/OpenGLContext_editor/bake/vegetation.py:197`
`cover.json` is keyed by variant name, and cards are `<variant>_card.png`, so
two slugs with a node of the same name overwrite each other's card and entry.
`VegetationLayer._under` keeps only the basename, so two species files named
alike from different directories collapse to the first. Possible.

#### ED-m15 - Grain is inert at the shipped defaults
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:500,1085`
With extent 4096, resolution 33, depth 4 and field_resolution 1025, the only
band left after `no_finer_than(4 m)` is 16 m, and at the 8 m finest-tile
spacing `bands()` needs features of 64 m or more: `grain_drawn().bands(8.0) ==
()`. The README's "Detail the tiles carry" section reads as though a default
world has it. Say which depth and field resolution it needs. Confirmed.

#### ED-m16 - The tree depth is configured twice
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:507`
`ProceduralWorld.depth` drives `detail_error()`, `ground_spacing()` and the
portal border, and the bake's own `depth` argument decides the real tree;
nothing checks they agree (glisteel-editor's `app.py:799` passes `depth=4`
whatever the world says). Let the bake take the depth from the world. Possible.

#### ED-m17 - The portal funnel measures from the nearest stretch of road, whichever it is
`openglcontext-editor/src/OpenGLContext_editor/world/road.py:1172`
`road_height` is the height of the nearest centreline point. On a hairpin or a
spiral that passes over or beside its own portal within `face + PORTAL_CUT`,
that is another stretch, and the funnel is hung from the wrong height: a crater
if it is lower, no cut if it is higher. Measure from the portal's own run.
Possible.

#### ED-m18 - A bore across a closed circuit's seam is two bores
`openglcontext-editor/src/OpenGLContext_editor/world/road.py:344` (`portals`),
`:1515` (`_op_runs`), `:451` (`structure_runs`)
Runs are split at index 0/n-1, so a tunnel through the start line gets two
portals in the middle of the hill (and two mouths, and two places). Possible.

#### ED-m19 - `flatten` centres a plant on its vertex mean
`openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:257`
A dense clump on one side drags the centre, so the instanced plant stands off
its position and the card is lopsided. `meshlod.chain.bounding_sphere` uses the
box centre for this reason. Confirmed.

#### ED-m20 - Stones state both "no collider" and "solid"
`openglcontext-editor/src/OpenGLContext_editor/world/procedural.py:269` says
the loose stone is "carrying no collider, so the surface a car is driven on is
the landscape"; `bake/stones.py:17-24` says a stone is solid and stood up as a
`PropColliders` dome, and `stone_layer` gives each one `shape='dome'`. One of
them is wrong. Confirmed.

#### ED-m21 - (uncommitted) Shared mutable species constants
`openglcontext-editor/src/OpenGLContext_editor/world/species.py:42-69`
`SHIPPED` and `COVER` are now module-level scenegraph nodes, which are mutable;
the frozen dataclasses they replace were not. A caller that sets a field on
`SHIPPED[0]` changes every later world. Build them in a function, or document
that `varied()` is how to change one. Possible.

#### ED-m22 - `rewrap` rasterises one face at a time in Python
`openglcontext-editor/src/OpenGLContext_editor/assets/rewrap.py:212-232`
A per-triangle loop with a meshgrid each; a 100k-triangle level at 2048 is
100k Python iterations. `sample` is nearest-neighbour, which aliases wherever
the new atlas is denser than the source. Confirmed (cost not measured).

#### ED-m23 - Tile content boxes are closed on both sides
`openglcontext-editor/src/OpenGLContext_editor/bake/stones.py:144-152`
`>= minimum & <= maximum` puts a stone exactly on a shared face into both
siblings. The same convention is used by props and scatter layers already, so
it is a package-wide choice to make half-open. Possible.

#### ED-m24 - `with_sky` embeds a JPEG as a base64 data URI inside a glB
`openglcontext-editor/src/OpenGLContext_editor/blender/openglcontext_lod/sky.py:222`
A glB carries images in its BIN chunk through a bufferView; a data URI costs a
third more bytes and lands in the JSON every loader parses. Confirmed.

#### ED-m25 - Public API typed as `Any`
`world/procedural.py` `stones()`, `stone_layer()`, `bore_openings()`,
`grain_applies()`, `seated_on()`; `assets/rewrap.py` every array field and
return; `bake/field.py:108` `drawn: str` (a `Literal['field', 'tiles']`).
The concrete types exist (`Scatter`, `StoneLayer | None`, `Holes | None`,
`HeightFn`). Confirmed.

#### ED-m26 - `_SEARCH` comment describes something else
`openglcontext-editor/src/OpenGLContext_editor/blender/__init__.py:59-61`
It says it is where Blender's Python lives and is only used for messages; it is
the executable name searched on PATH. Confirmed.

### Nit

- ED-n1 `openglcontext-editor/src/OpenGLContext_editor/blender/__init__.py:11-18` and
  `blender/openglcontext_lod/__init__.py:5-10`: bold-leader bullet lists
  (`* **levels of detail on any object** -- ...`), which the workspace rules
  forbid. Many module docstrings also open paragraphs with a bold sentence
  (`assets/plants.py:6-24`, `meshlod/asset.py:13-26`, `assets/polyhaven.py:13,20`,
  `bake/stones.py:17`, `world/structures.py:281`).
- ED-n2 `openglcontext-editor/src/OpenGLContext_editor/world/structures.py:304-307`:
  "Measured on Beacon, where the ground stands 1.4 m ... 117 km/h" is a
  history note in a docstring.
- ED-n3 `openglcontext-editor/src/OpenGLContext_editor/world/species.py:66-67,137-138`:
  "which is what there was before there were sets of them", "art baked before
  there were sets of them" - history.
- ED-n4 `openglcontext-editor/src/OpenGLContext_editor/assets/polyhaven.py:5-6,22-24,149-150`:
  "it is the decent thing and costs a line", "hammering them ... is not a way
  to say thank you" - commentary on the fact rather than the fact.
- ED-n5 `openglcontext-editor/src/OpenGLContext_editor/assets/rewrap.py:9-10,134`:
  the lekking-ruffs anecdote, and an unwrapper that "dutifully gives" charts
  back (perception/character).
- ED-n6 `openglcontext-editor/src/OpenGLContext_editor/assets/polyhaven.py:233`: the
  comment explaining the `raise` sits after it, unreachable in reading order.
- ED-n7 `openglcontext-editor/src/OpenGLContext_editor/assets/plants.py:360`:
  `import io` in the middle of `bake()`.
- ED-n8 `openglcontext-editor/src/OpenGLContext_editor/meshlod/asset.py:220`:
  `del path` to silence an unused parameter; drop the parameter.
- ED-n9 `openglcontext-editor/src/OpenGLContext_editor/meshlod/quality.py:130-150`:
  `LevelReport` exposes `_share` as a constructor argument behind a
  `reduction` property.
- ED-n10 `openglcontext-editor/pyproject.toml:87-90`: `oglce-gallery` beside
  `oglc-bake-plants` and `oglc-bake`; one prefix.

Question for the maintainer (ED-n10): The editor ships three console scripts under two prefixes: `oglc-bake-plants`
and the deprecated `oglc-bake` beside `oglce-gallery`. The engine's own commands
are all `oglc-` (`oglc-view`, `oglc-zones`, ...). Options: (a) rename
`oglce-gallery` to `oglc-gallery`, one prefix across the stack, at the risk of a
name that looks like an engine command coming from the editor distribution; or
(b) move the editor's commands to `oglce-` (`oglce-bake-plants`), which marks
them as authoring tools and keeps the engine's namespace to itself, at the cost
of renaming a documented command (with a one-release alias, as `oglc-bake`
has). Recommendation: (b), `oglce-` for everything the editor installs, with
`oglc-bake-plants` kept one release as an alias that says where the command
went; docs/lod.rst and the editor README would follow. Nothing was renamed.
- ED-n11 Docstring summaries that narrate: `polyhaven.fetch` "and say what came",
  `plants.bake` "and say what species it grew", `bin/plants.main` "write what
  grew".
- ED-n12 `openglcontext-editor/src/OpenGLContext_editor/bake/stones.py:141-152`: the
  per-kind `[i for i in mine if self.stones[i].kind == kind]` re-reads Python
  attributes per stone per kind; keep a kind index array beside `_plan`.

### Engine or editor

- Belongs in the engine: the zone-light capture loop (ED-M7); the OGLC_zone /
  emitter document writer next to `loaders/gltf/zoning.py` (ED-M8); lazy MSFT_lod
  sidecar reading (`LODAsset`) next to `loaders/gltf/lod.py` (ED-M8); reading the
  stones record and standing them up (ED-M3, currently in glisteel); deriving a
  world's bore openings from its record (ED-M6).
- Duplicated with the engine: the plant glTF reader and the LOD glB writer
  (ED-M8).
- ED-n13 - `wav_bytes` is small, but omi_audio is the audio owner.
- Placement is right for: `world/places.py`, `bake/zones.zone_records`,
  `assets/polyhaven`, `assets/plants`, `meshlod.chain/quality`, the Blender
  add-on (which cannot import the engine; `test_octahedral_agreement.py` keeps
  its copy of the fold honest).

### Documentation coverage

Updated in the range: README sections on levels of detail, the Blender add-on,
rewrap, grain, loose stone, the cleared corridor, portal excavation;
`docs/blender.md` (new).

Missing or wrong:
- ED-d1 - Zones, places, ambient sound, and `bake_probes` / `EXT_lights_image_based`
  are not in the README at all; `ProceduralWorld.places` is undocumented
  outside its field comment.
- ED-d2 - `oglc-bake-plants`, `cover.json` and Poly Haven fetching have no README
  section; the Layout table's `bin/` row omits `oglc-bake-plants`.
- ED-d3 - "What a bake writes beside the tiles" lists `world.json` only: not
  `zones.gltf`, `audio/*.wav`, `probes/`, the stones record, `terrain.drawn`.
- ED-d4 - `pyproject.toml:89` and `blender/__init__.py:30` point to `docs/blender.html`;
  the file is `docs/blender.md`.
- ED-d5 - README (portal paragraph, around line 596) says the funnel keeps
  `PORTAL_SOIL` of ground over the face; `conform_terrain` uses
  `tunnel.clearance + tunnel.portal_border` and never reads `PORTAL_SOIL`.
- ED-d6 - README calls `STONE_DENSITY`, `STONE_RADIUS`, `STONE_SLOPE_LIMIT` knobs "on
  the world"; they are module constants, not `ProceduralWorld` fields.
- Grain: no statement of the depth/field resolution at which it appears (ED-m15).
- `--canopy` help (ED-M9); stone collider contradiction (ED-m20).

### Test gaps

- No test of a card for a plant deep in z (ED-M2), nor of leaf-tile grain (ED-M1).
- `bake_probes`' capture path is not reachable by a test (ED-M7).
- No test that the add-on manifest ships (ED-M4) or that a failed Blender run is
  reported (ED-M10).
- No test that the bake's and the game's bore openings agree (ED-M6).
- ED-t1 - No test of `ZonesLayer.document()` against the engine's `ZoneReader`
  round-trip (only `probes._rewrite` reads it back).
- ED-t2 - `plants._accessor`'s interleaved branch, quantized/normalized accessors and
  strip primitives are untested.

### Checked and sound

- `places._pieces`: heading `atan2(-az, ax)` maps local +X onto the chord under a
  +Y rotation; local +Z matches `side = (-az, ax)`; `size` is (along, up,
  across) in the same frame; the eye is expressed in the box frame.
- `plants._local_matrix`: T * R * S, quaternion to matrix correct; normals use
  the inverse transpose.
- `structures._close_gaps`: a gap is handed to a bridge only where the road is
  above ground and to a bore only where it is below; causeways unchanged.
- `layers._opened`: attributes carried through the cut, unused vertices
  compacted, the inverse reshaped to 1-D (safe for either NumPy 2 inverse
  shape); a fully swallowed tile returns no content.
- `road.conform_terrain`: the funnel only lowers ground (`np.minimum`); a sample
  beyond the road search radius gets height 0 but the funnel radius
  (`face + PORTAL_CUT`) is always inside `reach`, so no spurious crater.
- `msftlod.plan/_write`: finest carries `ids` in decreasing detail, one coverage
  per level, alternatives detached from scenes and children, `children`
  dropped rather than left empty; repeats and partial coverage refused.
- `meshlod.asset`: sidecar buffer indices agree with buffer order; every uri
  confined by `Resolver` and every accessor size checked before reading.
- `polyhaven`: host allow-list, 512 MB cap, per-user 0700 cache, write
  confinement of published relative paths through `Resolver`.
- `zones.document`: `KHR_implicit_shapes` box form and `size` as full extents.
- `chain.build_chain`: one recorded collapse sequence, stop when no further
  reduction is possible, certified error by surface sampling.
- The uncommitted rename is complete within the package: no snake_case species
  fields remain in `src`, `tests` or `tools`.
- `ruff check src tests tools`: clean.

## Area 9: games, glisteel-editor, openglcontext-qt and workspace tools (GAME)

Scope: glisteel (`bbc2916^..HEAD` plus uncommitted), glisteel-editor (`997fcbd^..HEAD` plus uncommitted), openglcontext-forest (`5c077f8^..HEAD` plus uncommitted README/release-assets), twig-bb (`b299750^..HEAD` plus uncommitted), marble-demo (`87ae811^..HEAD`), marble-editor (`8bf5e49^..HEAD`), openglcontext-qt (`5492840^..HEAD`), and the root repository's `tools/`, `verify-everything.py`, `pyproject.toml` commits since 2026-09-12 plus the uncommitted `tools/release*`, `pyproject.toml`, `requirements-dev.txt`, `.gitignore`.

Method: read every source diff; confirmed suspected defects with scratch reproductions under the scratchpad (`marble_stale.py`, `marble_log.py`, `adopt.py`, `forest_order.py`). Nothing in any working tree was modified. `ruff check` is clean in every project reviewed.

Severity counts: Critical 2, Major 12, Minor 36, Nit 13.

---

### Cross-cutting (content packs and release tooling)

Three consumers (glisteel, openglcontext-forest, twig-bb) moved onto `OpenGLContext.contentpacks` in this range, which is the right direction. What each of them kept for itself is near-identical code, and two of the three copies carry a first-run defect from the same pattern (binding the asset root at import).

#### GAME-X1 (Major) - Three copies of the release-assets command

Where: `glisteel/release-assets.py:113-287`, `openglcontext-forest/release-assets.py:51-192`, `twig-bb/release-assets.py:51-160`

Problem: `build()`, `install()`, `push()` and the `--tag/--into/--install/--reinstall/--push` parser are the same code three times over, down to identical docstrings. The uncommitted `install()` docstring ("what a second build of a world wants") was pasted into forest and twig-bb, which have no worlds. The workspace CLAUDE.md says a project's own script should say only what to build and what the registry says about it. The flag handling, the store install loop and the push are the engine's job. glisteel's `bundle_registry()` also writes the zip format that the engine's `catalog.load_bundle` reads, so writer and reader live in different repositories.

Evidence: diff the three `install()` and `main()` bodies. The only differences are the namespace, the tag default and whether the registry is rewritten whole or one entry at a time.

Confidence: Confirmed.

Fix: add a `publish.main(spec, argv)` (or a `ReleaseAssets` class) to `OpenGLContext.contentpacks.publish`. It would take the namespace, URL template, catalog path and a `declare(into, tag) -> entries` callback, and would also own `bundle_registry`. Each script then shrinks to its `declare()`. Move forest's `refuse_pointers` into `archive.write()` so every game that uses Git LFS is protected.

#### GAME-X2 (Major) - Three copies of the "base pack or the wheel" resolver, all bound at import

Where: `glisteel/glisteel/content.py:57-169` with `glisteel/glisteel/models.py:37`; `openglcontext-forest/src/openglcontext_forest_demo/content.py:38-74` with `scene.py:46`; `twig-bb/twig_bb/art.py:36-56` with `combatsound.py:80`

Problem: each game has its own `registry()` cache, `store()`, `needed_to_start()` and `art_directory()`, and the `art_directory` docstring is identical in all three ("Both, deliberately ... When it does leave, this is the only place that has to stop looking there"). Each then freezes the answer into a module constant at import time (`ART = AssetLibrary(content.art_directory())`, `ASSETS = content.art_directory()`, `ASSETS = assets_directory()`). A pack fetched after import is never used by that process. Only the forest has actually removed the art from its wheel (see GAME-F1). In glisteel and twig-bb the same defect waits for the day their art leaves the wheel. Both READMEs already say the base pack "is fetched before the menu" or "before the first match", and no code in either game does it (GAME-G3, GAME-T3).

Evidence: `forest_order.py` in the scratchpad shows that `scene.HEIGHTMAP` keeps the import-time root after `content.art_directory()` changes. `grep needed_to_start` finds callers only in tests (glisteel) and in forest `run.fetch_art`. twig-bb has no caller at all.

Confidence: Confirmed.

Fix: give the engine an application-level object, for example `contentpacks.Application(namespace, catalog_path, fallback=...)`. It would hold `registry()`, `store()`, `base_directory()` (resolved on each call, or through a lazily bound `AssetLibrary`) and `ensure_base(progress, consent)` for console and UI use. Games then read paths through it at use time rather than through import-time constants. The download panel that glisteel and twig-bb each wrote (size of the whole set, terms, progress, failed or stopped) belongs in `OpenGLContext.ui` too. The engine has none today (`ls OpenGLContext/ui`).

---

### glisteel

Assessment: a large and well-tested feature drop: autopilot passing, traffic evasion, synthesized car sound, content packs, preferences, journal marks and `glisteel-diagnose`. The core logic is hoisted into plain objects (`CarSound`, `Autopilot`, `TrafficCar`) and tested windowless, which is good practice. Four problems stand out. The menu screens this range added do not close themselves. Download failures are never shown. The journal loses stretches that are still open when a run ends. The docstrings are full of development history. Several capabilities belong in the engine.

#### GAME-G1 (Major) - The Driving and Downloads screens never close; panels accumulate

Where: `glisteel/glisteel/menu.py:193-235` (`driving_screen`), `menu.py:246-290` (`download_screen`), `glisteel/glisteel/game.py:384-437` (`show_downloads`, `_on_fetch`, `_on_driving`)

Problem: neither screen calls `panel.close()` from its buttons. `track_screen` and `finish_screen` do, through `finish()`.
- "Use this" on the Driving screen calls `_on_driving` then `show_menu`, which pushes the menu on top and leaves the modal Driving panel underneath. `_on_resume` drops only the panel named `menu`, so the Driving panel is left over the race until Escape is pressed.
- `_on_fetch` calls `show_downloads()` without dropping the existing `downloads` panel, so two are stacked.
- "Close" on Downloads calls `show_tracks`, which drops only `menu`. That pushes a second track screen above the downloads panel and above the first track screen, which is unnamed and so can never be dropped.

Evidence: `menu.py` `chose()` and `cancel.on_activate` only call the callbacks. `OverlayStack.push` does not replace (`ui/overlay.py:343`). `show_menu` returns early only if a `menu` is already open.

Confidence: Confirmed by reading. There is no test, because every caller is `# pragma: no cover - needs a window`.

Fix: close the panel in `chose`, `cancel` and `start` as `track_screen` does, with the same `answered` guard. Name the track screen and drop it or reuse it in `show_tracks`. Have `show_downloads` replace an existing `downloads` panel. Add screen-level tests like the existing `test_it_answers_once_however_often_it_is_pressed`.

#### GAME-G2 (Major) - A failed or stopped download is never shown to the player

Where: `glisteel/glisteel/game.py:417-433` (`pollDownloads`)

Problem: when `job.finished` becomes true, `self._fetching` is set to None before the screen is rebuilt, and the rebuild passes `job=self._fetching`, which is now None. `_progress(None)` returns `''`. The screen therefore goes straight back to idle, and "Could not download: ..." and `STOPPED` never reach the player. `menu.py` has tests for both texts (`test_one_that_failed_says_so_rather_than_looking_idle`, `test_one_the_user_stopped_is_not_reported_as_a_failure`), but the game never renders them. Nothing offers to cancel a job either, so `STOPPED` cannot happen at all. The finished job's new track also does not appear in the track screen underneath (see GAME-G1) until the player reopens it.

Evidence: `if job.finished: self._fetching = None` comes before `self.show_downloads()`, which reads `job=self._fetching`.

Confidence: Confirmed.

Fix: keep the last finished job (for example `_last_fetch`) and render it until the next fetch starts, or pass `job` explicitly to the rebuild. Add a Stop button wired to `FetchJob.cancel()`. Refresh the library when a job finishes.

#### GAME-G3 (Major) - The base pack is documented as fetched before the menu; nothing fetches it

Where: `glisteel/glisteel/content.py:7-9,92-99`, `glisteel/README.md` ("a first run fetches something before it shows a menu"), `glisteel/glisteel/models.py:37`

Problem: `needed_to_start()` has no caller outside tests. `models.ART` is resolved at import. The wheel still ships `assets/**/*.glb`, so nothing breaks today. The README and the module docstring describe behaviour the game does not have. The day the art leaves the wheel, glisteel fails exactly as the forest does (GAME-F1).

Confidence: Confirmed.

Fix: implement the first-run fetch (with consent) before `GlisteelContext` builds a session, and resolve `ART` lazily (GAME-X2). Until then, correct the README.

#### GAME-G4 (Major, uncommitted) - `_note_a_touch` drops later, separate car contacts

Where: `glisteel/glisteel/session.py` uncommitted `_note_a_touch` (around line 876)

Problem: the hold-off counter is decremented only when `_note_a_touch` is called, which happens only on steps where the car is touching traffic. It is not decremented on every physics step. After one touch, the next `BUMP_AGAIN / PHYSICS_STEP` (60) contact steps are suppressed however far apart in time they are. A second, unrelated collision a minute later is silently left out of the journal. `_watch_for_a_bump` gets this right: it decrements before its early returns on every step.

Confidence: Confirmed by reading.

Fix: decrement `_touched` once per step in `advance()` (or at the top of `_watch_for_a_crash`, before the early returns), as `_watch_for_a_bump` does. Add a test with two touches separated by a clear gap.

#### GAME-G5 (Major) - Journal stretches still open at the end of a run are never written; refusals straddle passes

Where: `glisteel/glisteel/driver.py:338-372` (`held_back`), `driver.py:641-671` (`refused`), `driver.py:470-478` (`_pull_out`), `glisteel/glisteel/session.py:298-314` (`_mark_the_end`)

Problem:
- A `crawled` mark is written only when crawling stops, and a `pass-wanted` mark only when the reason changes. A run that ends while crawling therefore never writes the `crawled` mark, and that is the "stuck" outcome the mark exists to explain. `diagnose.Report.wanted()` under-reports for the same reason.
- `_pull_out` does not reset `_refusing`. A stretch of "other lane not clear" before a pass and another after it are merged into one duration, and the time spent passing is counted in it.
- The `refused` docstring says "the mark carries where it started wanting". `note()` stamps `at=` with the current station, which is where it stopped.
- The uncommitted `REASON_HOLDS` gate discards a short-held reason's seconds entirely. A driver alternating between two reasons on every step, the case the new docstring describes, writes nothing for the whole stretch.

Confidence: Confirmed.

Fix: add `Autopilot.flush(session)`, called from `_mark_the_end` and from `_pull_out`, that writes any open stretch. Record the start station when a stretch begins. Merge flip-flopping reasons into one "refused" stretch rather than discarding it.

#### GAME-G6 (Minor) - `drive_it(journal=...)` returns a report with no marks

Where: `glisteel/glisteel/diagnose.py:171-192`

Problem: when `journal` is given, `session.telemetry = journal` and `keeping` receives nothing, so `Report.marks` is empty. `kinds()`, `wanted()` and `ended_at()` are then all empty, although the docstring says the journal is kept "as well as the summary".

Confidence: Confirmed.

Fix: a tee recorder that forwards each mark to both destinations.

#### GAME-G7 (Minor) - `diagnose` writes `Traffic._rng`

Where: `glisteel/glisteel/diagnose.py:169-170`

Problem: a caller outside the class sets a private attribute, and `seed` is set separately beside it.

Confidence: Confirmed.

Fix: add `Traffic.reseed(seed)`.

#### GAME-G8 (Minor) - Hitting a parapet, portal or tree makes no sound

Where: `glisteel/glisteel/session.py:729-763` (`_watch_for_a_bump`, `_note_a_bump`) against `session.py:857-873`

Problem: `self.sound.hit(closing)` is called only from `_watch_for_a_crash`, which handles traffic contacts. Blows against the world are journalled but silent. The README table says "Impacts: every contact".

Confidence: Confirmed.

Fix: call `self.sound.hit(closing)` in `_watch_for_a_bump` as well, rate-limited by the same hold-off.

#### GAME-G9 (Minor) - "Asking to go" recovery moves a player who is pushing against something on purpose

Where: `glisteel/glisteel/session.py:922-960`

Problem: with the throttle held and the brake off at under 1 m/s for 3 s, the car is teleported with `return_to_track()`. A player nosing into a stopped traffic car or queue, or holding the throttle against a wall to push off, is moved without asking.

Confidence: Likely (design).

Fix: require the car also to be in contact with something static or off-line, or not to have anything within `following_gap` ahead. Or offer recovery through the HUD rather than doing it automatically for a human driver.

#### GAME-G10 (Minor) - A remembered preference overrides an explicit `--control` that names the default

Where: `glisteel/glisteel/game.py:181-185`, `glisteel/glisteel/options.py`

Problem: `if self.preferences.control and self.config.control == schemes.DEFAULT` cannot distinguish "not given" from `--control wheel`. The code comment says the command line outranks the remembered choice.

Confidence: Confirmed.

Fix: make the `Options.control` default None and resolve it after preferences are read.

#### GAME-G11 (Minor) - `Preferences.save()` can raise inside a UI callback

Where: `glisteel/glisteel/game.py:487-499` (`_on_driving`), `glisteel/glisteel/preferences.py:65-93`

Problem: an unwritable home directory raises `OSError` out of a button handler.

Confidence: Likely.

Fix: catch the error, log it, and keep the in-memory choice.

#### GAME-G12 (Minor) - `content.py` shadows its own `store` function with a parameter and reaches round it with `globals()['store']()`

Where: `glisteel/glisteel/content.py:78-151` (five functions)

Confidence: Confirmed.

Fix: rename the parameter (for example `into`) or the function (`default_store`).

#### GAME-G13 (Minor) - Orphaned comment line after removing the duplicate `PASSED_BY`

Where: `glisteel/glisteel/driver.py:1184`

Problem: "#: How far behind a stand-in wants what it pulled out for before it comes back" now runs straight into the `CROSSING_MARGIN` comment. The `PASSED_BY` comment at `driver.py:88-95` narrates the duplicate-binding bug ("One constant, because there were two ...").

Confidence: Confirmed.

Fix: delete the orphan line and drop the history from the `PASSED_BY` comment.

#### GAME-G14 (Minor) - `traffic.PASSING_SECONDS` duplicates `driver.PASS_SECONDS`, and a test keeps them equal

Where: `glisteel/glisteel/traffic.py:185-192`

Confidence: Confirmed.

Fix: import one from the other, or move both into a shared constants module. A test that asserts two copies agree is a sign there should be one.

#### GAME-G15 (Minor, partly uncommitted) - Two widths for the same car

Where: `glisteel/glisteel/traffic.py` `_pulled_off` (uses `IN_THE_WAY / 2`) against uncommitted `_room_beside` (uses `self.kind.width / 2`)

Problem: the two clamps disagree for any kind whose width is not `IN_THE_WAY`.

Confidence: Confirmed.

Fix: use `self.kind.width` in both.

#### GAME-G16 (Minor, performance headroom) - Nearest-point queries are full-line scans at the physics rate

Where: `glisteel/glisteel/world.py:662-699` (`nearest`, `_nearest`, `station_of`), callers in `driver.py:329-340, 355-372, 440-445, 540-545`

Problem: `_nearest` does three O(N) array passes over the whole centreline (about 2k to 3k samples for a 7 km lap), and the memo holds one entry. `Autopilot.controls` computes `road_speed(index, speed)` twice. `passing_lane`, `held_back` (through `target_speed`), `station()` and `update()` each call `nearest` again; the one-entry memo absorbs repeats only while nothing else queries in between. `station_of` has no memo and is always a full scan. At 120 Hz with more AI cars, or a longer road in a user's game, this is the scaling cost.

Confidence: Likely (by reading, not profiled).

Fix: a windowed search around the previous index per querying car (keep a hint per caller), with a full scan only when a car teleports. Compute `road_speed` once in `controls`.

#### GAME-G17 (Minor) - Two implementations of the "refusal stretch" logic

Where: `glisteel/glisteel/driver.py:641-671` (`Autopilot.refused`, `_refusing: str = ''`) and `driver.py:1312, 1500-1520` (`StandIn`, `_refusing: str | None`)

Confidence: Confirmed.

Fix: one small `Stretch` recorder object that both classes use.

#### GAME-G18 (Major, engine placement) - Content download UI and glue live in the game

Where: `glisteel/glisteel/menu.py:246-360`, `glisteel/glisteel/game.py:384-437`, `glisteel/glisteel/content.py`, and twig-bb's `menu.download_screen` / `viewer._startDownload`

Problem: both games wrote a consent and progress download screen over the engine's `FetchJob`, with the same rules: size of the whole set, terms, bar plus text, failed against stopped. See GAME-X2. By the workspace rule this is an engine capability placed in the demos.

Confidence: Confirmed.

Fix: `OpenGLContext.ui.contentscreen` (or similar), taking the registry and store and returning a panel. Both games then call it.

#### GAME-G19 (Minor, engine placement) - Vehicle sound model

Where: `glisteel/glisteel/sound.py`

Problem: `CarSound` and `Soundtrack` synthesize motor, tyre and wind sound from `omi_physics` `Wheel.slip` and speed. That is renderer-agnostic and any driving game built on the engine would want it.

Confidence: Likely.

Fix: move it into `omi_audio` (the synthesis) or `OpenGLContext.audio` (the scene nodes), with glisteel supplying its constants.

#### GAME-G20 (Minor, engine placement) - Runtime road-course queries

Where: `glisteel/glisteel/world.py` `Course` (`nearest`, `station_of`, `lane_point`, `width_at`, the uncommitted `carried` and `standing_room`)

Problem: `OpenGLContext.scenegraph.road` builds road geometry but offers nothing for querying a road at runtime, and every game on a road needs "where am I along it".

Confidence: Likely.

Fix: an engine `RoadCourse` query object alongside `road.py`, which would also be the natural home for GAME-G16's windowed search.

#### GAME-G21 (Minor, engine placement) - An in-memory telemetry recorder and an atomic per-user JSON document

Where: `glisteel/glisteel/diagnose.py:46-65` (`Marks`), `glisteel/glisteel/preferences.py:65-93`

Problem: `OpenGLContext.telemetry` has `NotRecording` but no in-memory keeper. `move/bindingstore.py` already does atomic per-user JSON. glisteel carries its own copies of both.

Confidence: Confirmed.

Fix: add `telemetry.Keeping` (a list recorder) and a small `userpaths.write_json_atomically` or settings-document helper.

#### GAME-G22 (Major, writing rules) - Docstrings and comments narrate history and journal anecdotes

Where (examples):
- `driver.py:88-95` (duplicate-constant story)
- `driver.py:147-163` (`ease`: "on the shipped Beacon road that put the car at -3.8 m ... every one of five runs")
- `driver.py:214-227` ("Read off the Ashdown journal")
- `driver.py:411-436` ("the driver could not see one: it only ever considered ...")
- `driver.py:449-462`, with bold "**Being on the wrong side of a road is worse ...** and that is a measured comparison rather than an opinion"
- `driver.py:552-569` and uncommitted `_pass_room` ("Measured on the 3 km circuit before this")
- uncommitted `refused` ("The recorded Tidewater lap has 164 of them")
- `session.py:275-290` (`ended`), `session.py:925-945` ("the one this used to miss")
- uncommitted `session._note_a_touch` ("until it was written down nothing anywhere said ...")
- `traffic.py:458-480` ("What it must not do is what it did ... until one does")
- `menu.py:196-205` (`driving_screen`: "only one of them has ever been reachable ... reads as missing because it *is* missing")
- `game.py:475-481` ("which is to say they could not be reached")
- `sound.py:70-83` ("Scaled to the whole range instead, as this first was"), `sound.py:12` ("**Which is why the game has sound and no content pack.**")
- `camera.py:37-50,84-91` ("the old resting place")
- `world.py:1024-1028` ("The 1695 m circuit was given sixteen ...")

Problem: CLAUDE.md requires docstrings to describe what is, not how it came to be. Keep the reason in the present tense and move measurements and anecdotes to `plans/DRIVING-AND-PLACE.md`. Many of these also use the "insisting" register (bold claims, "which is the point", "the whole of").

Confidence: Confirmed.

Fix: run `/ai-isms --fix` over glisteel. Move the journal evidence into plans.

#### GAME-G23 (Minor, documentation) - README gaps and mismatches

Where: `glisteel/README.md`

Problem:
- `glisteel-diagnose` (a new console script in `pyproject.toml`), `--telemetry` and the preferences file location are not documented.
- "Impacts | every contact" is wrong (GAME-G8).
- "a first run fetches something before it shows a menu" is wrong (GAME-G3).
- The new sections are bold-leader paragraphs throughout ("**Meet one head-on ...**", "**Somebody in the mirror ...**", "**And it does not always work, which is the point.**").

Confidence: Confirmed.

Fix: add a "Recording and diagnosing a run" section. Correct the two claims. Convert the bold leads into plain headings or prose.

#### GAME-G24 (Minor) - Every `release-assets.py` run rewrites the tracked, shipped registry

Where: `glisteel/release-assets.py:266-269`

Problem: `CATALOG` (`glisteel/packs.json`, shipped in the wheel) is rewritten on every run, including `--depth 2` drafts and `--install` runs made only to test locally. Its digests then describe archives nobody published. A developer who commits after a draft run ships a registry whose downloads fail the digest check. The same is true of forest (whole file) and twig-bb (one entry).

Confidence: Confirmed.

Fix: write the shipped registry only with `--push` (or an explicit `--write-registry`). Local installs should use a registry written under `--into`.

#### GAME-G25 (Nit) - A Markdown relative link in a registry copyright string

Where: `glisteel/glisteel/packs.json:10`

Problem: the copyright for `glisteel/cars` contains ``[`tools/cars.py`](../../../tools/cars.py)``, taken from `CREDITS.md` by `_credits()`. That string is shown in-game and is meaningless there.

Confidence: Confirmed.

#### GAME-G26 (Nit) - Three blank lines after `passable_count`

Where: `glisteel/glisteel/traffic.py:212-214`

#### GAME-G27 (Minor) - `Session.restart()` leaves the journal hold-offs and driver state from the last race

Where: `glisteel/glisteel/session.py:614-630`

Problem: `_bumped`, `_sampled`, the uncommitted `_touched`, and the driver's `passing`, `_refusing` and `_crawled_for` are not reset, so a restarted race inherits them.

Confidence: Likely.

#### GAME-G28 (Minor, Possible) - Bore mouth on a closed circuit whose tunnel spans the start station

Where: `glisteel/glisteel/world.py:1086-1100` (`_bores`), `world.py:152-160` (`Structure.holds`)

Problem: `road.centreline[one.holds(road.stations)]` is a boolean mask that does not wrap. A structure crossing station 0 would give two disjoint runs concatenated out of order, and `bore_opening` would build along a jump.

Confidence: Possible. Whether structures are ever stored across the seam was not checked.

#### GAME-G29 (Nit) - Inconsistent use of the `CourseLike` protocol

Where: `glisteel/glisteel/driver.py:431` (`getattr(course, 'width_at', ...)`), `session.py:795-798` (`hasattr(...)`), `driver.py:662` and `race.py:245` (called directly)

Problem: `width_at` is now in the protocol, so the fallbacks are dead code.

#### glisteel documentation coverage

The README covers traffic evasion, sound, journal marks, content packs, `release-assets.py` and Menu → Driving. It lacks `glisteel-diagnose`, `--telemetry` and preferences (GAME-G23). `plans/DRIVING-AND-PLACE.md`, `TRACK-PACKS.md` and `CONTROL-SCHEMES.md` are new and substantive.

#### glisteel: checked and sound

- `Voice.towards` rate limiting.
- The motor-rate range, which stays under Nyquist with 7 partials.
- `@cache` on the clips.
- `TrafficCar.alarm` and `evade` state transitions, including clearing `_alarmed` when cruising resumes.
- `_coming` teleport rejection.
- `_arriving` geometry (in front, closing, own width).
- `RaceTiming._down_the_road` for open roads.
- `Run.allow` zeroing the throttle during the countdown, so GAME-G9 does not fire on the grid.
- `Reflections` zoned short-circuit.
- `tracks.library` merging downloaded tracks.
- `Options` validation for `traffic=None`.
- `_unpaced()` sharing the swap-throttle fix between `--record` and `--capture`.

---

### glisteel-editor

Assessment: the recipe system and the four-view layout on the engine's `ViewSet` and `ViewChrome` are a sound engine-first change. The editor now says which views it has and the engine arranges them. Few defects. The documentation lags on the new bake options.

#### GAME-E1 (Minor) - "Strict" recipe validation truncates floats given for integer settings

Where: `glisteel-editor/glisteel_editor/recipe.py:68-86` (`Setting.read`)

Problem: `int(3.7)` is 3, so `depth = 3.7` or `seed = 23.5` in a TOML recipe is accepted and truncated. The module promises that "a key no setting is called is refused". This is the same class of silent misbake one level down.

Confidence: Confirmed.

Fix: for `kind is int`, refuse a non-integral float (`isinstance(value, float) and not value.is_integer()`).

#### GAME-E2 (Minor, documentation) - README says there is no splitter; the views now have splitters

Where: `glisteel-editor/README.md:414-415`

Problem: "there is no splitter to drag yet", while `app.py` pushes `ViewChrome` with "the splitters between them". The limitations list is also a bold-leader list, and new items were added to it in this range.

Confidence: Likely.

#### GAME-E3 (Minor, documentation) - `--no-probes`, `--no-places` and baked zone probes are not in the README

Where: `glisteel-editor/README.md`, `glisteel_editor/bake.py:130-133`, `recipe.py:124-127`

Problem: the bake now needs a GPU unless `--no-probes` is given. That is also a requirement for `glisteel/release-assets.py`, which passes no such flag.

Confidence: Confirmed.

#### GAME-E4 (Minor) - `WorldManifest.baked = date.today()` makes release archives date-dependent

Where: `glisteel-editor/glisteel_editor/bake.py:222`, used by `glisteel/release-assets.py`

Problem: `release-assets.py` states that "the archives' bytes [are] a function of the content and of nothing else", and a rebuild from a tag is meant to reproduce the digest. `world.json` carries the bake date, so a rebuild on another day gives a different digest.

Confidence: Confirmed.

Fix: take the date from `SOURCE_DATE_EPOCH` when it is set, or leave it out of the packed manifest.

#### GAME-E5 (Nit) - `WHEEL_BUTTONS` redefined locally although the engine exports it

Where: `glisteel-editor/glisteel_editor/controls.py:38`

Problem: `OpenGLContext.events.mouseevents.WHEEL_BUTTONS` already exists.

#### GAME-E6 (Minor, engine placement) - `WORLD_SETTINGS` restates `ProceduralWorld`'s parameters

Where: `glisteel-editor/glisteel_editor/recipe.py:89-128`

Problem: the list of about 18 world parameters, with their types and help text, is kept in the game editor, apart from `OpenGLContext_editor.world.procedural.ProceduralWorld`. A parameter added there is invisible to recipes until someone edits this file.

Confidence: Likely.

Fix: have `ProceduralWorld` declare its settings (for example a `SETTINGS` table) in openglcontext-editor, and have `recipe.py` read it.

#### glisteel-editor documentation coverage

Recipes, `--art-pack` and the four views are documented. Probes, places and the splitter status are not (GAME-E2, GAME-E3).

#### glisteel-editor: checked and sound

- The wheel direction change: the old local constants `WHEEL_UP, WHEEL_DOWN = 4, 3` were the reverse of the engine's `3, 4`. Moving to the engine's names corrects the direction, and the tests pin it.
- `split_art` / `_same_tree` refuses differing art.
- `describe()` reads `closed` and `seed` from the world.
- The uncommitted `scene.py` `waveStyle` change matches the engine field (`pbrmesh.py:227`).

---

### openglcontext-forest

Assessment: the move of ground cover into the engine's `GroundCover` is a good example of the "thin demo" rule: about 180 lines of clump LOD management left the demo. The content-pack move, however, breaks the published package on a first run.

#### GAME-F1 (Critical) - A first run from the wheel cannot find its art

Where: `openglcontext-forest/src/openglcontext_forest_demo/scene.py:46-53`, `content.py:60-74`, `run.py:77,501-506`, `pyproject.toml` package-data

Problem: the wheel no longer ships `assets/` (package-data is `packs.json` and `CREDITS.txt`). `scene.ASSETS = content.art_directory()` is evaluated when the package is imported: `__init__` exports `build_forest_scene`, and `run.py` imports `scene` at module level. On a first run no pack is installed, so `ASSETS` resolves to `IN_WHEEL`, which does not exist in an installed wheel. `main()` then calls `fetch_art()`, which downloads and installs the pack, but `HEIGHTMAP`, `CONTROL`, `COVER` and `A()` still point at the missing wheel directory. The first run of `oglc-forest` from PyPI fails, and only the second run works. Editable checkouts never see this, because `IN_WHEEL` exists there through LFS.

Evidence: `scratchpad/forest_order.py` imports `scene`, installs the pack into a different store, and shows `art_directory()` changing while `scene.HEIGHTMAP` does not.

Confidence: Confirmed.

Fix: resolve paths at use time (a `paths()` function or a lazily evaluated `ASSETS`), or do the fetch before any import of `scene` (a tiny entry module that fetches, then imports `run`). Add a test that imports `scene` with an empty store, installs the pack, and builds the paths. See GAME-X2 for the engine-level fix.

#### GAME-F2 (Minor) - `fetch_art` downloads 66 MB without asking, and a network failure is a traceback

Where: `openglcontext-forest/src/openglcontext_forest_demo/run.py:481-499`

Problem: the docstring says "it asks on the console", but it prints and fetches without any prompt. There is no handling for `FetchFailed`, URL or digest errors, and no `--no-fetch` / offline guidance beyond the `OPENGLCONTEXT_CONTENT` note in the README. glisteel and twig-bb both ask for consent.

Confidence: Confirmed.

Fix: prompt (with `--yes` for scripts), catch fetch errors, and print the `OPENGLCONTEXT_CONTENT` hint.

#### GAME-F3 - See GAME-X1 and GAME-X2 (release-assets and content duplication)

#### GAME-F4 (Nit, uncommitted) - The new `--reinstall` README sentence contradicts itself

Where: `openglcontext-forest/README.md:174` (the same text is in twig-bb and glisteel)

Problem: "It leaves a pack already in the store where it is; `--reinstall` does the same over whatever the store already holds, which is what a rebuilt world needs". "Does the same" reads as leaving the pack in place. The forest has no world. The line is not wrapped.

Fix: "`--install` keeps a pack that is already installed; `--reinstall` replaces it with the one just built."

#### GAME-F5 (Nit) - History in configuration comments

Where: `openglcontext-forest/pyproject.toml` package-data comment ("reached PyPI as 57 Git LFS pointers"), `release-assets.py` `refuse_pointers` docstring ("which is how 57 of them reached PyPI"), and the same four-line comment pasted four times in `.github/workflows/*.yml`

#### GAME-F6 (Minor, engine placement) - The Git LFS pointer check is demo-local

Where: `openglcontext-forest/release-assets.py:58-76`

Fix: fold it into `OpenGLContext.contentpacks.archive.write` (see GAME-X1).

#### openglcontext-forest documentation coverage

The README covers ground cover, the content pack, releasing and `OPENGLCONTEXT_CONTENT`.

- GAME-d1 - It does not say that a first run downloads 66 MB, and it does not describe what happens offline.

#### openglcontext-forest: checked and sound

- `quality.apply_to_scene` routing through `GroundCover.retune`.
- The config and CLI rename to `cover_density` / `grass_card_radius`.
- The `ForestScene.clump_radius` / `grass_far_radius` properties that keep old callers working.
- The CI `lfs: true` additions.
- The `OpenGLContext[glfw,gltf]` extras floor.

---

### twig-bb

Assessment: most of this range deletes twig-bb's own fetcher, catalog and archive code in favour of the engine's, which is the rule applied properly. The migration shim added to keep players' old downloads has a destructive defect.

#### GAME-T1 (Critical) - Legacy-content adoption moves the player's downloads into whatever cache directory a store is opened with

Where: `twig-bb/twig_bb/download.py:67-110` (`store`, `adopt_legacy_content`)

Problem: `adopt_legacy_content(store)` always reads the legacy tree from the real per-user location (`_default_cache()/twig-bb-content`). It moves each pack into `store.directory_for(pack)`, and `store` may be rooted anywhere. `store(cache_dir)` is reached from `pack_directory`, `pack_root`, `fetch_pack`, `FetchJob` and `assets_directory(cache_dir)`, with `cache_dir` coming from `--cache-dir` or from test fixtures. For example, `tests/test_download.py:159,171` call `resolve_target(..., cache_dir=str(tmp_path / 'cache'))`, and only some tests monkeypatch `_default_cache`. The first such call per root moves a player's (or developer's) real downloaded packs, hundreds of MB of textures, into that directory. A pytest `tmp_path` is deleted after three runs, so the packs are lost. On this machine `~/.config/OpenGLContext/twig-bb-content/` exists and is empty.

Evidence: `scratchpad/adopt.py` points `_default_cache` at a scratch "home" holding a legacy pack, calls `download.pack_directory(pack, cache_dir=<another dir>)`, and shows the pack moved into `<another dir>/packs/twig-bb/...` and gone from the legacy tree.

Confidence: Confirmed.

Fix: adopt only when the store is the default per-user store (`cache_dir is None`), or when the legacy directory is under the same root being opened. Copy rather than move across filesystems, or at least never into a caller-supplied root. Add a test that opens a store with an explicit `cache_dir` while a legacy tree exists and asserts the legacy tree is untouched.

#### GAME-T2 (Minor) - Adoption runs as an import side effect

Where: `twig-bb/twig_bb/art.py:56` (`ASSETS = assets_directory()`), `combatsound.py:80`

Problem: importing `twig_bb.art` calls `download.store()`, which on the first call moves directories (possibly a slow cross-filesystem `shutil.move` of hundreds of MB) during import.

Confidence: Confirmed.

Fix: resolve lazily and run adoption from the application's start-up path.

#### GAME-T3 (Minor) - The base pack is documented as fetched before the first match; nothing fetches it, and the asset root is bound at import

Where: `twig-bb/README.md` ("a base pack fetched before the first match"), `twig-bb/release-assets.py:7`, `twig_bb/art.py:56`, `combatsound.py:80`

Problem: this is latent while the wheel still ships `assets/**`. It is the forest defect (GAME-F1) waiting for the art to leave the wheel.

Confidence: Confirmed. See GAME-X2.

#### GAME-T4 (Nit) - `release-assets.py install()` does not guard a missing entry

Where: `twig-bb/release-assets.py:112-113`

Problem: `catalog.pack_for_key(KEY, ...)` returning None raises `AttributeError` rather than a message.

#### GAME-T5 (Minor, Possible) - A level target uses the pack's short name, which resolves only within this game's namespace

Where: `twig-bb/twig_bb/match.py:241-246`

Problem: a pack from an added registry under another namespace would have `other-ns/maps` shortened to `maps`. `pack_for_key('maps')` then resolves to `twig-bb/maps`, which is the wrong pack or None.

Confidence: Possible (depends on whether added registries are used for maps).

Fix: keep the full key and quote or escape it on the command line, or shorten only for `twig-bb/`.

#### GAME-T6 (Nit) - `CONTENT_SUBDIR` and `LEGACY_CONTENT` are both `'twig-bb-content'`

Where: `twig-bb/twig_bb/download.py:54,64`

#### GAME-T7 (Nit) - History in docstrings

Where: "resolved once at import the way it always was" (`art.py:54`), "callers here have always asked this module" (`download.py:27`), "a caller here passes what it has always passed" (`fetcher.py:39`)

#### twig-bb documentation coverage

The README covers the new store layout, `OPENGLCONTEXT_CONTENT`, adoption and `release-assets.py`. The uncommitted `--reinstall` sentence has the GAME-F4 wording.

#### twig-bb: checked and sound

- `jumppads.PushSystem` stand-in moved to a kinematic body placed with `place_body`, backed by the omi_physics floor bump.
- `companions` → `needs` renamed consistently in menu, viewer and conftest.
- `AssetPack = ContentPack` alias.
- `fetch_limit` and `UnsafeArchive` re-exported.
- `FetchJob` subclass passes the store.

---

### marble-demo

Assessment: moving from reading `world.contacts` once a frame to per-step contact listeners fixes a real problem: a lethal blow in an early step of a slow frame was missed, and the new test pins that. The accumulation it introduced leaks across respawns, and the world's event log is never drained.

#### GAME-M1 (Major) - Touches recorded while the marble is lost are read on the first frame after respawn

Where: `marble-demo/src/openglcontext_marble_demo/controller.py:289-292,339-366,525-547`

Problem: `_touch` records every step's contacts into `_touched` continuously. `_touches()` (which clears them) is called only while `state == ACTIVE`. While the marble is DESTROYED or FALLEN it is still in the world, and blows land on it: a hazard still swinging, a crusher still pressing, a bounce off the wall that struck it. `_respawn` clears `_squeezed_for` and the air state but not `_touched`. The first ACTIVE update after respawn reads those stale touches. A stale approach of `lethal_impact_speed` or more destroys the freshly respawned marble at its checkpoint immediately, costing the player a second `LOSS_PENALTY`.

Evidence: `scratchpad/marble_stale.py` rolls the marble into a wall at 30 m/s (STRUCK), hits the wall again during the destroy delay, and waits for the respawn at a clear checkpoint. The first frame gives `destroyed`, with `loss_count` of 2 and stale touches `[(wall, 30.0), ...]`. With `ctrl._touched.clear()` before respawn, the same run stays `active`.

Confidence: Confirmed.

Fix: clear `_touched` (and `_last_touches`, setting `_read_at = world.step_count`) in `destroy()`, `_begin_fall()` and `_respawn()`, or ignore events in `_touch` while `state != ACTIVE`. Add the reproduction as a test in `tests/test_destruction.py`.

#### GAME-M2 (Major) - `world.contact_log` fills to 65 536 events and is never drained

Where: `marble-demo/src/openglcontext_marble_demo/controller.py:327-337` and `mechanisms/lever.py:168-175`, which switch reporting on. There is no `contact_log.drain()` anywhere in marble-demo.

Problem: with reporting `'flagged'` and `report_persist = True`, every step logs an event for each of the marble's contacts as well as delivering it to the listeners. Nothing drains the log. It grows to its cap and stays there, allocating on every step (`list(events)` in `ContactLog.extend`).

Evidence: `scratchpad/marble_log.py`, with the marble resting on the floor for 20 000 steps, gives a log of 19 991 events, about 19.4 MB traced (about 1 KB per event). At the cap that is about 65 MB held for the life of a board. It fills faster when rolling against walls.

Confidence: Confirmed.

Fix: drain the log once per frame in `MarbleGame.advance`, or give omi_physics a way to deliver to listeners without logging, for example `contact_log=None` or `log_events=False`. The second is the engine-side fix, since any listener-only consumer pays this cost.

#### GAME-M3 (Minor) - Contact listeners change world-wide settings and are never removed; the lever answers any body

Where: `controller.py:327-337` (sets `world.report_persist = True` for every consumer), `mechanisms/lever.py:168-195`

Problem: listeners are added and never removed. Harmless while the world lives exactly as long as the game, but the controller makes a world-global change on behalf of one body. The lever now fires on any body that strikes the paddle above `hardness`. It used to fire only on the marble (`impact_on(marble, ..., among=(lever,))`), so a dynamic prop or debris can now throw a lever.

Confidence: Likely.

Fix: filter on the marble's index in `struck` (as the old code did), and scope persist reporting per body if omi_physics can.

#### marble-demo documentation coverage

The docstrings in `crusher.py`, `lever.py` and the tests were updated with the change. There is no user-facing documentation change, and none is needed.

#### marble-demo: checked and sound

- `_touches` step-count memo (no step since the last read gives the same touches).
- Normal flipped to the marble's side.
- The impulse normalised by mass.
- Hardest approach and impulse kept across the steps of a frame.
- The lever laid over inside the step so the marble carries on.

### marble-editor

The only change is the `OpenGLContext>=3.0.0a5` floor, which is consistent with the other projects. No findings.

---

### openglcontext-qt

Assessment: small and correct. `setPointerShape` maps the engine's `CURSORS` names to Qt shapes, refuses unknown names, and does nothing while the pointer is grabbed. The tests pin the table against both vocabularies.

#### GAME-Q1 (Minor) - The dependency comment names the wrong release

Where: `openglcontext-qt/pyproject.toml:37-42`

Problem: the comment says "3.0.0a4 rather than 2.3.0 ... none of which is in 3.0.0a2", while the floor is `>=3.0.0a5` (the contentpacks release).

Confidence: Confirmed.

#### GAME-Q2 (Minor, Possible) - Shape after pointer capture is released

Where: `openglcontext-qt/OpenGLContext_qt/qtcontext.py:621-632` together with the engine's `ui/overlay.py:602-613`

Problem: capture sets `BlankCursor`, and release calls `unsetCursor()`. The overlay caches `_cursorShown`, so if the widget under the pointer wanted `hand` before capture, `showCursor()` returns early after release and the arrow stays until the wanted shape changes. The root is the engine's cache not being invalidated when capture changes. It applies to every backend.

Confidence: Possible.

Fix: invalidate `_cursorShown` in the engine when `setPointerCapture` or `suspendPointerCapture` changes state.

#### GAME-Q3 (Nit)

Where: `tests/test_pointer_shape.py:1-6`, `qtcontext.py:576`

Problem: the test module docstring has "a widget class that already has that name is exactly why the engine's is `setPointerShape`" (insisting register). `CURSOR_SHAPES` is an untyped class attribute; `ClassVar[dict[str, str]]` would be clearer.

#### openglcontext-qt documentation coverage

This is a backend implementation of an engine API that is documented in the engine (`Context.setPointerShape`). No README change is needed.

---

### Workspace root: tools, verify-everything, packaging

Assessment: the preflight additions (serial passes, `checks` through tox, Windows venv layout, a half-built check venv cleared) and multi-file version bumps are careful and tested. `verify-everything.py` has fallen behind the workspace.

#### GAME-W1 (Major) - `verify-everything.py` does not run `opengl_decimate`

Where: `/workspaces/OpenGL-dev/verify-everything.py:66-86`

Problem: `opengl_decimate` joined the workspace (`d5f77e2`: `pyproject.toml` sources and dependencies, `tools/preflight.toml`), but the hand-kept `PROJECTS` roster was not updated. CLAUDE.md says this script "runs every project's suite". Unlike `preflight.load_projects`, which fails when its table does not cover `[tool.uv.sources]`, `verify-everything.py` has no coverage check, so a missing suite goes unnoticed.

Confidence: Confirmed.

Fix: add `('opengl_decimate', 'triangle-mesh decimation')` after `opengl_extrusions`. Add a check (a test in `tools/tests`) that `PROJECTS` covers `workspace_directories()`, minus explicit exclusions such as the accelerators.

#### GAME-W2 (Minor) - The `checks` gate hard-codes the POSIX venv layout

Where: `/workspaces/OpenGL-dev/tools/preflight.py:307-310`

Problem: `os.path.join(dev_venv, 'bin', 'tox')`, in the same change series that introduced `venv_tool()` to fix exactly this for ruff, mypy, python and uv.

Confidence: Confirmed.

Fix: `venv_tool(dev_venv, 'tox')`.

#### GAME-W3 (Minor, uncommitted) - A multi-file version bump is not atomic

Where: `/workspaces/OpenGL-dev/tools/release.py` `write_version`

Problem: files are validated and rewritten one at a time. If the second file has no `__version__`, the first has already been rewritten and the tree is left half-bumped. This is the disagreement `read_version` then refuses.

Confidence: Confirmed.

Fix: compute every replacement first, raise if any fails, then write them all.

#### GAME-W4 (Minor) - `declared_path` strips leading dots from directory names

Where: `/workspaces/OpenGL-dev/tools/preflight.py` `declared_path`

Problem: `.lstrip('./')` removes every leading `.` and `/` character, not the `./` prefix. `.claude/skills` would become `claude/skills`, and `../x` would become `x`. It is latent today, because every declared directory is a plain name or `.`.

Confidence: Confirmed.

Fix: `removeprefix('./')` in a loop, or `os.path.relpath`.

#### GAME-W5 (Minor) - `tools/issues.py` robustness

Where: `/workspaces/OpenGL-dev/tools/issues.py:79-96,116-134,301-320,393-410`

Problem:
- `_request` catches only `HTTPError`, so being offline (`URLError`) is an uncaught traceback. That includes `status`, which calls `rate_limit()` even to report the cache.
- When the rate-limit reserve is reached mid-pagination, every page already collected is discarded and nothing is saved. A first fetch too big for one hour's budget can never complete.
- The module docstring says the whole tracker is pulled down once, but a first fetch requests only open issues.
- `Cache.save` is not atomic.

Confidence: Confirmed.

#### GAME-W6 (Nit) - History in tool docstrings

Where: `tools/preflight.py` `venv_tool` ("Naming `bin` outright resolved every gate to a path that does not exist on Windows ...") and `declared_path` ("which is why it was the two accelerators")

#### GAME-W7 (Nit) - A config entry missing both version keys gives a bare `KeyError`

Where: `tools/release.py` `_version_files`

Problem: an entry with neither `version_file` nor `version_files` raises `KeyError` rather than a `ReleaseError` naming the project.

#### GAME-W8 (Nit) - Missing blank lines before a section comment

Where: `tools/doc_images.py:278-280`

Problem: after the gallery-writer removal, `return 'unknown'` runs straight into the `# ----` section comment. ruff's E30x rules are not selected at the root.

#### Workspace root: checked and sound

- `declares_serial` fails closed (no marker unless it is declared).
- Serial two-pass ordering matches `verify-everything.py`.
- `build_check_venv` clears a partial venv.
- The `EXPECTED` list keeps `checks` out of the gaps report.
- `release.toml` `version_files` for pyopengl and accelerate, with tests.
- `PyOpenGL-glut-binaries[dev]` is now installed on every platform, with matching `requirements-dev.txt` and CLAUDE.md text.
- `.gitignore` ignores `openglcontext-docs-preview/` and `tools/issue-cache/`.
- `doc_images._require` skipping entries whose assets are missing.

#### Workspace root documentation coverage

CLAUDE.md already describes preflight's `serial` and `checks` behaviour and the glut-binaries install.

- GAME-d2 - It has no entry for `tools/issues.py`.

`verify-everything.py`'s docstring is accurate apart from GAME-W1.
