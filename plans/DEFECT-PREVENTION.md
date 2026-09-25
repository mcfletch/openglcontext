# Defect prevention: gates for the defect classes the reviews keep finding

Status: Parked. Items 1 to 6 of the order of work are done, and item 7 in every project but openglcontext and pyopengl; what is pending is under [Parked, 2026-09-25](#parked-2026-09-25).

## Why

Eighteen review documents across the workspace hold about 1,150 findings. The
2026-09-25 review alone had 496. Most of them fall into 30 recurring classes,
and many of those classes were found again review after review because nothing
between reviews stops them. This plan gives each class a mechanism that
catches it at the edit that introduces it. A class that no mechanism can catch
gets a written rule and a test convention instead.

The catalogue behind this plan is [DEFECT-CATALOGUE.md](DEFECT-CATALOGUE.md)
(one section per class: definition, recurrence per review with finding codes,
where the fix landed, and how detectable it is). The tool measurements are
summarised in [Tooling](#tooling-measured-on-this-tree).

## Requirements

- Deterministic. A check decides from the syntax tree, the symbol table or the
  types, never from regular expressions over source text. The same input gives
  the same answer every time, and a clean result means the shape is absent.
- Fast. After an edit, all the static gates together finish in about a second.
  A cold run of every gate over the whole workspace finishes in well under a
  minute.
- Shareable. The rules ship as a package with a stable rule code per check,
  so openglcontext, the libraries, the games and applications built on the
  engine all run the same rules. Nothing GPL or LGPL is a dependency.
- Enforce the sanctioned API. Where a class has a fix that landed as one
  engine API (the table under [Per-class plan](#per-class-plan)), the check
  flags the raw form and points at that API. A rule nobody can satisfy without
  an allowlist entry is the wrong rule.
- Adopt without a flag day. Each rule starts as a report with a recorded
  baseline count per project, and joins the failing gate once a project is
  clean of it. openglcontext's `tests/unit/test_lint_gates.py` already works
  this way for ruff rules.

## Evidence: the classes by size

| Class | Findings (about) | Reviews | Static detection |
|---|---|---|---|
| Documentation contradicting the code, missing or pointing nowhere | 154 | 18 of 18 | references and list completeness only |
| Algorithm and specification errors | 118 | 15 | no; conformance and differential tests |
| Dead code and duplication within a project | 106 | 16 | dead code yes; duplication partly |
| Tests that cannot fail, untested or ungated code | 77 | 16 | syntactic shapes and gate coverage |
| Memo missing an input, or not reset | 51 | 8 | no; test convention |
| Redundant per-frame work | 48 | 9 | hot-path imports only |
| Numeric robustness | 45 | 12 | no; property tests |
| Typing that does not check | 40 | 9 | yes |
| Frame cost that grows with scene size | 39 | 10 | no; scaling tests |
| Unchecked document values | 37 | 10 | yes (AST and types) |
| Dependency floors and packaging contents | 36 | 12 | yes, by execution |
| Module boundary violations | 32 | 11 | yes |
| Prose that breaks the writing rules | 31 | 4 | lexical signs only |
| Swallowed or misreported errors | 28 | 12 | yes |
| Lint and format | 28 | 11 | yes |
| Unconfined paths and URLs | 25 | 8 | yes (sinks by AST, flow by types) |
| C-boundary memory and error safety | 25 | 7 | partly (compiler, sanitisers) |
| Inert declarations | 24 | 9 | parameters yes; fields partly |
| Engine capability outside the engine | 23 | 3 | partly |
| GL and frame state not restored | 22 | 7 | yes, through context-manager APIs |
| Identity-keyed state | 21 | 11 | yes for `id()` keys |
| Configuration read at the wrong time | 19 | 9 | yes |
| Resources without an owner | 18 | 6 | partly; GL in `__del__` yes |
| Non-atomic or destructive writes | 14 | 5 | yes |
| Shared mutable defaults and aliasing | 14 | 6 | yes |
| Optional frame layer without isolation | 12 | 5 | partly |
| Thread safety | 11 | 5 | partly, through a guarded-value type |
| Unbounded accumulation | 10 | 6 | partly |
| Logic hidden in window-bound code | 9 | 4 | pragma count yes |

The largest classes are the least detectable, and the classes the 09-25 review
named as cross-cutting are mostly detectable. So the plan has two halves:
static gates for the classes holding about a third of the findings, and test
conventions plus written rules for the rest.

## Tooling measured on this tree

Measured on 2026-09-25 on this machine (32 cores) against
`openglcontext/OpenGLContext` (514 files, 138k lines):

| Option | Licence | Whole tree | One file | Shared as | Verdict |
|---|---|---|---|---|---|
| ruff built-in rules, `banned-api` (TID251) | MIT | 0.02 s | 0.01 s | configuration | use; enable more rules |
| An extended ruff: our rules in Rust, in a fork | MIT | as ruff | as ruff | our own ruff wheel | not now; see below |
| Stdlib `ast` rule package | stdlib | 0.65 s (0.21 s on 8 processes) | 0.04 s | an ordinary package | use for the syntactic rules |
| Fixit 2 (LibCST) | MIT | 2.7 s | 0.3 s | package | adequate; slower, autofix |
| flake8 plugin | MIT | 6.7 s (1.1 s on 8) | 0.09 s | entry point | adequate; slow |
| pylint checker | GPL-2.0+ / astroid LGPL | 10.3 s | 0.22 s | package | no (licence) |
| semgrep CE | LGPL-2.1+ | 1.7 s | 0.9 s | YAML | no (licence) |
| ast-grep | MIT | 0.05 s | < 0.01 s | a rules directory | possible; no package entry point, no symbol table |
| mypy with `NewType`s and a plugin | MIT | 14.5 s cold | 0.1 s through `dmypy` | plugin module | use for the flow classes |
| pyright / basedpyright | MIT | 22 s | 0.6 s | no plugins | only adds `LiteralString` enforcement |
| ty | MIT, beta | 0.57 s | fast | no plugins | watch |

The two prototype rules (a bare conversion of a `.get()` result, and `id()`
used as a key) found the same 124 sites in every framework, so the frameworks
differ in speed, licence and sharing, not in what they find.

### The extended ruff

Ruff has no plugin interface: its rules are compiled into the binary. Our
classes as ruff rules would mean a fork, each rule a Rust `Violation` plus a
function over ruff's semantic model, registered in three places (`codes.rs`,
the dispatch in `checkers/ast/analyze/`, the rule module), with a snapshot
test. The most recent upstream rule touched 8 files and added 363 lines, 141
of them the rule itself.

What a ruff rule can see: the syntax tree, scopes and bindings, references,
import-resolved qualified names, and a few same-file type guesses. It sees
one file at a time and has no types from other modules.

The costs:

- Upstream moves fast. 1,001 commits in two months, a release about weekly,
  `codes.rs` changed 12 times in that span, and the internal rule API itself
  changed. A fork rebases every week or falls behind the ruff every user
  already has.
- Distribution. Each release is 17 platform wheels of about 10 MB, built from
  a 53-crate workspace. No Rust toolchain is installed in this container.
- Users would swap their ruff for ours, which puts our release cadence
  between them and upstream's fixes.
- It does not reach the classes that need types across modules (a path's
  provenance, a document value's travel through attributes, `Any` flowing
  through APIs). Those need mypy either way.

The speed it would buy is already available: the stdlib `ast` package checks
one changed file in 0.04 s. The plan therefore writes the rules in Python,
with ruff-style codes and the same suppression syntax, so that if an upstream
plugin interface appears (the ruff project has discussed one) or a rule proves
generally useful, porting it to Rust or proposing it upstream is a
translation, not a redesign. Rules that are useful beyond this workspace
(`id()` as a dictionary key, GL calls in `__del__`, a skip inside an `except`
in a test) are candidates for upstream ruff proposals in their own right.

## The design

Four layers. Each catches what the one before cannot.

### 1. Ruff, with more of its own rules

Enable, per project, through the existing ratchet
(`tests/unit/test_lint_gates.py` in openglcontext, and the same list in each
project's `pyproject.toml` once clean):

| Rule | Class it serves | openglcontext hits today |
|---|---|---|
| PGH003, PGH004 (ignores and noqa with a code) | typing | 0: enable now |
| PLE0604, PLE0605, F822 (bad `__all__` entries) | module boundaries | 0: enable now |
| RUF100 (unused noqa) | lint | 31 |
| DTZ (naive datetimes) | determinism | 4 |
| RUF012 (mutable class default without `ClassVar`) | shared mutable defaults | 76 |
| S110, S112, E722, BLE001 (swallowed errors) | swallowed errors | 67 / - / - / 216 |
| TRY400 (error without traceback in a handler) | swallowed errors | not measured |
| PLC0415 (import inside a function) | per-frame work | 684 (173 in `passes/`) |
| SLF001 (private member access) | module boundaries | 143 |
| ARG (unused arguments) | inert declarations | 536 |
| S202, S301, S307, S102, S310 (unsafe archive, pickle, eval, exec, url scheme) | unconfined paths, deserialisation | not measured |
| UP006, UP007, UP035 | lint | not measured |
| TID251 banned-api, with the ban list below | several | the ban list decides |

A deliberate exception is written as `# noqa: CODE reason`. The reason text is
required; the checker in layer 2 holds every `noqa` and `type: ignore` to
that.

The `banned-api` list (TID251) resolves names through imports, so it is
deterministic. It names the raw form and the message names the sanctioned
API. Each project's list is the workspace list plus its own additions, and
the modules that implement the sanctioned API are exempt by
`per-file-ignores`:

| Banned | Use instead | Exempt modules |
|---|---|---|
| `urllib.request.urlopen`, `urlretrieve` | `loaders.resolver.Resolver`, `AllowedHosts.open_url` | `loaders/resolver.py`, `contentpacks/fetch.py` |
| `tarfile.TarFile.extractall`, `zipfile.ZipFile.extractall` | `contentpacks.archive.extract` | `contentpacks/archive.py` |
| `shutil.rmtree`, `shutil.move`, `os.rename` | `atomicfiles.replace_directory`, `staged_directory` | `atomicfiles.py` |
| `os.environ`, `os.getenv` | `renderoptions.env_flag_once` / `env_number_once`, or the project's one settings module | `renderoptions.py`, settings modules, `testing/` |
| `time.time` in demos and games | `events.systemtime.systemTime` | the clock module |
| `os._exit` | `flush_and_exit` | the exit helper |
| `pickle.load`, `marshal.loads` | none | none |

Ruff cannot ban a builtin (`builtins.open` resolves to nothing), which is one
reason for layers 2 and 3.

### 2. `openglcontext-checks`: a stdlib `ast` rule package

A new sibling project, BSD, depending on nothing but the standard library, so
a user's project installs it without pulling the engine. It provides:

- `oglc-check [paths]`, which checks the named files, or the files changed
  since its last run (a per-project cache of file hash to result, so an
  unchanged file is not parsed again).
- Rule codes `OGC` plus three digits, grouped by class, each with a
  one-paragraph description, `VALID` and `INVALID` examples that are also its
  unit tests (Fixit's convention, without Fixit), and a pointer to the
  sanctioned API.
- Suppression by `# noqa: OGC101 reason` on the line, with a reason required,
  so ruff's RUF100 and this package agree on the syntax.
- Configuration in `[tool.openglcontext-checks]` in `pyproject.toml`: rule
  selection, per-path scopes (which modules count as "loader", "pass", "test",
  "demo"), and the exempt modules, the same shape as ruff's.
- A pytest entry point, so a project that already runs its suite gets the
  rules as one parametrised test per rule, and `tools/preflight.py` gains a
  `checks` gate per project.

The rules. Each looks at a syntax tree with a symbol table of the file
(imports, bindings, scopes); none reads source text.

| Code | Rule | Class | Shape it flags |
|---|---|---|---|
| OGC101 | bare conversion of a document value | unchecked document values | `float`/`int`/`bool` over a subscript or `.get()` call, in a module in the `loader` or `hook` scope, outside `documentvalues` |
| OGC102 | decode before a size check | unchecked document values | `b64decode`, `zlib.decompress`, Draco decode, `np.frombuffer` sized by a subscript, with no comparison against a cap on that value earlier in the function |
| OGC111 | raw opener on a non-literal path | unconfined paths | `open`, `Image.open`, `np.load`, `io.open` whose path argument is neither a literal nor the direct result of a sanctioned resolver call, in engine and library code |
| OGC121 | write in place | non-atomic writes | `open(..., 'w'/'wb'/'a'/'x')`, `Path.write_text`/`write_bytes`, `json.dump` to a handle not from `atomicfiles.staged_file`, outside `atomicfiles` and outside `tempfile` directories |
| OGC131 | `id()` as a key | identity-keyed state | `id(x)` used as a subscript, dict key, set member, or assigned to an attribute, where the same statement does not also store `x` |
| OGC132 | context-keyed table with no loss hook | identity-keyed state | a module-level dict whose keys come from `context_key()` or `getCurrentContext()` in a module that never calls `on_context_lost` |
| OGC141 | GL in `__del__` | resources without an owner | any call resolving to `OpenGL.GL.*` inside `__del__` |
| OGC142 | unowned GL allocation | resources without an owner | `glGen*`, `glCreate*` in a class that neither derives from `PassResources` nor defines `dispose`/`release`/`disposeResources` |
| OGC151 | raw GL state change in pass code | GL state not restored | `glEnable`, `glDisable`, `glBindFramebuffer`, `glScissor`, `glUseProgram`, `glCullFace` in the `pass` scope outside the state module, where no `try/finally` or `with` in the same function restores it |
| OGC161 | work at import | configuration timing | module- or class-level statements other than definitions, imports, literals, `logging.getLogger`, `TypeVar`, `NamedTuple`, `re.compile`, dataclass fields with literal or `field(default_factory=...)` defaults; any `os.environ`/`sys.argv` at module scope |
| OGC171 | state patched onto a class | shared mutable defaults | `cls.__dict__.setdefault`, `type(self).x = ...` |
| OGC181 | optional layer called unguarded | optional layer isolation | a call to a method a pass lists in its `OPTIONAL_LAYERS` from `Render`/`renderShared`, not through `LayerGuard.run` |
| OGC191 | broad handler without a traceback | swallowed errors | `except Exception`/`BaseException` whose body logs without `exc_info` and does not re-raise |
| OGC201 | ignore without a reason | typing | `# type: ignore[code]` or `# noqa: CODE` with no reason text after it |
| OGC202 | `Any` in a public signature | typing | a parameter or return annotated `Any` on a name in `__all__` (or public by name when the module has no `__all__`) |
| OGC211 | `__all__` incomplete | module boundaries | a name imported by another module of the same package from a module whose `__all__` does not list it |
| OGC221 | skip inside an `except` | tests that cannot fail | `pytest.skip`, `pytest.xfail`, `pytest.importorskip` of a first-party module inside an `except` body, in the `test` scope |
| OGC222 | test with no assertion | tests that cannot fail | a `test_*` function with no `assert`, no `pytest.raises`/`warns`, and no call to a function whose name starts `assert` or `check` |
| OGC223 | `pass` in a test's handler | tests that cannot fail | `except ...: pass` in the `test` scope |
| OGC231 | accumulation with no removal | unbounded accumulation | a `self` or module-level container appended to or written by key in a method, with no `pop`, `clear`, `del`, `popleft`, slice assignment or `maxlen` on it anywhere in the class or module |
| OGC241 | window pragma over logic | logic in window-bound code | a `# pragma: no cover` block marked window or GL whose body branches on values that are not GL results; plus a per-project count ratchet of such pragmas |
| OGC251 | command without a parser | inert declarations | a console-script entry point (from `pyproject.toml`) whose function does not construct an `ArgumentParser` or call one that does |

OGC101, OGC111, OGC121 and OGC151 flag a raw form that has one sanctioned
replacement, so their messages name it, and their exempt list is the
implementing module. OGC131, OGC141, OGC191, OGC201, OGC221 to OGC223 are
general Python hygiene and are the candidates to propose to upstream ruff.

### 3. Types that must be unwrapped

For the classes where the question is where a value came from, the type says
so. A sink accepts only the checked type, and the only way to get one is the
function that does the check. A plain `str` handed to a loader's open helper
is then a type error in mypy, in the editor and in every user's project.

The public API does not change. The entry points a caller uses (`load`,
`Resolver.fetch`, a node's `url` field, `oglc-view`'s argument) keep taking a
string or URL, and each is the one place that string passes through the
restrictions: it contains the path or checks the URL, and hands the checked
type down. Everything below it (the format loaders, the readers of a file a
document names, the image and array openers) takes only the checked type. A
user's code keeps passing strings; a lower-level function inside the engine,
or in a user's own loader built on these, cannot be handed an unchecked one.

A `NewType` is not enough on its own: the measurement showed mypy, pyright
and ty all accept `ContainedPath(x)` written anywhere. So each checked type is
a small runtime class whose constructor is private, with the mypy plugin
refusing a direct construction outside its home module:

```python
class ContainedPath(str):
    """A path the resolver has held to its base: under it, no `..`, no link out."""
    __slots__ = ()

def contain(base: str, name: str) -> ContainedPath: ...   # the only producer

def open_contained(path: ContainedPath, mode: str = 'rb') -> BinaryIO: ...
```

| Type | Produced only by | Accepted by | Class |
|---|---|---|---|
| `ContainedPath` | `Resolver.contain`, `tiles3d.fetch.beside`, `local_copy` | the loaders' open helpers, `Image` loading, `np.load` wrappers | unconfined paths |
| `CheckedURL` | `AllowedHosts.check`, `Resolver` | `open_url`, the fetch helpers | unconfined paths |
| `JSONObject = Mapping[str, object]` | the JSON-reading entry points | nothing; `object` must be narrowed | unchecked document values |
| `DocumentNumber` and friends | `DocumentValues.number` / `integer` / `flag` / `choice` / `vector` | node fields set from documents | unchecked document values |
| `ContextKey` | `contextresources.context_key` | per-context tables | identity-keyed state |
| `GLName` subclasses (`TextureName`, `FramebufferName`, `BufferName`, `ProgramName`) | owning wrappers that register with the pass or context on construction | the draw and bind helpers | resources without an owner |
| `Guarded[T]` | constructed with its lock | `with guarded as value:` only | thread safety |

`JSONObject` is the cheapest and widest: once the readers return
`Mapping[str, object]` instead of `Any`, mypy refuses `float(value)` on an
`object` until the code narrows it, and `DocumentValues` is the narrowing.

The mypy plugin ships in `openglcontext-checks` (a user adds one line to
`[tool.mypy] plugins`). Measured at 35 lines for the prototype, it hooks
`get_function_hook` to refuse direct construction of the checked types outside
their home modules, and to refuse `builtins.open` in scoped modules. It must
chain to mypy's own `open` hook so the return type stays exact.

`LiteralString` (PEP 675) would express "a string written in the source" for
paths and shader names, but mypy does not enforce it; pyright and ty do. It is
not relied on.

Runtime backstop: `OpenGLContext.testing.plugin` installs a `sys.audit` hook
for the session that records every `open` event and fails the test when a file
is opened from a module outside the sanctioned openers. It costs about 0.6 µs
an open (20,000 opens took 0.083 s against 0.070 s). Because it lives in the
engine's pytest plugin, projects built on the engine get it too.

### 4. Run after every edit

| Step | Cost after an edit | Cold |
|---|---|---|
| `ruff check` on the changed files | 0.01 s | 0.02 s per project |
| `oglc-check` on the changed files | 0.04 s | 0.65 s per large project |
| `dmypy run` (daemon, per project) | 0.1 s; 1.4 s for a widely imported interface | 14.5 s for openglcontext |

About 0.2 s in the common case. The editor runs these through a Claude Code
`PostToolUse` hook on `Edit`/`Write` (configured with the `update-config`
skill), reporting failures as feedback on the edit that caused them; the same
command runs as a git pre-commit hook for anyone not using the assistant;
`tools/preflight.py` runs the whole tree cold as today. `dmypy` keeps the
state of `.preflight-venv`'s non-editable installs; its daemon is started per
project on first use and restarted when `--rebuild-env` rebuilds the
environment.

## Per-class plan

For each class: what catches it, the sanctioned API where there is one, and
for the classes no static tool reaches, the test convention and the written
rule. Test conventions become fixtures and helpers in
`OpenGLContext.testing`, so an application's suite uses the same ones.

| Class | Mechanism | Sanctioned API |
|---|---|---|
| Unchecked document values | OGC101, OGC102; `JSONObject` and the `Document*` types | `loaders.documentvalues.DocumentValues`, `bounded` |
| Unconfined paths and URLs | TID251 on openers; OGC111; `ContainedPath`, `CheckedURL`; audit hook in tests | `Resolver`, `tiles3d.fetch.beside` / `local_copy`, `AllowedHosts.open_url` |
| Non-atomic or destructive writes | OGC121; TID251 on `rmtree`/`move`/`rename` | `OpenGLContext.atomicfiles`; `tools/atomicwrite.py` for the root tools |
| Identity-keyed state | OGC131, OGC132; `ContextKey` | hold the object; `WeakKeyDictionary`; `contextresources` |
| Memo missing an input | test convention: a `memo_inputs` helper that takes a memo's declared inputs, edits each in turn and asserts the answer changes; the cache rule in `openglcontext/CLAUDE.md` | generation counters bumped by field observers; `vrml.cache` holders with `depend` |
| Resources without an owner | OGC141, OGC142; `GLName` wrappers | `passes/disposal.PassResources`, `let_go`; node `dispose()` |
| GL and frame state not restored | OGC151; state context managers | `passes/framestate.FrameState`; `set_cull_state`; context managers to add (`gl_state.enabled`, `bound_framebuffer`) |
| Configuration read at the wrong time | OGC161; TID251 on `os.environ` | `renderoptions.env_flag_once` / `env_number_once`; `contentpacks.Application` |
| Shared mutable defaults | RUF012; OGC171; `ClassVar`, `Final`, `MappingProxyType` | per-instance initialisation; factory functions |
| Optional layer without isolation | OGC181 over each pass's declared `OPTIONAL_LAYERS`; test convention: a layer that always fails is driven for N frames and asserts the frames it asks for are bounded | `passes/layerguard.LayerGuard` |
| Swallowed errors | E722, BLE001, S110, S112, TRY400; OGC191 | narrow the catch; `log.exception` or `exc_info=True` |
| Redundant per-frame work | PLC0415; test convention: a still scene drawn twice, the second frame's allocations and uploads counted from `renderstats` and held at a floor | `InstanceBuffer`, `build_mesh_gpu`, `ViewPrograms` setup |
| Frame cost that grows with scene size | test convention under `serial`: a `scaling` helper times or counts a subsystem's work at n and 4n objects and asserts the ratio | spatial indices, vectorised passes |
| Unbounded accumulation | OGC231 | `collections.deque(maxlen=...)` for recordings; drained logs |
| C-boundary safety | `-Wall -Wextra -Werror` in the C builds; Cython `boundscheck`/`wraparound` on in debug builds; an ASan/UBSan CI job for pyopengl and opengl_decimate; the existing rule that a crash stops the work | `pygl_runtime.c` helpers |
| Inert declarations | ARG; a field-use check (a node or option class's declared fields against every attribute read in the package) as OGC252 after OGC-1xx; OGC251 | wire it or remove it |
| Typing that does not check | PGH003, OGC201, OGC202; mypy `enable_error_code = ["ignore-without-code", "possibly-undefined", "mutable-override", "explicit-override"]`, `warn_unused_ignores`; a configuration test per project (mypy settings present, `python_version` equal to the floor, `py.typed` shipped) | typecheck in `.preflight-venv` |
| Module boundary violations | SLF001; OGC211; naming rules per module family (pep8-naming, scoped) | public methods for what was reached into |
| Logic in window-bound code | OGC241 and its pragma ratchet | plain objects fed by a thin window class |
| Thread safety | `Guarded[T]` where adopted; a free-threaded CPython CI row; TSan on the C extensions | `with_world()`, `flush_events()` |
| Tests that cannot fail | OGC221 to OGC223; a skip budget per project (the number of skips with their reasons, failing when it rises) | `testing/display.py` as the one availability check |
| Untested or ungated code | a workspace test that every project is in `verify-everything.py`, `preflight.toml` and CI, and every declared tool configuration is run by a gate; diff coverage on changed lines | `tools/preflight.py` |
| Dependency floors and packaging | a preflight environment resolved at the declared minimums (`uv pip install --resolution lowest-direct`) running each suite; `vermin` for stdlib APIs newer than `requires-python`; the artifact check against the tree | `scripts/check_release_artifact.py`, `test_what_the_wheel_ships.py` |
| Documentation missing or pointing nowhere | extend `tests/unit/test_documentation_references.py` to every project, to `.rst` pages, shader comments and `CLAUDE.md`; completeness tests: every public module in the directory map and `structure.rst`, every console script, environment variable and extension documented, a changelog entry for every version bump | generated pages where the code is the source of truth (`renderoptions.ENVIRONMENT`) |
| Documentation contradicting the code | doctests collected (`--doctest-modules`); README code blocks run; option, default and environment tables generated from or tested against the code; otherwise the written rule that documentation ships with the change | |
| Prose that breaks the writing rules | the `ai-isms` scanner in preflight as a report; it reads text, not structure, so it reports rather than fails, except for the one lexical form that is unambiguous (a review finding code in a docstring or comment) | `.claude/skills/ai-isms` |
| Numeric robustness | property tests (hypothesis) over zero, negative, huge and non-finite inputs for each numeric entry point; `np.seterr(all='raise')` for the test session | `documentvalues.bounded`; local origins for far-from-origin geometry |
| Algorithm and specification errors | conformance suites against each specification's sample assets; differential tests between every pair of implementations of one API; every geometry path rendered under a mirroring transform | `scenegraph/winding.py` |
| Engine capability outside the engine | SLF001 in demo and game packages; a clone detector over the workspace at a threshold, as a report | the first rule of the workspace `CLAUDE.md` |
| Dead code and duplication | F401 and F841 on (openglcontext ignores F401 today); `vulture` at a confidence threshold as a report; a formula needed in GLSL and Python held by a test comparing the two | one copy, in the layer that owns it |

## Written rules and skills

Where a class cannot be caught mechanically, the rule goes where the work is
done:

- `openglcontext/CLAUDE.md` gains a section "Before a change is finished",
  one line per non-static class, each naming its test convention. The cache
  rule (already there) is the model: a rule and the test that holds code to
  it.
- A `/defects` skill in `.claude/skills/`: given a diff, it lists which
  classes the diff can introduce (it touches a memo, a per-frame method, a
  numeric entry point, a second implementation of an API) and which test
  convention each needs. It runs `oglc-check`, ruff and `dmypy` first, so the
  reviewer's attention goes to what the tools cannot see.
- The review template (for the next review) tags every finding with its class
  from [DEFECT-CATALOGUE.md](DEFECT-CATALOGUE.md). A finding in a class that has a gate is also a
  defect in the gate, and the review says which rule missed it.

## Order of work

1. Ruff rules at zero hits today (PGH003, PGH004, PLE0604, PLE0605, F822) into
   every project's selection. Record the per-project baseline of the others.
2. `openglcontext-checks` with its runner, configuration, suppression, cache,
   pytest entry point and preflight gate, and the first rules: OGC131, OGC141,
   OGC161, OGC201, OGC221 to OGC223 (general, low false-positive, small
   baselines).
3. The sanctioned-API rules with their ban lists: OGC101, OGC111, OGC121,
   OGC151, and TID251 in every project. Clear the baselines project by
   project.
4. The checked types: `JSONObject` first (widest effect for least code), then
   `ContainedPath` and `CheckedURL` with the mypy plugin, then `ContextKey`
   and the `GLName` wrappers.
5. The post-edit hook and `dmypy`, once steps 1 and 2 are fast and quiet.
6. The test-convention helpers in `OpenGLContext.testing`: `memo_inputs`,
   still-frame counts, `scaling`, the failing-layer driver, the audit hook,
   `np.seterr`, and the mirrored-render helper.
7. The remaining ruff ratchets (RUF012, BLE001/S110, PLC0415, SLF001, ARG) as
   each project reaches zero.

Each step lands with its tests, its documentation (a page in
`openglcontext/docs/` for the checks and types, since users run them too) and
its preflight declaration.

## Baseline, ruff rules

Item 1 of the order of work landed on 2026-09-25: PGH003, PGH004, PLE0604 and
PLE0605 are in every project's ruff selection. The only hit was one blanket
`type: ignore` in a glisteel test, now naming `method-assign` and why. F822 is
part of the F family every project already selects. Under `--preview` it also
reports the two names `OpenGLContext/viewer/__init__.py` serves through its
module `__getattr__`; the stable rule does not, and the preview rule is not
used. The workspace root and the two `accelerate` directories declare no ruff
table and are not linted.

Hit counts for the plan's other ruff rules on 2026-09-25, each rule measured
alone over the project's lint paths with its own configuration (RUF100 against
the project's own selection, since which `noqa` is unused depends on what is
selected). The openglcontext row covers `tests/`, `scripts/` and `docbuild/`
as well as the package, so it is larger than the package-only figures in
[Tooling](#tooling-measured-on-this-tree).

| Project | RUF100 | RUF012 | S110 | S112 | E722 | BLE001 | TRY400 | PLC0415 | SLF001 | ARG | DTZ | S102 | S202 | S301 | S307 | S310 | UP006 | UP007 | UP035 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| pyopengl-glut-binaries | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pyopengl | 244 | 60 | 11 | 6 | 0 | 68 | 6 | 2136 | 354 | 393 | 3 | 2 | 0 | 6 | 1 | 0 | 14 | 0 | 11 |
| simpleparse | 0 | 4 | 0 | 0 | 0 | 6 | 0 | 6 | 14 | 44 | 0 | 1 | 0 | 0 | 1 | 0 | 16 | 4 | 0 |
| pydispatcher | 0 | 0 | 5 | 0 | 0 | 10 | 0 | 4 | 10 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 20 | 0 | 9 |
| pyvrml97 | 0 | 3 | 3 | 0 | 0 | 6 | 0 | 48 | 11 | 55 | 0 | 0 | 0 | 0 | 0 | 0 | 27 | 0 | 17 |
| ttfquery | 0 | 2 | 0 | 1 | 0 | 3 | 0 | 7 | 3 | 0 | 0 | 0 | 0 | 1 | 1 | 0 | 6 | 0 | 4 |
| opengl_extrusions | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 18 | 56 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| opengl_decimate | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 33 | 16 | 0 | 0 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0 |
| omi_physics | 0 | 0 | 1 | 0 | 0 | 7 | 2 | 48 | 93 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| omi_audio | 4 | 8 | 0 | 0 | 0 | 1 | 0 | 18 | 24 | 53 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| pyopengl-video | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 114 | 18 | 111 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| openglcontext | 254 | 127 | 80 | 3 | 0 | 278 | 30 | 2806 | 1920 | 2442 | 8 | 1 | 1 | 0 | 2 | 8 | 2262 | 54 | 782 |
| openglcontext-qt | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 14 | 10 | 18 | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 0 | 5 |
| openglcontext-editor | 3 | 6 | 0 | 0 | 0 | 0 | 0 | 315 | 36 | 100 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| openglcontext-forest-demo | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 27 | 3 | 18 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| openglcontext-marble-demo | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 82 | 61 | 39 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| openglcontext-marble-editor | 19 | 0 | 0 | 0 | 0 | 0 | 0 | 25 | 2 | 27 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| glisteel | 23 | 0 | 0 | 0 | 0 | 0 | 0 | 304 | 128 | 43 | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| glisteel-editor | 21 | 0 | 0 | 0 | 0 | 0 | 0 | 89 | 9 | 36 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| twig-bb | 69 | 9 | 1 | 1 | 0 | 7 | 0 | 302 | 146 | 238 | 0 | 0 | 0 | 0 | 0 | 0 | 412 | 2 | 152 |

A project joins a rule the day its count is 0. Rules each project is clean of
today, so could select now:

- pyopengl-glut-binaries: all of them
- pyopengl: E722, S202, S310, UP007
- simpleparse: RUF100, S110, S112, E722, TRY400, DTZ, S202, S301, S310, UP035
- pydispatcher: RUF100, RUF012, S112, E722, TRY400, DTZ, S102, S202, S301, S307, S310, UP007
- pyvrml97: RUF100, S112, E722, TRY400, DTZ, S102, S202, S301, S307, S310, UP007
- ttfquery: RUF100, S110, E722, TRY400, ARG, DTZ, S102, S202, S310, UP007
- opengl_extrusions: RUF100, RUF012, S110, S112, E722, TRY400, ARG, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- opengl_decimate: RUF100, RUF012, S110, S112, E722, TRY400, ARG, DTZ, S102, S202, S301, S307, UP006, UP007, UP035
- omi_physics: RUF100, RUF012, S112, E722, ARG, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- omi_audio: S110, S112, E722, TRY400, DTZ, S102, S202, S301, S307, UP006, UP007, UP035
- pyopengl-video: RUF012, S110, S112, E722, BLE001, TRY400, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- openglcontext: E722, S301
- openglcontext-qt: RUF012, S110, S112, E722, BLE001, TRY400, DTZ, S102, S202, S301, S307, S310, UP007
- openglcontext-editor: S110, S112, E722, BLE001, TRY400, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- openglcontext-forest-demo: RUF100, RUF012, S110, S112, E722, BLE001, TRY400, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- openglcontext-marble-demo: RUF100, S110, S112, E722, BLE001, TRY400, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- openglcontext-marble-editor: RUF012, S110, S112, E722, BLE001, TRY400, DTZ, S102, S202, S301, S307, S310, UP006, UP007, UP035
- glisteel: RUF012, S110, S112, E722, BLE001, TRY400, S102, S202, S301, S307, S310, UP006, UP007, UP035
- glisteel-editor: RUF012, S110, S112, E722, BLE001, TRY400, S102, S202, S301, S307, S310, UP006, UP007, UP035
- twig-bb: E722, TRY400, DTZ, S102, S202, S301, S307, S310

## Baseline, OGC rules

Item 2 of the order of work landed on 2026-09-25 as the sibling project
`openglcontext-checks` (its own repository, not yet on GitHub): the
`oglc-check` command, `[tool.openglcontext-checks]` configuration, `# noqa:
CODE reason` suppression, a per-project result cache, the opt-in pytest entry
point `-p openglcontext_checks.pytest_plugin`, a preflight gate for every
project declaring the table, and the rules OGC131, OGC141, OGC161, OGC201,
OGC221, OGC222 and OGC223. The user documentation is the project's README and
[docs/checks.rst](../docs/checks.rst).

Decisions made while building it, against the design above:

- OGC161 reports a closed set (`os.environ`, `os.environb`, `sys.argv`,
  `os.getenv` and its siblings, `locale.setlocale`, `open`, the `os`
  file-system changes, `shutil`, `subprocess`) rather than every call at
  import, which reported ordinary module setup.
- OGC221 reports every `pytest.skip`, `xfail` and `importorskip` in an
  `except` body, not only an `importorskip` of a first-party module.
- OGC222 also counts a `raise` of an exception, `pytest.deprecated_call`, and
  helpers named `fail` or starting `expect` or `verify`, and takes a test to be
  what pytest collects by default: a name starting `test`.
- Files and directories whose names start with a dot are not checked unless
  named. Agents' git worktrees under `.claude/worktrees` inside several
  projects, and PyOpenGL's `directdocs/.samples`, otherwise put thousands of
  files that are not the project's into the counts; ruff leaves them out by
  reading `.gitignore`, which this package does not.
- The pytest items are added only to a run of the suite (no paths named) or
  with `--oglc-check`, so running one test file does not run the rules.
- On Python 3.10 the package depends on `tomli`, which stands in for
  `tomllib`; from 3.11 it needs only the standard library.

Speed over `OpenGLContext/` (514 files, 138,000 lines, 32 cores): 0.24 s with
nothing cached, 0.87 s in one process, 0.06 s from the cache. The oglc-check
gate across the whole workspace takes 2.2 s.

Findings per project on 2026-09-25, every rule, run from each project's root
over its whole tree less dot-directories and build output (workspace-tools
is the root's `tools/`, `verify-everything.py` and `.claude/skills`):

| Project | OGC131 | OGC141 | OGC161 | OGC201 | OGC221 | OGC222 | OGC223 |
|---|---|---|---|---|---|---|---|
| workspace-tools | 0 | 0 | 0 | 3 | 0 | 1 | 0 |
| openglcontext-checks | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pyopengl-glut-binaries | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pyopengl | 0 | 0 | 58 | 218 | 12 | 159 | 8 |
| pyopengl-accelerate | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| simpleparse | 0 | 0 | 1 | 2 | 0 | 233 | 0 |
| pydispatcher | 4 | 0 | 0 | 0 | 0 | 6 | 0 |
| pyvrml97 | 22 | 0 | 0 | 5 | 0 | 5 | 0 |
| ttfquery | 0 | 0 | 4 | 0 | 0 | 1 | 1 |
| opengl_extrusions | 0 | 0 | 1 | 1 | 1 | 4 | 0 |
| opengl_decimate | 0 | 0 | 2 | 2 | 0 | 0 | 0 |
| omi_physics | 2 | 0 | 0 | 7 | 0 | 3 | 0 |
| omi_audio | 0 | 0 | 2 | 3 | 0 | 6 | 1 |
| pyopengl-video | 0 | 0 | 0 | 0 | 0 | 7 | 1 |
| openglcontext | 216 | 2 | 135 | 301 | 66 | 95 | 14 |
| openglcontext-qt | 0 | 0 | 3 | 6 | 0 | 0 | 0 |
| openglcontext-editor | 7 | 0 | 0 | 10 | 2 | 1 | 0 |
| openglcontext-forest-demo | 0 | 0 | 11 | 0 | 2 | 1 | 0 |
| openglcontext-marble-demo | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| openglcontext-marble-editor | 0 | 0 | 3 | 20 | 0 | 0 | 0 |
| glisteel | 5 | 0 | 2 | 24 | 0 | 3 | 0 |
| glisteel-editor | 0 | 0 | 2 | 22 | 0 | 0 | 0 |
| twig-bb | 9 | 0 | 16 | 68 | 1 | 12 | 0 |
| total | 265 | 2 | 244 | 692 | 84 | 537 | 25 |

Every project whose count is 0 for a rule declares the table selecting it,
and preflight's `oglc-check` gate holds it there. The rules each project
left out, which join as its count reaches 0:

- workspace-tools: OGC201, OGC222
- openglcontext-checks, pyopengl-glut-binaries, pyopengl-accelerate: none
- pyopengl: OGC161, OGC201, OGC221, OGC222, OGC223
- simpleparse: OGC161, OGC201, OGC222
- pydispatcher: OGC131, OGC222
- pyvrml97: OGC131, OGC201, OGC222
- ttfquery: OGC161, OGC222, OGC223
- opengl_extrusions: OGC161, OGC201, OGC221, OGC222
- opengl_decimate: OGC161, OGC201
- omi_physics: OGC131, OGC201, OGC222
- omi_audio: OGC161, OGC201, OGC222, OGC223
- pyopengl-video: OGC222, OGC223
- openglcontext: all seven; it declares no table until it is clean of one,
  and its `preflight.toml` entry says so
- openglcontext-qt: OGC161, OGC201
- openglcontext-editor: OGC131, OGC201, OGC221, OGC222
- openglcontext-forest-demo: OGC161, OGC221, OGC222
- openglcontext-marble-demo: OGC161
- openglcontext-marble-editor: OGC161, OGC201
- glisteel: OGC131, OGC161, OGC201, OGC222
- glisteel-editor: OGC161, OGC201
- twig-bb: OGC131, OGC161, OGC201, OGC221, OGC222

Most of the OGC161 findings outside the packages are demo and helper scripts
that set `os.environ` before importing OpenGL, which a project can exempt by
`per-file-ignores` once it decides they are entry points. The largest OGC222
counts are simpleparse, whose tests assert inside a helper not named for it
(`doBasicTest`), and pyopengl, whose acceptance tests pass by not raising,
some with the check in a decorator; renaming the helper, or an explicit
assertion, clears them.

### openglcontext adopts every rule

openglcontext had findings under all seven rules (829 in all). Each was
resolved as a defect in the code or in the rule; none was exempted to make
the gate pass. The engine's table selects every rule (the default), and the
gate runs in preflight.

Fixed in the rules:

- OGC131 does not report a table that lives for one call (a local bound only
  to containers the function makes, used in place and never passed on,
  returned or stored), a display compared or measured and dropped, or a lookup
  whose entry is checked to hold the object (`entry[0] is x`,
  `table.get(id(x)) is x`). 74 findings.
- OGC161 takes a `script` scope, declared by the project: programs run as
  `python tests/x.py` or as a subprocess driver, which do their work at import
  by design. Nothing in the syntax marks a file as a program (the `bin/`
  modules have `__main__` guards and are imported too), so the project names
  its programs. A scope glob starting `!` removes paths from a scope. 121
  findings.
- OGC201 required a `type: ignore` reason in a form mypy rejects; the reason
  now follows a second `#`.
- OGC222 follows calls to helpers defined in the same module, or methods on
  the test's own class, through the helpers they call. 23 findings.
- The configuration lookup took an enclosing project's table when the
  nearest `pyproject.toml` had none; the nearest `pyproject.toml` is now the
  project.
- The result cache was keyed on the package version, so an edited rule in an
  editable install served old findings; it is keyed on the package's source.

Fixed in the code, among others:

- 243 `noqa` comments naming ruff codes the project ignores, and 11
  `type: ignore`s in tests mypy does not check, removed; 38 `type: ignore`s
  removed by fixing their cause, one of them in PyOpenGL (`vbo.VBO` typed as
  None).
- Tables keyed on `id()`: tiles, zones, emitters, crowds, the batching memo,
  joint palettes and a per-context texture cache now key on the object, and
  one scenegraph walker (`scenegraph/walk.reachable`) replaces nine. Real
  defects among them: a joint palette that could give a new mesh a collected
  mesh's range, a terrain collider table that did not hold its tiles, a
  scene observer recording nodes outside its scene, and an audio aim timer
  never cleared.
- Fonts delete their display lists in the context that made them, through a
  shared `contextresources.ContextNames` that geometry vertex arrays use too.
  The font provider shares one font between contexts, so lists were being
  called in contexts that never compiled them.
- 66 tests that turned a crash, a hang or a first-party import error into a
  skip now fail, and skip only where `gl_available`, `profile_unavailable`,
  `offscreen_unavailable` or `testing.network.unreachable` says the machine
  lacks something. 69 tests that asserted nothing assert what their names
  promise.
- Configuration read at import in the capture path, `terrain_view` and the
  test configuration moved to the first use.

Seven `noqa` lines remain in the engine, each with its reason on the line. Two
files are exempted by `per-file-ignores`: the tutorials `tests/glprint.py`
(OGC141; a Windows-only NeHe lesson) and `tests/hud_demo.py` (OGC201),
since tutorial code is not edited for tooling.

Findings per project after these changes, every rule (a project's gate runs
the rules its table selects):

| Project | OGC131 | OGC141 | OGC161 | OGC201 | OGC221 | OGC222 | OGC223 |
|---|---|---|---|---|---|---|---|
| workspace-tools | 0 | 0 | 0 | 3 | 0 | 1 | 0 |
| openglcontext-checks | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pyopengl-glut-binaries | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| pyopengl | 0 | 0 | 58 | 218 | 12 | 135 | 8 |
| pyopengl-accelerate | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| simpleparse | 0 | 0 | 1 | 2 | 0 | 0 | 0 |
| pydispatcher | 4 | 0 | 0 | 0 | 0 | 6 | 0 |
| pyvrml97 | 19 | 0 | 0 | 5 | 0 | 5 | 0 |
| pyvrml97-accelerate | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| ttfquery | 0 | 0 | 4 | 0 | 0 | 1 | 1 |
| opengl_extrusions | 0 | 0 | 1 | 1 | 1 | 4 | 0 |
| opengl_decimate | 0 | 0 | 2 | 2 | 0 | 0 | 0 |
| omi_physics | 0 | 0 | 0 | 7 | 0 | 3 | 0 |
| omi_audio | 0 | 0 | 2 | 3 | 0 | 6 | 1 |
| pyopengl-video | 0 | 0 | 0 | 0 | 0 | 7 | 1 |
| openglcontext | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| openglcontext-qt | 0 | 0 | 3 | 6 | 0 | 0 | 0 |
| openglcontext-editor | 3 | 0 | 0 | 10 | 2 | 1 | 0 |
| openglcontext-forest-demo | 0 | 0 | 11 | 0 | 2 | 1 | 0 |
| openglcontext-marble-demo | 0 | 0 | 4 | 0 | 0 | 0 | 0 |
| openglcontext-marble-editor | 0 | 0 | 3 | 20 | 0 | 0 | 0 |
| glisteel | 2 | 0 | 2 | 24 | 0 | 3 | 0 |
| glisteel-editor | 0 | 0 | 2 | 22 | 0 | 0 | 0 |
| twig-bb | 5 | 0 | 16 | 68 | 1 | 12 | 0 |

## Baseline, sanctioned-API rules

Item 3 of the order of work. In openglcontext-checks: OGC101, OGC102, OGC111,
OGC121 and OGC151, the `loader` and `pass` scopes (empty until a project names
its modules) and the `sanctioned` key, by which a project names its own API
for the rules that point at one. Decisions against the design above:

- One `loader` scope rather than `loader` and `hook`: a hook factory reading
  a document's values is a loader for these rules.
- OGC101's document field is a subscript or `.get` by a string literal on a
  table the module does not itself hold; an index by number or variable is a
  sequence or the program's own table. OGC102 shares that test for sizes.
- OGC111 reports a path the function builds (join, `+`, `/`, `%`, format,
  f-string) from a part the source does not fix, or reads from a named field;
  a parameter, attribute or another call's result opened as it is is left to
  the checked types of layer 3.
- OGC121 does not run in the `test` scope, does not report a stream opened to
  append (a log, a journal, a lock file: there is no staged form), and
  accepts `tempfile` directories, the sanctioned stagers and a write followed
  by `os.replace`, so a library below the engine satisfies it on its own.
- OGC151 has no default sanctioned managers: the engine has none yet.

Adoption on 2026-09-25: every project selects OGC121, and those with document
readers declare a `loader` scope and select OGC101, OGC102 and OGC111
(pyvrml97, omi_physics, omi_audio, twig-bb, glisteel, glisteel-editor,
openglcontext-editor, forest, marble-demo). pyopengl-video names its library
as the `pass` scope and selects OGC151. openglcontext selects OGC101, OGC102
and OGC121; its OGC111 hits belong to item 4's checked types. OGC151 is not
selected in openglcontext: its `pass` scope would hold about 85 findings in
`passes/` and 170 in the scenegraph's own GL renderers, most of them frame
set-up that wants the state context managers the per-class plan names
(`gl_state.enabled`, `bound_framebuffer`, a program and a scissor manager, and
a frame-baseline reset) before the calls can be moved onto them.

TID251 holds the banned-api list in the projects built on the engine
(openglcontext, -qt, -editor, forest, marble-demo, marble-editor, glisteel,
glisteel-editor, twig-bb), `time.time` in the demos and games only. The
libraries below the engine do not take it: the replacements live in the
engine above them, and `pickle` is already S301 there. openglcontext's list
leaves out `os.environ`, `os.getenv` and `urllib.request.urlopen` for now:
about 40 reads of the environment in the engine outside `renderoptions`
(the passes' own `OPENGLCONTEXT_INSTANCE_COLLAPSE`, `_CLUSTER_CULL`,
`_TRANSMISSION`, `_IBL` and `_RENDERER` reads among them) and cc0's opener,
which waits on item 4's `open_url(CheckedURL)`.

## The post-edit gates

Item 5 landed on 2026-09-25. `tools/editcheck.py` in the workspace root takes
the paths of edited files, finds each file's project (the nearest
`pyproject.toml`, looked up in `tools/preflight.toml`) and runs that project's
ruff on the file, `oglc-check --force-exclude` on it (skipped where the
project's own run would not check it), and mypy through one `dmypy` daemon per
typecheck run of `.preflight-venv`. A daemon starts on first use, restarts when
`preflight.py --rebuild-env` rebuilds the environment, and stops after an hour
idle; runs in one project queue on its lock, others do not wait. A warm edit
costs 0.18 to 0.25 s in all; a daemon's first run costs 0.6 s (pydispatcher)
to 7.4 s (openglcontext-editor), about 15 s for openglcontext.

It runs as a Claude Code `PostToolUse` hook on `Edit`, `Write` and
`MultiEdit` (`.claude/settings.json`), silent on success and exit 2 with the
findings on standard error otherwise, and as a git pre-commit hook
(`tools/git-hooks/pre-commit`, installed per repository by hand; the loop is
in `tools/editcheck.py`'s docstring). `--staged` checks the working-tree copy
of each staged file, not the staged copy. The Claude hook names
`.venv/bin/python`, so it does not run on Windows as written.

## The checked types

Item 4 of the order of work landed on 2026-09-25.

- `JSONObject = Mapping[str, object]` (`loaders/documentvalues.py`) is what
  the JSON readers answer: tilesets and external tilesets, a world's extras,
  manifests and species, content registries, install records and the publish
  command's registry, a LOD chain's and a grass clump's glTF JSON, the glTF
  decoder, the tileset sniff, the ambientCG reply; hook and zone parameters
  are typed the same way. `DocumentValues` gained `mapping`, `array`, `text`
  and `texts`; the `require_*` functions (`object`, `array`, `number`,
  `numbers`, `text`, `whole`, `index`, `item`) refuse a missing or malformed
  required part with `DocumentError`. Readers of the engine's own files
  (key bindings, telemetry and stall journals, the `bin/` tools) are not
  converted.
- `ContainedPath` and `CheckedURL` live in `loaders/resolver.py`, with a
  constructor keyed on a module-private object. Producers: `contain`,
  `Resolver.resolve` / `Resolver.contain`, `contained_source` and
  `checked_source` (a caller's string, checked once), `cached_path`;
  `checked_url`, `require_host`, `AllowedHosts.check`. `open_url`,
  `fetch_url`, `fetch_to_cache`, `read_contained`, `open_contained`,
  `tiles3d.fetch.read_bytes` and `local_copy` take only them. Found on the
  way: a cache key built from a URL's extension could carry a query's `..`
  out of the cache directory (the key is now one component), and a tileset
  read with no base took its document's content names as the caller's (they
  are now held to the working directory, and a `RuntimeTile`'s content URIs
  are absolute).
- The mypy plugin (`openglcontext_checks.mypy_plugin`) reports
  `checked-construction` and, in the `loader` scope, `unchecked-open`.
  openglcontext enables it: 19 opens in loader modules went through
  `contained_source`, `read_contained` or `Resolver.contain`, with no
  `type: ignore`. The openers are checked from a signature hook, because an
  error from a call hook during overload matching types `open()` as its last
  overload.
- `ContextKey` (`contextresources.py`) is what `context_key()` answers and
  what the engine's per-context tables are typed on. A backend tells
  PyOpenGL's dispatch its context by the raw handle
  (`contextresources.current_handle`), not by the key.
- OGC111: openglcontext has no findings in its `loader` scope and selects it.
  `urllib.request.urlopen` joined its banned API once `cc0` fetched through
  `open_url`.
- `GLName` owning wrappers: not adopted. The engine's GL names already have
  owners (the `PassResources.disposeResources` chain for a pass,
  `ContextNames` for names an object holds per context, the
  context-loss callbacks for module caches), and OGC141/OGC142 hold new code
  to them. A `TextureName(int)` would pass wherever PyOpenGL takes an int, so
  the type protects only the engine's own bind helpers, which few draws go
  through; making it protect the 106 allocation sites in 43 modules means
  routing every bind of every draw through a Python-level wrapper on the hot
  path. What it would add over the present ownership is a check that a name
  is used in the context that issued it, and a name carrying its
  `ContextKey` is the smaller change that gives that, where a defect shows
  it is needed.

## The test conventions

Item 6 landed on 2026-09-25: a module of `OpenGLContext.testing` for each
convention, each also a fixture of the engine's pytest plugin, documented in
[docs/testing.rst](../docs/testing.rst) ("Test conventions"), and the section
"Before a change is finished" in `openglcontext/CLAUDE.md` naming the test
each non-static class needs. The helpers are named `check_*` (the plan's
`memo_inputs` is `check_memo_inputs`), which is how OGC222 counts a test that
calls one as asserting.

| Convention | Module | Applied in | Defects found and fixed |
|---|---|---|---|
| `check_memo_inputs` | `testing/memo.py` | `tests/unit/test_memo_inputs.py`: batching memo, mirror generation, LOD memo, zone placement | `LOD.hysteresis` unwatched by `level_generation` (lod_demo's toggle did nothing while still); a `PBRMesh`'s own `material` unwatched by `mirror_generation`; `shape_material` ignored the mesh's material under an `Appearance` with no material |
| `check_scaling` | `testing/scaling.py` | `tests/unit/test_scaling.py`: zones, mirror planner, ground cover | `ZoneTable.classify_many` grew as objects times zones (16 to 18 times at 4x); Z-ordered chunks and a tree query per chunk make it linear (20,000 objects over 57 zones: 0.66 s to 0.04 s) |
| `check_failing_layer` | `testing/layers.py` | `tests/unit/test_failing_layers.py`: reflections, bloom start and composite, zone captures | none: each is isolated |
| `check_still_frame` | `testing/stillframe.py` | `tests/unit/test_still_frames.py`: six scenes | instance buffers, group material arrays and bitmap text were uploaded every still frame |
| `check_mirrored_render` | `testing/mirrored.py` | `tests/unit/test_mirrored_geometry.py`: every registered geometry, both renderers | Box, Sphere, Cone, Cylinder, Gear, Teapot, NurbsSurface and TrimmedSurface drew inside out under a negative scale; bitmap text in the core profile was drawn at a fixed spot rather than at the node |
| `numpy_errors` ini setting | `testing/plugin.py` | openglcontext's suite runs with `raise` | `polygonsort` divided by `w = 0` for a triangle reaching the eye plane; its `project` raised for most point counts and scaled y by the width |
| open audit (`open_audit` ini setting) | `testing/openaudit.py` | openglcontext's suite runs with `fail` | 22 readers of document- and application-named files opened them directly; the glTF loader opens through the resolver since 954b0a7 (97c94fa), and the other 21 are listed in `open_audit_sanctioned` and leave it as item 4 routes them through the resolver's checked paths |

`scene_context` and `drawn_image` (`testing/scenes.py`) are what the drawing
conventions are built on. The open audit costs about 4 microseconds an open
that reaches a checked module; the unit suite on 8 workers took 242 s
without it and 217 s with it, inside the run-to-run spread.

Left open: the mirrored-render test draws in the core profile, so the
compatibility-profile draw paths (fixed function, display lists) are not
held by it; underflow is not raised, since a result too small for its type
becoming zero is the answer. Two failures seen in full runs belong to other
work in progress in the tree: `test_viewer_component` (a viewer mix-in
shadowing `renderer` and `resolveDefinition`) and
`test_gltf_regression_diff::test_dl_downloads_when_absent`.
`test_unlit_pickable_gl[pointset]`, which failed once in a loaded full run
(its pick's readback had not landed in the frames it drew), waits for the
readback with `flushPendingPicks` (e9a40d9).

## Parked, 2026-09-25

Items 1 to 6 are done and committed. Item 7 is done in every project but
openglcontext and pyopengl. What is pending:

- openglcontext, item 7: under way when work stopped. Its brief, in order:
  the engine APIs the other projects asked for (a public way to stage
  `InstancedMeshLOD.compute_pending()`'s result; a public on/off switch for
  the instanced vegetation and terrain nodes; `FetchJob.wait(timeout)`; a
  public view, or a reasoned noqa, for each private engine name twig-bb's
  tests read: `PBRMaterial._ubo_version`, `PBRMesh._deform_version`,
  `PBRMesh._skin_matrices`, the mixer's `_writable()`,
  `PhysicsViewPlatform._world_dir`, `audio.scene._engines`,
  `ui.pictures._decoders`; `flush_and_exit` moved out of
  `OpenGLContext.testing`, which shipped games now import), then removing the
  `# noqa: SLF001` lines those projects carry meanwhile; routing the ~40
  `os.environ` reads outside `renderoptions` through its read-once functions
  and banning direct reads (TID251); the GL state context managers OGC151
  needs, then resolving its ~255 findings and selecting it; the
  `tiles3d/frustum.look_at` divide-by-zero that `numpy_errors = "raise"`
  exposes (`tests/tiles3d/test_streaming.py` fails on it); trimming
  `open_audit_sanctioned` of modules item 4 converted; and the 19 ruff rules
  across the engine (baselines in [Baseline, ruff rules](#baseline-ruff-rules)).
  What that agent committed and what it left is in its last commits and in
  `plans/pending/` in the workspace root, where it saves any unfinished change
  as a patch.
- openglcontext, item 7, state when it stopped: committed are the engine
  APIs (05bf7c3: `InstancedMeshLOD.stage()`, a `drawn` switch on the
  instanced nodes, `FetchJob.wait()`, `processexit.flush_and_exit`, public
  views for the names twig-bb read), the `look_at` fix (4618122), the
  environment reads through renderoptions with `os.environ`/`os.getenv`
  banned (a230572; `viewer/sceneviewer.py` is still exempt and can lose the
  exemption now that de5f152 landed), UP006/UP007/UP035 fixed but not
  selected (7669be0), and `passes/glstate.py` with OGC151's pass scope
  (331d420). Not done: OGC151's 176 findings and its selection; the ratchets
  over `OpenGLContext/**` (about 1,000 findings); SLF001 in tests/unit (about
  1,200, mostly white-box files needing per-file-ignores) and in the demo
  scripts (106, tutorials to exempt); selecting the rules and RUF100;
  trimming `open_audit_sanctioned`. Unfinished worker changes, if any, are
  patches in the workspace root's `plans/pending/`; run `git status` first.
  The full unit and visual suites were not run after a230572. twig-bb's
  `test_each_health_pack_draws_a_different_picture` failed once under load.
- pyopengl, item 7: the code fixes are committed; the rule selection and four
  handler narrowings wait on the maintainer's uncommitted pyopengl work, as
  patches in the workspace root's `plans/pending/`
  (`2026-09-25-pyopengl-ruff-select.patch`, which applies now, and
  `2026-09-25-pyopengl-handler-narrowing.patch`, after the error-path record
  changes land), with the report beside them. PLC0415 (about 1,300 of 2,141
  are one line the generator templates emit), SLF001 and ARG need generator
  and `pyproject.toml` changes in files the maintainer has modified.
- Uncommitted viewer edits in openglcontext that no agent made
  (`viewer/sceneviewer.py`, `viewer/environment.py`, `docs/embedding.rst`,
  `docs/viewer.rst`, `docs/structure.rst`, `docs/_static/oglc.css`,
  `tests/unit/test_viewer_for_backend.py`, a `pyproject.toml` hunk): they move
  the viewer's render settings into `resolveDefinition`, and
  `tests/unit/test_viewer_component.py` fails with them in the tree.
- A twig-bb full-suite run once reported one failure whose name was cut off;
  31 reruns passed. Suspected: its wall-clock tests with millisecond budgets,
  which twig-bb does not mark `serial`.
- Publishing: openglcontext-checks is not on PyPI, so the mypy plugin is
  enabled only in openglcontext, and openglcontext's tox typecheck
  environment will not build until it is published; with omi_audio 0.4.0a1
  and opengl_decimate 0.2.0a1, it goes out before the engine.
- A full `tools/preflight.py --rebuild-env` has not been run since items 3, 4,
  6 and 7 landed; it is the first step when this resumes.
- Decided by the maintainer: the public API changes the item-7 agents made
  (renamed or newly public names, removed unused parameters, the two
  pyvrml97 deprecations) stand. Still open: ttfquery's unclosed files and
  committed `.coverage`; simpleparse's three unused public keywords;
  omi_audio's `impact_clip(tuning)`; pydispatcher's CI lint job; marble-editor
  declaring a marble-demo floor; the forest's unused `event` parameters.

## Decided

- The rule package is the sibling project `openglcontext-checks`, installable
  by a project that does not use the engine.
- The checked types change no public signature: the top-level load operations
  take a string, pass it through the restrictions once, and hand the checked
  type to the lower-level loaders (see [layer 3](#3-types-that-must-be-unwrapped)).

## Questions for the maintainer

- Whether to propose the general rules (OGC131, OGC141, OGC191, OGC201,
  OGC221 to OGC223) to upstream ruff once they have run here for a release.
