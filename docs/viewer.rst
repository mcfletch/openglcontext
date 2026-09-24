The viewer
==========

.. rst-class:: introduction

``oglc-view`` opens a 3D scene — a glTF model, a VRML97 world, a Wavefront
OBJ, a streamed 3D Tiles dataset — renders it with the :doc:`core-profile PBR
renderer <pbr>` and lets you look around it or walk through it. **Which format
a source is in is worked out from the source**, not from which command you
typed, so there is one viewer and every format gets everything it can do.

Run it with nothing to open and it shows its menu: a :ref:`library <library>`
of sample models and worlds with pictures to browse, and a box to type an
address into — a viewer launched from a desktop has no command line to pass a
URL on. The same class is a reusable component — see :ref:`Embedding
<viewer-embedding>`.

.. _opening:

Opening something
-----------------

.. code-block:: bash

   oglc-view                       # the launch menu and the library
   oglc-view path/to/model.glb
   oglc-view path/to/world.wrl
   oglc-view path/to/model.obj
   oglc-view path/to/tileset.json
   oglc-view https://example.com/model.glb
   GLTF=path/to/model.gltf oglc-view

The viewer selects the core profile, the PBR renderer, the GLFW backend and
shadows for you, so no environment variables are needed.

What it can open
~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Source
     - Adapter
     - What it is
   * - ``.gltf`` ``.glb``
     - ``gltf``
     - A glTF 2.0 *model*: centred and framed, with its own cameras and animations.
       See :doc:`Loading glTF <gltf>`.
   * - ``.wrl`` ``.wrz`` ``.vrml`` ``.wrl.gz``
     - ``vrml97``
     - A VRML97 *world*: shown where it was authored, keeping its own sky, its own
       lights and its own ``Viewpoint`` nodes.
   * - ``.obj``
     - ``obj``
     - A Wavefront model. It carries no lights, cameras or sky, so the viewer
       supplies all three.
   * - ``tileset.json``, or any JSON with both ``asset`` and ``root``
     - ``tiles3d``
     - An OGC 3D Tiles dataset, streamed and refined as you move. See :doc:`Streamed
       3D Tiles <tiles3d>`.

A source served from a path with no suffix — ``/download?id=3`` — can be named
explicitly with ``--format gltf``.

A binary ``.glb`` is self-contained, so URLs to one work directly. A
non-binary ``.gltf`` usually references external ``.bin`` and texture files,
by URI relative to the document; a URL keeps the document's own location and
resolves them against it, so a remote multi-file model opens with its geometry
and textures intact. See :doc:`Loading glTF <gltf>`.

The viewer narrates what it is doing as it goes — the file it is opening, the
cameras and lights it found in it, the animation it is playing — on standard
output. Those lines carry names from the file and from the command line, which
are arbitrary Unicode, while a console holds only what its encoding has room
for: a Windows console is a codepage of a couple of hundred characters. A
character the console cannot show is written escaped — ``❤`` as ``\u2764`` —
and the model opens regardless. Redirect the output to a UTF‑8 file, or run
with ``PYTHONIOENCODING=utf-8``, to read the names as they are written.

A streamed dataset has knobs the other formats do not, and they are on the one
command line: ``--sse`` (screen-space error target in pixels; lower is more
detail), ``--memory`` (resident tile budget in MiB), ``--no-recenter`` and
``--cache-dir``. A format that is read once ignores them.

.. _framing:

Framing a model, and parts left out of the frame
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A model with no camera of its own is centred and framed automatically: the
camera backs off far enough for the model's bounding sphere to fill the field
of view, raised a little and tilted down so it is seen from slightly above.
``--margin``, ``--elevation`` and ``--tilt`` adjust that fit, and ``--eye
X,Y,Z`` with ``--look-at X,Y,Z`` replaces it outright.

The sphere is fitted to *the model*, which is not always everything the file
draws. Exported models quite often carry a part or two stranded far outside
themselves — a decal left behind at a hundred times its scale, a duplicate
forgotten at the far end of the file's coordinate space. Framing those too
would stand the camera hundreds of model-widths back, and the model would be a
speck in the middle of an empty frame. So a part is left out of the fit when
both of two things are true: the file's whole extent is more than **four
times** that of the nine-tenths of the model lying closest together, *and* the
part sits beyond an empty shell — more than **twice** as far out as everything
nearer than it. A model that merely thins out towards its edges fails the
second test, and a scene that genuinely is two things far apart fails the
first, so neither is cut.

Nothing is hidden by this: a stray is still drawn, and walking or flying out
to it reaches it as usual. It simply does not decide where the camera starts.
When any part is left out the viewer says so on startup, with how many and how
far out they are, so a file that looks incomplete can be recognised as one:

.. code-block:: python

   Framed on the model: 24 part(s) of this file sit up to 102 times its size
   away and start out of view.

The rule is ``OpenGLContext.loaders.gltf.transforms.framing_bounds()``, and
its three constants — ``STRAY_RATIO``, ``STRAY_CROWD`` and ``STRAY_GAP`` — are
the numbers quoted above. It applies to glTF sources; the other formats frame
their whole extent.

.. _viewer-window:

The window
~~~~~~~~~~

``oglc-view`` fills the screen, showing the scene alone. The :ref:`developer
overlay <hud-debug>` starts hidden; :kbd:`Alt`+:kbd:`f` brings it up.

.. code-block:: bash

   oglc-view model.glb                     # full screen
   oglc-view model.glb --no-fullscreen     # a 1920x1080 window
   oglc-view model.glb --size 1280x720     # a 1280x720 window

``--size WxH`` asks for a window of that size, and ``--fullscreen`` fills the
screen whatever the size. Without ``--size`` the window is 1920x1080, which is
also what leaving full screen from the Settings screen returns to.
``OPENGLCONTEXT_FULLSCREEN=0`` makes a window the default for a shell, and the
flags outrank it.

A capture or a recording does not fill the screen. Its window is ``--size``,
or the backend's default of 300x300, because that size is the resolution of
the file it writes. See :ref:`Capturing a frame <capture>`.

.. _commands:

The old command names
~~~~~~~~~~~~~~~~~~~~~

``oglc-gltf``, ``oglc-vrml`` and ``oglc-tiles`` still work: each runs
``oglc-view`` and prints a line saying so. They will be removed after one
release cycle. Every option they took is still accepted.

``oglc-vrml``'s ``--shaders`` / ``--no-shaders`` switches are gone. They
reached into the render pass from inside ``Redraw`` to turn shader rendering
on; the viewer renders through the core-profile PBR pass as a matter of
course. A world that genuinely wants the compatibility pipeline gets it where
every other renderer switch lives:

.. code-block:: bash

   OPENGLCONTEXT_PROFILE=compatibility oglc-view world.wrl

.. _viewer-controls:

Controls
--------

Moving
~~~~~~

- Up / Down — walk forward / back; Left / Right — turn.

- Ctrl+Up / Ctrl+Down — look up / down.

- Alt+Up / Alt+Down — move up / down; Alt+Left / Alt+Right — strafe.

- ``-`` levels the horizon; right-mouse drag orbits.

- ``g`` toggles walking (gravity and collision) against free-fly; ``f`` toggles
  flying while walking; ``m`` steps through the declared :doc:`movement modes
  <navigation>`.

.. _orbit:

What a right-drag orbits
~~~~~~~~~~~~~~~~~~~~~~~~

The point you clicked on, when you clicked on the model: examining the thing
you touched is the whole gesture. A click that hits *nothing* still resolves
to a world point — the far plane, an order of magnitude further out than
anything on screen — so a picked point is used only where it lies within reach
of the scene's bounding sphere (one and a half times its radius, which is
generous because a bounding sphere already overstates a model's extent).

Otherwise the pivot comes from the scene itself. Looking at a model from
outside, it is the middle of the model, whatever the model's size or where it
sits; standing *inside* a scene — a building you are walking through —
orbiting the far wall would swing you round the room, so the pivot is a point
ahead of the camera instead, at half the scene's radius. A viewer with nothing
loaded pivots a fixed distance ahead.

A drag from one side of the window to the other is **half a turn**. The
trackball measures a drag as the fraction of the way from where it started to
the edge of the window, so a full turn per window made every small nudge a
large swing; the distance to the pivot never changes, whatever the drag.

The scene
~~~~~~~~~

- PgUp / PgDn (or ``p`` / ``n``) — the scene's own cameras.

- Ctrl + PgUp / PgDn — the previous / next entry in the :ref:`library <library>`
  category this one was opened from. Nothing to step for a file named on the
  command line or an address typed in: those are not part of a list.

- ``k`` pauses the animation; ``[`` and ``]`` switch between animations.

- ``t`` starts and stops the turntable.

- ``v`` switches between one view of the scene and four: the plan, the front
  and left elevations, and the camera. ``--views quad`` opens with four. See
  :doc:`multiview`.

Each of these does its thing once, on the key coming back up: a held key
repeats around twenty times a second, which for these would be twenty models
loaded or twenty cameras past the one wanted. They are declared as a table,
``SceneViewerMixin.viewerKeys``, of ``KeyBinding(name, method, description,
modifiers, state)`` — a subclass adding a key of its own extends that rather
than overriding ``setupCallbacks``, and the description says what the key does
in a form fit to list. Modifiers are ``(shift, control, alt)``, in that order;
the ``F6`` controls screen rebinds the :doc:`navigation <navigation>`
commands, which are a separate set.

Screens
~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Key
     - What it raises
   * - ``F1``
     - The :ref:`library <library>`: what there is to open.
   * - ``F10``
     - :doc:`Settings <overlayui>` — the same page every program here shows.
   * - ``F6``
     - Controls: rebind any key.
   * - ``F2``
     - Save a screenshot — a PNG in the user’s picture folder, named for the window
       title. Every context binds this, not just the viewer; see :ref:`the screenshot
       key <screenshots>`.
   * - ``Escape``
     - The menu, with **Resume** first and Quit below it. Escape never ends the
       session by itself: it is the key people press to back out of something, and a
       loaded world is too expensive to throw away without being asked. Escape again
       resumes.
   * - ``Alt+F``
     - The :ref:`developer overlay <hud-debug>`, hidden when the viewer opens. The
       viewer adds a **Scene** section to it: the source, which adapter read it, the radius the framing came from,
       which camera is bound, the animation and how you are moving.

These are the keys ``twig-bb`` uses, deliberately: someone who has used one of
these programs knows the other.

Every screen is usable from the keyboard alone: the up/down arrows or
Tab/Shift-Tab move between items, Space or Return presses the one focused,
Return alone presses the screen's primary action, and Escape leaves it.

.. _library:

The library
-----------

``oglc-view`` with nothing named is not a usage message. It opens a menu, and
from it a shelf of models and worlds shown by their own pictures, so that you
can see what a sample is before opening it rather than reading a name like
``MetalRoughSpheresNoTextures``.

The shelf is *derived* from the demo roster the capture harness already uses
(``OpenGLContext.loaders.gltf_demos``), so the library and the reference
captures cannot drift on how a model has to be shown: the yaw it faces at, the
backdrop its materials need, whether it is meant to be walked. It is grouped
into **Models**, **Materials** (metals and glass, which need an environment),
**Scenes** (authored cameras or an interior), **Local builds** and, last,
**Feature tests**.

This project ships no worlds of its own, so there is no **Worlds** shelf until
an application adds one — ``tests/wrls`` is test data, not content.
``world_entries()`` turns a directory of them into entries for an application
that has some.

Preview pictures are the Khronos reference screenshots, fetched once and
cached on disk. Being offline costs pictures and nothing else.

The **Feature tests** shelf is last and holds the bulk of the Khronos set:
entries that exist to exercise one glTF feature — a bare triangle, a sparse
accessor, the ``Compare*`` grids — rather than to be looked at. Which is which
is a field on the shared demo table, so this shelf and ``oglc-gltf-demo``'s
browsing order cannot disagree.

The band's arrows *look*; clicking a picture is what opens it.

Choosing something opens it **into the running window** — a new adapter, a new
scenegraph, new framing — without tearing the context down. Loading happens in
the background, and a load that a later one has overtaken is dropped, so
clicking quickly through the shelf is safe.

Your own shelf
~~~~~~~~~~~~~~

An application curates its own by overriding one method:

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

An entry's ``options`` are ``ViewerOptions`` field names, applied when it is
opened and *not* carried over to the next one.

Hundreds of entries
~~~~~~~~~~~~~~~~~~~

The band shows five at a time out of however many there are, wrapping, so a
shelf of several hundred lays out as fast as one of three; the ``<<`` and
``>>`` buttons move a bandful at a time. Pictures are decoded off the render
thread and uploaded a couple per frame, and the least recently used are
dropped once a texel budget is reached — see ``OpenGLContext.ui.pictures``.

.. _capture:

Capturing a frame
-----------------

.. code-block:: bash

   oglc-view model.glb --capture-image shot.png --size 1100x680
   oglc-view model.glb --camera aerial --capture-image shot.png --capture-delay 0.5
   oglc-view model.glb --list-cameras

.. rst-class:: technical

``--capture`` is the same flag under its older name, and stays.

``--capture`` renders the scene, waits for it to settle — a wall-clock delay
and a minimum frame count, so the adaptive analytic-sky IBL has converged —
writes the PNG and exits. The captured frame carries no caption and no
developer overlay.

It also renders **without mapping a window** and with vsync off. A mapped
surface throttles the buffer swap to the compositor's frame callback, and with
nothing on screen consuming frames the swap never returns; a hidden window
renders and reads back identically. Both are overridable
(``OPENGLCONTEXT_HIDDEN=0``), since watching a capture happen is how you find
out why it looks wrong.

.. _video:

Recording a video
~~~~~~~~~~~~~~~~~

.. code-block:: bash

   oglc-view world.glb --capture-video walk.mp4 --fly-through
   oglc-view world.glb --capture-video spin.mp4 --turntable --video-seconds 8
   oglc-view world.glb --capture-video walk.mp4 --fly-through \
       --video-seconds 16 --video-fps 30 --size 1280x720

``--capture-video`` records the frames the viewer draws to an H.264 file and
exits when it has enough of them. The encoder is the one in the graphics
driver and the frame never leaves the GPU, so recording costs little more than
drawing. Like a captured frame, a recorded one carries no caption and no
developer overlay.

The recording is a *fixed number of frames* rather than however many the
machine managed in the time: the clock is advanced a frame at a time while it
runs, so the result plays at the speed it says whatever the frame rate was
while it was made. A slow machine takes longer to record; it does not record a
slower world.

**Something has to move.** A recording of a still is a picture with a file
size, and there are two ways to give it motion. ``--turntable`` spins the
model, which suits an object. ``--fly-through`` walks the camera along the
*scene's own viewpoints*, in the order the file declares them, easing in and
out of each leg — so the path is the one the author placed, and a world with
two cameras in it is already a shot. It is what a scene too big to see at once
wants: see :ref:`Levels of detail <lod-demo>`, where the walk from one end of
a hall to a bust at the other is exactly the two cameras that world carries.

.. rst-class:: technical

Recording needs `pyopengl-video <https://pypi.org/project/pyopengl-video/>`__,
which ``OpenGLContext[video]`` installs. Without it ``--capture-video`` says
so rather than recording nothing.

.. _viewer-embedding:

Embedding the viewer
--------------------

.. rst-class:: technical

This is the viewer as a whole program. For the viewer as *one widget* in a Tk,
Qt or wx application — a menu above it, a panel beside it, and the toolkit
owning the loop — see :doc:`Embedding a view in an application <embedding>`.

Everything the command does — loading without freezing the window, the default
light rig, auto-framing, the scene's own cameras and animations, the caption,
screenshots, the library, walking — is the reusable ``OpenGLContext.viewer``
package, not the script. An application gets all of it by subclassing
``ViewerContext`` and saying what it wants with a ``ViewerOptions``. There is
no command line involved:

.. code-block:: python

   from OpenGLContext.viewer import ViewerContext, ViewerOptions

   class MyViewer( ViewerContext ):
       options = ViewerOptions(
           source = 'model.glb',       # a path, a URL, or None for the library
           physics = True,             # walk it, rather than fly around it
           background = 'sky',
       )

   MyViewer.ContextMainLoop()

``ViewerOptions`` is a dataclass holding every knob the viewer has, and it is
the *same* object the command line fills in — ``argparse`` populates one as
its namespace — so the defaults are written once and a flag can never mean
something different from the field. The fields are grouped as: the source and
``format``; the cameras (``camera``, ``no_cameras``); auto-framing (``yaw``,
``margin``, ``elevation``, ``tilt``, ``eye``, ``look_at``); lighting and
environment (``lights``, ``shadows``, ``ibl_intensity``, ``environment``,
``background``); animation (``animate``, ``animation``, ``anim_time``,
``turntable``, ``no_rotate``); ``physics``; and the window and frame
(``size``, ``fullscreen``, ``capture``, ``capture_delay``, ``frames``).

The component opens the window its context class asks for, 300x300 unless
the class says otherwise. ``options.window()`` returns the ``size`` and
``fullscreen`` :doc:`definition fields <structure>` ``oglc-view`` opens its
own with — full screen, or 1920x1080 — for an application that wants the
same::

   MyViewer.ContextMainLoop(**MyViewer.options.window())

The component starts with the developer overlay hidden, through the
``debugOverlayStartsVisible`` attribute every context has.

The seams worth overriding
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Method
     - What it decides
   * - ``prepareSource()``
     - Where the scene comes from. A browser with no single source overrides this to
       do nothing.
   * - ``loadScene()``
     - Produce the scene. **Runs on a worker thread, so it must not touch GL** — that
       is what keeps the window drawing through a download.
   * - ``requestInitialScene()``
     - What to load first.
   * - ``buildScenegraph( scene )``
     - Turn a loaded scene into ``self.sg``. Called again for each new scene, which
       is what makes swapping possible.
   * - ``onSceneReady()``
     - Just after a scene is built, on the render thread.
   * - ``viewerLibrary()``
     - What this viewer offers to open.
   * - ``buildPhysicsWorld()``
     - Where the collision world comes from, if not from ``self.sg``. See
       :ref:`Walking any scene <walking>`.

``openSource( source )`` and ``openEntry( entry )`` swap the scene in a
running viewer.

The parts, separately
~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Module
     - What it is
   * - ``viewer.adapters``
     - What a source is and how to read it, keyed by suffix and content type.
   * - ``viewer.options``
     - Every knob, in one dataclass that ``argparse`` also fills in.
   * - ``viewer.library``
     - The shelf: entries, categories and previews.
   * - ``viewer.menu``
     - The launch menu and the browse screen, as plain :doc:`panels <overlayui>`.
   * - ``viewer.screens``
     - Which key raises which screen, and what happens when one is answered.
   * - ``viewer.asyncscene``
     - Loading off the render thread, format-neutral.
   * - ``viewer.framing``
     - Where to put a camera to see a thing — pure arithmetic, no GL.
   * - ``viewer.environment``
     - The sky, and the skybox its metals reflect.
   * - ``viewer.caption``
     - The line or two over the frame, as a :doc:`HUD layer <hud>`.
   * - ``viewer.capture``
     - One settled frame to a file.
   * - ``viewer.debug``
     - The developer overlay's **Scene** section.

Walking is not in this package at all: it is a capability of *every*
interactive context, in ``OpenGLContext.move.physicswalk``.

.. _adapters:

Adding a format
---------------

A format is an *adapter*: a class that reads one kind of source and answers
the handful of questions asked of every scene. Nothing in the viewer changes.

.. code-block:: python

   from OpenGLContext.viewer.adapters.base import SceneAdapter, ViewerScene

   class STLAdapter( SceneAdapter ):
       name = 'stl'
       recentres = True         # a model may be moved to the middle of the frame

       def load( self, source ):
           # Runs on a worker thread: no GL here.
           return ViewerScene( group = ..., center = ..., radius = ... )

Register it alongside the loader, context and node registries, against the
suffixes and content types it handles:

.. code-block:: python

   from OpenGLContext.plugins import Adapter
   Adapter( 'stl', 'mypackage.stl.STLAdapter', ['.stl', 'model/stl'] )

What a ``ViewerScene`` answers: ``group`` (the renderable root), ``center``
and ``radius`` (the bounding sphere the camera is framed against), ``strays``
and ``stray_reach`` (how much the sphere leaves out and how far out it goes —
see :ref:`Framing a model <framing>`; both 0 for a loader that frames
everything), ``viewpoints`` and ``cameras``, ``animations`` and ``player()``,
and ``exposure``. ``scene_bounds()`` in the same module works the bounding
sphere out of a scenegraph for a format whose loader does not.

The viewer asks two things *about* a format:

- ``recentres`` — whether a scene with no camera of its own may be moved to the
  origin to be framed. A *model* may: its coordinates are arbitrary. A *world*
  may not: its ground plane is at y=0, its viewpoints are in its own space, and
  moving it would put the avatar underground.

- ``update( viewer )`` — per-frame work for a source that is still arriving. 3D
  Tiles pages itself in against the current camera here; everything read once
  from a file wants nothing.

A scene that brings its own ``Background`` does not get a second one — two of
them is not two skies, it is a fight over which is bound — and one that brings
its own lights is not re-lit. Both are detected from the scene rather than
declared, so they are true of any format.
