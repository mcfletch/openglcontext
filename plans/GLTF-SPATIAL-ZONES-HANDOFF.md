# Spatial zones: hand-off (2026-09-24)

Where the work in [GLTF-SPATIAL-ZONES.md](GLTF-SPATIAL-ZONES.md) stands, for
picking it up again.

## Done and committed

- omi_audio `fbb7c10`: `omi_audio.reverb` (a comb-filter reverb on the whole
  mix, `Mixer.reverb`, `AudioEngine.reverb`); `synth.surf`, `synth.birdsong`.
- openglcontext (develop): the zone engine.
  - `scenegraph/zones.py` (maths), `scenegraph/zone.py` (`Zone`,
    `ZoneEnvironment`, `ZoneLights`, `ZoneAudio`, `ZoneReverb`,
    `ZoneVisibility`, `ZoneMirrors`, `ZoneGravity`).
  - `loaders/gltf/shapes.py`, `loaders/gltf/zoning.py` (`OGLC_zone` reader,
    `register_scoped`); `fastdecode` keeps 2.1 `shapes`; `GLTFScene.zones`.
  - `passes/zonelayers.py`, `passes/zoneprobes.py`, `passes/zonepass.py`
    (`ZonesMixin` on `FlatPass`), `shaders/_zone_inc.glsl`, `pbr.frag`
    (`envIrradiance`/`envRadiance`, `lightsOff`), `ibl.py` cube-map-array
    probe (`IBLProbe(layers=)`, `convolve`, `grow`), `pbrpass.set_zones`,
    `set_lights_off`, `PBR_ZONE_PROBES`.
  - Audio (`audio/areas.apply_zones`, `AudioEmitter.zoneGain`), physics
    (`physics/zones.py`, gravity volumes in `collision_world_from_scene`),
    visibility (`zoneHiddenAt` in `renderSet`), mirrors
    (`ReflectionPlanner.allowed`).
  - `TilesTerrain` mounts `extras.zones` (`{"document": "zones.gltf"}`).
  - `SceneSpec.shadows`; `zoneCaptureFaces` / `OPENGLCONTEXT_ZONE_CAPTURE_FACES`.
  - Docs: `docs/extensions/OGLC_zone.rst` (+ schema, 2.0/2.1 examples),
    `docs/zones.rst`, `docs/zones-internals.rst`, index, documentation,
    gltf, pbr, audio, physics, environment, testing.
  - Tests: `test_zones.py`, `test_gltf_zones.py`, `test_zone_layers.py`,
    `test_pbr_zones.py`, `test_tilesterrain_zones.py`; helpers
    `_zone_capture.py`, `_zone_cost_harness.py`.
- reference_images: Parthenon baselines re-blessed (shadows on).
- parthenon (root repo): two room zones (captured environment, door light,
  reverb), sky-fill removed, door spots at the doorway centre (outer 1.2,
  inner 0.2, shadows), pool = marble curb + flat water sheet tagged
  `OGLC_hook` water (steepness 0.012, ripple 3 m). Built with
  `uv run --no-project --with 'trimesh[easy]' --with pygltflib --with pillow
  --with numpy python src/parthenon/build_parthenon.py -o parthenon.glb
  --out-gltf parthenon.gltf`.
- openglcontext-editor: `world/places.py` (`road_places`), `bake/zones.py`
  (`ZonesLayer`, `zone_records`, `place_sounds`), `ProceduralWorld.places`
  and `zone_layer()`; `tests/test_world_places.py`.
- glisteel-editor: recipe setting `places` / `--no-places`.
- glisteel: `Reflections(zoned=)`, `world_is_zoned`; session passes it.

## Not yet done

1. Preflight has not been run on openglcontext, openglcontext-editor,
   glisteel, glisteel-editor since these changes (omi_audio passed). Run
   `tools/preflight.py <project>` for each and fix lint/mypy.
2. Full openglcontext unit suite was green except the Parthenon baselines
   (since re-blessed) and two fixed tests; the later performance changes
   (`ZoneTable.classify_many`, `refreshZones`, per-draw probe repacking)
   ran only the zone tests. Re-run the suite.
3. Glisteel performance, in `full` IBL: zoned Tidewater ran ~43 fps against
   61 without zones before `refreshZones`; a re-time was in progress
   (scratch bakes in the session scratchpad: `tidewater/`,
   `tidewater-plain/`). The remaining costs: zone captures (each is six
   whole-world draws; consider a capture far plane or fewer faces a frame
   for large worlds) and moving objects (now batched per draw list). Static
   objects hit the cache (verified: all misses were moving car shapes).
4. Glisteel runs IBL `auto`, which drops to `analytic` under 45 fps; captured
   zone probes only apply in `full`. Decide whether glisteel pins `full` or
   whether zone probes should be readable in `analytic` mode.
5. Visual check of glisteel places in `full` mode (tunnel, forest,
   causeway) — captures at `--drive-seconds 12/22/32/42/52` looked right on
   the causeway and forest; the tunnel was not reached yet.
6. `EXT_lights_image_based` (scene-level and zone `{"light": n}`) is not
   implemented; `ZoneEnvironment.light` exists as an unused field.
7. Plan document: set status to Implemented and record the departures
   (settings nodes named `Zone*` in a `settings` field; per-fragment world
   transform in the fragment shader with 4 layers; captures and cube-array
   probes done in the same pass; `reverb` added as an own property;
   `box_gain` kept unchanged beside `apply_zones`; pool is a raised curb;
   the `autoPlay` wording at line ~280 should read `autoplay`).
8. Rebake glisteel's shipped tracks (`glisteel/release-assets.py`) so they
   carry zones; `docs/glisteel.rst` and `docs/baking.rst` should mention the
   zones layer.
9. glisteel `session.py` and openglcontext `reflectionplanner.py` hold
   another session's uncommitted edits beside mine; only my hunks were
   committed.
