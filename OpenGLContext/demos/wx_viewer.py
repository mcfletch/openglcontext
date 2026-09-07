#! /usr/bin/env python3
"""A view inside a wx application: a menu, a scene tree, and the engine's viewer

Run it, with a scene to open or without one::

    python -m OpenGLContext.demos.wx_viewer model.glb
    python -m OpenGLContext.demos.wx_viewer https://example.com/scene.gltf

**Written from the API and not verified by running.**  wxPython does not build
in the container this engine is developed in, so unlike its Tk and Qt siblings
this program has never been on a screen here.  Read it as what the API says
rather than as what a machine has confirmed, and see ``plans/BACKEND-PARITY.md``
for what else about the wx backend that applies to.

On GTK3, wxPython makes its GL contexts through EGL, so ``PYOPENGL_PLATFORM``
must be ``egl`` for PyOpenGL to track the current context.  ``wxcontext`` sets
it when it can, which is why it is imported here before anything imports
``OpenGL`` -- see :mod:`OpenGLContext.wxcontext`.

The whole of the engine in here is three calls, and the rest is wx:

* :func:`OpenGLContext.viewer.viewerFor` gives the viewer over the wx backend.
  The context **is** a ``wx.glcanvas.GLCanvas``, so it goes straight into a
  sizer beside the application's other controls; there is no wrapper.
* :meth:`~OpenGLContext.viewer.sceneviewer.SceneViewerMixin.openSource` opens a
  path or a URL, on a worker thread.
* :class:`~OpenGLContext.outline.SceneOutline` is the scene as rows, which fill
  the ``wx.TreeCtrl``.

There is no fourth: **wx needs no loop call from the host.**  The canvas renders
from its own paint and idle events, so ``wx.App.MainLoop()`` drives the engine
by itself.  The Tk demo calls ``loopIteration`` from a timer and the Qt one
starts the backend's own timer; this one starts nothing.  For the same reason
``deferRedraw`` stays off here: it exists to stop an input event rendering where
it is handled, which is worth doing when a loop call is about to render anyway,
and here there is no such call.

**Quitting differs on this backend.**  The Tk and Qt contexts treat a view
inside somebody else's window as a view -- quitting one closes it and leaves the
host running -- while the wx context ends the process, as
:meth:`OpenGLContext.context.Context.OnQuit` does everywhere by default.  So the
Escape key and the engine's own Quit end this application rather than closing
the view in it.  The host's own Quit, below, closes the frame instead.

The same program is written for Tk in :mod:`OpenGLContext.demos.tk_viewer` and
for Qt in ``OpenGLContext_qt.demos.qt_viewer``.
"""
import sys

# Before OpenGL is imported by anything else: on GTK3 this is what settles
# PYOPENGL_PLATFORM=egl, without which shader rendering has no context to track.
try:
    from OpenGLContext import wxcontext                          # noqa: F401
except ImportError as error:
    # The distribution is `wxPython`, which the import name does not say.
    raise SystemExit(
        'This demo needs wxPython:\n    %s\n    pip install wxPython' % (error,)
    ) from None

import wx                                                        # noqa: E402
from pydispatch import dispatcher                                # noqa: E402

from OpenGLContext.outline import SceneOutline, nodeSummary      # noqa: E402
from OpenGLContext.viewer import viewerFor                       # noqa: E402

#: What the file chooser offers, which is what the viewer's adapters read.
SCENE_FILES = ('Scenes|*.gltf;*.glb;*.wrl;*.wrz;*.obj;*.json|Every file|*.*')

#: Menu command ids.
ID_OPEN_URL = wx.NewIdRef()


class SceneView(viewerFor('wx')):  # type: ignore[misc]  # base chosen at run time
    """The engine's viewer, as one widget in somebody else's window"""

    #: Called on the GUI thread once a scene has been built, if a host set it.
    onScene = None

    def hasSceneToShow(self):
        """The host opens scenes, so the engine's launch screen stays down

        Starting with nothing to show is a viewer with its shelf open, which is
        right for ``oglc-view`` and wrong here: this application has a File
        menu of its own, and a second menu over the top of the first is no
        welcome at all.
        """
        return True

    def onSceneReady(self):
        """A scene has been built and swapped in -- on the render thread

        Which is wx's own thread here, since the canvas renders from its paint
        and idle events, so a host told from here may touch its widgets.
        """
        super().onSceneReady()
        if self.onScene is not None:
            self.onScene()


class ViewerFrame(wx.Frame):
    """A window with a menu, a scene tree, and a view of the scene"""

    def __init__(self, source=None):
        wx.Frame.__init__(self, None, -1, 'OpenGLContext in wx',
                          size=(960, 600))
        #: Set while the tree is being refilled, so the expand and collapse
        #: events that refilling itself raises are not read as requests.
        self.filling = False
        self.buildMenu()
        splitter = wx.SplitterWindow(self, style=wx.SP_LIVE_UPDATE)
        panel = self.buildPanel(splitter)

        # The context *is* the canvas: it goes in the layout as any other
        # window does, and it opens no window of its own.
        self.view = SceneView(splitter, size=(720, 560))
        splitter.SplitVertically(panel, self.view, 240)
        splitter.SetMinimumPaneSize(160)

        #: The scene as rows.  The notice can arrive on the loader's worker
        #: thread, and wx's widgets belong to wx's thread, so `wx.CallAfter`
        #: is how it gets back to the right one.
        self.outline = SceneOutline(
            self.view.sg, onChange=lambda: wx.CallAfter(self.fillTree))
        #: The node the detail panel is following, if any.
        self.watching = None

        # Wired once there is an outline for it to work on, since it runs as
        # soon as anything is opened.
        self.view.onScene = self.onSceneReady

        self.Bind(wx.EVT_CLOSE, self.onClose)
        self.showDetail()
        if source:
            self.open(source)

    # -- building the window ----------------------------------------------
    def buildMenu(self):
        """The application's own menu bar, over the engine's two entry points"""
        fileMenu = wx.Menu()
        fileMenu.Append(wx.ID_OPEN, '&Open file…\tCtrl+O')
        fileMenu.Append(ID_OPEN_URL, 'Open &URL…')
        fileMenu.AppendSeparator()
        fileMenu.Append(wx.ID_EXIT, '&Quit\tCtrl+Q')
        menubar = wx.MenuBar()
        menubar.Append(fileMenu, '&File')
        self.SetMenuBar(menubar)
        self.Bind(wx.EVT_MENU, self.onOpenFile, id=wx.ID_OPEN)
        self.Bind(wx.EVT_MENU, self.onOpenURL, id=ID_OPEN_URL)
        self.Bind(wx.EVT_MENU, lambda event: self.Close(), id=wx.ID_EXIT)

    def buildPanel(self, parent):
        """The tree of the scene, and what the selected node holds"""
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.tree = wx.TreeCtrl(
            panel, style=wx.TR_HAS_BUTTONS | wx.TR_SINGLE | wx.TR_LINES_AT_ROOT)
        sizer.Add(self.tree, 1, wx.EXPAND)
        self.detail = wx.TextCtrl(
            panel, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_DONTWRAP,
            size=(-1, 180))
        sizer.Add(self.detail, 0, wx.EXPAND)
        self.status = wx.StaticText(panel, label='')
        sizer.Add(self.status, 0, wx.EXPAND)
        panel.SetSizer(sizer)

        self.tree.Bind(wx.EVT_TREE_SEL_CHANGED, self.onSelect)
        self.tree.Bind(wx.EVT_TREE_ITEM_EXPANDED, self.onOpenRow)
        self.tree.Bind(wx.EVT_TREE_ITEM_COLLAPSED, self.onCloseRow)
        return panel

    # -- the menu ---------------------------------------------------------
    def onOpenFile(self, event=None):
        with wx.FileDialog(self, 'Open a scene', wildcard=SCENE_FILES,
                           style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as chooser:
            if chooser.ShowModal() == wx.ID_OK:
                self.open(chooser.GetPath())

    def onOpenURL(self, event=None):
        with wx.TextEntryDialog(self, 'Address of a scene:', 'Open URL') as ask:
            if ask.ShowModal() == wx.ID_OK and ask.GetValue():
                self.open(ask.GetValue())

    def open(self, source):
        """Show *source*, which may be a path or a URL

        The load runs on a worker thread, so this returns at once and the
        window keeps drawing what it already has until the scene arrives.
        """
        self.status.SetLabel('Loading %s' % (source,))
        self.view.openSource(source)

    def onClose(self, event=None):
        """Let go of the scene and the GL context as the window goes

        ``releaseWindow`` is what gives the driver back every texture, buffer
        and shader the engine uploaded, and it has to happen while the canvas
        is still whole enough to be made current.
        """
        self.watch(None)
        self.outline.close()
        self.view.releaseWindow()
        self.Destroy()

    # -- the scene --------------------------------------------------------
    def onSceneReady(self):
        """A scene the worker thread loaded has been built and swapped in"""
        self.outline.root = self.view.sg
        self.status.SetLabel(str(self.view.source or ''))
        self.fillTree()

    # -- the tree ---------------------------------------------------------
    def rowLabel(self, row):
        """A row in one column: the node, and the field it hangs from

        A ``wx.TreeCtrl`` has no second column -- that is
        ``wx.dataview.TreeListCtrl`` -- and the field a node hangs from is worth
        seeing, so it goes in the label where it says anything the tree shape
        does not.
        """
        if row.field in (None, 'children'):
            return row.label
        return '%s  (%s)' % (row.label, row.field)

    def fillTree(self):
        """Put the outline's rows in the tree, as it stands now"""
        rows = self.outline.rows
        selected = self.outline.selection
        self.filling = True
        self.tree.Freeze()
        try:
            self.tree.DeleteAllItems()
            items = {}
            for row in rows:
                if not row.path:
                    item = self.tree.AddRoot(self.rowLabel(row))
                else:
                    item = self.tree.AppendItem(items[row.path[:-1]],
                                                self.rowLabel(row))
                self.tree.SetItemData(item, row.path)
                items[row.path] = item
                if row.expandable and row.path not in self.outline.expanded:
                    # A tree draws the button for an item that has children, so
                    # a row waiting to be opened is given one to stand for them.
                    self.tree.AppendItem(item, '…')
            for row in rows:
                if row.expandable and row.path in self.outline.expanded:
                    self.tree.Expand(items[row.path])
            if selected is not None and selected in items:
                self.tree.SelectItem(items[selected])
        finally:
            self.tree.Thaw()
            self.filling = False

    def pathOf(self, item):
        """The outline path an item stands for, or None where it stands for
        none -- the placeholder under a closed row, or no item at all"""
        if not item or not item.IsOk():
            return None
        return self.tree.GetItemData(item)

    def onOpenRow(self, event):
        """The button beside a row was clicked: open it in the model too"""
        if self.filling:
            return
        path = self.pathOf(event.GetItem())
        if path is not None:
            self.outline.expand(path)
            self.fillTree()

    def onCloseRow(self, event):
        if self.filling:
            return
        path = self.pathOf(event.GetItem())
        if path is not None:
            self.outline.collapse(path)
            self.fillTree()

    def onSelect(self, event=None):
        if self.filling:
            return
        self.outline.select(self.pathOf(self.tree.GetSelection()))
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
        """A field of the selected node changed, on whichever thread did it"""
        wx.CallAfter(self.showDetail)

    def showDetail(self):
        """Redraw the panel: what the selected node is, and what it holds"""
        row = self.outline.selectedRow
        if row is None:
            lines = ['Nothing selected']
        else:
            lines = ['%s %s' % (row.nodeType, row.defName) if row.defName
                     else row.nodeType]
            lines += ['%s = %s' % pair for pair in nodeSummary(row.node)]
        self.detail.SetValue('\n'.join(lines))


class ViewerApplication(wx.App):
    """The application, which owns the loop the engine draws inside"""

    def __init__(self, source=None):
        self.source = source
        wx.App.__init__(self, False)

    def OnInit(self):
        wx.InitAllImageHandlers()
        frame = ViewerFrame(source=self.source)
        self.SetTopWindow(frame)
        frame.Show(True)
        frame.view.SetFocus()
        return True


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # wx renders from the canvas's own paint and idle events, so this is the
    # whole of the loop: there is nothing for the host to drive.
    ViewerApplication(source=argv[0] if argv else None).MainLoop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
