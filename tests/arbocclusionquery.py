#! /usr/bin/env python
'''Tests operation of the ARB Occlusion Query extension
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph import imagetexture, shape, material, appearance, box
from OpenGL.GL import *
from OpenGL.GL.ARB.occlusion_query import *
from OpenGLContext.arrays import array
import string, time, sys

images = [
	"nehe_glass.bmp",
	"pimbackground_FR.jpg",
	"nehe_wall.bmp",
]

sizes = [
	(.5,2,.25),
	(1,1,1),
	(2,2,2),
	(3,2,3),
	(4,3,3),
	(3,3,3),
]

class TestContext( BaseContext ):
	currentImage = 0
	currentSize = 0
	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		query = glGenQueriesARB(1)
		glColorMask(GL_FALSE, GL_FALSE, GL_FALSE, GL_FALSE);
		glDepthMask(GL_FALSE);
		glBeginQueryARB(GL_SAMPLES_PASSED_ARB, query);
		# we'd want a different non-texture mode here, really...
		self.shape.Render( mode )
		glEndQueryARB(GL_SAMPLES_PASSED_ARB);
		glFlush()
		ready = False 
		print 'Waiting for completion of query (normal situation is 8 or 9 wait loop iterations)',
		while not ready:
			ready = glGetQueryObjectivARB(query,GL_QUERY_RESULT_AVAILABLE_ARB)
			if not ready:
				print '.',
		print
		print 'Fragments affected:', glGetQueryObjectuivARB(query, GL_QUERY_RESULT_ARB )
		glDeleteQueriesARB( [query] )

		glColorMask(GL_TRUE, GL_TRUE, GL_TRUE, GL_TRUE);
		glDepthMask(GL_TRUE);
		self.shape.Render( mode )
		
	def OnInit( self ):
		"""Scene set up and initial processing"""
		haveExtension = self.extensions.initExtension( "GL.ARB.occlusion_query")
		if not haveExtension:
			print 'GL_ARB_occlusion_query not supported!'
			sys.exit(1)
		print """When the box is offscreen number of pixels should drop to 0
"""
		print 'press i to choose another texture for the box'
		self.addEventHandler(
			'keypress', name = 'i', function = self.OnImageSwitch
		)
		print 'press s to choose another size for the box'
		self.addEventHandler(
			'keypress', name = 's', function = self.OnSizeSwitch
		)
		self.shape = shape.Shape(
			geometry = box.Box( size=sizes[0] ),
			appearance = appearance.Appearance(
				material =material.Material(
					diffuseColor =(1,1,1)
				),
				texture = imagetexture.ImageTexture(
					url = [images[0]]
				),
			),
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

