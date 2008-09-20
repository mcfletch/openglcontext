#! /usr/bin/env python
'''Draw simple, unlit geometry

Based on:
	OpenGL Tutorial #2.

	Project Name: Jeff Molofee's OpenGL Tutorial

	Project Description: Creating Your First Polygon & Quad

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

class TestContext( BaseContext ):
	"""This context customizes two points in the BaseContext.

	The first point is the initialPosition attribute.  By
	default, the OpenGLContext contexts position your
	eye/camera at (0,0,10), which makes it easy to see most
	meter-sized geometry located at the origin.  Since the
	tutorial manually repositions the geometry to be in a
	good viewing position under the assumption that the eye
	is at (0,0,0), we need to make that assumption valid.

	The second point is the Render method.  This method is
	called by most RenderMode subclasses to provide the
	scene graph rendering.  (The exception being the
	transparent objects RenderMode.)  The mode parameter
	will be a constant from the OpenGLContext.constants
	module (or potentially another integer if a user-generated
	rendering mode is being used).

	Note: the results of this Demo will be different than the
	tutorial code because the OpenGLContext is automatically
	enabling lighting.
	"""
	initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
	def Render( self, mode = 0):
		"""Render the geometry for the scene."""
		## Triggers the default operations, which allows for, for example, transparent rendering
		BaseContext.Render( self, mode )
		## Moves the drawing origin 6 units into the screen and 1.5 units to the left
		glDisable( GL_CULL_FACE )
		glTranslatef(-1.5,0.0,-6.0);
		## Starts the geometry generation mode
		glBegin(GL_TRIANGLES)
		glVertex3f( 0.0,  1.0, 0.0)
		glVertex3f(-1.0, -1.0, 0.0)
		glVertex3f( 1.0, -1.0, 0.0)
		glEnd()
		
		## Moves the drawing origin again, cumulative change is now (1.5,0.0,6.0)
		glTranslatef(3.0,0.0,0.0);

		## Starts a different geometry generation mode
		glBegin(GL_QUADS)
		glVertex3f(-1.0,-1.0, 0.0)
		glVertex3f( 1.0,-1.0, 0.0)
		glVertex3f( 1.0, 1.0, 0.0)
		glVertex3f(-1.0, 1.0, 0.0)
		glEnd();

if __name__ == "__main__":
	MainFunction ( TestContext)

