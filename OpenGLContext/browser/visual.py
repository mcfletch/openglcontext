"""VPython as a target:

Documentation on which we're basing our implementation:
    http://www.vpython.org/webdoc/visual/index.html

What are the key determinants in the visual python
API's success:

    geometry is simply created

    system has interactive operation (shell)

    flat hierarchies used throughout

    multiple mechanisms mapped to the same features

    use of "vector"-based orientation?

    simplified scripting APIs

    assumptions about application operation

    intuitive


"""
from math import pi
from vrml import node, field
import threading, time
from OpenGLContext.arrays import *
import colorsys as _colorsys

_application=None
_GUIThread=None
from OpenGLContext.browser.proxy import proxyField
from OpenGLContext.browser import geometry
from OpenGLContext.browser.vector import *

from OpenGLContext.browser.crayola import color

def _newNode( cls, named ):
    """Construct new instance of cls, set proper color, and add to objects"""
    if not scene.visible:
        scene.visible = 1
    if not [k for k in ('color','red','green','blue') if k in named]:
        named['color'] = scene.foreground
    if 'display' in named:
        target = named['display']
        del named['display'] # XXX fix when have backref added
    else:
        target = scene
    if not target.visible:
        target.visible = 1
    node = cls(**named)
    objs = target.objects
    objs.append( node )
    target.objects = objs
    return node


def rgb_to_hsv(T):
    """Convert RGB tuple to HSV value"""
    return _colorsys.rgb_to_hsv( *T )

def hsv_to_rgb(T):
    """Convert HSV tuple to RGB value"""
    return _colorsys.hsv_to_rgb( *T )


    

def sphere( **named ):
    """Create a sphere, adding to current scene"""
    return _newNode( geometry.VPSphere, named )
def cone( **named ):
    """Create a cone, adding to current scene"""
    return _newNode( geometry.VPCone, named )
def cylinder( **named ):
    """Create a cylinder, adding to current scene"""
    return _newNode( geometry.VPCylinder, named )
def box( **named ):
    """Create a box, adding to current scene"""
    return _newNode( geometry.VPBox, named )
def curve( **named ):
    """Create a new curve, adding to the current scene"""
    return _newNode( geometry.VPCurve, named )

class Display( node.Node ):
    """Proxy object for the "display" (context)

    Visual puts a lot of functionality into this object,
    with most of the fields being "trigger something on set"
    fields, rather than "normal" fields that just store
    values.
    """
    _frame = None
    _context = None

    ### GUI/frame configuration/control stuff
    cursor = proxyField("cursor", "SFNode", 1, None)
    x = proxyField( 'x', "SFInt32", 1, 0)
    y = proxyField( 'y', "SFInt32", 1, 0)
    width = proxyField( 'width', "SFInt32", 1, 400)
    height = proxyField( 'height', "SFInt32", 1, 300)
    title = proxyField( "title", "SFString", 1, "OpenGLContext" )

    visible = proxyField( "visible", "SFBool", 1, 0 )
    
    # exit-on-close
    exit = proxyField( "exit", "SFBool", 1, 1 )

    # background represents a SimpleBackground-style node...
    background = proxyField( 'background', 'SFColor', 1, (0,0,0))
    # ambient lighting
    ambient = proxyField("ambient", "SFFloat", 1, 0.2)
    # will have to be manually extracted from scenegraph
    lights = proxyField("lights", "MFNode", 1, list)
    # will have to be manually extracted from scenegraph
    objects = proxyField("objects", "MFNode", 1, list)

    ### viewplatform stuff
    center = proxyField( "center", "SFVec3f", 1, (0,0,0) )
    autocenter = proxyField( "autocenter", "SFBool", 1, 1 )
    forward = proxyField( "forward", "SFVec3f", 1, (0,0,-1))
    fov = proxyField( "fov", "SFFloat", 1, pi/3.0)
    up = proxyField( "up", "SFVec3f", 1, (0,1,0))
    # bounding box for the entire scene
    range = proxyField( "range", "SFVec3f", 1, (10,10,10))
    # inverse of range
    scale = proxyField( "scale", "SFVec3f", 1, (.1,.1,.1))
    autoscale = proxyField( "autoscale", "SFBool", 1, 1 )

    # what is this trying to do?
    uniform = proxyField( "uniform", "SFBool", 1, 0)
    # interactivity binding...
    userzoom = proxyField( "userzoom", "SFBool", 1, 0)
    userspin = proxyField( "userspin", "SFBool", 1, 0)

    # default object-creation colour
    foreground = proxyField( 'foreground', 'SFColor', 1, (1,0,0))
    
    def select( self ):
        """Makes this the currently-rendering context"""
    def create( self, event ):
        """Create rendering context for this display

        Create the application if necessary, then the
        frame, and return only after the frame has been
        created.
        """
        global _application
        if not _application:
            import wx
            class Application (wx.PySimpleApp):
                def OnInit(self, display=self, event=event):
                    frame = display.createFrame()
                    event.set()
                    self.SetTopWindow(frame)
                    return 1
            _application = app = Application()
            app.MainLoop()
        else:
            self.createFrame()
            event.set()
    def createFrame( self ):
        """Create a new rendering frame"""
        import wx
        from OpenGLContext.browser import nodes
        self._frame = wx.Frame(
            None,
            -1,
            self.title, (self.x,self.y), (self.width,self.height),
        )
        self._context = nodes.VisualContext(
            self._frame,
        )
        return self._frame
            
        
    def set_visible( self, value, fieldObject, *arguments, **named):
        """Visibility has changed, either hide or show"""
        if value and not self._frame:
            e = threading.Event()
            global _GUIThread
            if not _GUIThread:
                _GUIThread = threading.Thread( name="GUIThread", target=self.create, args=(e,) )
                _GUIThread.start()
            else:
                callInGUIThread( self.create, e )
            # if we haven't done anything in 10 seconds, we'll
            # have an exception raised...
            e.wait(10.0) 
        import wx
        if value:
            callInGUIThread( self._frame.Show, True )
        elif self._frame:
            if self.exit:
                callInGUIThread( self._frame.Close )
                while self in scenes:
                    scenes.remove( self )
            else:
                callInGUIThread( self._frame.Show, 0 )
    def set_pos( self, value, field, *arguments, **named ):
        if self._frame:
            callInGUIThread( self._frame.Move, (self.x, self.y))
            setattr(self._context, field.name, value )
    set_x = set_pos
    set_y = set_pos
    def set_size( self, value, field, *arguments, **named ):
        if self._frame:
            callInGUIThread( self._frame.SetSize, (self.width, self.height))
            setattr(self._context, field.name, value )
    set_width = set_size
    set_height = set_size
    
    def set_title( self, value, *arguments, **named ):
        if self._frame:
            callInGUIThread( self._frame.SetTitle, value )
    def _buildPlatformForward( name ):
        """Utility to build forwarder for the context.platform object"""
        def f( self, value, *arguments, **named ):
            if self._frame:
                if self._context and self._context.platform:
                    callInGUIThread( setattr, self._context.platform, name, value)
        return f
    set_center = _buildPlatformForward( 'center' )
    set_autocenter = _buildPlatformForward( 'autocenter' )
    set_autoscale = _buildPlatformForward( 'autoscale' )
    set_range = _buildPlatformForward( 'range' )
    set_uniform = _buildPlatformForward( 'uniform' )
    set_fov = _buildPlatformForward( 'fov' )
    set_up = _buildPlatformForward( 'up' )
    del _buildPlatformForward
    def set_scale( self, value, field, *arguments, **named ):
        """Scale is just a 1/range thing, so update range instead"""
        if isinstance( value, (int,long,float)):
            value = (value,value,value)
        if 0.0 in value:
            r = []
            for i in value:
                if i == 0:
                    r.append( 1.0e32)
                else:
                    r.append( 1.0/i )
            self.range = r
        else:
            self.range = array((1.0,1.0,1.0),'d')/asarray( value, 'd')
    def set_background( self, value, field, *arguments, **named ):
        """Set the scenegraph background attribute"""
        if self._context:
            callInGUIThread( setattr, self._context.getSceneGraph(), field.name, value )
    set_objects = set_background
    
        
def callInGUIThread( callable, *arguments, **named ):
    """Call the callable object in the GUI thread

    This adds a record to the eventCascadeQueue, which will
    executed during the standard DoEventCascade method.

    Note: the callable will be called in the event Cascade
    of the first valid scene context.
    """
    alreadyPut = 0
    for scene in scenes:
        context = getattr(scene,'_context')
        if context and not alreadyPut:
            context.eventCascadeQueue.put( (callable,arguments,named) )
            alreadyPut = 1
        if context:
            context.triggerRedraw( 1 )

scenes = []	
def display( **named ):
    """Create a new display for the system"""
    item = Display( **named )
    scenes.append( item )
    return item

def rate( framesPerSecond=30 ):
    """Allow animation to continue at given rate"""
    ## XXX This is totally wrong, should be tracking last-frame-start
    ## and deciding how to delay based on that :( 
    time.sleep( 1.0/framesPerSecond )
    if scene and scene._context:
        scene._context.triggerRedraw( 1 )

def select( display ):
    """Make the given display the "current" display (global scene)"""
    global scene
    scene = display
    return display

scene = None
select(display(DEF="Primary Window", title="Visual OpenGLContext"))
