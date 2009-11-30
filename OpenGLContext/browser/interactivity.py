"""Interactivity in VRML contexts

What I would like to do is create a mechanism
for binding python actions to a particular prototype
without requiring explicit subclassing within the
python class.  Something like:

8< ________ somefile.wrl ____
#VRML V2.0 utf8

PROTO TestNode [
    exposedField SFVec3f position 0,0,0
] {
    Shape { geometry Sphere {} appearance Appearance { material DEF Material Material{}}}
}

8< __________ regnode.py ____



"""


class ProtoScript:
    '''Node providing scripting for a given node-name'''
    PROTO = "TestNode"
    def __init__( self, *arguments, **named ):
        super( ProtoScript,self).__init__(*arguments, **named)
        self.OnInit()
    def OnInit( self ):
        '''Initialisation of the node'''
        self.bindFieldHandlers() # e.g. set_position
        self.registerCallback( )

    def registerCallback(
        self, button= 0, state=0, modifiers = (0,0,0),
        function = None,
    ):
        '''Register a (mouse) callback for our name'''
    def captureEvents( self, eventType, manager=None ):
        '''Capture the given events to the given manager'''
    def bindFieldHandlers( self ):
        '''Scan the class binding field handlers for this node'''
        for field in protofunctions.getFields( self ):
            for name in ('set_'+field.name, field.name+'_changed'):
                if hasattr( self, name):
                    field.watch( self, getattr( self, name) )
        

    def set_position( self, value, field, event ):
        '''Handle setting of position'''
    def on_mouseover( self, event ):
        '''Change colour on mouse-over'''
        self.scenegraph.getDEF( 'Material' ).diffuseColor = (1,0,0)
        self.timer = Timer(.3)
        self.timer.registerCallback( self.OnTimeout )
        self.timer.start( )