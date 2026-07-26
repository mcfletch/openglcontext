# Code review — OpenGLContext, 8e7703a..HEAD (2026-07-26)

**Scope.** The twelve commits from `8e7703a` to `991236e`: 288 files, +32,560/−2,202.
The substance is four new subsystems — the overlay UI (`OpenGLContext/ui/`,
~4,300 lines), declared movement modes (`OpenGLContext/move/modes.py`,
`navigation.py`, `bindingstore.py`), the rendering-options indirection
(`renderoptions.py` + `ContextDefinition` fields), and the input sampler
(`events/inputstate.py`) — plus teapot instancing, a large test-suite expansion
and a substantial documentation refresh.

**Overall.** This is good work. The design documents are unusually honest, the
docstrings explain *why* rather than *what*, `ui/` is ruff-clean, the widget
tests use real objects rather than mocks (0 uses of `Mock` across 14 UI test
files, 505 tests), and the separation of measurement / layout / hit-testing /
drawing is exactly right — it is what makes the whole overlay testable without a
GL context. The `plans/OVERLAY-UI.md` "Decisions" section is a model of how to
record a design.

It is not yet mergeable. Six findings are blocking, and one of them —
[B1](#blocker-1) — is the project's own guidelines being overridden by name. The
recurring theme across the rest is **a docstring that describes behaviour the
code does not have** ([M2](#major-2), [M3](#major-3), [M4](#major-4), [M9](#major-9)) and **a
feature that is half-wired and silently does nothing** ([B5](#blocker-5), [M10](#major-10),
[m5](#minor-5), [m10](#minor-10)). Both are worse than an outright bug in a codebase used
as teaching material, because a reader trusts the prose.

Everything below has an objective test, a reproduction, or a citation. Where a
finding is a judgement call it says so.

---

## Summary of findings

| ID | State | Severity | Area | Finding |
|----|-------|----------|------|---------|
| [B1](#blocker-1) | ✅ Fixed | Blocker | `pyproject.toml` | mypy `warn_return_any` override widened from `physics.*` to the whole package — forbidden by name in CLAUDE.md; hides 22 real errors in the new code |
| [B2](#blocker-2) | ✅ Fixed | Blocker | `tests/unit/test_gltf_conformance.py` | Suite is red at HEAD: 6 Parthenon views regress, up to 9.94% of pixels against a 2% tolerance |
| [B3](#blocker-3) | ✅ Fixed | Blocker | `tests/unit`, `passes/pbrpass.py` | New instancing test passes alone and fails in the full run; root cause is a memoised module global left dirty by another test |
| [B4](#blocker-4) | ✅ Fixed | Blocker | `ui/widgets.py` | `Slider` hit-tests against different geometry from the one it paints; the maximum cannot be reached with the pointer |
| [B5](#blocker-5) | ✅ Fixed | Blocker | `ui/generate.py` | A generated editor for an unhinted numeric field raises `TypeError` on the first keystroke |
| [B6](#blocker-6) | ✅ Fixed | Blocker | `pyproject.toml`, `CLAUDE.md` | mypy cannot run at all as configured; the mandated type gate is inoperative and the documented command errors |
| [M1](#major-1) | ✅ Fixed | Major | `ui/overlay.py` | `OverlayStack.clear()` loops forever on an already-closed panel |
| [M2](#major-2) | ✅ Fixed | Major | `ui/console.py` | `_follow()` does exactly what its docstring says it must never do |
| [M3](#major-3) | ✅ Fixed | Major | `ui/console.py` | `ConsoleLogHandler` retains the whole panel tree; the docstring claims the opposite |
| [M4](#major-4) | ✅ Fixed | Major | `ui/draw.py` | `end()` claims to restore GL state; it forces a fixed state and unbinds the caller's program |
| [M5](#major-5) | ✅ Fixed | Major | `ui/draw.py` | `close()` leaks the GL program |
| [M6](#major-6) | ✅ Fixed | Major | `events/inputstate.py`, `move/modes.py` | Modifiers are sampled at key-press only, so `Ctrl`+arrow depends on the order the two were pressed |
| [M7](#major-7) | ✅ Fixed | Major | `move/bindingstore.py` | Bindings are saved non-atomically on every rebind |
| [M8](#major-8) | ✅ Fixed | Major | `move/bindingstore.py` | Loading is forgiving of missing keys but not of wrong types, in a file the docstring invites hand-editing |
| [M9](#major-9) | ✅ Fixed | Major | `passes/flatcore.py`, `renderoptions.py` | Three different environment-read lifetimes in one class, and a docstring that contradicts the one beside it |
| [M10](#major-10) | ✅ Fixed | Major | `ui/generate.py` | A generated `KeyCapture` is unbound, so key edits on a generated page are silently discarded |
| [M11](#major-11) | ✅ Fixed | Major | `scenegraph/teapot.py`, `pbrmesh.py` | Geometry writes the pass's private GL-state cache; `depend_fields` disagrees with its documented API |
| [M12](#major-12) | ✅ Fixed | Major | `move/viewplatformmixin.py` | ~15 new methods with no type annotations, against the "all new code annotated" rule |
| [M13](#major-13) | ✅ Fixed | Major | `move/viewplatformmixin.py`, `navigation.py` | Rebuilding the navigation manager silently resets the player's chosen movement mode |
| [M14](#major-14) | ✅ Fixed | Major | `renderoptions.py` | `number()` is declared `-> float` and returns the raw field value |
| [m1](#minor-1) | ✅ Fixed | Minor | `ui/skin.py` + 4 modules | `Skin._image()` is private and called from five other modules |
| [m2](#minor-2) | ✅ Fixed | Minor | `ui/layout.py`, `ui/panel.py` | Full tree walks per frame and per keystroke, against the plan's own "layout on change, not per frame" |
| [m3](#minor-3) | ✅ Fixed | Minor | `ui/session.py`, `ui/settings.py` | `dirty` is a deep tree comparison run on every field write |
| [m4](#minor-4) | ✅ Fixed | Minor | `ui/session.py` | `SettingsSession` has no teardown; watches are dropped only by `revert()` |
| [m5](#minor-5) | ✅ Fixed | Minor | `ui/widgets.py` | Click-to-place-caret is half built: `_pending_caret` is dead and `caret_from` has no production caller |
| [m6](#minor-6) | ✅ Fixed | Minor | `ui/panel.py` | `Panel.viewport` is assigned every layout and never read |
| [m7](#minor-7) | ✅ Fixed | Minor | `ui/widgets.py` | `Slider.display_value(metrics)` takes an argument it never uses |
| [m8](#minor-8) | ✅ Fixed | Minor | `ui/widgets.py` | `Select.release` calls `super().activate()`, which resolves to the method it is already in |
| [m9](#minor-9) | ✅ Fixed | Minor | `ui/session.py` | Three of the four `_INTERNAL` entries are unreachable |
| [m10](#minor-10) | ✅ Fixed | Minor | `contextdefinition.py` | `UI_HINTS` for `profile`/`title` are unreachable and the `restart` hint is never consumed |
| [m11](#minor-11) | ✅ Fixed | Minor | `ui/draw.py` | `quad()` changes batch state before its own early-out, forcing empty flushes |
| [m12](#minor-12) | ✅ Fixed | Minor | `ui/draw.py`, `ui/skin.py` | Nine-slice tries only the first URL and cannot open the `file:` URL its docstring promises |
| [m13](#minor-13) | ✅ Fixed | Minor | `move/modes.py` | `MovementMode._turn` reads a field only its subclass declares |
| [m14](#minor-14) | ✅ Fixed | Minor | `move/navigation.py` | `_selectable()` carries a dead condition that costs a call per frame |
| [m15](#minor-15) | ✅ Fixed | Minor | `hud.py` | `distribute()` mutates its caller's list and does not say so |
| [m16](#minor-16) | ✅ Fixed | Minor | `hud.py` | A `Row`'s children are measured with no available width, so wrapped text in a row measures against a stale rectangle |
| [m17](#minor-17) | ✅ Fixed | Minor | `ui/layout.py` | `Grid` overflows its rectangle rather than shrinking when the columns do not fit |
| [m18](#minor-18) | ✅ Fixed | Minor | `ui/console.py` | `ConsolePanel.paint` is a copy of `Panel.paint` with one colour changed |
| [m19](#minor-19) | ✅ Fixed | Minor | `renderoptions.py` | A misspelt boolean environment variable is silently ignored; `''` means different things to `env_flag` and `env_choice` |
| [m20](#minor-20) | ✅ Fixed | Minor | `ui/overlay.py`, `bin/ui_demo.py` | `pragma: no cover - GL` on the overlay's only draw entry point, in a container that has real GL |
| [m21](#minor-21) | ✅ Fixed | Minor | `ui/bindings.py` | A module-level `gettext` call runs before any locale can be set, and no catalogue exists |
| [m22](#minor-22) | ✅ Fixed | Minor | `ui/scroll.py` | Every child is measured twice per layout, at two different widths |
| [m23](#minor-23) | ✅ Fixed | Minor | `ui/generate.py` | `label_for` lower-cases acronyms: "IBL" becomes "Ibl" |
| [m24](#minor-24) | ✅ Fixed | Minor | `ui/skin.py` | `DEFAULT_SKIN` is a process-wide mutable singleton handed out to every panel |
| [m25](#minor-25) | ✅ Fixed | Minor | `glfwcontext.py` | `contextDefinition` is assigned before `Context.__init__` is given the same object |
| [m26](#minor-26) | ✅ Fixed | Nit | `ui/console.py` | `# noqa: BLE001` is inert under the configured rule set |

Counts: 6 blocking, 14 major, 25 minor/nit.

## Remediation, 2026-07-26

**All 45 fixed**, each with a test that was red first. The full unit suite is
green: **3333 passed, 6 skipped, 4 xfailed, 0 failures** in 6m06s.

Five fixes turned out to be larger than the finding described, and are worth
naming because the finding understated them:

- **[B3](#blocker-3) was two bugs, not one.** The memoised
  `renderer_is_pbr` was the trigger the review found; underneath it,
  `ContextDefinition.profile` read `OPENGLCONTEXT_PROFILE` at **class-definition
  time**, so whichever module imported `contextdefinition` first froze the
  profile for the session. That is the same import-time-read defect as
  `INSTANCE_MIN` in [M9](#major-9), and it is what actually made the instancing
  test order-dependent. The three defaults are now lazy. A third layer —
  test modules setting `os.environ` at import, which the subprocess-rendering
  shadow tests inherit — is handled by restoring the renderer variables around
  every test in `tests/unit/conftest.py`. The `-k "instanc or pbr or shadow or
  flat or context or profile"` selection went from **9 failures to 0**; five of
  those nine pre-dated this change set.
- **[B2](#blocker-2) had the same root cause, and the review was wrong about
  it.** The review could not attribute the six Parthenon conformance failures
  and left the question open, leaning towards a rendering change in this range.
  It was neither: the capture subprocess asks for `OPENGLCONTEXT_PROFILE=core`,
  but `ContextDefinition.profile` had already frozen its default at import, so
  every one of those views was being rendered in the **compatibility** profile
  and compared against a core-profile baseline. Making the default lazy fixes
  all twenty views, and the run drops from 269s to 14s because the fast path is
  now actually taken. No baseline needed re-blessing, and nothing in the
  renderer was wrong.
- **[B4](#blocker-4) exposed a second defect.** Fixing the hit-test geometry
  showed the track *changing length as the value was dragged*, because the room
  kept for the printed value was sized from the current value's text. It is now
  sized for the widest number the slider can ever show.
- **[M9](#major-9) reached further than `flatcore`.** `INSTANCE_MIN` was a
  class attribute assigned at import in two passes and referenced from a third;
  it is now `instanceMinimum()` on the pass, with the memo in
  `renderoptions.env_flag_once` / `env_number_once` and a `reset_env_cache()`
  for tests.
- **[M11.2](#major-11) was not a defect.** The review flagged
  `depend_fields=('size', 'lid')` as disagreeing with the documented
  field-object form. Tested directly: `CacheHolder.depend` resolves a string
  through `protofunctions.getField`, the cache does drop on `size`/`lid` and
  does not on an unrelated field. The names were right; **CLAUDE.md's example
  was the thing out of step**, and it has been corrected rather than the code.

Two findings were fixed in a different way from the one suggested, after the
suggestion turned out to be worse:

- **[m3](#minor-3)** proposed replacing the deep comparison behind `dirty` with
  a touched-flag. A flag cannot answer "the value was set back by hand", which
  an existing test pins and which is the right behaviour for an Apply button.
  The comparison is kept and **memoised until the next edit** instead.
- **[m1](#minor-1)** proposed renaming `Skin._image`. Normalising in
  `OverlayRenderer.frame`, which already accepted `image=None`, removed all ten
  call sites and the method with them.

One correction to the review's own reasoning: it treated
[B2](#blocker-2), [B3](#blocker-3) and [M9](#major-9) as three separate
findings. They are one — **an environment variable read before anything can set
it** — wearing three faces: a memo with no reset, a class attribute assigned at
import, and a field default evaluated at class-definition time. Fixing the
first two led to the third, and the third was the one that mattered most.

The documentation changed with the code: `docs/overlayui.html` (deferred binding
save, `NumberField`, the console's follow rule and handler lifetime),
`plans/OVERLAY-UI.md` (stage 5, decision 2, and two new decisions on measurement),
and `CLAUDE.md` (the environment-read rule, the per-path mypy gate and its known
backlog, the `depend_fields` example, the widget list).

---

## Blockers

<a id="blocker-1"></a>

### B1— The mypy override was widened to the whole package

**Area:** `pyproject.toml`

`[[tool.mypy.overrides]]` changed from `module = "OpenGLContext.physics.*"` to
`module = "OpenGLContext.*"`, turning `warn_return_any` off for every module in
the project.

[openglcontext/CLAUDE.md](../CLAUDE.md) says, in the list of requirements for
new code: *"No new `# type: ignore` without a reason, and **no widening the
`physics.*` override to escape a real error**."* This change does the named
thing. The comment immediately above the override still reads *"Turn it off for
that package only; every other check … stays on"*, which is now false — so the
config also misdescribes itself.

It is not cosmetic. Narrowing the override back and re-running mypy over the new
modules alone produces **22 errors in 8 files**:

```
$ mypy --config-file <override narrowed to physics.*> --python-version 3.12 \
      --follow-imports=silent OpenGLContext/ui/ OpenGLContext/move/modes.py \
      OpenGLContext/move/navigation.py OpenGLContext/move/bindingstore.py \
      OpenGLContext/renderoptions.py
OpenGLContext/ui/widgets.py:507: error: Returning Any from function declared to return "str"
OpenGLContext/ui/widgets.py:625: error: Returning Any from function declared to return "int"
OpenGLContext/ui/scroll.py:198: error: Returning Any from function declared to return "Widget | None"
OpenGLContext/ui/panel.py:428: error: Returning Any from function declared to return "Widget | None"
OpenGLContext/ui/overlay.py:325: error: Returning Any from function declared to return "bool"
OpenGLContext/ui/overlay.py:325: note: Error code "no-any-return" not covered by "type: ignore[misc]"
...
Found 22 errors in 8 files (checked 20 source files)
```

Several are real: `Panel.primary()` and `ScrollViewport.widget_at()` both
promise `Widget | None` and return whatever `walk()`/`layoutChildren()` yielded,
which is `Any` — precisely the class of error the flag exists to catch, in
precisely the code that most needs it (a hit-test that returns the wrong kind of
object fails silently at a click, not at import).

**Remediation.** Restore `module = "OpenGLContext.physics.*"`. Fix the 22
errors: most are one `str(...)`, `int(...)` or `bool(...)` at the return, and
the two `walk()`-derived ones want `GUINode.walk()` annotated as
`Iterator['GUINode']` (see [M12](#major-12) and [m15](#minor-15) — `walk()` is the one
method in `hud.py` with no annotation, which is why they are `Any`). If some
module genuinely cannot be made clean in this piece of work, narrow the override
to *that* module with a comment naming what is left, so the exception is visible
and finite rather than package-wide and permanent.

---

<a id="blocker-2"></a>

### B2— The test suite is red at HEAD

**Area:** `tests/unit/test_gltf_conformance.py`, rendering

Six of the ten Parthenon conformance views fail, reproducibly, in a run of just
that file (so this is not an ordering artefact):

```
$ pytest tests/unit/test_gltf_conformance.py tests/unit/test_gltf_demo_cli.py -q
FAILED test_view_matches_baseline[Parthenon__cam01]
FAILED test_view_matches_baseline[Parthenon__cam02]
FAILED test_view_matches_baseline[Parthenon__cam03]
FAILED test_view_matches_baseline[Parthenon__cam04]
FAILED test_view_matches_baseline[Parthenon__cam08]
FAILED test_view_matches_baseline[Parthenon__cam09]
6 failed, 338 passed, 4 xfailed in 269.20s
E   AssertionError: Parthenon__cam08 regressed vs baseline:
    Max diff: 47.0/255, Mean diff: 2.45, Pixels different: 57247/576000 (9.94%)
```

Nearly 10% of pixels differ against a 2% tolerance. That is well past
rasterisation noise.

**What this review did and did not establish.** `test_gltf_conformance.py` is
unchanged in this range and its baselines were blessed on 17 July; four of the
twelve commits post-date that, so a rendering change in this range is the
leading hypothesis. Attribution to a specific commit was *not* established: a
worktree at `8e7703a` cannot render these views at all (the Parthenon baselines
do not resolve there), so a straight before/after comparison was not available.
`cam00` passing while `cam01`–`cam04`, `cam08`, `cam09` fail suggests a
view-dependent term — ambient or environment lighting — rather than a geometry
or material change.

[openglcontext/CLAUDE.md](../CLAUDE.md) is unambiguous that this blocks
regardless of who caused it: *"It does not matter who broke a test or when — if
it is red, it is your job to make it green before you are done."*

**Remediation.** Bisect the six views across the twelve commits with
`oglc-gltf-regression`. Two outcomes, and the work differs:

- **A real regression.** Fix it, and add the failing view to the set the change
  is validated against.
- **An intended visual change** (e.g. from the `iblIntensity` / `renderoptions`
  refactor changing an effective default). Re-bless with
  `oglc-gltf-regression --bless --only Parthenon`, and say in the commit message
  what changed and why the new image is the right one. A silent re-bless is the
  one outcome to avoid.

Separately, the gate itself is fragile in a way worth fixing while you are in
it: it depends on two out-of-repo trees (`../parthenon` for the model,
`../reference-images/gltf_baseline` for the images) with no pinned revision, so
either can drift and redden this repo's suite with no local change. Record the
model's content hash beside the baselines and **skip with a loud message**
("baseline blessed against parthenon.glb sha256:… , found …") rather than fail,
so a stale sibling checkout is distinguishable from a rendering regression at a
glance.

---

<a id="blocker-3"></a>

### B3— A new test passes alone and fails in the full run

**Area:** `tests/unit/test_passes_render_gl.py` (new in `49abc98`),
`OpenGLContext/passes/pbrpass.py`

```
$ pytest tests/unit/test_passes_render_gl.py::TestInstancedPBRRender::\
test_shared_geometry_collapses_to_instanced_draw
1 passed in 0.34s

$ pytest tests/unit/test_pbr_misc.py tests/unit/test_passes_render_gl.py
FAILED ...::test_shared_geometry_collapses_to_instanced_draw
E   assert 0 >= 1
E    +  where 0 = <_Rendered ...>.instanced_calls
1 failed, 5 passed
```

The failing test is **new in this change set**. CLAUDE.md again: *"'It passes in
isolation' is not passing — if a test only fails in the full run, that is a real
test-isolation bug to fix."*

**Root cause, traced.** `pbrpass.renderer_is_pbr()` memoises into a module
global with no reset hook:

```python
# passes/pbrpass.py:785
_renderer_is_pbr_cache: Optional[bool] = None

def renderer_is_pbr() -> bool:
    global _renderer_is_pbr_cache
    if _renderer_is_pbr_cache is None:
        _renderer_is_pbr_cache = (
            os.environ.get('OPENGLCONTEXT_RENDERER', '').strip().lower() == 'pbr')
    return _renderer_is_pbr_cache
```

`tests/unit/test_pbr_misc.py::TestRendererEnvCached::test_reflects_env_value`
assigns that global directly and then calls the function under a monkeypatched
`OPENGLCONTEXT_RENDERER='other'`. `monkeypatch` restores the environment
variable; it does not restore the module global. Confirmed:

```
$ python -c "..."
after other: False
env restored, still cached: False
```

Every later test in the session therefore sees `renderer_is_pbr() == False`, the
PBR pass never runs, and the instanced draw the new test counts never happens.

The cache and `test_pbr_misc.py` both pre-date `8e7703a`; the *test that trips
over them* is yours, which is what makes it this change's problem to fix.

**Remediation.** Two halves, both small:

1. Give the memo a public reset — `pbrpass.reset_renderer_cache()` — and call it
   from an `autouse` fixture in `tests/unit/conftest.py`. A process-lifetime
   memo of an environment variable needs an escape hatch for exactly this
   reason, and adding one is cheaper than auditing every future test.
2. In `test_pbr_misc.py`, set the global with
   `monkeypatch.setattr(pbrpass, '_renderer_is_pbr_cache', None)` so pytest
   restores it. A bare assignment to another module's global inside a test is
   the bug; `monkeypatch` already knows how to undo it.

Then re-run the whole `tests/unit` tree and confirm it is green. Note that the
run used for this review did not finish inside 50 minutes; a suite that cannot
be run to completion in one sitting is a suite whose isolation bugs accumulate
unseen. Consider marking the GL-heavy files so a `-m "not slow"` pass gives a
fast signal.

---

<a id="blocker-4"></a>

### B4— `Slider` hit-tests against geometry it does not paint

**Area:** `OpenGLContext/ui/widgets.py:604-724`

`Slider.track_rect(metrics=None)` reserves room at the right for the printed
value *only when it is given metrics*:

```python
def track_rect(self, metrics: Any = None) -> Rect:
    reserved = self.value_width(metrics) if metrics is not None else 0
    ...
    return Rect(self.rect.x + half, ..., max(1, self.rect.width - reserved - half * 2), thickness)
```

`paint()` passes metrics (line 713). The pointer path does not: `press()` and
`drag()` both call `self._fraction_at(x)` with no metrics (lines 679, 684), so
the value is computed against a track that is `value_width` pixels wider than
the one on screen. Measured:

```
painted track : Rect(x=7, y=9, width=170, height=6)
hit-test track: Rect(x=7, y=9, width=186, height=6)
click at right end of drawn track -> 9.086   (expected 10.0)
click at centre of drawn track    -> 4.570   (expected 5.0)
```

Consequences a player sees: the maximum is unreachable with the pointer, the
thumb does not sit under the cursor, and the error grows with the width of the
printed value — so a slider reading `"12.50 m/s"` is further out than one
reading `"3"`. The thumb also *paints* in one place and *responds* in another,
which is the failure mode `plans/OVERLAY-UI.md` set out to avoid when it said
"every widget has a rectangle, measured at layout time".

**Why 88 widget tests did not catch it.** They call the same defaulted helper
the buggy path calls:

```python
# tests/unit/test_ui_widgets.py:370
track = slider.track_rect()          # no metrics -- the *hit-test* geometry
slider.press(*slider.thumb_rect().centre)
slider.drag(track.right, track.y + 1)
```

The assertions are self-consistent with the defect, so they hold either way.
This is worth naming on its own: a helper with an optional argument that changes
its answer is a helper a test cannot pin.

**Remediation.**

1. Remove the default. Make `metrics` a required argument of `track_rect`,
   `thumb_rect`, `value_width` and `_fraction_at`; the geometry is meaningless
   without it, and a required argument makes the pointer path's omission a
   `TypeError` at import-test time rather than a silent 9% error.
2. Give `Slider` the metrics it needs at press time. The cleanest route is to
   store the metrics the widget was last arranged with — `arrange()` already
   receives them — as `self._metrics`, and have all four helpers read it. That
   also removes the `Optional[Any] = None` from four signatures.
3. Add a test that presses at `track_rect(metrics).right - 1` and asserts the
   value is the **maximum**, and one that presses at the painted centre and
   asserts the midpoint. Confirm both are red before the fix.

---

<a id="blocker-5"></a>

### B5— A generated numeric editor crashes on the first keystroke

**Area:** `OpenGLContext/ui/generate.py:114-125`, `ui/widgets.py:767-775`

`_numberEditor` falls back to a `TextField` when a numeric field has no
`minimum`/`maximum` hint. `TextField` is bound to the field, so `read()` returns
the field's value — a `float` — and `character()` immediately does string
arithmetic on it:

```python
def character(self, text: str) -> bool:
    current = self.read()                       # a float, for a bound SFFloat
    limit = int(self.maximumLength)
    if limit and len(current) >= limit:         # TypeError
```

Reproduced against a real `ContextDefinition`:

```
editor for iblIntensity: TextField
read() -> 1.0
typing into it raises: TypeError object of type 'float' has no len()
```

The comment above the fallback is right that a slider over an invented 0..1 is a
wrong answer — but the alternative shipped is a control that raises. The path is
reachable by design, not by accident: `page_for` / `record_panel` are the
generic route a game is told to use for any node, and `generate.py`'s own module
docstring advertises "Without a hint a number gets a text field rather than a
slider" as the intended behaviour.

The shipped settings screen happens to avoid it because
`ContextDefinition.UI_HINTS` gives every listed numeric field a range — so this
is a landmine for the first game that follows the documented pattern on its own
node, which is exactly the audience `generate.py` exists for.

**Remediation.** Add a `NumberField` (or a `numeric` flag on `TextField`) that
owns the string↔number conversion in one place:

- `read()` formats the field's value to a string for display and editing;
- `write()` parses, and on a value that does not parse yet (`''`, `'-'`, `'3.'`)
  keeps the text and leaves the field alone, committing on focus-loss or Enter;
- `integer` decides `int` vs `float`, as `Slider` already does.

This is also the honest fix for the "half-typed number must not reach the
renderer on every keystroke" requirement in `plans/OVERLAY-UI.md`, which the
current bound-`TextField` design cannot satisfy even for `SFString`-adjacent
cases. Red/green: a test that types `4` into a generated editor for
`iblIntensity` and asserts the field reads `4.0`.

---

<a id="blocker-6"></a>

### B6— The mandated type gate cannot run

**Area:** `pyproject.toml`, `openglcontext/CLAUDE.md`

The command CLAUDE.md gives for the type gate fails outright:

```
$ python -m mypy --follow-imports=silent OpenGLContext/ui/
.../numpy/__init__.pyi:737: error: Type statement is only supported in Python 3.12 and greater  [syntax]
Found 1 error in 1 file (errors prevented further checking)
```

`[tool.mypy] python_version = "3.10"` against a 3.12 virtualenv whose numpy
stubs use 3.12 syntax. Nothing is checked — the run stops at the first stub.
Forcing the real interpreter version works:

```
$ python -m mypy --python-version 3.12 --follow-imports=silent OpenGLContext/ui/ ...
Success: no issues found in 20 source files
```

So the new code *is* clean under the version it actually runs on, which is
credit to the author — but nobody could have known that from the documented
command, and it means the gate has been inoperative for however long the stubs
have been at this version. Combined with [B1](#blocker-1), the project currently has a
type-checking requirement that neither runs nor checks what it says it checks.

**Remediation.** Set `python_version = "3.12"` in `[tool.mypy]` to match the
virtualenv CLAUDE.md mandates, re-run over the whole package, and fix or
explicitly scope whatever that surfaces. If 3.10 support is a real constraint,
pin a numpy version whose stubs parse under 3.10 and say so in a comment beside
the setting — a version floor that exists for a reason should be legible.
Either way the invocation in
[openglcontext/CLAUDE.md](../CLAUDE.md) should be one that works when pasted.

---

## Major

<a id="major-1"></a>

### M1— `OverlayStack.clear()` loops forever on a closed panel

**Area:** `OpenGLContext/ui/overlay.py:105-128`

```python
def clear(self) -> None:
    while self.panels:
        self.pop()
```

`pop()` calls `top.close(result)`, and `Panel.close()` returns immediately if
`self.closed` — without notifying the listener that removes it from the stack.
A panel that is already closed when it reaches the stack therefore never leaves
it. Verified:

```
pushed an already-closed panel; len(panels) = 1
clear() finished within 3s: False
```

A hang with no exception and no log line is the worst failure shape available; it
looks like a GPU stall.

Reachability is low but not theoretical — `dialogs.confirm` hands the caller a
`Panel` and the caller decides when to push it, so a prompt answered
programmatically before it is shown lands here.

**Remediation.** Two independent guards, both worth having:

- `OverlayStack.push()` should refuse a closed panel — `raise ValueError("panel
  is already closed")`. Pushing a dead panel is a caller bug and should say so.
- `clear()` should not depend on the listener firing: iterate over a snapshot and
  call `remove()` directly, so the loop is bounded by construction.

```python
def clear(self) -> None:
    for panel in list(reversed(self.panels)):
        panel.close(None)
        self.remove(panel)
```

Red/green: the reproduction above, with `pytest.raises(ValueError)` on the push
and a `clear()` that returns.

<a id="major-2"></a>

### M2— `_follow()` does what its docstring forbids

**Area:** `OpenGLContext/ui/console.py:204-212`

```python
def _follow(self) -> None:
    """Keep the newest line in sight.

    Only ever downward: a console that yanked the view back while somebody
    was reading older output would be unusable in exactly the moment they
    needed it.
    """
    if self.body is not None:
        self.body.scrollTo(self.body.maximumScroll)
```

The implementation jumps to the bottom unconditionally. `write()` calls it on
every line, and `ConsoleLogHandler` calls `write()` for every log record — so
scrolling up to read an earlier traceback while the engine is still logging
snaps you to the end, which is the behaviour the docstring describes as
"unusable in exactly the moment they needed it".

**Remediation.** Implement the documented rule — follow only when already at (or
near) the bottom:

```python
def _follow(self) -> None:
    if self.body is None:
        return
    # Follow only if the reader was already at the end; someone who has
    # scrolled up is reading, and a jump would take the line away.
    if self.body.scroll >= self.body.maximumScroll - self.body.lineHeight:
        self.body.scrollTo(self.body.maximumScroll)
```

Note the `maximumScroll` has to be recomputed after the write, so the "was at the
end" test must be taken *before* the new line is appended. Red/green: scroll to
the top, write a line, assert `scroll` is unchanged; scroll to the bottom, write
a line, assert it followed.

<a id="major-3"></a>

### M3— `ConsoleLogHandler` retains the panel tree

**Area:** `OpenGLContext/ui/console.py:259-277`

```python
class ConsoleLogHandler(logging.Handler):
    """...
    Held by the handler rather than the panel so a console that has been closed
    simply stops receiving: a game may open and close several over a session,
    and a handler still writing into a dead one is a leak with no symptom.
    """
    def __init__(self, panel: ConsolePanel, ...):
        self.panel = panel
```

The reference is strong, and nothing removes the handler from the logger when
the panel closes. `emit()` early-returns on `panel.closed`, so it stops
*writing* — but the panel, its widget tree, its scrollback and any node a widget
is bound to stay reachable from `logging.getLogger(...).handlers` for the life of
the process. A game that opens and closes several consoles accumulates all of
them. That is the leak the docstring says the design avoids.

**Remediation.** Hold the panel weakly and unhook on close:

```python
def __init__(self, panel, level=logging.NOTSET, logger=None):
    super().__init__(level)
    self._panel = weakref.ref(panel)
    self._logger = logger or logging.getLogger('OpenGLContext')
    self._logger.addHandler(self)
    panel.closeListeners.append(lambda closing: self.detach())

def detach(self):
    self._logger.removeHandler(self)
```

`Panel.closeListeners` already exists for precisely this ("Separate from
`on_close` so an overlay stack can pop the panel without taking the one callback
the caller wanted"), so the hook is free. Then correct the docstring to describe
what the code does. Red/green: create a panel and handler, close the panel, drop
the local reference, `gc.collect()`, and assert the weakref is dead.

<a id="major-4"></a>

### M4— `end()` does not restore GL state

**Area:** `OpenGLContext/ui/draw.py:502-536`

```python
def end(self) -> None:
    """Draw what is left and put the GL state back as it was found."""
    ...
    glDisable(GL_SCISSOR_TEST)
    ...
    glDisable(GL_BLEND)
    glEnable(GL_DEPTH_TEST)
    glUseProgram(0)
```

It does not put anything back as it was found; it sets an assumed state. Depth
test on, blend off, no program bound, scissor off — whatever the caller had. The
docstring for `renderShaderOverlay` says it is *"Called by the shader render
pass once everything else is done, **with its program current**"*, and `end()`
unbinds that program. `begin()` likewise disables depth/cull and enables blend
without recording the previous values.

Today the overlay draws last so nothing observes the damage. That is a property
of the call site, not of this class, and `begin()`/`end()` are documented as
**public** ("Public so a game can draw its own HUD into the same batch") — so the
first caller who uses them mid-frame gets a silent state corruption, which is the
hardest class of GL bug to find.

**Remediation.** Either genuinely save and restore, or stop claiming to. Saving
is cheap and honest:

```python
def begin(self, viewport):
    ...
    self._saved = (glGetBooleanv(GL_DEPTH_TEST), glGetBooleanv(GL_CULL_FACE),
                   glGetBooleanv(GL_BLEND), glGetBooleanv(GL_SCISSOR_TEST),
                   glGetIntegerv(GL_CURRENT_PROGRAM),
                   glGetIntegerv(GL_BLEND_SRC_ALPHA),
                   glGetIntegerv(GL_BLEND_DST_ALPHA))
```

`glGet` in a per-frame path is a stall on some drivers, so if you would rather
not pay it, the alternative is to change the docstring to *"leaves depth testing
on, blending off and no program bound; call it last, or set the state you need
after it"* and note the constraint on `begin()` too. Both are acceptable; the
present combination of a promise and its opposite is not.

<a id="major-5"></a>

### M5— `close()` leaks the GL program

**Area:** `OpenGLContext/ui/draw.py:219-236`

`close()` deletes the VAO, the VBO and every texture, then does
`self._vao = self._vbo = self._white = self._program = None` — the program is
dropped without `glDeleteProgram`. `glfwcontext` now calls
`shadertext.drop_text_renderers()` before destroying a window precisely because
"a later window that the driver hands the same identifier" is a real hazard, so
the concern is already recognised; the overlay's own program is the one object
missed.

**Remediation.** `glDeleteProgram(self._program)` before clearing it (guarded by
`if self._program is not None`), and — since `close()` is the counterpart to
`initialize()` — have `glfwcontext`'s cleanup call it for the cached
`_overlayRenderer` the same way it calls `drop_text_renderers()`. Right now
nothing calls `close()` at all, so the leak is currently per-process rather than
per-window; wiring it up is the other half of the fix.

<a id="major-6"></a>

### M6— Modifiers are sampled at press time only

**Area:** `OpenGLContext/events/inputstate.py:38-51`, `move/modes.py:126-148`

`InputState.process` records the modifier triple only on a key-**down**, keyed by
that key's name:

```python
if state:
    self._held.add(name)
    self._pressed.add(name)
    getter = getattr(event, 'getModifiers', None)
    if getter is not None:
        self._modifiers[name] = tuple(getter())[:3]
```

`MovementMode.active()` then asks `inputs.modifiers(key)[index]` to decide
whether a modified binding applies. The result is order-dependent in a way a
player will hit within a minute of using the default `Ctrl`+arrow tilt:

- Hold the up arrow, *then* press Ctrl → the arrow's recorded triple has no
  Ctrl, so you keep walking forward and never tilt.
- Hold Ctrl+arrow, release Ctrl while keeping the arrow down → the recorded
  triple still says Ctrl, so the view keeps tilting and you never start walking.

The docstring on `modifiers()` accurately describes the storage ("recorded when
`name` was last pressed"), so this is a design gap rather than a slip — but the
thing `_GroundMode` binds it to is a *held* modifier, and a held modifier has to
be sampled, not remembered. That is the same argument that justified `InputState`
existing at all.

**Remediation.** Track the current modifier state rather than a per-key
snapshot. Every keyboard event carries `getModifiers()`, so:

```python
#: The modifiers as of the most recent key event, whichever key it was.
self._modifierState: Tuple[int, int, int] = (0, 0, 0)
```

updated on *both* press and release, with `modifiers(name)` keeping its
signature and returning the live state. Keep the per-key map only if something
genuinely needs "what was held when this key went down" — nothing currently
does. Red/green: press arrow, press Ctrl, assert `active(inputs, 'lookup')` and
`not active(inputs, 'forward')`; then release Ctrl and assert the reverse. Both
fail today.

While there: `_modifiers` entries are never removed on key-up, so the map grows
to the number of distinct keys ever pressed. The fix above removes the map, and
with it the growth.

<a id="major-7"></a>

### M7— Bindings are saved non-atomically, on every rebind

**Area:** `OpenGLContext/move/bindingstore.py:39-53`

```python
with open(path, 'w') as target:
    json.dump(stored, target, indent=2, sort_keys=True)
```

`open(path, 'w')` truncates first. `save_bindings` is called from `_bind()`,
i.e. once per key the player rebinds, so the window is small but frequent — and
what is at risk is the entire set of bindings, replaced by a zero-byte or
half-written file. The module docstring makes the stakes explicit: *"A rebinding
a player makes has to survive the process"*. `load_bindings` handles the
resulting `ValueError` by logging and returning False, so the symptom is silently
losing every binding, with a warning nobody reads.

**Remediation.** Write-and-rename, which is atomic on every platform this runs
on when both paths are in the same directory:

```python
directory = os.path.dirname(path) or '.'
os.makedirs(directory, mode=0o700, exist_ok=True)
handle, temporary = tempfile.mkstemp(dir=directory, prefix='.keybindings-')
try:
    with os.fdopen(handle, 'w') as target:
        json.dump(stored, target, indent=2, sort_keys=True)
    os.replace(temporary, path)
except BaseException:
    os.unlink(temporary)
    raise
```

Note also that the directory is created `0o770` while the file inherits the
umask — if the `0o770` is deliberate (it reads as "this is the user's own
directory"), the file should match with `0o600`; if it is not, `0o700` is the
conventional choice for an app-data directory. Pick one and be consistent.

<a id="major-8"></a>

### M8— Loading tolerates missing keys but not wrong types

**Area:** `OpenGLContext/move/bindingstore.py:56-80`

The docstring says the file is JSON *"which someone will eventually edit by hand
and should not have to fight"*, and loading is *"deliberately forgiving"*. It is
forgiving of unknown modes and commands. It is not forgiving of a wrong type
inside an otherwise well-formed entry:

```python
binding.keys = [str(key) for key in entry.get('keys', ())]
```

- `"keys": "wasd"` — a plausible hand edit — iterates the string and binds four
  separate keys `w`, `a`, `s`, `d`.
- `"keys": 5` raises `TypeError` out of `load_bindings`, past the
  `except (ValueError, OSError)` guard, at start-up.

A file the user is invited to edit should not be able to crash the application,
and should not silently mean something other than what it says.

**Remediation.** Validate the shape at the boundary, in one helper, and log what
was dropped:

```python
def _keyList(value: Any, where: str) -> Optional[List[str]]:
    if isinstance(value, str) or not isinstance(value, (list, tuple)):
        log.warning("ignoring %s: 'keys' must be a list of strings, got %r",
                    where, value)
        return None
    return [str(key) for key in value]
```

Same treatment for `modifier` (must be a string, and one of
`modes.MODIFIER_INDEX` or empty — an unknown modifier currently makes the
binding permanently unreachable, since `MODIFIER_INDEX.get()` returns `None` and
`active()` then never matches). Red/green: a test per malformed shape asserting
the app loads, the good entries apply and a warning is logged.

<a id="major-9"></a>

### M9— Three environment-read lifetimes in one class

**Area:** `OpenGLContext/passes/flatcore.py:70-137`, `renderoptions.py:65-83`

Within ~60 lines of one class, an environment variable is read three different
ways:

| Where | Lifetime | Line |
|---|---|---|
| `_envDefault('_shadows_env', 'OPENGLCONTEXT_SHADOWS', True)` | once per pass, cached | 70-83 |
| `INSTANCE_MIN = int(os.environ.get('OPENGLCONTEXT_INSTANCE_MIN', '4'))` | once per **process**, at import | 119 |
| `renderoptions.env_flag('OPENGLCONTEXT_INSTANCING', True)` inside a property | **every frame** | 134-136 |

`_envDefault`'s own docstring argues the case against the third: *"a pass that
changed its mind mid-session because something else edited `os.environ` would be
unpredictable"*. `instancing_enabled` does exactly that, two methods later.
Meanwhile `renderoptions`'s module docstring states the opposite rule for
everybody — *"every caller's default reads its environment variable **at call
time**"* — so the two files disagree about the contract they share.

The import-time variant is not merely inconsistent: it is untestable by
`monkeypatch.setenv` once the module is imported, which is a live trap for the
test suite (and is the shape of hazard that produced [B3](#blocker-3)).

**Remediation.** Pick one rule, write it down once in `renderoptions`, and make
all three obey it. `_envDefault`'s reasoning is the better rule — start-up
switches settle once, the `ContextDefinition` field is the thing that changes at
runtime — so:

- Move the memo into `renderoptions` as `env_flag_once(name, default)` /
  `env_number_once(...)`, with the cache keyed by variable name and a
  `reset_env_cache()` for tests (see [B3](#blocker-3)).
- Convert `INSTANCE_MIN` and `instancing_enabled` to it.
- Fix `renderoptions`'s module docstring to describe the settled rule, and drop
  the `_envDefault` helper and its four `_*_env` attributes from `flatcore`.

<a id="major-10"></a>

### M10— A generated `KeyCapture` is unbound

**Area:** `OpenGLContext/ui/generate.py:109-110`

```python
if kind == 'MFString' and hint.get('editor') == 'keys':
    return KeyCapture(keys=list(getattr(node, name)), name=name)
```

`KeyCapture` extends `Widget`, not `BoundWidget` — it has no `target` or
`fieldName` — so this copies the current keys and has no way back to the field.
Its `result()` must be read by a caller, and `page_for` has no such caller. A
generated page over any node with a `keys`-hinted `MFString` therefore shows a
key field that accepts a keystroke, turns the accent colour to say it took it,
and discards it.

`KeyBinding.UI_HINTS` in `move/modes.py:53-60` declares exactly that hint, so
`generate.page_for(a_KeyBinding)` — reachable via the generic `record_panel` —
produces one. The bindings page works only because `ui/bindings.py` builds its
own capture dialog and wires `on_change` by hand.

**Remediation.** Either make the generated widget work or refuse to generate it.
The first is better and is small, because the machinery exists:

```python
if kind == 'MFString' and hint.get('editor') == 'keys':
    capture = KeyCapture(keys=list(getattr(node, name)), name=name)
    capture.on_change = lambda widget, node=node, name=name: (
        setattr(node, name, widget.result()))
    return capture
```

If instead the position is that key capture always needs the conflict dialog and
therefore cannot be generated, return `None` here and say so in the module
docstring beside the `UNEDITABLE` list — a hint that produces a dead control is
worse than a field that visibly has no editor. Red/green: generate a page for a
`KeyBinding`, capture `'j'`, assert `binding.keys == ['j']`.

<a id="major-11"></a>

### M11— Geometry writes the pass's private state cache

**Area:** `OpenGLContext/scenegraph/teapot.py:170-184`, `scenegraph/pbrmesh.py:440-461`

```python
def _apply_draw_state(self, mode):
    glEnable(GL_CULL_FACE); glCullFace(GL_BACK); glFrontFace(GL_CCW)
    mode._pbr_cull_enabled = True
    mode._pbr_front_face = GL_CCW
```

`_pbr_cull_enabled` and `_pbr_front_face` are the PBR pass's private GL-state
memo, read and written in `pbrmesh.py`. `teapot.py` now writes them too. That is
an underscore-prefixed protocol with two participants in two packages and no
owner — the exact shape that goes stale when a third participant appears, and it
cannot be found by anyone reading `passes/` because the writer lives in
`scenegraph/`.

Separately, `instanceGPU` passes `depend_fields=('size', 'lid')` — bare strings —
while the documented API in [openglcontext/CLAUDE.md](../CLAUDE.md) shows field
objects (`depend_fields=(protofunctions.getField(self, 'size'),)`) and
`build_mesh_gpu`'s own docstring says "rebuilt when a `depend_fields` field
changes". One of the two is wrong; if strings happen to work, the documented
example should be strings, and if they do not, the teapot's cache never
invalidates when `size` changes.

**Remediation.**

1. Give the pass a public method for the thing the node actually wants —
   `mode.setCullState(enabled=True, front_face=GL_CCW)` on the PBR pass — and
   have both `pbrmesh` and `teapot` call it. The memo stays private to the pass,
   which is where it belongs.
2. Settle `depend_fields`. Add a test that changes `Teapot.size` between two
   instanced frames and asserts the cached `_MeshGPU` was rebuilt; whichever
   form makes that test pass is the form the CLAUDE.md example should show.

<a id="major-12"></a>

### M12— New methods in `viewplatformmixin.py` are unannotated

**Area:** `OpenGLContext/move/viewplatformmixin.py` (+190 lines this range)

Roughly fifteen new methods — `getInputState`, `getNavigationPlatform`,
`getNavigation`, `updateNavigation`, `setPointerCapture`,
`suspendPointerCapture`, `_applyPointerCapture`, `hasMouseMoveHandlers`,
`recordPointerMotion`, `_recordInput` — carry no type annotations, against
CLAUDE.md's *"All new code is fully type annotated and passes mypy"*. The rest
of the new work (`ui/`, `move/modes.py`, `navigation.py`, `bindingstore.py`,
`renderoptions.py`, `inputstate.py`) is fully annotated, so this file is the
outlier rather than the norm — which makes it look like an oversight rather than
a decision.

Matching the file's existing `def f( self ):` spacing is right and should stay
(CLAUDE.md says not to churn old code). Annotations are orthogonal to spacing.

`ruff` also reports four `F401` unused imports in this file (`math`,
`OpenGLContext.interactivecontext`, `OpenGLContext.move.direct`) plus `W291`/
`W293` — some pre-existing, but the file grew by 190 lines in this change and
`from OpenGLContext.move import direct, smooth` with `direct` unused sits inside
a method this work touched.

**Remediation.** Annotate the new methods (they are all simple: `-> None`,
`-> bool`, `-> Any` for the platform), drop the unused imports, and run
`ruff check --fix OpenGLContext/move/viewplatformmixin.py` for the whitespace.
Leave the star import and the older methods alone.

<a id="major-13"></a>

### M13— Rebuilding the navigation manager resets the player's mode

**Area:** `OpenGLContext/move/viewplatformmixin.py:91-109`, `move/navigation.py:26-34`

```python
if self.navigation is None or self.navigation.platform is not platform:
    self.navigation = NavigationManager(definition, platform)
```

and

```python
def __init__(self, definition, platform):
    ...
    first = self._selectable()
    if first:
        self._selected = first[0]
        self._publish(first[0])
```

`getNavigation` deliberately rebuilds when the platform changes — the docstring
explains why ("a character controller usually comes into being when a world
finishes loading"). But the rebuild discards `_selected` and republishes the
*first* declared mode. So a player who has switched to Fly, and then triggers
anything that swaps the platform, is silently put back into Walk mid-session,
with `ContextDefinition.movementMode` changing under every watcher.

**Remediation.** Re-point the existing manager rather than replacing it:

```python
def retarget(self, platform: Any) -> None:
    """Drive a different platform, keeping the player's chosen mode."""
    self.platform = platform
```

and in `getNavigation`, call `self.navigation.retarget(platform)` when only the
platform changed. Red/green: build a manager, `select('fly')`, retarget to a new
platform, assert `definition.movementMode.name == 'fly'`.

<a id="major-14"></a>

### M14— `number()` does not return a float

**Area:** `OpenGLContext/renderoptions.py:98-101`

```python
def number(source: Any, name: str, default: float) -> float:
    value = _value(source, name)
    return default if value is None else value
```

The annotation promises `float`; the raw field value is returned. For
`SFInt32` fields that is an `int`, and for anything numpy-backed it is a numpy
scalar. Callers compensate individually — `flatcore.py:116` and
`shadowpool.py:73` both wrap the result in `int(...)`, `flateffects.py:119` in
`float(...)` — which is the tell that the function is not doing its job. This is
one of the errors `warn_return_any` would have caught before [B1](#blocker-1) turned it
off package-wide.

**Remediation.** `return float(default if value is None else value)`, and drop
the compensating casts at the three call sites (keeping `int()` where an integer
is genuinely wanted, which is honest arithmetic rather than a workaround).

---

## Minor

<a id="minor-1"></a>

### m1— `Skin._image()` is private and used from five modules

**Area:** `ui/skin.py:241-243`, called from `widgets.py` (×6), `panel.py`,
`scroll.py` (×2), `console.py`

A leading underscore says "nobody outside this class"; ten call sites in four
other modules say otherwise. The reader has to decide which to believe.

**Remediation.** Rename to `image(self, value)` and export it. If the intent is
that widgets should not reach for artwork directly, the better shape is a
`skin.imageFor('field')` lookup, or moving the `image if image else None`
normalisation into `renderer.frame()` — which already accepts `image=None` — so
the call sites become `renderer.frame(rect, fill, skin.fieldImage)`. That last
option removes all ten uses.

<a id="minor-2"></a>

### m2— Full tree walks per frame and per keystroke

**Area:** `ui/layout.py:186-222`, `ui/panel.py:270-274, 401-423`

`plans/OVERLAY-UI.md` commits to "Layout runs when something changes, not per
frame", and the layout side honours it. Painting does not:

- `Grid.paint` calls `_activeRows()`, which walks **every widget in every cell**
  looking for `hovered`/`focused`, then `rowRects()`, which reads every child's
  rect. Once per grid, per frame. The settings screen has four grids.
- `Panel.key` calls `accelerate()` (a full `walk()`) on any key nothing else
  consumed, and `primary()` (another full `walk()`) on every Return.

At a few dozen widgets this is not a frame-rate problem, and `plans/OVERLAY-UI.md`
is right that virtualising is not needed yet. It is a *structure* problem: hover
and focus each change at exactly one point, so recomputing them by search every
frame is work the design already has the information to avoid.

**Remediation.** Cache what changes at the point of change:

- `Panel.pointer_moved` and `Panel.focus` are the only writers of `hovered`/
  `focused`. Have them set `panel._hoveredRow`/`_focusedRow` by asking the
  containing `Grid` once, and let `Grid.paint` read those.
- Build the accelerator map and the primary button once in `Panel.layout()` —
  layout already walks the tree — and invalidate on the next layout.

<a id="minor-3"></a>

### m3— `dirty` is a deep comparison run on every write

**Area:** `ui/session.py:206-209`, `ui/settings.py:113-118`

`SettingsSession.dirty` calls `nodes_equal(self.draft, self.target)`, which walks
every field of every node in the draft. `settings_panel` wires it to
`on_dirty`, which fires on **every** field write — so dragging a slider runs a
full recursive comparison of the whole `ContextDefinition` (including every
`movementModes` sub-node and every `KeyBinding` under them) once per mouse-move
event.

**Remediation.** The session already sees every edit through the dispatcher.
Set a `_dirty` flag in `_draftChanged` and clear it in `commit()`/`revert()`;
keep the deep comparison as `differs_from_target()` for the places that want the
exact answer. The Apply button wants "has anything been touched", which the flag
answers exactly.

<a id="minor-4"></a>

### m4— `SettingsSession` has no teardown

**Area:** `ui/session.py:176-203`

`_watch()` connects a dispatcher receiver per node in the draft; `_unwatch()` is
called only from `revert()`. A session that is dropped without reverting leaves
the connections in place, and `settings_panel` keeps `panel.session = session`
alive for the panel's lifetime.

`pydispatcher` holds senders weakly, so this is bounded rather than unbounded —
but there is no way for a caller to say "I am done with this session", and
`on_dirty` keeps firing on a draft belonging to a dialog that has closed.

**Remediation.** Add `close()` (calling `_unwatch()` and clearing `on_dirty`),
call it from the panel's `on_close`, and make `SettingsSession` a context
manager so the common case is `with SettingsSession(node) as session:`.

<a id="minor-5"></a>

### m5— Click-to-place-caret is half built

**Area:** `ui/widgets.py:750-765`

```python
def press(self, x: float, y: float) -> bool:
    if not super(TextField, self).press(x, y):
        return False
    self._pending_caret = x
    return True
```

`_pending_caret` is written and never read anywhere in the codebase.
`caret_from()` computes the answer it was evidently meant to feed, and has no
production caller — its only two uses are in `tests/unit/test_ui_widgets.py:482`.
So `focus_gained()` puts the caret at the end and clicking in the middle of a
value does nothing, while the code and a test both suggest otherwise.

**Remediation.** Finish it or remove it. Finishing needs the metrics at press
time — the same problem as [B4](#blocker-4), so the same fix (`self._metrics` stored at
`arrange()`) serves both:

```python
def press(self, x, y):
    if not super().press(x, y):
        return False
    self.caret = self.caret_from(x, self._metrics)
    return True
```

with the ordering caveat that `focus_gained()` runs after `press()` in
`Panel.pointer_pressed` and would overwrite it — so `focus_gained` should only
move the caret when it is out of range. Red/green: click at character 2 of
`'hello'` and assert `caret == 2`.

<a id="minor-6"></a>

### m6— `Panel.viewport` is dead

**Area:** `ui/panel.py:168`

`self.viewport = Rect(0, 0, view_width, view_height)` is assigned on every
layout and read nowhere. It is also an undeclared attribute on a node — not a
field, not in the class's documented attribute block — so it does not serialise
and does not appear in the class's own description of its state.

**Remediation.** Delete it. If a panel does need to know its window (nothing
currently does), declare it beside `_title_height` with a comment saying who
reads it.

<a id="minor-7"></a>

### m7— `Slider.display_value(metrics)` ignores its argument

**Area:** `ui/widgets.py:642-649`

The parameter is accepted, defaulted and never referenced. Two of the three call
sites pass one.

**Remediation.** Remove the parameter (`display_value(self) -> str`) and drop it
at the call sites. `tests/unit/test_ui_widgets.py:425` passes it and will need
the same edit.

<a id="minor-8"></a>

### m8— `Select.release` calls `super().activate()` on itself

**Area:** `ui/widgets.py:544-553`

`Select` does not override `activate`, so `super(Select, self).activate()`
resolves to the same `Widget.activate` that `self.activate()` would. The `super`
reads as "deliberately skip an override" and there is none to skip — so the next
person to add `Select.activate()` will find it silently bypassed.

**Remediation.** `self.activate()`. If the intent *is* "never run a subclass's
activate here", say so in a comment, because it is not otherwise deducible.

<a id="minor-9"></a>

### m9— Three quarters of `_INTERNAL` is unreachable

**Area:** `ui/session.py:46, 62-65`

```python
_INTERNAL = (' DEF', ' root', ' PROTO', 'externalURL')
...
if definition.name not in _INTERNAL
   and definition.name not in transient
   and not definition.name.startswith(' ')
```

The first three entries all start with a space and are already excluded by the
last clause. Only `'externalURL'` does any work, so the constant's name and
contents misdescribe what it filters.

**Remediation.** `_INTERNAL = ('externalURL',)` with a comment saying what it is
(a field the node system keeps that does not begin with a space), or drop the
tuple and special-case `externalURL` inline.

<a id="minor-10"></a>

### m10— Unreachable `UI_HINTS`, and an unconsumed hint key

**Area:** `contextdefinition.py:180-240`

Two dead pieces of metadata:

- `UI_HINTS` declares entries for `'profile'` and `'title'`, but neither name
  appears in `RENDERING_FIELDS`, `INTERFACE_FIELDS` or `DIAGNOSTIC_FIELDS`, and
  `settings_panel` builds the page from exactly those three lists. The hints are
  never read.
- `'profile'` also carries `'restart': True`. Grepping the whole tree finds
  exactly one occurrence — its own declaration. `generate.py` does not know the
  key exists.

The `restart` hint is the more interesting one, because it encodes a real fact
the UI ought to surface: `settings.py`'s `doApply` comment says *"A changed
profile or buffer format only takes effect on the next context, and nothing
pretends otherwise"* — but with the hint unconsumed, nothing tells the player
either.

**Remediation.** Decide whether `profile` belongs on the settings screen.

- If yes: add it to `RENDERING_FIELDS`, teach `generate.editor_for` to read
  `restart` and append " (restart required)" to the label (or disable the editor
  with that as its tooltip), and add `multisampleSamples` to the same treatment
  since it has the same property.
- If no: delete both hint entries, and delete `restart` with them.

Either way, a test that asserts every `UI_HINTS` key appears in one of the three
section lists would stop this recurring — it is the same "cannot silently go
missing" guarantee the generated page was built for, applied to the hints.

<a id="minor-11"></a>

### m11— `quad()` changes state before its own early-out

**Area:** `ui/draw.py:283-299`

```python
if rect.empty:
    return
self._state(self._white if texture is None else texture, mode)   # may flush
red, green, blue, alpha = _rgba(colour)
if alpha <= 0:
    return
```

A fully transparent quad flushes the batch and re-points `_texture`/`_mode`
before deciding it has nothing to draw — so the *next* quad flushes again to get
back. Transparent colours are not exotic here: `Label.color` defaults to
`(0,0,0,0)` meaning "use the skin", `Grid.paint` guards `rowRule` on
`float(skin.rowRule[3])` because a game may zero it, and a skin that turns off a
fill sets its alpha to 0.

**Remediation.** Move both early-outs above `_state`:

```python
red, green, blue, alpha = _rgba(colour)
if rect.empty or alpha <= 0:
    return
self._state(...)
```

While there: `_state` compares textures with `is not`. It works only because
every texture id is stored on a long-lived attribute and compared by identity
with itself; two equal ids from different sources would compare unequal. Use
`!=`.

<a id="minor-12"></a>

### m12— Nine-slice URL handling

**Area:** `ui/draw.py:379-405`, `ui/skin.py:58-61`

Two small mismatches between the promise and the code:

- `NineSlice.url` is `MFString` and documented as *"Where the image is, as a path
  or a file URL"*, but `ninepatch` uses `urls[0]` only. Everywhere else in
  OpenGLContext an `MFString` `url` is a list of *alternatives tried in order*
  (that is what `ImageTexture` does), so a skin listing a fallback gets the
  fallback ignored.
- `imageTexture` calls `PIL.Image.open(url)` directly, which takes a filesystem
  path. A `file://…` URL — which the docstring explicitly offers — raises, is
  caught, logged and cached as "will not load".

**Remediation.** Loop over the URLs and take the first that loads; run each
through the existing resolver (`OpenGLContext.loaders.resolver`) so `file:` and
relative paths behave as they do for every other texture in the system. If
routing through the resolver is more than this feature warrants, then narrow the
docstring to "a filesystem path" and drop the URL claim.

<a id="minor-13"></a>

### m13— `MovementMode._turn` reads a subclass's field

**Area:** `move/modes.py:168-190`

`_turn()` is defined on `MovementMode` and reads `self.turnAcceleration`, which
is declared on `_GroundMode`. Any direct `MovementMode` subclass that is not a
`_GroundMode` — which the class hierarchy explicitly invites, since
`MovementMode` is documented as the base prototype a game extends — gets an
`AttributeError` the first time a turn is held.

**Remediation.** Move `_turn` (and `_turn_held`/`_turning`, which are only used
by it) down to `_GroundMode`, beside the field it needs. If the intent is that
every mode can turn, move `turnRate`/`turnAcceleration` up to `MovementMode`
instead. Either is fine; the split as it stands is not.

<a id="minor-14"></a>

### m14— A dead condition in `_selectable()`

**Area:** `move/navigation.py:40-53`

```python
return [mode for mode in self.modes()
        if mode.enabled and not mode.enter_when(self.platform)
        and not self._imposable(mode)]
```

`enter_when()` returning True implies the mode overrides it, which implies
`_imposable(mode)` is True — so the middle clause can never be the deciding one.
It costs one `enter_when` call per mode, and `_selectable()` is reached from
`update()` on the frames where no mode is selected.

**Remediation.** Drop `not mode.enter_when(self.platform) and`. The remaining
`_imposable` test is the one that expresses the documented rule ("a mode that can
impose itself is excluded"), and it is a cheap type check rather than a call
into the platform.

<a id="minor-15"></a>

### m15— `distribute()` mutates its caller's list

**Area:** `hud.py:36-58`

`mains[index] = ...` writes through the caller's list and the function also
returns it. `Panel.arrange_content` calls it as
`heights = distribute(children, heights, spare)` and so cannot tell; a future
caller that keeps the original will silently find it changed. The docstring
describes the sharing rule and says nothing about mutation.

**Remediation.** `mains = list(mains)` at the top — the lists are a handful of
integers — so the return value is the only channel. Or, if the in-place
behaviour is wanted for a reason, rename to `distribute_into` and say so.

<a id="minor-16"></a>

### m16— A `Row`'s children measure with no available width

**Area:** `hud.py:277-296`

```python
inner = self.rect.inset(metrics.pixels(self.padding))
available = None if self.horizontal else inner.width
sizes = [child.natural_size(metrics, available) for child in children]
```

The comment on `_childAvailable` explains why a row cannot hand its width down
("its children have not yet been given their shares of it"), which is true for
the *flex* distribution. The consequence is that a wrapped `Label` inside a
`Row` falls back to `self.rect.width` — the rectangle from the *previous*
layout, or `0` on the first pass — so its measured height is wrong on the first
layout and stale on a resize.

`dialogs.confirm` and `bindings_panel` both put wrapped labels in a `Column`
(which does pass the width), so this does not currently bite; it will the first
time someone writes `Row { Label { wrap TRUE } Button {} }`.

**Remediation.** Two passes for the non-flex part: give each child the full inner
width for measurement, distribute, then re-measure the flexible children against
the widths they actually got. Or, cheaper and honest: have `Label.content_size`
return the unwrapped single-line size when `available is None`, and document that
`wrap` needs a container that can offer a width — with `Box` raising or logging
when it sees a wrapping child on the main axis, so the limitation is discovered
at development time rather than at a resize.

<a id="minor-17"></a>

### m17— `Grid` overflows rather than shrinking

**Area:** `ui/layout.py:119-137`

```python
spare = available - sum(widths) - gaps
if spare <= 0:
    return widths
```

When the natural columns do not fit, they are used unchanged and the cells are
laid out past the grid's right edge — over the scrollbar, or outside the panel.
`hud.distribute` makes the opposite choice for boxes and documents it ("a box
too small for them overflows instead, because the overflow is visible while a
crushed layout silently lies"), so the behaviour is at least consistent with a
stated principle. But a `Grid` has a defensible way to shrink that a box does
not: its label column is the one with slack.

**Remediation.** When `spare < 0`, take the shortfall from the widest column
(clamped so no column goes below, say, four characters) rather than overflowing,
and let the labels truncate with `metrics.truncate` — which already exists for
"where wrapping is not an option". A settings row that reads
"Environment inten… [slider]" is better than one whose slider is off-screen.

<a id="minor-18"></a>

### m18— `ConsolePanel.paint` duplicates `Panel.paint`

**Area:** `ui/console.py:167-179` vs `ui/panel.py:256-262`

The two are identical apart from `skin.consoleFill` in place of
`skin.panelFill`. Three lines of border and title drawing are copied, so a change
to how a panel draws its title has to be made twice.

Also, `ConsolePanel.paint` is defined *above* `__init__`, which no other class in
the package does.

**Remediation.** Add a `fillColour(self, skin)` hook to `Panel` returning
`skin.panelFill`, override it in `ConsolePanel` to return `skin.consoleFill`,
and delete the duplicated method. Move `__init__` above `paint`.

<a id="minor-19"></a>

### m19— Environment parsing is silently lenient and inconsistent

**Area:** `renderoptions.py:106-128`

- `env_flag` returns the caller's default for any value it does not recognise,
  so `OPENGLCONTEXT_SHADOWS=ture` silently means "on" and
  `OPENGLCONTEXT_BLOOM=yes please` silently means "off". These variables are the
  documented way to pin a feature for a CI run; a typo that reverses the pin
  with no diagnostic makes the CI result a lie.
- `FALSE_WORDS` includes `''`, so `OPENGLCONTEXT_BLOOM=` is False; `env_choice`
  treats `''` as "not set" and returns its default. Same spelling, opposite
  meaning, in adjacent functions.

**Remediation.** `log.warning("ignoring %s=%r: expected one of %s", ...)` on an
unrecognised value in both functions, and settle the empty string — treating it
as "unset" in both is the least surprising, since that is what an unexported
shell variable expands to. Red/green: a test per function asserting the warning
and the fallback.

<a id="minor-20"></a>

### m20— `pragma: no cover - GL` on the overlay's draw entry point

**Area:** `ui/overlay.py:385`, `bin/ui_demo.py:130`

```python
def renderShaderOverlay(self, pass_: Any) -> None:   # pragma: no cover - GL
```

[openglcontext/CLAUDE.md](../CLAUDE.md) opens with *"real OpenGL IS available …
Do not claim the sandbox is headless"*, and the coverage rule allows a gap only
where a line is *"genuinely impractical to reach (a defensive branch that needs
a broken GL driver, say)"*. "GL" is not that; `tests/unit/test_ui_draw_gl.py`
already drives `OverlayRenderer` against a real context in 17 tests.

The excluded method is the one that ties the stack, the layout, the metrics and
the renderer together — the integration seam, and the only place where "the
panel is laid out for the current window before it is drawn" is enforced.

**Remediation.** Cover it with the existing GL harness: push a panel onto a real
context, call `renderShaderOverlay`, and assert something observable (the
renderer was created and cached on the context; a second call with a resized
viewport re-laid-out the stack). Keep the two `except Exception` driver guards
excluded — those are the legitimate case. Same treatment for `ui_demo.OnInit`,
or drop that one as demo code if the suite does not run demos.

<a id="minor-21"></a>

### m21— A module-level `gettext` call, with no catalogue anywhere

**Area:** `ui/bindings.py:42`

`UNBOUND = _('(unbound)')` runs at import, before any application can call
`gettext.bindtextdomain`/`textdomain` — so this one string is frozen at the
locale in force at import time even after translation is set up. Every other
`_()` in the package is inside a function and does not have the problem.

Note that `from gettext import gettext as _` is an existing convention here
(`move/smooth.py`, `move/direct.py`, `bin/choosecontext.py` all predate this
work), so the *import* is consistent and should stay. But the workspace contains
no `.po`/`.mo` files and nothing binds a domain, so every `_()` in the project is
currently an identity function. That is fine as forward preparation — it is worth
one line in the docs saying so, since a reader who sees `_()` reasonably assumes
translations exist and will go looking for the catalogue.

**Remediation.** Make `UNBOUND` a function or inline the `_()` at its two use
sites. Add a sentence to `docs/overlayui.html` noting that UI strings are marked
for translation but no catalogues ship yet, and what a game must call to bind
its own.

<a id="minor-22"></a>

### m22— Every scroll child is measured twice per layout

**Area:** `ui/scroll.py:109-131`

`arrange_content` calls `child.natural_size(...)` once to accumulate
`contentHeight` (against `rect.width - _barGutter()`) and again in the placement
loop (against `view.width`). For a licence notice that is two full text-wrapping
passes over thousands of words on every layout.

The two widths differ when `needsBar` is False — the first subtracts the gutter,
the second does not — so the second pass can report a shorter child than
`contentHeight` claims, leaving a small phantom scroll range. The comment
acknowledges the ordering problem ("whether there is a bar depends on the
height, so measure once without it and settle the width after"), so the
conservative first pass is deliberate; the second measurement is what is
redundant.

**Remediation.** Keep the first pass's sizes and reuse them:

```python
sizes = [child.natural_size(metrics, content_width) for child in children]
self.contentHeight = pad * 2 + sum(int(size[1]) for size in sizes)
...
for child, size in zip(children, sizes, strict=True):
    child.arrange(Rect(view.x, cursor - size[1], view.width, size[1]), metrics)
```

with `content_width` computed once from the settled `needsBar`. That also removes
the width discrepancy.

<a id="minor-23"></a>

### m23— `label_for` destroys acronyms

**Area:** `ui/generate.py:60-65`

```python
words = _CAMEL.sub(' ', name)
return words[:1].upper() + words[1:].lower()
```

`iblIntensity` becomes "Ibl intensity" and `uiScale` becomes "Ui scale". Both are
currently masked by explicit `label` hints in `ContextDefinition.UI_HINTS`, so
the shipped screen reads correctly — but the fallback is what a game's own node
gets, and it is the path `generate.py` advertises as needing no per-setting work.

**Remediation.** Do not lower-case; split on the camel boundary and capitalise
only the first word, leaving the rest as written (`iblIntensity` →
"Ibl intensity" is still wrong, so also treat a run of capitals as one word:
`IBLIntensity` → "IBL intensity"). Add a small `KNOWN_ACRONYMS = ('ibl', 'ui',
'lod', 'fps')` upper-cased on output — three lines, and it makes the generated
page presentable without a hint for every field.

<a id="minor-24"></a>

### m24— `DEFAULT_SKIN` is a shared mutable singleton

**Area:** `ui/skin.py:252`, `panel.py:121-133`

`DEFAULT_SKIN = Skin()` is a module global handed to every panel that names no
skin, and `Skin.scaled()` returns `self` unchanged when the factor is 1 — so at
the reference font size every panel in the process shares one object. Nothing
mutates it today, but `Skin`'s fields are all writable and the class is
documented as authored data a game supplies, so "a game tweaks the default skin's
`panelFill`" is a natural thing to try and would change every dialog in the
process, including ones already on screen.

**Remediation.** Either document it as read-only in the module docstring ("the
default is shared; copy it with `.scaled(1.0)` before changing anything"), or
make `skin_for` return a per-panel copy on first use. The docstring route is
cheaper and probably right, but the current silence is the problem.

<a id="minor-25"></a>

### m25— `contextDefinition` assigned before `Context.__init__`

**Area:** `glfwcontext.py:63-65`

```python
self.contextDefinition = definition
self.applyVSync()
...
Context.__init__(self, definition)
```

`applyVSync` needs the definition, hence the early assignment — reasonable. But
`Context.__init__` is then given the same object and may normalise, copy or
default it, and if it ever does, the two references diverge with no error.

**Remediation.** Read the definition from the local variable instead of
round-tripping through `self` — `self.applyVSync(definition)` with the parameter
defaulting to `self.contextDefinition` — so the early assignment is unnecessary
and the base class remains the only thing that sets the attribute.

<a id="minor-26"></a>

### m26— An inert `noqa`

**Area:** `ui/console.py:88`

`# noqa: BLE001 - reported, not raised` suppresses a rule that is not in the
project's `select` list (`E`, `W`, `F`, `B`), so it does nothing. The comment
after it is worth keeping — the broad catch genuinely is deliberate.

**Remediation.** Drop the `noqa:` prefix and keep the prose: `# a command that
raises is reported, not re-raised`.

---

## What is right, and should not change

Worth recording so a later refactor does not undo it:

- **Measurement, layout, hit-testing and drawing are four separable things.**
  `ui/geometry.py` and `ui/metrics.py` have no GL and no node dependencies, which
  is why 505 UI tests run with no context and no mocks. This is the single best
  decision in the change set.
- **`hud.py` was implemented rather than replaced.** Decision 6 in
  `plans/OVERLAY-UI.md` was the right call and the result reads as one system.
- **The scale rule.** One number (`FontMetrics.scale`) multiplying every pixel
  measurement, with the two character-based exceptions called out explicitly, is
  a rule that can be checked rather than a convention that decays.
- **Editing on a copy, with commit writing fields into the existing node.** The
  reasoning about `USE` sharing and watchers in `ui/session.py` is exactly right
  and is the kind of thing that is very expensive to retrofit.
- **The claim ledger** (`OverlayMixin._claimed`, decision 10). Recognising that a
  key-down consumed by the last panel leaves its key-up for the world, and
  solving it with a small explicit set rather than a second dispatch path, is
  good engineering and well explained.
- **Documentation shipped with the change.** `docs/overlayui.html` (464 lines),
  `docs/navigation.html` (233), the `structure.html` and `documentation.html`
  updates, and the CLAUDE.md directory map all landed in the same work. That is
  the standard the workspace asks for and it was met.

---

## Suggested order of work

1. [B1](#blocker-1), [B6](#blocker-6) — restore the type gate and make it runnable, then fix
   the 22 errors it reveals. Everything else is easier to verify afterwards.
2. [B3](#blocker-3) — the isolation fix is small and makes the suite trustworthy.
3. [B2](#blocker-2) — bisect the conformance regression; this may be the largest
   unknown in the change set.
4. [B4](#blocker-4), [B5](#blocker-5), [M10](#major-10) — the three user-visible controls that do
   not work. [B4](#blocker-4) and [m5](#minor-5) share a fix.
5. [M2](#major-2), [M3](#major-3), [M4](#major-4), [M9](#major-9) — the docstrings that describe
   behaviour the code does not have. Each is either a code fix or a prose fix;
   decide which per case, but do not leave the contradiction.
6. [M6](#major-6), [M7](#major-7), [M8](#major-8), [M13](#major-13) — correctness in movement,
   persistence and input.
7. [M1](#major-1), [M5](#major-5), [M11](#major-11), [M12](#major-12), [M14](#major-14).
8. The minors, which are largely mechanical. [m1](#minor-1), [m6](#minor-6), [m7](#minor-7),
   [m8](#minor-8), [m9](#minor-9), [m26](#minor-26) are deletions and renames and could go in
   one commit.

Every item above should land with a test that was red first. Several of these —
[B4](#blocker-4), [B5](#blocker-5), [M1](#major-1), [M6](#major-6), [M10](#major-10) — have a reproduction in
this document that can be pasted into a test as-is.
