# Lint and typing — clearing the backlog in the older modules

**Status:** 🟡 Partial — the defect sweep (step 0) landed 2026-08-22; steps 1-8
are planned.

`ruff` and `mypy` are both configured in [pyproject.toml](../pyproject.toml) and
neither runs in CI. Over the whole package they report:

| Tool | Findings | Files with at least one |
|---|---|---|
| `ruff check OpenGLContext` | 3,288 | 146 |
| `mypy OpenGLContext` | 598 | 111 |

Those numbers describe the **older half** of the package almost exclusively. The
sub-packages written in the recent eras are already clean:

| Clean of ruff findings | Carrying them |
|---|---|
| `audio/`, `character/`, `edit/`, `nav/`, `packaging/`, `physics/`, `telemetry/`, `testing/`, `ui/`, `viewer/`, `__pyinstaller/`, `loaders/gltf/`, `loaders/tiles3d/`, `scenegraph/terrain/`, `scenegraph/vegetation/`, `scenegraph/water/` | `debug/` (238), `scenegraph/text/` (443), `passes/` (176), `events/` (144), `bin/` (131), the top-level modules (565), the legacy geometry nodes |

**Ruff-clean and mypy-clean are different sets.** Clean of *both* today:
`audio/`, `edit/`, `nav/`, `packaging/`, `physics/`, `telemetry/`, `testing/`,
`__pyinstaller/` and `scenegraph/water/`. `ui/` (23 errors),
`loaders/tiles3d/` (11), `loaders/gltf/` (8) and `scenegraph/terrain/` (4) are
ruff-clean with a small typing backlog, most of it `no-any-return` from numpy's
stubs. `physics/` counts as clean under the `warn_return_any` override the
package config already documents for it.

So this is not a package-wide quality question. It is a backlog concentrated in
the fixed-function and VRML97 modules, and the value of clearing it is that the
tools become **usable as gates** — today a real defect arrives in a report of
three thousand lines and is not seen.

## What is a defect and what is noise

Of the 3,288 ruff findings, **2,459 are `F403`/`F405`** — the star imports, in 75
files. [CLAUDE.md](../CLAUDE.md) settles what happens to those: star imports are
traditional here and old code is not to be churned out of them. They are
therefore **noise to be scoped, not code to be rewritten** (step 1).

Of the 598 mypy errors, three mechanical causes account for 375:

| Cause | Errors | Cleared by |
|---|---|---|
| `from OpenGL.GL import *` — every constant and entry point is invisible | 303 (202 in `debug/state.py` alone) | step 6 |
| `OpenGLContext/arrays.py` re-exports through a star from an untyped package, so **no** name is visible through it | 62, across 26 files | step 3 |
| `method = classmethod(method)` after the `def`, which mypy does not follow | 10 | step 2 |

That leaves roughly 220 errors that are worth reading one at a time, and a
sample of them (`physics/road.py`, `move/physicswalk.py`, `scenegraph/pbrmesh.py`)
are narrowing limits rather than faults: mypy cannot carry an `is not None` check
through an attribute, and a local binding satisfies it.

## Step 0 — the defects, landed 2026-08-22

Seven runtime faults, each found by one of the two tools, each fixed Red/Green
with a test in
[tests/unit/test_legacy_error_paths.py](../tests/unit/test_legacy_error_paths.py):

| Site | What happened |
|---|---|
| `scenegraph/inline.py:78` | The "no URL loaded" path called `warnings.warn` with no `warnings` imported, so an `Inline` whose URLs all failed raised `NameError`. Reports through the module logger now, as its sibling `ImageTexture` does. |
| `events/timer.py:56,70` | `"…NULL getTimeManager() result" % (context)` on a string with no placeholder: registering a `Timer` against a context with a null time manager raised `TypeError` instead of `ValueError`. The message names the context now. |
| `loaders/base.py:37`, `scenegraph/shaders.py:158` | `raise NotImplemented(...)` — not callable, so the abstract-method path raised `TypeError: 'NotImplementedType' object is not callable`. |
| `loaders/base.py:30,33` | `raise ValueError("…%s", baseURL)` — a comma where a `%` was meant, so the message was a tuple; and the sibling `log.warning` had a placeholder and no argument for it. |
| `loaders/base.py` `isGzip` | The magic number was compared as `str` against bytes read from a binary handle, so it never matched and a gzipped scene reached the parser still compressed. `.wrl.gz` files load. |
| `events/wxevents.py:59`, `scenegraph/boundingvolume.py:393`, `scenegraph/inline.py:76` | Loop variables named `wx`, `node` and `context`, each shadowing the module of that name for the rest of its function. |
| `quaternion.py:82` | A mutable list as the identity quaternion's default argument. |

Landed with them: [tests/unit/test_lint_gates.py](../tests/unit/test_lint_gates.py),
which runs `ruff` over the package for the **rule families that are now clear**
(`B006`, `F402`, the `%`-format and `.format` checks, `F821`, `F901`) and fails if
one comes back. Each step below adds its rules to that list; the list reaching
the full `E`/`W`/`F`/`B` set is what finishes this plan.

## Step 1 — scope the star-import noise

Add `per-file-ignores` for `F403`/`F405` covering the 75 files that use star
imports, with a comment saying why (the convention, and that these are the
modules it applies to). 2,459 findings leave the report and **829 remain**, which
is a report a person can read.

The entry is a list of paths rather than a blanket ignore, so a *new* file cannot
quietly acquire a star import and disappear from the checks.

## Step 2 — `@classmethod` for the 21 old-style bindings

`method = classmethod(method)` after the `def` is the pre-decorator idiom, in 21
places across 11 files (`scenegraph/text/fontprovider.py` ×5, then pairs in the
four backend context modules, `events/eventmanager.py`, `events/mouseevents.py`
and `loaders/vrml97.py`, and singles elsewhere). Converting to the decorator clears
the 10 `call-arg` errors, which are all of the form *Missing positional argument
"cls" in call to "ContextMainLoop"* and are read by anyone typing the file as a
real bug. Mechanical and independently verifiable per file.

While in those files: `super(Class, self)` (136 calls in 56 files) and
`class X(object)` (73) are the same era. Neither produces a finding, so neither
is urgent; take them per file when a file is open for another reason.

## Step 3 — make `OpenGLContext/arrays.py` visible to mypy

`arrays.py` is a docstring and `from vrml.arrays import *`. `pyvrml97` ships no
`py.typed`, so mypy treats the module as empty and every name reached through it
— `array`, `dot`, `zeros`, `allclose` — is *"Module "OpenGLContext.arrays" has no
attribute"*, 62 times across 26 files.

Adding `from numpy import *` above the existing line makes numpy's names visible
while pyvrml97's own additions still win, since they are imported second. No
caller changes.

**Sequence this with the work it uncovers.** Measured: the change clears 59 of
the 62 errors and reveals **150 more** that were hidden behind `Any` — mostly
`assignment`, in the modules that do array arithmetic. That is the point of the
change, but it means step 3 is "fix `arrays.py` *and* the package it exposes",
one sub-package at a time, not a one-line commit. Doing it per sub-package keeps
each piece reviewable.

The alternative — a `py.typed` marker in `pyvrml97` — is a sibling-project change
with the same effect and wider reach. Worth taking if that project is open for
other work.

## Step 4 — the formatting families

`W291`/`W293`/`W292` (460 findings), `E703` (41, of which 37 are in
`scenegraph/box.py`), `E401`, `E402`, `E713`, `E712`. All mechanical; `ruff
check --fix` and `ruff format` do the work.

**One sub-package per commit**, so the diff stays reviewable and a formatting
change is never mixed with a behaviour change. Run the suite after each.

## Step 5 — the findings that need reading

These are neither noise nor mechanical. Each wants someone to decide what the
code was for:

| Finding | Count | What to look for |
|---|---|---|
| `F401` unused import | 145 | Some are re-exports other modules rely on. Check each importer before removing. |
| `F841` unused variable | 44 | Roughly half are `except X as err` with an unused `err`. The rest are dead state — `scenegraph/interpolators.py` computes `start, stop` and `previous` in two methods and reads neither. |
| `B007` unused loop variable | 38 | 15 in `passes/_flat.py`. Usually a rename to `_name`; occasionally a loop that meant to use it. |
| `B905` `zip()` without `strict=` | 10 | Each one is a decision about whether a length mismatch is a bug. `scenegraph/material.py` and `polygontessellator.py` pair arrays that should match. |
| `B904` `raise` inside `except` without `from` | 4 | `glfwcontext.py`, `pygamecontext.py`, `scenegraph/shaders.py` ×2 — the backend import errors, where the original cause is what a user needs. |
| `B018` useless expression | 3 | Two are deliberate: a bare name probing for `NameError` (`polygontessellator.py`, `arraygeometry.py`). A comment and a `# noqa` state that; the third wants reading. |
| `B008`, `B010`, `B028` | 3 | One each in `text/_toolsfont.py`, `cubebackground.py`, `indexedlineset.py`. |

Mypy has its own short list of "read this one":

- `debug/logs.py:15` — `"type[Logger]" has no attribute "getTraceback"`.
- `ui/overlay.py:273`, `viewer/sceneviewer.py:733,742` — a mix-in calling methods
  its host provides. Real at run time; a `Protocol` for the host is what makes it
  checkable.
- `scenegraph/imagetexture.py:212,295` — classes defined twice under a
  PIL-present branch. Intentional; needs stating so it is not read as a mistake.
- `bin/gltf_demo.py:446-456` — six attributes set on `ViewerOptions` from outside
  the class. They belong on it.

## Step 6 — `debug/state.py` and the GL star imports

`debug/state.py` is 202 of the 303 `name-defined` errors: it is a table of
`glGet` constant names reached through `from OpenGL.GL import *`. A generated
table, or one import of the constants it names, removes the whole family from the
report and makes the file's subject legible.

The other GL-star files are covered by step 1 for ruff. For mypy they need the
same treatment as `arrays.py` — and PyOpenGL's own typing is the limit there, so
this is the step to take last and the one most likely to end in a documented
`per-module` mypy setting rather than a fix.

## Step 7 — `py.typed`

The package has no PEP 561 marker, so a project built on the engine gets no types
from it whatever we do here. Add it once a sub-package boundary can be named as
typed; it is not honest before that.

## Step 8 — the gate in CI

`.github/workflows/` runs `pages.yml` and `release.yml`. Add a job that runs, on
every push:

- `ruff check` for the rule families in `tests/unit/test_lint_gates.py`,
- `mypy` over the nine sub-packages that are clean of both today.

Both already pass, so the job is green the day it lands and stays that way. It
grows as the steps above complete, which is what keeps the cleared work cleared.

## Not doing

- **Removing star imports from old code.** [CLAUDE.md](../CLAUDE.md) settles it:
  new code is explicit, old code is left alone. Step 1 scopes the reporting
  instead.
- **Blanket `# type: ignore` or a widened `[[tool.mypy.overrides]]`.** The
  `physics.*` `warn_return_any` override exists for one measured reason (numpy
  arithmetic is `Any` in the shipped stubs) and is not a pattern to copy for
  making a number go down.
- **`--unsafe-fixes`.** 172 findings offer one. Each is a judgement about what
  the code meant; step 5 is where they get made, by hand.

## Verification

Every step: the full unit suite green, `ruff` and `mypy` clean on the files
touched, and the rule the step clears added to `tests/unit/test_lint_gates.py`
in the same commit. A step that clears a rule family without adding it to the
gate has not finished — the gate is the part that makes it stay cleared.
