.. _backends:

Windowing Backends
==================

.. rst-class:: introduction

OpenGLContext supports six GUI toolkits. With three of them the scene fills
the window. The other three put a GL view inside an interface built from
ordinary widgets, for a tool with menus and panels around the view. Every
backend can create a core-profile or a compatibility-profile context, and
every backend provides the :ref:`window-level methods <backend-capabilities>`
listed below. Set ``OPENGLCONTEXT_BACKEND`` to choose one (see
:doc:`Environment variables <environment>`).

The scene fills the window
--------------------------

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
--------------------------

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
----------------------

wxPython on GTK3 creates its GL context through EGL rather than GLX, and on
X11 it may use either. No configuration is needed. PyOpenGL's Linux platform
loads both interfaces and checks which one owns the current context, then
routes calls to that API (:py:mod:`OpenGL.platform.linux`). Do not set
``PYOPENGL_PLATFORM`` for wxPython.

.. _qt-backend:

Qt/PySide and the platform plugin
---------------------------------

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
----------------

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
-------------------------

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
   * - ``setPointerShape(name)``
     - Shows the pointer named in ``OpenGLContext.context.CURSORS``;
       ``''`` is the ordinary pointer. The overlay asks for the shape the
       control under the pointer wants; see :ref:`pointer-feedback`.
     - A shape the platform or its cursor theme has no picture for, which is
       left as it was; the offscreen backends, which have no pointer; and, on
       GLUT, Tk, wxPython and Qt, any shape while mouse-look holds the pointer
       hidden. The overlay asks for none then, whatever the backend.
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
backend could do it. Every windowed backend can. The settings screen's toggle
calls it, so a player can leave a full-screen game without restarting.

.. _top-level:

The context classes
-------------------

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

Adding a backend
~~~~~~~~~~~~~~~~

Context classes are registered by calling ``OpenGLContext.plugins.Context``
with a name and the dotted path to the class. ``OpenGLContext/__init__.py``
does this for the built-in backends. A third party registers its own backend
the same way, at import time:

.. code-block:: python

   from OpenGLContext.plugins import Context, InteractiveContext

   Context( 'mytoolkit', 'mypackage.context.MyContext' )
   InteractiveContext( 'mytoolkit', 'mypackage.context.MyInteractiveContext' )

The registry is a list in the running process. A third-party backend is added
to it when the application imports that package; there is no entry-point scan
and no install step beyond making the package importable.
``OPENGLCONTEXT_BACKEND=mytoolkit`` then selects it by the registered name.
Loaders, viewer adapters and scenegraph nodes are registered the same way,
through ``plugins.Loader``, ``plugins.Adapter`` (see :ref:`Adding a format
<adapters>`) and ``plugins.Node``.

A backend implements ``SwapBuffers`` to display a finished frame; see
:ref:`Presenting a frame <present>`.

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
