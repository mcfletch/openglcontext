# Test Suite Improvements

## Status: In Progress (Phase 1-4 Complete)

## Summary

Transform the test suite from interactive "does this work" scripts into automated pytest-based tests with subprocess isolation, event simulation, visual regression testing, and comprehensive HTML reports.

## Goals

1. **Subprocess-based test execution** - Run OpenGL contexts in subprocesses for isolation, coverage collection, and parallel execution ✅
2. **Event simulation** - Simulate keyboard, mouse, and display events for interaction testing (deferred)
3. **Visual regression testing** - Compare rendered output against known-good reference images ✅
4. **HTML test reports** - Generate reports showing pass/fail status, captured images, diffs, and log output ✅
5. **Coverage tracking** - Collect coverage data from subprocess tests to achieve 80-100% coverage ✅ (9% achieved)
6. **Convert existing scripts** - Migrate ~145 test scripts to automated pytest cases ✅ (129 scripts automated)

## Current State (January 2026)

### Implemented Infrastructure

- `tests/test_all_scripts.py` - Comprehensive subprocess test runner with:
  - `TestVisualRegression` - 118 visual scripts with screenshot capture/comparison
  - `TestAllScripts` - 129 total scripts including non-visual tests
  - Platform/library detection with skip logic (wxPython, pygame, Windows/WGL, GLUT)
  - Traceback detection in stderr
  - Coverage collection via `coverage run --parallel-mode`
  - HTML report generation at `tests/report.html`

- `tests/conftest.py` - Pytest configuration

- `OpenGLContext/context.py` enhancements:
  - `OPENGLCONTEXT_AUTO_EXIT_FRAMES` - Exit after N frames
  - `OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR` - Screenshot capture directory
  - `OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME` - Screenshot filename
  - `OPENGLCONTEXT_DISABLE_FPS_DISPLAY` - Hide FPS overlay for clean screenshots

- `OpenGLContext/testing/report_generator.py` - HTML report with:
  - Side-by-side reference/result/diff images
  - Pass/fail/skip/error status indicators
  - Stdout/stderr output display
  - Comparison statistics

- `OpenGLContext/testing/framebuffer_comparison.py` - Image comparison utilities

### Script Categorization

| Category      | Scripts | Treatment                                                    |
| ------------- | ------- | ------------------------------------------------------------ |
| Visual        | 118     | Screenshot capture + visual regression                       |
| Non-visual    | 11      | Functionality test only (glget.py, boundingvolume.py, etc.)  |
| Windows-only  | 4       | Skip on non-Windows (glprint.py, wgl_*.py)                   |
| wxPython      | 3       | Skip if wx unavailable                                       |
| pygame        | 2       | Skip if pygame unavailable                                   |
| GLUT-specific | 5       | Skip if GLUT unavailable                                     |
| Randomized    | 2       | `expect_visual_diff` marker                                  |
| Excluded      | 6       | Helper modules, tutorial intros                              |

### Test Results

Last run: **247 passed, 7 failed, 6 skipped**

Known failures:

- `solid_font.py` - Font provider registry issue
- `glutmousewheel.py` - GLUT-specific
- `savepostscript.py` - PostScript functionality
- `glprint.py` - Windows-only (skipped on Linux)

### Remaining Work

1. **Event simulation (Phase 2)** - Not yet implemented; deferred
2. **Reference image baseline** - Need to generate/curate reference images
3. **Coverage improvement** - Currently 9%, target 80%+
4. **CI integration (Phase 6)** - Deferred to separate plan

## Open finding: an import that breaks a later GL test

`tests/unit/test_passes_render_gl.py` fails its first four tests, and then the
pytest process dies without printing a summary, whenever it runs after certain
other modules. Two files reproduce it:

```bash
pytest tests/unit/test_glut_lineset.py tests/unit/test_passes_render_gl.py -p no:randomly
```

`test_glut_lineset.py` **collects no tests at all** -- its `TestContext` has an
`__init__` and pytest skips it -- so the damage is done purely by importing the
module. What survives that import is enough to stop the PBR pass instancing
(`instanced_calls == 0` with `renderer_is_pbr()` still True, so the pass *is*
selected and simply draws nothing through the instanced path).

Confirmed **not** caused by the overlay-UI work: with every `OpenGLContext/`
change of that branch stashed, the same run produces a byte-identical tail.

What is known:

- The failing tests pass in isolation and in small combinations; the fixture in
  `test_passes_render_gl.py` already tears its windows down and calls
  `glfw.terminate()`, so nothing accumulates *within* that file.
- `OpenGL.GLUT` is imported by `scenegraph/boundingvolume.py` at module scope
  (`from OpenGL.GLUT import glutSolidCube`), so it is loaded in both the passing
  and the failing orders -- the GLUT import alone is not the difference.
- Bisecting the alphabetical file order puts the change at exactly that module.

Ruled out since, by direct measurement rather than reasoning: the renderer *is*
the PBR one, `contextDefinition.instancing` is on, `OPENGLCONTEXT_INSTANCE_MIN`
is set, and `Sphere` still reports the same `instanceContentKey` and still has
`instanceGPU` -- so the geometry is groupable and the pass that would group it
is selected. Whatever survives the import is downstream of all four.

Not yet known: which piece of state carries across. Worth finding: it is the
only thing standing between this suite and a clean full run, and "passes in
isolation" is not passing. The whole suite is otherwise green -- 3166 passed
with this one file deselected.

**One member of that family is fixed.** `scenegraph/text/shadertext.py` cached
its `ShaderTextRenderer` per *font size* in a process-global dict, so a renderer
built in one GL context was handed to the next window and bound a texture name
that had died with the first -- silently drawing the wrong thing, or raising
`GL_INVALID_OPERATION` when the driver reused the id for something else. The
cache is now keyed by `(GL context, size)`, `drop_text_renderers()` releases the
current context's entries, and `GLFWContext` calls it as the window goes down.
This is a real multi-window bug as well as a test-isolation one; it is *not* the
cause of the failure above, which reproduces with the fix in place.

## Original Plan (for reference)

## Implementation Plan

### Phase 1: Test Infrastructure Foundation

#### 1.1 Create pytest fixtures (`tests/conftest.py`)

```python
import pytest
import subprocess
import signal
import os
from pathlib import Path

# Default timeout for most tests (context creation + single render)
DEFAULT_TIMEOUT = 30

# Longer timeout for tests with heavy initialization (NURBS, large scenes)
SLOW_TEST_TIMEOUT = 120

@pytest.fixture
def subprocess_runner():
    """Run a test script in a subprocess with coverage and timeout handling."""
    def run(script_path, args=None, env=None, timeout=DEFAULT_TIMEOUT):
        cmd = build_coverage_command(script_path, args)
        full_env = {**os.environ, **(env or {})}

        try:
            result = subprocess.run(
                cmd,
                env=full_env,
                capture_output=True,
                timeout=timeout,
                text=True,
            )
            return SubprocessResult(result, timed_out=False)
        except subprocess.TimeoutExpired as e:
            # Kill the subprocess tree on timeout
            kill_process_tree(e.pid)
            return SubprocessResult(
                returncode=124,  # Standard timeout exit code
                stdout=e.stdout or '',
                stderr=e.stderr or f'Test timed out after {timeout}s',
                timed_out=True,
            )
    return run

@pytest.fixture
def reference_image_dir():
    """Path to reference images directory."""
    return Path(__file__).parent / "reference_images"

@pytest.fixture
def opengl_env():
    """Environment variables for OpenGL context creation."""
    return {
        'OPENGLCONTEXT_PROFILE': 'compatibility',
        'OPENGLCONTEXT_BACKEND': 'glfw',
    }


def kill_process_tree(pid):
    """Kill a process and all its children."""
    import psutil
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in children:
            child.kill()
        parent.kill()
    except psutil.NoSuchProcess:
        pass
```

#### 1.2 Timeout configuration

Tests can specify custom timeouts using pytest markers:

```python
import pytest

# Test with default timeout (30s)
def test_simple_render(subprocess_runner):
    result = subprocess_runner('tests/box.py', ['--test', '--exit-after'])
    assert result.returncode == 0

# Test with extended timeout for slow initialization
@pytest.mark.timeout(120)
def test_nurbs_surface(subprocess_runner):
    result = subprocess_runner(
        'tests/nurbssurface.py',
        ['--test', '--exit-after'],
        timeout=120
    )
    assert result.returncode == 0

# Mark tests that are known to be slow
@pytest.mark.slow
def test_large_scene(subprocess_runner):
    ...
```

Run only fast tests: `pytest -m "not slow"`

#### 1.3 Subprocess coverage collection

Use `coverage run --parallel-mode` to collect coverage from subprocesses:

```python
def build_coverage_command(script_path, args):
    """Build command to run script with coverage collection."""
    cmd = [
        sys.executable, '-m', 'coverage', 'run',
        '--parallel-mode',
        '--source=OpenGLContext',
        str(script_path)
    ]
    if args:
        cmd.extend(args)
    return cmd
```

After all tests complete, combine coverage data:
```bash
coverage combine
coverage report --show-missing
coverage html
```

#### 1.3 Test result collector

Create a collector that gathers:
- Exit code (pass/fail)
- stdout/stderr output
- Reference, result, and diff images
- Timing information

### Phase 2: Event Simulation

#### 2.1 Event injection via IPC

Events are injected via Unix socket or stdin as JSON messages. This avoids windowing system dependencies and works with any backend.

**Command-line flag:**
```bash
python tests/mytest.py --event-socket /tmp/test_events.sock
# or
python tests/mytest.py --event-stdin
```

**JSON event format:**

```json
{"type": "mousebutton", "x": 100, "y": 200, "button": 0, "state": 1, "modifiers": [0, 0, 0]}
{"type": "mousemove", "x": 150, "y": 250, "buttons": [], "modifiers": [0, 0, 0]}
{"type": "keyboard", "key": "p", "state": 1, "modifiers": [0, 0, 0]}
{"type": "resize", "width": 800, "height": 600}
{"type": "capture", "name": "after_click"}
{"type": "exit"}
```

Events are OpenGLContext-level events, not backend-specific (GLFW, Qt, etc.).

#### 2.2 Event listener in Context

```python
class EventInjectionMixin:
    """Mixin to add event injection support to contexts."""

    def setup_event_injection(self, socket_path=None, use_stdin=False):
        """Set up event injection from socket or stdin."""
        self._event_injector = EventInjector(
            socket_path=socket_path,
            use_stdin=use_stdin,
            context=self,
        )

    def poll_injected_events(self):
        """Poll for and process injected events. Call from main loop."""
        if hasattr(self, '_event_injector'):
            for event in self._event_injector.poll():
                self._dispatch_injected_event(event)

    def _dispatch_injected_event(self, event):
        """Convert JSON event to OpenGLContext event and dispatch."""
        event_type = event.get('type')

        if event_type == 'mousebutton':
            self._inject_mousebutton(event)
        elif event_type == 'mousemove':
            self._inject_mousemove(event)
        elif event_type == 'keyboard':
            self._inject_keyboard(event)
        elif event_type == 'capture':
            self._do_capture(event.get('name', 'capture'))
        elif event_type == 'exit':
            self.OnQuit()
```

#### 2.3 Event injector implementation

```python
class EventInjector:
    """Reads JSON events from socket or stdin."""

    def __init__(self, socket_path=None, use_stdin=False, context=None):
        self.context = context
        self._buffer = ''

        if socket_path:
            self._setup_socket(socket_path)
        elif use_stdin:
            self._setup_stdin()

    def _setup_socket(self, path):
        """Set up Unix domain socket listener."""
        import socket
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.bind(path)
        self._socket.listen(1)
        self._socket.setblocking(False)
        self._conn = None

    def _setup_stdin(self):
        """Set up non-blocking stdin reading."""
        import sys
        import fcntl
        import os
        flags = fcntl.fcntl(sys.stdin.fileno(), fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin.fileno(), fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def poll(self):
        """Yield parsed JSON events."""
        # Read available data, parse complete JSON lines
        ...
```

#### 2.4 Test driver sends events

```python
def run_interactive_test(script_path, events, timeout=30):
    """Run a test script and send events to it."""
    import socket
    import json
    import tempfile

    socket_path = tempfile.mktemp(suffix='.sock')

    proc = subprocess.Popen(
        [sys.executable, script_path, '--event-socket', socket_path],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    # Poll for socket with short sleeps to minimize wait time
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    start = time.time()
    while time.time() - start < 10:  # Max 10s to wait for socket
        try:
            sock.connect(socket_path)
            break
        except (FileNotFoundError, ConnectionRefusedError):
            time.sleep(0.05)  # 50ms between attempts
    else:
        proc.kill()
        raise RuntimeError(f"Socket {socket_path} not available after 10s")

    for event in events:
        if event.get('type') == 'wait':
            time.sleep(event.get('duration', 0.5))
        else:
            sock.send((json.dumps(event) + '\n').encode())

    # Send exit and wait for completion
    sock.send(b'{"type": "exit"}\n')
    stdout, stderr = proc.communicate(timeout=timeout)

    return proc.returncode, stdout, stderr
```

#### 2.5 Event script format

Test scripts define interactions as a list of JSON-serializable events:

```python
# tests/test_click_sphere.py
EVENTS = [
    {"type": "wait", "duration": 0.5},
    {"type": "capture", "name": "before_click"},
    {"type": "mousebutton", "x": 320, "y": 240, "button": 0, "state": 1},
    {"type": "mousebutton", "x": 320, "y": 240, "button": 0, "state": 0},
    {"type": "wait", "duration": 0.1},
    {"type": "capture", "name": "after_click"},
    {"type": "exit"},
]
```

#### 2.6 Headless rendering support

For CI environments without displays:
- Use virtual framebuffer (Xvfb) on Linux
- Use EGL/OSMesa for offscreen rendering
- Add `--headless` flag to test scripts

### Phase 3: Visual Regression Framework

#### 3.1 Enhanced comparison

Extend `framebuffer_comparison.py`:

```python
class VisualRegressionTest:
    """Manages visual regression testing for a single test."""

    def __init__(self, test_name, reference_dir):
        self.test_name = test_name
        self.reference_dir = reference_dir

    def record_reference(self, profile='compatibility'):
        """Record reference image using specified profile."""
        pass

    def test_against_reference(self, profile='core', tolerance=None):
        """Test current rendering against reference."""
        pass

    def generate_report_data(self):
        """Generate data for HTML report."""
        return {
            'test_name': self.test_name,
            'status': 'pass' | 'fail' | 'skip',
            'reference_image': path,
            'result_image': path,
            'diff_image': path,
            'comparison_stats': {...},
            'stdout': '...',
            'stderr': '...',
        }
```

#### 3.2 Reference image management

- Store reference images per-profile (compatibility vs core)
- Version reference images with test code
- Provide CLI to update references: `pytest --update-references`

### Phase 4: HTML Report Generation

#### 4.1 Report structure

```
test_reports/
├── index.html           # Summary with pass/fail counts
├── test_name_1/
│   ├── report.html      # Individual test report
│   ├── reference.png
│   ├── result.png
│   ├── diff.png
│   └── output.txt       # stdout/stderr
└── test_name_2/
    └── ...
```

#### 4.2 Report content

Each test report shows:
- Pass/fail status with clear visual indicator
- Side-by-side reference vs result images
- Diff image with highlighted differences
- Comparison statistics (max diff, % different)
- Full stdout/stderr output
- Timing information
- Links to related tests

#### 4.3 pytest-html integration

Use `pytest-html` plugin with custom hooks:

```python
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    # Add extra HTML with images
    if hasattr(item, 'visual_regression_data'):
        extra = generate_image_html(item.visual_regression_data)
        report.extra = getattr(report, 'extra', []) + extra
```

### Phase 5: Test Migration

#### 5.1 Categorize existing tests

| Category | Count | Automation Approach |
|----------|-------|---------------------|
| Pure rendering | ~80 | Visual regression |
| Interactive | ~30 | Event simulation |
| API tests | ~20 | Direct pytest |
| Extension tests | ~15 | Conditional skip |

#### 5.2 Migration template

Use pytest parametrization to test multiple profiles without code duplication:

```python
# tests/test_rendering.py
import pytest
from pathlib import Path

PROFILES = ['compatibility', 'core']

class TestBoxRendering:
    """Visual regression tests for Box geometry."""

    @pytest.fixture
    def test_script(self):
        return Path(__file__).parent / "box.py"

    @pytest.mark.parametrize('profile', PROFILES)
    def test_box_renders(self, subprocess_runner, test_script, profile):
        """Box renders correctly in {profile} profile."""
        result = subprocess_runner(
            test_script,
            args=['--test', '--exit-after'],
            env={'OPENGLCONTEXT_PROFILE': profile}
        )
        assert result.returncode == 0


# For testing multiple scripts across profiles:
GEOMETRY_SCRIPTS = ['box.py', 'sphere.py', 'cone.py', 'cylinder.py']

@pytest.mark.parametrize('script', GEOMETRY_SCRIPTS)
@pytest.mark.parametrize('profile', PROFILES)
def test_geometry_renders(subprocess_runner, script, profile):
    """Geometry {script} renders in {profile} profile."""
    script_path = Path(__file__).parent / script
    result = subprocess_runner(
        script_path,
        args=['--test', '--exit-after'],
        env={'OPENGLCONTEXT_PROFILE': profile}
    )
    assert result.returncode == 0
```

#### 5.3 Batch conversion script

Create a script to generate test wrappers for existing scripts:

```python
# scripts/generate_test_wrappers.py
def generate_wrapper(script_path):
    """Generate pytest wrapper for an existing test script."""
    pass
```

### Phase 6: CI Integration (Deferred)

CI integration will be addressed in a separate feature plan. This phase will cover:

- GitHub Actions workflow configuration
- Xvfb setup for headless testing
- Coverage thresholds and reporting
- Badge generation for README

## File Changes

### New Files

- `tests/conftest.py` - Shared pytest fixtures
- `tests/test_visual_regression.py` - Visual regression test collection
- `tests/test_event_handling.py` - Event simulation tests
- `OpenGLContext/testing/subprocess_runner.py` - Subprocess test execution
- `OpenGLContext/testing/event_injector.py` - JSON event injection via socket/stdin
- `OpenGLContext/testing/report_generator.py` - HTML report generation
- `OpenGLContext/events/injected.py` - EventInjectionMixin for contexts
- `scripts/generate_test_wrappers.py` - Migration helper script

### Modified Files

- `OpenGLContext/testing/framebuffer_comparison.py` - Enhanced comparison
- `OpenGLContext/context.py` - Add EventInjectionMixin, poll_injected_events() in main loop
- `OpenGLContext/testingcontext.py` - Add --event-socket and --event-stdin CLI flags
- `setup.py` or `pyproject.toml` - Test dependencies
- `CLAUDE.md` - Updated test documentation

## Dependencies

Add to test requirements:
- `pytest`
- `pytest-html`
- `pytest-cov`
- `pytest-timeout`
- `coverage`
- `psutil` (for killing subprocess trees on timeout)
- `Pillow` (already optional)

## Success Criteria

1. `pytest tests/` runs all automated tests
2. Coverage report shows 80%+ coverage of OpenGLContext
3. HTML report displays all test results with images
4. Event simulation tests verify keyboard/mouse handling
5. Reference images maintained alongside code

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| GPU differences cause false failures | Configurable tolerance thresholds |
| Headless rendering unavailable | Skip visual tests gracefully |
| Subprocess tests slow | Parallel execution with pytest-xdist |
| Reference images bloat repo | Consider git-lfs for images |
| Tests hang indefinitely | Per-test timeouts with process tree cleanup |
| Slow tests dominate CI time | Mark slow tests, run separately or with longer CI timeout |

## Timeline Estimate

- Phase 1: Foundation - Core infrastructure
- Phase 2: Events - Event simulation
- Phase 3: Visual - Enhanced regression framework
- Phase 4: Reports - HTML report generation
- Phase 5: Migration - Convert existing tests
- Phase 6: CI - Deferred to separate feature plan

## Notes

- Tutorial code (files with extensive docstrings) should not be modified
- Existing interactive tests remain runnable for manual verification
- Tests should work on Linux, macOS, and Windows

## A rendered baseline must not inherit the parent's environment

**Added 2026-07-29.** Several test modules set a rendering variable in
`os.environ` at import time, because they need it before OpenGL is imported —
six under `tests/unit/` set `OPENGLCONTEXT_RENDERER=pbr`, and others set
`OPENGLCONTEXT_SHADOWS`. A capture subprocess started with `dict(os.environ)`
therefore renders with whatever the run has accumulated, which makes a
reference-image comparison depend on what was collected before it.

The symptom is a full run that fails four to ten pixel comparisons —
`test_shadow_rendering` and `test_gltf_conformance` — with a *different* set
each time, every one of which passes in isolation on an idle machine.
`OPENGLCONTEXT_RENDERER=pbr` alone reproduces five of them.

`tests/unit/conftest.py` already restores `OPENGLCONTEXT_*` and `PYOPENGL_*`
to their session values after every test, which handles the ordinary case; what
it cannot cover is a variable set between the last teardown and a capture, or a
capture started outside that directory.

**The rule.** Anything that spawns a renderer and then compares its pixels
builds its environment with `renderoptions.clean_environment`, which drops
every variable in `renderoptions.ENVIRONMENT` and then sets what the render
actually needs — so the result is reproducible from the call alone. The list is
kept in `renderoptions` because that is the module which reads them, and a test
asserts that every `OPENGLCONTEXT_*` name the package mentions is either in it
or deliberately excluded: **the next variable added is exactly the one nobody
would think to clear.**

`OpenGLContext/bin/gltf_regression.py` and `tests/unit/test_shadow_rendering.py`
are the two callers today.


## The Parthenon conformance views fail intermittently in a full run

**Open.** `test_gltf_conformance[Parthenon__camNN]` fails for a *varying* subset
of its ten baked cameras, only ever in a full `tests/unit` run, and never when
the file is run on its own.

The measurements that bound it:

| Run | Result |
|---|---|
| full `tests/unit` | 3 failed — `cam01`, `cam03`, `cam04` |
| full `tests/unit`, identical code and command | 0 failed |
| `test_gltf_conformance.py` alone | 312 passed |
| an earlier full run (2026-07-29) | 2 failed — `cam08`, `cam09` |

**A correct render is bit-identical to its baseline** — surviving artifacts from
a passing run compare at 0.000% of pixels differing, for every camera including
the ones that fail elsewhere. So this is not tolerance creep or anti-aliasing
noise: a failing capture is a materially different frame.

That rules out the model having moved, which an earlier version of this note
gave as the cause. A stale baseline is a *constant* diff, and would fail the
same cameras in isolation and in a full run, every time.

What remains is capture readiness. `gltf_regression.render_view` captures after
`--frames 8` plus `--capture-delay 0.5`, which is a floor rather than a signal
that the scene finished loading; the Parthenon is by far the heaviest model in
the roster, and a full run is the only context where the machine is busy enough
for eight frames not to be enough. The environment-inheritance cause described
in the section above is already fixed for this caller and is not it —
`render_view` builds the child environment with `renderoptions.clean_environment`.

**The fix is a readiness signal, not a longer delay.** A bigger
`--capture-delay` moves the race rather than removing it; the viewer should
report when the scene's resources are actually resident and the capture should
wait for that. Until then a full-run failure here is a real red that has to be
re-run to interpret, which is exactly the state a suite should not be in.
