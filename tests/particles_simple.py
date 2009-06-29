#! /usr/bin/env python
"""Simple demonstration code for a particle system
"""
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
from OpenGLContext.events.timer import Timer
import random
try:
	import RandomArray
except ImportError, err:
	RandomArray = None
try:
	from OpenGLContext.scenegraph.text import glutfont
except ImportError:
	glutfont = None

# need different imports for OpenGLContext 1.0
from OpenGLContext.scenegraph.basenodes import *

gravity = -9.8 #m/(s**2)
emitter = (0,0,0)
count = 3000
initialColor = (1,.9,.9)
pointSize = 1.5
colorVelocities = [1,.9,.7]
initialVelocityVector = array( [1.5,20.,1.5], 'd')

class TestContext( BaseContext ):
	"""Particle testing code context object
	"""
	initialPosition = (0,7,20)
	lastFraction = 0.0
	USE_FRUSTUM_CULLING = 0
	def OnInit( self ):
		"""Do all of our setup functions..."""
		BaseContext.OnInit( self )
		print """You should see something that looks vaguely like
a water-fountain, with individual droplets starting
blue and turning white."""
		if glPointParameterf:
			glPointParameterf( GL_POINT_SIZE_MIN, 10.0 )
			glPointParameterf( GL_POINT_SIZE_MAX, 20.0 )
		self.points = PointSet(
			coord = Coordinate(
				point = [emitter]*count
			),
			color = Color(
				color = [initialColor]*count
			)
		)
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
		self.addEventHandler( "keypress", name="s", function = self.OnSlower)
		self.addEventHandler( "keypress", name="f", function = self.OnFaster)
		self.addEventHandler( "keypress", name="h", function = self.OnHigher)
		self.addEventHandler( "keypress", name="l", function = self.OnLower)
		
		self.time = Timer( duration = 1.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
		glPointSize( pointSize )
		self.time2 = Timer( duration = 5.0, repeating = 1 )
		self.time2.addEventHandler( "cycle", self.OnLower )
		self.time2.register (self)
		self.time2.start ()

	### Timer callback
	def OnTimerFraction( self, event ):
		# item1, update all object's position with their last
		# velocity, this isn't quite accurate, but should approximate
		# nicely...
		points = self.points.coord.point
		colors = self.points.color.color
		
		f = event.fraction()
		if f < self.lastFraction:
			f += 1.0
		deltaFraction = (f-self.lastFraction)
#		if deltaFraction:
#			print 'fps', 1.0/deltaFraction
		self.lastFraction = event.fraction()
		if not deltaFraction:
			return
		points = points + (self.velocities*deltaFraction)
		# item2, cycle colours from white, through blue, then yellow, then red
		colors = colors + (self.colorVelocities*deltaFraction)
		# item3, apply acceleration to all velocities...
		self.velocities[:,1] = self.velocities[:,1] + (gravity * deltaFraction)

		# item3, start dead values again
		# move all of the dead to (0,0,0), set colours to (1,1,1)
		# for 1/4 of them, give them a new, random velocity
		below = less_equal( points[:,1], 0.0)
		dead = nonzero(below)
		if isinstance( dead, tuple ):
			# weird numpy change here...
			dead = dead[0]
		if len(dead):
			#print dead.__dims__
			def put( a, ind, b ):
				for i in ind:
					a[i] = b
			put( points, dead, emitter)
			dead = dead[:len(dead)/2]
			if len(dead):
#				print '%s spawning'%len(dead)
				put( colors, dead, initialColor)
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
		self.points.coord.point = points
		self.points.color.color = colors
		
	### Keyboard callbacks
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
		

if __name__ == "__main__":
	MainFunction ( TestContext)

