Rendering offscreen
===================

.. rst-class:: introduction

An offscreen context renders without a window. It creates a GL context
directly on a GPU, draws, and returns the pixels. Use it on a build machine
with no screen, in a rendering service, or in a batch job such as making
thumbnails for thousands of models. It is an ordinary
:py:class:`~OpenGLContext.context.Context` on a window system with no window:
``egl`` on Linux (:py:mod:`OpenGLContext.windowsystem.egl`) and ``wgl`` on
Windows (:py:mod:`OpenGLContext.windowsystem.wgl`).  ``offscreen`` names
whichever of the two the platform has, and both behave the same way.

Using an offscreen context
--------------------------

An offscreen context is an ordinary context. The scenegraph, the render
passes, the caches, screenshots, the :doc:`video recorder <recording>` and
the :doc:`event model <eventmodel>` all work as they do in a window:

.. code-block:: python

   from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor
   from OpenGLContext.context import Context

   class Offscreen(Context):
       windowSystemName = 'offscreen'      # EGL on Linux, WGL on Windows

       def Render(self, mode=None):
           glClearColor(0.2, 0.3, 0.3, 1.0)
           glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

   Offscreen.ContextMainLoop(size=(640, 480))

``MainLoop`` renders ``frameCount`` frames and returns. The default is one
frame; set it higher to render an animation frame by frame. A context is also
a context manager, which releases it on the way out and suits most scripts:

.. code-block:: python

   with Offscreen(size=(640, 480)) as context:
       context.OnDraw(force=1)
       pixels = glReadPixels(0, 0, 640, 480, GL_RGB, GL_UNSIGNED_BYTE)

An application that leaves its window system to the environment needs no
code change:

.. code-block:: bash

   OPENGLCONTEXT_BACKEND=offscreen python my_application.py

``eglcontext.EGLContext`` and ``wglcontext.WGLContext`` are ``Context`` with
one or the other pinned, and add ``close()`` under the name a pbuffer's owner
reaches for; ``releaseWindow()`` is the same call.

The context renders into a pbuffer, which is a real default framebuffer.
Passes that draw to framebuffer zero, read it back or take a screenshot work
as they do on a window, with no offscreen-specific code.

The context is made with the profile and version its definition names, as a
window is (see :doc:`profiles`): a core program gets a forward-compatible core
context at its version, so a fixed-function call fails offscreen as it does
in a window. A compatibility program that names a version of 3.2 or later gets
a compatibility profile at that version; one that names none gets the
driver's default context.

Platform support
----------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Platform
     - Window system
     - Requirements
   * - Linux
     - ``egl``: ``OpenGLContext.windowsystem.egl``
     - An EGL device. No display server, compositor or login session is
       needed.
   * - Windows
     - ``wgl``: ``OpenGLContext.windowsystem.wgl``
     - A display driver with ``WGL_ARB_pbuffer``, and a window station with a
       desktop. A service in session 0 has both. Nothing needs to be on
       screen, and no compositor or open remote-desktop connection is needed.
   * - macOS
     - none
     - CGL can create a windowless context (``OpenGL.CGL``) but provides no
       default framebuffer, so OpenGLContext has no offscreen window system
       for macOS. Use a hidden window.

On a platform without an offscreen window system, use a hidden window: set
``OPENGLCONTEXT_HIDDEN=1`` with any windowed one. A hidden window
renders and reads back the same pixels, and :doc:`the test suite <testing>`
uses one by default. A hidden window still needs a display server and a
desktop; the offscreen window systems do not.

Choosing the offscreen window system at run time
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Both are registered on every platform.  ``windowsystem='offscreen'`` asks for
whichever this platform has, so code that runs on several platforms names
neither:

.. code-block:: python

   from OpenGLContext.context import Context
   from OpenGLContext.windowsystem import WindowSystemUnavailable

   try:
       context = Context(windowsystem='offscreen', size=(1920, 1080))
   except WindowSystemUnavailable:
       ...                            # nothing here renders without a window

``WindowSystemUnavailable`` is raised where the platform's offscreen window
system will not load (for example, EGL with no library installed), naming it
and the import error.  :py:func:`OpenGLContext.windowsystem.offscreenName`
returns only the name, ``'egl'`` or ``'wgl'``, for use in a message; pass a
platform name to ask about another platform.

When construction fails
~~~~~~~~~~~~~~~~~~~~~~~

Constructing the context raises ``EGLContextError`` or ``WGLContextError``
when the machine cannot provide one: no devices, no pixel format matching
the requested buffers, no desktop GL, or a driver without pbuffers. Catch the
error to fall back to something else. A failed construction releases
everything it had acquired, so an application can retry with another device
or a smaller request without leaking resources.

On Windows, ``OpenGLContext.windowsystem.wgl.available()`` checks before
creating anything. It returns the names of the extensions the driver lacks, or an
empty sequence.

Choosing a GPU (EGL)
--------------------

A machine may offer several EGL devices: a GPU and a CPU rasteriser, or
several GPUs. By default the engine renders on the first hardware device.
``OpenGL.EGL.devices`` lists the devices:

.. code-block:: python

   >>> from OpenGL.EGL import devices
   >>> for device in devices.devices():
   ...     print(device)
   <DeviceInfo 0 radeonsi (hardware)>
   <DeviceInfo 1 <unnamed driver> (software)>

Two settings change the choice:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Effect
   * - ``OPENGLCONTEXT_EGL_DEVICE``
     - An index into that list. It overrides everything else; use it to pin a
       run to one of several GPUs. An index that is out of range or not a
       number raises an error naming the variable.
   * - ``LIBGL_ALWAYS_SOFTWARE``, ``GALLIUM_DRIVER``
     - When either requests software rendering, the engine picks a software
       device.

The engine follows a software-rendering request because Mesa crashes
otherwise. If ``LIBGL_ALWAYS_SOFTWARE`` is set and a display is opened on a
*hardware* device, Mesa prints a warning and then segfaults.

If no device of the preferred kind exists, the engine uses the first device
and logs a warning.

The helper window (Windows)
---------------------------

Windows has no device list to choose from and no call that creates a context
without a window. The functions that create a pbuffer
(``wglChoosePixelFormatARB``, ``wglCreatePbufferARB`` and
``wglCreateContextAttribsARB``) are extensions, and extension entry points
can only be looked up through an existing context. To get one,
``OpenGL.WGL.offscreen`` creates a 1×1 ``WS_POPUP`` window per process. The
window is never shown and has no message loop; it is used only to look up
those entry points. The pbuffer outlives it.

This needs a window station and a desktop, but nothing on screen. The
pbuffer lives in driver memory, so it survives a remote-desktop disconnect
that would destroy a window. In the one case where Windows discards a
pbuffer's contents, ``context.surface.lost`` is true; draw the frame again.

The pbuffer is created on the display driver bound to the process, with a
pixel format the GPU draws in hardware. Set
``OPENGLCONTEXT_WGL_ANY_ACCELERATION=1`` to accept a pixel format that does
not report full acceleration. An unusual or virtualised adapter may need
this; it renders more slowly instead of failing.

Finishing a frame
-----------------

A pbuffer has no display to present to, so ``SwapBuffers`` on an offscreen
context is a flush. After it, the frame's commands have been issued to the
driver, which a following readback, capture or video encode relies on. The
passes call ``SwapBuffers`` where they would on a window.

The flush is not done with ``eglSwapBuffers``. The EGL specification gives
``eglSwapBuffers`` no effect on a surface that is not a back-buffered window,
so on a pbuffer it returns ``EGL_TRUE`` and does nothing.

The surface is single-buffered, so the finished frame is in the *front*
buffer, not the back buffer. Every capture path in the engine calls
``OpenGLContext.capture.presented_buffer`` to find the buffer the framebuffer
has, rather than naming ``GL_BACK``. Reading a buffer the framebuffer does
not have raises ``GL_INVALID_OPERATION``.

Resizing
--------

A pbuffer has a fixed size. ``OnResize`` creates a new pbuffer with the same
config or pixel format and releases the old one. The GL context is kept, so
textures, buffers and programs remain. A width or height of zero or less
raises an error.

Driving a scene without user input
----------------------------------

An offscreen context has the camera, the event managers and the time
manager of an interactive context, but nothing delivers key presses or
clicks to it. To test what happens when a user picks an object or walks
forward, create the events with ``OpenGLContext.events.synthetic``, using
the record format of :doc:`the event model <eventmodel>`:

.. code-block:: python

   from OpenGLContext.events import synthetic

   synthetic.dispatch(context, {'type': 'keyboard', 'key': 'w', 'state': 1})
   context.OnDraw(force=1)
   synthetic.dispatch(context, {'type': 'keyboard', 'key': 'w', 'state': 0})

   synthetic.dispatch(context, {
       'type': 'mousebutton', 'button': 0, 'state': 1,
       'x': 160, 'y': 120, 'pick': True,
   })
   context.OnDraw(force=1)     # a picked event arrives with the pass

A :doc:`telemetry <telemetry>` recording and its replay use the same record
format, as does the out-of-process event injector, so a script written for
one works with the others.

The ``pick`` flag chooses how the event is delivered:

- With ``pick``, the event goes to the selection pass and is delivered after
  the pass has found what is under the cursor, as a real click is. This
  needs a render.
- Without ``pick``, the event goes straight to its event manager and reaches
  only context-level handlers. No render is needed.

Pick readback is asynchronous by default (``pickAsync``). A picked event is
delivered a frame or so after the draw that scheduled it, and the number of
frames depends on how busy the machine is. To act on the click before
continuing, call ``flushPendingPicks()``:

.. code-block:: python

   context.OnDraw(force=1)          # the frame that takes the event
   context.flushPendingPicks()      # the click has been delivered by here

``flushPendingPicks`` waits for the readbacks still in flight and returns
how many it waited for. A readback that completed during the frame counts as
zero but is still delivered: an event dispatched while the context is
drawing goes onto the event cascade queue, and the flush empties that queue
as the next frame would. The call blocks. A loop that can handle the click
whenever it arrives should keep drawing instead.

Time
----

The time manager runs as usual, so ``TimeSensor`` and ``Timer`` drive
animation offscreen as they do on screen. A bounded run advances the
engine's clock by a fixed step per frame (``OPENGLCONTEXT_CAPTURE_FPS``), so
a rendered sequence reaches the same point on every machine. See
:doc:`Environment variables <environment>`.
