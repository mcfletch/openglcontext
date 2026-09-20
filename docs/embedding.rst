Embedding a view in an application
==================================

.. rst-class:: introduction

A thick-client 3D application is a menu bar, a panel of controls, and a view
of the scene between them, with the toolkit's own main loop driving all of it.
This is how the engine goes in one: which call puts the view in a
widget, which of the two loops does the driving, and what the host has to do
that a full-window program does not.

Three sample programs go with this page, deliberately the same program three
times so they can be read against one another:

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Toolkit
     - Program
     - How the view goes in
     - Whose loop
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

Each takes an optional path or URL to open. They are Tk, Qt and wx because
those are the backends with a GUI library behind them — menus, trees, dialogs,
something to put a view beside. GLFW, Pygame and GLUT are window and input
libraries with no widgets, so an application on those draws its interface with
:doc:`OpenGLContext.ui <overlayui>` instead, which ``oglc-ui-demo`` shows.

.. _viewer:

The view
--------

:doc:`ViewerContext <viewer>` is the viewer ``oglc-view`` is, over whichever
backend the environment and the user's configuration chose. A program
embedding a view needs it over the toolkit that owns the window it is going
into, which is what ``viewerFor`` answers:

.. code-block:: python

   from OpenGLContext.viewer import viewerFor

   class SceneView( viewerFor('tk') ):
       def hasSceneToShow( self ):
           return True                     # this application has its own File menu

It takes the name a backend is selected by — ``tk``, ``qt``, ``wx``, ``glfw``,
``pygame``, ``glut`` — or nothing, for the same class ``ViewerContext``
already is. A name that is not a registered backend, or whose toolkit is not
installed, raises naming the ones there are. Asking twice gives one class, so
``isinstance`` means what a reader expects.

``hasSceneToShow`` is worth overriding in every embedded view. A viewer
started with nothing to show opens its shelf, which is right for ``oglc-view``
and wrong inside an application that has a File menu of its own. The engine's
other screens stay on their keys — F1 for the shelf, F10 for the render
settings, F6 for the controls — and an application that wants those keys for
itself binds none of them by setting ``LIBRARY_KEY``, ``SETTINGS_KEY`` and
``BINDINGS_KEY`` to ``''``.

.. _widget:

Putting it in the window
------------------------

Each backend joins its toolkit's layout in that toolkit's own way:

Tk
   Build the context with the widget that is to hold it,
   ``SceneView(parent=holder)``. The context is not itself a widget — the
   ``GLFrame`` it draws into is ``context.frame``, packed into the parent as it
   is made.
Qt
   The window is a ``QWindow``, and ``view.container(parent)`` wraps it in a
   ``QWidget`` for a layout. That needs ``PySide6.QtWidgets``, so the application
   object must be a ``QApplication`` rather than a bare ``QGuiApplication`` —
   **and it must exist before the view is built**, since the view makes one
   itself if there is none and Qt allows exactly one.
wx
   The context *is* a ``wx.glcanvas.GLCanvas``: ``SceneView(parent, size=(720,
   560))`` goes straight into a sizer.

.. _embedding-loop:

Whose loop, and who draws
-------------------------

A full-window program calls ``ContextMainLoop()`` and the engine owns the
loop. An embedded view does not: the host's loop is already running, and the
frames have to come out of it. What that takes differs by backend, and it is
the one part of embedding that is not the same in all three.

Tk — the host drives
   Call ``loopIteration()`` from an ``after`` callback. It answers False once the
   view has finished, which is how the host learns that a view quit from inside:

   .. code-block:: python

      def onFrame( self ):
          if not self.context.loopIteration():
              self.root.destroy()             # the view is gone; so is the window
              return
          self.root.after( 1, self.onFrame )
Qt — the backend drives
   ``view.startRenderTimer()``, after the window is shown, and Qt's own timer
   calls ``loopIteration`` from then on. There is no per-frame callback for the
   host, so a host that wants to know when a scene has arrived overrides
   ``onSceneReady()``.
wx — nothing to do
   The canvas renders from its own paint and idle events, so
   ``wx.App.MainLoop()`` drives the engine by itself.

Where the host drives the loop, set ``deferRedraw``. With it, an input event
asks for a redraw rather than rendering where it was handled, so a burst of
them costs one frame instead of one frame each. Every backend's own
``MainLoop`` sets it for exactly this reason, and a host calling
``loopIteration`` is standing in for that loop. Leave it alone under wx, where
there is no such call and the synchronous redraw is what draws at all.

**Quitting is not the same as ending the process.** A view inside somebody
else's window is a view: the Tk and Qt contexts close it and return, leaving
the host running, so the host decides what a finished view means — in these
samples, the window goes with it. ``releaseWindow()`` is what gives the driver
back every texture, buffer and shader the engine uploaded, and the host calls
it as its window closes. The wx context ends the process instead, as
``Context.OnQuit`` does by default, so the engine's own Quit and the Escape
key end a wx application rather than closing the view in it.

.. _outline:

The scene as a tree
-------------------

:py:mod:`OpenGLContext.outline <OpenGLContext.outline>` is the scenegraph as a
flat list of rows, with a set of expanded rows and a selection. It holds no GL
and knows no toolkit, so one model feeds a ``ttk.Treeview``, a ``QTreeWidget``
and a ``wx.TreeCtrl`` alike — and a program that just wants to know what is in
the scene it loaded can ask it with no window open at all:

.. code-block:: python

   from OpenGLContext.outline import SceneOutline

   outline = SceneOutline( context.sg )
   for row in outline.rows:
       print( '  ' * row.depth, row.label, row.field or '' )
   outline.toggle( outline.rows[1].path )

A row carries the node, its ``depth``, the ``field`` it hangs from, its
``defName`` and ``nodeType`` separately, whether it is ``expandable``, and its
``path`` — the child indices from the root, which is what expansion and
selection are recorded as and what a tree item should carry. ``row.label`` is
the name the file gave the node, or its type where it gave none.

**Children are the node-valued fields**, in name order: a ``Transform``'s
``children``, and equally a ``Shape``'s ``geometry`` and ``appearance``, which
the rendering traversal does not descend into and an inspector wants. A field
holding a *weak* reference is passed over — it points back into the scene
rather than down it — as is a value that is not a node. One node reached by
two routes gets a row under each, since that is what ``USE`` in a VRML file
and a shared mesh in a glTF one look like.

``nodeSummary(node)`` is the panel beside the tree: the values a node carries
in its own right, as ``(field, text)`` pairs, with the nodes under it left out
and a long value cut to a width you give it.

.. _watching:

Following a scene that changes
------------------------------

Every field of every node announces a change through :doc:`pydispatcher
<eventmodel>`, which is what lets a panel keep up with an animation moving a
node, a route firing into it, or an editor changing it. A ``SceneOutline``
listens on the fields that hold other nodes, so the tree follows the scene:

.. code-block:: python

   outline = SceneOutline( context.sg, onChange=self.treeNeedsFilling )

and a panel showing one node listens to that node directly:

.. code-block:: python

   from pydispatch import dispatcher

   dispatcher.connect( self.onNodeChanged, sender=node )
   ...
   dispatcher.disconnect( self.onNodeChanged, sender=node )

**A change arrives on whichever thread made it.** The viewer loads on a worker
thread, so a scene is assembled off the render thread, while a toolkit's
widgets belong to the toolkit's own thread. So ``onChange`` is a *notice*, not
a place to fill a tree from. Each sample crosses back the way its toolkit
does: Tk asks its per-frame callback whether ``outline.dirty``, Qt emits a
signal and lets a queued connection deliver it, and wx uses ``wx.CallAfter``.
One notice covers every change until the rows are next read, so a scene being
built does not flood the host.

``outline.close()`` lets go of the scene and its subscriptions. A viewer that
opens one model after another calls it on the way out, since the rows are what
would otherwise keep every scene it has ever shown alive.

.. _loading:

Opening a world
---------------

``openSource(path_or_url)`` shows something else, and the load runs on a
worker thread — so a slow download leaves the previous scene on screen and the
window keeps drawing. It answers False for a source that cannot be found or
whose format has no adapter, and a request supersedes the one before it, so
clicking quickly through a list is safe. Which formats that covers is the
:ref:`adapters' <adapters>` business rather than the application's: glTF and
GLB, VRML97, OBJ and 3D Tiles today, and whatever else an adapter is written
for.

``onSceneReady()`` is called on the render thread just after a scene has been
built, which is where a host refills its tree from ``context.sg``.

.. _shipping:

Shipping one
------------

An embedded viewer is packaged like any other application built on the engine,
and the samples come with the recipe for both ways of doing it:
``OpenGLContext/demos/packaging/`` for the Tk one and
``OpenGLContext_qt/demos/packaging/`` for the Qt one, each with a PyInstaller
``.spec``, a script that builds a ``.deb``, and the distribution that turns a
demo into an application. Their ``README.md`` reads alongside :doc:`Packaging
an application <packaging>`.

.. code-block:: python

   pyinstaller OpenGLContext/demos/packaging/viewer-demos.spec
   OpenGLContext/demos/packaging/build-deb.sh

Two things about it belong to the toolkit rather than to the application.
``unused_backend_modules(keep=['tk'])`` leaves the toolkits the application
does not use out of the bundle, which for a Tk or wx program is what keeps a
quarter of a gigabyte of Qt from travelling with it. And a Tk package must be
built with ``oglc-deb --backend tk``: Tk is part of CPython rather than a
wheel in the environment, so it is otherwise stripped out with everything else
an application "cannot reach", and the package installs and then fails to
start.

A demo is not a command — ``OpenGLContext.demos`` declares no console scripts,
since a command whose purpose is to be read is in the way of the ones that do
work — so shipping one means making it an application. For these that is a
``pyproject.toml`` naming a script and nothing else, which is the smallest
complete example of what an application of your own already has.
