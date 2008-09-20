#! /usr/bin/env python
'''Blending modes in OpenGL

Based on:
	OpenGL Tutorial #8.

	Project Name: OpenGL Tutorial By Tom Stanis

	Project Description: Blending In OpenGL

	Authors Name: Tom Stanis / Jeff Molofee (aka NeHe)

	Authors Web Site: www.hypercosm.com (Tom's)
					  nehe.gamedev.net (NeHe's)

	COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee / Tom Stanis

		If you plan to put this program on your web page or a cdrom of
		any sort, let me know via email, I'm curious to see where
		it ends up :)

			If you use the code for your own projects please give us credit,
			or mention our web sites somewhere in your program or it's docs.

	* Modified by NeHe Feb 2000

'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext import interactivecontext, drawcube
from OpenGL.GL import *
from OpenGL.GLU import *
import time
from Image import open

class TestContext( BaseContext ):
	"""New customization point: Background

	Background, like Lights is called by the default
	RenderMode.SetupBindables method. It is used here
	because the blending mode used by the tutorial
	will not work unless the background is black.
	"""
	usage ="""Demonstrates blending functions:
	press 'b' to toggle blending functions
	press 'f' to toggle filter functions
	press 'l' to toggle lighting
	press '<pageup>' to speed up rotation
	press '<pagedown>' to slow down rotation
	"""
	initialPosition = (0,0,2)
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		self.imageIDs = self.loadImages()
		self.currentFilter = 0 # index into imageIDs
		self.lightsOn = 0 # boolean
		self.blendOn = 1
		self.currentZOffset = -6
		self.rotationCycle = 8.0
		# note that these are different bindings from the tutorial,
		# as you can wander around with the arrow keys already...
		self.addEventHandler(
			'keypress', name = 'f', function = self.OnFilter
		)
		self.addEventHandler(
			'keypress', name = 'l', function = self.OnLightToggle
		)
		self.addEventHandler(
			'keyboard', name = '<pageup>', function = self.OnSpeedUp,
			state=0,
		)
		self.addEventHandler(
			'keyboard', name = '<pagedown>', function = self.OnSlowDown,
			state=0,
		)
		self.addEventHandler(
			'keypress', name = 'b', function = self.OnBlendToggle
		)
		print self.usage
		glLightfv( GL_LIGHT1, GL_AMBIENT, (0.2, .2, .2, 1.0) );
		glLightfv(GL_LIGHT1, GL_DIFFUSE, (.8,.8,.8));
		glLightfv(GL_LIGHT1, GL_POSITION, (-2,0,3,1) );
		

	def Lights (self, mode = 0):
		'''Setup the global lights for your scene'''
		if self.lightsOn:
			glEnable( GL_LIGHTING )
			glEnable(GL_LIGHT1);
			glDisable(GL_LIGHT0);
		else:
			glDisable( GL_LIGHTING )
			glDisable(GL_LIGHT1);
			glDisable(GL_LIGHT0);
	def Background( self, mode = 0):
		"""Demo's use of GL_ONE assumes that background is black"""
		if mode.passCount == 0:
			glClearColor(0,0,0,0)
			glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )

	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		glTranslatef(1.5,0.0,self.currentZOffset);
		glDisable( GL_CULL_FACE )
		glRotated( time.time()%(self.rotationCycle)/self.rotationCycle * -360, 1,0,0)
		self.blend()
		
		glEnable(GL_TEXTURE_2D)
		# re-select our texture, could use other generated textures
		# if we had generated them earlier...
		glBindTexture(GL_TEXTURE_2D, self.imageIDs[self.currentFilter])   # 2d texture (x and y size)
		self.drawCube()
		glDisable(GL_TEXTURE_2D)

	BLENDSTYLES = [
		(),
		(GL_SRC_ALPHA, GL_ONE), # what the demo uses originally
		(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA), # this is what should be used with sorted triangles
		(GL_SRC_ALPHA, GL_DST_ALPHA), # just for kicks...
	]
	def blend( self ):
		"""Choose and enable blending mode"""
		if self.blendOn == 0:
			glDisable(GL_BLEND);
			glEnable(GL_DEPTH_TEST);
			glDepthMask( ~0 )
		else:
			glEnable(GL_BLEND);
			glDisable(GL_DEPTH_TEST);
			glBlendFunc( * self.BLENDSTYLES[ self.blendOn] )
			glDepthMask( 0 ) # prevent updates to the depth buffer...
		
	def loadImages( self, imageName = "nehe_glass.bmp" ):
		"""Load an image from a file using PIL,
		produces 3 textures to demo filter types
		"""
		im = open(imageName)
		try:
			ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
		except SystemError:
			ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
		IDs = []
		# a Nearest-filtered texture...
		ID = glGenTextures(1)
		IDs.append( ID )
		glBindTexture(GL_TEXTURE_2D, ID)
		glPixelStorei(GL_UNPACK_ALIGNMENT,1)
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
		glTexImage2D(GL_TEXTURE_2D, 0, 3, ix, iy, 0, GL_RGBA, GL_UNSIGNED_BYTE, image)
		# linear-filtered
		ID = glGenTextures(1)
		IDs.append( ID )
		glBindTexture(GL_TEXTURE_2D, ID)
		glPixelStorei(GL_UNPACK_ALIGNMENT,1)
		glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
		glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR)
		glTexImage2D(GL_TEXTURE_2D, 0, 3, ix, iy, 0, GL_RGBA, GL_UNSIGNED_BYTE, image)
		# linear + mip-mapping
		ID = glGenTextures(1)
		IDs.append( ID )
		glBindTexture(GL_TEXTURE_2D, ID)
		glPixelStorei(GL_UNPACK_ALIGNMENT,1)
		glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MAG_FILTER,GL_LINEAR)
		glTexParameteri(GL_TEXTURE_2D,GL_TEXTURE_MIN_FILTER,GL_LINEAR_MIPMAP_NEAREST)
		gluBuild2DMipmaps(GL_TEXTURE_2D, 3, ix, iy, GL_RGBA, GL_UNSIGNED_BYTE, image)
		
		return IDs

	def OnIdle( self, ):
		self.triggerRedraw(1)
		return 1
	def OnBlendToggle( self, event ):
		self.blendOn = self.blendOn + 1
		if self.blendOn == len( self.BLENDSTYLES ):
			self.blendOn = 0
		print 'Blend now %s, %s'% [
			("None", "None"),
			("GL_SRC_ALPHA", "GL_ONE"),
			("GL_SRC_ALPHA", "GL_ONE_MINUS_SRC_ALPHA"),
			("GL_SRC_ALPHA", "GL_DST_ALPHA"),
		][ self.blendOn ]
	def OnFilter( self, event):
		"""Handles the key event telling us to change the filter"""
		self.currentFilter = (self.currentFilter + 1 ) % 3
		print 'Drawing filter now %s'% ( ["Nearest","Linear","Linear Mip-Mapped"][ self.currentFilter])
	def OnLightToggle( self, event ):
		"""Handles the key event telling us to toggle the lighting"""
		self.lightsOn = not self.lightsOn
		print "Lights now %s"% (["off", "on"][self.lightsOn])
	def OnSpeedUp( self, event):
		"""Handles key event to speed up"""
		print 'speed up'
		self.rotationCycle = self.rotationCycle /2.0
	def OnSlowDown( self, event ):
		"""Handles key event to slowdown"""
		print 'slow down'
		self.rotationCycle = self.rotationCycle * 2.0

			
	def drawCube( self ):
		"Draw a cube with both normals and texture coordinates"
		glBegin(GL_QUADS);
		glNormal3f( 0.0, 0.0, 1.0)
		glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);

		glNormal3f( 0.0, 0.0,-1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);

		glNormal3f( 0.0, 1.0, 0.0)
		glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f(-1.0,  1.0,  1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f( 1.0,  1.0,  1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);

		glNormal3f( 0.0,-1.0, 0.0)
		glTexCoord2f(1.0, 1.0); glVertex3f(-1.0, -1.0, -1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f( 1.0, -1.0, -1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);

		glNormal3f( 1.0, 0.0, 0.0)
		glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);

		glNormal3f(-1.0, 0.0, 0.0)
		glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glEnd()
	

if __name__ == "__main__":
	MainFunction(TestContext)