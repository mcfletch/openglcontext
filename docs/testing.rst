Testing what you draw
=====================

.. rst-class:: introduction

Some of what an application draws can only be checked by drawing it.
``OpenGLContext.testing`` is what that takes: a hidden GL window for a test
that renders in its own process, a runner for the tests that need a whole
application in a child process, and the pixel comparison that says whether the
frame is the one you blessed. It ships with the engine, so a game built on
OpenGLContext tests its rendering the same way the engine tests its own.

.. _fixtures:

A GL context in the test process
--------------------------------

Turn the fixtures on from the project's pytest configuration:

.. code-block:: python

   [tool.pytest.ini_options]
   addopts = "-p OpenGLContext.testing.plugin"

and a test can ask for a window:

.. code-block:: python

   def test_the_glow_spreads(gl_context):
       from OpenGLContext.passes.bloom import BloomPass
       ...                                   # the context is current here

Three fixtures come with the plugin:

``gl_context``
   A hidden core-profile 3.3 window, 64×64, current for the test.
``gl_context_compat``
   The same in the compatibility profile, for the fixed-function paths —
   ``glFrustum``, display lists, the GLU tessellator. It skips where the driver
   answers a compatibility request with a core context, since nothing that wants
   one would work in it.
``gl_window``
   The factory both are built on, for a test that wants a different size, profile
   or hint. Every window it makes is destroyed when the test ends, and asking for
   a second one leaves *it* current — which is how a test proves that a resource
   cached against one context is not handed to the next.

A test that wants its own size or profile builds it on the factory rather than
on GLFW:

.. code-block:: python

   @pytest.fixture
   def gl_context(gl_window):
       return gl_window('bloom', size=(96, 96))

   @pytest.fixture
   def gl_context(gl_window):
       """The fixed-function draw, which is compatibility-only."""
       return gl_window('nurbs', profile='compatibility')

All three **skip** rather than fail where there is no GL target, which is what
a machine without one should get. A typo in the arguments — a profile nobody
offers — is a ``ValueError`` instead, because skipping it would hide the test
for good.

These fixtures make a bare GLFW window. A test that drives a whole ``Context``
— a demo script, an application's own context class — declares the profile on
the class instead, and gets it on whichever backend is running:

.. code-block:: python

   class TestContext( BaseContext ):
       profile = 'compatibility'   # this test draws with the fixed-function pipeline

See :ref:`Saying which profile your program needs <core-profile>` for what
that composes with.

.. _window:

What the window is
------------------

**It is never mapped.** A suite with hundreds of rendering tests in it would
otherwise flash hundreds of windows over whatever the person running it is
doing, and steal focus while they type. A hidden window renders and reads back
identically — every ``glReadPixels`` sees the same pixels — and on Wayland it
is also the only way a swap is guaranteed not to block on a compositor that
has nothing to show.

**The hints are reset first.** GLFW window hints are process-global and
sticky, so a window asked for without a reset is the window the *previous*
test asked for. Every context from these fixtures starts from
``glfw.default_window_hints()``.

**One window per test.** GL state is global to a context, so a test that
inherits another's context inherits whatever it left enabled, bound and
compiled. Where a whole file's worth of tests genuinely shares one scene, say
so with a scope:

.. code-block:: python

   @pytest.fixture(scope='module')
   def gl_context():
       with hidden_window('teapot', size=(256, 256)) as window:
           yield window

**A framebuffer format is negotiated, not granted.** A hint naming part of it
— ``ALPHA_BITS``, ``DEPTH_BITS``, ``SAMPLES`` — is a request, and the driver
answers with the nearest pixel format it offers. A window asked for with
``{'ALPHA_BITS': 0}`` comes back with eight bits of alpha on a desktop that
has no alpha-less format, so a test that depends on what it got should ask the
framebuffer rather than assume the hint was granted.

.. _windowless:

Or no window at all
-------------------

``OPENGLCONTEXT_TEST_WINDOWING=offscreen`` gives every test a context on a
surface the display driver allocates instead of a hidden window, so the suite
runs where there is no windowing toolkit to open one with — a service, a
container with no desktop, a machine with no GLFW installed:

.. code-block:: bash

   OPENGLCONTEXT_TEST_WINDOWING=offscreen pytest tests/unit

The backend is the platform's: a :doc:`WGL pbuffer <offscreen>` on Windows. A
platform with none says so rather than opening a window the run asked not to
have, and ``OPENGLCONTEXT_TEST_WINDOWING=glfw`` (the default) is the hidden
window described above.

**What a test gets is the same either way** — a current context of the profile
and size it asked for. What differs is the handle the fixture yields, which is
the offscreen context rather than a GLFW window. A test that only needs *a*
context never notices. One that reaches past the context to the window uses
the helpers that work under both:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Instead of
     - Use
   * - ``glfw.make_context_current(handle)``
     - ``glcontext.make_current(handle)``
   * - ``glfw.make_context_current(None)``
     - ``glcontext.release_current()``
   * - ``glfw.get_framebuffer_size(handle)``
     - ``glcontext.framebuffer_size(handle)``

A test that genuinely asks GLFW about a window — whether it is mapped, whether
a hint reached it — has nothing to ask under ``offscreen``, and skips on
``glcontext.windowing() != 'glfw'``.

.. _teardown:

Handing the contexts back
-------------------------

A window closes through the context that owns it, and the engine's caches are
told while that context is still current: the render pass, the shader
programs, the text renderers and the teapot's vertex arrays all hold GL
*names*, and a name means something only in the context that issued it.
Closing one of two windows without making it current first retires the wrong
one — the live context loses its programs, and the closed context's names stay
reachable by whatever the driver hands the address to next.

Some driver stacks fault while freeing a context, from inside the driver and
with nothing of ours on the stack. Two have been seen, both under GLFW's
Wayland backend, which reaches the driver through EGL: an NVIDIA one that
kills roughly **one teardown in ten** inside ``libnvidia-eglcore``, and a Mesa
one that aborts on a bad free. A fault at teardown lands in whatever runs
next, so it reads as flaky pollution between tests rather than as one broken
test, and a ``SIGABRT`` cannot be caught: one teardown takes the whole run
down. A test process has no need to hand its contexts back at all — the OS
reclaims every one of them as the process exits — so on such a stack both
teardown calls are stood down for the session and the windows a run leaks cost
a little memory until it ends.

**Which stack this is, is asked rather than assumed.**
``OpenGLContext.testing.glfwteardown`` builds a window in a child process and
frees it; if the child aborts, this machine is one of them. Where it does not,
the engine's own release path — the code a user's application runs on exit —
runs as it normally does, and so stays under test. That is what stops the
workaround outliving the driver defect: it retires itself on the first machine
that no longer needs it. The plugin settles this once, before anything opens a
window.

**The probe frees a hundred contexts, not one.** The fault it is looking for
is a fraction of teardowns rather than every one, so a short probe would
answer “sound” on a faulting stack most of the time and wave the run through
to crash as it would have anyway. A hundred cycles puts the chance of missing
a one-in-ten fault at three in a hundred thousand, and costs nothing
measurable: starting the child and opening the first window is the whole
expense, so the probe takes about a third of a second either way.

``OPENGLCONTEXT_GLFW_TEARDOWN`` pins the answer for a run whose stack is
already known, which also skips the probe:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Value
     - What the run does
   * - ``auto`` (the default)
     - Ask this machine, once, and act on the answer.
   * - ``native``
     - Release every context, whatever the driver does with it.
   * - ``neutralised``
     - Leak them: destroy no window and terminate no library.

.. _without-pytest:

Without pytest
--------------

The window machinery has no pytest in it, so a script or another runner can
use it directly:

.. code-block:: python

   from OpenGLContext.testing.glcontext import GLUnavailable, hidden_window

   try:
       with hidden_window('probe', size=(128, 128), profile='core'):
           ...
   except GLUnavailable as err:
       print('no GL here:', err)

``gl_available()`` answers whether a context can be created at all — for a
module-level ``skipif``, say. It is worked out once and remembered, since it
cannot change while the process lives.

``describe_gl()`` answers what the GL *is*: the vendor, renderer and version
strings the driver gave, and whether it rasterises on the CPU. It returns
``None`` where no context can be made, and shares the one probe window with
``gl_available()``.

.. code-block:: python

   from OpenGLContext.testing.glcontext import describe_gl

   description = describe_gl()
   if description is not None and description.software:
       ...                       # llvmpipe, SwiftShader, GDI Generic, ...

.. _markers:

Which tests run where
---------------------

Four markers say what a test needs of the machine it runs on, so a run can ask
for the subset that machine can answer.

``gl_context(profile=..., backend=..., **options)``
   This test is about *one kind* of context and no other. The options are set for
   the test and put back afterwards, they reach any child process it launches,
   and the test is skipped where this machine cannot give that kind — a
   compatibility-profile test on a core-only driver, a GLUT test where GLUT is
   not installed. A test with no marker takes whatever the run settled on; see
   :ref:`Which context a run gets <testing-choosing>`.
``performance``
   Asserts how *fast* something draws. That is a question about the renderer as
   much as about the code, and a CPU rasteriser answers it wrongly by orders of
   magnitude — so the plugin skips these where ``describe_gl().software`` is
   true, and names the renderer in the skip reason.
   ``OPENGLCONTEXT_PERFORMANCE_TESTS=1`` runs them anyway, for somebody profiling
   the software rasteriser itself; ``=0`` skips them whatever the renderer, which
   is what a shared or throttled machine wants. A value that is neither is an
   error rather than a silently reversed pin.
``serial``
   Needs a quiet machine. A wall-clock margin closes under concurrent load, so a
   full run is two passes: ``-m "not serial"`` and then ``-m serial``. Every
   ``performance`` test is also ``serial``; the reverse does not follow.
``visual``
   Compares a rendered frame against a blessed reference image. The references
   are blessed on one renderer, so a second one differs from them by more than
   the pixel gate allows — see :ref:`Comparing pixels <pixels>`.

.. _cost-per-object:

Counting the work, not the milliseconds
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A timing assertion is a claim about the machine as much as about the engine,
so where a gate can be written against the *work* a frame does instead, it is.
``tests/unit/test_per_object_frame_cost.py`` renders a field of shadow-casting
level-of-detail chains at two sizes and reads three counts off it: how many
times a path was asked where it is in the world, how many casters had their
world geometry derived, and how many times the scene's levels were chosen. On
a scene where nothing has moved the last two are zero and the first is one per
path, and those answers are the same on every machine — a change that puts
per-object work back into the frame moves them immediately, where it might
hide in the milliseconds on a fast box.

The frame time is tracked alongside them, as the slope between the two sizes
so the fixed cost of a frame cancels: what is asserted is the processor time
one more object adds. That one carries ``performance`` as well as ``serial``.
See `the plan
<https://github.com/mcfletch/openglcontext/blob/main/plans/PER-OBJECT-FRAME-COST.md>`__
for the measurements behind it.

Continuous integration runs on two OpenGL implementations, both free for a
public repository: Mesa's llvmpipe on a Linux runner under ``xvfb-run``, and
Apple's GL on the macOS runners, which are real machines with GPUs. GitHub's
GPU runner is a larger runner, billed per minute and never free, whatever the
repository's visibility.

.. code-block:: bash

   xvfb-run -a python -m pytest -m "not serial and not visual and not performance"
   xvfb-run -a python -m pytest -m "serial and not visual and not performance"

``LIBGL_ALWAYS_SOFTWARE=1`` reproduces the software-rendered run on a machine
that has a GPU, which is how a failure seen in CI is chased locally.

.. _testing-choosing:

Which context a run gets
------------------------

Two settings decide what kind of GL a test is given, and both are answered
once for the run rather than by each test for itself:

``PYOPENGL_PLATFORM``
   Which of PyOpenGL's platform modules loads, and so which library
   ``glViewport`` is looked for in. Linux is asked for ``egl``, which renders
   with no X display; everywhere else PyOpenGL's own default is the only right
   answer — WGL on Windows, the framework on macOS — and naming one would name
   the wrong one.
``OPENGLCONTEXT_BACKEND``
   Which windowing toolkit builds the context: the first of GLFW, pygame, wx and
   GLUT that will actually import. Left unnamed, the engine takes the first
   backend that happens to be registered, so two machines with different packages
   installed run different code.

``OpenGLContext.testing.plugin`` settles both before anything imports
``OpenGL``, so **a test module must not**. A module-scope ``os.environ`` write
runs while pytest is still collecting, which makes it the whole session's
answer and the answer every child process inherits — and what ran is then
decided by collection order. Ten modules once set ``PYOPENGL_PLATFORM=egl``
that way, each reasonably for its own context; on Windows, where there is no
EGL, the value reached every script the suite launched and made every GL entry
point undefined. ``tests/unit/test_no_configuration_at_import.py`` holds the
suite to the rule.

What to do instead, in order of how much a test is asking for:

- **Nothing** — take the run's context. Most tests.

- **A fixture** — ``gl_context``, ``gl_context_compat`` or ``gl_window`` for an
  in-process window of a particular profile, which skip where the driver will
  not give one.

- The ``gl_context`` marker — for a test that is about one kind of context,
  including one that renders in a child process. It sets what it names, passes
  it to children, puts it back, and skips where the kind cannot be had.

- ``monkeypatch.setenv`` — for a render option one test wants and nothing else
  does.

The run's own configuration is taken before a single test module is imported,
and put back both after collection and after every test. After collection
because a module that *imports one of this project's programs* —
``oglc-terrain``, ``oglc-gltf-demo`` — picks up that program's choice of
renderer, since a program about to draw settles one as it loads; nothing in
the importing module's own source says so, and left standing it would become
the whole run's. ``import_unconfigured`` is how a module says it wants the
program and not its choices.

Everything under ``OPENGLCONTEXT_`` and ``PYOPENGL_`` is put back after every
test, to what the run settled on. That is *configuration*: it says what kind
of context a program gets. The display, the driver's own variables and the
interpreter's paths are the *machine*, and a child gets all of those —
``OpenGLContext.testing.gl_env`` is where the two are told apart.

.. code-block:: python

   from OpenGLContext.testing.gl_env import gl_subprocess_env
   subprocess.run([sys.executable, '-c', DRIVER], env=gl_subprocess_env())

A child built that way gets the machine, the run's own configuration, what the
running test declared, and whatever the call names — and nothing a
neighbouring test happened to leave behind.
``import_unconfigured('OpenGLContext.bin.view')`` is the same idea for
importing one of this project's programs, which settle the renderer as they
are imported because they are about to draw.

.. _offscreen:

Rendering offscreen, and on a headless runner
---------------------------------------------

``display_available()`` is the single answer to “can OpenGL render here?”: a
windowed display, or an offscreen platform selected with
``PYOPENGL_PLATFORM=egl`` (or ``osmesa``). Counting the offscreen case is what
stops a visual suite silently skipping and reporting green on a headless
runner without having drawn anything. A virtual X server (``xvfb-run``) is the
other way.

Two environment variables belong to a test run rather than to an application,
and both survive into child processes: ``OPENGLCONTEXT_HIDDEN=1`` keeps
windows off the screen, and ``OPENGLCONTEXT_NO_VSYNC=1`` stops a swap blocking
on a compositor frame callback. Set ``OPENGLCONTEXT_HIDDEN=0`` to watch a test
render, which is how you find out why one looks wrong.

macOS with no window server
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hidden_window`` makes a GLFW window where it can and falls back to **CGL**
where it cannot. GLFW asks macOS for an *accelerated* pixel format and nothing
else, so on a machine with no accelerated renderer — a virtual machine, a CI
runner, a session nobody is logged into — it can create no context at all,
whatever hints it is given. CGL is the layer NSGL is built on and will.

Nothing a test does has to change. ``backend()`` says which one answered, and
the two places where a window and an offscreen target differ have an answer
that works for both:

``framebuffer_size(window)``
   How big the framebuffer is. The fixtures yield a GLFW window handle under GLFW
   and an ``OffscreenWindow`` under CGL, and a test that wants the size should
   not have to know which.
``color_buffer_attachment()``
   Which attachment holds the colour: ``GL_BACK_LEFT`` for a window,
   ``GL_COLOR_ATTACHMENT0`` for an offscreen target, which is a framebuffer
   object.

A CGL context has no drawable and so no framebuffer zero; an offscreen target
is bound in its place, and drawing and reading back behave as they do on a
window. What macOS does not have is skipped rather than substituted: there is
no compatibility profile above 2.1 there, so the fixed-function render arms
and ``gl_context_compat`` skip with that as the reason.

.. _timeouts:

A test that stops answering
---------------------------

The suite runs under ``pytest-timeout``, configured in ``pyproject.toml`` as
``timeout = 300`` with ``timeout_method = "thread"``. The slowest test that
legitimately runs to completion takes about 25 seconds, so the limit is a
backstop rather than a deadline.

The method matters as much as the number. The default *signal* method raises
out of a ``SIGALRM`` handler, and a Python signal handler runs only when the
main thread next executes bytecode — which a thread waiting on CPython's
import lock never does, because that lock is taken with the GIL released and
is not interruptible. A process that reaches that state answers to no signal
at all: neither the timeout nor ``SIGTERM`` reaches it, and only ``SIGKILL``
ends it. The *thread* method is a watchdog thread instead, which prints every
thread's stack and ends the process, so such a hang is a red run with the
evidence in it. It ends the whole session rather than failing one test, which
is the right trade: a timeout here is a defect to stop and fix.

A test that waits on a background resource load waits on the loader pool
rather than on a thread name or a sleep — see :ref:`Loading without stopping
the frame <background-loading>`.

.. _subprocess:

A whole application, in a child process
---------------------------------------

Some tests are about the application rather than about a pass: that it starts,
draws a frame and exits, that a command-line option reaches the renderer, that
a leak does not accumulate over a hundred frames. Those run in a subprocess,
where a crash is a return code rather than the end of the suite.

.. code-block:: python

   from OpenGLContext.testing.subprocess_runner import run_test_with_popen

   result = run_test_with_popen(script, args=['--frames', '8'], timeout=30)
   assert result.success, result.stderr

The runner knows the child's process id, so a timeout reaps the whole process
tree rather than the runner itself. A context exits by itself after
``OPENGLCONTEXT_AUTO_EXIT_FRAMES`` frames, and writes a screenshot on the way
out when ``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR`` and
``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME`` say where.

**Build the child's environment rather than inheriting it.** Test modules set
``OPENGLCONTEXT_*`` variables at import time to configure their own renderer,
and those writes persist in the parent, so a child started with
``dict(os.environ)`` renders with whatever the run has accumulated — which
makes its result depend on collection order. ``gl_subprocess_env()`` starts
from the system and graphics variables alone and adds exactly what the caller
names; ``renderoptions.clean_environment()`` does the same for a caller that
wants the full list of what to drop. Anything that renders a frame and then
compares its pixels uses one of them.

Events can be injected into such a child over a socket, so a test can click,
type and ask for a capture: ``OpenGLContext.testing.event_injector`` has both
ends. Both name one path — ``--event-socket`` on the application, the same
string to ``EventSender`` — and the transport underneath is whichever the
platform has: a Unix domain socket where there are any, and otherwise a
loopback TCP port whose number the listener publishes in a file at that path.
A second transport reads the events from standard input instead
(``--event-stdin``); it makes that descriptor non-blocking through ``fcntl``,
so it is POSIX-only.

.. _pixels:

Comparing pixels
----------------

``OpenGLContext.testing.framebuffer_comparison`` reads a frame back and
compares it against a blessed one. The comparison is a **percentage
tolerance** — by default 2% of pixels may differ by more than 5 per channel —
not a byte-for-byte match, because cross-GPU rasterization, anti-aliasing and
gamma differ. Pin a software rasterizer (``LIBGL_ALWAYS_SOFTWARE=1``) where
byte-stable references are wanted.

A frame is only comparable if the renderer was told to stop adapting.
Directional-shadow cascade count and image-based lighting both follow the
frame rate, so a capture pins them: ``OPENGLCONTEXT_SHADOW_CASCADES=n`` fixes
the cascades, and the capture path fixes the IBL. A scene loaded through the
viewer pins its ``anim_time``. Without that, what is compared is the moment
the capture happened to be taken.

**A capture counts frames rather than seconds.** A scene animated against the
wall clock reaches a different point in its animation on a fast machine than
on a slow one, so the frame read back is a picture of how long the process
took to start. Under ``OPENGLCONTEXT_AUTO_EXIT_FRAMES`` the engine's time
source is a ``FixedStepClock`` starting at zero and advancing one frame's
worth per ``OnDraw``: a TimeSensor a third of the way through its cycle is a
third of the way through it in every run, on every machine.
``OPENGLCONTEXT_CAPTURE_FPS`` names a rate other than 60, or 0 for a capture
that wants to watch real time pass.

Everything reading ``OpenGLContext.events.systemtime`` follows it, which is
every ``Timer`` and every ``TimeSensor``. Code calling ``time.time()`` itself
does not, and has to ask ``systemtime.systemTime()`` instead to be
reproducible. Nor does state advanced from ``OnIdle``, which the main loop
calls as often as it has room for: a scene moved there holds whatever the last
idle wrote rather than what the frame being drawn is worth. The few scripts
that do that are listed in ``RANDOMIZED_SCRIPTS`` in
``tests/test_all_scripts.py`` and are run for their exit status instead.

Every image a regression test compares against lives in
``tests/reference_images``, which is a submodule — the
``openglcontext-reference-images`` repository — because the pictures are large
and are re-blessed on their own schedule rather than when the code changes.
The PNGs are held in `Git LFS <https://git-lfs.com/>`__, so ``git lfs
install`` has to have been run once for the checkout to hold images rather
than pointer files. Clone with them, or fetch them into an existing checkout:

.. code-block:: bash

   git lfs install                                      # once per machine
   git clone --recurse-submodules https://github.com/mcfletch/openglcontext
   git submodule update --init tests/reference_images   # in an existing clone

Its top level holds one frame per test script, looked up by script name.
``gltf_baseline/`` holds the glTF conformance baselines, one PNG and one JSON
of capture parameters per sample scene, which ``oglc-gltf-regression`` diffs
against and ``--bless`` re-establishes after review.
``OPENGLCONTEXT_GLTF_BASELINE`` points at a copy somewhere else.

Without the submodule the tests still run: a view with no reference to compare
against is reported as having none rather than failing.

.. _what-to-test:

What to put in a test, and where
--------------------------------

**Hoist the rule out of the window.** A rule, a loop or a state machine inside
a class whose setup opens a GL surface is code no test can put under a
microscope. Move it into a plain object that takes its time step and its
inputs as arguments and holds no GL, and leave the windowed class a thin shell
that builds one, feeds it and draws the result. What is left for
``gl_context`` is then the part that genuinely has to draw.

**Drive the real thing.** Prefer real geometry, real nodes and a real context
over a mock: a test that replaces every collaborator with a stub proves the
stubs work. Mocks are for the edges that are genuinely hard to produce — a
specific GL error, missing hardware, a network failure.

**Smoke tests over reference images, for anything random.** A reference image
of a particle system is a reference image of a random number generator. Assert
that pixels changed where pixels should have changed.
