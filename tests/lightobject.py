#! /usr/bin/env python
'''Test for Light objects and their properties...
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph import basenodes
from OpenGL.GL import *

class TestContext( BaseContext ):
	angle = 0
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		print """You should see an opaque sphere and a translucent cylinder
with rotating lighting in three colours."""

		self.lights = [
			basenodes.PointLight(
				location = (-2,2,2),
				color=(1,0,0),
			),
			basenodes.SpotLight(
				location = (0,0,4),
				color = (0,0,1),
				direction = (0,0,-1),
			),
			basenodes.DirectionalLight(
				direction = (-10,-10,0),
				color= (0,1,0),
			),
		]
		self.lightTransform = basenodes.Transform(
			children = self.lights,
		)
		self.sg = basenodes.sceneGraph(
			children = [
				self.lightTransform,
				basenodes.Shape(
					geometry = basenodes.Sphere(
					),
					appearance = basenodes.Appearance(
						material = basenodes.Material( diffuseColor=(1,1,1) ),
					),
				),
				basenodes.Transform(
					translation = (1,-.5,2),
					rotation = (1,0,0,.5),
					children = [
						basenodes.Shape(
							geometry = basenodes.Cylinder(
							),
							appearance = basenodes.Appearance(
								material = basenodes.Material(
									diffuseColor=(1,1,1),
									shininess = .8,
									transparency = .3,
								),
							),
						),
					],
				),
			],
		)
		
	def OnIdle( self, ):
		self.angle += .005
		self.lightTransform.rotation = (0,1,0,self.angle )
		self.triggerRedraw(1)
		return 1
	

if __name__ == "__main__":
	MainFunction ( TestContext)

