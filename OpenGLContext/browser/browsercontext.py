from OpenGLContext.loaders import loader
from OpenGLContext import wxinteractivecontext
import traceback, time

def loadCallback( context, url, scenegraph ):
    """Standard "loading" callback"""
    context.scene = scenegraph
    context.triggerRedraw( force = 1 )

BaseContext = wxinteractivecontext.wxInteractiveContext

class BrowserContext(BaseContext):
    """VRML browser-type context"""
    scene = None
    frameCount = 0
    frameTime = 0
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.addEventHandler( 'keypress', name = '<escape>',function = self.OnQuit )
        self.HandleCommandLine()
        self.addEventHandler( 'keypress', name = 'f',function = self.OnFrameRate )
    def HandleCommandLine( self ):
        """Handle command-line arguments as a stand-alone browser"""
        import sys
        if sys.argv[1:]:
            self.loadUrl( sys.argv[1:] )
    def loadUrl( self, url, replaceCurrent=1 ):
        """Load the given URL into the browser"""
        import threading
        threading.Thread(
            name = "Background load of %s"%(url),
            target = self.loadBackground,
            args = ( url, loadCallback,),
        ).start()
    def loadBackground( self, url, callback, errorBack = None ):
        """Load a given URL, call callback on success

        If errorBack is provided, call it on errors, otherwise
        print a standard traceback.
        """
        try:
            sg = loader.Loader.load( url )
            callback( self, url, sg )
        except Exception, err:
            if errorBack:
                errorBack( self, url, err )
            else:
                traceback.print_exc()
        
    def getSceneGraph( self ):
        """Get the scene graph for the context (or None)"""
        return self.scene

    def OnDraw (self, *arguments, **namedarguments):
        """Override to provide frame-rate reporting"""
        t = time.clock()
        result = BaseContext.OnDraw( self, *arguments, **namedarguments )
        if result:
            self.frameTime += time.clock()-t
            self.frameCount += 1
        return result
        