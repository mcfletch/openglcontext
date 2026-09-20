OpenGLContext Structural Overview
=================================

.. rst-class:: introduction

How the stack is built up. Each layer is written against the one below it;
blue is ours and grey is somebody else's. A dashed line is an optional extra
rather than something a plain install brings.

.. mermaid::

   flowchart TD
       classDef ours fill:#dbe7ff,stroke:#5a7ab5,color:#111
       classDef third fill:#ededed,stroke:#999999,color:#111

       subgraph apps["Games and demos"]
           glisteel["GLinting Steel"]
           twig["twig-bb"]
           forest["forest demo"]
       end

       subgraph authoring["Authoring"]
           editor["OpenGLContext-editor"]
       end

       subgraph engine["The engine"]
           oglc["OpenGLContext"]
       end

       subgraph libs["Libraries"]
           pyopengl["PyOpenGL"]
           vrml["PyVRML97"]
           omip["omi_physics"]
           omia["omi_audio"]
           ext["opengl_extrusions"]
           ttf["TTFQuery"]
       end

       subgraph base["Underneath"]
           simple["SimpleParse"]
           dispatch["PyDispatcher"]
           numpy["numpy"]
           pillow["Pillow"]
           gltflib["pygltflib"]
           miniaudio["miniaudio"]
       end

       subgraph metal["The machine"]
           driver["The GL driver, and the GPU"]
       end

       glisteel --> editor
       glisteel --> oglc
       twig --> editor
       twig --> oglc
       forest --> oglc
       editor --> oglc
       oglc --> pyopengl
       oglc --> vrml
       oglc --> omip
       oglc --> omia
       oglc --> ext
       oglc --> ttf
       oglc --> numpy
       oglc --> pillow
       oglc --> gltflib
       vrml --> simple
       vrml --> dispatch
       vrml --> numpy
       omip --> numpy
       omia --> numpy
       omia -.-> miniaudio
       ext --> numpy
       pyopengl --> driver

       class glisteel,twig,forest,editor,oglc,pyopengl,vrml,omip,omia,ext,ttf,simple,dispatch ours
       class numpy,pillow,gltflib,miniaudio,driver third

Each of those is released on its own and useful on its own: ``omi_physics``
and ``omi_audio`` are the OMI glTF models in numpy with no renderer in them,
``opengl_extrusions`` sweeps and tessellates geometry for anyone who wants
vertex arrays, and ``PyVRML97`` is the node, field and route model the
scenegraph is built from. What the engine adds is the window, the render
passes and the scenegraph that ties them together.

The OpenGLContext Package (top-level)
-------------------------------------

Within the top-level :py:mod:`OpenGLContext package <OpenGLContext>` are the
objects implementing the :py:mod:`Context <OpenGLContext.context>` interface.
Each supported GUI library defines a derived Context class which overrides
various methods to support the Context API (these derived classes are named
:py:mod:`GLUTContext <OpenGLContext.glutcontext>`,:py:mod:`PygameContext
<OpenGLContext.pygamecontext>`, :py:mod:`wxContext <OpenGLContext.wxcontext>`,
etceteras).  Each supported GUI will also provide a sub-class which uses the
mix in :py:mod:`InteractiveContext <OpenGLContext.interactivecontext>`, which,
through the events package (see below), allows for keyboard and mouse event
processing.  Each GUI library will then provide a module Xtestingcontext.py
(e.g. :py:mod:`gluttestingcontext.py <OpenGLContext.gluttestingcontext>`)
which provides a context class factory function, and a "mainloop" function.
The :py:mod:`testingcontext.py <OpenGLContext.testingcontext>` module then
provides an interface for finding the appropriate testing context for the
specified GUI library.

.. rst-class:: technical

Context classes are registered by calling ``OpenGLContext.plugins.Context``
with a name and the dotted path to the class, which
``OpenGLContext/__init__.py`` does for the in-tree backends. A third party
registers its own the same way, at import time:

.. code-block:: python

   from OpenGLContext.plugins import Context, InteractiveContext

   Context( 'mytoolkit', 'mypackage.context.MyContext' )
   InteractiveContext( 'mytoolkit', 'mypackage.context.MyInteractiveContext' )

.. rst-class:: technical

The registry is a list in the running process, so what puts a third-party
backend on it is the application importing that package — there is no
entry-point scan and no install step beyond having the package importable.
``OPENGLCONTEXT_BACKEND=mytoolkit`` then selects it by the name given here.
Loaders, viewer adapters and scenegraph nodes are registered the same way
through ``plugins.Loader``, ``plugins.Adapter`` (see :doc:`Adding a format
<viewer>`) and ``plugins.Node``.

Which backends are supported
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Six toolkits, in two shapes. Three of them open a window and the scene is
that window; three put a GL view inside an interface built of ordinary
widgets, which is what a tool with menus and panels around the view wants.
The engine is the same either way: every backend can ask for a core profile
or a compatibility one, and the window-level capabilities below are the same
on all of them. ``OPENGLCONTEXT_BACKEND`` names the one to use.

The scene is the window
^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Backend
     - Runs on
     - What it brings
   * - ``glfw``
     - Linux (X11 and Wayland), Windows, macOS
     - What the test suite and the visual-regression captures run against,
       and the one to reach for in core-profile and PBR work. ``pip install
       "OpenGLContext[glfw]"`` carries the library with it.
   * - ``glut``
     - Linux (X11; XWayland under Wayland), Windows, macOS
     - freeglut, through the C library the system provides — ``pip install
       PyOpenGL[glut]`` is what supplies it on Windows. The oldest path, and
       the one the NeHe tutorials are written against. freeglut has no
       Wayland backend of its own.
   * - ``pygame``
     - Linux (X11 and Wayland), Windows, macOS
     - SDL2's window, input and audio, for an application already built on
       that stack. ``pip install "OpenGLContext[pygame]"``.

A view inside an interface
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Backend
     - Runs on
     - What it brings
   * - ``tk``
     - Linux (X11; XWayland under Wayland), Windows, macOS
     - Tkinter, through PyOpenGL's own ``OpenGL.Tk.GLFrame`` widget, so
       nothing outside Python's standard library is imported. Tcl/Tk itself
       is a system package, and several Linux distributions leave it out of a
       default Python install (``apt install python3-tk``).
       ``TkContext(parent=...)`` puts the view in a frame you built.
   * - ``wx``
     - Linux (X11 and Wayland, through GTK3), Windows, macOS
     - wxPython's native widgets, with the view in a ``wx.glcanvas.GLCanvas``
       — wxPython 4 (Phoenix) or newer. GTK3 makes its context through EGL
       rather than GLX, which PyOpenGL works out for itself. See
       ``tests/wx_with_controls.py``.
   * - ``qt``
     - Linux (X11, and Wayland where the Qt build's platform plugin offers a
       drawable GL surface; ``QT_QPA_PLATFORM=xcb`` runs it through XWayland
       otherwise), Windows, macOS
     - Qt 6 through PySide6, from the separate :py:mod:`OpenGLContext_qt
       <OpenGLContext_qt>` distribution, which the engine imports where it is
       installed.

.. rst-class:: technical

The Tk backend draws into ``OpenGL.Tk.GLFrame``, which makes a GL context on
the window Tk hands out — through GLX on X11 and WGL on Windows. A Tk window
has no native handle until it has been mapped, so ``OPENGLCONTEXT_HIDDEN`` is
honoured by withdrawing the window once the context exists: it appears and
goes, rather than never appearing, and rendering and reading back are
unaffected because both happen in the back buffer. A headless machine runs
the X11-only backends under ``xvfb-run``.

No window at all
^^^^^^^^^^^^^^^^

A build machine, a rendering service and a batch job want a context with no
window and no display server behind it. Each platform reaches one through its
own interface, and the engine has a backend for two of the three:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Backend
     - Runs on
     - What it brings
   * - ``egl``
     - Linux, and Android
     - :doc:`eglcontext.EGLContext <offscreen>` takes a GPU through EGL and
       renders to a pbuffer: no display server, no compositor, no session. A
       machine with several EGL devices — a GPU and a CPU rasteriser — is
       asked which it has, and the application picks.
   * - ``wgl``
     - Windows
     - ``OpenGLContext.wglcontext`` makes a pbuffer through WGL. It wants a
       driver offering ``WGL_ARB_pbuffer`` and a window station with a
       desktop, which a service in session 0 has; nothing appears on screen.
   * - —
     - macOS
     - CGL (:py:mod:`OpenGL.CGL`) makes a context with no window, but no
       default framebuffer with it, so there is no backend here yet. A hidden
       window is the way: ``OPENGLCONTEXT_HIDDEN=1`` on any of the backends
       above.

``Context.getOffscreenContextType()`` answers with whichever of them this
machine has, or ``None``, so a program that runs on more than one platform
asks rather than naming a class. :doc:`Rendering offscreen <offscreen>` covers
the device choice, what each backend needs and what to do where there is
neither.

.. _backend-capabilities:

What every backend offers
~~~~~~~~~~~~~~~~~~~~~~~~~

The toolkit an application already uses should choose a window system, not a
subset of the engine, so the window-level capabilities are the same on all of
them. Each is a method on ``Context`` that answers **whether it happened**, so
a caller can tell "this platform will not" from "nobody implemented this" and
offer the user something else.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - Does
     - Where it answers False
   * - ``setPointerCapture(on)``
     - Hides the pointer and reports unbounded motion, which is what mouse-look turns
       from
     - A window system that will not give a client the pointer — Qt's Wayland plugin,
       for one; turning is then limited to the window
   * - ``setFullscreen(on)``
     - Moves a live window to the screen and back, keeping its GL context
     - A machine with no monitor attached, or a session with no window manager to
       honour the request
   * - ``applyVSync()``
     - Waits for the display's refresh, or does not (``ContextDefinition.vsync``)
     - Qt and Pygame, where the interval is part of a surface format settled when the
       context is made: the change is logged and takes effect in the next window.
       GLUT, Tk and wxPython ask the window system's own swap-control extension, and
       answer False where there is none
   * - ``pumpWindowEvents()``
     - Delivers whatever the window system has queued, for a program driving its own
       loop rather than calling ``MainLoop``
     - The offscreen backend, which has no window system to ask
   * - ``releaseWindow()``
     - Lets the window, and the GL objects in it, go — one name, so a caller that
       built a context need not know which backend made it
     - Answers nothing; there is nothing to report about having done it

``context.setVSync(False)`` is the call an application makes to uncap its
frame rate: it writes the field and applies it. That matters more than it
sounds — a forced redraw blocks on a buffer swap nobody is presenting, so a
headless capture that does not uncap draws one frame and then waits for ever —
and reaching for a particular toolkit's own swap-interval call instead does
nothing on any other backend.

A context knows how big it is as soon as it exists: ``getViewPort()`` answers
a width, height pair before a single event has been pumped, so a program that
draws its first frame before entering a loop gets a projection matrix, an
overlay scale and a picking ray of the right size. A window system that
reports the size through a resize callback is asked directly instead, as the
window is made.

Beside those, every backend reports pointer motion to the movement sampler as
it happens (``recordPointerMotion``), supplies key-repeat where the platform
delivers none, and releases every held key when its window loses focus — no
platform sends a key-up for a key that was down when focus went elsewhere, and
without the release the camera keeps moving with nobody touching the keyboard.
The held-key half is ``events.eventhandlermixin.HeldKeyMixin``, shared. See
:doc:`Movement Modes & Navigation <navigation>`.

Each backend's loop has the same shape: the window system's events are pumped,
then the animation hook, then one render for the iteration whatever arrived —
so a burst of input coalesces into a single frame rather than forcing a render
per event — with the phases timed by :doc:`looptrace <hud>` and the telemetry
and stall journals closed as the loop ends. GLUT's is built on
``glutMainLoopEvent``; a GLUT without it keeps the older arrangement, where
the toolkit owns the loop. wxPython's loop is wx's own, and the phases are not
timed there.

An application whose loop is already running keeps it: the view goes in a
widget beside the rest of the interface, and the frames come out of the host's
loop rather than the engine's. That is :doc:`Embedding a view in an
application <embedding>`, which covers what each of Tk, Qt and wx needs and
has a sample program for each.

.. _fullscreen:

Filling the screen
~~~~~~~~~~~~~~~~~~

A game normally wants the whole display and a tool normally does not, so the
program sets it rather than whoever launches it:
``ContextDefinition.fullscreen``, defaulted from ``OPENGLCONTEXT_FULLSCREEN``
and offered on the settings screen under *Interface*.

.. code-block:: python

   from OpenGLContext.contextdefinition import ContextDefinition
   MyGame.ContextMainLoop(definition=ContextDefinition(fullscreen=True))

The window opens at the display's *current* resolution, so nothing switches
video modes: a mode change is slow and rearranges the icons on every other
desktop that display is showing. A program that wants a different rendering
resolution says so with the definition's ``size``.

``OPENGLCONTEXT_HIDDEN`` outranks it. A window that is not meant to appear
cannot fill the screen -- the platforms take "fill the screen" as an
instruction to map it -- so a capture subprocess that honoured both would put
itself over the display of whoever started the run.

``context.setFullscreen(True/False)`` moves a window that already exists,
keeping the GL context and everything loaded into it, and answers whether the
backend could. Every backend can. Applying the settings screen's toggle calls
it, so a player can leave a full-screen game without restarting.

Rendering runs through the **passes** package described in :ref:`Rendering
Passes <passes>` below: a single "flat" pass that observes the scenegraph's
structure and draws it in a fixed sequence (background, opaque, transparent,
selection, overlay). See :doc:`Flat Rendering <flat>` for the overview.

.. rst-class:: technical

Earlier versions instead gave each Context a list of RenderMode objects
(Timer, Opaque, Transparent, Select) driven by a visitor-pattern traversal.
That system was removed once the flat pass replaced it;
``Context.renderPasses`` now names the flat-pass dispatcher.

.. _core-profile:

OpenGL Core Profile Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A context is core profile unless something asks otherwise. Core profile uses
GLSL shaders rather than the fixed-function pipeline, which is what makes it
work on OpenGL 3.3+ contexts and on platforms such as macOS that offer nothing
else — and it is what the engine's own geometry draws through, since
``PBRMesh``, and so the glTF loader and every generator built on it, is
shader-only. Every backend (``glfw``, ``glut``, ``pygame``, ``wx``, ``qt``)
creates one.

The compatibility profile is fully supported, and is what a program asks for
when it means to draw with the older pipeline.

Saying which profile your program needs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``OPENGLCONTEXT_PROFILE=compatibility`` settles the profile for a whole run,
which is what a CI job or a one-off comparison wants. A program that *needs* a
particular profile says so on its Context class instead, so the requirement
travels with the code and nobody has to know to set a variable before running
it:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'   # this program draws with the fixed-function pipeline

Use this for anything calling ``glBegin``, ``glVertexPointer``,
``glMaterial``, ``glLight``, the matrix stack, display lists, or GLSL's
``gl_ModelViewProjectionMatrix`` and friends: none of them exist in a core
context.

``profile`` settles the OpenGL version to go with it, and is applied over any
``contextDefinition`` the class declares, so a subclass can name its profile
and still inherit the size, buffers and rendering features its base asked for.
Where more than the profile is at stake, declare the whole definition:

.. code-block:: python

   from OpenGLContext import contextdefinition

   class MyContext( BaseContext ):
       contextDefinition = contextdefinition.ContextDefinition(
           profile = 'compatibility',
           size = (800, 600),
           multisampleSamples = 4,
       )

Either declaration is read before the window is created, on every backend --
the profile, the version and the buffer formats are all window-creation
parameters, so there is no configuring them afterwards. A definition passed to
the constructor outranks both. Each context gets its own copy of what the
class declared, since a context writes its own size back to its definition as
the window is resized.

wxPython, GTK3 and EGL
^^^^^^^^^^^^^^^^^^^^^^

wxPython on GTK3 makes its GL context through EGL rather than GLX, and on X11
it may be either. Nothing has to be configured for that: PyOpenGL's Linux
platform loads both interfaces and probes for the live context, so the calls
are routed to whichever API owns the context the toolkit made
(:py:mod:`OpenGL.platform.linux`).

Qt/PySide and the platform plugin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Qt backend lives in the separate **OpenGLContext-qt** distribution and
registers itself under the name ``qt``, so installing it is all that is needed
for ``OPENGLCONTEXT_BACKEND=qt`` to select it. It is built on ``QWindow`` with
a ``QOpenGLContext`` of its own rather than on ``QOpenGLWidget``, so
framebuffer 0 is the screen and every render path -- the bloom composite, the
selection buffer's blit, the back-buffer read behind a screenshot -- behaves
as it does under GLUT and GLFW. Both profiles are supported, and every
``ContextDefinition`` field that describes the window is mapped to the Qt
surface format.

.. code-block:: bash

   OPENGLCONTEXT_BACKEND=qt python your_script.py

**Which Qt platform plugin you get matters.** Qt asks the platform integration
for the context, and some of them hand back one that is current on no drawable
surface at all: every GL call succeeds, nothing raises, and every frame is
black. The backend detects that at start-up and says so, naming the plugin.
Selecting another one usually fixes it:

.. code-block:: bash

   QT_QPA_PLATFORM=xcb OPENGLCONTEXT_BACKEND=qt python your_script.py

Two limits are worth knowing. ``accumulationBuffer`` does not exist in Qt 6
and is reported rather than silently dropped, and ``OPENGLCONTEXT_HIDDEN`` is
not supported -- Qt's offscreen surfaces have no default framebuffer on the
common EGL platforms, so headless capture should use the ``glfw`` backend.

.. _context-resources:

When a context goes away
~~~~~~~~~~~~~~~~~~~~~~~~

A GL object is a *name*, and it means something only in the context that
issued it. The engine's caches of them — the render pass, the VRML97 shader
programs, the text renderers, the teapot's vertex arrays — are therefore keyed
by the GL context as well as by whatever else identifies the entry.

Keying alone is not enough. The key is the context's handle, the handle is an
address, and a driver hands the same address out again for the next context: a
cache that keys on it and is never told the old context died answers the new
one with the dead one's names. PyOpenGL's own dispatch tables are keyed the
same way and have the same exposure — a recycled handle arrives holding the
dead context's resolved function pointers.

So a backend says both things, and ``Context`` states the contract once so
that a backend inherits it rather than having to know it:

.. code-block:: python

   self.bindContextResources( handle )      # in setCurrent
   self.releaseContextResources( handle )   # as the window is destroyed

``releaseContextResources`` tells the engine's caches, so they can *delete*
what they hold rather than merely forget it, and retires PyOpenGL's dispatch
table for that context. It has to be called **with the context still current
and its window still whole**, which is the only moment either of those is
possible. Every backend does: ``glfw``, ``glut``, ``pygame``, ``wx``, ``egl``
and ``qt``.

Application code that caches GL objects of its own registers to hear the same
announcement. The callback takes no arguments and runs with the dying context
current, so it may delete GL objects as well as forget them, and
``contextresources.context_key()`` tells it which context that is:

.. code-block:: python

   from OpenGLContext import contextresources

   @contextresources.on_context_lost
   def drop_my_cached_objects():
       ...

Registering the same callable twice registers it once, and one cache raising
does not stop the rest from being told. The registry holds a strong reference
for the life of the process, which is right for a module-level cache
registering at import; a callback bound to something shorter-lived hands
itself back with ``contextresources.forget_context_lost( callback )``.

A cache holds **one entry per context**, not one entry. Two windows draw
alternately, so a single slot belongs to whichever drew last: every frame of
every context would miss, rebuild what the other displaced, and abandon the
displaced entry's GL objects in a context that is still alive and can no
longer be reached to delete them. ``renderpass._passes``,
``shaderpass._shader_programs``, ``Teapot._buffers`` and
``shadertext._renderers`` are all mappings for that reason.

The test fixtures announce it too, which is what a suite needs: several
hundred windows open and close in one process, and that is precisely the
setting in which a driver reuses an address.

The :py:mod:`ViewPlatform <OpenGLContext.move.viewplatform>` and
:py:mod:`ViewPlatformMixin <OpenGLContext.move.viewplatformmixin>` classes
provide a simple navigation interface using the keyboard arrow keys (walk/fly)
and the ALT-arrow keys (pan/slide), plus the three examine gestures —
right-drag to orbit, middle-drag to pan, wheel to move toward or away. Those
are :py:mod:`TurntableOrbit <OpenGLContext.move.orbit>` driven by
:py:mod:`ExamineManager <OpenGLContext.move.examinemanager>`; see
:ref:`Examining <examine>`.

An application wanting more than that declares **movement modes** on its
``ContextDefinition``: walking, flying, swimming and first-person mouse-look
as scenegraph nodes, each with its own speeds and key bindings, driven from
sampled input rather than from events so several inputs act in one frame. See
:doc:`Movement Modes & Navigation <navigation>`. A context that declares none
keeps the older navigation untouched.

An application that needs a screen over the running world — rendering
settings, key rebinding, a licence notice, a console — mixes in
``ui.overlay.OverlayMixin``, which adds a stack of panels, routes input to the
topmost one and draws it after the frame. While a modal panel is up the world
hears nothing at all, including the input sampler — and a press the overlay
took takes its release with it, so the keystroke that closes the last panel
does not also reach the world. Every switchable rendering feature is a field
on the ``ContextDefinition``, read through ``renderoptions``, so the settings
screen is generated from those fields rather than hand-written. The window's
height picks the font size and everything else is measured against it, so the
interface is the same size in the eye at 1080p and at 4K. See :doc:`Overlay UI
<overlayui>`.

Finally, at the top-level, we have a number of utility functions and modules,
including drawcube (a testing function), :py:mod:`Quaternion
<OpenGLContext.quaternion>`,:py:mod:`utilities
<OpenGLContext.utilities>`,:py:mod:`vector utilities
<OpenGLContext.vectorutilities>`, and :py:mod:`triangle utilities
<OpenGLContext.triangleutilities>`.

.. _passes:

Rendering Passes
----------------

The **passes** package holds the current rendering system. A single
``FlatPass`` observes the scenegraph and, each frame, draws it in a fixed
sequence -- background, opaque, transmissive, transparent, selection and
overlay -- rather than traversing it once per rendering mode. The base class
(``passes/_flat.py``) carries two code paths, chosen by one flag:

- ``flatcompat.py`` -- the compatibility-profile pass, using the fixed-function
  pipeline (``glLight*``, ``glMaterial*``).

- ``flatcore.py`` -- the core-profile pass, using GLSL shaders. See
  :doc:`Core-Profile Rendering <renderpasses>`.

Shader programs are managed by ``VRML97ShaderProgram``
(``passes/shaderpass.py``), which compiles the lit, unlit, vertex-colour,
point, line and shadow-depth programs and assembles them from the GLSL sources
in the ``shaders/`` directory (the ``.vert``/``.frag`` files plus shared
``_*.glsl`` include files, spliced together at compile time). Built on top of
this are:

- ``pbrpass.py`` -- the physically based (metallic/roughness) renderer, a
  Cook-Torrance uber-shader. See :doc:`Physically Based Rendering <pbr>` and the
  :doc:`shader walkthrough <ubershader>`.

- ``ibl.py`` -- image-based (environment) lighting: the precomputed
  irradiance/prefilter/BRDF-LUT probe.

- ``shadowmap.py``, ``shadowmixin.py``, ``shadowcaps.py``, ``shadowmath.py`` --
  the shared shadow subsystem used by both the VRML97 and PBR lit shaders. See
  :doc:`Shadows <shadows>`.

- ``transmission.py`` -- the backdrop capture for glass
  (``KHR_materials_transmission``).

- ``selection.py`` -- colour/object-id picking.

- ``renderpass.py`` -- picks which ``FlatPass`` subclass renders a context
  (profile + renderer) and caches it across frames; ``viewpointbinding.py``
  binds the scene's active Viewpoint into the view platform for the core-profile
  path.

Loaders and Command-Line Tools
------------------------------

The **loaders** package reads external model formats into the scenegraph:

- VRML97 / VRML files, parsed with SimpleParse (see :doc:`Using VRML97
  <vrml97>`).

- glTF 2.0 and binary GLB, via pygltflib, mapped onto PBR materials (see
  :doc:`Loading glTF <gltf>`).

- Wavefront OBJ.

.. _background-loading:

Loading without stopping the frame
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Setting the ``url`` of an ``ImageTexture``, an ``Inline``, a ``GLSLShader`` or
an ``HDRBackground`` returns at once and the fetch, the decode and the parse
run on ``OpenGLContext.loaders.background``'s pool. The pool holds
``background.WORKERS`` daemon threads (four), started as work arrives, so a
scene naming several hundred textures costs four threads rather than several
hundred. A load that raises is logged with the url it was given and the worker
carries on.

A test or a tool that wants the scene complete before it looks at it waits:

.. code-block:: python

   from OpenGLContext.loaders import background

   texture = ImageTexture(url=['brick.png'])
   background.wait_for_idle(20)        # True once every load has finished
   print(background.pending())         # how many are still going

``wait_for_idle`` answers ``False`` if the timeout expires first, and waits
for work submitted while it is waiting — which is what a scene whose first
file names the rest of them needs. A caller wanting loads of its own that do
not queue behind the scenegraph's builds its own ``background.LoadPool`` and
calls ``shutdown()`` when it is done with it; the engine's own pool lives as
long as the process.

.. rst-class:: technical

A load submitted with a ``prepare`` callable has it run **on the submitting
thread**, and that is where each of the url fields makes the imports its load
will need — PIL's per-format plugin modules, the loader, the format handlers,
the lighting probe. A module being imported for the first time is imported
under CPython's import lock, which is taken with the GIL released and which no
Python signal handler can interrupt: a thread waiting for it answers to no
``SIGTERM``, no ``KeyboardInterrupt`` and no test runner's timeout. Keeping
first-use imports on the thread that asked for the load keeps them ordinary,
interruptible work, and raises an ``ImportError`` where a caller can see it. A
load of your own submitted through ``background.load_in_background`` should
pass a ``prepare`` for the same reason.

The **viewer** package is the reusable viewer itself — loading a scene without
freezing the window, default lighting, auto-framing, cameras and animations,
the caption, screenshots, a library of samples to open, and rendering one
settled frame to a file. An application embeds
``viewer.sceneviewer.ViewerContext`` and configures it with a
``ViewerOptions``, which is the same object the command line fills in (see
:ref:`Embedding the viewer <viewer-embedding>`). Its parts — ``adapters``,
``asyncscene``, ``framing``, ``environment``, ``caption``, ``capture``,
``library``, ``menu`` — are usable individually by a context that is not a
viewer.

What format a source is in is decided by an **adapter** registered under
``plugins.Adapter``, alongside the loader, context and node registries, so the
dispatch is data rather than a chain of tests and a third party adds a format
without touching the viewer (:ref:`Adding a format <adapters>`).

The **bin** package provides console commands, registered as scripts when the
package is installed: ``oglc-view`` (:doc:`the viewer <viewer>` plus a command
line, for every format), ``oglc-terrain``, ``oglc-gltf-demo``,
``oglc-gltf-regression``, ``oglc-ui-demo``, ``oglc-character-sheet``,
``oglc-test`` and ``oglc-lorentz``. ``oglc-gltf``, ``oglc-vrml`` and
``oglc-tiles`` are deprecated aliases for ``oglc-view``.

The **packaging** package is for shipping an application built on the engine
to somebody who has no Python — a frozen bundle, or a native package holding
its own interpreter. It is the engine's answers to what neither can work out
alone: which of its modules are reached by name rather than by import (the
PyInstaller hooks in ``__pyinstaller``, which PyInstaller finds by entry
point), which windowing toolkits an application is not using, and which
libraries it asks the operating system for. It carries one console command,
``oglc-deb``. Nothing in it is imported at run time and nothing in it draws
(see :doc:`Packaging an application <packaging>`).

Scenegraph Rendering
--------------------

The :py:mod:`scenegraph <OpenGLContext.scenegraph>` and
:py:mod:`scenegraph.text <OpenGLContext.scenegraph.text>` packages provide a
set of Python classes which render certain common types of geometry,
materials, textures and grouping nodes (modeled loosely after VRML 97 nodes).
This allows you to create "retained mode" scenes for rendering in your
contexts (note that these classes are largely divorced from the internals of
the context). You'll find :py:mod:`Transform
<OpenGLContext.scenegraph.transform>` (including integer "names" reported
during selection), :py:mod:`Shape
<OpenGLContext.scenegraph.shape>`,:py:mod:`Material
<OpenGLContext.scenegraph.material>`,:py:mod:`ImageTexture
<OpenGLContext.scenegraph.imagetexture>`, and :py:mod:`Light
<OpenGLContext.scenegraph.light>` nodes which are similar to their VRML 97
namesakes.  The :py:mod:`ArrayGeometry
<OpenGLContext.scenegraph.arraygeometry>` class handles the rendering of all
of :py:mod:`IndexedFaceSet
<OpenGLContext.scenegraph.indexedfaceset>`,:py:mod:`IndexedLineSet
<OpenGLContext.scenegraph.indexedlineset>` and :py:mod:`PointSet
<OpenGLContext.scenegraph.pointset>`, with the modules of those names simply
instantiating ArrayGeometry instances with the appropriate parameters.  The
text package provides basic text rendering in 3D or 2D forms using TTFQuery or
one of the GUI library engines.

Alongside the VRML97-style nodes, the scenegraph includes ``PBRMaterial`` and
a ``PBRMesh`` geometry (``scenegraph/pbrmaterial.py``), the metallic/roughness
material and mesh produced by the :doc:`glTF loader <gltf>` and rendered by
the :doc:`PBR pass <pbr>`. Legacy ``Material`` nodes are converted to the same
model when the PBR renderer is active, so both kinds of content share one
pipeline.

Events and Selection
--------------------

The :py:mod:`events <OpenGLContext.events>` package implements a simple cross
GUI-library event generation and handling system.  Each GUI library defines
subclasses of the major event and event handler classes.  These subclasses
translate from native events to OpenGLContext events. The event handler
classes (which are mixin classes) are then included in the GUI library's
Context class to provide the event handling interfaces.

Mouse events reach the application through the pick queue: a backend adds one
with ``Context.addPickEvent`` and the selection pass dispatches it once it has
resolved what the pick point is over. The queue is a mapping keyed by
``Event.getPickKey``, so events that are the same news twice within one frame
cost one dispatch. **The wheel is the exception**: a notch arrives as a press
and release of button 3 or 4 (``mouseevents.WHEEL_UP`` and ``WHEEL_DOWN``, the
X11 numbering), it is an increment rather than a state, and its pick key is
distinct per notch so none is dropped. GLFW reports scrolling on a callback of
its own in offsets and translates to those buttons; see :ref:`the overlay UI
documentation <wheel>`.

.. _structure-bindings:

Which handler holds a key
~~~~~~~~~~~~~~~~~~~~~~~~~

One, and it is the last registered: a key is identified by ``(name, state,
modifiers)`` and registering a second handler for the same triple replaces the
first. So the two places a context binds keys run in a deliberate order, and
``Context.__init__`` runs them that way:

#. ``setupDefaultEventCallbacks`` — what a key does when nobody has said
   otherwise: Escape, the arrow-key navigation, right-drag to examine, PageDown
   to cycle viewpoints, ``Alt+F`` for the developer overlay, and :ref:`F2 or
   Alt+S <screenshots>` for a screenshot.

#. ``setupCallbacks`` — what a key does in *this* context. It lands on top, so an
   application that wants a key the framework also binds simply binds it.

Modifiers are a three-tuple in the order ``(shift, control, alt)``. A binding
that asks for the wrong slot is not an error — it registers, and the key
silently never fires.

Handlers are held by **weak** reference, so the caller must keep the callback
alive; a bound method of a live object is the normal choice, and one with no
other reference is collected the moment the registration returns, leaving the
key silently dead.

.. _present:

Presenting a frame, and reading it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A render pass finishes a frame by calling ``Context.presentFrame``, which is
the last moment that frame can be read: ``SwapBuffers`` hands the back buffer
to the driver, which recycles it, so a read afterwards returns an older frame.
Anything that has to see what the viewer saw — a screenshot, a :doc:`still
capture <testing>`, a :doc:`recording <recording>` — reads it from there.

.. code-block:: python

   def presentFrame(self):
       self.tickRecording()              # before the swap: this is the frame
       return super().presentFrame()

``SwapBuffers`` is one thing: the method each GUI backend implements to put
the buffer up. Override ``presentFrame`` for work that belongs to the frame,
and ``SwapBuffers`` only when writing a backend.

.. _screenshots:

The screenshot key
~~~~~~~~~~~~~~~~~~

Every context binds ``F2`` (and ``Alt+S``) to ``requestScreenshot`` without
being asked, so a program built on OpenGLContext has a screenshot key with no
configuration. The key *asks*: it raises a flag and requests a redraw, and the
picture is taken from ``presentFrame``, for the reason above. The redraw is
what makes the key work on a still scene, where there would otherwise be no
next frame.

The file goes to the user’s picture folder — ``~/Pictures`` or whatever the
desktop, the Finder or the Windows shell says that is — named for the window
title: ``GLinting-Steel-0001.png``. The count rises to the first name nothing
is using, so pressing the key twice keeps both shots. A machine with no home
directory writes to the working directory instead.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Attribute
     - What it does
   * - ``screenshotKey``
     - The key to bind, ``'<F2>'`` by default. ``''`` binds none, which is how an
       application keeps F2 for something of its own.
   * - ``screenshotTemplate``
     - How the file is named. ``%(name)s`` is the window title, ``%(count)04i`` the
       number that rises until the name is free.
   * - ``screenshotDirectory()``
     - Where a screenshot with no path of its own is written. Override it to file
       them somewhere else.
   * - ``OnSaveImage()``
     - Takes the picture now, from whatever is in the back buffer. Call it from
       ``presentFrame``, or pass ``template=`` to write a named file.
