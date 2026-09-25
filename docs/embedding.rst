Embedding a view in an application
==================================

.. rst-class:: introduction

A desktop 3D application usually has a menu bar, a panel of controls and a
view of the scene, all driven by the GUI toolkit's main loop. This page shows
how to put an OpenGLContext view into such an application: which call puts
the view in a widget, which loop draws the frames, and what the host
application has to do that a full-window program does not.

Three sample programs go with this page. They are the same program written
for three toolkits, so they can be compared line by line:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Toolkit
     - Program
     - How the view is added
     - Main loop
   * - Tk
     - ``python -m OpenGLContext.demos.tk_viewer``
     - ``SceneView(parent=frame)``
     - ``root.mainloop()``, calling ``loopIteration()``
   * - Qt
     - ``python -m OpenGLContext_qt.demos.qt_viewer``
     - ``view.container(parent)``
     - ``QApplication.exec()``, with the backend's timer
   * - wx
     - ``python -m OpenGLContext.demos.wx_viewer``
     - the context *is* the canvas
     - ``wx.App.MainLoop()``, driving itself

Each takes an optional path or URL to open. Tk, Qt and wx are the backends
backed by a GUI library, with menus, trees and dialogs to place a view
beside. GLFW, Pygame and GLUT handle windows and input but have no widgets.
An application on one of those draws its interface with
:doc:`OpenGLContext.ui <overlayui>` instead; ``oglc-ui-demo`` shows how.

.. _viewer:

The view class
--------------

:doc:`ViewerContext <viewer>` is the class behind ``oglc-view``. It runs on
the backend chosen by the environment and the user's configuration. An
embedded view has to run on the toolkit that owns the host window.
``viewerFor`` returns the viewer class for a named backend:

.. code-block:: python

   from OpenGLContext.viewer import viewerFor

   class SceneView( viewerFor('tk') ):
       def hasSceneToShow( self ):
           return True                     # this application has its own File menu

``viewerFor`` takes a backend name (``tk``, ``qt``, ``wx``, ``glfw``,
``pygame`` or ``glut``), or no argument for the same class as
``ViewerContext``. An unknown backend, or one whose toolkit is not installed,
raises an error that lists the available backends. Two calls with the same
name return the same class, so ``isinstance`` checks work as expected.

The class draws a model as ``oglc-view`` does: with the
:doc:`PBR renderer <pbr>` (its ``renderer`` attribute is ``'pbr'``), with
shadows, and with the ambient and environment light scaled to 0.4 so that the
default light rig's sun reads against it. ``options.ibl_intensity`` and
``options.shadows`` on the subclass change those, and
``OPENGLCONTEXT_IBL_INTENSITY`` still sets the ambient scale where the options
do not. A ``contextDefinition`` passed to the constructor outranks both.

Override ``hasSceneToShow`` in every embedded view. A viewer started with
nothing to show opens its library, which suits ``oglc-view`` but not an
application with its own File menu. The viewer's other screens stay on their
keys: F1 for the library, F10 for render settings and F6 for controls. To
free those keys for the application, set ``LIBRARY_KEY``, ``SETTINGS_KEY``
and ``BINDINGS_KEY`` to ``''`` on the subclass.

.. _widget:

Adding the view to a window
---------------------------

Each backend joins its toolkit's layout in that toolkit's usual way:

Tk
   Pass the containing widget when building the context:
   ``SceneView(parent=holder)``. The context is not a widget itself. It draws
   into a ``GLFrame``, available as ``context.frame``, which is packed into
   the parent when the context is created.
Qt
   The view's window is a ``QWindow``. ``view.container(parent)`` wraps it in
   a ``QWidget`` to place in a layout. This needs ``PySide6.QtWidgets``, so
   the application object must be a ``QApplication``, not a bare
   ``QGuiApplication``. **Create it before building the view.** The view
   creates an application object if none exists, and Qt allows only one.
wx
   The context is a ``wx.glcanvas.GLCanvas``. Add ``SceneView(parent,
   size=(720, 560))`` to a sizer directly.

.. _embedding-loop:

Running the main loop
---------------------

A full-window program calls ``ContextMainLoop()``, and the engine runs the
loop. An embedded view cannot, because the host's loop is already running
and the frames have to come from it. How that works differs by backend.

Tk: the host drives the view
   Call ``loopIteration()`` from an ``after`` callback. It returns ``False``
   once the view has quit, which tells the host to clean up:

   .. code-block:: python

      def onFrame( self ):
          if not self.context.loopIteration():
              self.root.destroy()             # the view is gone; so is the window
              return
          self.root.after( 1, self.onFrame )
Qt: the backend drives the view
   Call ``view.startRenderTimer()`` after the window is shown. A Qt timer
   then calls ``loopIteration``. The host gets no per-frame callback; to act
   when a scene has loaded, override ``onSceneReady()``.
wx: no action needed
   The canvas renders from its own paint and idle events, so
   ``wx.App.MainLoop()`` drives it.

When the host drives the loop (Tk), set ``deferRedraw``. An input event then
requests a redraw instead of rendering immediately, so a burst of events
costs one frame rather than one frame per event. Every backend's own
``MainLoop`` sets it for the same reason. Do not set it under wx: there is no
``loopIteration`` call there, and the immediate redraw is what draws the
frame.

Quitting and cleanup
~~~~~~~~~~~~~~~~~~~~

Under Tk and Qt, quitting the view closes the view and returns; the host
application keeps running. The host decides what to do next; in the samples,
the window closes with it. Call ``releaseWindow()`` when the host window
closes. It frees every texture, buffer and shader the engine uploaded.

Under wx, quitting ends the process, as ``Context.OnQuit`` does by default.
The engine's Quit command and the Escape key end a wx application rather
than only closing the view.

.. _loading:

Opening a scene
---------------

``openSource(path_or_url)`` replaces the scene. The load runs on a worker
thread, so the previous scene stays on screen and the window keeps drawing
during a slow download. It returns ``False`` for a source that cannot be
found or whose format has no adapter. A new request replaces any load still
in progress, so it is safe to click quickly through a list. The
:ref:`adapters <adapters>` decide which formats open: glTF and GLB, VRML97,
OBJ and 3D Tiles, plus any format an application adds an adapter for.

``onSceneReady()`` is called on the render thread just after a scene is
built. Refill a scene tree from ``context.sg`` there.

.. _outline:

The scene as a tree
-------------------

:py:mod:`OpenGLContext.outline <OpenGLContext.outline>` presents the
scenegraph as a flat list of rows, with a set of expanded rows and a
selection. It uses no GL and no toolkit, so one model can feed a
``ttk.Treeview``, a ``QTreeWidget`` or a ``wx.TreeCtrl``. A program can also
use it with no window open to list what a loaded scene contains:

.. code-block:: python

   from OpenGLContext.outline import SceneOutline

   outline = SceneOutline( context.sg )
   for row in outline.rows:
       print( '  ' * row.depth, row.label, row.field or '' )
   outline.toggle( outline.rows[1].path )

Each row has these attributes:

- the node;
- ``depth``;
- ``field`` - the field of the parent that holds the node;
- ``defName`` and ``nodeType``;
- ``expandable``;
- ``path`` - the child indices from the root. Expansion and selection are
  recorded by path, so a tree item should store it.
- ``label`` - the name the file gave the node, or its type if it has no name.

A row's children are its node's node-valued fields, in name order. That
includes a ``Transform``'s ``children``, and also a ``Shape``'s ``geometry``
and ``appearance``, which the render traversal does not descend into but an
inspector needs. Fields holding *weak* references are skipped, because they
point back up the scene. Values that are not nodes are skipped too. A node
reachable by two routes gets a row under each, which is how ``USE`` in VRML
and shared meshes in glTF appear.

``nodeSummary(node, width=60)`` returns the data for a detail panel: the
node's own field values as ``(field, text)`` pairs, without the child nodes,
with long values cut to ``width`` characters.

.. _watching:

Following a scene that changes
------------------------------

Every field of every node sends a signal through :doc:`pydispatcher
<eventmodel>` when it changes. That lets a panel follow an animation, a route
or an editor as they change the scene. A ``SceneOutline`` connects to the
fields that hold other nodes, so the tree follows the scene structure:

.. code-block:: python

   outline = SceneOutline( context.sg, onChange=self.treeNeedsFilling )

A panel showing one node connects to that node directly:

.. code-block:: python

   from pydispatch import dispatcher

   dispatcher.connect( self.onNodeChanged, sender=node )
   ...
   dispatcher.disconnect( self.onNodeChanged, sender=node )

**A change signal arrives on the thread that made the change.** The viewer
builds scenes on a worker thread, while a toolkit's widgets belong to the
toolkit's own thread. Treat ``onChange`` as a notification only, and fill the
tree on the toolkit thread. Each sample does this its toolkit's way: Tk
checks ``outline.dirty`` in its per-frame callback, Qt emits a signal through
a queued connection, and wx uses ``wx.CallAfter``. One notification covers
every change until the rows are next read, so building a scene does not
flood the host with calls.

``outline.close()`` releases the scene and disconnects the signals. Call it
before discarding an outline. Otherwise the outline keeps every scene it has
shown in memory.

.. _shipping:

Shipping an embedded viewer
---------------------------

An embedded viewer is packaged like any other application built on the
engine. The samples include packaging for both PyInstaller and Debian
packages: ``OpenGLContext/demos/packaging/`` for the Tk sample and
``OpenGLContext_qt/demos/packaging/`` for the Qt sample. Each has a
PyInstaller ``.spec`` file, a script that builds a ``.deb``, and a
distribution that turns the demo into an application. Read their
``README.md`` alongside :doc:`Packaging an application <packaging>`.

.. code-block:: bash

   pyinstaller OpenGLContext/demos/packaging/viewer-demos.spec
   OpenGLContext/demos/packaging/build-deb.sh

Two settings depend on the toolkit:

- ``unused_backend_modules(keep=['tk'])`` leaves out the toolkits the
  application does not use. For a Tk or wx program this keeps about a quarter
  of a gigabyte of Qt out of the bundle.
- Build a Tk package with ``oglc-deb --backend tk``. Tk is part of CPython,
  not a wheel in the environment. Without the option it is removed along with
  other modules the application does not import, and the installed package
  fails to start.

``OpenGLContext.demos`` declares no console scripts, so to ship a demo, turn
it into an application. For these samples that is a ``pyproject.toml`` that
names a script, the smallest complete example of an application's own
packaging.
