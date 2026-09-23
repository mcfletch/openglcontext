OpenGLContext Structural Overview
=================================

.. rst-class:: introduction

OpenGLContext is a retained-mode scenegraph engine for games and other 3D
applications. It is built from a number of open source packages, most of them
maintained alongside it. The demos and games at the top of the diagram keep
their reusable code in the engine, so each one is a small application on top
of it. Parts that are useful outside OpenGLContext, such as ``omi_audio``,
``omi_physics``, ``opengl_extrusions`` and ``pyopengl-video``, are separate
packages.

.. mermaid::

   block-beta
       columns 8

       glisteel["GLinting Steel"]:2
       twig["Twitchy GLitchy Bang Bang"]:3
       forest["OpenGLContext Forest Demo"]:3

       editor["OpenGLContext-editor"]:5
       space:3

       oglc["OpenGLContext"]:8

       video["pyopengl-video"]:1
       space:7

       pyopengl["PyOpenGL"]:1
       omip["omi_physics"]:1
       omia["omi_audio"]:1
       ext["opengl_extrusions"]:1
       ttf["TTFQuery"]:1
       vrml["PyVRML97"]:2
       gltflib["pygltflib"]:1

       space:2
       mini["miniaudio"]:1
       space:1
       fonttools["fontTools"]:1
       simple["SimpleParse"]:1
       dispatch["PyDispatcher"]:1
       space:1

       numpy["numpy"]:7
       space:1

       classDef ours fill:#dbe7ff,stroke:#5a7ab5,color:#111
       classDef third fill:#ededed,stroke:#999999,color:#111

       class glisteel,twig,forest,editor,oglc,video,pyopengl,vrml,omip,omia,ext,ttf,simple,dispatch ours
       class mini,fonttools,gltflib,numpy third

.. mermaid::

   block-beta
       columns 2
       legendfirst["Blue: first-party packages"]
       legendthird["Grey: third-party packages"]

       classDef ours fill:#dbe7ff,stroke:#5a7ab5,color:#111
       classDef third fill:#ededed,stroke:#999999,color:#111

       class legendfirst ours
       class legendthird third

The packages it is built on
---------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Package
     - What it provides
   * - `PyOpenGL <https://mcfletch.github.io/pyopengl/>`__
     - The OpenGL bindings: every entry point of GL, GLU, GLUT, EGL, WGL and
       GLX, the extensions, and the array handling that passes Python data to
       the driver.
   * - `pyopengl-video <https://github.com/mcfletch/pyopengl-video>`__
     - Encodes the colour buffer to H.264 on the GPU's own encoder, without
       copying the frame off the card. An extra: ``OpenGLContext[video]``.
   * - `PyVRML97 <https://github.com/mcfletch/pyvrml97>`__
     - The node, field, route and prototype model the scenegraph is built
       from, and the VRML97 parser that fills it.
   * - `pygltflib <https://gitlab.com/dodgyville/pygltflib>`__
     - Reads and writes glTF 2.0 and GLB, as the typed records the
       specification describes.
   * - `omi_physics <https://github.com/mcfletch/omi_physics>`__
     - Rigid bodies, colliders, joints and gravity zones on the OMI glTF
       physics model, computed in NumPy.
   * - `omi_audio <https://github.com/mcfletch/omi_audio>`__
     - Spatial audio on glTF's ``KHR_audio_emitter`` model: the gain curves,
       the voice pool and the block mixing, in NumPy.
   * - `opengl_extrusions <https://github.com/mcfletch/opengl_extrusions>`__
     - Sweeping, lathing and tubing, and the constrained Delaunay
       tessellator that fills an outline with triangles.
   * - `TTFQuery <https://github.com/mcfletch/ttfquery>`__
     - Finds the fonts installed on the machine and reads their glyph
       outlines.
   * - `SimpleParse <https://mcfletch.github.io/simpleparse/>`__
     - The parser generator the VRML97 grammar is written in.
   * - `PyDispatcher <https://github.com/mcfletch/pydispatcher>`__
     - Signal dispatch. Field changes are sent through it, so code can observe
       changes to the scenegraph.
   * - `fontTools <https://github.com/fonttools/fonttools>`__
     - Reads the tables of a TrueType or OpenType file, for TTFQuery.
   * - `miniaudio <https://github.com/irmen/pyminiaudio>`__
     - Decodes audio files and plays sound through the sound card. An extra:
       ``omi_audio[playback]``. Without it the mixer runs but plays nothing.
   * - `numpy <https://numpy.org/>`__
     - The arrays all of the above compute with, and the memory passed to the
       driver.

The packages inside OpenGLContext
---------------------------------

.. mermaid::

   block-beta
       columns 8

       bin["bin"]:2
       viewer["viewer"]:3
       demos["demos"]:3

       ui["ui"]:2
       edit["edit"]:2
       testing["testing"]:1
       telemetry["telemetry"]:1
       debug["debug"]:1
       packaging["packaging"]:1

       passes["passes"]:2
       physics["physics"]:1
       nav["nav"]:1
       character["character"]:1
       move["move"]:1
       audio["audio"]:1
       video["video"]:1

       scenegraph["scenegraph"]:3
       loaders["loaders"]:2
       shaders["shaders · resources"]:2
       contentpacks["contentpacks"]:1

       context["context"]:3
       events["events"]:2
       resources["contextresources"]:3

Each layer uses the layers below it. At the bottom are the window and its
events. Above them is the scenegraph, which the render passes draw and the
simulation packages update.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Package
     - What it does
     - Described in
   * - ``bin``
     - The console commands: ``oglc-view``, ``oglc-terrain``,
       ``oglc-gltf-demo`` and the rest.
     - :ref:`Console commands <commands-list>`
   * - ``viewer``
     - The embeddable viewer the commands are built on, and the per-format
       adapters it selects between.
     - :doc:`The viewer <viewer>`
   * - ``demos``
     - A GL view inside a Tk or wx application, for a tool with an interface
       around the scene.
     - :doc:`Embedding <embedding>`
   * - ``ui``
     - The overlay: panels, widgets, a generated settings screen, the
       key-binding editor, the console and the in-world HUD.
     - :doc:`Overlay UI <overlayui>`, :doc:`HUD <hud>`
   * - ``edit``
     - The editor toolkit: tool modes, plan and orbit views, the tri-axis
       handle, and a NURBS node's control points.
     - :doc:`Editing <editing>`
   * - ``testing``
     - The machinery a test suite imports: a hidden GL context, the pytest
       fixtures that provide one, capture and comparison.
     - :doc:`Testing what you draw <testing>`
   * - ``telemetry``
     - Records a whole session (input, frame times, exceptions, marks) to one
       file, to read back or replay.
     - :doc:`Session telemetry <telemetry>`
   * - ``debug``
     - Developer aids: buffer dumps, GL state, leak counts.
     - —
   * - ``packaging``
     - Shipping an application: a PyInstaller bundle, or a Debian package
       carrying its own interpreter.
     - :doc:`Packaging <packaging>`
   * - ``passes``
     - The render passes: the flat core and compatibility passes, the PBR
       uber-shader, shadows, image-based lighting and instancing.
     - :ref:`Rendering passes <passes>`
   * - ``physics``
     - Rigid bodies, colliders, gravity zones, triggers and the character
       controller, on ``omi_physics``.
     - :doc:`Physics <physics>`
   * - ``nav``
     - The navigation mesh generated from the collision mesh, and routes
       pulled taut through its portals.
     - :doc:`Navigation meshes <navmesh>`
   * - ``character``
     - Rigged characters: the rig, the clips, the mixer, attachments and
       crowds.
     - :doc:`Rigged characters <characters>`
   * - ``move``
     - The camera and the movement modes (examine, fly, walk, swim and
       mouse-look), and the walking model under them.
     - :doc:`Movement <navigation>`
   * - ``audio``
     - The scenegraph's audio nodes and the per-context engine that plays
       them, on ``omi_audio``.
     - :doc:`Spatial audio <audio>`
   * - ``video``
     - H.264 capture of what a context drew, through ``pyopengl-video``.
     - :doc:`Recording <recording>`
   * - ``scenegraph``
     - Every node type: shapes, materials, lights, text, NURBS, extrusions,
       terrain, water, roads, vegetation and the PBR mesh.
     - :ref:`Scenegraph rendering <scenegraph-rendering>`
   * - ``loaders``
     - File formats into the scenegraph: glTF and GLB, VRML97, OBJ and
       streamed 3D Tiles.
     - :ref:`Loaders <structure-loaders>`
   * - ``shaders``, ``resources``
     - The GLSL sources the passes compile, and the icons, font atlases and
       shader text stored as generated modules.
     - :doc:`GLSL in OpenGLContext <glslversions>`
   * - ``contentpacks``
     - Data an application downloads instead of shipping: the registry, the
       store, safe extraction and the polled download.
     - :doc:`Content packs <contentpacks>`
   * - ``context``
     - The window, the main loop, the profile and the context definition,
       with one module per backend.
     - :ref:`The top-level package <top-level>`
   * - ``events``
     - One keyboard, mouse and window event model across the backends, and
       the dispatch that carries a change through the scenegraph.
     - :ref:`Events and selection <events-and-selection>`
   * - ``contextresources``
     - The caches that release a GL context's objects when the context is
       destroyed.
     - :ref:`Context resources <context-resources>`

.. _top-level:

The OpenGLContext Package (top-level)
-------------------------------------

The top-level :py:mod:`OpenGLContext package <OpenGLContext>` holds the
:py:mod:`Context <OpenGLContext.context>` class and one subclass per GUI
library, which implements the Context API for that library:
:py:mod:`GLUTContext <OpenGLContext.glutcontext>`, :py:mod:`PygameContext
<OpenGLContext.pygamecontext>`, :py:mod:`wxContext <OpenGLContext.wxcontext>`
and so on.

Each GUI library also provides:

- an interactive context, which adds the :py:mod:`InteractiveContext
  <OpenGLContext.interactivecontext>` mix-in for keyboard and mouse events
  (see :ref:`Events and selection <events-and-selection>`);

- a testing-context module, such as :py:mod:`gluttestingcontext
  <OpenGLContext.gluttestingcontext>`, with a context class factory function
  and a ``mainloop`` function.

:py:mod:`testingcontext <OpenGLContext.testingcontext>` finds the testing
context for the selected GUI library.

.. rst-class:: technical

Context classes are registered by calling ``OpenGLContext.plugins.Context``
with a name and the dotted path to the class. ``OpenGLContext/__init__.py``
does this for the built-in backends. A third party registers its own backend
the same way, at import time:

.. code-block:: python

   from OpenGLContext.plugins import Context, InteractiveContext

   Context( 'mytoolkit', 'mypackage.context.MyContext' )
   InteractiveContext( 'mytoolkit', 'mypackage.context.MyInteractiveContext' )

.. rst-class:: technical

The registry is a list in the running process. A third-party backend is added
to it when the application imports that package; there is no entry-point scan
and no install step beyond making the package importable.
``OPENGLCONTEXT_BACKEND=mytoolkit`` then selects it by the registered name.
Loaders, viewer adapters and scenegraph nodes are registered the same way,
through ``plugins.Loader``, ``plugins.Adapter`` (see :ref:`Adding a format
<adapters>`) and ``plugins.Node``.

.. _backends:

Which backends are supported
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

OpenGLContext supports six GUI toolkits. With three of them the scene fills
the window. The other three put a GL view inside an interface built from
ordinary widgets, for a tool with menus and panels around the view. Every
backend can create a core-profile or a compatibility-profile context, and
every backend provides the :ref:`window-level methods <backend-capabilities>`
listed below. Set ``OPENGLCONTEXT_BACKEND`` to choose one (see
:doc:`Environment variables <environment>`).

The scene fills the window
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Backend
     - Runs on
     - Notes
   * - ``glfw``
     - Linux (X11 and Wayland), Windows, macOS
     - The test suite and the visual-regression captures run on it. Use it
       for core-profile and PBR work. ``pip install "OpenGLContext[glfw]"``
       installs the library.
   * - ``glut``
     - Linux (X11; XWayland under Wayland), Windows, macOS
     - freeglut, through the C library the system provides. On Windows,
       ``pip install PyOpenGL[glut]`` supplies it. The NeHe tutorials are
       written against it. freeglut has no Wayland backend of its own.
   * - ``pygame``
     - Linux (X11 and Wayland), Windows, macOS
     - SDL2's window, input and audio, for an application already built on
       Pygame. ``pip install "OpenGLContext[pygame]"``.

A view inside an interface
^^^^^^^^^^^^^^^^^^^^^^^^^^

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Backend
     - Runs on
     - Notes
   * - ``tk``
     - Linux (X11; XWayland under Wayland), Windows, macOS
     - Tkinter, through PyOpenGL's own ``OpenGL.Tk.GLFrame`` widget, so it
       imports nothing outside Python's standard library. Tcl/Tk itself is a
       system package, and several Linux distributions leave it out of a
       default Python install (``apt install python3-tk``).
       ``TkContext(parent=...)`` puts the view in a frame you built.
   * - ``wx``
     - Linux (X11 and Wayland, through GTK3), Windows, macOS
     - wxPython 4 (Phoenix) or newer, with the view in a
       ``wx.glcanvas.GLCanvas``. See ``tests/wx_with_controls.py`` and
       :ref:`the note on GTK3 <wx-gtk3>`.
   * - ``qt``
     - Linux (X11, and Wayland where the Qt build's platform plugin provides a
       drawable GL surface; otherwise ``QT_QPA_PLATFORM=xcb`` runs it through
       XWayland), Windows, macOS
     - Qt 6 through PySide6, from the separate :py:mod:`OpenGLContext_qt
       <OpenGLContext_qt>` distribution. The engine imports it when it is
       installed. See :ref:`the notes on Qt <qt-backend>`.

.. rst-class:: technical

The Tk backend draws into ``OpenGL.Tk.GLFrame``, which creates a GL context on
the window Tk provides, through GLX on X11 and WGL on Windows. A Tk window has
no native handle until it is mapped, so the backend handles
``OPENGLCONTEXT_HIDDEN`` by withdrawing the window once the context exists.
The window appears briefly and then goes. Rendering and reading back are not
affected, because both use the back buffer. On a headless machine, run the
X11-only backends under ``xvfb-run``.

.. _wx-gtk3:

wxPython, GTK3 and EGL
^^^^^^^^^^^^^^^^^^^^^^

wxPython on GTK3 creates its GL context through EGL rather than GLX, and on
X11 it may use either. No configuration is needed. PyOpenGL's Linux platform
loads both interfaces and checks which one owns the current context, then
routes calls to that API (:py:mod:`OpenGL.platform.linux`). Do not set
``PYOPENGL_PLATFORM`` for wxPython.

.. _qt-backend:

Qt/PySide and the platform plugin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The Qt backend is in the separate **OpenGLContext-qt** distribution. It
registers itself under the name ``qt``, so once it is installed,
``OPENGLCONTEXT_BACKEND=qt`` selects it. It uses ``QWindow`` with its own
``QOpenGLContext`` rather than ``QOpenGLWidget``. Framebuffer 0 is therefore
the screen, and every render path (the bloom composite, the selection buffer's
blit, the back-buffer read for a screenshot) behaves as it does under GLUT and
GLFW. Both profiles are supported, and every ``ContextDefinition`` field that
describes the window is mapped to the Qt surface format.

.. code-block:: bash

   OPENGLCONTEXT_BACKEND=qt python your_script.py

Some Qt platform plugins return a context that is current on no drawable
surface. Every GL call then succeeds without error, and every frame is black.
The backend detects this at start-up and logs a message naming the plugin.
Selecting another plugin usually fixes it:

.. code-block:: bash

   QT_QPA_PLATFORM=xcb OPENGLCONTEXT_BACKEND=qt python your_script.py

Limits of the Qt backend:

- ``accumulationBuffer`` does not exist in Qt 6. The backend reports it
  instead of ignoring it.

- ``OPENGLCONTEXT_HIDDEN`` is not supported. Qt's offscreen surfaces have no
  default framebuffer on the common EGL platforms, so use the ``glfw`` backend
  for headless capture.

No window at all
^^^^^^^^^^^^^^^^

A build machine, a rendering service or a batch job may need a context with no
window and no display server. Each platform provides this through its own
interface, and OpenGLContext has backends for two of them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Backend
     - Runs on
     - Notes
   * - ``egl``
     - Linux, and Android
     - :doc:`eglcontext.EGLContext <offscreen>` opens a GPU through EGL and
       renders to a pbuffer, with no display server, compositor or session.
       On a machine with several EGL devices, such as a GPU and a CPU
       rasteriser, the application chooses one.
   * - ``wgl``
     - Windows
     - ``OpenGLContext.wglcontext`` creates a pbuffer through WGL. It needs a
       driver that offers ``WGL_ARB_pbuffer`` and a window station with a
       desktop, which a service in session 0 has. Nothing appears on screen.
   * - —
     - macOS
     - CGL (:py:mod:`OpenGL.CGL`) can create a context with no window, but
       without a default framebuffer, so OpenGLContext has no windowless
       backend on macOS. Use a hidden window instead:
       ``OPENGLCONTEXT_HIDDEN=1`` with any of the backends above.

``Context.getOffscreenContextType()`` returns the windowless context class for
the current platform, or ``None`` if its bindings cannot be loaded. A program
that runs on several platforms calls it instead of naming a class.
:doc:`Rendering offscreen <offscreen>` covers choosing a device, what each
backend needs, and what to do on a platform with neither.

.. _backend-capabilities:

What every backend offers
~~~~~~~~~~~~~~~~~~~~~~~~~

The same window-level methods are available on every backend, so the choice of
toolkit does not limit which engine features an application can use. Each
method returns ``True`` if it took effect and ``False`` if the platform could
not do it, so the application can offer the user an alternative.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it does
     - Returns False on
   * - ``setPointerCapture(on)``
     - Hides the pointer and reports unbounded motion, which mouse-look needs.
     - A window system that does not give a client the pointer, such as Qt's
       Wayland plugin. Turning is then limited to the window.
   * - ``setFullscreen(on)``
     - Switches a live window to full screen and back, keeping its GL context.
     - A machine with no monitor attached, or a session with no window
       manager to handle the request.
   * - ``applyVSync()``
     - Turns waiting for the display's refresh on or off, following
       ``ContextDefinition.vsync``.
     - Qt and Pygame, where the swap interval is part of the surface format
       set when the context is created. The change is logged and takes effect
       in the next window. GLUT, Tk and wxPython use the window system's
       swap-control extension, and return False where there is none.
   * - ``pumpWindowEvents()``
     - Delivers the window system's queued events, for a program that runs
       its own loop instead of calling ``MainLoop``.
     - The offscreen backends, which have no window system.
   * - ``releaseWindow()``
     - Releases the window and the GL objects in it. The name is the same on
       every backend, so the caller does not need to know which backend
       created the context.
     - Returns nothing.

To uncap the frame rate, call ``context.setVSync(False)``. It writes the field
and applies it. A headless capture needs this: a forced redraw blocks on a
buffer swap that nothing presents, so without it the capture draws one frame
and then waits indefinitely. A toolkit's own swap-interval call works only on
that toolkit's backend.

``getViewPort()`` returns the window's width and height as soon as the context
exists, before any events have been processed. A program that draws its first
frame before entering a loop gets a projection matrix, overlay scale and
picking ray of the right size. On a window system that reports the size only
through a resize callback, the backend queries the size directly while it
creates the window.

Every backend also:

- reports pointer motion to the movement sampler as it happens
  (``recordPointerMotion``);

- generates key-repeat where the platform delivers none;

- releases every held key when its window loses focus. No platform sends a
  key-up for a key that was down when focus moved elsewhere, and without the
  release the camera would keep moving. ``events.eventhandlermixin.HeldKeyMixin``
  implements this for all backends.

See :doc:`Movement Modes & Navigation <navigation>`.

Each backend's main loop has the same order: pump the window system's events,
run the animation hook, then render once for the iteration, however many
events arrived. A burst of input therefore produces a single frame rather than
a render per event. :ref:`looptrace <hud-loop>` times the phases, and the
telemetry and stall journals are closed when the loop ends. The GLUT loop uses
``glutMainLoopEvent``; with a GLUT that lacks it, GLUT runs the loop itself.
wxPython uses wx's own loop, and its phases are not timed.

An application that already has a main loop keeps it: the view goes into a
widget in the rest of the interface, and the host's loop drives the frames.
:doc:`Embedding a view in an application <embedding>` covers what Tk, Qt and wx
each need, with a sample program for each.

.. _fullscreen:

Filling the screen
~~~~~~~~~~~~~~~~~~

Set ``ContextDefinition.fullscreen`` to open the window filling the screen. Its
default comes from ``OPENGLCONTEXT_FULLSCREEN``, and the settings screen offers
it under *Interface*.

.. code-block:: python

   from OpenGLContext.contextdefinition import ContextDefinition
   MyGame.ContextMainLoop(definition=ContextDefinition(fullscreen=True))

The window opens at the display's current resolution, so the video mode does
not change. A mode change is slow and rearranges the icons on every desktop
that display shows. To render at a different resolution, set the definition's
``size``.

``OPENGLCONTEXT_HIDDEN`` takes precedence. The platforms treat a full-screen
request as a request to show the window, so a hidden capture subprocess that
also went full screen would cover the display of whoever started the run.

``context.setFullscreen(True/False)`` switches a window that already exists,
keeping the GL context and everything loaded into it, and returns whether the
backend could do it. Every windowed backend can. The settings screen's toggle
calls it, so a player can leave a full-screen game without restarting.

.. _core-profile:

OpenGL Core Profile Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~

A context uses the core profile unless the program asks for the compatibility
profile. The core profile draws with GLSL shaders instead of the
fixed-function pipeline, so it works on OpenGL 3.3+ contexts and on platforms
such as macOS that offer only the core profile. The engine's own geometry
requires it: ``PBRMesh`` draws only through shaders, and the glTF loader and
every generator built on it produce ``PBRMesh`` nodes. Every backend can create
a core-profile context.

The compatibility profile is fully supported. Use it for a program that draws
with the fixed-function pipeline.

Saying which profile your program needs
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

``OPENGLCONTEXT_PROFILE=compatibility`` sets the profile for a whole run, for a
CI job or a one-off comparison. A program that needs a particular profile
declares it on its Context class instead, so the requirement stays with the
code:

.. code-block:: python

   class MyContext( BaseContext ):
       profile = 'compatibility'   # this program draws with the fixed-function pipeline

Declare it for any program that calls ``glBegin``, ``glVertexPointer``,
``glMaterial``, ``glLight``, the matrix stack, display lists, or GLSL's
``gl_ModelViewProjectionMatrix`` and similar built-ins. None of these exist in
a core context.

``profile`` also sets the matching OpenGL version. It is applied on top of any
``contextDefinition`` the class declares, so a subclass can name its profile
and still inherit the size, buffers and rendering features from its base
class. To set more than the profile, declare the whole definition:

.. code-block:: python

   from OpenGLContext import contextdefinition

   class MyContext( BaseContext ):
       contextDefinition = contextdefinition.ContextDefinition(
           profile = 'compatibility',
           size = (800, 600),
           multisampleSamples = 4,
       )

Every backend reads either declaration before it creates the window. The
profile, the version and the buffer formats are window-creation parameters and
cannot be changed afterwards. A definition passed to the constructor takes
precedence over both. Each context gets its own copy of the class's
definition, because a context writes its size back to its definition when the
window is resized.

.. _context-resources:

When a context goes away
~~~~~~~~~~~~~~~~~~~~~~~~

A GL object is identified by a *name*, and the name is valid only in the
context that created it. The engine's caches of GL objects (the render pass,
the VRML97 shader programs, the text renderers, the teapot's vertex arrays)
are therefore keyed by the GL context as well as by the entry's own key.

The key is the context's handle, which is a memory address, and a driver can
give the same address to the next context it creates. A cache keyed on the
address that is not told when the old context is destroyed returns the old
context's names to the new one. PyOpenGL's own dispatch tables are keyed the
same way: a reused handle would bring the destroyed context's function
pointers with it.

A backend therefore makes two calls, which ``Context`` defines so that every
backend inherits them:

.. code-block:: python

   self.bindContextResources( handle )      # in setCurrent
   self.releaseContextResources( handle )   # as the window is destroyed

``releaseContextResources`` notifies the engine's caches so that they
*delete* their GL objects instead of only dropping them, and retires
PyOpenGL's dispatch table for that context. It must be called **while the
context is still current and its window still exists**, because only then
can GL objects be deleted. Every backend makes this call.

Application code that caches its own GL objects can register for the same
notification. The callback takes no arguments and runs with the dying context
current, so it can delete GL objects as well as drop them.
``contextresources.context_key()`` identifies the context:

.. code-block:: python

   from OpenGLContext import contextresources

   @contextresources.on_context_lost
   def drop_my_cached_objects():
       ...

Registering the same callable twice registers it once, and an exception in
one callback does not stop the others from running. The registry holds a
strong reference for the life of the process, which suits a module-level cache
registered at import. To unregister a callback bound to a shorter-lived
object, call ``contextresources.forget_context_lost( callback )``.

A cache holds **one entry per context**, not one entry in total. Two windows
draw in turn, so a single slot would hold whichever context drew last. Every
frame of every context would miss, rebuild what the other context displaced,
and leave the displaced GL objects in a live context with no way to delete
them. ``renderpass._passes``, ``shaderpass._shader_programs``,
``Teapot._buffers`` and ``shadertext._renderers`` are all mappings for this
reason.

The test fixtures also send the notification. A test suite opens and closes
several hundred windows in one process, which is when a driver is most likely
to reuse an address.

Navigation, overlays and utilities
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The :py:mod:`ViewPlatform <OpenGLContext.move.viewplatform>` and
:py:mod:`ViewPlatformMixin <OpenGLContext.move.viewplatformmixin>` classes
provide keyboard navigation: the arrow keys walk or fly, and Alt with the
arrow keys pans or slides. They also provide the three examine gestures:
right-drag to orbit, middle-drag to pan, and the wheel to move toward or away.
:py:mod:`TurntableOrbit <OpenGLContext.move.orbit>` implements the gestures and
:py:mod:`ExamineManager <OpenGLContext.move.examinemanager>` drives them; see
:ref:`Examining <examine>`.

For more than that, an application declares **movement modes** on its
``ContextDefinition``: walking, flying, swimming and first-person mouse-look,
as scenegraph nodes with their own speeds and key bindings. They are driven
from sampled input rather than from events, so several inputs can act in one
frame. See :doc:`Movement Modes & Navigation <navigation>`. A context that
declares no modes uses the keyboard navigation above.

For screens over the running world, such as rendering settings, key
rebinding, a licence notice or a console, an application mixes in
``ui.overlay.OverlayMixin``. It adds a stack of panels, routes input to the
topmost panel and draws the stack after the frame. While a modal panel is
open, the world receives no input, including the input sampler. When the
overlay takes a key press it also takes the matching release, so the key that
closes the last panel does not reach the world. Every switchable rendering
feature is a field on the ``ContextDefinition``, read through
``renderoptions``, and the settings screen is generated from those fields. The
window's height sets the font size and the rest of the interface is measured
from it, so the interface appears the same size at 1080p and at 4K. See
:doc:`Overlay UI <overlayui>`.

The top-level package also holds utility modules: drawcube (a test function),
:py:mod:`Quaternion <OpenGLContext.quaternion>`, :py:mod:`utilities
<OpenGLContext.utilities>`, :py:mod:`vector utilities
<OpenGLContext.vectorutilities>` and :py:mod:`triangle utilities
<OpenGLContext.triangleutilities>`. :doc:`Using NumPy arrays <numeric_arrays>`
describes the vector functions.

.. _passes:

Rendering Passes
----------------

The **passes** package holds the rendering system. ``Context.renderPasses`` is
the callable that draws a frame; by default it is
``renderpass.defaultRenderPasses``. A single ``FlatPass`` observes the
scenegraph and draws it each frame in a fixed sequence: selection, shadow maps,
then background, opaque, transmissive, transparent and overlay. See
:ref:`frame-sequence` for every step, and :doc:`Flat Rendering <flat>`.

The sequence runs once for each view in the context's ``ViewLayout``
(``OpenGLContext/multiview/``). The scene is traversed once, and each view
culls that traversal against its own camera and draws into its own rectangle;
see :doc:`Several views on one window <multiview>`.

The base class (``passes/_flat.py``) has two code paths, chosen by one flag:

- ``flatcompat.py`` -- the compatibility-profile pass, using the fixed-function
  pipeline (``glLight*``, ``glMaterial*``).

- ``flatcore.py`` -- the core-profile pass, using GLSL shaders. See
  :doc:`Core-Profile Rendering <renderpasses>`.

``VRML97ShaderProgram`` (``passes/shaderpass.py``) compiles the lit, unlit,
vertex-colour, point, line and shadow-depth programs. It assembles them from
the GLSL sources in the ``shaders/`` directory: the ``.vert`` and ``.frag``
files, plus shared ``_*.glsl`` files that are included at compile time. Built
on top of these are:

- ``pbrpass.py`` -- the physically based (metallic/roughness) renderer, a
  Cook-Torrance uber-shader. See :doc:`Physically Based Rendering <pbr>` and the
  :doc:`shader walkthrough <ubershader>`.

- ``ibl.py`` -- image-based (environment) lighting: the precomputed
  irradiance, prefilter and BRDF lookup-table probe.

- ``shadowmap.py``, ``shadowmixin.py``, ``shadowcaps.py``, ``shadowmath.py`` --
  the shadow subsystem shared by the VRML97 and PBR lit shaders. See
  :doc:`Shadows <shadows>`.

- ``transmission.py`` -- the backdrop capture for glass
  (``KHR_materials_transmission``).

- ``selection.py`` -- colour and object-id picking.

- ``renderpass.py`` -- chooses which ``FlatPass`` subclass renders a context
  (by profile and renderer) and caches the choice across frames.

- ``viewpointbinding.py`` -- binds the scene's active Viewpoint to the view
  platform in the core-profile path.

``OpenGLContext/multiview/`` holds the views: the layout a frame is drawn for,
the drawing strategy the driver supports, and the ``ViewFrame`` holding one
view's camera, frustum and draw list.

.. _structure-loaders:

Loaders, the Viewer and Command-Line Tools
------------------------------------------

The **loaders** package reads external model formats into the scenegraph:

- VRML97 files, parsed with SimpleParse (see :doc:`Loading VRML97
  <vrml97>`).

- glTF 2.0 and binary GLB, through pygltflib, mapped onto PBR materials (see
  :doc:`Loading glTF <gltf>`).

- Streamed OGC 3D Tiles (see :doc:`Streamed 3D Tiles <tiles3d>`).

- Wavefront OBJ.

.. _background-loading:

Loading without stopping the frame
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Setting the ``url`` of an ``ImageTexture``, an ``Inline``, a ``GLSLShader`` or
an ``HDRBackground`` returns immediately. The fetch, decode and parse run on
the thread pool in ``OpenGLContext.loaders.background``. The pool has
``background.WORKERS`` daemon threads (four), started as work arrives, so a
scene that names several hundred textures uses four threads. A load that
raises an exception is logged with its url, and the worker continues with the
next load.

To wait until the scene is complete, for example in a test or a tool, call
``wait_for_idle``:

.. code-block:: python

   from OpenGLContext.loaders import background

   texture = ImageTexture(url=['brick.png'])
   background.wait_for_idle(20)        # True once every load has finished
   print(background.pending())         # how many are still going

``wait_for_idle`` returns ``False`` if the timeout expires first. It also waits
for work submitted while it is waiting, such as the files a scene's first file
names. For loads that should not queue behind the scenegraph's, create a
separate ``background.LoadPool`` and call its ``shutdown()`` when you are done
with it. The engine's own pool lasts as long as the process.

.. rst-class:: technical

When a load is submitted with a ``prepare`` callable, ``prepare`` runs **on the
submitting thread**. Each url field uses it to import the modules its load
needs: PIL's per-format plugins, the loader, the format handlers and the
lighting probe. The first import of a module holds CPython's import lock. A
thread waiting for that lock does not respond to ``SIGTERM``,
``KeyboardInterrupt`` or a test runner's timeout. Running first-use imports on
the submitting thread keeps them interruptible, and raises any
``ImportError`` where the caller can handle it. Pass a ``prepare`` callable to
``background.load_in_background`` for your own loads for the same reason.

The viewer
~~~~~~~~~~

The **viewer** package is the reusable viewer: it loads a scene without
freezing the window, and provides default lighting, automatic framing, cameras
and animations, the window caption, screenshots, a library of samples, and
rendering one settled frame to a file. An application embeds
``viewer.sceneviewer.ViewerContext`` and configures it with a
``ViewerOptions``, the same object the command line fills in (see
:ref:`Embedding the viewer <viewer-embedding>`). Its modules (``adapters``,
``asyncscene``, ``framing``, ``environment``, ``caption``, ``capture``,
``library``, ``menu``) can also be used by a context that is not a viewer.

An **adapter** registered under ``plugins.Adapter`` decides which format a
source is in, alongside the loader, context and node registries. A third party
adds a format by registering an adapter, without changing the viewer; see
:ref:`Adding a format <adapters>`.

Command-line tools and packaging
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The **bin** package provides the console commands, installed as scripts with
the package: ``oglc-view`` (:doc:`the viewer <viewer>` with a command line, for
every format), ``oglc-terrain``, ``oglc-gltf-demo``, ``oglc-gltf-regression``,
``oglc-ui-demo``, ``oglc-character-sheet``, ``oglc-test`` and
``oglc-lorentz``. ``oglc-gltf``, ``oglc-vrml`` and ``oglc-tiles`` are
deprecated aliases for ``oglc-view``. :ref:`Console commands <commands-list>`
describes each one.

The **packaging** package builds an application on the engine into something
a user without Python can run: a frozen bundle, or a native package with its
own interpreter. It records what those tools cannot find out by themselves:

- which engine modules are loaded by name rather than by import (the
  PyInstaller hooks in ``__pyinstaller``, which PyInstaller finds through an
  entry point);

- which windowing toolkits an application does not use;

- which libraries it loads from the operating system.

It provides one console command, ``oglc-deb``. Nothing in it is imported at run
time and nothing in it draws. See :doc:`Packaging an application
<packaging>`.

.. _scenegraph-rendering:

Scenegraph Rendering
--------------------

The :py:mod:`scenegraph <OpenGLContext.scenegraph>` and
:py:mod:`scenegraph.text <OpenGLContext.scenegraph.text>` packages provide
Python classes for common geometry, materials, textures and grouping nodes,
modelled on VRML97 nodes. You build a retained-mode scene from them and a
context renders it. The node classes depend very little on the internals of
the context.

The package includes :py:mod:`Transform <OpenGLContext.scenegraph.transform>`
(including the integer "names" reported during selection), :py:mod:`Shape
<OpenGLContext.scenegraph.shape>`, :py:mod:`Material
<OpenGLContext.scenegraph.material>`, :py:mod:`ImageTexture
<OpenGLContext.scenegraph.imagetexture>` and :py:mod:`Light
<OpenGLContext.scenegraph.light>` nodes, similar to their VRML97 namesakes.
:py:mod:`ArrayGeometry <OpenGLContext.scenegraph.arraygeometry>` renders
:py:mod:`IndexedFaceSet <OpenGLContext.scenegraph.indexedfaceset>`,
:py:mod:`IndexedLineSet <OpenGLContext.scenegraph.indexedlineset>` and
:py:mod:`PointSet <OpenGLContext.scenegraph.pointset>`; each of those modules
creates an ArrayGeometry with the appropriate parameters. The text package
renders 3D or 2D text using TTFQuery or a GUI library's font engine; see
:doc:`Rendering Text <text>`.

Alongside the VRML97-style nodes, the scenegraph includes ``PBRMaterial`` and
a ``PBRMesh`` geometry (``scenegraph/pbrmaterial.py``). These are the
metallic/roughness material and mesh that the :doc:`glTF loader <gltf>`
produces and the :doc:`PBR pass <pbr>` renders. When the PBR renderer is
active, legacy ``Material`` nodes are converted to the same model, so both
kinds of content go through one pipeline.

.. _events-and-selection:

Events and Selection
--------------------

The :py:mod:`events <OpenGLContext.events>` package provides event generation
and handling that works the same across GUI libraries. Each GUI library
defines subclasses of the main event and event handler classes, which
translate native events into OpenGLContext events. The event handler classes
are mix-ins, included in each GUI library's Context class to provide the event
handling interface. See :doc:`Event Model <eventmodel>` for how changes
propagate through the scenegraph.

Mouse events reach the application through the pick queue. A backend adds an
event with ``Context.addPickEvent``, and the selection pass dispatches it once
it has found what is under the pick point. The queue is a mapping keyed by
``Event.getPickKey``, so identical events within one frame are dispatched
once.

The mouse wheel is handled differently. Each notch arrives as a press and
release of button 3 or 4 (``mouseevents.WHEEL_UP`` and ``WHEEL_DOWN``, the X11
numbering). A notch is an increment rather than a state, so each notch has a
distinct pick key and none is dropped. GLFW reports scrolling through its own
callback as offsets, and the GLFW backend translates these into the button
events; see :ref:`the overlay UI documentation <wheel>`.

When an event arrives, ``Context.routeEvent`` sets ``event.view`` to the view
it belongs to: the view under the pointer, the view where a held button was
pressed, or, for a key, the active view. The selection pass resolves the pick
through that view's camera. See :doc:`Several views on one window
<multiview>`.

.. _structure-bindings:

Which handler holds a key
~~~~~~~~~~~~~~~~~~~~~~~~~

Each key has one handler: the last one registered. A key is identified by
``(name, state, modifiers)``, and registering a second handler for the same
triple replaces the first. ``Context.__init__`` binds keys in two steps, in
this order:

#. ``setupDefaultEventCallbacks`` binds the framework's defaults: Escape, the
   arrow-key navigation, right-drag to examine, PageDown to cycle viewpoints,
   ``Alt+F`` for the developer overlay, and :ref:`F2 or Alt+S <screenshots>`
   for a screenshot.

#. ``setupCallbacks`` binds the keys for *this* context. It runs second, so an
   application that binds a key the framework also binds replaces the
   framework's handler.

Modifiers are a three-tuple in the order ``(shift, control, alt)``. A binding
with a modifier in the wrong position registers without error, and the key
never fires.

Handlers are held by **weak** reference, so the caller must keep the callback
alive. A bound method of a live object is the usual choice. A callback with no
other reference is garbage-collected as soon as the registration returns, and
the key does nothing.

.. _present:

Presenting a frame, and reading it
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A render pass finishes a frame by calling ``Context.presentFrame``. This is
the last point at which the frame can be read: ``SwapBuffers`` gives the back
buffer to the driver, which reuses it, so a read after the swap returns an
older frame. A screenshot, a :doc:`still capture <testing>` or a
:doc:`recording <recording>` reads the frame in ``presentFrame``.

.. code-block:: python

   def presentFrame(self):
       self.tickRecording()              # before the swap: this is the frame
       return super().presentFrame()

``SwapBuffers`` is the method each GUI backend implements to display the
buffer. Override ``presentFrame`` for work that belongs to the frame, and
override ``SwapBuffers`` only when writing a backend.

.. _screenshots:

The screenshot key
~~~~~~~~~~~~~~~~~~

Every context binds ``F2`` (and ``Alt+S``) to ``requestScreenshot``, so every
program built on OpenGLContext has a screenshot key without configuration.
Pressing the key sets a flag and requests a redraw; the picture is taken in
``presentFrame``, for the reason given above. The redraw makes the key work on
a still scene, which would otherwise draw no further frames.

The file is written to the user's picture folder: ``~/Pictures``, or the
folder the desktop, the Finder or the Windows shell names for pictures. It is
named after the window title, for example ``GLinting-Steel-0001.png``. The
number increases to the first name not already in use, so pressing the key
twice keeps both pictures. On a machine with no home directory, the file is
written to the working directory.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Attribute
     - What it does
   * - ``screenshotKey``
     - The key to bind, ``'<F2>'`` by default. Set it to ``''`` to bind no
       key, for example to use F2 for something else.
   * - ``screenshotTemplate``
     - The file name pattern. ``%(name)s`` is the window title, and
       ``%(count)04i`` is the number that increases until the name is free.
   * - ``screenshotDirectory()``
     - Returns the directory for a screenshot with no path of its own.
       Override it to save screenshots elsewhere.
   * - ``OnSaveImage()``
     - Saves the current back buffer immediately. Call it from
       ``presentFrame``, or pass ``template=`` to write a named file.
