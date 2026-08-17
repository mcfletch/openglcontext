# Code review — OpenGLContext, 4262442..HEAD (2026-08-03)

**Scope.** The 39 commits from `4262442` to `d66d249` (`reconstruct/logical-history`
vs `master`): 816 files, +134,990/−27,615. This is the final review before the
**3.0.0a1** release, so it covers the whole branch rather than one subsystem —
the glTF loader package, the PBR/shadow/IBL render passes, the overlay UI, the
viewer decomposition, physics and navigation, terrain and 3D Tiles, spatial
audio, the test-harness rework, and the consolidation that removed `browser/`,
`shadow/`, `scenegraph/tree/` and the visiting render passes.

**Overall.** The engineering is in good shape and the release is close. Every new
package — `ui/`, `viewer/`, `loaders/gltf/`, `loaders/tiles3d/`, `physics/`,
`nav/`, `audio/`, `scenegraph/terrain/`, `scenegraph/vegetation/` — is
ruff-clean. The removals are guarded by regression tests that assert the modules
are gone. `plans/PROJECT-PLAN.md` tracks partial work honestly rather than
rounding it up to Complete. Documentation coverage is genuinely complete: every
major feature has a page, and of ~75 module paths cited across `docs/`, only two
are wrong.

The findings cluster in two places. **Packaging** is where the release-stopping
problems are, and none of them is visible from the source tree — they only
appear in the built artifact or in a resolver run against PyPI. **One loader
never got the security treatment the others did**: `loaders/resolver.py` is
careful, well-documented work that every glTF module routes through, and
`loaders/tiles3d/` reimplements resolution beside it with none of the
guarantees. That is [B1](#b1).

**Test suite.** 4,646 passed / 2 failed / 7 skipped / 4 xfailed
(`tests/unit`, `-m "not serial and not network"`, 6m01s). Both failures are
`test_gltf_conformance.py::test_view_matches_baseline[Parthenon__cam08]` and
`[Parthenon__cam09]` — the bimodal analytic-sky IBL views documented in
`CLAUDE.md`, which names those two cameras as the worst offenders. Not a
regression and not counted as a finding.

Everything below has a reproduction, a build artifact, or a citation.

---

## Summary of findings

| ID | State | Severity | Area | Finding |
|----|-------|----------|------|---------|
| [B1](#b1) | ✅ Fixed | Blocker | `loaders/tiles3d/fetch.py` | Bypasses `Resolver` entirely: unrestricted SSRF, arbitrary local-file read from a remote tileset, path traversal, no size cap |
| [B2](#b2) | ✅ Fixed | Blocker | build process | A stale `build/` ships every deleted module, including the `pickle`-based `gzpickle` the branch removed for that reason |
| [B3](#b3) | 🔴 Open | Blocker | `pyproject.toml` | Five dependencies cannot be resolved from PyPI; the release has a hard publish ordering |
| [B4](#b4) | ✅ Fixed | Blocker | `README.md` | Titled 2.3.0 with no 3.0.0 changelog entry; it is the PyPI long description |
| [M1](#m1) | ✅ Fixed | Major | `loaders/cc0.py` | Unbounded download and zip-bomb exposure on a shipped entry point; browser-spoofing User-Agent |
| [M2](#m2) | ✅ Fixed | Major | `pyproject.toml` | Four live tools sit under a "deprecated aliases, removed after one release cycle" comment |
| [M3](#m3) | ✅ Fixed | Major | packaging / `bin/gltf_demo.py` | Environment cube maps are not shipped; the docstring says they make `cube` work out of the box |
| [M4](#m4) | ✅ Fixed | Major | `loaders/gltf/accessors.py` | numpy-2-deprecated call form on the normalized-accessor path, with no numpy ceiling |
| [M5](#m5) | ✅ Fixed | Major | `docs/physics.html` | Cites `OpenGLContext/physics/model.py`; the module is `omi_physics/model.py` |
| [M6](#m6) | ✅ Fixed | Major | `docs/terrain.html` | Cites `loaders/tiles3d/cc0.py`; the module is `loaders/cc0.py` |
| [m1](#m1-minor) | ✅ Fixed | minor | `docs/`, `pyopengl/directdocs` | 49 dead `../pydoc/*.html` links from the two primary index pages (pre-existing) |
| [m2](#m2-minor) | ✅ Fixed | minor | `MANIFEST.in` | Four dead entries, each emitting a build warning |
| [m3](#m3-minor) | ✅ Fixed | minor | `setup.py` | Duplicates and conflicts with `pyproject.toml`; classifiers have drifted |
| [m4](#m4-minor) | 🔴 Open | minor | `scenegraph/text/fonts/` | `trim-regular.zip` referenced by nothing and not shipped |
| [m5](#m5-minor) | ✅ Fixed | minor | `passes/_flat.py`, `move/`, `testing/` | Unused imports, two left by the picking split |
| [m6](#m6-minor) | ✅ Fixed | minor | `context.py` | Six deprecated `threading` aliases, one on a per-event path |
| [m7](#m7-minor) | ✅ Fixed | minor | `pyproject.toml`, `MANIFEST.in` | Review bookkeeping (`finding 3.30`, …) in shipped files — forbidden by CLAUDE.md |
| [m8](#m8-minor) | ✅ Fixed | minor | five docstrings | History/confession phrasing, including the exact sentence CLAUDE.md quotes as its Bad example |
| [m9](#m9-minor) | ✅ Fixed | minor | `scripts/parse_teapot_obj.py` | Defaults `--output` to the deleted `teapot_data.py` |
| [m10](#m10-minor) | ✅ Fixed | minor | `scenegraph/audio.py` | VRML `AudioSource.url` reaches the decoder unresolved, unlike the glTF path |
| [m11](#m11-minor) | 🔴 Open | minor | `README.md` | The changelog says `events.tkevents` and `events.fxevents` were removed; both are still in HEAD |
| [m12](#m12-minor) | 🔴 Open | minor | `bin/profile_view.py` | Orphaned: its `oglc-profile` entry point is gone, nothing references it |
| [m13](#m13-minor) | ✅ Fixed | minor | `scenegraph/shadershape.py` | Cannot be imported at all — `create_shader_geometry` does not exist; a suite test is skipped to hide it |

**17 of 20 fixed (2026-08-03)**, each Red/Green. Remaining: **B3** (a publish
ordering, not a code change — the four sibling projects release first), **m1**
(generate `pydoc/` or drop the links) and **m4** (decide whether the bundled font
ships). See [Remediation](#remediation) for what landed.

---

## Blockers

<a name="b1"></a>
### B1 — `loaders/tiles3d/fetch.py` bypasses the resolver entirely

`loaders/resolver.py` enforces same-origin fetching re-checked on every redirect
hop, confines a local document to its own directory, size-caps every resource,
and caches under the per-user app-data directory with `mode=0o700`. Every module
in `loaders/gltf/` routes through it. `loaders/tiles3d/` does not, and its own
`fetch.py` reimplements resolution with none of those properties.

Reproduced directly:

```python
from OpenGLContext.loaders.tiles3d import fetch
fetch.resolve_uri('https://tiles.example.com/a/', '/etc/passwd')
# -> '/etc/passwd'                    then opened with open(uri, 'rb')
fetch.resolve_uri('https://tiles.example.com/a/', 'http://169.254.169.254/latest/meta-data/')
# -> 'http://169.254.169.254/latest/meta-data/'      fetched verbatim
fetch.resolve_uri('/srv/tilesets/city/', '../../../etc/shadow')
# -> '/srv/tilesets/city/../../../etc/shadow'
```

All three values are attacker-controlled `content.uri` entries in a
`tileset.json`, and all three reach `read_bytes` through
`tileset._build_tile` → `_resolve_uri`. So:

* a **remote** tileset can name an absolute local path and have it read, because
  `resolve_uri` returns an absolute path unchanged and `read_bytes` treats
  anything that is not http(s) as a file to open;
* a tileset can name **any host** — `is_url(uri)` is true, so the URL is passed
  to `urlopen` with no origin check at all, and the response is cached to disk.
  This is unrestricted SSRF, including link-local metadata endpoints;
* a **local** tileset can traverse out of its own directory through
  `os.path.join`, which is not checked.

On top of that, `read_bytes` does one unbounded `response.read()` with no size
cap, follows redirects without re-validating them, and creates its cache
directory with default permissions.

The reason this is easy to miss on audit is that `resolver.py`'s module
docstring claims it is "the containment core, kept in one auditable place" for
"any loader that follows external references". That is not true while `tiles3d`
exists. **Fix by routing `tiles3d` through `Resolver`**, not by patching
`fetch.py` guard by guard — the second approach leaves two policies to keep in
step, which is the situation that produced this.

<a name="b2"></a>
### B2 — A stale `build/` reinstates the deleted `gzpickle` in the wheel

A wheel built from the working tree as it stands contains **every module this
branch deleted**: the whole `browser/` package (15 modules + 12 test scripts +
`default_world.wrl`), `shadow/` (6 modules), `scenegraph/tree/` (5 modules),
`teapot_data.py`, and `loaders/gzpickle.py`.

`gzpickle` is the one that matters. It was removed *because* it called
`pickle.load` on `.pkl`/`.pkl.gz` scene data, and
`tests/unit/test_gzpickle_removed.py` asserts the module no longer imports. That
test passes against the source tree while the shipped artifact would put the
module back — so the security fix does not reach users, and the test that is
supposed to hold it cannot see the failure.

Cause is the leftover `build/lib/` staging directory; setuptools copies it
forward without pruning files that no longer exist in the source. Confirmed by
building the same commit in a clean `git worktree`: **0** deleted-module files in
that wheel, 38 in the working-tree one.

`rm -rf build/ *.egg-info` before packaging fixes it. Given the consequence this
belongs in the release procedure as an explicit step, and is worth a check on
the built artifact before upload.

<a name="b3"></a>
### B3 — Five dependencies cannot be resolved from PyPI

| Requirement in `pyproject.toml` | Latest published on PyPI |
|---|---|
| `PyOpenGL>=4.0.0a1` | 3.1.10 |
| `PyOpenGL-accelerate>=4.0.0a1` | 3.1.10 |
| `PyVRML97>=2.3.4b1` | 2.3.1 |
| `TTFQuery>=2.0.1a1` | 1.0.5 |
| `simpleparse>=3.0.0a3` | 2.2.4 |

`pip install OpenGLContext==3.0.0a1` fails at resolution today. The workspace
siblings are at exactly the required versions (pyopengl 4.0.0a2, pyvrml97
2.3.4b1, ttfquery 2.0.1a1, simpleparse 3.0.0a3), so this is a **publish ordering
constraint** rather than a defect in the metadata: those four projects release
first. Worth writing into the release runbook, because four of the five are
pre-release specifiers and a partial publish fails in a way the error message
does not explain. `PyVRML97-accelerate` is already at 2.3.4b1; `PyVRML97` itself
is the one that lags.

<a name="b4"></a>
### B4 — `readme.txt` is still titled 2.3.0

The file opens with `OpenGLContext 2.3.0` and its newest changelog heading is
`2.3.0 (in progress)`, while `OpenGLContext/__init__.py` has
`__version__ = "3.0.0a1"`. `pyproject.toml` sets `readme = "readme.txt"`, so the
PyPI page for 3.0.0a1 would be headed 2.3.0 and would carry no entry describing
the release.

The major bump is well justified — the changelog's own "Removed code that
nothing reached any more" section is a list of withdrawn public API, which is
exactly what a major version is for. The prose just has not been renamed to
claim it.

---

## Major

<a name="m1"></a>
### M1 — `loaders/cc0.py`: unbounded download and zip-bomb exposure

Reachable from the shipped `oglc-terrain` entry point (`bin/terrain_view.py`
lines 194–199) and from `SplatTerrain` (`scenegraph/terrain/splat.py:107`), so
it runs on a normal first use rather than only in development.

`_download` reads the response with an uncapped `.read()` (line 58) and then
reads each zip member with an uncapped `z.read(n)` (line 83). Neither bounds
memory or disk, so a hostile or compromised response expands without limit. The
zip is not slip-vulnerable — output paths are precomputed from a fixed `kinds`
map rather than taken from the archive — which is the right shape; it is only
the sizes that are unbounded.

Two smaller points in the same file:

* `_UA = {"User-Agent": "Mozilla/5.0 (OpenGLContext terrain)"}` spoofs a browser,
  which directly contradicts the deliberate `_user_agent()` policy in
  `resolver.py` and the intent of commit 3308582 ("USER-AGENT Identify ourselves
  properly when downloading resources").
* `cache_dir()` uses `~/.cache` rather than `userpaths.appdatadirectory()`, and
  creates it without `mode=0o700`, unlike the resolver's considered choice.
  `tiles3d/fetch.default_cache_dir()` has the same two properties.

The network access itself is properly disclosed in `docs/terrain.html`, with the
procedural fallback described — that part is fine.

<a name="m2"></a>
### M2 — `pyproject.toml` labels four live tools as deprecated aliases

```toml
oglc-view = "OpenGLContext.bin.view:main"
# Deprecated aliases for oglc-view; removed after one release cycle.
oglc-vrml = "OpenGLContext.bin.vrml_view:main"
oglc-gltf = "OpenGLContext.bin.gltf_view:main"
oglc-terrain = "OpenGLContext.bin.terrain_view:main"
oglc-tiles = "OpenGLContext.bin.tiles_view:main"
oglc-gltf-demo = "OpenGLContext.bin.gltf_demo:main"
oglc-gltf-regression = "OpenGLContext.bin.gltf_regression:main"
oglc-ui-demo = "OpenGLContext.bin.ui_demo:main"
```

Only three are aliases, and each says so in its own module docstring:
`vrml_view`, `gltf_view`, `tiles_view` ("now an alias for `oglc-view`").
`terrain_view` is a distinct tool ("view and walk a streamed 3D-Tiles terrain
world"), as are `gltf_demo`, `gltf_regression` and `ui_demo`.

The comment's scope reads as covering all seven, so whoever executes the removal
next cycle deletes four working commands. Move the comment to cover only the
three aliases, or annotate each line.

<a name="m3"></a>
### M3 — Environment cube maps are not packaged, but the code says they are

`bin/gltf_demo.default_env_prefix` says the faces shipped under the package's
`resources/environment` "are used so the `cube` background works out of the
box". The 18 `.jpg` files are in the repository but are matched by neither
`[tool.setuptools.package-data]` (which lists only `shaders/*.vert|frag|glsl`)
nor `MANIFEST.in` (which includes `OpenGLContext/resources/*.txt` only).
Confirmed absent from a clean-worktree wheel.

Both call sites degrade correctly — `default_env_prefix` and
`gltf_regression._env_prefix` both `return None` when the faces are missing — so
nothing crashes. But every pip install silently takes that path, and the
docstring states the opposite. Either add the files to `package-data` or drop
the claim.

Worth noting what is *not* broken here, since it looks alarming at first: the
font atlases, icons and `phongprecalc.vert`/`phongweights.frag` are all shipped
as generated `.py` modules (`font_atlas_14.py`, `context_icon_png.py`,
`phongprecalc_vert.py`), so their source files being absent from the wheel is
correct. The cube maps are the only data with no module form.

<a name="m4"></a>
### M4 — numpy-2-deprecated call form on the glTF normalized-accessor path

`loaders/gltf/accessors.py:199`:

```python
np.maximum(out, -1.0, out)
```

Passing the output array as a third positional argument is deprecated in numpy
2.x. This is new code from 22aa481, on `_coerce_normalized`, which every model
with quantized attributes or Draco geometry goes through — so it warns on a
common path. `pyproject.toml` requires `numpy>=2.0` with no upper bound, so this
breaks outright when the form is removed. Fix is `out=out`.

<a name="m5"></a>
### M5 — `docs/physics.html` cites a module that does not exist

Line 57 states the OMI structures "live in `OpenGLContext/physics/model.py`".
There is no such file; `OpenGLContext/physics/` holds `debugdraw.py`, `demo.py`,
`gltf_world.py`, `manager.py`, `threaded.py`. The structures are in
`omi_physics/model.py`, and `omi_gltf.py` and `joints.py` — also named in the
same paragraph — are likewise in the sibling package.

Stale from the physics split. `docs/audio.html` cites its sibling package
correctly throughout (`omi_audio/clip.py`, `omi_audio/mixer.py`, …), so this page
simply did not get the same pass.

<a name="m6"></a>
### M6 — `docs/terrain.html` cites the wrong path for the CC0 fetcher

Line 62 cites `loaders/tiles3d/cc0.py`; the module is `loaders/cc0.py`. The
neighbouring citation on line 64 (`loaders/tiles3d/foliage.py`) is correct, so
this is a single slip rather than a systematic error.

---

## Minor

<a name="m1-minor"></a>
### m1 — 49 dead API-reference links from the two primary doc index pages

`documentation.html` and `structure.html` link 49 `../pydoc/*.html` targets;
there is no `pydoc/` directory in the repository. `text.html` adds three more.

Pre-existing and not a regression — this branch net *removed* two such links —
but these are the two pages a new reader lands on, and a first alpha is a
reasonable moment to either generate `pydoc/` or drop the links.

Separately, 196 links in `docs/tutorials/` are site-absolute (`/context/index.html`,
`/context/documentation/tutorial/index.html`). Those resolve on the deployed
site and break for anyone reading the docs from a checkout or an sdist. Also
pre-existing; the tutorials were not touched by this branch.

<a name="m2-minor"></a>
### m2 — `MANIFEST.in` has four dead entries

Each emits a warning on every sdist build:

```
warning: no files found matching 'OpenGLContext/browser/*.wrl'    # package deleted
warning: no files found matching 'pydoc/*.py'                     # directory never existed
warning: no files found matching 'OpenGLContext/tests/resources/*.txt'
warning: no files found matching 'tests/*.frag'
```

<a name="m3-minor"></a>
### m3 — `setup.py` duplicates and conflicts with `pyproject.toml`

It still declares `version`, `license`, `packages`, `classifiers`, `keywords` and
`long_description`, producing `SetuptoolsWarning: 'license' overwritten by
pyproject.toml` on every build. Its classifier list has already drifted from the
authoritative one — it claims `Programming Language :: C`, although a comment in
the same file correctly records that the package is now pure Python and that the
compiled physics lives in `omi_physics`. Reduce to a shim or remove.

<a name="m4-minor"></a>
### m4 — `trim-regular.zip` is referenced by nothing

`OpenGLContext/scenegraph/text/fonts/trim-regular.zip` (added in 2ec126e,
containing `trim.ttf` and `UNLICENSE.txt`) is referenced by no code, no
documentation and no manifest, and is not shipped in the wheel. The zipping is
itself a signal of intent — `MANIFEST.in` carries `global-exclude *.ttf`, which
a bare `.ttf` would have hit — so this looks like a bundled fallback font that
never got wired up.

Either wire it in and surface its licence in `license.txt` (which currently
mentions only FontTools and the `dek_texturesurf` demo among third-party
material), or drop the file.

<a name="m5-minor"></a>
### m5 — Unused imports left by the refactors

`passes/_flat.py` carries eight, of which two — `SelectionFBO` and
`SelectionBufferFBO` — are leftovers from the picking split in 984f332, so they
point at the new module rather than an old one. `move/direct.py` (2),
`move/movementmanager.py` (1), `move/smooth.py` (1) and
`testing/subprocess_runner.py` (1) have the rest. `_flat.py` also has six `B007`
unused loop variables.

The new packages are clean: `ui/`, `viewer/`, `loaders/gltf/`,
`loaders/tiles3d/`, `physics/`, `nav/`, `audio/`, `scenegraph/terrain/` and
`scenegraph/vegetation/` all pass `ruff check` with no findings. The package as a
whole reports 3,339, but that is the documented pre-existing backlog in the older
star-import modules, and the gate is per-path.

<a name="m6-minor"></a>
### m6 — Deprecated `threading` aliases in `context.py`

Six calls across lines 87–965: `threading.currentThread()` (×5),
`.getName()` and `.setName()`. All deprecated since Python 3.10 and warning on
every call; line 87 is on a per-event path. Pre-existing, but `context.py` grew
782 lines in this branch and the classifiers now advertise Python 3.13 and 3.14,
so it is the right time. `current_thread()` and the `name` attribute are the
replacements.

<a name="m7-minor"></a>
### m7 — Review bookkeeping in shipped packaging files

CLAUDE.md forbids bare finding numbers outside `plans/` by name. Four instances,
in the two files a packager reads first:

* `pyproject.toml:3` — `-- finding 3.30`
* `pyproject.toml:15` — `(finding 4.26)`
* `pyproject.toml:18` — `(finding 4.28)`
* `MANIFEST.in:31` — `(finding 4.27)`

The *reasons* in those comments are good and should stay; it is only the
citations that go.

<a name="m8-minor"></a>
### m8 — History and confession phrasing in five docstrings

* `scenegraph/audio.py:14` — "which pyvrml97 has always declared and nothing has
  ever played". This is the sentence CLAUDE.md quotes verbatim as its Bad
  example for the rule.
* `renderoptions.py:6` — "from the environment variable that used to be the only
  way to set it"
* `context.py:471` — "Escape used to be bound straight to `OnQuit`"
* `viewer/adapters/tiles.py:13` — "This is what `oglc-tiles` used to be"
* `ui/debugoverlay.py:23` — "It replaces the frame-rate counter that used to be
  drawn by…"

The `docs/` HTML is clean of this pattern — the documentation review in 0bd1ee6
evidently caught it there — so the remaining work is the docstrings.

<a name="m9-minor"></a>
### m9 — `scripts/parse_teapot_obj.py` writes to a deleted file

Its `--output` default is `OpenGLContext/scenegraph/teapot_data.py`, removed by
this branch (14,869 lines) in favour of the NURBS teapot.

<a name="m10-minor"></a>
### m10 — VRML `AudioSource.url` reaches the decoder unresolved

`scenegraph/audio.py:177` `_fromUrl` passes each `url` entry straight to
`engine.clip(name)` → `ClipCache` → `decode_file(path)`, which opens the path as
given. `omi_audio` is explicit that this is intended — `decode_file`'s docstring
says "it is the caller's job to have decided that the path is one this
application is willing to read" — and the **glTF** path honours that, resolving
through `AudioLibrary` with the loader's own resolver.

The VRML path does not, so a scene file can name an arbitrary local path. Impact
is low: nothing is returned to the document, so it is a decode-succeeds/fails
oracle rather than a read primitive. It is worth closing for consistency, since
it is the one asset path in the scenegraph that does not share the discipline of
the rest.

---

## Areas confirmed clean

Recorded so the next review does not re-derive them:

* **No `pickle`, `eval`, `exec` or `marshal`** in library code. The three
  `__import__` sites are the plug-in registries.
* **PIL's decompression-bomb guard** is left at its default —
  `MAX_IMAGE_PIXELS` is not touched anywhere.
* **glTF resolver adoption is complete**: `loader`, `accessors`, `textures`,
  `meshes`, `materials`, `animation`, `scene`, `draco`, `environment_sky` and
  `samples` all route through `resolver.py`.
* **The removals left no dangling references**, and `tests/unit/test_gzpickle_removed.py`
  and `test_shader_cleanup_sources.py` hold them.
* **All ten console-script entry points** resolve to a module with a `main`.
* **No copyleft contamination**, no hardcoded developer paths, no debug flags
  defaulting on, no stray `.orig`/`.rej`/`.bak` files tracked.
* **Documentation coverage is complete** for gltf, pbr, shadows, instancing,
  particles, physics, terrain, viewer, overlayui, hud, navigation, audio,
  ubershader, renderpasses and text; no orphan pages.

---

<a name="remediation"></a>
## Remediation — 2026-08-03

17 of the 20 findings were fixed in one pass, each Red/Green. Full unit suite
**4,693 passed / 0 failed / 7 skipped** (the bimodal Parthenon views landed on
their matching state this run; they remain bimodal). Ruff and mypy clean on every
file touched; wheel and sdist rebuilt from a clean worktree and passed
`check_release_artifact.py`, with all 18 cube-map faces present and no
`browser/`, `shadow/` or `gzpickle`.

**B1 — 3D Tiles containment.** `loaders/tiles3d/fetch.py` no longer keeps a
policy of its own. `resolve_uri` builds a `Resolver` for the tileset's base and
asks it, so the same-origin rule and the directory confinement are the ones in
`loaders/resolver.py`; `read_bytes` routes a remote payload through
`resolver._fetch_url`, which brings the size cap, the origin-locked redirect
chain, the atomic write and the single-flight lock the tile runtime wanted
anyway. `Resolver.fetch` is deliberately *not* used: it memoises bytes per
document, which for a streaming tileset of thousands of tiles would hold the
whole dataset in RAM. The root URI a user names is still unrestricted, since it
came from the command line and not from a document.
`tests/unit/test_tiles3d_fetch_security.py`, 19 tests: the three reproductions
from [B1](#b1), a symlink that leaves the tileset directory, the cache
permissions, and the same-origin cases that must keep working. One reproduction
turned out to be safe already and its test now records why —
`urljoin` reads a leading `/` as root-relative *on that origin*, so
`/etc/passwd` becomes a same-origin URL rather than a local path; the test
asserts that rather than an exception.

**B2 — stale build staging.** `scripts/check_release_artifact.py` compares an
artifact against the tree it was built from and fails on any member the tree no
longer has. That is the general form of the bug rather than a list of names, so
it catches the whole class. Run against the contaminated wheel it reported 74
files — including seven `OpenGLContext/audio/*` modules left from the
`omi_audio` split that this review had not spotted. `tests/unit/test_release_artifact_check.py`
covers wheels, sdists, generated metadata and root files.

**B4 — the changelog.** Retitled to 3.0.0a1 with an entry for the release: the
glTF loader, PBR, shadow maps, instancing, the single viewer, the overlay UI,
physics and navigation, terrain and 3D Tiles, spatial audio, particles and fog,
the untrusted-asset containment, and the packaging work. The heading records
that the major version is for the removals listed under it. A concurrent session
had converted `readme.txt` to `README.md`; the entry went into that file and its
`pyproject`/`MANIFEST` updates were left alone.

**M1 — cc0 bounds.** The download is capped (`MAX_ARCHIVE_BYTES`) and, because an
archive is compressed, each extracted map is checked against its *declared* size
before extraction (`MAX_MEMBER_BYTES`) rather than expanded and measured
afterwards. The User-Agent is now `resolver._user_agent()`, so the fetcher names
the project instead of impersonating a browser, and the cache moved to
`userpaths.appdatadirectory()` with mode `0o700`.

**M3 — the cube maps.** `resources/environment/*.jpg` is declared as package
data, so all 18 faces ship and `default_env_prefix` finds them. The packaging
test now asserts that every declared pattern matches something and that each of
the three face sets is complete — five faces would render a cube with a hole in
it.

**m3 — setup.py deleted.** Everything in it was superseded by `pyproject.toml`
and it had drifted: an `oglc-profile` entry point removed in b9d021d, a
`Programming Language :: C` classifier for a pure-Python package, and a
long description describing a Tkinter context that no longer exists. Nothing
invoked it; the wheel and sdist build unchanged without it.

**m9 — parse_teapot_obj.py deleted** rather than repointed. It generated the
triangle-array `teapot_data.py` that this branch removed in favour of the
hand-committed Bézier data in `teapot_nurbs_data.py`, from an OBJ file that is
not in the repository, and nothing referenced it.

**m10 — VRML audio.** `AudioSource._fromUrl` resolves each `url` entry against
the document's own `baseURI` (the idiom `ImageTexture` already uses) before the
name reaches the decoder, so a scene may only play audio under its own directory
or, over http(s), from its own origin. An entry outside those bounds is skipped
with a warning and the next is tried. A source built in application code has no
document behind it and stays unconfined.

**Two test files needed updating**, both because a contract deliberately changed
rather than to accommodate a weaker assertion. `test_cc0_extra.py`'s response
stub returned its whole payload from every `read()`, which was fine while the
module read once and wrong once it streams in chunks; it now drains like a real
response. The same file's cache-location tests moved from `XDG_CACHE_HOME` to
`appdatadirectory`, and an autouse fixture now redirects the cache so no test in
it writes to the real per-user directory.

**Documentation updated in the same pass:** `docs/terrain.html` gains a "What a
tileset is allowed to reach" section for the [B1](#b1) policy and the cc0 caps,
`docs/audio.html` gains the [m10](#m10-minor) confinement rule,
`docs/physics.html` and `docs/terrain.html` have their wrong module paths
corrected, and `loaders/resolver.py`'s module docstring now names both callers
so its "one auditable place" claim is checkable.

### m1 fixed — directdoc repaired and the API reference regenerated

<a name="m1-investigation"></a>
**Outcome: 3,124 modules documented, and 43 of the 44 `../pydoc/` links in
`docs/` now resolve** (the last, `wxcontext`, needs wxPython installed).
OpenGLContext coverage went from 31% to **97%** — the ten gaps are the wx, WGL
and FOX modules that cannot import without those toolkits, plus
[m13](#m13-minor). The six fixes below were applied to `pyopengl/directdocs`;
`docs/structure.html` and `docs/vrml97.html` had five links repointed at modules
that had moved into `move/`. The investigation that led here follows.

The generator behind the `pydoc/*.html` links is
`directdocs/dumbpydoc.py`, on the `directdocs` branch of the **pyopengl** repo
(merged to `develop` in 2019 by `5430eeec`, "Move directdocs to a sub-directory
for merging to mainline"). Its module list already names `OpenGLContext` and
`OpenGLContext_qt`, so nothing needs porting. It was run against the current tree
to find out whether it would close this finding. It does not.

**It needs four Python 3 fixes before it runs at all** — all in `pyopengl`, none
in this repository:

| Location | Breakage |
|---|---|
| `dumbpydoc.py:31` | the URL-map pickle is opened in text mode, and relative to the cwd rather than the module |
| `templates/master.html:6-7` | implicit relative imports (`from dumbpydoc import …`) |
| `templates/module.html:60` | an unclosed `<br>`; Genshi parses the template as XML |
| `model.py:290` | `inspect.getargspec`, removed in Python 3.11 |

`model.py` also drops into `pdb.set_trace()` from an exception handler, which
would hang an unattended documentation build rather than fail it.

**With those fixed it renders all twelve projects** — the eight it already knew
about plus `omi_audio`, `omi_physics`, `openglcontext_forest_demo` and
`twig_bb` — producing 2,714 pages. **But it documents only 31% of
OpenGLContext, and the new code least of all:**

| Package | modules | documented |
|---|---:|---:|
| `OpenGLContext` (all) | 344 | 108 (31%) |
| `move/` | 16 | 2 (12%) |
| `passes/` | 24 | 4 (17%) |
| `scenegraph/` | 99 | 21 (21%) |
| `ui/` | 21 | 5 (24%) |
| `viewer/` | 21 | 6 (29%) |
| `loaders/gltf/` | 13 | 6 (46%) |
| `loaders/tiles3d/` | 19 | 9 (47%) |
| `omi_audio` | 11 | 3 (27%) |
| `omi_physics` | 24 | 5 (21%) |
| `twig_bb` | 55 | 9 (16%) |

`OpenGLContext.context` itself is not among them. The cause is structural rather
than a matter of configuration: `PyModule.inspect()` classifies the *attributes of
an imported module object* and recurses into whatever is already a
`types.ModuleType` there. There is no `pkgutil.walk_packages` and no filesystem
walk, so a module is documented only if some `__init__` has imported it. A
codebase that reaches its parts through plugin registries and deferred imports —
which is how the backends, node types and loaders here are found — is largely
invisible to it.

The discovery limit is not structural, though: `PyModule` resolves its name with
`__import__`, so any importable dotted name can simply be handed to `render()`.
`dumbpydoc` now enumerates each project with `pkgutil.walk_packages` and renders
the names directly (`package_modules`, `render_projects`), with `render(recurse=False)`
while it walks the explicit list so pages are not re-rendered once per importing
parent. A subpackage that will not import is warned about and skipped rather than
being fatal.

**Applied to `pyopengl/directdocs`:**

| File | Fix |
|---|---|
| `dumbpydoc.py` | pickle opened binary and relative to the module, not the cwd |
| `dumbpydoc.py` | `types.UnboundMethodType` dropped (py3 unbound methods are plain functions) |
| `dumbpydoc.py` | `package_modules`/`render_projects`; `PROJECTS` extended with `omi_audio`, `omi_physics`, `openglcontext_forest_demo`, `twig_bb` |
| `model.py` | `inspect.getfullargspec`, keeping keyword-only arguments |
| `model.py` | `pdb.set_trace()` in an exception handler replaced with a warning |
| `templates/master.html` | package-qualified imports |
| `templates/module.html` | `<br>` closed, since Genshi parses the template as XML |
| `templates/module.html` | base classes separated by commas — the `py:for` emitted `(Auditory Children Node)` |
| `dumbmarkup.py` | a run of `=` is a title only on a *single line*; an opening-and-closing pair is a reStructuredText table border, and swallowing it into an `<h1>` lost both the rows and the columns |
| `dumbmarkup.py` | a block whose continuation lines are indented keeps its own spacing (new `Preformatted`, rendered into a `pre`), so tables and aligned name/description columns survive HTML whitespace collapsing |
| `dumbmarkup.py` | a link target has to look like one (scheme, path, anchor or filename); `[--help for the tunable knobs]` was becoming an `<a href="--help">` and eating the text around it |

The markup changes also remove pre-existing false links in the shader tutorials,
which share `dumbmarkup`: `[%(LIGHT_COUNT)d * %(LIGHT_SIZE)d]` and `[j +
%(POSITION)d]` were both being read as `[target text]`. The tutorials' real link
forms — `[shader_2.py-screen-0001.png Screenshot]`, `[http://… OpenGLContext]` —
still match.

`types.UnboundMethodType` was the expensive one: it made every module containing
a class render to nothing, which is why the first measured coverage was 31%
across the board rather than obviously broken.

Run it with:

```bash
cd pyopengl && python -m directdocs.dumbpydoc      # writes directdocs/pydoc/
```

Two things remain a deployment question rather than a code one: the run must
happen somewhere the optional toolkits are installed if the wx/WGL pages are
wanted, and `upload-pydoc.sh` puts the output under
`htdocs/documentation/pydoc/`, which has to be where `../pydoc/` resolves from
the published `docs/`.

### Still open

* **[B3](#b3)** — publish `PyOpenGL` 4.0.0a1+, `PyOpenGL-accelerate`,
  `PyVRML97` 2.3.4b1, `TTFQuery` 2.0.1a1 and `simpleparse` 3.0.0a3 before
  OpenGLContext 3.0.0a1. No change to this repository.
* **[m1](#m1-minor)** — **fixed 2026-08-03**; see above. The remaining work is a
  deployment choice, not a code change.
* **[m4](#m4-minor)** — **fixed 2026-08-03**: `trim-regular.zip` (with `trim.ttf`
  and `UNLICENSE.txt`) deleted as unreferenced. The font-atlas generator was also
  made to refuse to substitute a different font when DejaVu is absent, since it
  would otherwise emit DejaVu's licence over another font's glyphs; the licence
  notice is now derived from the font actually used.
* **[m11](#m11-minor)**, **[m12](#m12-minor)** — found while measuring m1.

<a name="m11-minor"></a>
### m11 — the changelog claims a removal that did not happen

`README.md` lists `events.tkevents` and `events.fxevents` among the modules
removed ("no Tk or FOX context exists to reach them"). Both are still in `HEAD`,
and `git log --diff-filter=D` over the branch shows neither was ever deleted.
Either finish the removal or drop them from the list; as it stands the release
notes describe a package that does not match the wheel.

<a name="m13-minor"></a>
### m13 — `scenegraph/shadershape.py` cannot be imported

```
ImportError: cannot import name 'create_shader_geometry'
             from 'OpenGLContext.scenegraph.shadergeometry'
```

No such function exists anywhere in the tree. The module ships in the wheel and
raises for anyone who imports it. `tests/unit/test_shaderpass.py:349` carries
`@unittest.skip("shadershape module has broken import - pending implementation")`,
so the suite records the breakage rather than reporting it — it is one of the
seven skips in a full run. Found by the documentation build, which imports every
module and so cannot skip past it.

**Fixed 2026-08-03: module and test deleted.** Nothing imported it — a
case-insensitive sweep of the whole workspace found it only in that skipped test
and in two plan documents. It was not registered as a node type, and
`Shape._render_shader` ([shape.py:91](../OpenGLContext/scenegraph/shape.py#L91))
already provides what it was meant to add.

This was not a new finding. `plans/CODE-REVIEW-2026-07-13.md` §4a raised it in
July — *"dead with a broken import; delete it and its skipped test"* — and it was
marked ⬜ Backlog and shipped anyway. The gap worth noting is not the module but
that a HIGH finding survived a release cycle in a backlog state; a skipped test
is not a record anything acts on.

**`addTransparent`, raised alongside it in the same July review, is fixed and
needs nothing.** It was then a silent no-op, so a shape statically classed opaque
but found transparent at render time was dropped for the frame. It now records
`(matrix, renderPath, shape)` and `_renderDeferredTransparent` replays it, drained
from both `_flat.renderTransparent` and `flatcompat.renderTransparent`, with five
tests in `tests/unit/test_deferred_transparent.py`.

Its use of `glLoadMatrixf` — meaningless in a core profile — is correct here
rather than a latent core-profile bug: `Shape.Render` returns into
`_render_shader` before reaching the `addTransparent` call, so the deferral is
only ever entered on the legacy path, where fixed-function matrix calls are
available. The shader path classifies transparency in the pass itself
(`_flat.py:617`) rather than discovering it mid-draw.

<a name="m12-minor"></a>
### m12 — `bin/profile_view.py` is orphaned

Its `oglc-profile` console script is gone (it survived only in the `setup.py`
deleted under [m3](#m3-minor)), `pyproject.toml` does not declare it, and nothing
imports it.

---

## What is left before the release

1. **[B3](#b3)** — publish the four sibling projects, then confirm
   `pip install OpenGLContext==3.0.0a1` resolves in a clean environment.
2. Build with `python -m build`, and run
   `python scripts/check_release_artifact.py dist/*.whl dist/*.tar.gz` on the
   result. That is now the guard against [B2](#b2) recurring.
3. Decide **[m1](#m1-minor)** and **[m4](#m4-minor)** — both are choices rather
   than defects.
