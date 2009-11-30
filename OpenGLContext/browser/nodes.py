from OpenGLContext.browser import browsercontext, passes
from vrml import field, node
from math import pi
from OpenGL import GL, GLU, GLUT
from OpenGLContext import context


class VisualViewPlatform( node.Node ):
    """View-platform-like functionality"""
    ### viewplatform stuff
    center = field.newField( "center", "SFVec3f", 1, (0,0,0) )
    autocenter = field.newField( "autocenter", "SFBool", 1, 1 )
    forward = field.newField( "forward", "SFVec3f", 1, (0,0,-1))
    fov = field.newField( "fov", "SFFloat", 1, pi/3.0)
    up = field.newField( "up", "SFVec3f", 1, (0,1,0))
    # bounding box for the entire scene
    range = field.newField( "range", "SFVec3f", 1, (10,10,10))
    # inverse of range
    scale = field.newField( "scale", "SFVec3f", 1, (.1,.1,.1))
    autoscale = field.newField( "autoscale", "SFBool", 1, 1 )
    # what is this trying to do?
    uniform = field.newField( "uniform", "SFBool", 1, 0)
    context = field.newField( "context", "WeakSFNode", 1, None)
    def setViewport( self, x,y ):
        """Set the viewport for aspect calculations"""
    def frustum( self, mode, size ):
        """Set up the viewing Frustum"""
        if size and size[1]:
            aspect = float(size[0])/float(size[1])
        else:
            aspect = 1.0
        GLU.gluPerspective(self.fov * 180.0 / pi, aspect, 0.001, 1000.0)
    def render (self, mode):
        """Set up the perspective and model-view matrices

        Basically, we want to back-project

        context.getBoundingBox() -> center and range/scale values
        """
        self.frustum(mode, mode.context.getViewPort())
        if self.autocenter:
            center = self.context.getBoundingBox().center
        else:
            center = self.center
        # should sanity-check the up vector, range, and forward
        cameraPosition = center + (self.range*(-self.forward))
        GLU.gluLookAt(
            cameraPosition[0],cameraPosition[1],cameraPosition[2],
            center[0],center[1],center[2],
            self.up[0],self.up[1],self.up[2]
        )
    


class VisualContext(browsercontext.BrowserContext):
    # interactivity binding...
    userzoom = field.newField( "userzoom", "SFBool", 1, 0)
    userspin = field.newField( "userspin", "SFBool", 1, 0)

    platform = field.newField( 'platform', 'SFNode', 1, None )
    renderPasses = passes.defaultRenderPasses
    scene = None
    def Viewpoint( self, mode = None):
        """Customization point: Sets up the projection matrix

        This implementation potentially instantiates the
        view platform object, and then calls the object's
        render method with the mode as argument.
        """
        if not self.platform:
            self.platform = VisualViewPlatform(context=self)
        self.platform.render(
            mode = mode,
        )
    ViewPort = context.Context.ViewPort
        
    def getBoundingBox(self):
        """Get the last-known scenegraph bounding-box"""
        from OpenGLContext.scenegraph import boundingvolume
        return boundingvolume.AABoundingBox(
            center = (0,0,0),
            size = (20,20,20),
        )
    def getSceneGraph( self ):
        """Get the current scenegraph"""
        if self.scene is None:
            self.scene = VisualScene()
        return self.scene
    



from OpenGLContext.scenegraph import scenegraph
from vrml.vrml97 import nodetypes

class VisualScene( scenegraph.SceneGraph ):
    """A Visual-style scenegraph"""
    # background represents a SimpleBackground-style node...
    background = field.newField( 'background', 'SFColor', 1, (0,0,1))
    # ambient lighting
    ambient = field.newField("ambient", "SFFloat", 1, 0.2)
    # will have to be manually extracted from scenegraph
    lights = field.newField("lights", "MFVec3f", 1, [(2,3,2),])
    # will have to be manually extracted from scenegraph
    objects = field.newField("objects", "MFNode", 1, list)
    def renderedChildren( self, types= (nodetypes.Children, nodetypes.Rendering,) ):
        """List of all children that are instances of given types

        Default scenegraph uses "children" while the VPython
        scenegraph uses "objects"...
        """
        
        items = [
            child for child in self.objects
            if isinstance( child, types)
        ]
        return items
