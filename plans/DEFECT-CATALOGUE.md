# Recurring defect classes across the workspace's code reviews

Research input for a plan that prevents each class mechanically (a static
check, a typed wrapper, a configuration gate) or, where that cannot work, by a
written rule and a test convention.

## Sources and method

Nineteen review documents, about 1,150 findings in all:

| Abbrev. | Document | Findings tagged |
|---|---|---|
| Jan | openglcontext/plans/CODE-REVIEW-2026-01.md | 19 |
| PR | openglcontext/plans/PR-REVIEW-PBR-RENDERING-EXPERIMENT-2026-07-04.md | 85 |
| 07-13 | openglcontext/plans/CODE-REVIEW-2026-07-13.md | 50 |
| 07-19 | openglcontext/plans/CODE-REVIEW-2026-07-19.md | 55 |
| STR | openglcontext/plans/STRUCTURE-AND-DOCUMENTATION-REVIEW.md | 23 |
| 07-26 | openglcontext/plans/CODE-REVIEW-2026-07-26.md | 46 |
| 08-03 | openglcontext/plans/CODE-REVIEW-2026-08-03.md | 23 |
| O09-03 | openglcontext/plans/CODE-REVIEW-2026-09-03.md | 15 |
| P09-03 | pyopengl/plans/CODE-REVIEW-2026-09-03.md | 17 |
| P09-05 | pyopengl/plans/CODE-REVIEW-2026-09-05.md | 8 |
| P09-24 | pyopengl/plans/CODE-REVIEW-2026-09-24.md | 21 |
| CD | plans/2026-09-01-pyopengl-c-dispatch-review.md | 59 |
| TY | plans/2026-09-10-typing-and-offscreen-review.md | 25 |
| EXT | opengl_extrusions/plans/2026-08-23-code-review.md | 70 |
| GLI | glisteel/plans/2026-08-19-CODE-REVIEW.md | 78 |
| DEC | opengl_decimate/plans/REVIEW-0.1.0a1.md | 32 |
| OMI | omi_audio/docs/reviews/2026-07-31-code-review.md | 38 |
| 09-25 | openglcontext/plans/CODE-REVIEW-2026-09-25.md (all 496 table rows; 490 classified) | 490 |

Every finding was given one primary class (and at most one secondary) against
a 27-class draft taxonomy, then the draft was split and merged on the evidence
into the 30 classes below. Counts are primary-class counts and are
approximate: a finding that sits on a boundary (a stale cache that is also a
documentation error) was counted once. Where a class below is a split of a
draft class the split was estimated by reading the finding titles, and is
marked "about". The per-finding tagging is in the working files beside this
one (`early.md`, `mid.md`, `sep.md`, `plans.md`, `libs.md`, `r0925a.md`,
`r0925b.md`).

Commits cited without a project are in openglcontext.

Detectability grades, as asked:

- (a) mechanically detectable from the AST or configuration, deterministically;
- (b) detectable by typing discipline (NewType, wrapper types, Protocols,
  Final/ClassVar, mypy strictness);
- (c) partially detectable: a checker finds a useful share, with false
  negatives or an allowlist;
- (d) not statically detectable: needs a rule, a test convention or a process.

Baseline facts that bear on the checkers:

- openglcontext's ruff selection is `E, W, F, B` only, with F401/F403/F405/E402
  ignored. openglcontext-editor, glisteel and openglcontext-forest already
  select `BLE` and `S110`; opengl_decimate, opengl_extrusions and omi_physics
  select `ARG, I, UP, SIM, C4, RUF`; pyopengl and twig-bb select `E, W, F, B`.
- openglcontext already has an AST/ruff ratchet pattern in its suite that the
  plan can extend rather than invent: `tests/unit/test_lint_gates.py` (a list
  of ruff rules the package is clean of, one parametrised test each),
  `tests/unit/test_documentation_references.py` (every module a docstring
  names imports), `tests/unit/test_no_configuration_at_import.py` (no test
  module writes `os.environ` at import), `tests/unit/test_declared_shims.py`
  (TYPE_CHECKING shims match the real class) and
  `tests/unit/test_vertex_semantics.py`. pyopengl has `tests/gates/`.
- In `openglcontext/OpenGLContext` today: 269 `except Exception`, 46
  `type: ignore` of which 37 carry no reason text, 79
  `pragma: no cover ... window` across the engine and games, 47
  `float(... .get(...))` calls, 173 function-local imports in `passes/`.

---

## 1. Unchecked document values

Definition. A value read from an untrusted structured source (glTF JSON and
`extras`, `OGLC_*` extension blocks, a tileset, a registry, a saved settings
file, a CLI argument) is converted with a bare `float()`, `int()`, `bool()`,
`str.lower() == ...`, a positional index or a `dict[key]`, without a default,
a bound, a finiteness check, or a size cap applied before the value is used to
allocate or decode. Shape for a checker: a call to `float`/`int`/`bool` (or a
subscript) whose argument is a subscript or `.get()` on a mapping that came
from `json.load(s)` / a glTF `extras` / `extensions` dict, in a module under
`loaders/` or a `*hooks.py`, outside `DocumentValues`. The second shape is an
allocation or decode (`np.empty(n)`, `base64.b64decode`, `zipfile` read,
Draco decode) sized by such a value with no cap checked first.

Recurrence, about 37: Jan 1, PR 7, 07-13 2, 07-19 3, 07-26 2, EXT 1, GLI 2,
DEC 1, OMI 1, 09-25 17.
- REF-C1 (critical) `scenegraph/reflector.py` `reflector_for` catches
  TypeError/ValueError but not OverflowError (`1e999`) and accepts NaN.
- ZON-M7 / SG-M1 a malformed `OGLC_zone` / hook / `MSFT_lod` value aborts the
  whole glTF load (`loaders/gltf/zoning.py`, `hooks.py`, `lod.py`).
- SG-C1 (critical) `scenegraph/particlehooks.py` lets a file set
  `maxParticles` to 4e9. SG-n3 `octahedralHemi: "false"` read as true.
- SG-m12 / CP-4 / 07-19 #5, G2 size checked after decoding (data URI, archive
  members, Draco).
- 07-26 M8 `move/bindingstore.py` crashes on wrong types; CP-11 registry
  fields coerced with bare `bool()`/`int()`; DEC 11 six option fields
  unvalidated.

Where the fix landed. `OpenGLContext/loaders/documentvalues.py`
(`DocumentValues.number/integer/flag/choice/vector`, and `bounded()` for
values set in code), added in 2b39a0e and adopted across the glTF readers in
69e59f9 ("One malformed hook, zone, MSFT_lod or image-light value costs that
value, not the load"); `HookRunner` isolation of a failing factory (36aa17c);
size-before-decode in 942b27d and faec2f1; registry validation in 35f2158.
opengl_decimate's answer is `__post_init__` validation of every option field.

Detectability: (a) plus (b). A checker can flag `float`/`int`/`bool` over a
`.get()`/subscript in the loader and hook modules outside `documentvalues`;
the allowlist is small. Typing makes it stronger: if the JSON-reading entry
points return `Mapping[str, object]` (a `JSONObject` alias) rather than `Any`,
mypy rejects `float(value)` on an `object` until the code narrows it, and the
narrowing helper is `DocumentValues`. The size-cap-before-decode shape is (c).

---

## 2. Unconfined paths and URLs

Definition. A file name or URL taken from a document, tileset, registry,
archive member, cache slug or redirect is joined (`os.path.join`, `+`) and
opened (`open`, `Image.open`, `np.load`, `urlopen`, `urlretrieve`,
`extractall`) without going through the resolver that enforces containment
(no absolute path, no `..`, realpath under the base, same origin, allowed
scheme and hosts, redirects re-checked). Checker shape: a call to a file- or
network-opening API whose path argument is not a literal and not the return
value of the sanctioned resolver functions, in engine/library code.

Recurrence, about 25: Jan 1, PR 1, 07-13 2, 07-19 1, 08-03 3, GLI 2, OMI 1,
09-25 14.
- 08-03 B1 `loaders/tiles3d/fetch.py` bypassed `Resolver`: SSRF, traversal.
- SG-M7 / ZON-m14 / SG-M8 tileset-named zones and cover files joined without
  containment, remote names opened as local files (`scenegraph/tilesterrain.py`,
  `vegetation/cover.py`).
- SG-C1 particle `texture` opens any local path; ED-m2 editor glTF reader.
- CP-13 `fetch_url` accepts `file://`; CP-10 namespace bypass on
  case-insensitive file systems; CP-27 abspath not realpath; ED-m4 redirect
  host not re-checked.
- 07-13 #12 glTF same-origin check bypassed by a redirect; OMI S1 audio `uri`
  path traversal; GLI S1/S2.
- CP-1 (critical) is the same policy wrong in the other direction: the
  resolver refused GitHub's cross-origin release redirect.

Where the fix landed. `loaders/resolver.py` `Resolver` containment;
`loaders/tiles3d/fetch.py` `beside(base, name)` and `local_copy(uri)`
(1d665f3); per-service redirect allowlist `AllowedHosts.open_url` (d0ebb74,
a9a8616); registry transport and name checks (35f2158). omi_audio moved uri
resolution out of the library into `AudioLibrary`.

Detectability: (a) for the sinks, (b) for the flow. Ruff's `TID251`
banned-api can forbid `urllib.request.urlopen`, `urlretrieve`,
`tarfile.TarFile.extractall`, `zipfile.ZipFile.extractall`, `pickle.load`
everywhere except the resolver and archive modules, deterministically.
`S202` (tarfile unsafe members) and `S310` (urlopen scheme) are ready-made.
A `ContainedPath = NewType('ContainedPath', str)` returned only by
`Resolver`/`fetch.beside`, and taken by the loaders' open helpers, makes an
unconfined join a type error. The `os.path.join(base, <document value>)`
shape in loaders is (c).

---

## 3. Non-atomic or destructive file writes

Definition. A file or directory that a later run reads back (install record,
cache, registry, settings, save game, version file, extracted archive) is
written in place with `open(path, 'w')`, `Path.write_text`, `json.dump` to an
open handle, `extractall` into the destination, or `shutil.rmtree`/`move` of a
live directory, with no stage-and-`os.replace` and no inter-process lock; or a
derived artifact is written beside a read-only source/install. Checker shape:
a write-mode `open`, `write_text`/`write_bytes`, `shutil.move`/`rmtree`/
`copytree` on a non-temporary path outside `atomicfiles`.

Recurrence, about 14: 07-19 1 (#12 clump texture written into the asset dir),
07-26 1, GLI 2, P09-24 1 (secondary), 09-25 10.
- CP-3 / MV-M10 / MV-m21 content-pack and viewer archive extraction cached as
  complete when interrupted (`contentpacks/store.py`, `viewer/source.py`).
- CP-7, CP-12 registry kept or refreshed non-atomically; CP-23 staging dir
  reused; ED-m1 Poly Haven cache.
- GAME-T1 (critical) twig-bb `download.py` moves a player's downloads into
  whatever store root is open, including a pytest `tmp_path`.
- 07-26 M7 `move/bindingstore.py`; GLI C7 project save, S4 `Records.save`;
  GAME-W5 `tools/issues.py`.

Where the fix landed. `OpenGLContext/atomicfiles.py` (`staged_file`,
`write_bytes`, `write_text`, `copy_file`, `staged_directory`,
`replace_directory`, `file_lock`), ed05f72, used by contentpacks, the
resolver, the viewer, the glTF writer, glisteel `records`/`preferences` and
the editor. `tools/atomicwrite.py` for the workspace tools (bba63a9).
Pack install fixes 99b0959, 285c6de, 72b1deb, f3d7771, 998e682.

Detectability: (a). The sinks are a closed set of stdlib calls; flag them in
package code outside `atomicfiles`/`atomicwrite`, with an allowlist for
writes into a directory obtained from `tempfile`. `TID251` can express most of
it. The destructive-move shape (GAME-T1) is (d).

---

## 4. Identity-keyed state

Definition. A cache, registry or per-object table is keyed on something the
runtime reuses: `id(obj)` without holding `obj`, a raw pointer or context
address, an OpenGL name, `__dict__` identity, the "currently current"
context, or a bare entry-point name where the API is part of the identity.
When the original goes away the key is reissued and the table answers the new
object with the old object's state. Checker shape: an `id(...)` call whose
result is used as a subscript, dict key, set member or stored attribute in a
statement that does not also store the object; a module-level dict keyed by a
context handle with no `on_context_lost` registration in the module.

Recurrence, about 21: 07-19 1, PR 1, O09-03 3, P09-03 2, P09-05 1, P09-24 1,
CD 3, TY 1, EXT 1, GLI 1, 09-25 6.
- REF-M7 `passes/reflection.py` `_FITS` keyed on `id(positions)`; ZON-M3
  instanced groups compare `id(matrix)`; ZON-n6 `ZonePack.key` from `id()`;
  MV-m1 capability cache on a raw context address; SG-n14 GL program ids.
- 07-19 S1 shadow depth-map cache on reusable `id()`s; PR 4.5 per-context
  caches keyed on `id()`; EXT F1 contour-normal cache; GLI A6 `id(car)`.
- O09-03 M1/M2/M3 single-slot per-context caches, backends never announcing
  teardown, PyOpenGL's dispatch table never told a context died.
- CD 4.1 use-after-free forgetting a context; CD 5.5 `set_error_checking`
  reaches only the current context's table; CD 5.6 / P09-03 M3 support layer
  keyed by bare name across eight APIs; TY §6-found2 `releaseWindow` retires
  "whichever context is current".

Where the fix landed. The cache rule in `openglcontext/CLAUDE.md` ("Key on
the object, never on `id()` alone", c93ca71); `contextresources.context_key`,
`on_context_lost` / `forget_context_lost`; `Context.bindContextResources` /
`releaseContextResources` calling `OpenGL._dispatch.forget_context`;
`WeakKeyDictionary` or holding the object in the entry (c2bf4ee, 41aa5cb,
e75a0e3); `(api, name)` keys in PyOpenGL (`_key_for`, `swallowed_for`).

Detectability: (a) for `id()`-as-key, which is a pure AST pattern with very
few legitimate uses (logging, `__repr__`). (c) for context-keyed tables: a
checker can require that any module-level dict whose keys come from
`context_key()`/`getCurrentContext()` also registers `on_context_lost`. (b)
partly: a `ContextKey` NewType produced only by `contextresources` makes the
key's provenance visible.

---

## 5. Memo that misses an input, or is not reset

Definition. A memo, generation-stamped cache or remembered answer compares
some but not all of the inputs its computation reads (a field of the node
itself, a setting, a scale, a texture edited in place, a scene swap), or state
that belongs to one run/scene/session/respawn is not cleared when the next
starts. The answer outlives the question. Shape: `if self._x is None or key !=
self._key: ...` where the computation reads attributes not in `key`;
`functools.cache` on methods; a `restart()`/`destroy()`/scene-swap that does
not clear a member set elsewhere.

Recurrence, about 51 (the largest class in 09-25's "Major" findings): Jan 1,
PR 2, 07-13 1, 07-19 4, 07-26 2, EXT 1, GLI 7, 09-25 about 33.
- ZON-M1 runtime zone-setting edits ignored until re-keyed; ZON-M2 a scaled
  object keeps its zones; ZON-M4 any zone moving evicts every image-light
  probe (`scenegraph/zone.py`, `passes/zonepass.py`).
- PASS-M2 batching memo ignores `reflector` and in-place texture edits
  (`passes/instancing.py`); PASS-M3 LOD memo ignores the node's own fields;
  SG-M2 `LOD.boundingVolume` cached for the first level; REF-m8 / PASS-m16
  `mirror_generation` misses `waveStyle`.
- MV-M1 a view's navigation keeps driving a replaced camera; MV-M7 strategy
  fixed at the first frame; CP-2 no install record, URL cache fails forever.
- 07-19 #2/#3 shadow cache stale layer, key committed before render
  succeeds; 07-26 B3 memo with no reset; GLI D21 / GAME-G27
  `Session.restart()` keeps state; GAME-M1 marble touches survive respawn.

Where the fix landed. Generation counters bumped by the scenegraph's field
observers (`passes.reflection.mirror_generation`, `_zoneEpoch`; 12d087e,
41aa5cb, 99dde94, f63b296), `vrml.cache` holders with `depend(node, field)`,
and the written cache rule in `openglcontext/CLAUDE.md` including its test
convention ("A cache's tests edit each input in turn and assert that the
answer changes"). `renderoptions.reset_env_cache` / `pbrpass.reset_renderer_cache`
for process memos. Explicit reset in lifecycle methods (da2d769, 2dcc045).

Detectability: (d), with a (c) fringe. Whether a key covers every input is a
data-flow question over attribute reads a checker cannot settle in this
codebase's dynamic scenegraph. Ruff `B019` (`lru_cache` on methods) and a check
that forbids hand-rolled `self._memo` patterns in `passes/` in favour of one
sanctioned memo type (which takes its depends explicitly) are (c). The
enforceable part is the test convention: a memo class declares its inputs, and
a generic test edits each declared input and asserts the answer changes.

---

## 6. Resources without an owner

Definition. Something that must be released explicitly (a GL texture,
framebuffer, buffer, VAO, query, program; a GLFW cursor; an EGL display; a
thread or worker; a `logging` handler; a dispatcher receiver or
`on_context_lost` callback) is created with no object whose disposal releases
it, or is released from the wrong place (`__del__` on the collector's thread,
the wrong context). Shape: a `glGen*`/`glCreate*`/`glfwCreate*`/
`threading.Thread`/`addHandler`/`dispatcher.connect` in a class that has no
`dispose`/`release`/`disposeResources` and is not a `PassResources` mixin; any
`gl*` call inside `__del__`.

Recurrence, about 18: PR 2, 07-19 3, 07-26 3, O09-03 3, GLI 1, 09-25 5
(+ SG-m15 thread leak).
- PASS-M1 a scene swap leaks the reflection atlas, GPU timers, view UBO, zone
  capture targets, IBL probe array (`passes/renderpass.py` `_dispose`);
  ZON-m4, REF-m9, MV-m14 GLFW cursors, ED-m12.
- 07-19 #4 no teardown in any terrain/vegetation node; I2 HDR skybox leaks
  per environment change; X1 `gltf_uploader.release()` is a no-op.
- PR 3.3 GL calls from `__del__` (`scenegraph/pbrmesh.py`); PR 3.15 shadow
  maps leak on context loss; O09-03 M4 failed EGL construction leaks.
- 07-26 M5 `ui/draw.py` `close()` leaks its program; 07-26 M3
  `ConsoleLogHandler` retains the panel tree; m4 dispatcher watches never
  removed; O09-03 m5 `on_context_lost` has no unregister.

Where the fix landed. `OpenGLContext/passes/disposal.py`
(`PassResources.disposeResources` chained through every pass mixin via
`super()`, and `let_go`), b3b34b3, called by `renderpass.cached_pass` and the
context-loss callback; per-context VAOs deleted with the node or the context
(6f1446d); `PBRMesh.flush_pending_deletes` queue instead of GL in `__del__`;
node `dispose()` (07-19 pass 1); `contextresources.forget_context_lost`.

Detectability: (a) for GL-in-`__del__`; (c) for ownership. A checker can list
every class that calls a GL allocator and require that it either derives from
`PassResources`/a `GLResource` base or defines a release method, with an
allowlist. (b): a small set of owning wrappers (`Texture`, `Framebuffer`,
`Buffer`, `Program` holding a `GLName` NewType and registering with the pass
or the context on construction) makes an unowned name a type error where the
raw `glGen*` return is not accepted.

---

## 7. GL state and frame state not restored

Definition. A stretch of drawing changes global state (enable/disable,
bound framebuffer, texture unit, program, cull face, scissor, depth mask,
clear colour; or an audio engine's global reverb) and does not restore it on
every exit path, or a per-frame hand-off object survives the frame (including
a frame that raised). Shape: a function that calls `glEnable`,
`glBindFramebuffer`, `glScissor`, `glUseProgram`, `glCullFace` and returns or
can raise without a matching restore in a `finally` or a context manager.

Recurrence, about 22: 07-13 1, 07-19 3, PR 3, 07-26 1, P09-03 1, CD 2,
09-25 11.
- MV-m15 an exception inside a view leaves scissoring on; REF-m12 / REF-m13
  the atlas leaves clear colour and bindings dirty and stays bound on unit 31
  while it is the draw target; PASS-m13 `ibl.convolve` does not restore.
- PASS-m1 / PASS-m2 the frame's gather has two hand-off mechanisms and the
  legacy pick path clears one mid-frame; SG-m21 `_render_legacy` changes cull
  and texture env.
- ZON-M8 / ZON-M9 zones overwrite the application's reverb and leave gains.
- 07-19 #1 IBL fallback corrupts GL state on FBO failure; 07-13 §3i
  FBO/scissor leak on exception; 07-26 M4 `ui/draw.py` `end()` claims to
  restore and does not; CD 9-K1/9-K2 `use_debug_output` replaces the
  application's callback and leaves synchronous mode on.

Where the fix landed. `OpenGLContext/passes/framestate.py` `FrameState`, held
by `FlatPass.drawingFrame` and dropped in `finally` (bb53dfa); the pass's CPU
state memo `passes.instancing.set_cull_state` / `mode.setCullState`;
`finishViews` resets scissor in `finally` (a17d7a1); 63ebd9c, 9028bfe,
44a73c5; b779874 for the audio case.

Detectability: (c) as AST, (b) as API. A checker can pair
enable/bind/use calls with restores inside the same function and require a
`try/finally` or `with`, and can forbid raw `glEnable`/`glBindFramebuffer` in
`passes/` outside a state module. The deterministic route is typed: context
managers (`with gl_state.enabled(GL_SCISSOR_TEST)`, `with bound_framebuffer(fbo)`)
as the only sanctioned form in pass code, enforced by `TID251` on the raw
calls in those packages.

---

## 8. Configuration read at the wrong time

Definition. An environment variable, path, backend choice, locale, platform
probe or other process setting is either bound at import time (module scope,
class body, a default argument or field default) so nothing can set it first,
or re-read on every frame/call so it changes under a running program; or a
process-wide setting is overwritten unconditionally. Shape: module- or
class-level statements that read `os.environ`/`os.getenv`/`sys.argv`, call a
path resolver, choose a backend, or perform side effects (moving files);
`os.environ[...] =` at module level; an environment read inside a function
reached per frame, outside `renderoptions`.

Recurrence, about 19: Jan 1, PR 2, 07-19 1, STR 1, 07-26 3, P09-05 1,
P09-24 2, GLI 1, 09-25 6 (and 3 more secondary).
- GAME-F1 (critical) the forest's `scene.ASSETS = content.art_directory()`
  evaluated at import, before `main()` fetches the pack
  (`openglcontext-forest/src/openglcontext_forest_demo/scene.py:46`);
  GAME-X2 three import-bound art resolvers; GAME-T2 twig-bb adoption runs as
  an import side effect.
- BIN-2 `profile_view` sets `PYOPENGL_ERROR_CHECKING` after `OpenGL` is
  imported; BIN-9 audio demo picks a GL backend at import.
- 07-26 B2/B3/M9 one defect under three numbers: `ContextDefinition.profile`
  default evaluated at class definition, a memo with no reset, three
  environment-read lifetimes in one class; m21 module-level gettext.
- P09-05 #3 `_configflags` freezes at whichever import touches it first;
  P09-24 #8 X-display probe at collection time, #17 `LC_ALL` overwritten
  unconditionally; GLI A21 tools execute on import.
- Per-frame reads: ZON-m6 `zoneCaptureFaces`, MV-n11 `requested_strategy`,
  PR 5.2.

Where the fix landed. `renderoptions.env_flag_once` / `env_number_once` /
`reset_env_cache` (the one memo; `tests/unit/conftest.py` resets it around
every test); `contentpacks.Application` / `AssetLibrary` resolving art at each
use (f358383); 725ab76, 0a651ab, afc43fa, f79eef5, bf9facc, e75a0e3;
`tests/unit/test_no_configuration_at_import.py` for test modules.

Detectability: (a). Module-level and class-body statements are syntactically
identifiable; a checker allows literals, imports, `logging.getLogger`,
`TypeVar`, `NamedTuple`, `re.compile`, decorators and definitions, and flags
calls outside an allowlist plus any `os.environ`/`os.getenv`/`sys.argv`
access. Extending the existing `test_no_configuration_at_import.py` from test
modules to the package and to the demos is the direct route. `os.environ`
reads outside `renderoptions` (engine) and each project's single settings
module are also (a).

---

## 9. Shared mutable defaults and aliasing

Definition. A mutable object (list, dict, set, scenegraph node, skin) is held
at class or module level and mutated through instances or callers, or a
function returns or stores a container shared with live state, so one user's
change reaches every other. Shape: a class-body assignment of `[]`, `{}`,
`set()`, `dict()`, a node constructor, without `ClassVar`/`Final` and an
immutable type; `cls.__dict__.setdefault`; a module-level container mutated
inside functions; `to_*`/export functions that return a member container
unchanged.

Recurrence, about 14: 07-13 1, PR 1, 07-26 2, GLI 3, OMI 1, 09-25 6.
- ZON-m7 mutable class-level defaults on the zone mixin patched with
  `__dict__.setdefault`; REF-n4 / PASS-n4 the same on the effects mixin;
  SG-m25 water presets as mutable shared globals; ED-m21 `SHIPPED`/`COVER`
  module-level nodes.
- REF-M1 an object's `mirror` hook mutates cached shared `Shape`s, so every
  node using the mesh becomes a mirror.
- 07-13 §3g class-attribute mutation leaks frustum culling across contexts;
  07-26 m24 `DEFAULT_SKIN` process-wide mutable singleton, m15
  `hud.distribute()` mutates its caller's list; GLI A11, A16; OMI C4
  `to_gltf` aliases a live list.

Where the fix landed. Per-instance initialisation (bf9facc "The zone mixin
keeps no state on its class", 4b8943e); factory functions
`shipped_trees()`/`default_cover()` (3e7a6a8); new Shapes per mesh user
(f9051d6).

Detectability: (a) plus (b). Ruff `RUF012` (mutable-class-default) flags a
mutable class attribute not annotated `ClassVar`; `B006`/`B008` cover
arguments (B006 is already in `test_lint_gates.py`). A custom check for
`__dict__.setdefault` and for module-level containers written from functions
is (a). Typing: `ClassVar[Mapping[...]]`, `Final`, `tuple`/`frozenset` and
`types.MappingProxyType` for shared tables make a mutation a mypy error.
Aliasing on export (OMI C4) is (d).

---

## 10. Optional frame layer without failure isolation, or retrying forever

Definition. An optional part of a frame (reflections, zone captures, bloom,
IBL, a vegetation layer, a background loader worker) is called from the frame
without a guard, so one exception loses the whole frame or every frame; or a
failure is answered by requesting another frame or another attempt with no
limit. Shape: a call from `Render`/`renderShared`/`OnDraw` into an optional
layer that is not wrapped in the sanctioned guard; `triggerRedraw`/`retry`
inside an `except` or an "unfinished" branch with no counter.

Recurrence, about 12: 07-13 1, 07-19 3, PR 1, 07-26 1, 09-25 6.
- REF-C1 `renderReflections` called unguarded (`passes/_flat.py:1666`);
  REF-M2 a mirror over the texel budget forces redraws forever.
- ZON-m1 / ZON-m2 a failed capture discards the schedule and retries every
  frame; MV-m3 fly-through requests frames forever after it ends; PASS-m17 /
  SG-m27 `LoadPool` workers die and are not replaced.
- 07-19 #6 a shader compile error in `instancedgl` kills the loop; G3 one bad
  Draco blob aborts the scene; I1 no capability probe; 07-26 M1
  `OverlayStack.clear()` loops forever; PR 4.24 a transient tessellation
  error latches permanently.

Where the fix landed. `OpenGLContext/passes/layerguard.py` `LayerGuard`
(2b39a0e), used by `flateffects.py` and `reflectionpass.py`;
`instancedgl.ensure_gl` for node layers; per-zone give-up in the capture
schedule (3b37935); worker replacement (0f2b557); planner stops asking for a
frame it cannot afford (d6cc1c7).

Detectability: (c). The pass can declare its optional layers; a checker then
asserts every call site of those methods inside the frame goes through
`LayerGuard.run`. "Retry forever" is (d): a test convention (drive a layer
that always fails and assert the frame count it asks for is bounded).

---

## 11. Swallowed or misreported errors

Definition. An exception is caught more broadly than the failure it
anticipates and then discarded, logged without its traceback, reported as a
different condition ("not found", "declares nothing", "skip"), raised as the
wrong type, or the documented exception family is incomplete. Shape: bare
`except:`; `except Exception`/`BaseException` whose body is `pass`,
`continue`, a return of an empty value, or a log call without `exc_info`;
`except OSError: return {}`.

Recurrence, about 28: Jan 1, 07-13 5, 07-19 1, PR 1, O09-03 1, P09-03 1,
CD 1, TY 2, EXT 2, GLI 2, OMI 2, 09-25 9.
- 07-13 §7a 173 `except Exception: pass` plus 11 bare `except:`; Jan 1.1;
  07-13 #8 `obj.py` Python-3 breakage swallowed; §3f per-frame exception to
  stderr.
- 07-19 I6 teardown `except Exception: pass` hides GL errors; PASS-n6 silent
  except-pass around a draw-state reset.
- CD 14.1 `except OSError: {}` turns an unreadable declaration table into
  "declares nothing" (`OpenGL/_declarations.py`); TY §10.3 bare
  `except Exception` lets a generator ship an incomplete stub.
- CP-15 traceback dropped by `log.warning('%s', err)`; CP-20 every `gh`
  failure read as "no release"; CP-22 documented exception family misses
  `InvalidURL`; ED-M10 stale glB accepted when Blender fails; GLI C9
  `SystemExit` from library code.

Where the fix landed. Case by case: `log.debug(..., exc_info=True)`
(8dc1976), narrowed catches (faec2f1, d902a1e, 35f2158), `importlib.resources`
reads (CD 14.1). No shared helper; the three projects that already select
`BLE` and `S110` show the gate.

Detectability: (a). Ruff `E722` (bare except), `BLE001` (blind except),
`S110` (try-except-pass), `S112` (try-except-continue) and `TRY400`
(error instead of exception in handlers) cover the syntactic core; a
`# noqa: BLE001 reason` convention records the deliberate ones, and `RUF100`
keeps noqa comments honest. "Logged without `exc_info`" inside a broad
handler is a short custom AST rule. Misclassification ("not found") is (d).

---

## 12. Redundant per-frame work

Definition. Work whose result does not change between frames is repeated
every frame or every draw: GL objects generated and deleted per draw,
constant uniforms and textures re-uploaded, a buffer reallocated instead of
sub-updated, an invariant recomputed twice, a warning logged every frame, a
subprocess run per call, and module imports executed inside per-draw
functions. Shape for the mechanical subset: `import` statements inside
functions reached from `render`/`OnDraw`/`update`; `glGen*`/`glBufferData`
inside `render()` without a cache guard.

Recurrence, about 48 (about 11 of them hot-path imports): 07-13 7, 07-19 3,
PR 5, 07-26 4, CD 1, TY 1, EXT 1, GLI 6, 09-25 20.
- 07-13 #3/#4/#5/§3c per-frame VAO/VBO churn in `shadergeometry.py`,
  `pointset.py`, `indexedlineset.py`, `nurbs.py`; §1a about 16 in-function
  numpy/ctypes imports in hot paths.
- SG-M6 every ground tile re-uploads about 20 constant uniforms and five
  textures (`scenegraph/terrain/`); SG-m16 ground cover re-uploads instance
  arrays every moving frame; REF-m11 `keep()` blits the whole atlas.
- MV-m20 `draw_arrays` imports `OpenGL.GL` every draw; PH-12 per-frame import
  of `apply_zones`; PR 4.7, 4.20; GLI E10; MV-m19 uncached subprocess.
- GLI E3 `Course.nearest` recomputed 10.5 and 50 times a frame; PASS-n7 a
  broken LOD node warns every frame.

Where the fix landed. `instancedgl.InstanceBuffer`, `build_mesh_gpu`
(cached per context with `depend_fields`), `_get_or_build_vao` (07-13), the
`ViewPrograms` setup callback (39bd94d), module-scope imports (e75a0e3,
d45de01), `cached_property` in glisteel. `passes/renderstats.py` counts draws
per frame for the overlay.

Detectability: (a) for imports, (d) for the rest. Ruff `PLC0415`
(import-outside-top-level) with a per-line reason for deliberate lazy imports
is deterministic. GL churn inside `render()` is (c) by AST. The general case
wants a test convention: render the same still scene twice and assert the
second frame's GL call counts (uploads, allocations) from `renderstats` or a
call-counting shim are at a floor.

---

## 13. Frame cost that grows with scene size in Python

Definition. Per frame (or per physics step, per edit) Python iterates over
every object, record, zone, triangle or pair, or materialises an
objects-by-zones-by-corners array, where an index, a spatial grid, a
vectorised NumPy expression or incremental update would bound the cost.
Shape: nested Python loops or per-element NumPy calls over scene-sized
collections inside a per-frame method; `list.pop(0)`; O(n*m) membership.

Recurrence, about 39: Jan 3, 07-13 1, 07-19 4, PR 2, P09-03 1, CD 1, EXT 6,
GLI 3, DEC 2, 09-25 about 20.
- ZON-M5 one moving zone reclassifies every object, 125 ms a frame at 5,000
  objects; ZON-M6 first classification allocates 443 MB; REF-M4 per-record
  Python per mirror view, 77 ms at 2,000 records x 4 views.
- GAME-G16 full-centreline nearest-point scans at the physics rate; LIB-D1
  `multiple-choice` schedule 28 s against 0.02 s; LIB-D6 compiled loop
  quadratic in valence; PH-08 linear body lookups.
- 07-19 #15 collision broadphase O(N) over trunk colliders; X3 per-triangle
  Python bake; EXT F-1/F-2 weld loops; DEC 12/13 brute-force certify and weld.

Where the fix landed. Vectorised or incremental passes (41aa5cb zones,
b05e7f8 mirrors), `opengl_decimate.spatial` uniform grid, the terrainwalk
spatial hash, `scenegraph/roadcourse.RoadCourse` windowed search (f52f33e),
boolean liveness arrays in omi_physics (010ef09).

Detectability: (d). Complexity is not visible in the AST in any useful way
here. The enforceable form is a scaling test convention under the existing
`serial` marker: time or count work at n and at k*n objects and assert the
ratio stays under a bound, for each per-frame subsystem.

---

## 14. Unbounded accumulation

Definition. A list, log, queue, cache or pending set is appended to on a
recurring path and nothing removes from it (no eviction, drain, cap or
clear), so memory grows for the life of the process. Shape: `.append`,
`.extend`, `[key] =` on a module-level or `self` container inside a method,
with no `pop`/`clear`/`del`/`popleft`/`maxlen` on the same container anywhere
in its class or module.

Recurrence, about 10: 07-19 2, EXT 1, P09-03 2, CD 1, GLI 1, 09-25 3.
- GAME-M2 / LIB-P9 marble-demo's `contact_log` grows to 65 MB, never drained
  (omi_physics); MV-m21 viewer archive cache with no eviction.
- CD 9-K3 `_installed_callbacks` appended and never emptied; P09-03 m7
  retired dispatch tables never reclaimed.
- 07-19 X2 `physics_colliders.on_evicted` pending list; X4 residency never
  deletes stale entries; EXT B7 `_created` grows while its docstring says it
  is cleared; GLI A17 `_DRAWN` module cache.

Where the fix landed. Drained logs and subscriptions (`PhysicsWorld.log_events`
only once something subscribes, 4ee44f4; omi_physics 010ef09), capped caches,
`dispatch.reclaim_retired()` in PyOpenGL.

Detectability: (c). The "grows here, never shrinks anywhere" pattern is a
cheap AST check per container attribute with a small allowlist; it misses
growth through aliases. `collections.deque(maxlen=...)` as the sanctioned
recording type makes the bound explicit.

---

## 15. C-boundary memory and error safety

Definition. In C, Cython or a ctypes boundary: a pointer or buffer outlives
its owner or is read past its measured length; an output buffer is sized from
the wrong object; an integer is narrowed without a range check (`long` vs
`int64` on LLP64); a failed allocation is read as an answer; an error status
is returned with no Python exception set, or a pending exception is
clobbered; undefined behaviour through a mismatched function-pointer cast;
the GIL held across a blocking driver call.

Recurrence, about 25: P09-03 3, P09-24 1, CD 14, TY 1, DEC 4, OMI 1, 09-25 1.
- P09-03 B1 output-array bounds guard measures the wrong buffer
  (`accelerate/src/c/pygl_runtime.c`); M4 debug branch returns -1 with no
  exception set; m5 `PyErr_Restore` clobbers a pending exception.
- CD 4.1 use-after-free when a context table is forgotten; 4.2 GIL held
  across every blocking call; 5.8 stubs cast to a 4-argument vectorcall slot;
  9-E1..E6 unchecked results and missing `PyErr_Occurred`; 9-S4 no
  `m_free`/`m_clear`.
- P09-24 #1 `glGetUniformIndices(program, N)` dereferences a null `char**`
  (segfault).
- DEC 2 fixed scratch buffers give up at valence 1024; DEC 3 `long[::1]` on
  `int64` breaks on Windows; DEC 17 compiled loop never releases the GIL; DEC
  18 failed `realloc` leaks; LIB-D21 indices narrowed without check; OMI C3
  partial device-buffer write.

Where the fix landed. `pygl_buf_reset`, `pygl_byte_count`,
`pygl_ensure_raised`, `pygl_error_code` in `pygl_runtime.c`;
`src/cdispatch/blocking.py` driving `PYGL_CALL_*_BLOCKING`; the retire list
for forgotten tables; `StringArrayCountChecked` / `PYGL_STRING_ARRAY_MIN`;
opengl_decimate `IntPool`, `cnp.int64_t`, `with nogil:` (see
opengl_decimate/plans/REVIEW-0.1.0a1.md).

Detectability: (c). Compiler warnings as errors (`-Wall -Wextra -Wpedantic
-Werror`, which would have caught CD 5.8 and 9-S6), clang-tidy/cppcheck,
Cython directives (`boundscheck`, `wraparound`) in debug builds and a grep
ban on bare `long` in `.pyx` memoryviews are deterministic for their
shapes. Lifetime and exception-state contracts need an ASan/UBSan CI job
(CD 11-6 asks for one) and the rule, already the workspace's, that a crash
stops the work.

---

## 16. Inert declarations

Definition. Something presents itself as a control and has no effect: a
node field or option that nothing reads, a parameter the function ignores, a
widget whose value nothing consumes, a guard that can never fire (checks the
wrong buffer, reads an attribute nothing sets, tests AVAILABLE for ACTIVE),
an environment variable nothing reads. Shape: unused function parameters;
declared VRML/dataclass fields never read anywhere in the package; a
condition whose operand is never assigned.

Recurrence, about 24: PR 3, STR 1, 07-26 4, P09-03 3, EXT 3, GLI 4, DEC 1,
OMI 1, 09-25 2 (and 3 more secondary).
- PR 3.5 `PBRMaterial.doubleSided` inert; 3.13 per-light shadow bias fields
  dead; 3.17 capability caps advertise tiers not implemented.
- 07-26 B5 / M10 / m5 half-wired widgets in `ui/generate.py` and
  `ui/widgets.py`; m7 `display_value(metrics)` ignores its argument.
- P09-03 M1 accelerate version guard can never fail; m4 `validate=True`
  validates nothing for multi-sampler programs; m12 AVAILABLE for ACTIVE.
- EXT B1 `crease_angle` documented and inert; B2 `normals='path_edge'`; DEC 6
  `position_noise` alone is a no-op; OMI F5 `autoplay` never acted on; GLI
  D1-D3 ignored parameters; CP-6 documented `requires` never parsed; STR 6 a
  dead environment variable.

Where the fix landed. Wire it or remove it, case by case. Ruff `ARG` is
selected in opengl_decimate, opengl_extrusions and omi_physics.

Detectability: (a) for parameters (ruff `ARG001`/`ARG002`, with `_` names for
protocol conformance). (c) for fields: a checker lists every field a node
class or option dataclass declares and every attribute read in the package,
and reports declared-but-never-read. Guards that never fire are (d): the test
convention is a red test per guard that drives its failing input.

---

## 17. Typing that does not check

Definition. Two shapes of the same fault, a type gate reporting success
without having compared anything. The configuration shape: mypy not run, run
against an editable install where siblings are `Any`, `check_untyped_defs`
off, `python_version` above the supported floor, `# mypy: ignore-errors`,
`py.typed` missing or shipped over thousands of errors, stubs that drift from
runtime. The annotation shape: `Any` in a public signature where a concrete
type or Protocol exists, `# type: ignore` with no code and no reason, records
passed as positional tuples, `if False:` for `TYPE_CHECKING`.

Recurrence, about 40: Jan 1, 07-26 4, P09-24 2, CD 4, TY 4, EXT 1, GLI 3,
OMI 3, 09-25 18.
- ZON-M10 zone modules fail the project's mypy gate with 47 errors;
  PASS-m3, SG-m22, PH-04 further gate errors.
- MV-m16 public multi-view API typed `Any`; SG-m24 hooks API `Any`; ED-m25
  editor world queries `Any`; GLI T3 `Any` on nearly every parameter; OMI Q3
  NumPy typing `Any`; CD 7.1 every PyOpenGL array alias collapses to `Any`.
- SG-m23 seven new `type: ignore` with no reason; ZON-n4; PASS-n13.
- EXT C1 mypy passes because untyped bodies are never checked; GLI T1 mypy
  configured and failing; OMI Q5 / TY §4 `python_version` pinned above the
  floor; CD 7.2 `py.typed` over 3,718 errors; CD 14.7 `ignore-errors` does
  not stop following; TY §7 pydispatch ships no `py.typed`; TY §8 about 40
  unverified TYPE_CHECKING shims.

Where the fix landed. `tools/preflight.py` typechecking in
`.preflight-venv` with every project installed non-editable (the workspace
CLAUDE.md explains why); `disallow_untyped_defs`, `check_untyped_defs`,
`warn_unused_ignores` in openglcontext's `pyproject.toml`; Protocols
(`ViewCamera` e39f521, glisteel `interfaces.py`); 8c0b006, bf9facc, 92a9b04,
cf35d34; `tests/unit/test_declared_shims.py`; `pydispatch/py.typed` with a
packaging test.

Detectability: (a) for configuration and ignores, (b) for `Any`. A
configuration test can assert each project's mypy settings (strictness flags
present, `python_version` equal to the `requires-python` floor or a matrix
over it) and that `py.typed` ships (`test_what_the_wheel_ships.py` in
pyopengl is the pattern). mypy's `enable_error_code = ["ignore-without-code"]`
plus ruff `PGH003` make every ignore carry a code; a short tokenize check
requires reason text after it. `Any` in public signatures: a custom check over
names in `__all__` (or mypy `disallow_any_explicit` per public module),
deterministic.

---

## 18. Prose that breaks the writing rules

Definition. Docstrings, comments and documentation that narrate history
("previously", "no longer", "replaces the old"), carry review bookkeeping
(finding codes, "per the review"), use bold-leader lists, insist or sell
("which is the whole point"), apologise, dare the reader, or give the software
perception ("the game hears"). Shape: regular expressions over string
literals and comments, which the `ai-isms` scanner already implements.

Recurrence, about 31 primary (more as secondary): 08-03 2, P09-24 1, GLI 1,
09-25 27.
- GAME-G22 glisteel docstrings narrate history and journal anecdotes;
  SG-n1, MV-m18, ED-n1..n5, LIB-W1, GAME-F5, GAME-T7.
- PASS-n1 / ZON-n9 review finding numbers in `shaders/pbr.frag` comments;
  08-03 m7 finding numbers in `pyproject.toml`, `MANIFEST.in`.
- DOC-25 README bold leaders and glosses; LIB-A4 CHANGELOG bold bullets;
  REF-n10 / BIN-17 perception verbs; P09-24 #14 test docstrings narrate what
  used to happen.

Where the fix landed. `.claude/skills/ai-isms/` (`scripts/scan.py`, `/ai-isms
--fix`) and `python build-docs.py --only prose` for PyOpenGL's pages;
sweeps 5f21b22, 41ccaab, 8f15e33, 985053a, glisteel 84e56c9.

Detectability: (a) for the lexical signs (finding-code patterns such as
`[A-Z]{2,5}-[CMmndt]\d+`, "finding \d", "previously", "used to", "no longer",
bold-leader list items, the named glosses); (c) for the rest. Running
`scan.py` over changed files in `tools/preflight.py`, failing on the
deterministic signs and reporting the others, is the gate.

---

## 19. Documentation that contradicts the code

Definition. A docstring, comment, page, README, `--help` text or example
states behaviour, a default, a unit, a limit or a guarantee the code does not
have (often a safety or coverage claim nothing tests). Shape: not syntactic.

Recurrence, about 85 of the 154 documentation findings (the other 69 are
class 20): spread across every review; heaviest in 09-25 (about 45), DEC
(about 10), OMI, EXT, CD and STR.
- 07-26 M2 `ui/console.py` `_follow()` does what its docstring forbids; M4
  `ui/draw.py` `end()` claims to restore GL state.
- CD 10-extra `_dispatch/__init__.py` docstring says the default is ctypes
  two lines above setting `c`; CD 5.4 `PYOPENGL_FULL_LOGGING` documented to
  select ctypes, does nothing; CD 10.3 "a difference not in the table is a
  test failure" while the test checks 3 of 11 attributes.
- DOC-07 reflection texture-unit threshold off by one; DOC-15 water page;
  ZON-d3/d6; MV-M2 tile aspect; LIB-D2/D3 decimate docs; ED-M9 `--canopy`
  help; GAME-G3 / GAME-T3 base pack documented as fetched.
- DEC 5, 7, 10, 24, 25; OMI D3 three documented guarantees not met; EXT A1
  README headline example fails; GLI C10 doctest wrong and never collected.

Where the fix landed. Page and docstring edits in the same commit as the fix
(feac428, dd659f3, ee585ca, 41aa5cb, 842b416, 4acb2c4). Where a page is
generated from the code it cannot drift: `docs/environment` from
`renderoptions.ENVIRONMENT` (STR), PyOpenGL's `BY_DESIGN` turned from prose
into predicates (CD).

Detectability: (d), with a (c) fringe. Examples are (a): collect doctests
(`--doctest-modules`, as EXT E1 did) and run README code blocks. Tables that
restate code (environment variables, CLI options, option dataclass fields and
defaults, extension lists) are (c) if generated from, or tested against, the
source of truth. The rest needs the "documentation ships with the change"
rule.

---

## 20. Documentation missing or pointing nowhere

Definition. A shipped surface (public module, console command, option,
environment variable, extension, node, file format) has no page, index entry,
changelog entry, directory-map row or `untrusted.rst` coverage; or a doc, docstring
or shader comment names a module, method, command, file or link that does not
exist. Shape for the mechanical part: every public module appears in
`CLAUDE.md`'s directory map and `docs/structure.rst`; every console script,
`renderoptions.ENVIRONMENT` entry and `__all__` name has a doc mention; every
dotted name, path and link in docs resolves; a version bump has a changelog
entry.

Recurrence, about 69 (about 50 missing, about 19 dangling): Jan 1, STR 7,
08-03 4, P09-03 1, P09-24 1, CD 2, EXT 4, OMI 6, 09-25 about 40.
- Missing: DOC-02 README changelog stops at 3.0.0a1, LIB-D25 / LIB-P3 no
  CHANGELOG for opengl_decimate / omi_physics releases; SG-d1 `untrusted.rst`
  silent on hooks, zones, image lights; ZON-d8 / PASS-d3 / DOC-12 directory
  map and structure page omit modules; DOC-13 zones lack a front-page entry,
  demo and tutorial; P09-03 m10 EGL devices module ships with no page; STR 10
  no environment-variable page, 11 `nav/` undocumented.
- Dangling: DOC-01 link to a tutorial never generated; MV-m10 docs name a
  nonexistent `placeViews`; MV-m12 shader comment names a nonexistent module;
  08-03 M5/M6/m1 dead module paths and 49 dead pydoc links; STR 8, extra-b,
  extra-d `oglc-profile` never registered; ED-d4 `.html` for `.md`;
  DOC-17 docstrings that produce docutils errors.

Where the fix landed. `tests/unit/test_documentation_references.py` in
openglcontext (every dotted name in a docstring imports; pages' commands
exist) from the STR review; ae6b376, 5104af3, 2b16950, 87a45d0, d694709,
a17e096; Sphinx `-W` in `build-docs.py`.

Detectability: (a) for dangling references and for list-completeness (map
rows, structure rows, env vars, console scripts, changelog on version bump):
all are set comparisons between the code and a document. Extending
`test_documentation_references.py` to the other projects and to `.rst`,
shader comments and `CLAUDE.md` covers the dangling half; completeness
tests cover the listed surfaces. Whether a feature is documented well enough
is (d).

---

## 21. Dependency floors and packaging contents

Definition. The declared requirements do not match what the code needs or
what the release carries: a floor below the sibling or third-party API
called, `requires-python` below the language or C-API level used, a floor
never exercised, dependencies unresolvable from the index, package data or
manifests missing from the wheel/sdist or stale files shipped, a lower
layer's API used before it is released.

Recurrence, about 36: Jan 1, PR 7, 08-03 6, P09-03 1, P09-05 1, P09-24 1,
CD 2, EXT 1, GLI 1, DEC 2, OMI 2, 09-25 11.
- BIN-3 / ZON-m15 / ED-M5 `omi_audio>=0.2.0a1` while the engine calls
  `set_rate` and reverb that no release carries; ED-M11 editor HEAD uses the
  engine's old species API; GAME-W1 opengl_decimate missing from
  `verify-everything.py`.
- CD 4.4 `requires-python >=3.9` while the C dispatch needs 3.10; ED-m11
  `tomllib` under a 3.10 floor; PR 3.30 SPDX licence needs setuptools>=77.
- 08-03 B2 a stale `build/` shipped deleted modules including gzpickle; B3
  five dependencies unresolvable from PyPI; DEC 4 sdist omits
  `tests/shapes.py`; ED-M4 Blender manifest missing from the wheel; CP-19,
  DOC-04.
- DEC 22 numpy floor never exercised; GLI A18 assets through `__file__`.

Where the fix landed. `scripts/check_release_artifact.py` (built artifact
against the tree); pyopengl's `tests/bindings/test_what_the_wheel_ships.py`;
opengl_decimate's `oldest-numpy` tox env and sdist-unpack CI step;
`tools/release.py` `version_files` and release order in
`tools/release.toml`; floors raised in f9d10f3 and 064b328.

Detectability: (a) by execution rather than by AST. A preflight environment
resolved at the declared minimums (`uv pip install --resolution
lowest-direct`) running the suite finds floor defects deterministically, and
an artifact check finds packaging ones. `vermin` or a small AST check finds
stdlib APIs newer than `requires-python`. Sibling floors can be checked by a
tool that compares each `[project] dependencies` pin with the version that
first carries the names imported (release metadata), which is (c).

---

## 22. Tests that cannot fail

Definition. A test passes whatever the code does: it skips on the crash it
exists to detect, asserts something true by construction (`is not None` on a
comprehension, `<=` where `<` is the claim, the fixture it was built from),
never calls the code named, swallows the exception with `pass`, or the whole
suite reads green while skipped (no display, a drifted availability check, a
dispatch axis that silently fell back).

Recurrence, about 28: PR 3, 07-13 1, 08-03 1, P09-03 1, P09-24 3, CD 2, TY 1,
EXT 13, OMI 2, 09-25 1.
- ZON-M11 zone render and cost tests turn a crash into a skip; 08-03 m13 a
  skip hid an unimportable `shadershape.py` since July.
- PR 2.9 visual regression gate is a tautology; 4.31 the whole visual suite
  skips when `$DISPLAY` is unset; 07-13 #11 drifted display-check copy.
- EXT D1-D13 thirteen vacuous or wrong assertions (for example D9 "all
  survive" swallows `TriangulationError`, D10 asserts a comprehension is not
  None); OMI T2 a "report themselves" test never calls `__repr__`.
- P09-24 #7 listening-socket test never touches the listener, #9 a class
  inserted mid-file absorbed two tests, #18 C cases skipped when run alone;
  CD 11-5 470 unsummarised skips; TY §14.3-b two tests skipped for two months.

Where the fix landed. c260e9c (zone tests fail on a crash); `-ra` in
`addopts` so every skip states its reason; the `conftest.py` self-check that
`PYOPENGL_DISPATCH=c` implies `ACTIVE`; `BY_DESIGN` predicates;
`OpenGLContext/testing/display.py` as the one availability check; hypothesis
property tests in opengl_extrusions.

Detectability: (a) for the syntactic shapes, (c) overall. An AST check over
test modules can flag `pytest.skip`/`xfail` inside an `except` block,
`pytest.importorskip` of a first-party module, `except ...: pass` in a test,
test functions with no `assert`/`raises`/fixture-assert call, and
`assert <comprehension> is not None`. A skip budget (fail when skips exceed
an allowlist with reasons) is (a) at run time. Assertions weaker than the
claim need mutation testing (OMI T1 found three surviving mutations), which
is (d) as a routine gate.

---

## 23. Untested paths and ungated suites

Definition. Code that ships is not exercised by any gate: a branch or module
with no test, a compiled path excluded from coverage, a platform the wheels
target but CI does not run, a project whose suite `verify-everything.py` or
preflight does not run, doctests not collected, a declared gate (ruff, mypy,
coverage) nothing runs.

Recurrence, about 49: Jan 4, PR 7, 07-19 1, STR 1, 07-26 1, P09-05 2,
P09-24 2, CD 2, TY 3, EXT 6, GLI 3, DEC 5, OMI 4, 09-25 8.
- GAME-W1 `verify-everything.py` does not run opengl_decimate; P09-05 #1
  macOS CI never builds the C dispatch; DEC 14 100% coverage measures none of
  the 820-line compiled reducer; DEC 15 ubuntu-only matrix for three-platform
  wheels.
- REF-m16, PASS-m18, ZON-m16, ED-t1/t2, PH-09 new branches untested; REF-M8
  the VRML97 mirror path has no test.
- EXT C4 no CI; OMI T6 ruff/mypy declared and run nowhere; EXT E1 / GLI C10
  doctests never collected.

Where the fix landed. 37ff30c (opengl_decimate added to
`verify-everything.py`); `tools/preflight.py` and `tools/preflight.toml`
("declared configuration counts as a gate"); CI matrices in
opengl_extrusions and opengl_decimate; 3390cf2, 40e887d, ccab6c5, e10a78b.

Detectability: (a) for gate coverage: a workspace test can assert that every
submodule with a `pyproject.toml` is in `verify-everything.py`'s project list
and in `preflight.toml`, that every declared ruff/mypy/coverage config is
exercised by a gate, and that CI matrices name every platform the wheel build
targets. (c) for code: a diff-coverage gate on changed lines. Choosing what
deserves a test is (d).

---

## 24. Logic hidden in window-bound code

Definition. Decisions, loops or state machines live inside a class whose
construction opens a GL surface (a Context, a render pass entry point, a
mainloop callback, a UI screen) so no unit test can reach them; the marker is
`# pragma: no cover - needs a window` (or GL) over a body that is mostly
logic.

Recurrence, about 9: Jan 1, 07-26 1, GLI 3, 09-25 4 (plus the private-reach
findings moved to class 25).
- GLI T4 pragma hides 79% of `game.py`, which then reports 100% coverage;
  GAME-G1 glisteel's Driving and Downloads screens never close, unseen for
  that reason; GLI C3 pointer handler bound before `self.keyboard` exists.
- REF-m14 mirror-view content selection inside the window-bound pass; BIN-7
  the physics demo's frame pacing and forward ray in `main()`'s context;
  ED-M7 `bake_probes` scheduling untestable; 07-26 m20 `no cover - GL` on the
  overlay's only draw entry.

Where the fix landed. Plain objects that take their inputs and time step
(`passes/reflectionplanner.py`, `reflectiontiles.py`, `zonebake.ZoneBakePlan`
c1a4439, `events/framestep.py`, `ViewPlatform.forward()` acf95bc); the rule
"Hoist the logic out of what a test cannot reach" in the workspace CLAUDE.md.

Detectability: (c). The pragma is greppable and countable (79 today): a
ratchet that fails when the count or the number of covered-by-pragma lines
rises is (a) as a gate, and a checker can flag a `no cover` block that
contains branching over non-GL values. Whether logic belongs in a plain
object is (d).

---

## 25. Module boundary violations

Definition. Code reaches into another object's private state
(`other._name`, a pass's private cache, pydispatch's internal registry, a
test reading `writer._durations`), or the public surface is inconsistent: a
name imported by siblings but missing from `__all__`, underscore-private
names imported across modules, one option with two spellings, the same
concept named in camelCase and snake_case, GL and GLES variants of one
function with different signatures.

Recurrence, about 32: 07-19 2, PR 2, STR 2, 07-26 2, O09-03 0, P09-24 3,
TY 1, EXT 2, GLI 3, DEC 1, 09-25 14.
- REF-n1 planner calls a private and `__all__` is incomplete; MV-m17
  `ProgressBar` missing from `__all__`; MV-n15 `poses_from`; GLI T6
  `race.__all__` omits seven names; EXT C7.8, C7.9.
- 07-19 #14 terrain nodes reach into the PBR pass's private cache; 07-26 M11
  geometry writes the pass's private GL-state cache; ZON-m5 capture path
  reads schedule internals; GAME-G7 `diagnose` sets `Traffic._rng`; PR 4.21
  context reaches into pydispatch internals; P09-24 #15 tests unpack private
  marshal blobs; LIB-W4.
- STR 1 / MV-n3 camelCase and snake_case for one concept; BIN-15 two
  spellings of one option; P09-24 #2 GL and GLES3 signatures differ; 07-26 m1
  `Skin._image()` called from five modules.

Where the fix landed. Public methods replacing the reach-in
(`mode.setCullState`, `_declarations.declared_commands()` /
`ctypes_entry_point()`, `ViewPlatform.forward()`); `__all__` fixes (c2bf4ee,
eac9d70, 41ccaab); the naming rule recorded with MV-n3 (1e7a9a8).

Detectability: (a). Ruff `SLF001` (private-member-access) flags
`obj._name` for any `obj` other than `self`/`cls`, with per-line reasons for
the deliberate ones. An `__all__` completeness check (every name another
module of the package imports from a module that declares `__all__` is in
it; every public top-level definition is in it or deliberately private) is a
short AST pass. Naming conventions per layer are (a) with scoped
`pep8-naming`.

---

## 26. Thread safety

Definition. State shared between threads (a render thread and a physics or
load thread, a watcher thread, a driver callback) is mutated without the lock
that guards it, a snapshot is taken outside the lock, module-level dicts are
modified unlocked, or thread-local state is relied on outside the conditions
that make it valid.

Recurrence, about 11: 07-19 1, P09-05 1, CD 2, DEC 1 (GIL, also in 15),
09-25 6.
- PH-01 threaded manager loses a removed body's events; PH-03 render thread
  mutates the world without the world lock; LIB-P10 `dropped` miscounts on a
  racing drain (omi_physics).
- SG-m14 `_blocks` swapped while a background scatter may write; MV-n14
  module dict modified without a lock (`eglcontext.py`).
- 07-19 I7 undocumented load/render-thread swap in `passes/ibl.py`; CD 8.3
  about 20 mutable process-global C statics with no `Py_mod_gil`; CD 9-K4
  debug callback thread-local state; P09-05 #8 glBegin-dirtied tracking is
  one global across contexts and threads.

Where the fix landed. `with_world()` and `ThreadedSimulation.flush_events()`
(e10a78b, omi_physics 010ef09, 4ef553c); locks in `eglcontext` (11edccd);
generation check before storing (97f90f9).

Detectability: (d), with a (c) fringe. There is no dependable static race
checker for Python. A checker can flag module-level containers written from
functions outside a `with <lock>` block, and a `GuardedBy` convention (a
wrapper type whose value is reached only through `with guarded as value:`)
makes the lock unavoidable where adopted (b). A free-threaded CPython CI
row and TSan on the C extensions are the dynamic backstop.

---

## 27. Engine capability outside the engine

Definition. A capability a game or application would also want (download
consent UI, release publishing, pack resolution, vehicle audio, road-course
queries, glTF writing, kinematic movers, bake loops) is implemented in a
demo, game, editor or tool, often more than once, or reads engine privates;
or a shipped demo does not exercise the engine feature it advertises.

Recurrence, about 23: 07-19 2, STR 1 (secondary), 09-25 about 21.
- GAME-X1 three copies of `release-assets.py`; GAME-X2 three import-bound art
  resolvers; GAME-G18 two download consent screens; GAME-G19 vehicle sound
  synthesis in glisteel; GAME-G20 road-course queries in glisteel.
- ED-M8 four hand-written glTF readers and writers beside the engine's;
  ED-M6 bore openings derived twice; ED-M7 zone-light bake reading pass
  privates; BIN-6 kinematic door and trigger occupancy in a demo; GAME-E6
  `ProceduralWorld` parameters restated.
- 07-19 #10 tiles3d carries a second, mostly dead vegetation engine; X5 an
  "optional" dependency hard-wired into core terrain. BIN-4 / BIN-5 the audio
  demo shows flat plastic and the fallback rather than zones.

Where the fix landed. New engine APIs: `contentpacks/publish.py`
(`Release`, `main`, 4253ba8), `contentpacks.Application` (f358383),
`ui/contentscreen.ContentScreen` (43dc4fb), `audio/vehicle.VehicleSoundtrack`
(ea7e869), `scenegraph/roadcourse.RoadCourse` (f52f33e), `KinematicMover` and
`CollisionEvents.occupancy()` (b44ad79), `GLTFWriter.add_lod`/`add_zone`
(542cfcf, b563ce0), `roadworks.BoreCut` (08da2ef), `passes/zonebake`
(c1a4439).

Detectability: (c). Cross-repository clone detection (pylint `R0801` or a
token-shingle tool run over the workspace with a threshold) finds the
duplicated-in-three-games shape. `SLF001` in demo and game packages finds
the "reads engine privates" shape deterministically. Whether a single copy
belongs in the engine is (d) and is the workspace's first written rule.

---

## 28. Numeric robustness

Definition. Arithmetic that fails at an edge: division by a value that can
be zero, NaN or infinity propagating, absolute epsilons in scale-dependent
geometry, precision lost far from the origin or in single precision,
accumulation without wrap, integer truncation of floats, unnormalised
quaternions, denormals, off-by-one in bounds, missing physical constants
(`/PI`, `roughness^2`).

Recurrence, about 45: 07-19 3, PR 9, STR 1, O09-03 1, P09-05 1, P09-24 1,
TY 1, EXT 4, GLI 1, DEC 1, OMI 1, 09-25 21.
- SG-M9 `GroundCover` raises `ZeroDivisionError` at zero density; LIB-W3 zero
  frame-rate numerator; MV-M5 distance clamp loses small subjects; PASS-m4
  inset assumes a 512-pixel tile; SG-m3 normals wrong under non-uniform scale.
- DEC 1 quadrics in absolute coordinates lose the metric far from the
  origin; LIB-D14 near-singular placement; LIB-D17 float index arrays
  truncated; LIB-A5 denormal decay.
- PR 4.4 IBL diffuse missing `/PI`; 4.12 unnormalised quaternion; 07-19 #13
  world-space hash precision; OMI C2 one NaN poisons the whole mix; EXT A2 /
  B12 absolute epsilons.

Where the fix landed. Local guards; `documentvalues.bounded` for values set in
code; `topology.local_origin` in opengl_decimate; non-finite-gain guard at the
control-thread boundary in omi_audio.

Detectability: (d), with (c) help. Property-based tests (hypothesis) over
degenerate and extreme inputs found real defects in opengl_extrusions; a test
convention that each numeric entry point has a property test over zero,
negative, huge and non-finite inputs is the enforceable form. `np.seterr`
set to `raise` in the test session turns silent NaN and division warnings into
failures, which is (a) at run time.

---

## 29. Algorithm and specification errors

Definition. The code does something other than what the specification
(glTF, VRML97, OpenGL, `KHR_audio_emitter`, `MSFT_lod`) or its own contract
says: wrong matrix convention, winding ignored under mirroring, wrong
default, clamp where the spec has none, a budget that misses a case, event
routing to the wrong view; and divergence between two implementations of one
API (C and ctypes dispatch, compiled and NumPy reducers).

Recurrence, about 118, the largest code class and the most evenly spread:
07-13 5, 07-19 4, PR 10, STR 4, 07-26 8, O09-03 1, P09-03 1, P09-05 1,
CD 8, TY 4, EXT 5, GLI 6, DEC 3, OMI 6, 09-25 about 58.
- Winding and handedness recur as a sub-shape: REF-M8 `IndexedFaceSet`
  mirrors ignore `ccw`; 07-13 §4e wrong winding under mirrors; EXT B3/B4
  `reversed()`/`transformed()`; GLI C2 car body wound inside out; SG-m3.
- SG-M5 ground tile matrix convention; PASS-M4 multi-view shadows vanish;
  REF-M5/M6 budgets; MV-M2 tile aspect; OMI C1 `maxDistance` clamped where the
  spec does not; PR 3.1 BRDF roughness remap missing.
- Parity: CD 6.1 / 6.2 `GLError` fields and tuple-vs-list outputs differ
  between C and ctypes; P09-24 #11 different error messages; DEC 2 compiled
  reducer disagrees with NumPy past valence 1024; LIB-D24.

Where the fix landed. Case by case; `scenegraph/winding.py`
(`apply_winding_cull`) as the one mirror-aware winding flip (07-13); the
differential tests `tests/test_native.py` (opengl_decimate) and
`tests/attribute_surface` / `check_absorption.py` (PyOpenGL).

Detectability: (d). The enforceable forms are conformance suites against the
specification's sample assets (the glTF conformance tests already exist),
differential tests between every pair of implementations of one API, and a
test convention for the winding sub-shape (every geometry path rendered under
a negative-determinant transform).

---

## 30. Dead code and duplication within a project

Definition. Code that nothing reaches (unused functions, modules, branches,
constants, scripts, fixtures, a whole experimental package) or the same
computation written two or more times inside one project (three
material-to-uniform readers, a matrix in three places, a shader function
inlined in four shaders, timing constants twice, four "yaw from forward"
implementations), which then drift.

Recurrence, about 106 (the largest class after documentation and spec):
Jan 2, 07-13 18, 07-19 7, PR 14, STR 2, 07-26 7, 08-03 3, O09-03 3,
P09-03 1, P09-24 2, CD 1, TY 4, EXT 4, GLI 15, OMI 2, 09-25 21.
- 07-13 §4c three parallel material-to-uniform paths; §2b `encodeObjectId`
  inlined in four shaders; §3h about 300 lines of dead fixed-function path;
  PR 2.10 about 600 lines of dead selection code in the hot path.
- STR 2 perspective/look-at three times and two `Frustum` classes; O09-03 m3
  `gl_context_key()` implemented identically three times; EXT C7.10/C7.11 the
  orientation error bound in four places.
- GLI A1 yaw from a forward vector four times with two sign conventions;
  GAME-G14/G15/G17, ZON-n7 three copies of the zone falloff; PASS-m8
  `renderShared` duplicates `setupViewLighting`; TY §14.1-a nine test modules
  re-implement stub parsing.

Where the fix landed. One copy each: `_vrml97_lighting_inc.glsl`,
`_objectid_inc.glsl`, `scenegraph/material_fields.py`,
`contextresources.context_key()`, `predicates.ORIENT_BOUND` (the `.pyx`
refuses to build if it disagrees), glisteel `geometry.yaw_of`, pyopengl
`tests/stubs.py`; the pass mixins `ReflectionsMixin` (6657acf) and
`MultiviewPassMixin` (8c20e9f).

Detectability: (a) for dead code that tools see (ruff `F401`/`F841`/`ARG`,
which openglcontext ignores or does not select; vulture at a confidence
threshold; zero-coverage files), (c) for duplication (pylint `R0801` /
token-shingle clone detection per project, GLSL included, with a
threshold). A constant or formula required in two languages (GLSL and
Python) is held by a test that compares them, as ccab6c5 and 5ca00aa do.

---

## Minor classes not listed above

Counted, but too small or too process-shaped for a class of their own:

- Lint and format: about 28 (Jan 1, PR 2, 07-19 1, 07-26 1, 08-03 2,
  P09-24 1, TY 1, EXT 2, GLI 2, OMI 2, 09-25 13). Missing E30x blank lines,
  deprecated `List`/`Dict`, inert `noqa` (07-26 m26, GLI D10), a ruff F811
  suppression that hid a real duplicate (P09-24 #19). (a): ruff `E30x`,
  `UP006/UP007/UP035`, `RUF100`, `ruff format --check`.
- Repository hygiene and process: about 10 (PR 2.1, 2.2, 3.29; EXT C6; OMI
  Q10; LIB-D20; LIB-V4; CD 8.2; TY §12-f). Generated outputs committed,
  packages untracked, stray worktrees, unrelated changes inside a commit.
  (a) for artifacts (a pre-commit check on `git ls-files` patterns), (d) for
  branch scope.
- Unsafe deserialisation and dynamic execution: about 4 (07-13 #2 `pickle.load`
  on scene data, P09-03 m2 `eval`, P09-03 m9 `exec`, CD 14.10-a marshal).
  (a): ruff `S301`, `S307`, `S102`.
- Determinism: about 4 (BIN-8 demos stepping from `time.time()`, GAME-E4 bake
  date in archives, PR 4.32/4.33 wall-clock capture). (c): ban
  `time.time()` in demos in favour of `systemtime.systemTime()` via `TID251`.
- Abrupt exit: 3 (PR 3.25 `os._exit` skips coverage, STR demo-a loses stdout,
  GLI A14 skips teardown). (a): ban `os._exit` outside `flush_and_exit`.
- Python 2 remnants: 3 (07-13 #0, #8, §7b). Now cleared; ruff `UP` keeps them
  out.
- Command-line entry without a parser: 1 (BIN-12 `oglc-mirrors --help` opens
  the demo). (a): a test runs every console script with `--help`.

---

## Ranking by total count across all reviews

| Rank | Class | Total (about) | Reviews it appears in | Grade |
|---|---|---|---|---|
| 1 | 19 + 20 Documentation (contradicting 85, missing or dangling 69) | 154 | 18 of 18 | (d) / (a) for references and list completeness |
| 2 | 29 Algorithm and specification errors | 118 | 15 | (d) |
| 3 | 30 Dead code and in-project duplication | 106 | 16 | (a) dead / (c) duplicates |
| 4 | 22 + 23 Test integrity (cannot fail 28, untested or ungated 49) | 77 | 16 | (a)/(c) |
| 5 | 5 Memo missing an input or not reset | 51 | 8 | (d) with (c) fringe |
| 6 | 12 Redundant per-frame work | 48 | 9 | (a) imports / (d) |
| 7 | 28 Numeric robustness | 45 | 12 | (d) |
| 8 | 17 Typing that does not check | 40 | 9 | (a) config and ignores / (b) Any |
| 9 | 13 Frame cost that scales with scene size | 39 | 10 | (d) |
| 10 | 1 Unchecked document values | 37 | 10 | (a) + (b) |
| 11 | 21 Dependency floors and packaging contents | 36 | 12 | (a) by execution |
| 12 | 25 Module boundary violations | 32 | 11 | (a) |
| 13 | 18 Prose rule breaks | 31 | 4 (+ secondary in 3) | (a) lexical / (c) |
| 14 | 11 Swallowed or misreported errors | 28 | 12 | (a) |
| 15 | Lint and format (minor) | 28 | 11 | (a) |
| 16 | 2 Unconfined paths and URLs | 25 | 8 | (a) sinks + (b) |
| 17 | 15 C-boundary memory and error safety | 25 | 7 | (c) |
| 18 | 16 Inert declarations | 24 | 9 | (a) params / (c) fields |
| 19 | 27 Engine capability outside the engine | 23 | 3 | (c) |
| 20 | 7 GL and frame state not restored | 22 | 7 | (c) / (b) via context managers |
| 21 | 4 Identity-keyed state | 21 | 11 | (a) id() / (c) context |
| 22 | 8 Configuration read at the wrong time | 19 | 9 | (a) |
| 23 | 6 Resources without an owner | 18 | 6 | (a) `__del__` / (c) / (b) |
| 24 | 3 Non-atomic or destructive writes | 14 | 5 | (a) |
| 25 | 9 Shared mutable defaults and aliasing | 14 | 6 | (a) + (b) |
| 26 | 10 Optional layer without isolation | 12 | 5 | (c) |
| 27 | 26 Thread safety | 11 | 5 | (d) with (c) |
| 28 | 14 Unbounded accumulation | 10 | 6 | (c) |
| 29 | 24 Logic hidden in window-bound code | 9 | 4 | (c), pragma ratchet (a) |

"Reviews it appears in" counts documents out of the 18 rows of the source
table where the class has at least one primary finding.

## Observations for the plan

The classes with the most findings are the least mechanically detectable
(documentation contradictions, spec errors, stale memos, numeric edges). The
classes the 09-25 review singled out as cross-cutting themes are mostly the
mechanically detectable ones, and each now has one sanctioned API, so a
checker can enforce "use X":

| Class | Sanctioned API | Enforcement |
|---|---|---|
| 1 Unchecked document values | `loaders/documentvalues.DocumentValues`, `bounded` | AST ban on bare conversions in loaders and hooks; `JSONObject = Mapping[str, object]` |
| 2 Unconfined paths | `Resolver`, `tiles3d.fetch.beside` / `local_copy`, `AllowedHosts.open_url` | `TID251` banned-api on raw openers; `ContainedPath` NewType |
| 3 Non-atomic writes | `OpenGLContext.atomicfiles`, `tools/atomicwrite.py` | `TID251`/AST ban on write sinks outside them |
| 4 Identity-keyed state | object-held keys, `WeakKeyDictionary`, `contextresources` | AST ban on `id()` as a key |
| 6 Resources without an owner | `passes/disposal.PassResources`, `let_go`, node `dispose()` | AST: GL allocators only in owning classes; no GL in `__del__` |
| 7 GL state not restored | `passes/framestate.FrameState`, cull-state memo | sanctioned context managers; raw state calls banned in `passes/` |
| 8 Configuration timing | `renderoptions.env_flag_once` / `env_number_once`, `contentpacks.Application` | extend `test_no_configuration_at_import.py` to package and demos; environment reads only in `renderoptions` |
| 9 Shared mutable defaults | per-instance init, factories | ruff `RUF012`, `ClassVar`/`Final` |
| 10 Optional layer isolation | `passes/layerguard.LayerGuard` | AST: declared optional layers called only through `LayerGuard.run` |
| 11 Swallowed errors | narrowed catches with `exc_info` | ruff `E722`, `BLE001`, `S110`, `S112`, `RUF100` |
| 12 Hot-path imports | module-scope imports | ruff `PLC0415` |
| 17 Typing | `tools/preflight.py` typecheck in `.preflight-venv` | mypy `ignore-without-code`, ruff `PGH003`, reason-text check, config test, no `Any` in `__all__` signatures |
| 18 Prose | `.claude/skills/ai-isms/scripts/scan.py` | run in preflight, fail on lexical signs |
| 20 Dangling docs | `tests/unit/test_documentation_references.py` | extend to all projects, `.rst`, shaders, `CLAUDE.md` |
| 25 Module boundaries | public methods for what was reached into | ruff `SLF001`; `__all__` completeness check |

openglcontext's `tests/unit/test_lint_gates.py` ratchet (a rule joins the
list once the package is clean of it) is the existing mechanism to adopt the
ruff rules above one at a time without a flag day: `RUF012`, `BLE001`,
`S110`, `S112`, `E722`, `PLC0415`, `SLF001`, `PGH003`, `RUF100`, `TID251`,
`S202`, `S301`, `S307`, `ARG`. The custom AST rules (`id()` keys,
module-level side effects, write sinks, bare conversions in loaders, GL in
`__del__`, skip inside `except` in tests) fit the same parametrised shape as
`test_no_configuration_at_import.py`, and could live as a small shared
checker package that each project's suite and `tools/preflight.py` run, so
the games and libraries get them too.

For the (d) classes the reviews themselves point at test conventions that
make a defect fail a test rather than a frame: a memo test that edits each
declared input; a still-scene second-frame call count; scaling tests under the
`serial` marker; property tests over degenerate inputs with
`np.seterr(all='raise')`; differential tests between every pair of
implementations of one API; rendering every geometry path under a mirroring
transform.
