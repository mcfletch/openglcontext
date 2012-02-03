"""Context functionality under the wxPython GUI environment"""
import wx
from wx import glcanvas
#from wx.glcanvas import *
from OpenGL.GL import *
from OpenGLContext import context, contextdefinition
from OpenGLContext.events import wxevents
import logging 
log = logging.getLogger( __name__ )

class wxContext(
    glcanvas.GLCanvas, # wxPython OpenGL context
    wxevents.EventHandlerMixin, # provides wx to OpenGLContext event translation
    context.Context, # primary super-class
):
    """Context sub-class for the wxPython GUI environment

    This is one of the "supported" Context types (pygame and
    glut being the other two).  The base Context here is the
    root of a hierarchy of wxPython-specific contexts with
    most users wanting to use the wxInteractiveContext class,
    which provides navigation and examination support.
    """
    init = None
    calledDoInit = 0
    def __init__(
        self, parent, definition=None, 
        id=-1, pos= wx.DefaultPosition, 
        style = wx.WANTS_CHARS, name = "GLContext", 
        **named
    ):
        """Initialize the wxContext object and window

        parent -- wx.Window parent of the context window
        id -- wxPython ID for the window, can normally be left
            as the default
        pos -- wxPython position object or a two-tuple of coordinates
            for the wxPython window that we are creating
        size -- wxPython  size object, or a two-tuple of dimensions
            for the wxPython window that we are creating
        style -- wxPython style integer (a bit-mask) dictating the
            window style
        name -- string determining the wxPython window's name,
            which is an internal value which allows wxPython
            programmers to search for particular windows.

        This implementation simply passes the wxPython-specific
        arguments to the wxGLCanvas initializer, then calls the
        context.Context initializer.
        """
        if definition is None:
            definition = contextdefinition.ContextDefinition( **named )
        else:
            for key,value in named.items():
                setattr( definition, key, value )
        glcanvas.GLCanvas.__init__(
            self, parent, id=id, pos=pos, 
            size = tuple(definition.size), style=style, name=name, 
            attribList = self.wxFlagsFromDefinition(definition)
        )
        self.Show( )
        context.Context.__init__ (self, definition)
    def wxFlagsFromDefinition( cls, definition ):
        """Determine the flags to pass to he initialiser (attribList)"""
        attributes = []
        if definition.rgb:
            attributes.append( glcanvas.WX_GL_RGBA )
        else:
            attributes.append( glcanvas.WX_GL_BUFFER_SIZE )
            attributes.append( 8 )
        if definition.doubleBuffer:
            attributes.append( glcanvas.WX_GL_DOUBLEBUFFER )
        if definition.stereo > -1:
            attributes.append( glcanvas.WX_GL_STEREO )
            # does this take a parameter?
        if definition.depthBuffer > -1:
            attributes.append( glcanvas.WX_GL_DEPTH_SIZE )
            attributes.append( definition.depthBuffer )
        if definition.stencilBuffer > -1:
            attributes.append( glcanvas.WX_GL_STENCIL_SIZE )
            attributes.append( definition.stencilBuffer )
        if definition.accumulationBuffer > -1:
            for flag in (
                glcanvas.WX_GL_MIN_ACCUM_RED,
                glcanvas.WX_GL_MIN_ACCUM_GREEN,
                glcanvas.WX_GL_MIN_ACCUM_BLUE,
                glcanvas.WX_GL_MIN_ACCUM_ALPHA,
            ):
                attributes.append( flag )
                attributes.append( definition.accumulationBuffer )
        return attributes
    wxFlagsFromDefinition = classmethod( wxFlagsFromDefinition )

    def DoInit( self ):
        """Call the OnInit method at a time when the context is valid

        This method provides a customization point where
        contexts which do not completely initialize during
        their __init__ method can arrange to have the OnInit
        method processed after their initialization has
        completed.  The default implementation here simply
        calls OnInit directly w/ appropriate setCurrent
        and unsetCurrent calls.

        Note:
            The only context currently known to require
            this customization is the wxPython-on-GTK context,
            everything else completes context initialization
            before calling Context.__init__.
        """
##		if wx.Platform == '__WXGTK__':
        wx.EVT_WINDOW_CREATE(self, self._OnInitCallback)
##		else:
##			self._OnInitCallback()
    def _OnInitCallback( self, event=None ):
        """Callback for GTK initialisation-finished event

        On all platforms other than GTK, will be called
        immediately by the DoInit method.  On GTK, it will
        be called as the EVT_WINDOW_CREATE event handler.
        
        On GTK where this context is not being created
        as a child of a new frame, this will get called
        during the first OnPaint method.
        """
        if not self.calledDoInit:
            self.calledDoInit = 1
            context.Context.DoInit( self )
    def setupCallbacks( self ):
        """Setup various callbacks for this context

        Binds most of the wxPython event types to callbacks on this
        object, which allows interactive sub-classes to easily
        manage the bindings without needing any wxPython-specific
        logic.
        """
        if not self.init:
            self.init = 1
            # Bind the wxPython background erase event
            # Without this binding, the canvas will tend to flicker
            wx.EVT_ERASE_BACKGROUND(self, self.wxOnEraseBackground)
            # Handle resizing of the window
            wx.EVT_SIZE(self, self.wxOnSize)
            # Handle requests to display this canvas
            wx.EVT_PAINT(self, self.wxOnPaint)
            # Handle keyboard events...
            wx.EVT_KEY_DOWN( self, self.wxOnKeyDown )
            wx.EVT_KEY_UP( self, self.wxOnKeyUp )
            wx.EVT_CHAR( self, self.wxOnCharacter )
            # Handle mouse events...
            wx.EVT_LEFT_DOWN( self, self.wxOnMouseButton )
            wx.EVT_RIGHT_DOWN( self, self.wxOnMouseButton )
            wx.EVT_MIDDLE_DOWN( self, self.wxOnMouseButton )
            wx.EVT_LEFT_UP( self, self.wxOnMouseButton )
            wx.EVT_RIGHT_UP( self, self.wxOnMouseButton )
            wx.EVT_MIDDLE_UP( self, self.wxOnMouseButton )
            wx.EVT_MOTION( self, self.wxOnMouseMove )
            if hasattr( self, 'OnIdle' ):
                wx.EVT_IDLE( self, self.wxOnIdle )

    def ProcessEvent( self, event ):
        """Dispatch events to appropriate engine based on event type

        Because the method named "ProcessEvent" is used by both
        wxPython and the OpenGLContext.events package, we need to
        dispatch to the appropriate handler when the method is called.

        XXX This method doesn't appear to get called by wxPython, and
            even if it were, almost every context uses the
            EventHandlerMixIn class's implementation (which isn't
            aware of the wxEventPtr class) anyway.
        """
        if isinstance( event, wx.Event ):
            return glcanvas.GLCanvas.ProcessEvent( self, event )
        else:
            return wxevents.EventHandlerMixin.ProcessEvent( self, event )

    def wxOnPaint(self, event):
        """Callback: Called for each paint event

        wxOnPaint is responsible for doing all of the processing
        required to setup-for and trigger a redraw of the OpenGL
        context.  Because this callback can only occur in the
        GUI/rendering thread, the call to triggerRedraw should
        always cause an immediate rendering cycle.

        Note the use of GetClientSize and Viewport, which
        updates the viewport dimensions before rendering.

        Note also the use of wxPaintDC.  Without this
        instantiation the paint handler would fail, even
        though we don't actually use the dc at all.
        """
        dc = wx.PaintDC(self)
        size = self.GetClientSize()
        if size.width == 0 or size.height == 0:
            return
        if not self.calledDoInit:
            log.info( """wxOnPaint before initialisation started""" )
            self._OnInitCallback( )
        self.setCurrent()
        self.ViewPort( size.width, size.height )
        self.unsetCurrent()
        self.triggerRedraw(1)

    def wxOnIdle( self, event ):
        """Callback: Handle wxPython idle event notification

        The major function of this callback is to virtualize
        OnIdle handling, that is, to call self.OnIdle if it
        actually exists.
        """
        if hasattr( self, 'OnIdle'):
            if not self.OnIdle():
                wx.Yield()
        event.RequestMore()

    def wxOnSize(self, event):
        """Handle window re-size event

        We actually just trigger a redraw, as the
        paint event handler does all the work for us.
        """
        self.Refresh()
        event.Skip()
        # wxPython generates size events all the time, we
        # just tell the system to refresh and let the paint
        # handler do it's job.  With the following line we wind
        # up in a situation where the context is rendering before
        # it even has a context into which to render!  So keep it
        # commented out!
        #~ context.Context.OnResize( self ) # triggers a redraw

    def wxOnEraseBackground(self, event):
        """Prevent flashing of the window by capturing and ignoring background erase events

        As you might imagine, this is just a hack.
        """
        pass # Do nothing, to avoid flashing.


    def setCurrent (self):
        """Acquire the OpenGL "focus"

        Basically this just calls the GUI library SetCurrent
        method after dispatching to the superclass's
        implementation.
        """
        context.Context.setCurrent( self )
        glcanvas.GLCanvas.SetCurrent(self)
    def SwapBuffers (self): # happens to match the wx method
        """Swap the GL buffers (force flush as we do)"""
        glcanvas.GLCanvas.SwapBuffers(self)
    def getDefaultIcons( cls ):
        """Get the OpenGLContext icons as a wxPython wxIconBundle

        You can call frame.SetIcons( bundle ) on the bundle returned
        from this function (set of 2 icons, 16x16 and 32x32)
        """
        try:
            from OpenGLContext.resources import context_icon_png, context_icon_small_png
        except ImportError, err:
            return None
        else:
            bundle = wx.IconBundle( )
            bundle.AddIcon( getIcon(context_icon_png.data) )
            bundle.AddIcon( getIcon(context_icon_small_png.data) )
            return bundle
    getDefaultIcons = classmethod( getDefaultIcons )

    def ContextMainLoop( cls, *args, **named ):
        """Initialise the context and start the mainloop"""
        class ContextApp(wx.App):
            def OnInit(self):
                wx.InitAllImageHandlers()
                frame = wx.Frame(
                    None, -1, 
                    cls.getApplicationName(), 
                    wx.DefaultPosition, 
                    wx.Size(600,300)
                )
                self.SetTopWindow(frame)
                frame.Show( True )
                instance = cls( frame, *args, **named )
                instance.SetFocus( )
                frame.SetSize( instance.contextDefinition.size )
                icons= instance.getDefaultIcons()
                if icons is not None:
                    frame.SetIcons( icons )
                return True
        app = ContextApp(0)
        app.MainLoop()
    ContextMainLoop = classmethod( ContextMainLoop )


def getIcon( data ):
    """Return the data from the resource as a wxIcon"""
    import cStringIO
    stream = cStringIO.StringIO(data)
    image = wx.ImageFromStream(stream)
    icon = wx.EmptyIcon()
    icon.CopyFromBitmap(wx.BitmapFromImage(image))
    return icon



if __name__ == '__main__':
    from drawcube import drawCube
    class TestContext(wxContext):
        def Render(self, mode):
            glTranslated(0, 0, -3)
            glRotated(30, 1, 0, 0)
            glRotated(40, 0, 1, 0)
            drawCube()
    TestContext.ContextMainLoop()
