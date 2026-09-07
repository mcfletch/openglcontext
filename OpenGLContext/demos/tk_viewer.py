#! /usr/bin/env python3
"""A view inside a Tk application: a menu, a scene tree, and the engine's viewer

Run it, with a scene to open or without one::

    python -m OpenGLContext.demos.tk_viewer model.glb
    python -m OpenGLContext.demos.tk_viewer https://example.com/scene.gltf

Tkinter ships with CPython, so this needs nothing installed.  It does need an X
display: Tk has no Wayland backend, so a headless machine runs it under
``xvfb-run``.

The whole of the engine in here is four calls, and the rest is Tk:

* :func:`OpenGLContext.viewer.viewerFor` gives the viewer over the Tk backend,
  built with ``parent=`` so it sits in this application's window rather than
  opening one of its own.
* :meth:`~OpenGLContext.viewer.sceneviewer.SceneViewerMixin.openSource` opens a
  path or a URL, on a worker thread.
* :class:`~OpenGLContext.outline.SceneOutline` is the scene as rows, which fill
  the ``ttk.Treeview``.
* :meth:`~OpenGLContext.tkcontext.TkContext.loopIteration` draws one frame, from
  Tk's own timer -- the host owns the loop, so the engine is a guest in it.

The engine's own screens stay on their keys: F1 for the shelf of models, F10 for
the render settings, F6 for the controls.  An application is free to bind none
of them (``LIBRARY_KEY = ''`` and its siblings) and put the same things in its
own menus.

The same program is written for wx in :mod:`OpenGLContext.demos.wx_viewer` and
for Qt in ``OpenGLContext_qt.demos.qt_viewer``.
"""
import sys
import tkinter
from tkinter import filedialog, simpledialog, ttk

from pydispatch import dispatcher

from OpenGLContext.outline import SceneOutline, nodeSummary
from OpenGLContext.viewer import viewerFor

#: How often Tk is asked to draw a frame, in milliseconds.  The engine's own
#: wait paces the frame rate; this only has to be small enough not to be what
#: limits it.
FRAME_INTERVAL = 1

#: What the file chooser offers, which is what the viewer's adapters read.
SCENE_FILES = [('Scenes', '*.gltf *.glb *.wrl *.wrz *.obj *.json'),
               ('Every file', '*')]


class SceneView(viewerFor('tk')):  # type: ignore[misc]  # base chosen at run time
    """The engine's viewer, as one widget in somebody else's window"""

    def hasSceneToShow(self):
        """The host opens scenes, so the engine's launch screen stays down

        Starting with nothing to show is a viewer with its shelf open, which is
        right for ``oglc-view`` and wrong here: this application has a File
        menu of its own, and a second menu over the top of the first is no
        welcome at all.
        """
        return True


def rowId(path):
    """The tree item id for an outline path; :func:`pathOf` is its inverse"""
    return 'row:' + '.'.join(str(index) for index in path)


def pathOf(itemId):
    """The outline path an item id stands for, or None where it stands for none

    Not every item in the tree is a row of the outline: a row waiting to be
    opened holds a placeholder, and the empty string is Tk's way of saying that
    nothing is selected at all.
    """
    kind, _, indices = itemId.partition(':')
    if kind != 'row':
        return None
    return tuple(int(index) for index in indices.split('.')) if indices else ()


class ViewerApplication:
    """A window with a menu, a scene tree, and a view of the scene"""

    def __init__(self, source=None):
        self.root = tkinter.Tk()
        self.root.title('OpenGLContext in Tk')
        self.root.geometry('960x600')
        self.root.protocol('WM_DELETE_WINDOW', self.onQuit)

        self.buildMenu()
        panes = ttk.PanedWindow(self.root, orient=tkinter.HORIZONTAL)
        panes.pack(fill=tkinter.BOTH, expand=True)
        panes.add(self.buildPanel(panes), weight=1)

        # The view goes in a frame of the application's own, which is what
        # `parent` means: the context opens no window, and the loop is not its
        # to run.  Everything else about it is the viewer `oglc-view` is.
        holder = ttk.Frame(panes)
        panes.add(holder, weight=3)
        self.context = SceneView(parent=holder, size=(720, 560))
        # This loop is the host's, so the frames are too: with this set, an
        # input event asks for a redraw instead of rendering where it was
        # handled, and a burst of them costs one frame rather than one each.
        # Every backend's own `MainLoop` does the same, for the same reason.
        self.context.deferRedraw = True

        #: The scene as rows.  It notices a change on whichever thread makes
        #: one; `onFrame` below asks whether the tree wants refilling, which is
        #: the plainest way back onto Tk's own thread.
        self.outline = SceneOutline(self.context.sg)
        #: The scene the tree was filled from, so one that arrives on the
        #: worker thread is noticed as it is swapped in.
        self.shownScene = None
        #: The node the detail panel is following, if any.
        self.watching = None

        self.showDetail()
        if source:
            self.open(source)
        self.root.after(FRAME_INTERVAL, self.onFrame)

    # -- building the window ----------------------------------------------
    def buildMenu(self):
        """The application's own menu bar, over the engine's two entry points"""
        menubar = tkinter.Menu(self.root)
        fileMenu = tkinter.Menu(menubar, tearoff=False)
        fileMenu.add_command(label='Open file…', accelerator='Ctrl+O',
                             command=self.onOpenFile)
        fileMenu.add_command(label='Open URL…', command=self.onOpenURL)
        fileMenu.add_separator()
        fileMenu.add_command(label='Quit', accelerator='Ctrl+Q',
                             command=self.onQuit)
        menubar.add_cascade(label='File', menu=fileMenu)
        self.root.config(menu=menubar)
        self.root.bind_all('<Control-o>', self.onOpenFile)
        self.root.bind_all('<Control-q>', self.onQuit)

    def buildPanel(self, parent):
        """The tree of the scene, and what the selected node holds"""
        panel = ttk.Frame(parent)
        self.tree = ttk.Treeview(panel, columns=('field',), selectmode='browse')
        self.tree.heading('#0', text='Node')
        self.tree.heading('field', text='Field')
        self.tree.column('field', width=90, stretch=False)
        self.tree.pack(fill=tkinter.BOTH, expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.onSelect)
        self.tree.bind('<<TreeviewOpen>>', self.onOpenRow)
        self.tree.bind('<<TreeviewClose>>', self.onCloseRow)

        self.detail = tkinter.Text(panel, height=10, width=44, wrap='none',
                                   state='disabled')
        self.detail.pack(fill=tkinter.X)
        self.status = ttk.Label(panel, text='', anchor='w')
        self.status.pack(fill=tkinter.X)
        return panel

    # -- the menu ---------------------------------------------------------
    def onOpenFile(self, event=None):
        chosen = filedialog.askopenfilename(
            parent=self.root, title='Open a scene', filetypes=SCENE_FILES)
        if chosen:
            self.open(chosen)

    def onOpenURL(self, event=None):
        typed = simpledialog.askstring('Open URL', 'Address of a scene:',
                                       parent=self.root)
        if typed:
            self.open(typed)

    def onQuit(self, event=None):
        """Let go of the scene, the GL context and the window, in that order

        The host owns the loop, so quitting is destroying the window rather
        than ending the process, and ``releaseWindow`` is what gives the driver
        back every texture, buffer and shader the engine uploaded.
        """
        self.watch(None)
        self.outline.close()
        self.context.releaseWindow()
        self.root.destroy()

    def open(self, source):
        """Show *source*, which may be a path or a URL

        The load runs on a worker thread, so this returns at once and the
        window keeps drawing what it already has until the scene arrives.
        """
        self.status.config(text='Loading %s' % (source,))
        self.context.openSource(source)

    # -- the frame --------------------------------------------------------
    def onFrame(self):
        """One iteration of the engine's loop, driven from Tk's timer

        ``loopIteration`` answers False once the view is finished -- quit from
        inside, or its window gone.  A view in somebody else's window never
        ends the host's process, so the host decides what to do about it; here
        the view is the reason the window exists, so the window goes with it.
        """
        if not self.context.loopIteration():
            self.root.destroy()
            return
        if self.context.sg is not self.shownScene:
            # A scene the worker thread loaded has been built and swapped in.
            # Giving it to the outline walks it there and then, so there is
            # nothing left for the `dirty` test below to notice: a new scene
            # refills the tree from here.
            self.shownScene = self.outline.root = self.context.sg
            self.status.config(text=str(self.context.source or ''))
            self.fillTree()
        elif self.outline.dirty:
            self.fillTree()
        self.root.after(FRAME_INTERVAL, self.onFrame)

    # -- the tree ---------------------------------------------------------
    def fillTree(self):
        """Put the outline's rows in the Treeview, as it stands now

        The rows are replaced wholesale rather than reconciled, so the
        selection and the keyboard focus are put back afterwards: they are
        Tk's, and deleting an item takes them with it.
        """
        selected, focused = self.outline.selection, self.tree.focus()
        self.tree.delete(*self.tree.get_children())
        for row in self.outline.rows:
            self.tree.insert(
                rowId(row.path[:-1]) if row.path else '',
                'end', iid=rowId(row.path), text=row.label,
                values=(row.field or '',),
                open=row.path in self.outline.expanded,
            )
            if row.expandable and row.path not in self.outline.expanded:
                # A Treeview draws the arrow for a row that has children, so a
                # row waiting to be opened is given one to stand for them.
                self.tree.insert(rowId(row.path), 'end', text='…')
        if selected is not None:
            self.tree.selection_set(rowId(selected))
        if self.tree.exists(focused):
            self.tree.focus(focused)

    def onOpenRow(self, event=None):
        """The arrow beside a row was clicked: open it in the model too"""
        path = pathOf(self.tree.focus())
        if path is not None:
            self.outline.expand(path)
            self.fillTree()

    def onCloseRow(self, event=None):
        path = pathOf(self.tree.focus())
        if path is not None:
            self.outline.collapse(path)
            self.fillTree()

    def onSelect(self, event=None):
        chosen = self.tree.selection()
        self.outline.select(pathOf(chosen[0]) if chosen else None)
        self.watch(self.outline.selected)
        self.showDetail()

    # -- watching the selected node ---------------------------------------
    def watch(self, node):
        """Follow *node*'s fields, and stop following whatever came before

        Every field of every node announces a change through pydispatcher, so
        a panel showing one node keeps up with an animation moving it, a route
        firing into it, or anything else editing the scene.
        """
        if self.watching is not None:
            dispatcher.disconnect(self.onNodeChanged, sender=self.watching)
        self.watching = node
        if node is not None:
            dispatcher.connect(self.onNodeChanged, sender=node)

    def onNodeChanged(self, signal=None, sender=None, **named):
        """A field of the selected node changed, on whichever thread did it

        Tk's widgets belong to Tk's thread, so this asks for the panel to be
        redrawn there rather than drawing it here.
        """
        self.root.after_idle(self.showDetail)

    def showDetail(self):
        """Redraw the panel: what the selected node is, and what it holds"""
        row = self.outline.selectedRow
        if row is None:
            lines = ['Nothing selected']
        else:
            lines = ['%s %s' % (row.nodeType, row.defName) if row.defName
                     else row.nodeType]
            lines += ['%s = %s' % pair for pair in nodeSummary(row.node)]
        self.detail.config(state='normal')
        self.detail.delete('1.0', 'end')
        self.detail.insert('1.0', '\n'.join(lines))
        self.detail.config(state='disabled')

    def run(self):
        self.root.mainloop()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    ViewerApplication(source=argv[0] if argv else None).run()
    return 0


if __name__ == '__main__':
    sys.exit(main())
