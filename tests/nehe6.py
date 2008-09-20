#! /usr/bin/env python
'''Texture Mapping geometry

Based on:
	OpenGL Tutorial #6.

	Project Name: Jeff Molofee's OpenGL Tutorial

	Project Description: Texture Mapping.

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

class TestContext( BaseContext ):
	"""There is one new customization point used here: OnInit

	OnInit is called by the Context class after initialization
	of the context has completed, and before any rendering is
	attempted.  Within this method, you'll generally perform
	your global setup tasks.

	We also see the use of the python imaging library for
	loading images, something which is obviously not seen
	in the original tutorial.

	Finally, this interpretation reorganizes the code to resemble
	more idiomatic python than the original code.
	"""
	initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		self.imageID = self.loadImage ()
		
	def loadImage( self, imageName = "nehe_wall.bmp" ):
		"""Load an image file as a 2D texture using PIL

		This method combines all of the functionality required to
		load the image with PIL, convert it to a format compatible
		with PyOpenGL, generate the texture ID, and store the image
		data under that texture ID.

		Note: only the ID is returned, no reference to the image object
		or the string data is stored in user space, the data is only
		present within the OpenGL engine after this call exits.
		"""
		im = open(imageName)
		try:
			ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBA", 0, -1)
		except SystemError:
			ix, iy, image = im.size[0], im.size[1], im.tostring("raw", "RGBX", 0, -1)
		# generate a texture ID
		ID = glGenTextures(1)
		# make it current
		glBindTexture(GL_TEXTURE_2D, ID)
		glPixelStorei(GL_UNPACK_ALIGNMENT,1)
		# copy the texture into the current texture ID
		glTexImage2D(GL_TEXTURE_2D, 0, 3, ix, iy, 0, GL_RGBA, GL_UNSIGNED_BYTE, image)
		# return the ID for use
		return ID

	def Render( self, mode = 0):
		"""Render scene geometry"""
		BaseContext.Render( self, mode )
		glDisable( GL_LIGHTING) # context lights by default
		glTranslatef(1.5,0.0,-6.0);
		glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
		self.setupTexture()
		self.drawCube()
	def setupTexture( self ):
		"""Render-time texture environment setup

		This method encapsulates the functions required to set up
		for textured rendering.  The original tutorial made these
		calls once for the entire program.  This organization makes
		more sense if you are likely to have multiple textures.
		"""
		# texture-mode setup, was global in original
		glEnable(GL_TEXTURE_2D)
		glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
		glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
		glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
		# re-select our texture, could use other generated textures
		# if we had generated them earlier...
		glBindTexture(GL_TEXTURE_2D, self.imageID)   # 2d texture (x and y size)
			
	def drawCube( self ):
		"""Draw a cube with texture coordinates"""
		glBegin(GL_QUADS);
		glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);

		glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);

		glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f(-1.0,  1.0,  1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f( 1.0,  1.0,  1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);

		glTexCoord2f(1.0, 1.0); glVertex3f(-1.0, -1.0, -1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f( 1.0, -1.0, -1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);

		glTexCoord2f(1.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
		glTexCoord2f(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);

		glTexCoord2f(0.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
		glTexCoord2f(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
		glTexCoord2f(1.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);
		glTexCoord2f(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glEnd()
		
	def OnIdle( self, ):
		"""Request refresh of the context whenever idle"""
		self.triggerRedraw(1)
		return 1
		
	

if __name__ == "__main__":
	MainFunction ( TestContext)

