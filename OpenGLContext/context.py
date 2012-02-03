"""Abstract base class for all rendering contexts

OpenGL operates with the idea of a current context
in which OpenGL calls will operate.  This is something
a little bit more than a "window", as it includes
a number of (optional) off-screen buffers, and
a great deal of state which is manipulated by the
various OpenGL functions. (OpenGL is basically a huge
state machine).

The Context in OpenGLContext is your basic interface
to the context, and simple operation of OpenGLContext
(such as that you'll see in most of the test scripts)
can focus almost entirely on the Context object and
its various customization points.

If you wish to use the scene graph facilities of
OpenGLContext, look particularly at the abstract
function getSceneGraph, which can be overridden to
provide a particular scenegraph object to the renderer.
SceneGraph objects provide their own light, background,
and render-traversal mechanisms, which allow you to
largely ignore the Context objects.

The bulk of the actual rendering work is done by the
Visitor and RenderVisitor classes (or their shadow-
enabled equivalents from shadow.passes), and it is
these classes which define the rendering callbacks
which are available from the Context class.
"""
from OpenGL.GL import *
from OpenGLContext import visitor, texturecache,plugins
from OpenGLContext.passes import renderpass
from vrml.vrml97 import nodetypes
from vrml import node,cache
import weakref, os, time, sys, logging 
log = logging.getLogger( __name__ )

class LockingError( Exception ):
    pass

try:
    import threading, Queue
    contextLock = threading.RLock()
    contextThread = None
except ImportError:
    threading = 0
    class DummyLock:
        """Dummy locking mechanism when threading is not available

        I do not know of any situations where it shouldn't
        be available on a supported platform, but it's
        possible I suppose.
        """
        def acquire( self, *arguments, **named ):
            return
        def release( self, *arguments, **named ):
            return
    contextLock = DummyLock()
    contextThread = None

def inContextThread():
    """Return true if the current thread is the context thread"""
    if threading:
        if threading.currentThread() == contextThread:
            return 1
        elif threading.currentThread().getName() == contextThread.getName():
            return 1
        else:
            return 0
    return 1

class Context(object):
    """Abstract base class on which all Rendering Contexts are based

    The Context object represents a single rendering context
    for use by the application.  This base class provides only
    the most rudimentary of application support, but sub-classes
    provide such things as navigation, and/or event handling.

    Attributes:

        sg -- OpenGLContext.basenodes.sceneGraph; the root of the
            node-rendering tree.  If not NULL, is used to control
            most aspects of the rendering process.
            See: getSceneGraph

        renderPasses -- callable object, normally an instance of
            OpenGLContext.passes.renderpass.PassSet which implements the
            rendering algorithm for the Context

        alreadyDrawn -- flag which is set/checked to determine
            whether the context needs to be redrawn, see:
                Context.triggerRedraw( ... )
                Context.shouldRedraw( ... )
                Context.suppressRedraw( ... )
            for the API to use to interact with this attribute.

        viewportDimensions -- Storage for the current viewport
            dimensions, see:
                Context.Viewport( ... )
                Context.getViewport( ... )
            for the API used to interact with this attribute.
            
        drawPollTimeout -- default timeout for the drawPoll method

        currentContext -- class attribute pointing to the currently
            rendering Context instance.  This allows code called
            during a Render-pass to access the Context object.
            
            Note: wherever possible, use the passed render-pass's
            "context" attribute, rather than this class attribute.
            If that isn't possible, use the deprecated
            getCurrentContext function in this module.

        allContexts -- list of weak references to all instantiated
            Context objects, mostly of use for code which wants to
            refresh all contexts when shared resources/states are
            updated

        drawing -- flag set to indicate that this Context is
            currently drawing, mostly used internally

        frameCounter -- node, normally a framecounter.FrameCounter
            instance which is used to track frame rates, must have
            an addFrame method as seen in framecounter.FrameCounter,
            See setupFrameRateCounter

        extensions -- extensionmanager.ExtensionManager instance
            with which to find and initialise extensions for this
            context.
            See setupExtensionManager

        cache -- vrml.cache.Cache instance used for optimising the
            rendering of scenegraphs.
            See setupCache

        redrawRequest -- threading Event for triggering a request

        scenegraphLock -- threading Lock for blocking rendering
            from re-entering during a rendering pass

        pickEvents -- dictionary mapping event type and key to
            event object where each event requires select-render-pass
            support
            
        contextDefinition -- node describing the options used to
            create this context (set by sub-classes during init)
    """
    currentContext = None
    allContexts = []
    renderPasses = renderpass.defaultRenderPasses
    frameCounter = None
    contextDefinition = None
    
    ### State flags/values
    # Set to false to trigger a redraw on the next available iteration
    alreadyDrawn = None
    drawing = None
    viewportDimensions = (0,0)
    drawPollTimeout = 0.01

    ### Node-like attributes
    PROTO = "Context"
    DEF = "#Context"
    
    def __init__ (self, definition=None):
        """Establish the Context working environment

        setupThreading, initializeEventManagers,
        setupCallbacks, setupDefaultEventCallbacks,
        adds a weakref to self to allContexts
        establishes pickEvents
        and then calls OnInit
        """
        definition = definition or self.contextDefinition
        if not definition:
            from OpenGLContext import contextdefinition
            definition = contextdefinition.ContextDefinition()
        self.contextDefinition = definition
        self.setupThreading()
        self.setupExtensionManager( )
        self.initializeEventManagers( )
        self.setupCallbacks()
        self.setupDefaultEventCallbacks()
        self.allContexts.append( weakref.ref(self))
        self.pickEvents = {}
        self.eventCascadeQueue = Queue.Queue()
        self.setupCache()
        self.setupFontProviders()
        self.setupFrameRateCounter()
        self.DoInit()
    def DoInit( self ):
        """Call the OnInit method at a time when the context is valid

        This method provides a customization point where
        contexts which do not completely initialize during
        their __init__ method can arrange to have the OnInit
        method processed after their initialization has
        completed.  The default implementation here simply
        calls OnInit directly w/ appropriate setCurrent
        and unsetCurrent calls and calls the glutInit()
        function with an empty argument-list.
        """
        self.setCurrent()
        try:
            try:
                from OpenGL import GLUT
                GLUT.glutInit([])
            except Exception, err:
                pass
            self.OnInit()
        finally:
            self.unsetCurrent()
        
    ### Customisation points
    def setupCallbacks( self ):
        """Establishes GUI callbacks for asynchronous event GUI systems

        Subclasses and applications will register events
        here for those event types in which they are interested.
        Most minor applications should use interactivecontext's
        abstract callbacks (which translate the GUI library's
        native events into a common event framework for all
        interactivecontexts).

        The default implementation does nothing.
        """
    def setupCache( self ):
        """Setup caching strutures for content

        This includes the general compiled-geometry caches
        and the texture cache
        """
        self.textureCache = texturecache.TextureCache()
        self.cache = cache.Cache()
    def setupExtensionManager( self ):
        """Create an extension manager for this context"""
        from OpenGLContext import extensionmanager
        self.extensions = extensionmanager.ExtensionManager()
    def setupFontProviders( self ):
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.
        """
        
    def setupDefaultEventCallbacks( self ):
        """Setup common callbacks for the context

        This will normally be done in the GUI-lib's sub-class of
        context.  You might override it to provide other default
        callbacks, but you'll normally want to call the base-class
        implementation somewhere in that overridden method.
        """
        self.addEventHandler( 'keyboard', name = '<escape>',
            function = self.OnQuit )
        self.addEventHandler( 
            'keypress', name = 'f',modifiers = (False,False,True), # ALT
            function = self.OnFrameRate 
        )
        self.addEventHandler( 'keyboard', name = '<pagedown>', 
            function = self.OnNextViewpoint )
        self.addEventHandler( 'keypress', name = 's', 
            modifiers = (False,False,True),
            function = self.OnSaveImage )
        
    def OnQuit( self, event=None ):
        """Quit the application (forcibly)"""
        import sys
        sys.exit( 0 )
    def OnFrameRate( self, event=None ):
        """Print the current frame-rate values"""
        if self.frameCounter:
            self.frameCounter.display = not (self.frameCounter.display)
            print '%sfps'%( self.frameCounter.summary()[1], )
    def OnNextViewpoint( self, event=None ):
        """Go to the next viewpoint for the scenegraph"""
        sg = self.getSceneGraph()
        if sg:
            current = getattr( sg, 'boundViewpoint', None )
            if current:
                current.isBound = False
                current.set_bound = False
        self.triggerRedraw( 1 )
    def OnSaveImage( 
        self, event=None, 
        template='%(script)s-screen-%(count)04i.png', 
        script=None,
        date=None,
        overwrite=False,
    ):
        """Save our current screen to disk (if possible)"""
        try:
            try:
                from PIL import Image # get PIL's functionality...
            except ImportError, err:
                # old style?
                import Image
        except ImportError, err:
            log.error( "Unable to import PIL" )
            saved = False
            return (0,0)
        else:
            width, height = self.getViewPort()
            if not width or not height:
                return (width,height)
            glPixelStorei(GL_PACK_ALIGNMENT, 1)
            data = glReadPixelsub(0, 0, width, height, GL_RGB)
            if hasattr( data, 'tostring' ):
                string = data.tostring()
            else:
                string = data
            image = Image.fromstring( 
                'RGB', 
                (int(width),int(height)), 
                string 
            )
            image = image.transpose( Image.FLIP_TOP_BOTTOM)
            if script is None:
                import sys
                script = sys.argv[0]
            if date is None:
                import datetime
                date = datetime.datetime.now().isoformat()
            count = 0
            saved = False
            while (not saved) and count <= 9999:
                count += 1
                test = template%locals()
                if overwrite or (not os.path.exists( test )):
                    log.warn( 'Saving to file: %s', test )
                    image.save( test, 'PNG' )
                    saved = True 
                    return (width,height)
                else:
                    log.info( 'Existing file: %s', test )
        return (0,0)
        
    def setupThreading( self ):
        """Setup primitives (locks, events) for threading
        """
        global contextThread
        if threading:
            contextThread = threading.currentThread()
            contextThread.setName( "GUIThread")
        self.setupScenegraphLock()
        self.setupRedrawRequest()
    def setupFrameRateCounter( self ):
        """Setup structures for managing frame-rate

        This sets self.frameCounter to an instance of
        framecounter.FrameCounter, which is a simple node
        used to track frame-rate metadata during rendering.

        Updates to the framecounter are performed by OnDraw
        iff there is a visible change processed.

        Note:
            If you override this method, you need to either use
            an object which has the same API as a FrameCounter or
            use None, anything else will cause failures in the
            core rendering loop!
        """
        from OpenGLContext import framecounter
        self.frameCounter = framecounter.FrameCounter()
        
            
    def initializeEventManagers( self, managerClasses=() ):
        """Customisation point for initialising event manager objects

        See:
            OpenGLContext.eventhandlermixin.EventHandlerMixin
        """
    def setupRedrawRequest( self ):
        """Setup the redraw-request (threading) event"""
        if threading:
            self.redrawRequest = threading.Event()
        
    def setupScenegraphLock( self ):
        """Setup lock to protect scenegraph from updates during rendering
        """
        if threading:
            self.scenegraphLock = threading.RLock()
        
    def lockScenegraph( self, blocking=1 ):
        """Lock scenegraph locks to prevent other update/rendering actions

        Potentially this could be called from a thread other than the
        GUI thread, allowing the other thread to update structures in
        the scenegraph without mucking up any active rendering pass.
        """
        if threading:
            self.scenegraphLock.acquire(blocking)
    def unlockScenegraph( self ):
        """Unlock scenegraph locks to allow other update/rendering actions

        Potentially this could be called from a thread other than the
        GUI thread, allowing the other thread to update structures in
        the scenegraph without mucking up any active rendering pass.
        """
        if threading:
            self.scenegraphLock.release()
        
    def setCurrent (self, blocking=1):
        """Set the OpenGL focus to this context
        """
        assert inContextThread(), """setCurrent called from outside of the context/GUI thread! %s"""%( threading.currentThread())
        if not contextLock.acquire( blocking ):
            raise LockingError( """Cannot acquire without blocking""" )
        Context.currentContext = self
        self.lockScenegraph()
    def unsetCurrent( self ):
        """Give up the OpenGL focus from this context
        """
        assert inContextThread(), """unsetCurrent called from outside of the context/GUI thread! %s"""%( threading.currentThread())
        self.unlockScenegraph()
        Context.currentContext = None
        contextLock.release()
            
    def OnInit( self ):
        """Customization point for scene set up and initial processing

        You override this method to do housekeeping chores such as
        loading images and generating textures, loading pre-established
        geometry, spawning new threads, etc.

        This method is called after the completion of the Context.__init__
        method for the rendering context.  GUI implementers:
            Wherever possible, this should be the very last function
            called in the initialization of the context to allow user
            code to use all the functionality of the context.
        """
    def OnIdle(self,*arguments ):
        ''' Override to perform actions when the rendering loop is idle '''
        return self.drawPoll()

    def OnDraw (self, force = 1, *arguments):
        """Callback for the rendering/drawing mechanism

        force -- if true, force a redraw.  If false, then only
            do a redraw if the event cascade has generated events.

        return value is whether a visible change occured

        This implementation does the following:

            * calls self.lockScenegraph()
                o calls self.DoEventCascade()
            * calls self.unlockScenegraph()
            * calls self.setCurrent()
            * calls self.renderPasses( self )
                See: passes sub-package
                See: visitor.py, rendervisitor.py, renderpass.py,
                shadow/passes.py for examples of render-pass-sets
                which can be triggered.
                See: flat.py for standard second-generation renderer

                The RenderPasses define the core of the rendering
                mechanism.  The default rendering passes will defer
                most rendering options to the scenegraph returned by
                self.getSceneGraph().  If that value is None (default)
                then the pass will use the Context's callbacks.

                You can define new RenderPasses to replace the
                rendering algorithm, override the Context's various
                callbacks to write raw OpenGL code, or work by
                customizing the scene graph library.
            * if there was a visible change (which is the return value
                from the render-pass-set), calls self.SwapBuffers()
            * calls self.unsetCurrent()
        """
        assert inContextThread(), """OnDraw called from outside of the context/GUI thread! %s"""%( threading.currentThread())
        # could use if self.frameCounter, but that introduces a
        # potential race condition, so eat the extra call...
        t = time.clock()
        self.lockScenegraph()
        try:
            changed = self.DoEventCascade()
            if not force and not changed:
                return 0
        finally:
            self.unlockScenegraph()
        self.setCurrent()
        self.drawing = 1
        if threading:
            self.redrawRequest.clear()
        try:
            visibleChange = self.renderPasses( self )
            if visibleChange:
                if self.frameCounter is not None:
                    self.frameCounter.addFrame( time.clock()-t )
                return 1
            return 0
        finally:
            self.drawing = None
            self.unsetCurrent()

    def drawPoll( self, timeout=None):
        """Wait timeout seconds for a redraw request

        timeout -- timeout in seconds, if None, use
            self.drawPollTimeout

        returns 0 if timeout, 1 if true
        """
        if timeout is None:
            timeout = self.drawPollTimeout
        if threading:
            self.redrawRequest.wait( timeout )
            if self.redrawRequest.isSet():
                self.OnDraw( force = 1)
                return 1
            else:
                self.OnDraw( force = 0)
                return 1
        return 0

    def Render( self, mode = None):
        """Customization point for geometry rendering

        This method is called by the default render passes to
        render the geometry for the system.  Wherever possible,
        you should pay attention to the rendering modes to allow
        for optimization of your geometry (for instance,
        selection passes do not require lighting).

        The default implementation merely ensures that matrix mode
        is currently model view.

        See: visitor.py, rendervisitor.py, renderpass.py,
        shadow/passes.py for definitions of the properties of the
        mode.
        """
        if not glGetInteger( GL_MATRIX_MODE ) == GL_MODELVIEW:
            glMatrixMode(GL_MODELVIEW)
        ### Put your rendering code here

    def DoEventCascade( self ):
        """Customization point for generating non-GUI event cascades

        This method should only be called after self.lockScenegraph
        has been called.  self.unlockScenegraph should then be called

        Most Contexts will use the eventhandler mix-in's version of this
        method.  That provides support for the defered-execution of
        functions/method during the event cascade.
        """
        return 0
        
    def OnResize (self, *arguments):
        '''Resize the window when the windowing library says to'''
        self.triggerRedraw(1)
        
    def triggerPick( self):
        """Trigger a selection rendering pass

        If the context is not currently drawing, the selection render will
        occur immediately, otherwise it will occur the next time the
        rendering loop reaches the selection stage.
        """
        contextLock.acquire()
        try:
            if (not self.drawing) and inContextThread():
                self.OnDraw()
            elif threading:
                self.redrawRequest.set()
        finally:
            contextLock.release()


    def triggerRedraw( self, force=0 ):
        """Indicate to the context that it should redraw when possible

        If force is true, the rendering will begin immediately if the
        context is not already drawing.  Otherwise only the indicator flag
        will be set.
        """
        contextLock.acquire()
        try:
            self.alreadyDrawn = 0
        finally:
            contextLock.release()
        if force and (not self.drawing) and inContextThread():
            self.OnDraw()
        elif threading:
            self.redrawRequest.set()
        else:
            raise RuntimeError( """Unreasonable threading state!""" )
    def shouldRedraw( self ):
        """Return whether or not the context contents need to be redrawn"""
        return not self.alreadyDrawn

    def suppressRedraw( self ):
        """Indicate to the context that there is no need to re-render

        This method signals to the context that there are no updates
        currently requiring redrawing of the context's contents.

        See:
            Context.shouldRedraw and Context.triggerRedraw
        """
        self.alreadyDrawn = 1


    def SwapBuffers (self):
        """Called by the rendering loop when the buffers should be swapped

        Each GUI library needs to override this method with the appropriate
        code for the library.
        """

    def ViewPort( self, width, height ):
        """Set the size of the OpenGL rendering viewport for the context

        This implementation assumes that the context takes up the entire
        underlying window (i.e. that it starts at 0,0 and that width, height
        will represent the entire size of the window).
        """
        assert inContextThread(), """ViewPort called from outside of the context/GUI thread! %s"""%( threading.currentThread())
        self.setCurrent()
        try:
            self.viewportDimensions = width, height
            glViewport( 0,0, int(width), int(height) )
        finally:
            self.unsetCurrent()
        if self.contextDefinition:
            self.contextDefinition.size = width,height
    def getViewPort( self ):
        """Method to retrieve the current dimensions of the context
        
        Return value is a width, height tuple. See Context.ViewPort
        for setting of this value.
        """
        return self.viewportDimensions

    def Viewpoint (self, mode = None):
        """Customization point for setting up the projection matrix

        The default implementation calls glFrustrum with fairly
        generic values to establish a camera similar to a 35mm.

        Note: Most real-world contexts use a ViewPlatformMixin
        sub-class of Context, which uses a ViewPlatform object to
        manage the viewpoint set up, so the default implementation
        is seldom used.
        
        Note: This method is currently called by just about every
        rendering pass set regardless of whether there is a scene
        graph (the scene graph rendering code doesn't yet have
        camera support, so it simply calls this method).  However,
        if you define a SetupBindables( mode ) method on your
        Context this customization point will not be called.
        
        Eventually the scene graph may grow its own camera handling
        code, at which point it will probably stop calling this
        customization point.
        """
        # This code is not OpenGL 3.1 compatible
        glMatrixMode(GL_PROJECTION);
        # load the identity matrix (reset the view)
        glLoadIdentity()
        # calculate a 3D perspective view
        glFrustum(-0.5, 0.5, -0.5, 0.5, .5, 5.0);

    def Background(self, mode = None):
        """Customization point for clearing/drawing the background.

        The default implementation clears the color and depth
        buffers, using solid white for the clear color.

        Note: This method is only called if there is no scene graph,
        and if there is no self.SetupBindables( mode ) method
        available on the Context.
        """
        if mode.passCount == 0: # first pass...
            glClearColor(1.0,1.0,1.0,1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )

    def Lights (self, mode = None):
        """Customization point for setting up global illumination parameters
        Depending on the mode, should either enable or disable
        lighting for all of those lights in the scene.

        The default implementation enables lighting and light 0
        if render mode is not select, disables them otherwise.

        Note: This method is only called if there is no scene graph,
        and if there is no self.SetupBindables( mode ) method
        available on the Context.
        """
        # This code is not OpenGL 3.1 compatible
        if mode.visible and mode.lighting:
            # Enable lighting calculations
            glEnable(GL_LIGHTING);
            # Enable the default light zero (shining forward on the z axis)
            glEnable(GL_LIGHT0);
        else:
            glDisable(GL_LIGHTING);
            glDisable(GL_LIGHT0);
            
    def addPickEvent( self, event ):
        """Add event to list of events to be processed by selection-render-mode

        This is a method of the Context, rather than the
        rendering pass (which might seem more elegant given
        that it is the rendering pass which deals with the
        events being registered) because the requests to
        render a pick event occur outside of the rendering
        loop.  As a result, there is (almost) never an
        active context when the pick-event-request comes in.
        """
        self.pickEvents[ (event.type, event.getKey()) ] = event
    def getPickEvents( self ):
        """Get the currently active pick-events"""
        return self.pickEvents
    def getSceneGraph( self ):
        """Get the scene graph for the context (or None)

        You must return an instance of:
        
            OpenGLContext.scenegraph.scenegraph.SceneGraph

        Normally you would create that using either a loader
        from OpenGLContext.loader:
        
            from OpenGLContext.loader import vrml97
            def OnInit( self ):
                self.sg = vrml97.load( 'c:\\somefile\\world.wrl' )

        or by using the classes in OpenGLContext.scenegraph.basenodes:
        
            from OpenGLContext.scenegraph import basenodes
            def OnInit( self ):
                self.sg = basenodes.sceneGraph(
                    children = [
                        basenodes.Transform(...)
                    ],
                )

        to define the scenegraph in Python code.
        """
        return getattr( self, 'sg', None)
    def renderedChildren( self, types = None ):
        """Get the rendered children of the scenegraph"""
        sg = self.getSceneGraph()
        if not sg:
            return (ContextRenderNode,)
        else:
            return (sg,)

    ### app-framework stuff
    APPLICATION_NAME = 'OpenGLContext'
    def getApplicationName( cls ):
        """Retrieve the application name for configuration purposes"""
        return cls.APPLICATION_NAME
    getApplicationName = classmethod( getApplicationName )
    def getUserAppDataDirectory( cls ):
        """Retrieve user-specific configuration directory

        Default implementation gives a directory-name in the
        user's (system-specific) "application data" directory
        named
        """
        from OpenGLContext.browser import homedirectory
        base = homedirectory.appdatadirectory()
        if sys.platform == 'win32':
            name = cls.getApplicationName()
        else:
            # use a hidden directory on non-win32 systems
            # as we are storing in the user's home directory
            name = '.%s'%( cls.getApplicationName())
        path = os.path.join(
            base,
            name,
        )
        if not os.path.isdir( path ):
            os.makedirs( path, mode=0770 )
        return path
    getUserAppDataDirectory = classmethod( getUserAppDataDirectory )

    ttfFileRegistry = None
    def getTTFFiles( self ):
        """Get TrueType font-file registry object"""
        if self.ttfFileRegistry:
            return self.ttfFileRegistry
        from ttfquery import ttffiles
        registryFile = os.path.join(self.getUserAppDataDirectory(), 'font_metadata.cache')
        from OpenGLContext.scenegraph.text import ttfregistry
        registry = ttfregistry.TTFRegistry()
        if os.path.isfile( registryFile ):
            log.info( "Loading font metadata from cache %r", registryFile )
            registry.load( registryFile )
            if not registry.fonts:
                log.warn( "Re-scanning fonts, no fonts found in cache" )
                registry.scan()
                registry.save()
                log.info( "Font metadata stored in cache %r", registryFile )
        else:
            log.warn( "Scanning font metadata into cache %r, please wait", registryFile )
            registry.scan()
            registry.save( registryFile )
            log.info( "Font metadata stored in cache %r", registryFile )
        # make this a globally-available object
        Context.ttfFileRegistry = registry
        return registry

    def getDefaultTTFFont( cls, type='sans' ):
        """Get the current user's preference for a default font"""
        import os
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join( directory, 'defaultfont-%s.txt'%(type.lower(),) )
        name = None
        try:
            name = open(filename).readline().strip()
        except IOError, err:
            pass
        if not name:
            name = None
        return name
    getDefaultTTFFont = classmethod( getDefaultTTFFont )
    def setDefaultTTFFont( cls, name, type='sans' ):
        """Set the current user's preference for a default font"""
        import os
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join( directory, 'defaultfont-%s.txt'%(type.lower(),) )
        if not name:
            try:
                os.remove( filename )
            except Exception, err:
                return False
            else:
                return True
        else:
            try:
                open(filename,'w').write( name )
            except IOError, err:
                return False
            return True
    setDefaultTTFFont = classmethod( setDefaultTTFFont )

    def getContextTypes( cls, type=plugins.InteractiveContext ):
        """Retrieve the set of defined context types
        
        type -- testing type key from setup.py for the registered modules
        
        returns list of setuptools entry-point objects which can be passed to 
        getContextType( name ) to retrieve the actual context type.
        """
        return type.all()
    getContextTypes = classmethod( getContextTypes )
    def getContextType( 
        cls, entrypoint=None, 
        type=plugins.InteractiveContext,
    ):
        """Load a single context type via entry-point resolution
        
        returns a Context sub-class *or* None if there is no such
        context defined/available, will have a ContextMainLoop method 
        for running the Context top-level loop.
        """
        if entrypoint is None:
            entrypoint = cls.getDefaultContextType() or 'glut'
        if isinstance( entrypoint, (str,unicode)):
            for ep in cls.getContextTypes( type ):
                if entrypoint == ep.name:
                    return cls.getContextType( ep, type=type )
            return None
        try:
            classObject = entrypoint.load()
        except ImportError, err:
            return None
        else:
            return classObject
    getContextType = classmethod( getContextType )
    def getDefaultContextType( cls ):
        """Get the current user's preference for a default context type"""
        import os
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join( directory, 'defaultcontext.txt' )
        name = None
        try:
            name = open(filename).readline().strip()
        except IOError, err:
            pass
        if not name:
            name = None
        return name
    getDefaultContextType = classmethod( getDefaultContextType )
    def setDefaultContextType( cls, name ):
        """Set the current user's preference for a default font"""
        import os
        directory = cls.getUserAppDataDirectory()
        filename = os.path.join( directory, 'defaultcontext.txt' )
        if not name:
            try:
                os.remove( filename )
            except Exception, err:
                return False
            else:
                return True
        else:
            try:
                open(filename,'w').write( name )
            except IOError, err:
                return False
            return True
    setDefaultContextType = classmethod( setDefaultContextType )


    def ContextMainLoop( cls, *args, **named ):
        """Mainloop for the context, each GUI sub-class must override this"""
        raise NotImplementedError( 
        """No mainloop specified for context class %r"""%(
            cls,
        ))
    ContextMainLoop = classmethod( ContextMainLoop )

##	def getUserContextPreferences( cls ):
##		"""Retrieve user-specific context preferences"""
##		raise NotImplementedError( """Don't have preferences working yet""" )
    @staticmethod
    def fromConfig( cfg ):
        """Given a ConfigParser instance, produce a configured sub-class"""
        from OpenGLContext import plugins
        from OpenGLContext import contextdefinition
        type = gui = None
        if cfg.has_option( 'context', 'type' ):
            type = cfg.get( 'context', 'type' )
        if cfg.has_option( 'context', 'gui' ):
            gui = cfg.get( 'context', 'gui' )
        if type is None:
            type = 'vrml'
        for plug_type in [
            plugins.InteractiveContext,
            plugins.VRMLContext,
            plugins.Context,
        ]:
            if type == plug_type.type_key:
                type = plug_type 
        baseCls = Context.getContextType( gui, type )
        baseCls = type( 'TestingContext', (baseCls,), {
            'contextDefinition': contextdefinition.ContextDefinition.fromConfig(
                cfg,
            ),
        } )
        return baseCls

### Context render-calling child...
class _ContextRenderNode( nodetypes.Rendering, nodetypes.Children, node.Node ):
    """The Context object as a RenderNode

    Returned as the child of the Context if there
    is no getSceneGraph() result.
    """
    def Render( self, mode ):
        """Delegate rendering to the mode.context.Render method"""
        return mode.context.Render( mode )
ContextRenderNode = _ContextRenderNode()

def getCurrentContext( ):
    """Get the currently-rendering context

    This function allows code running during the render cycle
    to determine the current context.  As a general rule, the
    context is available as rendermode.context from the render
    mode/pass which is passed to the rendering functions as an
    argument.

    Note: this function is deprecated, use the passed rendering
    mode/pass's context attribute instead.
    """
    return Context.currentContext
