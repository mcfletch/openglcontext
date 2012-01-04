"""First-person-shooter like movement control"""
from gettext import gettext as _
from OpenGLContext.move import direct
from OpenGLContext import arrays
from OpenGLContext.events import timer 
from OpenGLContext.scenegraph import interpolators
import math

class Smooth( direct.Direct ):
    """Smooth movement using position interpolators
    
    Provides much smoother interaction than the direct base-class, 
    produces smoothed interpolations between the current position/orientation
    and the target.
    """
    STEPDURATION = 0.05 # 1/20 of a second
    TURNANGLE = math.pi/64
    TURNDURATION = 0.05
    STEPDISTANCE = .25
    timer = None
    posInterpolator = None
    posTimer = orientTimer = None
    startOrient = None
    targetOrient = None
    
    def bind( self, context ):
        super( Smooth, self ).bind( context )
        self.posTimer = timer.Timer( duration = self.STEPDURATION )
        self.posTimer.register( context )
        self.orientTimer = timer.Timer( duration = self.TURNDURATION )
        self.orientTimer.register( context )
        self.posInterpolator = interpolators.PositionInterpolator( key = [0.0,1.0])
        self.orientInterpolator = interpolators.OrientationInterpolator( key = [0.0,1.0] )
        #context.addEventHandler(function=self.onFinished, node=self.timer, timetype='stop')
        self.posTimer.addEventHandler(
            timetype='fraction', function=self.onPositionFraction,
        )
        self.orientTimer.addEventHandler(
            timetype='fraction', function=self.onOrientFraction,
        )
    def restartPosTimer( self ):
        """Restart our timer to go to new location"""
        self.posTimer.stop()
        self.posTimer.start()
    def restartOrientTimer( self ):
        """Restart our timer to go to new location"""
        self.orientTimer.stop()
        self.orientTimer.start()
    def onPositionFraction( self, event ):
        """Process fractional update of our position"""
        fraction = (event.fraction() / 2.0) + .5
        x,y,z = self.posInterpolator.on_set_fraction( fraction )
        self.platform.position = arrays.array([x,y,z,0.0], 'f' )
    def onOrientFraction( self, event ):
        """Process fractional update of our position"""
        fraction = (event.fraction() / 2.0) + .5
        self.platform.quaternion = self.startOrient.slerp( self.targetOrient, fraction )
    def stepRelative( self, x=0,y=0,z=0 ):
        """Step given distance in view-relative coordinates"""
        self.posInterpolator.keyValue = [ 
            self.platform.position[:3], 
            self.platform.relativePosition( x=x,y=y,z=z )[:3],
        ]
        self.restartPosTimer()
    def turn (self, deltaOrientation= (0,1,0,math.pi/4) ):
        turned = self.platform.relativeOrientation( deltaOrientation )
        self.startOrient = self.platform.quaternion # self.platform.quaternion.slerp( turned, .05 )
        self.targetOrient = turned 
        self.restartOrientTimer()
