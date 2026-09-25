Testing what you draw
=====================

.. rst-class:: introduction

``OpenGLContext.testing`` provides tools for testing rendering code:

- pytest fixtures that give a test a hidden GL window in the test process;
- a runner for tests that start a whole application in a child process;
- a pixel comparison that checks a rendered frame against an approved
  reference image;
- test conventions for the defects no static check finds: a memo missing an
  input, work repeated in a still frame, cost that grows faster than the
  scene, an optional layer that keeps failing, geometry drawn inside out
  under a mirror, a file opened outside the engine's openers, and a NaN made
  from numbers.

It ships with the engine, so a game built on OpenGLContext can test its
rendering the same way the engine tests its own.

.. _fixtures:

A GL context in the test process
--------------------------------

Turn the fixtures on in the project's pytest configuration:

.. code-block:: toml

   [tool.pytest.ini_options]
   addopts = "-p OpenGLContext.testing.plugin"

A test then requests a context by naming a fixture:

.. code-block:: python

   def test_the_glow_spreads(gl_context):
       from OpenGLContext.passes.bloom import BloomPass
       ...                                   # the context is current here

The plugin provides three fixtures:

``gl_context``
   A hidden core-profile 3.3 window, 64×64 pixels, current for the test.
``gl_context_compat``
   The same in the compatibility profile, for fixed-function code such as
   ``glFrustum``, display lists and the GLU tessellator. It skips where the
   driver returns a core context for a compatibility request.
``gl_window``
   The factory the other two use, for a test that needs a different size,
   profile or window hint. Every window it makes is destroyed when the test
   ends. Creating a second window makes the second one current, so a test
   can check that a resource cached for one context is not reused in
   another.

To change the size or profile, build the fixture on ``gl_window`` rather
than on GLFW directly:

.. code-block:: python

   @pytest.fixture
   def gl_context(gl_window):
       return gl_window('bloom', size=(96, 96))

   @pytest.fixture
   def gl_context(gl_window):
       """The fixed-function draw, which is compatibility-only."""
       return gl_window('nurbs', profile='compatibility')

All three fixtures **skip** the test when the machine has no GL target.
Invalid arguments, such as an unknown profile name, raise ``ValueError``
instead, so a mistake does not silently skip the test.

These fixtures create a bare GLFW window. A test that runs a whole
``Context``, such as a demo script or an application's context class,
declares the profile on the class instead. The profile then applies on
whichever backend is running:

.. code-block:: python

   class TestContext( BaseContext ):
       profile = 'compatibility'   # this test draws with the fixed-function pipeline

See :ref:`Saying which profile your program needs <core-profile>` for how
this combines with other settings.

.. _window:

How the test window is set up
-----------------------------

The window is never shown. A suite with hundreds of rendering tests would
otherwise flash hundreds of windows on screen and take keyboard focus. A
hidden window renders and reads back the same pixels. On Wayland, a hidden
window also keeps the buffer swap from blocking on the compositor.

Window hints are reset first. GLFW window hints are global to the process
and persist, so without a reset a test gets the window the previous test
requested. Every fixture window starts from ``glfw.default_window_hints()``.

Each test gets its own window. GL state belongs to a context, so a test
sharing another test's context also shares whatever that test left enabled,
bound or compiled. When all the tests in a file share one scene, give the
fixture a wider scope:

.. code-block:: python

   @pytest.fixture(scope='module')
   def gl_context():
       with hidden_window('teapot', size=(256, 256)) as window:
           yield window

Framebuffer hints are requests. A hint such as ``ALPHA_BITS``,
``DEPTH_BITS`` or ``SAMPLES`` asks for part of a pixel format, and the
driver returns the nearest format it offers. A window requested with
``{'ALPHA_BITS': 0}`` has eight bits of alpha on a desktop that offers no
format without alpha. If a test depends on the format, it should query the
framebuffer rather than assume the hint was honoured.

.. _without-pytest:

Without pytest
--------------

The window code does not depend on pytest, so a script or another test
runner can use it directly:

.. code-block:: python

   from OpenGLContext.testing.glcontext import GLUnavailable, hidden_window

   try:
       with hidden_window('probe', size=(128, 128), profile='core'):
           ...
   except GLUnavailable as err:
       print('no GL here:', err)

``gl_available()`` returns whether a context can be created at all, for
example for a module-level ``skipif``. It is computed once per process.

``describe_gl()`` returns a description of the GL implementation: the
vendor, renderer and version strings, and whether it rasterises on the CPU.
It returns ``None`` when no context can be created. It shares its probe
window with ``gl_available()``.

.. code-block:: python

   from OpenGLContext.testing.glcontext import describe_gl

   description = describe_gl()
   if description is not None and description.software:
       ...                       # llvmpipe, SwiftShader, GDI Generic, ...

.. _windowless:

Testing without a window
------------------------

``OPENGLCONTEXT_TEST_WINDOWING=offscreen`` gives every test a context on a
surface allocated by the display driver, instead of a hidden window. Use it
where no windowing toolkit can open a window: in a service, in a container
with no desktop, or on a machine without GLFW.

.. code-block:: bash

   OPENGLCONTEXT_TEST_WINDOWING=offscreen pytest tests/unit

The backend is the platform's :doc:`offscreen context <offscreen>`: an EGL
pbuffer on Linux and a WGL pbuffer on Windows. On a platform without one,
such as macOS, no window is opened: ``GLUnavailable`` is raised, and the
fixtures skip their tests with a message saying to unset the variable. The
default, ``OPENGLCONTEXT_TEST_WINDOWING=glfw``, uses the hidden GLFW window
described above.

On Linux the offscreen context renders on an EGL *device*, not through a
display server, so it needs no ``DISPLAY``, no ``WAYLAND_DISPLAY`` and no
windowing library. That is how it differs from the default: a hidden GLFW
window also works on a machine with no desktop, but it needs GLFW installed.
``OPENGLCONTEXT_EGL_DEVICE`` selects the device, as it does for
``EGLContext``; see :doc:`offscreen`. The context class,
``OpenGLContext.eglcontext.PbufferContext``, can also be used on its own::

   from OpenGLContext.eglcontext import PbufferContext

   with PbufferContext(width=96, height=48) as gl:
       glReadPixels(0, 0, gl.width, gl.height, GL_RGB, GL_UNSIGNED_BYTE)

In both modes a test gets a current context with the profile and size it
requested. The difference is the object the fixture yields: an offscreen
context instead of a GLFW window handle. A test that only needs a current
context is unaffected. A test that uses the window handle should call the
helpers in ``OpenGLContext.testing.glcontext``, which work in both modes:

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

A test that queries GLFW about the window itself, such as whether it is
mapped or whether a hint took effect, has nothing to query in offscreen mode.
Skip it when ``glcontext.windowing() != 'glfw'``.

.. _offscreen:

Headless runners
~~~~~~~~~~~~~~~~

``display_available()`` returns whether OpenGL can render on this machine:
either a windowed display exists, or an offscreen platform is selected with
``PYOPENGL_PLATFORM=egl`` (or ``osmesa``). Counting the offscreen case keeps
a visual suite on a headless runner from skipping every test and reporting
success without drawing anything. Running under a virtual X server
(``xvfb-run``) also works.

Two environment variables configure a test run and are passed on to child
processes:

- ``OPENGLCONTEXT_HIDDEN=1`` keeps windows off the screen.
- ``OPENGLCONTEXT_NO_VSYNC=1`` stops a buffer swap from waiting for a
  compositor frame callback.

Set ``OPENGLCONTEXT_HIDDEN=0`` to watch a test render, for example to see
why its output looks wrong.

macOS with no window server
~~~~~~~~~~~~~~~~~~~~~~~~~~~

``hidden_window`` creates a GLFW window where it can, and falls back to
**CGL** where it cannot. GLFW only requests an *accelerated* pixel format on
macOS. On a machine with no accelerated renderer, such as a virtual machine,
a CI runner or a machine with no logged-in session, GLFW cannot create a
context whatever the hints. CGL, the layer NSGL is built on, can.

Tests need no changes. ``backend()`` returns which one was used. Two helpers
cover the places where a window and an offscreen target differ:

``framebuffer_size(window)``
   Returns the framebuffer size. The fixtures yield a GLFW window handle
   under GLFW and an ``OffscreenWindow`` under CGL, and this works with
   either.
``color_buffer_attachment()``
   Returns the attachment holding the colour buffer: ``GL_BACK_LEFT`` for a
   window, ``GL_COLOR_ATTACHMENT0`` for an offscreen target, which is a
   framebuffer object.

A CGL context has no drawable, so it has no framebuffer zero. An offscreen
target is bound in its place, and drawing and reading back work as they do
on a window. macOS has no compatibility profile above GL 2.1, so the
fixed-function render paths and ``gl_context_compat`` skip there, with that
as the reason.

.. _markers:

Test markers
------------

Four markers say what a test needs from the machine, so a run can select the
tests the machine can run.

``gl_context(profile=..., backend=..., **options)``
   The test is about one kind of context. The options are set for the test,
   passed to any child process it starts, and restored afterwards. The test
   is skipped where the machine cannot provide that kind of context, such as
   a compatibility-profile test on a core-only driver, or a GLUT test where
   GLUT is not installed. A test with no marker uses the run's context; see
   :ref:`Which context a run gets <testing-choosing>`.
``performance``
   The test asserts how fast something draws. A CPU rasteriser is slower by
   orders of magnitude, so the plugin skips these tests where
   ``describe_gl().software`` is true, and names the renderer in the skip
   reason. ``OPENGLCONTEXT_PERFORMANCE_TESTS=1`` runs them anyway, for
   profiling the software rasteriser itself. ``=0`` skips them on any
   renderer, which suits a shared or throttled machine. Any other value is
   an error.
``serial``
   The test needs a quiet machine, because it measures a wall-clock margin
   that closes under load. Run the suite in two passes: ``-m "not serial"``
   and then ``-m serial``. Every ``performance`` test is also ``serial``, but
   not every ``serial`` test is a ``performance`` test.
``visual``
   The test compares a rendered frame against an approved reference image.
   The references are made on one renderer, and another renderer differs from
   them by more than the tolerance allows; see :ref:`Comparing pixels
   <pixels>`.

.. _cost-per-object:

Counting work instead of time
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A timing assertion depends on the machine as well as the engine. Where a
test can check the *work* a frame does instead, it should.
``tests/unit/test_per_object_frame_cost.py`` renders a field of
shadow-casting level-of-detail chains at two sizes and reads three counts:

- how many times a node path's world position was queried;
- how many shadow casters had their world geometry recomputed;
- how many times the scene's detail levels were chosen.

In a scene where nothing has moved, the last two are zero and the first is
one per path, on every machine. A change that adds per-object work to each
frame changes these counts at once, where a fast machine might hide it in
the timings.

The test also measures frame time, as the slope between the two scene sizes,
so the fixed cost per frame cancels out. The assertion is on the processor
time one more object adds. That check is marked ``performance`` as well as
``serial``. See `the plan
<https://github.com/mcfletch/openglcontext/blob/main/plans/PER-OBJECT-FRAME-COST.md>`__
for the measurements.

Continuous integration
~~~~~~~~~~~~~~~~~~~~~~

Continuous integration runs on two OpenGL implementations that are free for
a public repository: Mesa's llvmpipe on a Linux runner under ``xvfb-run``,
and Apple's GL on the macOS runners, which have GPUs. GitHub's GPU runners
are billed per minute for all repositories.

.. code-block:: bash

   xvfb-run -a python -m pytest -m "not serial and not visual and not performance"
   xvfb-run -a python -m pytest -m "serial and not visual and not performance"

To reproduce a CI failure on a machine with a GPU, set
``LIBGL_ALWAYS_SOFTWARE=1`` to use the software renderer.

.. _testing-choosing:

Which context a run gets
------------------------

Two settings decide what kind of GL a test gets. Both are set once for the
whole run:

``PYOPENGL_PLATFORM``
   Which PyOpenGL platform module loads, and so which library GL functions
   such as ``glViewport`` come from. On Linux the plugin sets ``egl``, which
   renders without an X display. On other platforms PyOpenGL's default is
   used (WGL on Windows, the OpenGL framework on macOS), and the variable is
   not set.
``OPENGLCONTEXT_BACKEND``
   Which windowing toolkit creates the context: the first of GLFW, pygame, wx
   and GLUT that imports. Without this, the engine takes the first
   registered backend, so machines with different packages installed would
   run different code.

``OpenGLContext.testing.plugin`` sets both before anything imports
``OpenGL``. **A test module must not set them.** A module-level
``os.environ`` write runs during collection, so it applies to the whole
session and to every child process, and the result depends on collection
order. For example, ``PYOPENGL_PLATFORM=egl`` set by one module reaches every
script the suite starts; on Windows, which has no EGL, every GL entry point
is then undefined. OGC161 of the :doc:`static checks <checks>` enforces this
rule on every module's source, and
``tests/unit/test_no_configuration_at_import.py`` on what a program imported
during collection settles.

Instead, from the least to the most specific:

- Take the run's context. Most tests need nothing more.

- Use a fixture: ``gl_context``, ``gl_context_compat`` or ``gl_window`` give
  an in-process window of a given profile, and skip where the driver cannot
  provide one.

- Use the ``gl_context`` marker for a test about one kind of context,
  including one that renders in a child process. The marker sets what it
  names, passes it to child processes, restores it afterwards, and skips
  where that kind of context is not available.

- Use ``monkeypatch.setenv`` for a render option that one test needs.

The plugin records the run's configuration before any test module is
imported. It restores that configuration after collection and after every
test.

It restores after collection because importing one of this project's
programs, such as ``oglc-terrain`` or ``oglc-gltf-demo``, sets that program's
renderer choice as it loads. Nothing in the importing module shows this, and
the choice would otherwise apply to the whole run. To import a program
without its settings, use ``import_unconfigured``, for example
``import_unconfigured('OpenGLContext.bin.view')``.

After every test, everything under ``OPENGLCONTEXT_`` and ``PYOPENGL_`` is
restored to the run's values. Those variables are *configuration*: they
decide what kind of context a program gets. The display, the driver's own
variables and the interpreter paths describe the *machine*, and child
processes receive all of them. ``OpenGLContext.testing.gl_env`` separates
the two:

.. code-block:: python

   from OpenGLContext.testing.gl_env import gl_subprocess_env
   subprocess.run([sys.executable, '-c', DRIVER], env=gl_subprocess_env())

A child process started this way gets the machine's variables, the run's
configuration, the settings of the running test's marker, and whatever the
call adds. It gets nothing a previous test left behind.

.. _subprocess:

A whole application in a child process
--------------------------------------

Some tests are about the whole application: that it starts, draws a frame
and exits, that a command-line option reaches the renderer, or that memory
does not grow over a hundred frames. These run in a child process, where a
crash is a return code rather than the end of the test run.

.. code-block:: python

   from OpenGLContext.testing.subprocess_runner import run_test_with_popen

   result = run_test_with_popen(script, args=['--frames', '8'], timeout=30)
   assert result.success, result.stderr

The runner tracks the child's process id, so a timeout kills the child's
whole process tree and not the runner. A context exits by itself after
``OPENGLCONTEXT_AUTO_EXIT_FRAMES`` frames. When
``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_DIR`` and
``OPENGLCONTEXT_AUTO_EXIT_CAPTURE_NAME`` are set, it writes a screenshot
there before exiting.

Build the child's environment rather than copying the parent's. The
parent's environment can hold ``OPENGLCONTEXT_*`` variables set by tests or
by imported programs. A child started with ``dict(os.environ)`` renders with
all of them, so its result depends on which tests ran first.
``gl_subprocess_env()`` starts from the system and graphics variables only
and adds what the caller names. ``renderoptions.clean_environment()`` does
the same, for a caller that wants the full list of what is removed. Use one
of them for any child whose frame will be compared against a reference.

Tests can send events to a child process over a socket to click, type and
request a capture. ``OpenGLContext.testing.event_injector`` has both ends.
Both are given the same path: ``--event-socket`` on the application, and
the same string to ``EventSender``. The transport is a Unix domain socket
where the platform has them; otherwise it is a loopback TCP port, whose
number the listener writes to a file at that path. A second transport,
``--event-stdin``, reads events from standard input. It makes standard input
non-blocking with ``fcntl``, so it works on POSIX systems only.

.. _pixels:

Comparing pixels
----------------

``OpenGLContext.testing.framebuffer_comparison`` reads a frame back and
compares it with an approved reference. The comparison uses a **percentage
tolerance**: by default, up to 2% of pixels may differ by more than 5 in any
channel. It is not a byte-for-byte match, because rasterisation,
anti-aliasing and gamma differ between GPUs. For byte-identical references,
use a software rasteriser (``LIBGL_ALWAYS_SOFTWARE=1``).

Adaptive rendering
~~~~~~~~~~~~~~~~~~

The number of directional-shadow cascades and the image-based lighting mode
both adapt to the frame rate. A capture fixes them, so the compared frame
does not depend on when it was taken. ``OPENGLCONTEXT_SHADOW_CASCADES=n``
fixes the cascade count, and a capture fixes the IBL at the mode the GPU
supports. A scene loaded through the viewer also fixes its ``anim_time``.

A run counts as a capture when it is bounded by
``OPENGLCONTEXT_AUTO_EXIT_FRAMES``, or when the viewer is running a settle
capture. The adaptive code paths check ``Context.renderingForCapture``. For a
run that is neither, ``OPENGLCONTEXT_IBL=full`` or ``analytic`` fixes the IBL
mode by name. The viewer's own ``capturing`` flag is narrower: it is set only
for a settle capture, and makes the viewer load its scene before the main
loop starts and run no simulation.

Time in a capture
~~~~~~~~~~~~~~~~~

A capture counts frames, not seconds. A scene animated by the wall clock
reaches a different point on a fast machine than on a slow one. Under
``OPENGLCONTEXT_AUTO_EXIT_FRAMES`` the engine's time source is a
``FixedStepClock`` that starts at zero and advances one frame's worth per
``OnDraw``. A ``TimeSensor`` one third of the way through its cycle is at
the same point in every run on every machine. ``OPENGLCONTEXT_CAPTURE_FPS``
sets a rate other than the default 60, or ``0`` to use real time.

Everything that reads ``OpenGLContext.events.systemtime`` follows this
clock, which includes every ``Timer`` and every ``TimeSensor``. Code that
calls ``time.time()`` directly does not; call ``systemtime.systemTime()``
instead to make it reproducible. State updated from ``OnIdle`` does not
follow the clock either, because the main loop calls ``OnIdle`` as often as
it can. Scripts that update their scene there are listed in
``RANDOMIZED_SCRIPTS`` in ``tests/test_all_scripts.py`` and are checked only
for their exit status.

Reference images
~~~~~~~~~~~~~~~~

The reference images are in ``tests/reference_images``, a git submodule
pointing at the ``openglcontext-reference-images`` repository. The images
are large and are updated on their own schedule. The PNG files are stored in
`Git LFS <https://git-lfs.com/>`__, so run ``git lfs install`` once per
machine; otherwise the checkout contains pointer files instead of images.
Clone with the submodule, or fetch it into an existing checkout:

.. code-block:: bash

   git lfs install                                      # once per machine
   git clone --recurse-submodules https://github.com/mcfletch/openglcontext
   git submodule update --init tests/reference_images   # in an existing clone

The top level holds one frame per test script, named after the script.
``gltf_baseline/`` holds the glTF conformance baselines: one PNG and one JSON
file of capture parameters per sample scene. ``oglc-gltf-regression``
compares against them, and ``--bless`` replaces them after review. A scene
whose ``SceneSpec`` sets ``shadows`` is captured with shadow maps; every other
scene is captured without them. Set
``OPENGLCONTEXT_GLTF_BASELINE`` to use a copy stored elsewhere.

Without the submodule the tests still run. A view with no reference image is
reported as having none; it does not fail.

.. _teardown:

Releasing contexts
------------------

A window is closed through the context that owns it, and the engine's caches
are released while that context is still current. The render pass, the
shader programs, the text renderers and the teapot's vertex arrays hold GL
*names*, and a name is only valid in the context that created it. Closing
one of two windows without making it current first releases names in the
wrong context: the live context loses its programs, and the caches keep the
closed context's names, which can then refer to whatever the driver reuses
them for.

Some driver stacks crash while freeing a context, inside the driver. Two are
known, both under GLFW's Wayland backend, which reaches the driver through
EGL:

- an NVIDIA driver, which crashes in about one teardown in ten inside
  ``libnvidia-eglcore``;
- a Mesa driver, which aborts on an invalid free.

A crash at teardown shows up in whichever test runs next, so it looks like
interference between tests. A ``SIGABRT`` cannot be caught, so one bad
teardown ends the whole run. A test process does not need to release its
contexts, because the operating system reclaims them when the process
exits. On an affected stack, the plugin therefore skips both teardown calls
for the session, and the leaked windows use some memory until the run ends.

The plugin tests the machine rather than assuming.
``OpenGLContext.testing.glfwteardown`` creates and frees windows in a child
process before any test opens a window. If the child aborts, the machine is
affected. On an unaffected machine the engine's normal release path, the
same code an application runs on exit, runs as usual and stays under test.
The workaround applies only on machines that have the defect.

The probe frees 100 contexts, not one. The crash happens in a fraction of
teardowns, so a single teardown would usually pass on an affected stack.
With 100 cycles, the chance of missing a one-in-ten fault is about three in
a hundred thousand. The probe takes about a third of a second, most of it
spent starting the child and opening the first window.

``OPENGLCONTEXT_GLFW_TEARDOWN`` sets the answer for a run on a known stack,
and skips the probe:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Value
     - Effect
   * - ``auto`` (the default)
     - Probe the machine once and act on the result.
   * - ``native``
     - Release every context.
   * - ``neutralised``
     - Leak the contexts: destroy no window and do not terminate GLFW.

.. _timeouts:

Test timeouts
-------------

The suite runs under ``pytest-timeout``, set in ``pyproject.toml`` to
``timeout = 300`` with ``timeout_method = "thread"``. The slowest test that
completes normally takes about 25 seconds, so the limit only catches hangs.

The thread method is required. The default *signal* method raises from a
``SIGALRM`` handler, and Python runs signal handlers only when the main
thread next executes bytecode. A thread waiting on CPython's import lock
never does, because that lock is taken with the GIL released and cannot be
interrupted. A process in that state ignores the timeout and ``SIGTERM``;
only ``SIGKILL`` ends it. The thread method uses a watchdog thread that
prints every thread's stack and ends the process, so a hang becomes a failed
run with the stacks in its output. It ends the whole session, not only the
one test. Treat any timeout as a defect to fix.

A test that waits for a background resource load should wait on the loader
pool, not on a thread name or a sleep; see :ref:`Loading without stopping
the frame <background-loading>`.

.. _skipping:

When a test may skip
--------------------

A skip says the machine lacks something the test needs. Decide it with a
check that does not run the code under test, before that code runs: the
``gl_context`` fixtures and ``gl_available()`` for a GL target,
``profile_unavailable(profile)`` for a context of one profile,
``offscreen_unavailable(profile)`` for a windowless one (all three in
``OpenGLContext.testing.glcontext``), ``pytest.importorskip`` for an optional
package, ``sys.platform`` for a platform. The two ``*_unavailable`` functions
return the reason to skip, or ``None``, and ask once per profile for the
process. Do not catch an exception from the code under test and skip on it.
A loader that raises, a viewer that hangs or a renderer that crashes is then
reported as skipped, in a run that reads green.

A test that reads a published sample, such as a Khronos model or a Poly
Haven panorama, needs a copy in the resolver's cache or a connection to the
host that serves it. ``OpenGLContext.testing.network.unreachable(url)``
answers that without fetching anything, and returns the reason to skip or
``None``:

.. code-block:: python

   from OpenGLContext.testing.network import unreachable

   def test_the_duck_loads():
       reason = unreachable(DUCK_URL)
       if reason:
           pytest.skip(reason)
       scene = load(fetch_to_cache(DUCK_URL))

The fetch then runs unguarded, so a defect in the resolver or the loader
fails the test. A host's answer is kept for the life of the process, and a
host that does not accept a connection within five seconds counts as
unreachable.

.. _conventions:

Test conventions
----------------

Each convention is a function in a module of ``OpenGLContext.testing`` and a
fixture of the plugin of the same name, so a test either imports it or asks
for it. Each raises an ``AssertionError`` subclass saying what it found, and
each name starts with ``check_``, which is how the ``openglcontext-checks``
rule OGC222 counts a test calling it as one that asserts. The engine's own
use of each is named below; those tests are the fuller examples.

A scene drawn in the test
~~~~~~~~~~~~~~~~~~~~~~~~~

``OpenGLContext.testing.scenes.scene_context(children, size=(96, 96))`` is a
context drawing a scenegraph of ``children``, current for a ``with`` block
and released when it ends. The context is the interactive context of the
backend the run uses, or ``base`` where a project has its own. It is hidden,
does not wait for the display's refresh, draws no frame-rate counter and pins
image-based lighting to ``analytic``; ``environment`` sets further
``OPENGLCONTEXT_*`` values for the block and puts the old ones back, and any
other keyword is a ``ContextDefinition`` field. ``context.OnDraw(force=1)``
draws a frame, and ``drawn_image(context)`` draws one and returns it as a
top-down ``(H, W, 3)`` array. The ``scene_context`` fixture skips the test
where no core-profile context can be made.

A memo follows every input
~~~~~~~~~~~~~~~~~~~~~~~~~~

A memo keeps an answer against what it was made from. An input it does not
compare is an edit it does not see, and the next frame is drawn from the
stale answer. ``OpenGLContext.testing.memo.check_memo_inputs(ask, inputs,
fresh=...)`` takes a way to ask the memo, one edit per input (a mapping of
name to callable, or ``(name, edit)`` pairs, applied in order), and the
computation with no memo in the way. It applies each edit and fails naming
every input whose edit the memo did not follow, every edit after which the
memo answers differently from ``fresh``, and every edit that changes nothing:

.. code-block:: python

   from OpenGLContext.testing.memo import check_memo_inputs

   def test_the_level_memo_follows_its_fields():
       check_memo_inputs(ask, [
           ('LOD.range', lambda: setattr(node, 'range', [20.0, 30.0])),
           ('LOD.hysteresis', lambda: setattr(node, 'hysteresis', 0.0)),
       ], fresh=lambda: [node.levelAt(distance, 1.0, 1.0)])

Make the nodes an edit sets before the edits start: making a node sets its
fields, and a field set moves the generation counts memos compare, which
would hide a missed input. ``same`` compares two answers where ``==`` does
not. ``tests/unit/test_memo_inputs.py`` holds the batching, mirror,
level-of-detail and zone placement memos to it.

A still frame asks nothing new of GL
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A frame of a scene nothing has changed in should find every buffer, texture
and program made and filled. ``OpenGLContext.testing.stillframe.
check_still_frame(draw, allocations=0, uploads=0, compiles=0, warmup=3)``
draws ``warmup`` frames, counts the GL calls of the next, and fails where the
frame made more GL objects, filled more buffers or textures, or compiled or
linked more than the floors given. The failure names each call and the line
that made it:

.. code-block:: python

   from OpenGLContext.testing.stillframe import check_still_frame

   def test_the_menu_over_the_level_costs_nothing(scene_context):
       with scene_context(level_children) as context:
           check_still_frame(lambda: context.OnDraw(force=1), warmup=8)

``counting_gl(names)`` is the shim underneath: it replaces each named entry
point wherever a loaded module or PyOpenGL's buffer implementation holds it,
counts the calls from any thread, and puts every one back. A function that
bound an entry point to a local name before the count began is not counted.
``tests/unit/test_still_frames.py`` holds six scenes to a floor of nothing.

Cost that grows with the scene
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``OpenGLContext.testing.scaling.check_scaling(prepare, n=..., most=...,
factor=4, measure='time')`` builds the scene at ``n`` and at ``factor * n``
with ``prepare(size)``, which returns the work as a callable, runs the work
once at each size and then measures it, and fails where the larger costs more
than ``most`` times the smaller. ``measure='count'`` takes the number the work
returns (objects touched, records built) instead of its time; a count is the
same on every machine and is the better measure where the work can give one.
A timed test carries the ``serial`` marker, and the fixture refuses one that
does not. Linear work at a factor of 4 costs about 4 times as much, work
independent of the scene about 1, and work growing as the square about 16:

.. code-block:: python

   @pytest.mark.serial
   def test_classifying_grows_with_the_objects(check_scaling):
       def prepare(objects):
           table, lows, highs = road(objects)
           return lambda: table.classify_many(lows, highs)
       check_scaling(prepare, n=5000, most=6.0, repeat=3)

``tests/unit/test_scaling.py`` holds zone classification, the mirror planner
and ground cover to it.

An optional layer that fails
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Reflections, bloom and zone captures add to a frame that is complete without
them, and one that fails is switched off and reported once
(``passes/layerguard.LayerGuard``). ``OpenGLContext.testing.layers.
check_failing_layer(frame, owner, name, frames=10, context=None)`` replaces
``owner.name`` with a method that raises, draws ``frames`` frames, and fails
where the layer was entered more than once, its failure was logged other than
once, or it asked for a frame (``context.triggerRedraw``) after it failed:

.. code-block:: python

   def test_reflections_that_fail_are_switched_off(scene_context):
       with scene_context(mirror_room) as context:
           for _ in range(8):
               context.OnDraw(force=1)
           check_failing_layer(lambda: context.OnDraw(force=1),
                               renderpass.FLAT, '_renderReflections',
                               context=context)

``attempts``, ``reports`` and ``most_asked`` change the bounds for a layer
that is tried once per item. ``tests/unit/test_failing_layers.py`` holds
reflections, bloom and zone captures to it.

Geometry under a mirror
~~~~~~~~~~~~~~~~~~~~~~~

A transform with a negative determinant turns every triangle's winding over,
and a geometry that culls its back faces must turn its front face with it.
``OpenGLContext.testing.mirrored.check_mirrored_render(geometry)`` draws the
geometry in front of a camera at the origin, and again inside
``Transform(scale=(-1, 1, 1))``, and fails where the second picture differs
from the first turned left to right over more than ``most_differing`` of the
frame (default 2%), or where the geometry covers less than ``least_drawn`` of
it. ``appearance``, ``distance``, ``size`` and ``environment`` (a renderer,
say) are passed through. ``tests/unit/test_mirrored_geometry.py`` holds every
geometry the engine registers to it and fails when a new one has neither a
case nor a stated reason.

Floating-point errors
~~~~~~~~~~~~~~~~~~~~~

The plugin's ``numpy_errors`` setting runs each test inside
``numpy.errstate`` with that action for division by zero, overflow and
invalid operations: ``raise`` makes a NaN or an infinity made from numbers a
``FloatingPointError`` where it is made. Underflow is left alone, since a
result too small for its type becoming zero is the answer. Unset, NumPy's own
setting stands; ``--numpy-errors`` overrides the ini value. It holds on the
test's own thread. A test that means to make a NaN says so with
``numpy.errstate`` around it. OpenGLContext's suite runs with ``raise``:

.. code-block:: toml

   [tool.pytest.ini_options]
   numpy_errors = "raise"

Files opened outside the sanctioned openers
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A path a document names reaches the disk through the resolver, which holds
it to the directory it was named in, and a file is written through
``OpenGLContext.atomicfiles``. The open audit (``OpenGLContext.testing.
openaudit``) is a ``sys.audit`` hook that charges each file opened to the
innermost module of a checked package on the stack, and records it where
that module is not a sanctioned opener. Opens the import system or traceback
formatting make on a module's behalf, a package's own data files and file
descriptors are not recorded. A package name sanctions every module in it.

``open_audit = "fail"`` fails the test that opened such a file, at teardown,
naming the module, the line and the path; ``"report"`` lists each as an
``OpenAuditWarning`` in the run's warnings summary; ``"off"``, the default,
installs nothing. ``open_audit_checked`` defaults to ``OpenGLContext``, and
``open_audit_sanctioned`` to the engine's openers:

.. code-block:: toml

   [tool.pytest.ini_options]
   open_audit = "fail"
   open_audit_checked = ["OpenGLContext", "mygame"]
   open_audit_sanctioned = [
       "OpenGLContext.loaders.resolver",
       "OpenGLContext.contentpacks",
       "OpenGLContext.atomicfiles",
       "OpenGLContext.testing",
       "mygame.savegames",
   ]

A project listing its own openers names the engine's as well. The hook costs
about 4 microseconds an open that reaches a checked module; over the engine's
unit suite the difference is inside the run-to-run spread. OpenGLContext's
suite runs with ``fail``, and its ``pyproject.toml`` lists which modules open
files and why.

.. _what-to-test:

What to put in a test
---------------------

Move logic out of windowed classes. A rule, loop or state machine inside a
class whose setup opens a GL surface is hard to test in isolation. Move it
into a plain object that takes its time step and inputs as arguments and
holds no GL. Keep the windowed class as a thin shell that creates the
object, feeds it and draws the result. ``gl_context`` is then needed only
for the part that has to draw.

Test the real code. Prefer real geometry, real nodes and a real context to
mocks. A test that replaces every collaborator with a stub only tests the
stubs. Use mocks for conditions that are hard to produce, such as a specific
GL error, missing hardware or a network failure.

Use smoke tests for anything random. A reference image of a particle system
is a picture of one random sequence. Assert that pixels changed where they
should have changed instead.
