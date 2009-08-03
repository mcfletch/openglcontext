#! /usr/bin/env python
'''Tests rendering of the Box geometry object
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.arrays import *
from OpenGL.GL import *
import string, time

class TestContext( BaseContext ):
	def OnInit( self ):
		"""Scene set up and initial processing"""
		print """You should see an elongated box over a white background
	The box should have a mapped texture (a stained-glass window)
	and should be centered on the window.
"""
		print 'press i to choose another texture for the box'
		self.addEventHandler(
			'keypress', name = 'i', function = self.OnImageSwitch
		)
		print 'press s to choose another size for the box'
		self.addEventHandler(
			'keypress', name = 's', function = self.OnSizeSwitch
		)
		appear = Appearance(
			material = Material(
				diffuseColor =(.2,.2,.2),
				shininess = .5,
				specularColor = (1,0,0),
			),
		)
		self.sg = sceneGraph(
			children = [
				Transform( 
					DEF = 'g1',
					children = [
						Shape(
							geometry = Gear(
								teeth = 20,
								tooth_depth = 0.05,
							),
							appearance = appear,
						),
					],
				),
				Transform( 
					DEF = 'g2',
					translation = (2.0,0,0),
					rotation = (0,0,1,1*(2*pi)/120.),
					children = [
						Shape(
							geometry = Gear(
								teeth = 60,
								outer_radius = 1.5,
								tooth_depth = 0.05,
							),
							appearance = appear,
						),
					],
				),
			],
		)
	def OnImageSwitch( self, event=None ):
		"""Choose a new mapped texture"""
		self.currentImage = currentImage = self.currentImage+1
		newImage = images[currentImage%len(images)]
		self.shape.appearance.texture.url = [ newImage ]
		print "new image (loading) ->", newImage
	def OnSizeSwitch( self, event=None ):
		"""Choose a new size"""
		self.currentSize = currentSize = self.currentSize+1
		newSize = sizes[currentSize%len(sizes)]
		self.shape.geometry.size = newSize
		print "new size ->", newSize
		self.triggerRedraw(1)
	

if __name__ == "__main__":
	MainFunction ( TestContext)

