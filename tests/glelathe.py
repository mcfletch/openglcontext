#! /usr/bin/env python
'''Test of gleLathe and related functions
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
from math import pi
from OpenGLContext.scenegraph import extrusions

contour = array([
	(0,0), (1,0),
	(1,1), (0,1),
	(0,0),
],'d')

normals = array([
	(0,-1), (1,0),
	(0,1), (-1,0),
],'d')

	

from OpenGLContext.scenegraph.basenodes import *
class TestContext( BaseContext ):
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		print """You should see a round "washer" formed by sweeping a square
through a circle.  A drill-like screw should penetrate the
center of the washer.  Around the washer should be a cone-
shaped "spring", which should extend some distance downward."""
		appearance = Appearance(
			material=Material(),
			texture = ImageTexture(
				url = "wrls/irradiation.jpg",
			),
			textureTransform = TextureTransform(
				scale = [8,1],
			),
		)
		self.sg = sceneGraph(
			children = [
				Transform(
					rotation = (1,0,0, 1.9),
					scale = (.8,.8,.8),
					children = [
						Shape(
							geometry = extrusions.Lathe(
								contour = contour,
								normals = normals,
								startRadius = 1.5,
								textureMode = 'cylinder vertex',
							),
							appearance = appearance,
						),
						Shape(
							geometry = extrusions.Screw(
								contour = contour,
								normals = normals,
								startZ = -5,
								endZ = 5,
								totalAngle = 5 * pi,
								textureMode = 'flat normal model',
							),
							appearance = Appearance(
								material=Material(),
							),
						),
						Shape(
							geometry = extrusions.Spiral(
								contour = contour,
								normals = normals,
								startRadius = 3,
								deltaRadius = 1.5,
								startZ = 0,
								deltaZ = 1.5,
								totalAngle = 8 * pi,
								textureMode = 'cylinder vertex model',
							),
							appearance = appearance,
						),
					],
				),
				PointLight( location = (20,10,4) ),
				PointLight( location = (-20,10,-4), color=(.3,.3,.5) ),
			],
		)
	

if __name__ == "__main__":
	MainFunction ( TestContext)

