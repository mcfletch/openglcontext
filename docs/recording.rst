Recording video
===============

.. rst-class:: introduction

A **recorder** writes the frames a context draws to an H.264 video file. Each
frame is copied from the framebuffer into a texture that the GPU's video
encoder reads in place, so only the compressed video crosses the bus. By
default the world advances by exactly one frame's worth of time for each
frame written. A recording is therefore smooth however long each frame took
to draw, and the same run records the same way twice.

.. _installing:

What it needs
-------------

Recording needs the ``video`` extra, which installs `pyopengl-video
<https://github.com/mcfletch/pyopengl-video>`__, the bindings to the video
encoder in the graphics driver:

.. code-block:: bash

   pip install OpenGLContext[video]

The encoder is part of the graphics driver, so nothing else has to be
installed. These GPUs and platforms have an encoder pyopengl-video can use:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - GPU
     - Platform
     - Encoder interface
   * - NVIDIA
     - Linux
     - NVENC
   * - AMD
     - Linux
     - VA-API; needs an EGL context
   * - Intel
     - Windows
     - oneVPL
   * - Intel
     - Linux
     - VA-API, the same code as AMD; untested

The VA-API path exports the frame through EGL, so the context must be an EGL
context: the :doc:`egl offscreen backend <offscreen>`, or GLFW on Wayland.
GLFW on X11 makes a GLX context by default, which this path cannot record
from. It also needs the VA-API driver for the GPU (``mesa-va-drivers`` for AMD,
``intel-media-va-driver`` for Intel). The pyopengl-video README has the
details.

On a machine without a usable encoder, the program runs normally, and a
request to record reports what is missing rather than failing partway
through. Without the ``video`` extra nothing changes at all: the recorder is
imported only when a recording is requested.

On a machine with more than one GPU, the encoder must be on the GPU the
renderer uses, because it reads the frame from that GPU's memory. The
recorder picks an encoder on the context's own adapter. On a laptop that runs
OpenGL on its integrated graphics, that is the integrated GPU's encoder.

.. _recording:

Recording from the viewer
-------------------------

No code is needed: :doc:`oglc-view <viewer>` can record any scene it can
open.

.. code-block:: bash

   oglc-view world.glb --capture-video walk.mp4 --fly-through
   oglc-view model.glb --capture-video spin.mp4 --turntable --video-seconds 8
   oglc-view model.glb --capture-image shot.png

A recording needs something to move, and a file opened in a viewer has no
camera path of its own. ``--fly-through`` builds one from the scene's own
viewpoints: it visits them in the order the file declares them, easing in and
out of each leg. A world with two viewpoints in it is enough for a shot. The
path advances by recorded frames rather than by wall time, so it lasts as
long as the video however fast the machine draws. ``--turntable`` rotates the
model instead. ``--video-seconds`` sets the length (default 12) and
``--video-fps`` the frame rate (default 30).

A recorded frame has no caption and no developer overlay, the same as a
screenshot. See :ref:`Recording a video <video>` on the viewer page.

.. _recording-context:

Recording from a context
------------------------

``RecordingMixin`` adds recording to a context. Set the recording up, call
``tickRecording()`` from :ref:`presentFrame <present>`, and the mixin closes
the file when the recording reaches its length:

.. code-block:: python

   from OpenGLContext.video.recorder import RecordingMixin

   class MyContext(RecordingMixin, BaseContext):
       def OnInit(self):
           self.setupRecording('run.mp4', fps=60, seconds=20)

       def presentFrame(self):
           self.tickRecording()          # before the swap
           return super().presentFrame()

**Call it before the swap.** The back buffer holds the frame just drawn only
until it is swapped. The :ref:`still capture <stills>` follows the same rule.

A complete program also handles a machine with no encoder, and asks for a new
frame every time round the loop:

.. code-block:: python

   from OpenGLContext import testingcontext
   from OpenGLContext.video.recorder import RecordingMixin, RecordingUnavailable

   BaseContext = testingcontext.getInteractive('glfw')


   class RecordedContext(RecordingMixin, BaseContext):
       def OnInit(self):
           # 90 frames at 30 fps: three seconds of video, and the run ends there
           self.setupRecording('run.mp4', fps=30, frames=90)

       def presentFrame(self):
           try:
               self.tickRecording()            # before the swap
           except RecordingUnavailable as error:
               self.recorder = None            # nothing here can encode
               print('not recording: %s' % (error,))
           return super().presentFrame()

       def OnIdle(self, event=None):
           self.triggerRedraw(1)               # a recording wants every frame


   if __name__ == "__main__":
       RecordedContext.ContextMainLoop()

``RecordingUnavailable`` is raised at the first frame the recording would
have kept, because that is when the encoder is opened. Setting
``self.recorder`` to None stops the next frame from trying again; the context
keeps drawing, and everything except the recording works as usual.

``OnIdle`` is there because a context normally draws only when something
changes. A recording needs a frame every time round the loop, so an
application whose scene may stay still requests one.

A context that manages the recorder itself can use it directly:

.. code-block:: python

   from OpenGLContext.video.recorder import VideoRecorder

   recorder = VideoRecorder('run.mp4', fps=60, seconds=20)
   ...
   recorder.capture()          # in presentFrame, before the swap
   ...
   recorder.close()

``capture()`` returns whether it kept the frame. ``recorder.recording`` says
whether the recorder still wants more frames. The two differ: a recorder
waiting for ``start_after`` to pass keeps no frame but is not finished.

.. _recording-settings:

Recording options
-----------------

These are the arguments of ``setupRecording()`` and ``VideoRecorder``:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Argument
     - Default
     - Meaning
   * - ``fps``
     - 60
     - Frames per second, as a number or an exact ``(numerator, denominator)``
       pair. Use the pair for rates such as 29.97, so a long recording does
       not drift.
   * - ``size``
     - the viewport
     - The recording keeps the size it starts at. If the window is resized
       later, frames are scaled to fit.
   * - ``seconds`` / ``frames``
     - until closed
     - How long to record.
   * - ``start_after``
     - 0
     - Seconds of real time to wait before the first frame is kept. A world
       that streams its content in arrives over the first few seconds; without
       a wait, the recording shows it arriving.
   * - ``fixed_step``
     - True
     - Advance the engine's clock by one frame per frame recorded. See
       :ref:`recording-clock`.
   * - anything else
     -
     - Passed to the encoder: ``bitrate``, ``preset``, ``tuning``, ``gop``,
       ``bframes``.

.. _recording-clock:

The clock a recording runs on
-----------------------------

Drawing a frame takes as long as it takes. A scene recorded against the wall
clock plays back unevenly: a frame that took 40 ms to draw shows 40 ms of
movement in a 16 ms video frame, and a scene that streams in its content
stutters wherever the streaming happened.

So by default a recorder installs a ``FixedStepClock`` and advances it one
frame for each frame recorded. Everything time-driven follows, because
everything reads one clock. A ``Timer`` polls
``OpenGLContext.events.systemtime.systemTime()``, so every ``TimeSensor``, and
every animation they drive, advances with it.

.. code-block:: python

   from OpenGLContext.video.clock import FixedStepClock

   with FixedStepClock(fps=60) as clock:
       while recording:
           render()
           clock.advance()

Code that reads ``time.time()`` directly does not follow the recorder's
clock. Read ``systemTime()`` instead, and that code's motion is recorded as
evenly as the scenegraph's.

A fixed step means the run is not in real time: a heavy frame takes as long
as it needs, and the world waits for it. That suits a recording, but not a
game someone is playing. To record an interactive session as it happened,
including its stalls, pass ``fixed_step=False`` to use the wall clock.

Screen captures use the same clock for a different reason: a frame read back
after a fixed number of draws should show the same moment of the scene on any
machine. ``capture_clock()`` sets this up, and the context installs it when
``OPENGLCONTEXT_AUTO_EXIT_FRAMES`` requests a bounded run. See
:ref:`Testing <pixels>`.

.. _recording-demo:

Seeing it work
--------------

.. figure:: images/demos/recording_demo.jpg
   :alt: Eight coloured blocks ride a carousel around a white sphere on a grey floor, each casting a shadow, and a red lamp burns above and to the left

   :doc:`python tests/recording_demo.py <tutorials/recording_demo>` - eight
   blocks turning and bobbing around a sphere. Every frame differs from the
   last, so an unevenly clocked recording of it shows a stutter. Press ``r``
   to start recording and again to stop and close the file; the lamp is red
   while a recording is running. Press ``c`` to make the next recording use
   the wall clock instead of a fixed step.

``--record`` records without the keyboard, for scripted runs: the demo
records that many frames, prints what it wrote, and exits.

.. code-block:: bash

   $ python tests/recording_demo.py --record 90
   recording to recording_demo.mp4 at 30 fps, 90 frames
   recorded 90 frames to recording_demo.mp4
     picture     300x300
     frame rate  30/1 fps (3.000 seconds of video)
     clock       fixed step
     file size   81983 bytes

The ``clock`` line says which time source the recording used, and the frame
rate is the spacing the frames were stamped at. ``--output PATH`` chooses the
file. The environment variables ``OPENGLCONTEXT_RECORD_FRAMES`` and
``OPENGLCONTEXT_RECORD_PATH`` set the same two things for the demo.

.. _orientation:

Turning the frame the right way up
----------------------------------

OpenGL's framebuffer starts at the bottom left, while a video encoder treats
a texture's first row as the top of the picture. The copy into the capture
texture reverses its destination Y coordinates, so the frame is turned over
during the blit at no extra cost. That copy is ``copy_frame()``, and it is
public, for an application that encodes by some other route and needs the
same copy.

.. code-block:: python

   from OpenGLContext.video.recorder import CaptureTarget, copy_frame

   target = CaptureTarget(width, height)
   copy_frame(target.framebuffer, (width, height))   # target.texture now holds the frame

``CaptureTarget`` is for code doing its own capture. A recording gets its
textures from the *encoder* instead, because on Windows the encoder reads a
Direct3D surface and only the encoder backend can create one. The copy into
that surface happens inside a ``for_drawing()`` scope, which passes the
surface between the two graphics APIs where that is needed and does nothing
elsewhere.

.. _stills:

Stills
------

A single frame is a separate job. ``OpenGLContext.capture`` reads the back
buffer and writes a PNG, and ``SettleCapture`` waits for a scene to settle
before it takes one. Use a recording for motion and a still capture for a
picture. See :ref:`screenshots` and :ref:`pixels`.

.. _recording-limits:

Limits
------

- H.264 only, up to 4096×4096, in an MP4 file.

- Supported encoders - NVIDIA and AMD on Linux, and Intel on Windows; Intel on
  Linux uses the AMD code path and is untested. NVIDIA and AMD on Windows are
  not supported. See :ref:`installing`.

- One GPU per recording - the encoder reads the frame where the renderer left
  it, so the two must be on the same adapter.

- No audio - the file has a video track only.

- The recording belongs to the OpenGL context that started it, and every
  frame must come from that context's thread.
