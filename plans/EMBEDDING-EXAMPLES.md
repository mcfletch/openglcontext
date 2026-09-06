# A viewer application, in each GUI toolkit

Status: **Planned** (2026-09-06).

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
