"""Context functionality under the wxPython GUI environment

Note: wxPython GTK3 uses EGL for OpenGL context creation, not GLX.
PyOpenGL must be configured to use EGL for proper context tracking,
which is required for shader-based rendering (VAO/VBO operations).
This module automatically sets PYOPENGL_PLATFORM=egl when GTK3 is detected.
"""
import os
import sys
import wx

# wxPython GTK3 uses EGL for OpenGL contexts, but PyOpenGL defaults to GLX.
# We need to set PYOPENGL_PLATFORM before importing OpenGL modules.
# Check if we're on GTK3 and EGL hasn't been explicitly configured.
if '__WXGTK__' in wx.PlatformInfo and 'gtk3' in wx.PlatformInfo:
    if 'PYOPENGL_PLATFORM' not in os.environ:
        os.environ['PYOPENGL_PLATFORM'] = 'egl'
        # If OpenGL was already imported, warn the user
        if 'OpenGL' in sys.modules:
            import logging
            logging.getLogger(__name__).warning(
                "OpenGL was imported before wxcontext could set PYOPENGL_PLATFORM=egl. "
                "This may cause issues with shader rendering. "
                "Set PYOPENGL_PLATFORM=egl before importing OpenGL."
            )

from wx import glcanvas
#from wx.glcanvas import *
from OpenGL.GL import *
from OpenGLContext import context
from OpenGLContext.events import wxevents
import logging
log = logging.getLogger( __name__ )
try:
    from cStringIO import StringIO
except ImportError:
    from io import BytesIO as StringIO

if wx.VERSION >= (4,):
    USE_CONTEXT = True
else:
    USE_CONTEXT = False

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
    #: True while the pointer is hidden and being warped back to the middle of
    #: the canvas for a mouse-look mode.
    _pointerGrabbed = False
    #: Where the pointer was last warped to, so the movement the warp itself
    #: generates can be told from a real one.
    _pointerWarpedTo = None
    #: Set once this canvas's GL objects have been let go, so quitting and the
    #: canvas's own destruction do not both do it.
    _released = False
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
        # Resolved before the canvas exists, since its attribute list and the
        # context attributes below are both built from it -- see
        # Context.resolveDefinition.
        definition = self.resolveDefinition( definition, **named )
        if USE_CONTEXT:
            # wxPython Phoenix (4+) has a separate context object...
            glcanvas.GLCanvas.__init__(
                self, parent, id=id, pos=pos,
                size = tuple(int(x) for x in definition.size), style=style, name=name,
                attribList = self.wxFlagsFromDefinition(definition),
            )
            # Create context attributes for profile/version selection
            ctx_attrs = self._wxContextAttrsFromDefinition(definition)
            self._wx_context = glcanvas.GLContext(
                self,
                None,
                ctx_attrs,
            )
            if not self._wx_context.IsOK():
                log.warning(
                    "Failed to create OpenGL context with requested profile=%s, version=%s. "
                    "Falling back to default context.",
                    definition.profile, definition.version
                )
                # Fallback to default context without specific profile/version
                self._wx_context = glcanvas.GLContext(self, None)
        else:
            glcanvas.GLCanvas.__init__(
                self, parent, id=id, pos=pos,
                size = tuple(int(x) for x in definition.size), style=style, name=name,
                attribList = self.wxFlagsFromDefinition(definition)
            )
        # Showing is a step of its own here, so hiding is not taking one.  See
        # renderoptions.hidden_window: rendering and reading back are
        # unaffected, and a suite of GL scripts should not take over the screen
        # of whoever is running it.
        from OpenGLContext import renderoptions
        if not renderoptions.hidden_window():
            self.Show( )
        context.Context.__init__ (self, definition)
    @classmethod
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

    @classmethod
    def _wxContextAttrsFromDefinition(cls, definition):
        """Create GLContextAttrs for profile/version selection (wxPython 4+).

        Supports core profile via OPENGLCONTEXT_PROFILE=core environment variable.
        When profile is "core", requests OpenGL 3.3+ core profile context.
        """
        attrs = glcanvas.GLContextAttrs()

        # Set OpenGL version if specified
        major = int(definition.version[0]) if definition.version[0] > 0 else 0
        minor = int(definition.version[1]) if definition.version[0] > 0 else 0

        if definition.profile == "core":
            # Core profile - use OpenGL 3.3+ with core profile
            if major == 0:
                # Default to 3.3 for core profile
                major, minor = 3, 3
            attrs.CoreProfile().OGLVersion(major, minor)
            log.info("Requesting OpenGL %d.%d core profile context", major, minor)
        elif definition.profile == "compatibility":
            # Compatibility profile
            if major >= 3:
                # Only set compatibility profile for GL 3.0+
                attrs.CompatibilityProfile().OGLVersion(major, minor)
                log.info("Requesting OpenGL %d.%d compatibility profile context", major, minor)
            else:
                # Let driver choose for older versions
                attrs.PlatformDefaults()
        else:
            # Default - let driver choose
            attrs.PlatformDefaults()

        attrs.EndList()
        return attrs

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
        self.Bind(wx.EVT_WINDOW_CREATE, self._OnInitCallback)
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
            self.Bind(wx.EVT_ERASE_BACKGROUND, self.wxOnEraseBackground)
            # Handle resizing of the window
            self.Bind(wx.EVT_SIZE, self.wxOnSize)
            # Handle requests to display this canvas
            self.Bind(wx.EVT_PAINT, self.wxOnPaint)
            # Handle keyboard events...
            self.Bind(wx.EVT_KEY_DOWN, self.wxOnKeyDown )
            self.Bind(wx.EVT_KEY_UP, self.wxOnKeyUp )
            self.Bind(wx.EVT_CHAR, self.wxOnCharacter )
            # Handle mouse events...
            self.Bind(wx.EVT_LEFT_DOWN, self.wxOnMouseButton )
            self.Bind(wx.EVT_RIGHT_DOWN, self.wxOnMouseButton )
            self.Bind(wx.EVT_MIDDLE_DOWN, self.wxOnMouseButton )
            self.Bind(wx.EVT_LEFT_UP, self.wxOnMouseButton )
            self.Bind(wx.EVT_RIGHT_UP, self.wxOnMouseButton )
            self.Bind(wx.EVT_MIDDLE_UP, self.wxOnMouseButton )
            self.Bind(wx.EVT_MOTION, self.wxOnMouseMove )
            self.Bind(wx.EVT_MOUSEWHEEL, self.wxOnMouseWheel )
            # No key-up arrives for a key that was down when focus went
            # elsewhere; see wxOnKillFocus.
            self.Bind(wx.EVT_KILL_FOCUS, self.wxOnKillFocus )
            # The canvas going is the end of its GL context, and the caches
            # holding that context's names have to be told while it is still
            # whole.  EVT_WINDOW_DESTROY rather than EVT_CLOSE: a canvas is
            # destroyed with its frame and never sees a close of its own.
            self.Bind(wx.EVT_WINDOW_DESTROY, self.wxOnWindowDestroy )
            if hasattr( self, 'OnIdle' ):
                self.Bind(wx.EVT_IDLE, self.wxOnIdle )

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

    def _glHandle(self):
        """The GL context handle the caches and PyOpenGL key on.

        wx owns the context object and does not hand out a platform handle, so
        it is read from the platform with the canvas current.
        """
        from OpenGLContext import contextresources
        return contextresources.context_key()

    def OnQuit(self, event=None):
        """Let go of this canvas's GL objects, then end the application

        The release happens **here** as well as on the canvas's destruction,
        because :meth:`Context.OnQuit` ends the process with ``os._exit``:
        nothing after it runs, no ``finally`` and no ``atexit`` hook, and no
        destroy event ever arrives.  Pressing Escape is the path a user
        actually takes.
        """
        self.releaseCanvas()
        return context.Context.OnQuit(self, event)

    def releaseCanvas(self):
        """Drop this context's GL objects, with its context current

        The caches may *delete* what they hold rather than merely forget it,
        and deleting a name needs the context that issued it.  Calling this
        twice is harmless; the second call has nothing to do.
        """
        if self._released:
            return
        self._released = True
        try:
            self.setCurrent()
        except Exception as err:
            log.debug( "cannot take the context to release it: %s", err )
            self.releaseContextResources( None )
            return
        try:
            self.releaseContextResources( self._glHandle() )
        finally:
            self.unsetCurrent()

    def wxOnWindowDestroy(self, event):
        """Let go of this context's GL objects as the canvas is destroyed."""
        event.Skip()
        if event.GetEventObject() is not self:
            return                      # a child's destruction, not ours
        self.releaseCanvas()

    def wxOnEraseBackground(self, event):
        """Prevent flashing of the window by capturing and ignoring background erase events

        As you might imagine, this is just a hack.
        """
        pass # Do nothing, to avoid flashing.


    if USE_CONTEXT:
        def setCurrent (self):
            """Acquire the OpenGL "focus" (wx Pheonix version)

            Basically this just calls the GUI library SetCurrent
            method after dispatching to the superclass's
            implementation.
            """
            context.Context.setCurrent( self )
            self._wx_context.SetCurrent(self)
            self.bindContextResources( self._glHandle() )
    else:
        def setCurrent (self):
            """Acquire the OpenGL "focus" (wxPython 3.x version)

            Basically this just calls the GUI library SetCurrent
            method after dispatching to the superclass's
            implementation.
            """
            context.Context.setCurrent( self )
            glcanvas.GLCanvas.SetCurrent(self)
            self.bindContextResources( self._glHandle() )
    def SwapBuffers (self): # happens to match the wx method
        """Swap the GL buffers (force flush as we do)"""
        glcanvas.GLCanvas.SwapBuffers(self)
    def setFullscreen( self, fullscreen ):
        """Fill the screen, or go back to a window.

        The frame the canvas sits in is what fills the screen -- a canvas
        cannot, and the menu bar and status bar a frame may carry have to go
        with it.
        """
        frame = self.GetTopLevelParent()
        if frame is None:
            return False
        frame.ShowFullScreen( bool( fullscreen ) )
        return True

    def settingsChanged( self ):
        """Re-apply the window-level settings a changed definition affects."""
        from OpenGLContext import renderoptions
        self.applyVSync()
        self.setFullscreen( renderoptions.fullscreen_window( self ) )
        context.Context.settingsChanged( self )

    def applyVSync( self, definition=None ):
        """Wait for the display's refresh, or don't (ContextDefinition.vsync)

        wx names nothing for this, so it goes to the window system's own
        swap-control extension; see :mod:`OpenGLContext.swapcontrol`, which
        answers False where there is none.  Asked with this canvas current,
        since that is the drawable the interval is set for.
        """
        from OpenGLContext import renderoptions, swapcontrol
        source = self if definition is None else definition
        wanted = renderoptions.flag(
            source, 'vsync',
            not renderoptions.env_flag('OPENGLCONTEXT_NO_VSYNC', False))
        self.setCurrent()
        try:
            return swapcontrol.set_swap_interval( 1 if wanted else 0 )
        finally:
            self.unsetCurrent()

    def setPointerCapture( self, capture ):
        """Hide the pointer and keep it in the window, for a mouse-look mode

        wx has no relative-motion mode, so the pointer is warped back to the
        middle of the canvas after every movement -- which is what makes the
        motion unbounded, since a pointer that stops at the edge of the screen
        is a view that stops turning there.  The warp arrives back as an
        ordinary movement and is recognised and dropped; see
        :meth:`OpenGLContext.events.wxevents.EventHandlerMixin.wxOnMouseMove`.
        """
        capture = bool( capture )
        self._pointerGrabbed = capture
        self._pointerWarpedTo = None
        if capture:
            self.SetCursor( wx.Cursor( wx.CURSOR_BLANK ) )
            if not self.HasCapture():
                self.CaptureMouse()
        else:
            self.SetCursor( wx.NullCursor )
            while self.HasCapture():
                # wx counts captures, and releases one per call.
                self.ReleaseMouse()
        forget = getattr( self, 'forgetPointerOrigin', None )
        if forget is not None:
            # Where the pointer is means something different on each side of
            # this, so the first report afterwards establishes a position
            # rather than arriving as one flick of the view.
            forget()
        if capture:
            self.recentrePointer()
        return True

    def recentrePointer( self ):
        """Put the pointer back in the middle of the canvas, if it is grabbed"""
        if not self._pointerGrabbed:
            return
        size = self.GetClientSize()
        middle = ( int(size.width) // 2, int(size.height) // 2 )
        self._pointerWarpedTo = middle
        self.WarpPointer( *middle )

    def pointerWarpEcho( self, x, y ):
        """Whether this movement is the one :meth:`recentrePointer` caused

        A movement the program made itself is not motion the user asked for:
        left in, it cancels out every real movement and mouse-look never turns.
        """
        if self._pointerWarpedTo is None:
            return False
        echo = ( int(x), int(y) ) == self._pointerWarpedTo
        if echo:
            self._pointerWarpedTo = None
        return echo

    def getDefaultIcons( cls ):
        """Get the OpenGLContext icons as a wxPython wxIconBundle

        You can call frame.SetIcons( bundle ) on the bundle returned
        from this function (set of 2 icons, 16x16 and 32x32)
        """
        try:
            from OpenGLContext.resources import context_icon_png, context_icon_small_png
        except ImportError as err:
            return None
        else:
            bundle = wx.IconBundle( )
            bundle.AddIcon( getIcon(context_icon_png.data) )
            bundle.AddIcon( getIcon(context_icon_small_png.data) )
            return bundle
    getDefaultIcons = classmethod( getDefaultIcons )

    def ContextMainLoop( cls, *args, **named ):
        """Initialise the context and start the mainloop"""
        made = []
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
                from OpenGLContext import renderoptions
                frame.Show( not renderoptions.hidden_window() )
                instance = cls( frame, *args, **named )
                made.append( instance )
                instance.SetFocus( )
                frame.SetSize( instance.contextDefinition.size )
                if renderoptions.fullscreen_window( instance.contextDefinition ):
                    instance.setFullscreen( True )
                icons= instance.getDefaultIcons()
                if icons is not None:
                    frame.SetIcons( icons )
                return True
        app = ContextApp(0)
        try:
            app.MainLoop()
        finally:
            # A loop left while it was still slow -- a closed window, a Ctrl-C
            # -- holds an episode nobody has written, and what it holds of the
            # last few seconds is what a session that ended badly is worth
            # reading for.
            for instance in made:
                if instance.stallJournal is not None:
                    instance.stallJournal.close()
                instance.stopTelemetry( 'mainloop-ended' )
    ContextMainLoop = classmethod( ContextMainLoop )


def getIcon( data ):
    """Return the data from the resource as a wxIcon"""
    stream = StringIO(data)
    image = wx.Image(stream)
    icon = wx.Icon()
    icon.CopyFromBitmap(wx.Bitmap(image))
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
