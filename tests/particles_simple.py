#! /usr/bin/env python
'''=Particle System (PointSet)=

[particles_simple.py-screen-0001.png Screenshot]
[particles_simple.py-screen-0002.png Screenshot]
[particles_simple.py-screen-0003.png Screenshot]

This tutorial demonstrates the creation of a "particle system"
which in this case creates a crude simulation of a water fountain.
We use Numpy to do the heavy lifting of the actual updates to 
the particles.  We use the PointSet object's ability to render 
using the applied texture as a sprite (GL.ARB.point_parameters).
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
from OpenGLContext.events.timer import Timer
import random
from OpenGLContext.scenegraph.basenodes import *
try:
    import RandomArray
except ImportError, err:
    RandomArray = None
try:
    from OpenGLContext.scenegraph.text import glutfont
except ImportError:
    glutfont = None
'''These are the parameters we're going to use to create our 
simulation.  Particle systems would normally encapsulate these 
in a node somewhere, but we want to see what we're doing.

 * gravity -- applied to each in-play droplet 
 * emitter -- location from which to emit 
 * count -- number of points allocated 
 * initialColor -- initial colour for each droplet 
 * pointSize -- how big the droplets are 
 * colorVelocities -- change in colour over time 
 * initialVelocityVector -- nozzle speed of the droplets
'''
gravity = -9.8 #m/(s**2)
emitter = (0,0,0)
count = 3000
initialColor = (1,.9,.9)
pointSize = 1.5
colorVelocities = [1,.9,.7]
initialVelocityVector = array( [1.5,20.,1.5], 'd')

class TestContext( BaseContext ):
    """Particle testing code context object"""
    initialPosition = (0,7,20)
    lastFraction = 0.0
    def OnInit( self ):
        """Do all of our setup functions..."""
        BaseContext.OnInit( self )
        print """You should see something that looks vaguely like
a water-fountain, with individual droplets starting
blue and turning white."""
        '''The PointSet node will do the actual work of rendering 
        our points into the GL.  We start it off with all points 
        at the emitter location and with initial colour.'''
        self.points = PointSet(
            coord = Coordinate(
                point = [emitter]*count
            ),
            color = Color(
                color = [initialColor]*count
            ),
            minSize = 7.0,
            maxSize = 10.0,
            attenuation = [0,1,0],
        )
        '''We use a simple Appearance node to apply a texture to the 
        PointSet, the PointSet will use this to enable sprite-based 
        rendering if the extension(s) are available.'''
        self.shape = Shape(
            appearance = Appearance(
                texture = ImageTexture( url='_particle.png' ),
            ),
            geometry = self.points,
        )
        self.text = Text(
            string = ["""Current multiplier: 1.0"""],
            fontStyle = FontStyle(
                family='SANS', format = 'bitmap',
                justify = 'MIDDLE',
            ),
        )
        self.sg = sceneGraph( children = [
            self.shape,
            SimpleBackground( color = (.5,.5,.5),),
            Transform(
                translation = (0,-1,0),
                children = [
                    Shape(
                        geometry = self.text
                    ),
                ],
            ),
        ] )
        self.velocities = array([ (0,0,0)]*count, 'd')
        self.colorVelocities = array( colorVelocities, 'd')
        print '  <s> make time pass more slowly'
        print '  <f> make time pass faster'
        print '  <h> higher'
        print '  <l> (L) lower'
        print '  <[> smaller drops'
        print '  <]> larger drops'
        self.addEventHandler( "keypress", name="s", function = self.OnSlower)
        self.addEventHandler( "keypress", name="f", function = self.OnFaster)
        self.addEventHandler( "keypress", name="h", function = self.OnHigher)
        self.addEventHandler( "keypress", name="l", function = self.OnLower)
        self.addEventHandler( "keypress", name="]", function = self.OnLarger)
        self.addEventHandler( "keypress", name="[", function = self.OnSmaller)
        '''First timer will provide the general simulation heartbeat.'''
        self.time = Timer( duration = 1.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        '''Second timer provides a cycle on which the fountain 
        reduces/increases the speed at which droplets are started.'''
        self.time2 = Timer( duration = 5.0, repeating = 1 )
        self.time2.addEventHandler( "cycle", self.OnLower )
        self.time2.register (self)
        self.time2.start ()

    ### Timer callback
    def OnTimerFraction( self, event ):
        """Perform the particle-system simulation calculations"""
        points = self.points.coord.point
        colors = self.points.color.color
        '''Our calculations are going to need to know how much time 
        has passed since our last event.  This is complicated by the 
        fact that a "fraction" event is cyclic, returning to 0.0 after 
        1.0.'''
        f = event.fraction()
        if f < self.lastFraction:
            f += 1.0
        deltaFraction = (f-self.lastFraction)
        self.lastFraction = event.fraction()
        '''If we have received an event which is so soon after a 
        previous event as to have a 0.0s delta (this does happen 
        on some platforms), then we need to ignore this simulation 
        tick.'''
        if not deltaFraction:
            return
        '''Each droplet has been moving at their current velocity 
        for deltaFraction seconds, update their position with the 
        results of this speed * time.  You'll note that this is not 
        precisely accurate for a body under acceleration, but it 
        makes for easy calculations.  Two machines running 
        the same simulation will get *different* results here, as 
        a faster machine will apply acceleration more frequently,
        resulting in a faster total velocity.'''
        points = points + (self.velocities*deltaFraction)
        '''We also cycle the droplet's colour value, though with 
        the applied texture it's somewhat hard to see.'''
        colors = colors + (self.colorVelocities*deltaFraction)
        '''Now, apply acceleration to the current velocities such 
        that the droplets have a new velocity for the next simulation 
        tick.'''
        self.velocities[:,1] = self.velocities[:,1] + (gravity * deltaFraction)
        '''Find all droplets which have "retired" by falling below the 
        y==0.0 plane.'''
        below = less_equal( points[:,1], 0.0)
        dead = nonzero(below)
        if isinstance( dead, tuple ):
            # weird numpy change here...
            dead = dead[0]
        if len(dead):
            '''Move all dead droplets back to the emitter.'''
            def put( a, ind, b ):
                for i in ind:
                    a[i] = b
            put( points, dead, emitter)
            '''Re-spawn up to half of the droplets...'''
            dead = dead[:(len(dead)//2)+1]
            if len(dead):
                '''Reset color to initialColor, as we are sending out 
                these droplets right now.'''
                put( colors, dead, initialColor)
                '''Assign slightly randomized versions of our initial 
                velocity for each of the re-spawned droplets.  Replace 
                the current velocities with the new velocities.'''
                if RandomArray:
                    velocities = (RandomArray.random( (len(dead),3) ) + [-.5, 0.0, -.5 ]) * initialVelocityVector
                else:
                    velocities = [
                        array( (random.random()-.5, random.random(), random.random()-.5), 'f')* initialVelocityVector
                        for x in xrange(len(dead))
                    ]
                def copy( a, ind, b ):
                    for x in xrange(len(ind)):
                        i = ind[x]
                        a[i] = b[x]
                copy( self.velocities, dead, velocities)
        '''Now re-set the point/color fields so that the nodes notice 
        the array has changed and they update the GL with the changed 
        values.'''
        self.points.coord.point = points
        self.points.color.color = colors
        
    '''Set up keyboard callbacks'''
    def OnSlower( self, event ):
        self.time.internal.multiplier = self.time.internal.multiplier /2.0
        if glutfont:
            self.text.string = [ "Current multiplier: %s"%( self.time.internal.multiplier,)]
        else:
            print "slower",self.time.internal.multiplier
    def OnFaster( self, event ):
        self.time.internal.multiplier = self.time.internal.multiplier * 2.0
        if glutfont:
            self.text.string = [ "Current multiplier: %s"%( self.time.internal.multiplier,)]
        else:
            print "faster",self.time.internal.multiplier
    def OnHigher( self, event ):
        global initialVelocityVector
        initialVelocityVector *= [1,1.25,1]
    def OnLower( self, event ):
        global initialVelocityVector
        if hasattr(event,'count') and not event.count() % 4:
            initialVelocityVector[:] = [1.5,20,1.5]
        else:
            initialVelocityVector /= [1,1.5,1]
    def OnLarger( self, event ):
        self.points.minSize += 1.0
        self.points.maxSize += 1.0
    def OnSmaller( self, event ):
        self.points.minSize = max((0.0,self.points.minSize-1.0))
        self.points.maxSize = max((1.0,self.points.maxSize-1.0))

if __name__ == "__main__":
    TestContext.ContextMainLoop()