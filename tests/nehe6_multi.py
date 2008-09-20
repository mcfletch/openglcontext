#! /usr/bin/env python
'''Multi-texturing version of texturing demo

This customization of the original rotating cube demo
uses the Timer class to provide a flexible timing
mechanism for the animation.

In particular, the demo allows you to modify the
"multiplier" value of the internal time frame of
reference compared to real world time.  This allows
for speeding, slowing and reversing the state of
rotation.

Also uses the texture module instead of manually
converting PIL textures.

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
from OpenGLContext import texture
from OpenGL.GL import *
from OpenGLContext.arrays import array
import sys
from OpenGLContext.events.timer import Timer

multitexture = None

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
	rotation =  0

	def OnInit( self ):
		"""Do all of our setup functions..."""
		global multitexture
		multitexture = self.extensions.initExtension( "GL.ARB.multitexture")
		if not multitexture:
			print 'GL_ARB_multitexture not supported!'
			sys.exit(1)

		self.addEventHandler( "keypress", name="r", function = self.OnReverse)
		self.addEventHandler( "keypress", name="s", function = self.OnSlower)
		self.addEventHandler( "keypress", name="f", function = self.OnFaster)
		self.time = Timer( duration = 8.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()

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
	def Load( self ):
		self.image = self.loadImage ("nehe_wall.bmp")
		self.lightmap = self.loadLightMap( "lightmap1.jpg" )
		
	def Render( self, mode = 0):
		"""Render scene geometry"""
		BaseContext.Render( self, mode )
		if not getattr( self, 'image', None ):
			self.Load()
		if mode.visible:
			glDisable( GL_LIGHTING) # context lights by default
			glTranslatef(1.5,0.0,-6.0);
			glRotated( self.rotation, 1,0,0)
			glRotated( self.rotation, 0,1,0)
			glRotated( self.rotation, 0,0,1)
			
			multitexture.glActiveTextureARB(multitexture.GL_TEXTURE0_ARB); 
			glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
			glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
			glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_DECAL)
			self.image()
			multitexture.glActiveTextureARB(multitexture.GL_TEXTURE1_ARB);
			glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
			glTexParameterf(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
			glTexEnvf(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_MODULATE)
			self.lightmap()
			self.drawCube()

	def loadImage( self, imageName = "nehe_wall.bmp" ):
		"""Load an image from a file using PIL.
		"""
		from Image import open
		multitexture.glActiveTextureARB(multitexture.GL_TEXTURE0_ARB);
		return texture.Texture( open(imageName) )
	def loadLightMap( self, imageName = "lightmap1.jpg" ):
		"""Load an image from a file using PIL as a lightmap (greyscale)
		"""
		from Image import open
		multitexture.glActiveTextureARB(multitexture.GL_TEXTURE1_ARB); 
		return texture.Texture( open(imageName) )
		
	def drawCube( self ):
		"""Draw a cube with texture coordinates"""
		glBegin(GL_QUADS);
		mTexture(0.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
		mTexture(1.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
		mTexture(1.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
		mTexture(0.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);

		mTexture(1.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
		mTexture(1.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		mTexture(0.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
		mTexture(0.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);

		mTexture(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		mTexture(0.0, 0.0); glVertex3f(-1.0,  1.0,  1.0);
		mTexture(1.0, 0.0); glVertex3f( 1.0,  1.0,  1.0);
		mTexture(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);

		mTexture(1.0, 1.0); glVertex3f(-1.0, -1.0, -1.0);
		mTexture(0.0, 1.0); glVertex3f( 1.0, -1.0, -1.0);
		mTexture(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);
		mTexture(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);

		mTexture(1.0, 0.0); glVertex3f( 1.0, -1.0, -1.0);
		mTexture(1.0, 1.0); glVertex3f( 1.0,  1.0, -1.0);
		mTexture(0.0, 1.0); glVertex3f( 1.0,  1.0,  1.0);
		mTexture(0.0, 0.0); glVertex3f( 1.0, -1.0,  1.0);

		mTexture(0.0, 0.0); glVertex3f(-1.0, -1.0, -1.0);
		mTexture(1.0, 0.0); glVertex3f(-1.0, -1.0,  1.0);
		mTexture(1.0, 1.0); glVertex3f(-1.0,  1.0,  1.0);
		mTexture(0.0, 1.0); glVertex3f(-1.0,  1.0, -1.0);
		glEnd()
		
	def OnIdle( self, ):
		"""Request refresh of the context whenever idle"""
		self.triggerRedraw(1)
		return 1
		
def mTexture( a,b ):
	multitexture.glMultiTexCoord2fARB(multitexture.GL_TEXTURE0_ARB, a,b)
	multitexture.glMultiTexCoord2fARB(multitexture.GL_TEXTURE1_ARB, a,b) 


if __name__ == "__main__":
	MainFunction ( TestContext)

