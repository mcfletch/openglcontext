#! /usr/bin/env python
'''NeHe lesson 6 using OpenGLContext Timer class

This customization of the original rotating cube demo
uses the Timer class to provide a flexible timing
mechanism for the animation.

In particular, the demo allows you to modify the
"multiplier" value of the internal time frame of
reference compared to real world time.  This allows
for speeding, slowing and reversing the state of
rotation.

As an added bonus, it also uses the texture module
to load the PIL image into a texture for rendering.

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
from OpenGLContext.arrays import array
import string
from OpenGLContext.events.timer import Timer
from OpenGLContext import texture

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
	drawPollTimeout = 0.01
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		self.image = self.loadImage ()
		print """You should see a slowly rotating textured cube

The animation is provided by a timer, rather than the
crude time-module based animation we use for the other
NeHe tutorials."""
		print '  <r> reverse the time-sequence'
		print '  <s> make time pass more slowly'
		print '  <f> make time pass faster'
		self.addEventHandler( "keypress", name="r", function = self.OnReverse)
		self.addEventHandler( "keypress", name="s", function = self.OnSlower)
		self.addEventHandler( "keypress", name="f", function = self.OnFaster)
		self.time = Timer( duration = 8.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
		self.rotation =  0
	### Timer callback
	def OnTimerFraction( self, event ):
##		print "timer fraction[%s] [%s]->%s"%(self.time.internal.multiplier, event.value(), event.fraction())
		self.rotation = event.fraction()* -360
	### Keyboard callbacks
	def OnReverse( self, event ):
		self.time.internal.multiplier = -self.time.internal.multiplier
		print "reverse",self.time.internal.multiplier
	def OnSlower( self, event ):
		self.time.internal.multiplier = self.time.internal.multiplier /2.0
		print "slower",self.time.internal.multiplier
	def OnFaster( self, event ):
		self.time.internal.multiplier = self.time.internal.multiplier * 2.0
		print "faster",self.time.internal.multiplier
		
		
	def Render( self, mode = 0):
		"""Render scene geometry"""
		BaseContext.Render( self, mode )
		glDisable( GL_LIGHTING) # context lights by default
		glTranslatef(1.5,0.0,-6.0);
		glRotated( self.rotation, 1,0,0)
		glRotated( self.rotation, 0,1,0)
		glRotated( self.rotation, 0,0,1)
		self.setupTexture()
		self.drawCube()
	def loadImage( self, imageName = "nehe_wall.bmp" ):
		"""Load an image file as a 2D texture using PIL
		"""
		from Image import open
		im = texture.Texture( open(imageName) )
		return im

	def setupTexture( self ):
		"""Render-time texture environment setup

		This method encapsulates the functions required to set up
		for textured rendering.  The original tutorial made these
		calls once for the entire program.  This organization makes
		more sense if you are likely to have multiple textures.
		"""
		# texture-mode setup, was global in original
		glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
		glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
		glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
		self.image()
			
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
		
	

if __name__ == "__main__":
	MainFunction ( TestContext)

