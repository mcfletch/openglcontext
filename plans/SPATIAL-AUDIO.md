# Spatial audio

**Status: ✅ Complete.** The engine is the standalone
[`omi_audio`](https://github.com/mcfletch/omi_audio) package — the
`KHR_audio_emitter` model, every gain curve, the clip cache, the numpy mixer,
the device seam and the engine, with no renderer anywhere in it. OpenGLContext
holds the two integrations: `OpenGLContext/scenegraph/audio.py` (the nodes, for
both the glTF and the VRML97 models) and `OpenGLContext/audio/` (a per-context
engine and the player's settings). Wired into every render pass, read out of
glTF, documented in [docs/audio.html](../docs/audio.html) and demonstrated by
`tests/audio_spatial.py`.

## The decision that shaped everything else

The obvious route was VRML97's `Sound` and `AudioClip` nodes: pyvrml97 has
declared them for twenty years with exactly the fields spatial audio needs, and
nothing has ever played them. Implementing a published specification beats
inventing an API.

**They are not the primary model.** VRML97's ellipsoid falloff is expressible by
no authoring tool anyone uses, and there is very little VRML97-authored audio
content left worth playing. The data model is instead glTF's
[`KHR_audio_emitter`](https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/KHR_audio_emitter),
which is the Web Audio `PannerNode` model — a distance curve, a directional
cone, a gain — and which Blender, Godot and Three.js already export. That is the
same decision `OpenGLContext/physics` made with the OMI physics extensions: the
published schema *is* the in-memory model, so import and export are a
near-identity mapping and there is no private format to keep in sync.

VRML97's nodes are implemented anyway, on the same machinery, with their own
ellipsoid curve. It cost one function — `spatial.ellipsoid_gain_at`, which takes
the sound's world location and direction and the listener's position and gives
back a gain, so the node itself holds no geometry.

## Shape

`omi_audio`, which knows nothing about a scenegraph:

| Module | Answers |
|---|---|
| `omi_audio/model.py` | `KHR_audio_emitter` as typed records with the extension's own field names and defaults; `from_gltf`/`to_gltf` round-trip |
| `omi_audio/spatial.py` | Every gain curve — three glTF distance models, the Web Audio cone, VRML97's two ellipsoids, equal-power panning — and the listener's pose |
| `omi_audio/clip.py` | Encoded audio → mono float32 at one rate, from a file or from bytes, decoded once, cached by name |
| `omi_audio/library.py` | What one document's audio references have resolved to — the seam where the *application's* resolver, never the audio library, decides what a `uri` means |
| `omi_audio/synth.py` | Tones, chirps, noise and impacts made out of arithmetic, so demos and tests need no assets and no licences |
| `omi_audio/mixer.py` | A fixed voice pool summed into stereo blocks: allocation-free, lock-free on the audio thread, priority stealing, gain ramping, an underwater low-pass |
| `omi_audio/device.py` | Where blocks go — `miniaudio`, or silence |
| `omi_audio/engine.py` | The one object an application holds |

OpenGLContext's own, and the whole of what makes the two meet:

| Module | Answers |
|---|---|
| `scenegraph/audio.py` | The `AudioEmitter`, `AudioSource` and `Sound` nodes |
| `audio/scene.py` | Attaching an engine to a context and driving one frame |
| `audio/settings.py` | `AudioSettings`, the `ContextDefinition` sub-node a player edits |

## Decisions worth keeping

- **The engine is a package of its own.** numpy is its only hard dependency and
  a scenegraph is not among them, so it is testable and usable without a
  renderer — the same shape `omi_physics` has. What crosses back into
  OpenGLContext is the nodes and the per-context engine, and nothing else.
- **`miniaudio`, and only `miniaudio`.** MIT, and every decoder it bundles is
  MIT or public domain, where the convenient wrappers (`libsndfile`, PyAV,
  `pydub`-via-ffmpeg) are LGPL or worse. One package covers `.wav`, `.mp3`,
  `.ogg` and `.flac`, and it resamples and re-channels *while* decoding.
  **Optional** because it publishes no `manylinux_aarch64` wheel; the reason is
  recorded beside the `omi_audio[playback]` extra in both projects'
  `pyproject.toml` so it is not tidied into `dependencies`.
- **Silence is a backend.** Package absent, device won't open, or the backend
  falling back to its own null output — all three end in one warning and a
  `NullDevice`. `open_device()` cannot raise. Both silent paths are tested,
  including one that forces the import to fail.
- **Mono clips.** A stereo source has already decided where it sits in the
  stereo field, and a sound that has decided cannot be panned to where it
  actually is. Stereo files are mixed down as they decode.
- **The mixer never allocates, blocks, decodes, resolves or logs.** A fixed
  pool, pre-allocated buffers, numpy `out=` everywhere, and a lock taken only by
  the control thread. One test asserts that twenty blocks of a full pool
  allocate nothing measurable.
- **`play()` returns a handle, not a slot.** A stolen voice's old owner would
  otherwise steer somebody else's explosion — silent, intermittent and very hard
  to find. The handle carries a generation and goes inert.
- **A document's `uri` is the loader's business, never the audio library's.** A
  scene file comes from a third party, and interpreting one of its strings means
  deciding what `../../etc/passwd`, `file://`, a UNC path and an `http:` URL are
  allowed to mean. `omi_audio` therefore never resolves, opens or interprets a
  `uri`: `AudioLibrary` calls back into `loaders/gltf/scene.py`, which uses the
  same size-capped, same-origin `Resolver` every texture and buffer goes
  through. That is also what makes audio *inside* the document work — a `.glb`'s
  `bufferView` and a `data:` URI are bytes the loader already holds, and the
  library takes bytes.
- **Two volumes, and they multiply.** `AudioSettings.volume` is the player's;
  `AudioEngine.master_gain` is the application's. Writing one over the other
  every frame makes whichever loses last exactly one frame, and the symptom is a
  volume key that prints a new number and changes nothing.
- **Sound is driven from `FlatPass.beginFrame`, not `Render`.** `Render` is
  overridden per profile; a per-frame duty hooked into it is hooked into one
  profile. `tests/unit/test_audio_pass_wiring.py` holds every concrete pass to
  it by name.
- **Silence costs nothing.** No device is opened and no thread starts until a
  frame is drawn with an audible node in it.

## Tests

The suite is split the way the code is. `omi_audio`'s own
`tests/test_{spatial,model,clip,library,mixer,device,engine,output_level}.py`
cover the curves at known distances and angles, the glTF round-trip, voice
stealing under pressure, the ramp, the muffle's frequency response, both silent
paths, and that a hostile `uri` reaches the application and nothing else.
OpenGLContext keeps `tests/unit/test_audio_{nodes,scene,gltf,pass_wiring,demo_audible}.py`,
which cover what it adds. No hardware anywhere in either.

Two of them exist because of defects found by running the demo on a real
desktop, and both are the kind nothing else would have caught:

- `omi_audio`'s `test_output_level.py` drives the chain **exactly as the device
  driver does** — prime the generator, `send()` a frame count, decode the bytes
  — and asserts a level in dBFS for a source at a stated position. Every other
  test asserts a ratio, and a ratio is the same at any level.
- `test_audio_demo_audible.py` asserts the demo's own scene sits in a comfortable
  *band*: too quiet demonstrates nothing, too loud is startling and reaches the
  limiter. It has been wrong in both directions.

## Codec extensions

`KHR_audio_emitter` guarantees only MP3. `OMI_audio_ogg_vorbis` and
`OMI_audio_opus` each hang off a **source** and name a second entry in the same
`audio` array holding the same sound better encoded, leaving the source's own
`audio` as the fallback — so a document plays everywhere and sounds better where
the codec is there.

`omi_audio.formats` holds both, `AudioLibrary.clip_for()` asks for the best it
can decode and falls back when one will not resolve, and
`emitters_from_document` puts every encoding into `AudioSource.url`, better
first. Vorbis decodes; **Opus does not** — it is read, round-tripped and
reported, and an Opus source plays its MP3 fallback. `formats.decodable()` asks
the backend which formats it reads rather than asserting a list, so a
`miniaudio` that gained Opus would be used with nothing here changing, and an
application with its own decoder sets `library.encodings`.

A fallback is taken only when the better encoding will not **resolve**. One that
is still downloading is waited for: falling through on "not here yet" would play
the worse encoding of every sound whose better one merely had not landed.

Documented in [docs/audio.html](../docs/audio.html#codecs) and
`omi_audio/docs/DATA-MODEL.md`; the roster of every OMI extension and its status
is [OMI-EXTENSIONS.md](OMI-EXTENSIONS.md).

## Not done

- No HRTF, no reverb, no occlusion. The muffle is a whole-mix low-pass, which is
  what a liquid volume needs and not what a wall needs.
- **Opus is not decoded.** `miniaudio` does not read it, and adding it means a
  second decoder plus WebM demuxing. libopus is BSD-3, so it is available if
  something needs it; nothing does yet.
- `alphaGen portal`-style listener-dependent generators have no equivalent here.
- Music streams are decoded whole rather than streamed; clips are small, and
  nothing yet plays anything long enough for it to matter.
