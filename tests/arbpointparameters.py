#! /usr/bin/env python
'''Test point parameter rendering code
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from math import pi
import sys

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.events.timer import Timer
from OpenGL.GL import *
from OpenGL.GL.ARB.point_parameters import *

class TestContext( BaseContext ):
	initialPosition = (0,0,3) # set initial camera position, tutorial does the re-positioning
	usingExtension = True
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		haveExtension = self.extensions.initExtension( "GL.ARB.point_parameters")
		if not haveExtension:
			print 'GL_ARB_point_parameters not supported!'
			sys.exit(1)
		print """Should see a sine wave overhead"""
		print 'press x toggle use of the extension'
		self.addEventHandler(
			'keypress', name = 'x', function = self.OnDisableExtension
		)
		
		line = arange(0.0,1.0,.01)
		line2 = line[::-1]
		self.coordinate = Coordinate(
			point = map(None, line,[0]*len(line), [0]*len(line) ),
		)
		self.color = Color(
			color = map(None,line, [0]*len(line), line2 ),
		)
		maxPointSize = 4.0
		glPointSize( maxPointSize )
		glPointParameterfvARB( GL_POINT_DISTANCE_ATTENUATION_ARB, (0.,0.,1))
		glPointParameterfARB( GL_POINT_SIZE_MAX_ARB, maxPointSize )
		self.sg = sceneGraph(
			children = [
				Transform(
					translation = (-.5,.25,0),
					scale = (2,2,2),
					rotation = (1,0,0,1.57),
					children = [
						Shape(
							geometry = PointSet(
								coord = self.coordinate,
								color = self.color,
							),
						),
					],
				),
			],
		)
		self.time = Timer( duration = 8.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
	def OnTimerFraction( self, event ):
		"""On event from the timer, generate new geometry"""
		xes = arange( 0.0, 1.0, 0.01 )
		range = (xes - event.fraction())*math.pi*2
		yes = sin( range )
		points = map(None,xes,yes,[0.0]*len(xes))
		colors = map(None,xes,xes[::-1],[0.0]*len(xes))
		self.coordinate.point = points
		self.color.color = colors
	def OnDisableExtension( self, event ):
		if self.usingExtension:
			glPointParameterfvARB( GL_POINT_DISTANCE_ATTENUATION_ARB, (1.,0.,0.))
			print 'point attenuation', glGetFloat( GL_POINT_DISTANCE_ATTENUATION_ARB )
			self.usingExtension = False
		else:
			glPointParameterfvARB( GL_POINT_DISTANCE_ATTENUATION_ARB, (0.,0.,1))
			print 'point attenuation', glGetFloat( GL_POINT_DISTANCE_ATTENUATION_ARB )
			self.usingExtension = True
		

if __name__ == "__main__":
	MainFunction ( TestContext)

