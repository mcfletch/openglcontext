.. _backends:

Window Systems
==============

.. rst-class:: introduction

OpenGLContext draws into a window belonging to one of six GUI toolkits, or into
a pbuffer with no window at all.  With three of the toolkits the scene fills the
window; the other three put a GL view inside an interface built from ordinary
widgets, for a tool with menus and panels around the view.  Every window system
creates a core-profile or a compatibility-profile context, and every one
provides the :ref:`window-level methods <backend-capabilities>` listed below.

A :py:class:`~OpenGLContext.context.Context` *holds* its window system rather
than being one: ``context.windowsystem`` is a
:py:class:`~OpenGLContext.windowsystem.WindowSystem`, and ``context.window`` is
the toolkit's own window or widget.  Which window system is a field of the
context's definition.

.. _choosing-a-window-system:

Choosing a window system
------------------------

``ContextDefinition.windowsystem`` names it, by the name it is registered
under.  A program writes one context class and says where it opens:

.. code-block:: python

   from OpenGLContext.context import Context

   class Viewer(Context):
       def OnInit(self):
           self.sg = Loader.load('world.glb')

   Viewer.ContextMainLoop(windowsystem='pygame', size=(800, 600))

The field is read once, as the context is built.  Left empty -- the default --
it is settled then, in this order:

1. ``OPENGLCONTEXT_BACKEND``, where it is set (see :doc:`Environment variables
   <environment>`).  A name set there that is not usable is an error, since the
   run asked for it.
2. The user's preference, ``defaultcontext.txt`` in their application-data
   directory, which ``Context.setDefaultContextType(name)`` and ``python -m
   OpenGLContext.bin.choosecontext`` write.  A preference that is not usable is
   logged and passed over.
3. The first window system that imports, in the order ``glfw``, ``glut``,
   ``pygame``, ``qt``, ``tk``, ``wx``, then any other registered one.  The
   windowless ones are never chosen this way.

``offscreen`` names whichever window system renders with no window on this
platform: ``wgl`` on Windows and ``egl`` everywhere else.  A name that is not
registered, or whose toolkit will not import, raises
:py:class:`~OpenGLContext.windowsystem.WindowSystemUnavailable` (a
``RuntimeError``) naming what was asked for, what is registered and the import
error.  :py:func:`OpenGLContext.windowsystem.choose` is the rule.

A class that needs one window system pins it, as it pins its profile:

.. code-block:: python

   class Baker(Context):
       windowSystemName = 'offscreen'    # never open a window

``windowSystemName`` is applied over the class's own ``contextDefinition`` and
under a definition passed to the constructor that names one.  Each toolkit's
module publishes a class pinned this way -- ``glfwcontext.GLFWContext``,
``pygamecontext.PygameContext``, ``tkcontext.TkContext``,
``wxcontext.wxContext``, ``eglcontext.EGLContext`` and so on -- and its
``*interactivecontext`` and ``*vrmlcontext`` modules name the same class.

The scene fills the window
--------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Window system
     - Runs on
     - Notes
   * - ``glfw``
     - Linux (X11 and Wayland), Windows, macOS
     - The test suite and the visual-regression captures run on it. Use it
       for core-profile and PBR work. ``pip install "OpenGLContext[glfw]"``
       installs the library.  ``context.window`` is GLFW's window handle.
   * - ``glut``
     - Linux (X11; XWayland under Wayland), Windows, macOS
     - freeglut, through the C library the system provides. On Windows,
       ``pip install PyOpenGL[glut]`` supplies it. The NeHe tutorials are
       written against it. freeglut has no Wayland backend of its own.
       ``context.window`` is GLUT's window id.
   * - ``pygame``
     - Linux (X11 and Wayland), Windows, macOS
     - SDL2's window, input and audio, for an application already built on
       Pygame. ``pip install "OpenGLContext[pygame]"``.  ``context.window``
       is the display surface.

A view inside an interface
--------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Window system
     - Runs on
     - Notes
   * - ``tk``
     - Linux (X11; XWayland under Wayland), Windows, macOS
     - Tkinter, through PyOpenGL's own ``OpenGL.Tk.GLFrame`` widget, so it
       imports nothing outside Python's standard library. Tcl/Tk itself is a
       system package, and several Linux distributions leave it out of a
       default Python install (``apt install python3-tk``).
       ``Context(windowsystem='tk', parent=someFrame)`` puts the view in a
       frame you built; ``context.window`` is the ``GLFrame``.
   * - ``wx``
     - Linux (X11 and Wayland, through GTK3), Windows, macOS
     - wxPython 4 (Phoenix) or newer.  ``context.window`` is a
       ``wx.glcanvas.GLCanvas``, made inside the ``parent`` given.  See
       ``tests/wx_with_controls.py`` and :ref:`the note on GTK3 <wx-gtk3>`.
   * - ``qt``
     - Linux (X11, and Wayland where the Qt build's platform plugin provides a
       drawable GL surface; otherwise ``QT_QPA_PLATFORM=xcb`` runs it through
       XWayland), Windows, macOS
     - Qt 6 through PySide6, from the separate :py:mod:`OpenGLContext_qt
       <OpenGLContext_qt>` distribution, which declares it in the
       ``OpenGLContext.windowsystems`` entry-point group.  ``context.window``
       is a ``QWindow``.  See :ref:`the notes on Qt <qt-backend>`.

Each takes the toolkit container to open inside as the context's ``parent``
keyword; a window system that makes windows of its own only refuses one.
:doc:`Embedding a view in an application <embedding>` covers what each needs.

.. rst-class:: technical

The Tk window system draws into ``OpenGL.Tk.GLFrame``, which creates a GL
context on the window Tk provides, through GLX on X11 and WGL on Windows. A Tk
window has no native handle until it is mapped, so ``OPENGLCONTEXT_HIDDEN`` is
applied by withdrawing the window once the context exists.  The window appears
briefly and then goes. Rendering and reading back are not affected, because
both use the back buffer. On a headless machine, run the X11-only window
systems under ``xvfb-run``.

.. _wx-gtk3:

wxPython, GTK3 and EGL
----------------------

wxPython on GTK3 creates its GL context through EGL rather than GLX, and on
X11 it may use either. No configuration is needed. PyOpenGL's Linux platform
loads both interfaces and checks which one owns the current context, then
routes calls to that API (:py:mod:`OpenGL.platform.linux`). Do not set
``PYOPENGL_PLATFORM`` for wxPython.

A wx canvas has no GL context to run ``OnInit`` in until the toolkit has
created its native window, which on GTK is after the constructor returns, so
the wx window system completes the context from the canvas's creation or its
first paint, whichever comes first.

.. _qt-backend:

Qt/PySide and the platform plugin
---------------------------------

The Qt window system is in the separate **OpenGLContext-qt** distribution. It
is registered under the name ``qt`` through its entry point, so once it is
installed ``windowsystem='qt'`` (or ``OPENGLCONTEXT_BACKEND=qt``) selects it.
It uses ``QWindow`` with its own ``QOpenGLContext`` rather than
``QOpenGLWidget``. Framebuffer 0 is therefore the screen, and every render path
(the bloom composite, the selection buffer's blit, the back-buffer read for a
screenshot) behaves as it does under GLUT and GLFW. Both profiles are
supported, and every ``ContextDefinition`` field that describes the window is
mapped to the Qt surface format.

.. code-block:: bash

   OPENGLCONTEXT_BACKEND=qt python your_script.py

Some Qt platform plugins return a context that is current on no drawable
surface. Every GL call then succeeds without error, and every frame is black.
The window system detects this at start-up and logs a message naming the
plugin.  Selecting another plugin usually fixes it:

.. code-block:: bash

   QT_QPA_PLATFORM=xcb OPENGLCONTEXT_BACKEND=qt python your_script.py

Limits of the Qt window system:

- ``accumulationBuffer`` does not exist in Qt 6. The window system reports it
  instead of ignoring it.

- ``OPENGLCONTEXT_HIDDEN`` is not supported. Qt's offscreen surfaces have no
  default framebuffer on the common EGL platforms, so use ``glfw`` for
  headless capture.

No window at all
----------------

A build machine, a rendering service or a batch job may need a context with no
window and no display server. Each platform provides this through its own
interface, and OpenGLContext has window systems for two of them:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Window system
     - Runs on
     - Notes
   * - ``egl``
     - Linux, and Android
     - :doc:`EGL <offscreen>` opens a GPU and renders to a pbuffer, with no
       display server, compositor or session.  On a machine with several EGL
       devices, such as a GPU and a CPU rasteriser, the application chooses
       one.
   * - ``wgl``
     - Windows
     - A pbuffer made through WGL.  It needs a driver that offers
       ``WGL_ARB_pbuffer`` and a window station with a desktop, which a
       service in session 0 has. Nothing appears on screen.
   * - —
     - macOS
     - CGL (:py:mod:`OpenGL.CGL`) can create a context with no window, but
       without a default framebuffer, so OpenGLContext has no windowless
       window system on macOS. Use a hidden window instead:
       ``OPENGLCONTEXT_HIDDEN=1`` with any of the window systems above.

``windowsystem='offscreen'`` asks for whichever of the two this platform has,
so a program that runs on several platforms names no toolkit.  On either, the
main loop draws the context's ``frameCount`` frames -- or as many as
``wantsMoreFrames()`` asks for -- and returns.  :doc:`Rendering offscreen
<offscreen>` covers choosing a device, what each needs, and what to do on a
platform with neither.

.. _backend-capabilities:

What every window system offers
-------------------------------

The same window-level methods are available on every context, whichever window
system it holds, so the choice of toolkit does not limit which engine features
an application can use.  Each is answered by the window system, and returns
``True`` if it took effect and ``False`` if the platform could not do it, so the
application can offer the user an alternative.

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
   * - ``setPointerShape(name)``
     - Shows the pointer named in ``OpenGLContext.context.CURSORS``;
       ``''`` is the ordinary pointer. The overlay asks for the shape the
       control under the pointer wants; see :ref:`pointer-feedback`.
     - A shape the platform or its cursor theme has no picture for, which is
       left as it was; the offscreen window systems, which have no pointer;
       and, on GLUT, Tk, wxPython and Qt, any shape while mouse-look holds the
       pointer hidden. The overlay asks for none then.
   * - ``setFullscreen(on)``
     - Switches a live window to full screen and back, keeping its GL context.
     - A machine with no monitor attached, or a session with no window
       manager to handle the request.
   * - ``applyVSync()``
     - Turns waiting for the display's refresh on or off, following
       ``ContextDefinition.vsync``.
     - Qt and Pygame, where the swap interval is part of the surface format
       set when the context is created. The change is logged and takes effect
       in the next window. GLUT, Tk and wxPython use the platform's
       swap-control extension, and return False where there is none.
   * - ``pumpWindowEvents()``
     - Delivers the window system's queued events, for a program that runs
       its own loop instead of calling ``MainLoop``.
     - The offscreen window systems, which have none.
   * - ``releaseWindow()``
     - Releases the window and the GL objects in it.
     - Returns nothing.

To uncap the frame rate, call ``context.setVSync(False)``. It writes the field
and applies it. A headless capture needs this: a forced redraw blocks on a
buffer swap that nothing presents, so without it the capture draws one frame
and then waits indefinitely.

``getViewPort()`` returns the window's width and height as soon as the context
exists, before any events have been processed. A program that draws its first
frame before entering a loop gets a projection matrix, overlay scale and
picking ray of the right size: the window system reports the size of what is
drawn into (``drawableSize()``) as the context completes, in the pixels the
viewport counts, which on a scaled display are not the window's logical ones.

Every window system also:

- reports pointer motion to the movement sampler as it happens
  (``recordPointerMotion``);

- lets the context generate key-repeat where the platform delivers none;

- releases every held key when its window loses focus. No platform sends a
  key-up for a key that was down when focus moved elsewhere, and without the
  release the camera would keep moving. ``events.eventhandlermixin.HeldKeyMixin``
  implements this, and the window system builds the release as its own
  toolkit's event (``emitKey``).

See :doc:`Movement Modes & Navigation <navigation>`.

Each main loop has the same order: take the window system's queued events, run
the animation hook (``OnIdle``), then render once for the iteration, however
many events arrived. A burst of input therefore produces a single frame rather
than a render per event.  ``WindowSystem.loopIteration`` is that pass;
:ref:`looptrace <hud-loop>` times its phases, and the telemetry and stall
journals are closed when the loop ends.  The GLUT loop uses
``glutMainLoopEvent``; with a GLUT that lacks it, GLUT runs the loop itself.
Tk and Qt drive the pass from a toolkit timer, and wxPython from its idle
event.

An application that already has a main loop keeps it: the view goes into a
widget in the rest of the interface, and the host's loop drives the frames,
calling ``context.loopIteration()`` where its toolkit does not.
:doc:`Embedding a view in an application <embedding>` covers what Tk, Qt and wx
each need, with a sample program for each.

.. _fullscreen:

Filling the screen
------------------

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
window system could do it. Every windowed one can. The settings screen's toggle
calls it, so a player can leave a full-screen game without restarting.

.. _top-level:

The context class
-----------------

:py:class:`OpenGLContext.context.Context` is the one context class.  It is
composed of mix-ins, each in its own module:

- :py:class:`~OpenGLContext.events.eventhandlermixin.EventHandlerMixin` -- the
  keyboard, mouse and timer event managers (see :ref:`Events and selection
  <events-and-selection>`);
- :py:class:`~OpenGLContext.move.viewplatformmixin.ViewPlatformMixin` -- the
  camera and the default navigation;
- :py:class:`~OpenGLContext.vrmlcontext.VRMLSceneMixin` -- ``load()`` and the
  font providers ``Text`` nodes draw with, loaded the first time one is drawn;
- :py:class:`~OpenGLContext.context.ContextCore` -- the definition, the window
  system, redraw scheduling, the render passes, picking and the frame loop.

An application subclasses ``Context`` and overrides ``OnInit``, ``Render``,
``OnIdle``, ``setupCallbacks`` and the other customisation points; none of the
toolkit's own methods are in its namespace.
:py:mod:`testingcontext <OpenGLContext.testingcontext>`'s ``getInteractive()``
answers ``Context`` for the tutorials, and ``getInteractive(name)`` the class
pinned to that window system.

Writing a window system
~~~~~~~~~~~~~~~~~~~~~~~

A window system is a subclass of
:py:class:`OpenGLContext.windowsystem.WindowSystem`.  It is made with the
context it draws for, as ``self.context``, and provides:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it does
   * - ``open(definition, parent)``
     - Makes the window and its GL context from the resolved definition,
       current on this thread; answers whether ``OnInit`` can run now.  One
       that cannot calls ``context.completeInit()`` itself once it can.
   * - ``makeCurrent()``
     - Makes the GL context current and answers its handle
       (``self.glHandle()``), or None where there is no window.
   * - ``swap()``
     - Presents the finished frame.
   * - ``drawableSize()``
     - The size of what is drawn into, in pixels.
   * - ``release()``
     - Calls ``context.releaseContextResources(handle)`` with the GL context
       current, then destroys the window.  Twice is once.
   * - ``bindCallbacks()``
     - Connects the toolkit's input to methods of its own, which build the
       events in :py:mod:`OpenGLContext.events` with ``self.context`` and
       hand them to ``context.ProcessEvent`` or ``context.addPickEvent``.
   * - ``pump()``, ``running()``, ``mainLoop()``, ``run(contextClass, ...)``
     - The loop.  The defaults poll with ``pump()`` and render once per pass;
       a toolkit whose dispatcher owns the loop sets ``pollsEvents = False``
       and calls ``loopIteration()`` from a timer.  ``run`` makes an
       application object first where the toolkit needs one.

and optionally ``setFullscreen``, ``setPointerCapture``, ``setPointerShape``,
``applyVSync``, ``resize`` (for a surface of fixed size), ``emitKey``,
``quit`` (answering False for a view inside somebody else's application) and
``abandon``.  ``OpenGLContext/windowsystem/glfw.py`` is the shortest complete
one.

It is registered under a name, by its dotted path, either in the running
process:

.. code-block:: python

   from OpenGLContext.plugins import WindowSystem

   WindowSystem('mytoolkit', 'mypackage.windowing.MyWindowSystem')

or, so that installing the package is enough, in its distribution's metadata:

.. code-block:: toml

   [project.entry-points."OpenGLContext.windowsystems"]
   mytoolkit = "mypackage.windowing:MyWindowSystem"

Nothing is imported until a context asks for it.  ``windowsystem='mytoolkit'``
or ``OPENGLCONTEXT_BACKEND=mytoolkit`` then selects it.  Loaders, viewer
adapters and scenegraph nodes are registered the same way, through
``plugins.Loader``, ``plugins.Adapter`` (see :ref:`Adding a format
<adapters>`) and ``plugins.Node``.

.. _context-resources:

When a context goes away
------------------------

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

So there are two calls, both on ``Context``.  ``setCurrent`` makes the first
with the handle the window system's ``makeCurrent`` answers, and a window system
makes the second as it destroys its window:

.. code-block:: python

   context.bindContextResources( handle )      # in Context.setCurrent
   context.releaseContextResources( handle )   # in WindowSystem.release

``releaseContextResources`` notifies the engine's caches so that they
*delete* their GL objects instead of only dropping them, and retires
PyOpenGL's dispatch table for that context. It must be called **while the
context is still current and its window still exists**, because only then
can GL objects be deleted. Every window system makes this call.

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
reason, and so are the GL names an object holds of its own: the vertex array
objects each geometry node keeps (``scenegraph.shadergeometry.get_or_build_vao``)
the display lists a font compiles for its characters
(``scenegraph.text.font.Font``), and the list a ``displaylist.DisplayList``
holds. Those are kept one set per context the object is drawn in (a
``DisplayList``'s, in the context current when it is made), and deleted in that
context when the object is collected or the context is torn down.

An object's names cannot be deleted from its ``__del__``: a finaliser runs on
whichever thread the collector does, with whatever context is current there,
or none. ``contextresources.ContextNames`` is the mechanism the engine uses for
them, and application code holding GL names of its own can use it too. It is
made once, at module level, naming the attribute it keeps an owner's names in
and how one name is deleted; ``entries(owner)`` answers the owner's entries for
the current context, made on first use, or ``None`` for an object that cannot
take an attribute:

.. code-block:: python

   from OpenGL.GL import glDeleteBuffers
   from OpenGLContext import contextresources

   _BUFFERS = contextresources.ContextNames(
       '_buffers', lambda name: glDeleteBuffers(1, [name]))

   def buffer_for(owner):
       buffers = _BUFFERS.entries(owner)
       if 'vertices' not in buffers:
           buffers['vertices'] = make_buffer(owner)
       return buffers['vertices']

When an owner is collected its names are queued by context and deleted the
next time ``entries`` or ``collect()`` runs with that context current; a torn
down context has every owner's names for it deleted and forgotten. By default
an entry is a name; ``names=`` takes a function listing the names an entry
holds, where an entry carries more than one or something besides.

The test fixtures also send the notification. A test suite opens and closes
several hundred windows in one process, which is when a driver is most likely
to reuse an address.
