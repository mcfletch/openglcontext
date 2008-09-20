#! /usr/bin/env python
'''Texture Filters, Basic Lighting & Keyboard Control

Note: keys are different from tutorial, arrows move, pageup/pagedown control
speed of rotation

Based on:
	OpenGL Tutorial #7.

	Project Name: Jeff Molofee's OpenGL Tutorial

	Project Description: Texture Filters, Basic Lighting & Keyboard Control

	Authors Name: Jeff Molofee (aka NeHe)

	Authors Web Site: nehe.gamedev.net

	COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee

		If you plan to put this program on your web page or a cdrom of
		any sort, let me know via email, I'm curious to see where
		it ends up :)

			If you use the code for your own projects please give me credit,
			or mention my web site somewhere in your program or it's docs.
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
import time
from Image import open
from OpenGL.GLU import *

class TestContext( BaseContext ):
	"""New customization point: Lights, New feature: keyboard event handlers

	Context.Lights is called by the default rendering passes
	if there is no scenegraph present.

	Uses the addEventHandler method for registering new event handlers
	for given keyboard and mouse events.
	"""
	
	usage ="""Demonstrates filter functions:
	press 'f' to toggle filter functions
	press 'l' to toggle lighting
	press '<pageup>' to speed up rotation
	press '<pagedown>' to slow down rotation
"""
	initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		self.imageIDs = self.loadImages()
		self.currentFilter = 0 # index into imageIDs
		self.lightsOn = 1 # boolean
		self.currentZOffset = -6
		self.rotationCycle = 8.0
		
		## Adds event handlers for the given keys
		# Note that these are different bindings from the tutorial,
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
		print self.usage
		glLightfv( GL_LIGHT1, GL_AMBIENT, (0.2, .2, .2, 1.0) );
		glLightfv(GL_LIGHT1, GL_DIFFUSE, (.8,.8,.8));
		glLightfv(GL_LIGHT1, GL_POSITION, (-2,0,3,1) );

	def loadImages( self, imageName = "nehe_crate.bmp" ):
		"""Load an image from a file using PIL,
		produces 3 textures to demo filter types.

		Converts the paletted image to RGB format.
		"""
		im = open(imageName)
		try:
			## Note the conversion to RGB the crate bitmap is paletted!
			im = im.convert( 'RGB')
			ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
		except SystemError:
			ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
		assert ix*iy*4 == len(image), """Image size != expected array size"""
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
		print 'doing mip-maps, fails on RedHat Linux'
		gluBuild2DMipmaps(
			GL_TEXTURE_2D, 
			GL_RGBA, ix, iy, GL_RGBA, GL_UNSIGNED_BYTE, image
		)
		print 'finished mip-mapped'
		return IDs

	def Lights (self, mode = 0):
		''' Setup the global lights for your scene, called by context before rendering'''
		if self.lightsOn:
			glEnable( GL_LIGHTING )
			glEnable(GL_LIGHT1);
			glDisable(GL_LIGHT0);
		else:
			glDisable( GL_LIGHTING )
			glDisable(GL_LIGHT1);
			glDisable(GL_LIGHT0);
	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		glTranslatef(1.5,0.0,self.currentZOffset);
		glEnable(GL_TEXTURE_2D)
		# re-select our texture, could use other generated textures
		# if we had generated them earlier...
		glBindTexture(GL_TEXTURE_2D, self.imageIDs[self.currentFilter])
		
		glRotated( time.time()%(self.rotationCycle)/self.rotationCycle * -360, 1,0,0)
		self.drawCube()

	### Callback-handlers
	def OnIdle( self, ):
		self.triggerRedraw(1)
		return 1
	
	def OnFilter( self, event):
		"""Handles the key event telling us to change the filter"""
		self.currentFilter = (self.currentFilter + 1 ) % 3
		print 'Drawing filter now %s'% (
			["Nearest","Linear","Linear Mip-Mapped"][ self.currentFilter]
		)
	def OnLightToggle( self, event ):
		"""Handles the key event telling us to toggle the lighting"""
		self.lightsOn = not self.lightsOn
		print "Lights now %s"% (["off", "on"][self.lightsOn])
	def OnSpeedUp( self, event):
		"""Handles key event to speed up"""
		self.rotationCycle = self.rotationCycle /2.0
	def OnSlowDown( self, event ):
		"""Handles key event to slowdown"""
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
	MainFunction ( TestContext)

