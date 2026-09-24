Capturing the Render
====================

.. rst-class:: introduction

A program built on OpenGLContext can keep what it draws in three ways: a
screenshot taken with a key, a single settled frame written to a PNG by
``oglc-view`` or by your own code, and an H.264 video recorded on the GPU's
own encoder. All three read the frame at the same point, just before it is
shown.

.. _present:

Presenting a frame, and reading it
----------------------------------

A render pass finishes a frame by calling ``Context.presentFrame``. This is
the last point at which the frame can be read: ``SwapBuffers`` gives the back
buffer to the driver, which reuses it, so a read after the swap returns an
older frame. A screenshot, a still capture or a recording reads the frame in
``presentFrame``.

.. code-block:: python

   def presentFrame(self):
       self.tickRecording()              # before the swap: this is the frame
       return super().presentFrame()

``SwapBuffers`` is the method each GUI backend implements to display the
buffer. Override ``presentFrame`` for work that belongs to the frame, and
override ``SwapBuffers`` only when writing a backend.

.. _screenshots:

The screenshot key
------------------

Every context binds ``F2`` (and ``Alt+S``) to ``requestScreenshot``, so every
program built on OpenGLContext has a screenshot key without configuration.
Pressing the key sets a flag and requests a redraw; the picture is taken in
``presentFrame``. The redraw makes the key work on a still scene, which would
otherwise draw no further frames.

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
   * - ``requestScreenshot()``
     - Saves the next frame, as the key does. Call it from a menu item or a
       button of your own.
   * - ``OnSaveImage()``
     - Saves the current back buffer immediately and returns its width and
       height. Call it from ``presentFrame``, or pass ``template=`` to write a
       named file.

.. _still-capture:

One settled frame from the viewer
---------------------------------

``oglc-view`` renders a scene, waits for it to settle, writes a PNG and exits:

.. code-block:: bash

   oglc-view model.glb --capture-image shot.png --size 1100x680
   oglc-view model.glb --camera aerial --capture-image shot.png --capture-delay 0.5

It waits ``--capture-delay`` seconds (default 0.5) and at least ``--frames``
frames (default 10), so lighting that adapts over several frames has
converged. The capture renders in a hidden window with vsync off, and the
window size is the size of the picture. The same capture is the ``capture``
field of ``ViewerOptions``, for a viewer of your own. :ref:`Capturing a frame
<capture>` on the viewer page lists the options.

One settled frame from your own code
------------------------------------

``OpenGLContext.capture`` reads the back buffer and writes a PNG.
``capture_to_png( path )`` saves the current frame; ``SettleCapture`` waits
for a scene to settle first. Call either from ``presentFrame``:

.. code-block:: python

   from OpenGLContext.capture import SettleCapture

   class MyContext( BaseContext ):
       def OnInit( self ):
           self.still = SettleCapture( 'shot.png', delay=0.5, min_frames=10 )

       def presentFrame( self ):
           if self.still.tick():         # True once it has written the file
               self.OnQuit()
           return super().presentFrame()

       def OnIdle( self, event=None ):
           self.triggerRedraw( 1 )       # a still scene draws no more frames by itself

``delay`` is a minimum in seconds and ``min_frames`` a minimum in frames;
the capture waits for whichever is longer. A context draws only when
something changes, so ``OnIdle`` asks for the frames the capture counts. ``capture_to_png`` skips an
all-black frame unless ``skip_blank=False`` is passed, and returns whether it
wrote a file.

A test that compares what was drawn against a reference image uses the same
reads through the test machinery; see :ref:`Comparing pixels <pixels>`.

Recording video
---------------

``pyopengl-video`` encodes the frames a context draws to an H.264 file on the
GPU's own video encoder. Each frame is copied into a texture that the encoder
reads in place, so only the compressed video leaves the graphics card. It is
an optional extra:

.. code-block:: bash

   pip install "OpenGLContext[video]"

The encoder is part of the graphics driver: NVENC on NVIDIA under Linux,
VA-API on AMD (and Intel) under Linux, and oneVPL on Intel under Windows. On a
machine without one, a request to record reports what is missing and the
program carries on.

The viewer records any scene it opens, moving the camera along the scene's
own viewpoints or turning the model:

.. code-block:: bash

   oglc-view world.glb --capture-video walk.mp4 --fly-through
   oglc-view model.glb --capture-video spin.mp4 --turntable --video-seconds 8

A context of your own records by mixing in ``RecordingMixin`` and calling
``tickRecording()`` from ``presentFrame``:

.. code-block:: python

   from OpenGLContext.video.recorder import RecordingMixin

   class MyContext( RecordingMixin, BaseContext ):
       def OnInit( self ):
           self.setupRecording( 'run.mp4', fps=60, seconds=20 )

       def presentFrame( self ):
           self.tickRecording()          # before the swap
           return super().presentFrame()

By default the recorder advances the engine's clock by exactly one frame for
each frame it writes, so the video plays smoothly however long each frame took
to draw. :doc:`Recording video <recording>` covers the supported GPUs, the
recording options, the clock and handling a machine with no encoder.
