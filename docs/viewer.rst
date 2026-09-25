The viewer
==========

.. rst-class:: introduction

``oglc-view`` opens a 3D scene and renders it with the :doc:`core-profile PBR
renderer <pbr>`. You can look around the scene or walk through it. It opens
glTF models, VRML97 worlds, Wavefront OBJ files and streamed 3D Tiles
datasets. The viewer identifies the format from the source itself, so one
command opens all of them.

Run it with no arguments to get its menu. The menu offers a :ref:`library
<library>` of sample models and worlds, shown by preview pictures, and a box
for typing a path or URL. The viewer is also a reusable class: see
:ref:`Embedding the viewer <viewer-embedding>`.

.. _opening:

Opening a scene
---------------

.. code-block:: bash

   oglc-view                       # the launch menu and the library
   oglc-view path/to/model.glb
   oglc-view path/to/world.wrl
   oglc-view path/to/model.obj
   oglc-view path/to/tileset.json
   oglc-view https://example.com/model.glb
   oglc-view --pack openglcontext/gallery
   GLTF=path/to/model.gltf oglc-view

The viewer turns on the core profile, the PBR renderer, the GLFW backend and
shadows itself. No environment variables are needed.

``--pack KEY`` opens a :doc:`content pack <contentpacks>` the engine publishes
(``OpenGLContext/packs.json``): ``openglcontext/gallery`` is the
:ref:`level-of-detail demo world <lod-demo>`. The first run prints the pack's
title, size and terms and fetches it into the engine's content store, checked
against its digest; later runs open it from there without a download.

Supported formats
~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Source
     - Adapter
     - Description
   * - ``.gltf`` ``.glb``
     - ``gltf``
     - A glTF 2.0 *model*: centred and framed, with its own cameras and animations.
       See :doc:`Loading glTF <gltf>`.
   * - ``.wrl`` ``.wrz`` ``.vrml`` ``.wrl.gz``
     - ``vrml97``
     - A VRML97 *world*: shown where it was authored, with its own sky, lights
       and ``Viewpoint`` nodes. See :doc:`VRML97 <vrml97>`.
   * - ``.obj``
     - ``obj``
     - A Wavefront model. OBJ has no lights, cameras or sky, so the viewer
       supplies all three.
   * - ``tileset.json``, or any JSON with both ``asset`` and ``root``
     - ``tiles3d``
     - An OGC 3D Tiles dataset, streamed and refined as you move. See :doc:`Streamed
       3D Tiles <tiles3d>`.

For a source whose path has no suffix, such as ``/download?id=3``, name the
format with ``--format gltf``.

A binary ``.glb`` file is self-contained, so a URL to one works directly. A
text ``.gltf`` file usually refers to separate ``.bin`` and texture files by
URIs relative to the document. The viewer resolves those against the
document's URL, so a remote multi-file model opens with its geometry and
textures. See :doc:`Loading glTF <gltf>`.

.. _viewer-archives:

Archives
~~~~~~~~

A world of several files travels as an archive: a ``.zip``, ``.tar``,
``.tar.gz`` (``.tgz``), ``.tar.bz2`` (``.tbz2``) or ``.tar.xz`` (``.txz``),
as a path or a URL. ``#member`` after it names the scene to open inside:

.. code-block:: bash

   oglc-view world.tar.gz#gallery.glb
   oglc-view https://example.com/world.tar.gz#scenes/gallery.gltf
   oglc-view world.zip                 # holds exactly one scene file

An archive holding exactly one scene file (``.glb``, ``.gltf``, ``.wrl``,
``.wrz``, ``.vrml``, ``.x3d`` or ``.obj``) needs no ``#``. One holding several
is refused with a list of what it holds, and one that holds no such file says
so. The whole archive is unpacked, not only the member, so a ``.gltf``'s
buffers and textures and a level-of-detail chain's sidecars resolve against
the member's own directory.

An archive is unpacked once, into ``<app data>/OpenGLContext/archives/``
under a name taken from its digest, and later openings of the same bytes use
that directory. The extraction is the one :doc:`content packs <contentpacks>`
use: an archive may unpack to no more than 512 MB, a member naming an absolute
path or climbing out of the directory is refused, and the archive is unpacked
beside its directory and renamed into place when complete, so an interrupted
extraction is done again on the next opening. Two viewers opening one archive
take turns. Nothing removes old archives from that directory; deleting it at
any time costs only the next opening's extraction.

A URL to an archive follows a redirect to any public https host, which is how
release hosts such as GitHub serve their assets (see :ref:`Fetching
<fetching>` on the content-packs page).

Streamed datasets take extra options:

- ``--sse`` - the screen-space error target, in pixels. Lower values load more
  detail.
- ``--memory`` - the budget for resident tiles, in MiB.
- ``--no-recenter`` and ``--cache-dir``.

Other formats ignore these options.

Console output
~~~~~~~~~~~~~~

The viewer prints progress to standard output: the file it is opening, the
cameras and lights it found, and the animation it is playing. These lines
contain names from the file and the command line, which can be any Unicode
text. A console can only show the characters its encoding supports; a Windows
console uses a code page of a few hundred characters. The viewer writes any
character the console cannot show as an escape (``❤`` becomes ``\u2764``),
and the model still opens. To see the names as written, set
``PYTHONIOENCODING=utf-8`` and redirect the output to a file.

.. _framing:

Framing a model
~~~~~~~~~~~~~~~

The viewer centres and frames a model that has no camera of its own. The
camera moves back until the model's bounding sphere fills the field of view,
and sits a little above the model, tilted down. ``--margin``, ``--elevation``
and ``--tilt`` (radians, default 0.10) adjust the fit. ``--eye X,Y,Z`` with
``--look-at X,Y,Z`` places the camera explicitly instead.

The bounding sphere is fitted to the model, which is not always everything in
the file. Exported models sometimes contain stray parts far outside the
model, such as a decal left at a hundred times its scale. Framing those as
well would put the model as a speck in the middle of an empty frame. A part
is left out of the fit when both of these are true:

- the file's whole extent is more than four times the extent of the 90% of
  the model that lies closest together, and
- the part lies more than twice as far out as everything nearer than it, with
  empty space in between.

A model that thins out towards its edges fails the second test. A scene made
of two groups far apart fails the first. Neither is cut.

Stray parts are still drawn, and you can walk or fly out to them. They only
do not affect the starting camera. When parts are left out, the viewer prints
how many and how far away they are:

.. code-block:: python

   Framed on the model: 24 part(s) of this file sit up to 102 times its size
   away and start out of view.

The rule is ``OpenGLContext.loaders.gltf.transforms.framing_bounds()``. Its
constants ``STRAY_RATIO`` (4), ``STRAY_CROWD`` (0.9) and ``STRAY_GAP`` (2)
are the numbers above. It applies to glTF sources; other formats frame their
whole extent.

.. _viewer-window:

The window
~~~~~~~~~~

``oglc-view`` opens full screen. The :ref:`developer overlay <hud-debug>`
starts hidden; :kbd:`Alt`+:kbd:`f` shows it.

.. code-block:: bash

   oglc-view model.glb                     # full screen
   oglc-view model.glb --no-fullscreen     # a 1920x1080 window
   oglc-view model.glb --size 1280x720     # a 1280x720 window

``--size WxH`` opens a window of that size, and ``--fullscreen`` fills the
screen whatever the size. Without ``--size`` the window is 1920x1080, which is
also the size the Settings screen returns to when full screen is switched
off. ``OPENGLCONTEXT_FULLSCREEN=0`` makes a window the default; the flags
override it.

A capture or a recording is never full screen. Its window is ``--size``, or
the backend's default of 300x300, because the window size is the resolution
of the file it writes. See :ref:`Capturing a frame <capture>`.

.. _commands:

Deprecated command names
~~~~~~~~~~~~~~~~~~~~~~~~

``oglc-gltf``, ``oglc-vrml`` and ``oglc-tiles`` are deprecated aliases. Each
prints a notice and runs ``oglc-view`` with the same options.

``oglc-vrml`` does not accept ``--shaders`` or ``--no-shaders``. The viewer
always renders through the core-profile PBR pass. To render a world with the
compatibility pipeline, set the profile in the environment:

.. code-block:: bash

   OPENGLCONTEXT_PROFILE=compatibility oglc-view world.wrl

.. _viewer-controls:

Controls
--------

Moving
~~~~~~

- Up / Down - walk forward / back; Left / Right - turn.

- Ctrl+Up / Ctrl+Down - look up / down.

- Alt+Up / Alt+Down - move up / down; Alt+Left / Alt+Right - strafe.

- ``-`` levels the horizon; right-mouse drag orbits.

- ``g`` switches between walking (gravity and collision) and free flight;
  ``f`` toggles flying while walking; ``m`` steps through the declared
  :doc:`movement modes <navigation>`.

.. _orbit:

The orbit pivot
~~~~~~~~~~~~~~~

A right-drag orbits the camera around a pivot point:

- If the click lands on the scene, the pivot is the point clicked.
- A click on empty space still gives a world point, on the far plane. The
  viewer only uses a picked point within 1.5 times the scene's
  bounding-sphere radius of its centre.
- Otherwise, when the camera is outside the middle of the scene, the pivot
  is the centre of the scene's bounding sphere.
- When the camera is within a quarter of the radius of the centre, as when
  walking through a building, the pivot is a point ahead of the camera at
  half the scene's radius. Orbiting the far wall would swing the camera
  around the room.
- With nothing loaded, the pivot is 10 units ahead of the camera.

The rotation is proportional to how far the pointer moves. A drag the height
of the window turns the view half a turn, and horizontal drags turn at the
same rate. The distance to the pivot stays the same throughout the drag.

The scene
~~~~~~~~~

- PgUp / PgDn (or ``p`` / ``n``) - the scene's own cameras.

- Ctrl + PgUp / PgDn - the previous / next entry in the :ref:`library
  <library>` category the scene was opened from. This does nothing for a
  file named on the command line or an address typed in, since those are not
  part of a list.

- ``k`` pauses the animation; ``[`` and ``]`` switch between animations.

- ``t`` starts and stops the turntable.

- ``v`` switches between one view of the scene and four: the plan, the front
  and left elevations, and the camera. ``--views quad`` opens with four. See
  :doc:`multiview`.

These keys act once, when the key is released. A held key repeats about
twenty times a second, which would load twenty models or skip twenty cameras.

The keys are listed in ``SceneViewerMixin.viewerKeys``, a table of
``KeyBinding(name, method, description, modifiers, state)``. To add a key in
a subclass, extend that table rather than overriding ``setupCallbacks``. The
description is the text shown in key listings. Modifiers are ``(shift,
control, alt)``, in that order. The :doc:`navigation <navigation>` commands
are a separate set, rebound in the ``F6`` controls screen.

Screens
~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Key
     - Opens
   * - ``F1``
     - The :ref:`library <library>`.
   * - ``F10``
     - :doc:`Settings <overlayui>`, the same page as in every other program
       built on OpenGLContext.
   * - ``F6``
     - Controls: rebind any key.
   * - ``F2``
     - Saves a screenshot: a PNG in the user's pictures folder, named after the
       window title. Every context binds this key; see :ref:`the screenshot
       key <screenshots>`.
   * - ``Escape``
     - The menu, with **Resume** first and Quit below it. Escape does not quit
       on its own, so a loaded world is not lost by accident. Press Escape
       again to resume.
   * - ``Alt+F``
     - The :ref:`developer overlay <hud-debug>`, hidden when the viewer
       opens. The viewer adds a **Scene** section to it: the source, the adapter that read it, the radius used
       for framing, the bound camera, the animation and the movement mode.

``twig-bb`` uses the same keys.

Every screen works from the keyboard alone. The up and down arrows, or Tab
and Shift-Tab, move between items. Space or Return presses the focused item,
Return presses the screen's primary action, and Escape leaves the screen.

.. _library:

The library
-----------

Run ``oglc-view`` with no source and it opens a menu. From there, the library
shows sample models and worlds by their preview pictures, so you can see a
sample before opening it.

The library is built from the demo table the reference captures use
(``OpenGLContext.loaders.gltf_demos``). Each model is shown the same way in
both: the direction it faces, the backdrop its materials need, and whether it
is meant to be walked. The shelves are:

- Models
- Materials - metals and glass, which need an environment to reflect.
- Scenes - models with authored cameras, or interiors.
- Local builds
- Feature tests - most of the Khronos sample set: entries that each
  exercise one glTF feature (a bare triangle, a sparse accessor, the
  ``Compare*`` grids) rather than being something to look at. The same field
  in the demo table sets ``oglc-gltf-demo``'s browsing order.

OpenGLContext ships no worlds, so there is no **Worlds** shelf until an
application adds one. ``tests/wrls`` holds test data, not content.
``world_entries()`` turns a directory of world files into library entries.

The preview pictures are the Khronos reference screenshots. They are fetched
once and cached on disk. Offline, the library shows no pictures but works
otherwise.

The arrows on the band scroll it. Click a picture to open that entry.

The entry opens in the running window, with a new adapter, scenegraph and
framing; the GL context is kept. Loading runs in the background. When a later
choice replaces a load still in progress, the earlier load is dropped, so it
is safe to click quickly through the shelf.

Adding entries
~~~~~~~~~~~~~~

An application sets its own library by overriding ``viewerLibrary()``:

.. code-block:: python

   from OpenGLContext.viewer import ViewerContext
   from OpenGLContext.viewer.library import Entry, Library, default_library

   class MyViewer( ViewerContext ):
       def viewerLibrary( self ):
           return default_library().extend([
               Entry(
                   name = 'Our product',
                   source = 'https://example.com/product.glb',
                   category = 'Ours',
                   preview = 'https://example.com/product.jpg',
                   note = 'the current revision',
                   options = {'physics': True, 'yaw': 0.4},
               ),
           ])

An entry's ``options`` are ``ViewerOptions`` field names. They apply while
that entry is open and are not carried over to the next one.

Large libraries
~~~~~~~~~~~~~~~

The band shows five entries at a time and wraps around, so a shelf of several
hundred entries lays out as fast as a shelf of three. The ``<<`` and ``>>``
buttons move by five. Pictures are decoded off the render thread and uploaded
a few per frame. The least recently used pictures are dropped once a texel
budget is reached; see ``OpenGLContext.ui.pictures``.

.. _capture:

Capturing a frame
-----------------

.. code-block:: bash

   oglc-view model.glb --capture-image shot.png --size 1100x680
   oglc-view model.glb --camera aerial --capture-image shot.png --capture-delay 0.5
   oglc-view model.glb --list-cameras

``--capture-image`` renders the scene, waits for it to settle, writes the PNG
and exits. ``--capture`` is the same option under another name. The viewer
waits for ``--capture-delay`` seconds (default 0.5) and at least ``--frames``
frames (default 10), so the adaptive analytic-sky IBL has converged. The
captured frame has no caption and no developer overlay.

A capture renders in a hidden window with vsync off. A visible window
throttles the buffer swap to the compositor's frame callback, and a window
that nothing displays never gets one, so the swap would not return. A hidden
window renders and reads back the same pixels. Set ``OPENGLCONTEXT_HIDDEN=0``
to show the window while it captures, for example to see why a capture looks
wrong.

.. _video:

Recording a video
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   oglc-view world.glb --capture-video walk.mp4 --fly-through
   oglc-view world.glb --capture-video spin.mp4 --turntable --video-seconds 8
   oglc-view world.glb --capture-video walk.mp4 --fly-through \
       --video-seconds 16 --video-fps 30 --size 1280x720

``--capture-video`` records the frames the viewer draws to an H.264 file and
exits when the recording is complete. ``--video-seconds`` sets the length
(default 12) and ``--video-fps`` the frame rate (default 30). The encoder is
in the graphics driver and frames stay on the GPU, so recording costs little
more than drawing. Recorded frames have no caption and no developer overlay.

The recording has a fixed number of frames. The clock advances by one frame
at a time while recording, so the video plays at the right speed whatever
frame rate the machine reached. A slow machine takes longer to record, but
the world in the video does not move more slowly.

Give the recording something that moves:

- ``--turntable`` spins the model. Use it for a single object.
- ``--fly-through`` moves the camera along the scene's own viewpoints, in the
  order the file declares them, easing in and out of each leg. The path is
  the one the author placed, so a world with two cameras already makes a
  shot. Use it for a scene too large to see at once. See :ref:`Levels of
  detail <lod-demo>`, where the walk from one end of a hall to a bust at the
  other follows the two cameras in that world. Without a recording it runs
  live, over ``--video-seconds``, from the moment the scene is shown; a scene
  opened afterwards walks its own viewpoints from its start, and the camera
  stays at the last viewpoint when the walk ends.

.. rst-class:: technical

Recording needs `pyopengl-video <https://pypi.org/project/pyopengl-video/>`__,
which ``OpenGLContext[video]`` installs. Without it, ``--capture-video``
reports that the package is missing and does not record. See
:doc:`Recording video <recording>` for recording from your own program.

.. _viewer-embedding:

Embedding the viewer
--------------------

.. rst-class:: technical

This section covers the viewer as a complete program. To use the viewer as
one widget in a Tk, Qt or wx application, with the toolkit running the main
loop, see :doc:`Embedding a view in an application <embedding>`.

The reusable ``OpenGLContext.viewer`` package provides everything the command
does: background loading, the default light rig, auto-framing, the scene's
own cameras and animations, the caption, screenshots, the library and
walking. Subclass ``ViewerContext`` and configure it with ``ViewerOptions``.
No command line is involved:

.. code-block:: python

   from OpenGLContext.viewer import ViewerContext, ViewerOptions

   class MyViewer( ViewerContext ):
       options = ViewerOptions(
           source = 'model.glb',       # a path, a URL, or None for the library
           physics = True,             # walk it, rather than fly around it
           background = 'sky',
       )

   MyViewer.ContextMainLoop()

``ViewerOptions`` is a dataclass holding every viewer setting. The command
line fills in the same object, since ``argparse`` uses one as its namespace,
so each flag and its field share one default. The fields, by group:

- the source and ``format``;
- cameras: ``camera``, ``no_cameras``;
- auto-framing: ``yaw``, ``margin``, ``elevation``, ``tilt``, ``eye``,
  ``look_at``;
- lighting and environment: ``lights``, ``shadows``, ``ibl_intensity``,
  ``environment``, ``background``;
- animation: ``animate``, ``animation``, ``anim_time``, ``turntable``,
  ``no_rotate``;
- ``physics``;
- the window and capture: ``size``, ``fullscreen``, ``capture``,
  ``capture_delay``, ``frames``.

The component opens the window its context class asks for, 300x300 unless
the class says otherwise. ``options.window()`` returns the ``size`` and
``fullscreen`` :ref:`definition fields <fullscreen>` that ``oglc-view`` opens
with (full screen, or 1920x1080), for an application that wants the same::

   MyViewer.ContextMainLoop(**MyViewer.options.window())

The component starts with the developer overlay hidden, by setting the
``debugOverlayStartsVisible`` attribute every context has.

.. _viewer-toolkits:

The viewer on each toolkit
--------------------------

``ViewerContext`` runs on the backend the environment and the user's
configuration choose. ``viewerFor( name )`` returns the viewer class for a
named :doc:`backend <backends>` instead: ``glfw``, ``glut``, ``pygame``,
``tk``, ``qt`` or ``wx``. A backend whose toolkit is not installed raises
``RuntimeError`` naming the ones that are available.

The viewer in a window of its own
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

With the scene filling the window, the program is the same on every backend
but for the name:

.. code-block:: python

   from OpenGLContext.viewer import ViewerOptions, viewerFor

   class MyViewer( viewerFor('glfw') ):     # or 'glut', 'pygame', 'tk', 'qt', 'wx'
       options = ViewerOptions( source='model.glb' )

   if __name__ == '__main__':
       MyViewer.ContextMainLoop()

``ContextMainLoop`` opens the window and runs that toolkit's main loop until
the viewer quits. GLUT and Tk need an X display (XWayland under Wayland), and
Qt may need ``QT_QPA_PLATFORM=xcb``; :doc:`Windowing Backends <backends>` has
what each needs.

The viewer inside a Tk application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In Tk the view draws into a frame of the application's window, and the
application's loop calls ``loopIteration()`` for each frame:

.. code-block:: python

   import tkinter
   from OpenGLContext.viewer import viewerFor

   class SceneView( viewerFor('tk') ):
       def hasSceneToShow( self ):
           return True                     # the application opens its own scenes

   root = tkinter.Tk()
   view = SceneView( parent=root, size=(720, 560) )
   view.deferRedraw = True                 # one frame per iteration, however many events
   view.openSource( 'model.glb' )

   def onFrame():
       if not view.loopIteration():        # False once the view has quit
           root.destroy()
           return
       root.after( 1, onFrame )

   def onClose():
       view.releaseWindow()
       root.destroy()

   root.protocol( 'WM_DELETE_WINDOW', onClose )
   root.after( 1, onFrame )
   root.mainloop()

The viewer inside a Qt application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The Qt backend is the separate ``OpenGLContext-qt`` distribution. The view is
a ``QWindow``; ``container()`` wraps it in a widget for a layout, and
``startRenderTimer()`` has Qt's own timer draw the frames:

.. code-block:: python

   import sys
   from PySide6 import QtWidgets
   from OpenGLContext.viewer import viewerFor

   application = QtWidgets.QApplication( sys.argv )   # before the view

   class SceneView( viewerFor('qt') ):
       def hasSceneToShow( self ):
           return True

   class Window( QtWidgets.QMainWindow ):
       def __init__( self, source ):
           super().__init__()
           self.view = SceneView( size=(720, 560) )
           self.view.deferRedraw = True
           self.setCentralWidget( self.view.container( self ) )
           self.view.openSource( source )

       def closeEvent( self, event ):
           self.view.stopRenderTimer()
           self.view.releaseWindow()
           super().closeEvent( event )

   window = Window( 'model.glb' )
   window.show()
   window.view.startRenderTimer()          # after the window is shown
   application.exec()

Create the ``QApplication`` before the view. The view creates an application
object if none exists, Qt allows only one, and ``container()`` needs the
widgets one.

The viewer inside a wx application
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

In wx the view *is* a ``wx.glcanvas.GLCanvas``, placed in the frame like any
other window, and it draws from its own paint and idle events:

.. code-block:: python

   import wx
   from OpenGLContext.viewer import viewerFor

   class SceneView( viewerFor('wx') ):
       def hasSceneToShow( self ):
           return True

   class Frame( wx.Frame ):
       def __init__( self, source ):
           wx.Frame.__init__( self, None, -1, 'Viewer', size=(960, 600) )
           self.view = SceneView( self, size=(720, 560) )
           self.view.openSource( source )
           self.Bind( wx.EVT_CLOSE, self.onClose )

       def onClose( self, event ):
           self.view.releaseWindow()
           self.Destroy()

   application = wx.App( False )
   Frame( 'model.glb' ).Show( True )
   application.MainLoop()

Under wx the viewer's Quit command and the Escape key end the application.

:doc:`Embedding a view in an application <embedding>` explains each of these
choices, and adds a scene tree that follows the loaded scene. The sample
programs ``OpenGLContext.demos.tk_viewer``, ``OpenGLContext_qt.demos.qt_viewer``
and ``OpenGLContext.demos.wx_viewer`` are complete applications built this
way.

Methods to override
~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - Purpose
   * - ``prepareSource()``
     - Sets where the scene comes from. A browser with no single source
       overrides it to do nothing.
   * - ``loadScene()``
     - Produces the scene. **Runs on a worker thread, so it must not call
       GL.** This keeps the window drawing during a download.
   * - ``requestInitialScene()``
     - Chooses what to load first.
   * - ``buildScenegraph( scene )``
     - Turns a loaded scene into ``self.sg``. Called again for each new scene,
       which is how scenes are swapped.
   * - ``onSceneReady()``
     - Called on the render thread just after a scene is built.
   * - ``viewerLibrary()``
     - Returns the library this viewer offers.
   * - ``buildPhysicsWorld()``
     - Builds the collision world, when it should not come from ``self.sg``.
       See :ref:`Walking any scene <walking>`.

``openSource( source )`` and ``openEntry( entry )`` replace the scene in a
running viewer.

Modules
~~~~~~~

Each of these can also be used by a context that is not a viewer.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - Contents
   * - ``viewer.adapters``
     - One adapter per format, chosen by suffix and content type.
   * - ``viewer.options``
     - ``ViewerOptions``, the dataclass ``argparse`` also fills in.
   * - ``viewer.library``
     - The library: entries, categories and previews.
   * - ``viewer.menu``
     - The launch menu and the browse screen, as plain :doc:`panels <overlayui>`.
   * - ``viewer.screens``
     - The key that opens each screen, and the action taken when one closes.
   * - ``viewer.asyncscene``
     - Loading off the render thread, for any format.
   * - ``viewer.framing``
     - Camera placement to fit an object: arithmetic only, no GL.
   * - ``viewer.environment``
     - The sky, and the skybox that metals reflect.
   * - ``viewer.caption``
     - The caption over the frame, as a :doc:`HUD layer <hud>`.
   * - ``viewer.capture``
     - Writing one settled frame to a file.
   * - ``viewer.debug``
     - The developer overlay's **Scene** section.

Walking is not part of this package. Every interactive context can walk,
through ``OpenGLContext.move.physicswalk``; see :ref:`Walking any scene
<walking>`.

.. _adapters:

Adding a format
---------------

A format is an *adapter*: a class that reads one kind of source and returns a
``ViewerScene``. The rest of the viewer does not change.

.. code-block:: python

   from OpenGLContext.viewer.adapters.base import SceneAdapter, ViewerScene

   class STLAdapter( SceneAdapter ):
       name = 'stl'
       recentres = True         # a model may be moved to the middle of the frame

       def load( self, source ):
           # Runs on a worker thread: no GL here.
           return ViewerScene( group = ..., center = ..., radius = ... )

Register it in the plugin registry, with the suffixes and content types it
handles, alongside the loader, context and node registrations:

.. code-block:: python

   from OpenGLContext.plugins import Adapter
   Adapter( 'stl', 'mypackage.stl.STLAdapter', ['.stl', 'model/stl'] )

A ``ViewerScene`` holds:

- ``group`` - the renderable root;
- ``center`` and ``radius`` - the bounding sphere the camera is framed on;
- ``strays`` and ``stray_reach`` - how many parts the sphere leaves out and
  how far out they are (see :ref:`Framing a model <framing>`); both 0 for a
  loader that frames everything;
- ``viewpoints`` and ``cameras``;
- ``animations`` and ``player()``;
- ``exposure``.

``scene_bounds()`` in the same module computes the bounding sphere of a
scenegraph, for a format whose loader does not supply one.

Two adapter members control how the viewer treats a format:

- ``recentres`` - whether a scene with no camera of its own may be moved to
  the origin for framing. A *model* may, because its coordinates are
  arbitrary. A *world* may not: its ground is at y=0, its viewpoints are in
  its own coordinates, and moving it would put the avatar underground.

- ``update( viewer )`` - per-frame work for a source that is still loading.
  The 3D Tiles adapter pages in tiles for the current camera here. Formats
  read once from a file do nothing.

The viewer adds no ``Background`` to a scene that has its own, since two
bound backgrounds would conflict. It adds no lights to a scene that has its
own lights. Both checks look at the loaded scene, so they apply to every
format.
