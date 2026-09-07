# A viewer application, in each GUI toolkit

Status: **Landed** (2026-09-07).  What landed, and what was found doing it, is
at the end; the plan above it is as it was written.

## Why

Someone deciding whether to build a thick-client 3D application on this engine
asks one question first: *what does the code look like in my toolkit?* The
engine answers with six backends and a `ContextDefinition`, and every example
that ships is a **full-window** program -- a `TestContext` subclass and
`ContextMainLoop()`. Nothing shows a view **inside an application**: a menu bar
above it, a panel beside it, the host toolkit owning the loop.

That is the shape of nearly every program a reader wants to write. The parts
are all present -- `TkContext(parent=...)`, `QtContext.container()`,
`wxContext(parent, ...)`, `loopIteration()`, `pumpWindowEvents()` -- and none of
them is demonstrated together.

## Three examples, one for each toolkit

Tk, Qt and wx are the backends with a GUI library behind them: menus, trees,
dialogs, a widget the view can sit in. GLFW, Pygame and GLUT are
window-and-input libraries with none of that, so there is nothing for an
embedding example to embed the view *in*; an application on those draws its own
interface with `OpenGLContext.ui`, which `oglc-ui-demo` already shows.

| Toolkit | Example | Embedding call | Loop |
| --- | --- | --- | --- |
| Tk | `examples/tk_viewer.py` | `TkContext(parent=frame)` | `root.mainloop()`, driving `loopIteration()` |
| Qt | `openglcontext-qt/examples/qt_viewer.py` | `context.container(parent)` | `QGuiApplication.exec()` |
| wx | `examples/wx_viewer.py` | `wxContext(parent, ...)` | `wx.App.MainLoop()` |

The same small application in each, so the three can be read against one
another:

- **A view**, filling most of the window: `ViewerContext`, which is what
  `oglc-view` is, so the example inherits every format the adapters read, the
  PBR pass, auto-framing, the walk/examine navigation and the async loader.
- **A scenegraph panel** beside it: the nodes of the loaded scene as a tree in
  the toolkit's own tree control -- `ttk.Treeview`, `QTreeView`, `wx.TreeCtrl` --
  expandable, showing the selected node's type and DEF name.
- **A menu**: *Open file…*, *Open URL…*, *Quit*, on the toolkit's own menu bar,
  with the toolkit's own file chooser and text prompt.

Opening is `context.openSource(path_or_url)`, which already exists and already
loads on a worker thread, so a slow download leaves the previous scene on screen
and the window keeps drawing.

Each example should be about a page of its toolkit's own code plus four engine
calls. That ratio is the thing being demonstrated: if an example needs more
engine than that, the engine is missing something.

## What the engine is missing

One piece, and it belongs in the engine rather than in three copies inside three
examples.

**A scenegraph outline model** -- `OpenGLContext/outline.py`, beside
`visitor.py`, whose `children()` is the traversal it walks. A plain object over
a scenegraph: rows of `(depth, node, label, expandable)`, a set of expanded
paths, a selection, and `toggle(row)`. No GL, no toolkit, no events, so it is
covered outright, and one model feeds a `ttk.Treeview`, a `QTreeView` and a
`wx.TreeCtrl` alike -- which is what keeps each example's tree binding to a
dozen lines. The label is the node's DEF name where the file gave one, else its
node type.

An inspector of the running scene is a thing a game wants too -- it is what the
developer overlay would show if it could -- so this is engine API, not example
code.

Everything else is there: the menus, file choosing and prompting are the host
toolkit's, and the view, the formats, the framing and the loading are the
engine's.

## Where they live

In the repository that owns the toolkit, next to the code they demonstrate:
`openglcontext/examples/` for Tk and wx, whose backends ship here, and
`openglcontext-qt/examples/` for the Qt one, since PySide6 is that
distribution's dependency and not this one's.

Each is a single file that runs directly:

```bash
python examples/tk_viewer.py model.glb
python examples/wx_viewer.py model.glb
python examples/qt_viewer.py model.glb        # in openglcontext-qt
```

No `[project.scripts]` entries: these are read as much as run, and a console
command whose purpose is to be read is a command in the way of the ones that do
work.

## Testing

The examples are held to the same bar as the rest of the suite rather than left
as prose that happens to be executable.

- The outline model is unit-tested directly, with no window -- which is what
  makes it engine API rather than example code.
- Each example is driven headless for a few frames through the auto-exit capture
  path (`OPENGLCONTEXT_AUTO_EXIT_FRAMES`), the same way `tests/test_all_scripts.py`
  drives the demo scripts, and the frame is checked to be non-empty.
- The menu actions are exercised by calling the example's own command handlers
  and asserting what they did -- that *Open* reached `openSource`, that the tree
  refilled from the new scene, that *Quit* released the window. No file chooser
  is opened and no human clicks anything.
- **wx is written from the API and left unverified** until it runs on a machine
  with wxPython, which will not build in this container. That is stated in the
  example's own docstring, not only here.

## Documentation

A new `docs/embedding.html`, linked from `docs/documentation.html` and from
`docs/structure.html` where the backends are described: what each toolkit's
embedding call is, which of them owns the loop, the four engine calls the three
programs share, and one paragraph saying where an application on GLFW, Pygame or
GLUT gets its interface instead. `openglcontext-qt/README.md` points at its own
example from the section that currently shows the embedding snippet inline.

## Order of work

1. `outline.py` and its tests -- nothing else can be written against it until it
   exists, and it is the piece all three examples share.
2. `examples/tk_viewer.py`, since Tk needs nothing installed and the whole loop
   can be verified here.
3. `openglcontext-qt/examples/qt_viewer.py`, verified under `QT_QPA_PLATFORM=xcb`.
4. `examples/wx_viewer.py`, written and marked unverified.
5. `docs/embedding.html`, and the two pages that link to it.

## What landed

The three programs ship **inside the repositories that own their toolkits**,
rather than as `examples/` scripts or as distributions of their own:
`OpenGLContext/demos/tk_viewer.py` and `wx_viewer.py`, and
`OpenGLContext_qt/demos/qt_viewer.py`.  So they are installed with the engine
and reachable from a frozen bundle or an installed `.deb` without any packaging
of their own, and they are run as modules:

```bash
python -m OpenGLContext.demos.tk_viewer model.glb
python -m OpenGLContext.demos.wx_viewer model.glb
python -m OpenGLContext_qt.demos.qt_viewer model.glb
```

No `[project.scripts]` entries, for the reason the plan gives: a console command
whose purpose is to be read is in the way of the ones that do work.

### The engine gained two things, not one

`OpenGLContext/outline.py` as planned -- `SceneOutline`, rows of
`(path, node, depth, field, defName, nodeType, expandable)`, an expanded set, a
selection, and pydispatcher subscriptions on the node-valued fields so the rows
follow the scene.  Two decisions the plan did not settle:

- **Children are the node-valued fields**, not `visitor.children`.  The
  rendering traversal does not descend into a `Shape`'s `geometry` and
  `appearance`, and those are exactly what an inspector is for.  What is left
  out is decided by the field rather than by a list of names: a **weak** field
  points back into the scene rather than down it (every node's `root`), and a
  value that is not a `Node` is not a row (a scenegraph's `routes`).
- **`nodeSummary(node)`** came with it -- the values a node carries in its own
  right, as `(field, text)` pairs -- because the panel beside the tree is the
  same job and three copies of that loop is three copies too many.

`OpenGLContext.viewer.viewerFor(backend)` is the second, and the plan's own test
is what asked for it: `ViewerContext` is composed over whichever backend the
*environment* chose, so a Tk program embedding one had four lines of plug-in
lookup to write before it could subclass anything.  `viewerFor('tk')` answers
the viewer over the named backend, cached so asking twice gives one class.

### What the demos had to be told that a full-window program does not

Four things, all of them now in `docs/embedding.html` because none of them is
guessable:

- **`hasSceneToShow()` wants overriding.**  A viewer with no source opens its
  shelf, which is right for `oglc-view` and wrong over an application's own File
  menu.  The engine already documented the override for a host with scenes of
  its own; an embedded view is that case.
- **`deferRedraw` is the host's to set** where the host drives the loop.  Every
  backend's `MainLoop` sets it so a burst of input costs one frame rather than
  one frame each, and a host calling `loopIteration` is standing in for that
  loop.  Not under wx, where nothing calls `loopIteration` and the synchronous
  redraw is what draws at all.
- **A finished view does not end the host's process** -- deliberately, on Tk and
  Qt -- so the host has to notice.  Tk's `loopIteration()` answers False, which
  is the per-frame callback the demo already has; Qt drives its own timer and
  offers no such hook, so its demo overrides `OnQuit`.
- **wx quits differently.**  `wxContext.OnQuit` ends the process, where the Tk
  and Qt contexts close an embedded view and leave the host running.  That is a
  **parity gap**, not a wx limitation: neither `ContextMainLoop` nor the context
  records whether it made the frame it lives in, which is what the other two
  decide on.  Left as it is and written down in the demo and the docs, since
  wxPython does not build here and the fix would ship unverified.

### Testing

`tests/unit/test_outline.py` covers the model outright: 43 cases, no GL and no
toolkit, 100% of `outline.py`.  `tests/unit/test_viewer_for_backend.py` covers
the composition.

The Tk demo is driven through `tests/helpers/_tk_viewer_drive.py`, one
subprocess per step under a real X server, and the Qt one the same way through
`openglcontext-qt/tests/helpers/_qt_viewer_drive.py`.  Seven steps each: the
scene reaches the tree, opening a row opens it in the model, selecting one names
the node, a change to it reaches the panel, the File menu opens a scene through
the engine, quitting releases the context, and a view that finishes takes the
host's window with it.  A subprocess per step because a Tk application is a
process with one interpreter, and because a second GL context in one process
picks up the first one's programs.

wx is written from the API and **unverified by running**, stated in its own
docstring as the plan asked.

Four defects in the demos were found by that harness rather than by reading:
setting a new scene on the outline clears its `dirty` flag, so a tree refilled
only on `dirty` never filled at all; refilling a `ttk.Treeview` drops the
keyboard focus, so the *next* collapse was applied to the root; a placeholder
item's id parsed as the root's path; and a test that waits *frames* rather than
seconds gives a loader thread no wall time at all -- an iteration with nothing to
draw returns at once, and six hundred of them took 0.0 s.

## Shipping one (2026-09-07)

The demos come with the recipe for both ways of delivering an application built
on the engine, in `OpenGLContext/demos/packaging/` and
`OpenGLContext_qt/demos/packaging/`: a PyInstaller `.spec` and its `entry.py`,
a `build-deb.sh`, and a `deb-project/` that turns a demo into a distribution.
Both ship in the wheel, since somebody who installed the engine rather than
cloning it should have them.

**A demo is not a command, and a package needs one.** `OpenGLContext.demos`
declares no console scripts on purpose, so `deb-project/pyproject.toml` is the
smallest thing that gives one: a name, a dependency and a `[project.scripts]`
line, with no code of its own. That is also the honest shape for a reader --
you do not package "the engine", you package your application, and your
application is a distribution.

Both were built and run rather than written and hoped for, and getting the Tk
bundle to render found **four defects, three of them shipped**:

- **`unused_backend_modules(keep=['tk'])` raised**: `BACKEND_MODULES` predates
  the Tk backend and had no entry for it, so the one call an embedded Tk
  application makes was the one call that could not be made. `egl` was missing
  for the same reason. `tkinter` is named as Tk's module although it is the
  standard library, because a freezer follows the import and brings the whole
  of Tcl/Tk -- megabytes a GLFW bundle has no use for.
- **`oglc-deb` stripped Tk out of the interpreter it shipped.** `PRUNE` removes
  what an application "cannot reach", and Tk is *part of CPython* rather than a
  wheel in the environment, so a Tk package installed and then failed to start.
  `appdir.BACKEND_RUNTIME` and `prune_patterns(keep=...)` say what a backend
  needs kept, and `oglc-deb --backend NAME` is how a package says which it is.
- **`oglc-deb` wrote a package that could not run, with its own default build
  directory.** A virtual environment records where it was made in absolute
  form; `relocate` was given the *relative* staging path, matched nothing in
  the `#!` lines and pyvenv.cfg, and rewrote them into
  `/where/you/built//opt/<package>/...`, leaving the interpreter symlink
  pointing into the build tree. Absolute from `build` down, and `relocate`
  takes its arguments as absolute whatever it is handed.
- **PyOpenGL's PyInstaller hook missed two families of module reached by name**
  -- `OpenGL.Tk.context.IMPLEMENTATIONS` (GLX or WGL, chosen from the windowing
  system Tk turns out to be on) and `OpenGL.raw.<api>._errors` (which every
  binding `_declarations` builds imports, and only GL's and EGL's are imported
  statically anywhere). The second is not a Tk problem: any frozen application
  reaching GLU, GLX, WGL or an ES binding hit it. Both are now read from the
  same tables the running library uses, so an API or an implementation added to
  PyOpenGL is carried without an edit to the hook.

The fourth was mine: `viewerFor('tk')` imported `sceneviewer`, whose module body
resolved the *default* backend -- so asking for the backend that is there failed
for the sake of the one that is not, which is exactly a one-toolkit bundle.
`ViewerContext` is now built by a module `__getattr__` on first use, which is
the same reasoning `OpenGLContext/viewer/__init__.py` already applied one level
up and had not carried down.

Verified end to end in this container: the frozen bundle renders a frame
(132 MB, with Tcl/Tk in it and no Qt, wx or pygame), and the `.deb` installs,
puts `oglc-tk-viewer` in `/usr/bin` with a desktop entry, runs from there and
renders one. The Qt pair is written from the same options against the same
tools and is **not built**, a Qt bundle being large enough that doing it on
every push would be most of a test run; what drifts is held instead --
`test_demo_packaging.py` in each distribution resolves the `module:attribute`
strings the tables name, so a renamed module fails there rather than in a build
nobody runs until a release.
