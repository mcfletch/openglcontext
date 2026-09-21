Rendering offscreen
===================

.. rst-class:: introduction

A build machine has no screen, a rendering service has no user, and a batch
job that turns ten thousand models into ten thousand thumbnails has no reason
to open a window for any of them. An offscreen context renders without one: it
takes a GPU directly, draws, and gives the pixels back. There is one per
platform — ``OpenGLContext.eglcontext.EGLContext`` on Linux and
``OpenGLContext.wglcontext.WGLContext`` on Windows — and they behave the same
way.

A context like any other
------------------------

It is an ordinary context, so the scenegraph, the render passes, the caches,
the screenshot machinery, the :doc:`video recorder <recording>` and the event
model all work unchanged:

.. code-block:: python

   from OpenGL.GL import GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor
   from OpenGLContext.eglcontext import EGLContext        # Linux
   # from OpenGLContext.wglcontext import WGLContext      # Windows

   class Offscreen(EGLContext):
       def Render(self, mode=None):
           EGLContext.Render(self, mode)
           glClearColor(0.2, 0.3, 0.3, 1.0)
           glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

   Offscreen.ContextMainLoop(size=(640, 480))

``MainLoop`` renders ``frameCount`` frames (one by default) and returns,
rather than waiting for a user who is not there. An animation being rendered
frame by frame sets it higher. The context is also a context manager, which is
usually what a script wants:

.. code-block:: python

   with Offscreen(size=(640, 480)) as context:
       context.OnDraw(force=1)
       pixels = glReadPixels(0, 0, 640, 480, GL_RGB, GL_UNSIGNED_BYTE)

Selecting it by name works too, so an application that already chooses its
backend needs no code change:

.. code-block:: bash

   OPENGLCONTEXT_BACKEND=egl python my_application.py     # Linux
   OPENGLCONTEXT_BACKEND=wgl python my_application.py     # Windows

Rendering goes to a pbuffer, which is a real default framebuffer. Every pass
that draws to framebuffer zero, reads it back or takes a screenshot behaves
exactly as it does on a window, and nothing has to know it is offscreen. A
pbuffer has a fixed size, so ``OnResize`` builds a replacement and drops the
old one; the GL context survives, and the textures, buffers and programs in it
survive with it.

Which backend a platform has
----------------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Platform
     - Backend
     - What it needs
   * - Linux
     - ``egl`` — ``OpenGLContext.eglcontext``
     - An EGL device. No display server, no compositor, no session.
   * - Windows
     - ``wgl`` — ``OpenGLContext.wglcontext``
     - A display driver offering ``WGL_ARB_pbuffer``, and a window station with a
       desktop — which a service in session 0 has. Nothing on screen, no compositor,
       and no remote-desktop connection that stays open.
   * - macOS
     - —
     - CGL gives a windowless context (``OpenGL.CGL``) but no default framebuffer, so
       there is no OpenGLContext backend on it yet. Use a hidden window.

**Where there is none, a hidden window is the fallback.**
``OPENGLCONTEXT_HIDDEN=1`` on any windowing backend renders and reads back
identically, and is what :doc:`the test suite <testing>` uses by default. What
a hidden window cannot do is run with no display server or no desktop at all,
which is the thing these backends are for.

Where the platform cannot provide one, constructing the context raises
``EGLContextError`` or ``WGLContextError`` rather than failing obscurely, so
an application can try it and fall back. On Windows,
``OpenGLContext.wglcontext.available()`` answers before anything is created,
naming the extensions the driver lacks.

Asking for whichever one is here
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Both backends are registered on every platform, so code that runs on more than
one asks for the offscreen context rather than naming a class:

.. code-block:: python

   from OpenGLContext.context import Context

   offscreen = Context.getOffscreenContextType()
   if offscreen is None:
       ...                            # nothing here renders without a window
   context = offscreen(size=(1920, 1080))

``None`` covers both ways of not having one: a platform with no backend, and a
backend whose bindings will not load — an EGL with no library behind it, say.
For the caller those are the same answer, and the decision after it is the
same one. ``Context.getOffscreenBackendName()`` gives the name alone
(``'egl'`` or ``'wgl'``) for a caller that wants to say which in a message,
and takes a platform to ask about another machine.

Which GPU it renders on (EGL)
-----------------------------

A machine may offer several EGL devices — a GPU and a CPU rasteriser, or
several GPUs. By default the engine renders on the first hardware device.
``OpenGL.EGL.devices`` reports what is there:

.. code-block:: python

   >>> from OpenGL.EGL import devices
   >>> for device in devices.devices():
   ...     print(device)
   <DeviceInfo 0 radeonsi (hardware)>
   <DeviceInfo 1 <unnamed driver> (software)>

Two things change the choice:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Variable
     - Effect
   * - ``OPENGLCONTEXT_EGL_DEVICE``
     - An index into that list, which overrides everything else. Use it to pin a run
       to one GPU of several. An index that is out of range, or not a number, is an
       error naming the variable rather than a silent fallback.
   * - ``LIBGL_ALWAYS_SOFTWARE``, ``GALLIUM_DRIVER``
     - When the environment asks for software rendering, a software device is chosen.

A request for software rendering is honoured because Mesa crashes
otherwise: asking it for a display on a *hardware* device while
``LIBGL_ALWAYS_SOFTWARE`` demands software is a contradiction it detects,
warns about, and then segfaults on rather than refusing cleanly.

Where no device of the preferred kind exists, the first device is used and a
warning says so: rendering on the other sort beats not rendering.

One window, created and never shown (Windows)
---------------------------------------------

Windows has no device enumeration to choose from and no windowless context
call. The calls that build a pbuffer — ``wglChoosePixelFormatARB``,
``wglCreatePbufferARB``, ``wglCreateContextAttribsARB`` — are extensions, and
an extension entry point is resolved through a context that already exists, so
there is a chicken and egg. The way out of it is a 1×1 ``WS_POPUP`` window,
never shown and never given a message loop, used for nothing but resolving
those entry points. ``OpenGL.WGL.offscreen`` makes one per process and the
pbuffer outlives it.

What that needs is a window station and a desktop; what it does not need is
anything on screen. The pbuffer is the driver's own memory, so it survives a
remote-desktop disconnect that would take a window with it —
``context.surface.lost`` reports the one case where Windows discards what a
pbuffer held, and the answer to that is to draw the frame again.

The pbuffer is created on the display driver bound to the process, and the
pixel format is required to be one the GPU draws.
``OPENGLCONTEXT_WGL_ANY_ACCELERATION=1`` accepts one that does not call itself
fully accelerated, which is what an unusual or virtualised adapter may need:
rendering slowly beats refusing.

Driving a scene with no one at the keyboard
-------------------------------------------

An offscreen context is still an interactive one — it has the camera, the
event managers and the time manager — but nothing outside it will ever deliver
a keystroke or a click. A test that wants to know what happens when the user
picks an object or walks forward supplies the events itself, through :doc:`the
event model <eventmodel>`'s record vocabulary:

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

That is the same vocabulary a telemetry recording writes and its replay reads,
and the same one the out-of-process event injector speaks, so a script written
for one drives the others. The ``pick`` flag chooses the route: with it the
event goes to the selection pass and is delivered once the buffer has resolved
what is under the cursor, which is what a real click does and which needs a
render; without it the event goes straight to its manager, reaching
context-level handlers only, which needs no render at all.

The pick readback is asynchronous by default (``pickAsync``), so a picked
event is resolved a frame or so after the draw that scheduled it rather than
within it. How many frames that takes is a property of how busy the machine
is, so a caller that has to act on the click before it goes on asks for it
rather than drawing on and hoping:

.. code-block:: python

   context.OnDraw(force=1)          # the frame that takes the event
   context.flushPendingPicks()      # the click has been delivered by here

``flushPendingPicks`` waits for the readbacks still in flight and returns how
many it waited for. A readback that landed *during* the frame counts zero and
is delivered all the same: an event dispatched while the context is drawing
goes on the event cascade queue rather than to its handler, and the flush
empties that queue as the next frame would. It blocks, which is the cost of
asking; a loop that is happy to hear about the click whenever it arrives
should simply keep drawing.

Finishing a frame
-----------------

A pbuffer has nothing to present to, so ``SwapBuffers`` is a flush: the point
at which the frame's commands are guaranteed to have been issued to the
driver, which is what a readback, a capture or an encode after it depends on.
Every pass calls it where it would on a window, so nothing has to know.

``eglSwapBuffers`` is not what does it. The EGL specification gives it no
effect on any surface that is not a back-buffered window, so on a pbuffer it
returns ``EGL_TRUE`` and issues nothing.

The surface is single-buffered, since nothing presents it, so the finished
frame is in the *front* buffer rather than the back one. Every capture path
here asks the framebuffer which it has
(``OpenGLContext.capture.presented_buffer``) rather than naming ``GL_BACK``,
because naming a buffer a framebuffer does not have is
``GL_INVALID_OPERATION`` and not a quiet fallback.

Resizing
--------

A pbuffer is created at a fixed size and cannot be resized, so ``OnResize``
builds a replacement against the same config or pixel format and drops the old
one. The GL context survives, so textures, buffers and programs are all still
there afterwards. A width or a height of zero or less is not a surface and is
refused by name.

When construction fails
-----------------------

Constructing the context raises ``EGLContextError`` or ``WGLContextError``
where this machine cannot provide one — no devices, no pixel format matching
the buffers asked for, no desktop GL, a driver with no pbuffers — so an
application can try it and fall back. A failure gives back whatever it had
already taken, so an application that tries several devices or reduces its
request and tries again leaks nothing per attempt.

Time
----

The time manager runs as usual, so ``TimeSensor`` and ``Timer`` drive
animation offscreen exactly as they do on screen. A bounded run puts the
engine's clock on a fixed step (``OPENGLCONTEXT_CAPTURE_FPS``), so a sequence
rendered here reaches the same point on every machine — see :doc:`Environment
Variables <environment>`.
