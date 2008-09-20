from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
	def OnInit( self ):
		"""Initialise and set up the scenegraph"""
		print 'Should see a textured box where the texture is loaded from a url'
		self.sg = sceneGraph(
			children = [
				Transform(
					rotation = (0,1,0,.8),
					children = [
						Shape(
							geometry = Box( size=(4,4,2) ),
							appearance = Appearance(
								material = Material(
									diffuseColor =(1,1,1)
								),
								texture = ImageTexture(
									url = "http://www.vrplumber.com/maps/thesis_icon.jpg",
								),
							),
						),
					],
				),
			],
		)
	def getSceneGraph( self ):
		"""With older OpenGLContext versions need to explicitly return this"""
		return self.sg

if __name__ == "__main__":
	MainFunction( TestContext )
