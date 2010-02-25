#! /usr/bin/env python
'''wxPython-based meta-testing framework...
'''
from OpenGLContext import testingcontext
testingcontext.PREFERENCELIST = ('wx',)
import wx
import weakref

class TestFrame( wx.Frame ):
    """Base frame for the wx-based test framework

    This is to be reminiscent of the wxPython demo in
    a lot of ways.
        Left-side, a list control with the available tests
        Right-upper side, the Context window, hosted by a panel
        Right-lower side, an output window
    """
    currentTestIndex = 0
    def __init__(
        self, parent=None, id=-1, title="OpenGLContext Visual Shell",
        pos = wx.DefaultPosition, size = (600,450),
        style = wx.DEFAULT_FRAME_STYLE, name = "mainframe",
    ):
        wx.Frame.__init__( self, parent, id, title, pos, size, style, name )
        self.CreateControls( style )
        icons = self.context.getDefaultIcons()
        if icons:
            self.SetIcons( icons )

    def CreateShellEnvironment( self ):
        """Create the working shell environment"""
        from OpenGLContext import arrays
        from OpenGLContext.scenegraph import basenodes, extrusions
        from OpenGLContext import utilities, vectorutilities, displaylist
        from OpenGLContext.loaders import loader, vrml97
        from pydispatch import dispatcher
        environment = {
            'load': loader.Loader.load,
            'dump': vrml97.defaultHandler().dump,
            'frame': weakref.proxy(self),
            'context': weakref.proxy(self.context),
            'DisplayList': displaylist.DisplayList,
            'crossProduct': vectorutilities.crossProduct,
            'crossProduct4':vectorutilities.crossProduct4,
            'magnitude':vectorutilities.magnitude,
            'normalise':vectorutilities.normalise,
            'pointNormal2Plane':utilities.pointNormal2Plane,
            'plane2PointNormal':utilities.plane2PointNormal,
            'rotMatrix':utilities.rotMatrix,
            'dispatcher':dispatcher,
        }
        for module in basenodes, extrusions, arrays:
            for name in dir(module):
                if name not in environment:
                    environment[name] = getattr( module, name )
        return environment
    def CreateControls( self, style=None ):
        """Create the controls for the frame"""
        self.shellSplitter = wx.SplitterWindow( self, -1, style = wx.SP_3DSASH)
        self.CreateContext( self.shellSplitter )
##		self.splitter = wx.SplitterWindow(self.shellSplitter, -1, style = wx.SP_3DSASH)
##		self.splitter.SplitVertically(
##			self.CreateSelectionControl( self.splitter ),
##			self.CreateContext( self.splitter ),
##			180,
##		)
        self.shellSplitter.SplitHorizontally(
##			self.splitter,
            self.context,
            self.CreateShellControl( self.shellSplitter ),
            -180,
        )
        self.CreateMenus()
        self.Layout()
    def CreateMenus( self ):
        """Create our application menu-bars"""
        # Prepare the menu bar
        menuBar = wx.MenuBar()

        menuData = [
            ('&File', [
                ('&Open', 'OnOpenCommand', """Open VRML97 file replacing current scene"""),
                ('&Add', 'OnAddCommand', """Add VRML97 file contents to current scene""" ),
                ('E&xit', 'OnExitCommand', """Exit the browser"""),
            ]),
        ]
        for menuName, subElements in menuData:
            menu = wx.Menu()
            for label, method, description in subElements:
                ID = wx.NewId()
                menu.Append( ID, label, description )
                wx.EVT_MENU( self, ID, getattr( self, method) )
            menuBar.Append( menu, menuName )
        self.SetMenuBar(menuBar)
    def OnExitCommand( self, event ):
        """Exit from the browser"""
        self.Close()
    def OnOpenCommand( self, event ):
        """Open a file-selection dialog to load a file"""
        import os
        dialog = wx.FileDialog(
            self, message="Choose VRML97 file to replace world",
            defaultDir=os.getcwd(),
            defaultFile="",
            wildcard="*.wrl",
            style=wx.OPEN | wx.CHANGE_DIR
        )
        if dialog.ShowModal() == wx.ID_OK:
            path = dialog.GetPath()
            from OpenGLContext.loaders import loader
            scenegraph = loader.Loader.load( path )
            self.context.scene = scenegraph
    def OnAddCommand( self, event ):
        """Add VRML97 nodes from a file"""


    def CreateContext( self, parent ):
        """Create the VRML browser context"""
        from OpenGLContext.browser import browsercontext
        self.context = browsercontext.BrowserContext( parent )
        return self.context
    def CreateSelectionControl( self, parent ):
        """Create and populate the test-list control"""
        return wx.ListCtrl( parent, -1 )
    def CreateShellControl( self, parent ):
        """Create the base shell control for the testing application"""
        self.shell = UpdatingShell( parent, -1, locals = self.CreateShellEnvironment())
        self.shell.context = self.context
        return self.shell
    def UpdateShellVariables( self, **named ):
        """Update shell's local variables from named arguments"""
        self.shell.interp.locals.update( named )

from wx.py import shell

class UpdatingShell( shell.Shell ):
    def push(self, command):
        """Send command to the interpreter for execution."""
        shell.Shell.push( self, command )
        try:
            self.context.triggerRedraw()
        except AttributeError:
            pass



if __name__ == "__main__":
    class TestApplication (wx.PySimpleApp):
        def OnInit(self):
            wx.InitAllImageHandlers()
            frame = TestFrame(None, -1, "OpenGLContext wxPython tests")
            ##frame.LoadContext(  )
            frame.Show (1)
            self.SetTopWindow(frame)
            return 1

    app = TestApplication ()
    app.MainLoop()


