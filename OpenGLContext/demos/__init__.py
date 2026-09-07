"""Sample applications: a view inside somebody else's window

Every other example that ships is a full-window program -- a context subclass
and ``ContextMainLoop()``.  These are the other shape: a view as *one widget*
in an application, with a menu above it and a panel beside it, and the host
toolkit owning the main loop.

Three programs, one per toolkit with a GUI library behind it, deliberately the
same program three times so they can be read against one another:

===============================  ===================================
:mod:`OpenGLContext.demos.tk_viewer`   ``ttk.Treeview``, ``root.mainloop()``
:mod:`OpenGLContext.demos.wx_viewer`   ``wx.TreeCtrl``, ``wx.App.MainLoop()``
``OpenGLContext_qt.demos.qt_viewer``   ``QTreeView``, ``QApplication.exec()``
===============================  ===================================

Each is run as a module, with an optional scene to open::

    python -m OpenGLContext.demos.tk_viewer model.glb

GLFW, Pygame and GLUT have no widgets to put beside a view -- they are window
and input libraries -- so an application on those draws its interface with
:mod:`OpenGLContext.ui`, which ``oglc-ui-demo`` shows.

Each demo is a page of its own toolkit's code over four engine calls:

``viewerFor(backend)(parent=...)``
    The view: :func:`OpenGLContext.viewer.viewerFor` gives the same viewer
    ``oglc-view`` is, over the toolkit that owns the window it goes in, so the
    demo inherits every format the adapters read, the PBR pass, auto-framing
    and the walk/examine navigation.
``context.openSource(path_or_url)``
    Opening a world.  It loads on a worker thread, so a slow download leaves
    the previous scene on screen and the window keeps drawing.
``SceneOutline(context.sg, onChange=...)``
    The scene as rows for the toolkit's tree control, re-walked when the scene
    changes underneath it (:mod:`OpenGLContext.outline`).
``context.loopIteration()``
    One frame, for the toolkit whose loop does not otherwise call back often
    enough.  Only Tk needs it: wx renders from its idle event and Qt from a
    timer of its own.

Both places a node is watched go through **pydispatcher**, which is how every
field of every node announces a change: the outline listens to the fields
holding other nodes, so the tree follows the scene, and each demo listens to
the one selected node, so the panel showing it keeps up.

See ``docs/embedding.html`` and ``plans/EMBEDDING-EXAMPLES.md``.
"""
