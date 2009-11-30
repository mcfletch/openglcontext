"""Interactions for navigating the context"""
from gettext import gettext as _
from OpenGLContext.move import movementmanager
from OpenGLContext import quaternion
from OpenGLContext.events import timer
import math

class Direct( movementmanager.MovementManager ):
    """OpenGLContext's original manipulation for the view platform"""
    commands = movementmanager.MovementManager.commands + [
        # User-name, key, function-name
        (_('Forward'), 'forward','forward'),
        (_('Back'), 'backward','backward' ),
        (_('Up'), 'up','up' ),
        (_('Down'), 'down', 'down' ),
        (_('Left'), 'left', 'left' ),
        (_('Right'), 'right', 'right' ),
        
        (_('Turn Up'), 'turnup', 'turnup' ),
        (_('Turn Down'), 'turndown', 'turndown' ),
        (_('Turn Left'), 'turnleft', 'turnleft' ),
        (_('Turn Right'), 'turnright', 'turnright' ),
        
        (_('Straighten'), 'straighten','straighten'),
        
        (_('Faster'), 'faster', 'faster' ),
        (_('Slower'), 'slower','slower' ),
    ]
    commandBindings = dict(
        forward=dict( eventType='keyboard', name='<up>', state=1, modifiers=(0,0,0) ),
        backward=dict( eventType='keyboard', name='<down>', state=1, modifiers=(0,0,0) ),
        up=dict( eventType='keyboard', name='<up>', state=1, modifiers=(0,0,1)),
        turnup=dict(eventType='keyboard', name='<up>', state=1, modifiers=(0,1,0)),
        turndown=dict(eventType='keyboard', name='<down>', state=1, modifiers=(0,1,0)),
        down=dict(eventType='keyboard', name='<down>', state=1, modifiers=(0,0,1),),
        turnleft=dict(eventType='keyboard', name='<left>', state=1, modifiers=(0,0,0),),
        left=dict(eventType='keyboard', name='<left>', state=1, modifiers=(0,0,1)),
        turnright=dict(eventType='keyboard', name='<right>', state=1, modifiers=(0,0,0),),
        right=dict(eventType='keyboard', name='<right>', state=1, modifiers=(0,0,1),),
        straighten=dict(eventType='keypress', name='-', modifiers=(0,0,0),),
        slower=dict(eventType='keypress', name='[', modifiers=(0,0,0),),
        faster=dict(eventType='keypress', name=']', modifiers=(0,0,0),),
        examine=dict(eventType='mousebutton', button=1, state = 1, modifiers=(0,0,0),),
    )
    STEPDISTANCE = 0.5 # 1/2 of a unit
    TURNANGLE = math.pi/32

    ### LOGO-like commands...
    def turn (self, deltaOrientation= (0,1,0,math.pi/4) ):
        """Apply rotation within the current orientation

        In essence, this allows you to "turn your head"
        which gives you the commonly useful ability to
        function from your own frame of reference.

        For example:
            turn( 1,0,0,angle ) will rotate the camera up
                from its current view orientation
            turn( 0,1,0,angle ) will rotate the camera about
                the current horizon

        This method is implemented almost entirely within
        the quaternion class.  Quaternion's have considerable
        advantages for this type of work, as they do not
        become "warped" with successive rotations.
        """
        self.platform.setOrientation( self.platform.relativeOrientation( deltaOrientation ) )
        self.context.triggerRedraw(1)

    def stepRelative( self, x=0,y=0,z=0 ):
        """Step this distance in relative (view) coordinates"""
        self.platform.moveRelative( x=x,y=y,z=z )
        self.context.triggerRedraw(1)

    def forward( self, event ):
        """(callback) Move platform forward by STEPDISTANCE

        triggers redraw after completion
        """
        self.stepRelative( z = -self.STEPDISTANCE )
    def backward( self, event ):
        """(callback) Move platform backward by STEPDISTANCE

        triggers redraw after completion
        """
        self.stepRelative( z = self.STEPDISTANCE )
    def up( self, event ):
        """(callback) Move platform upward by STEPDISTANCE

        triggers redraw after completion
        """
        self.stepRelative( y = self.STEPDISTANCE )
    def down( self, event ):
        """(callback) Move platform downward by STEPDISTANCE

        triggers redraw after completion
        """
        self.stepRelative( y = -self.STEPDISTANCE )
    def left( self, event ):
        """(callback) Move platform left by STEPDISTANCE

        triggers redraw after completion
        """
        self.stepRelative( x = -self.STEPDISTANCE )
    def right( self, event ):
        """(callback) Move platform right by STEPDISTANCE

        triggers redraw after completion
        """
        self.stepRelative( x = self.STEPDISTANCE )
    def turnup( self, event ):
        """(callback) Rotates "head" backward (looks upward) by TURNANGLE

        triggers redraw after completion
        """
        self.turn( (1.0,0.0,0.0, self.TURNANGLE) )
    def turndown( self, event ):
        """(callback) Rotates "head" forward (looks downward) by TURNANGLE

        triggers redraw after completion
        """
        self.turn( (1.0,0.0,0.0, -self.TURNANGLE) )
    def turnleft( self, event ):
        """(callback) Rotates "head" to the left by TURNANGLE

        triggers redraw after completion
        """
        self.turn( (0.0,1.0,0.0, self.TURNANGLE) )
    def turnright( self, event ):
        """(callback) Rotates "head" to the right by TURNANGLE

        triggers redraw after completion
        """
        self.turn( (0.0,1.0,0.0, -self.TURNANGLE) )
    def straighten( self, event ):
        """(callback) Straightens the platform orientation

        Attempts to make the orientation equal to the
        y-axis orientation of the current orientation.

        In other words, tries to make the camera's horizon
        equal to the object-space horizon (the x,z plane)
        without altering the y-axis orientation.

        See:
            OpenGLContext.viewplatform.ViewPlatform.straighten
        
        triggers redraw after completion
        """
        self.platform.straighten()
        self.context.triggerRedraw(1)
        
    def faster( self, event ):
        """Increase our walking speed"""
        self.STEPDISTANCE *= 1.5
    def slower( self, event ):
        """Decrease our walking speed"""
        self.STEPDISTANCE /= 1.5
