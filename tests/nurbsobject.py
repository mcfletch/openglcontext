#! /usr/bin/env python
'''Nurbs object test (draw trimmed NURBs surface geometry)

The test data arrays are taken from the RedBook trim demo
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import nurbs

class TestContext( BaseContext ):
	initialPosition = (0,0,3) # set initial camera position, tutorial does the re-positioning
	def buildControlPoints( self ):
		ctlpoints = zeros( (4,4,3), 'd')
		for u in range( 4 ):
			for v in range( 4):
				ctlpoints[u][v][0] = 2.0*(u - 1.5)
				ctlpoints[u][v][1] = 2.0*(v - 1.5);
				if (u == 1 or u ==2) and (v == 1 or v == 2):
					ctlpoints[u][v][2] = 3.0;
				else:
					ctlpoints[u][v][2] = -3.0;
		return ctlpoints
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		nurbs.initialise( self )
		print """You should see a multi-coloured Nurbs surface
with an ice-cream-cone-shaped trimming curve
(a hole cut out of it)."""
		
		color = zeros( (4,4,3), 'd' )
		color[0,:,:] = (1.,0,0)
		color[1,:,:] = (.66,.33,0)
		color[2,:,:] = (.33,.66,0)
		color[3,:,:] = (0,1.,0)
		
		self.shape = Shape(
			appearance = Appearance(
				material = Material(),
			),
			geometry = TrimmedSurface(
				surface = NurbsSurface(
					controlPoint = self.buildControlPoints(),
					color = color,
					vDimension = 4,
					uDimension = 4,
					uKnot = array(  [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], 'd'),
					vKnot = array(  [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], 'd'),
					
				),
				trimmingContour = [
					Contour2D(
						children = [
							Polyline2D(
								# outside edge
								point = array(  [
									[0.0, 0.0],
									[1.0, 0.0],
									[1.0, 1.0],
									[0.0, 1.0],
									[0.0, 0.0],
								], 'd')
							),
						],
					),
					Contour2D(
						children = [
							Polyline2D(
								# inside edge
								point = array([
									[0.75, 0.5],
									[0.5, 0.25],
									[0.25, 0.5],
								],'d')
							),
							NurbsCurve2D(
								knot = array( [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], 'd'),
								controlPoint = array( [
									[0.25, 0.5],
									[0.25, 0.75],
									[0.75, 0.75],
									[0.75, 0.5],
								],'d')
							)
						]
					),
				]
			),
		)
		self.sg = sceneGraph(
			children = [ self.shape ],
		)

if __name__ == "__main__":
	MainFunction ( TestContext)

