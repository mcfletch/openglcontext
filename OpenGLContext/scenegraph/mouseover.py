"""Simple node for constructing mouse-over functionality"""
from OpenGLContext.scenegraph.switch import Switch
from vrml.vrml97 import nodetypes
from vrml import field

class MouseOver( nodetypes.Bindable, Switch ):
    """Simple node for constructing mouse-over functionality
    
    Give it two values for whichChoice and the first will be
    displayed by default, until the mouse moves over it, at
    which point the second will be displayed.
    
    Generally assumes that you've got two objects of the same
    size, otherwise the objects will flash in and out as the
    mouse leaves the object when the different shape appears.
    """
    PROTO = 'MouseOver'
    bound = False
    whichChoice = field.newField( 'whichChoice', 'SFInt32', 1, 0)
    def bind( self, context ):
        """Setup node-specific event callbacks and the like

        This uses the context to register callbacks, as should
        be done whenever registering per-context callbacks.
        """
        if not self.bound:
            self.bound = True
            context.addEventHandler(
                'mousein', node=self, 
                function = self.OnMouseIn,
            )
            context.addEventHandler(
                'mouseout', node=self, 
                function = self.OnMouseOut,
            )
    def OnMouseOut( self, event ):
        """Switch back to default state"""
        self.whichChoice = 0
        event.context.triggerRedraw(1)
    def OnMouseIn( self, event ):
        """Switch back to highlight state"""
        self.whichChoice = 1
        event.context.triggerRedraw(1)