#! /usr/bin/env python
'''Rotating a polygon on one of it's axes.

Based on:
	OpenGL Tutorial #4.

	Project Name: Jeff Molofee's OpenGL Tutorial

	Project Description: Rotating a polygon on one of it's axes.

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

## The time module is used to provide crude animation support
import time

class TestContext( BaseContext ):
	"""This context customizes 3 points in the BaseContext.
	
	The third point (beyond the two covered in the previous lessons)
	is the addition of an OnIdle handler.  This method (if present)
	is called whenever the GUI library has completed all pending
	event processing and signals an "idle" state.  By calling
	self.triggerRedraw( force = 1 ), we force a redraw of the context
	to show the next "frame" of the animation.
	"""
	initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
	def Render( self, mode = 0):
		"""Render the scene geometry"""
		BaseContext.Render( self, mode )
		glDisable( GL_LIGHTING) # context lights by default
		glDisable( GL_CULL_FACE)
		glTranslatef(-1.5,0.0,-6.0);
		## The call to time.time creates a float value which is
		## converted to a fraction of three seconds then multiplied
		## by 360 (degrees) to get the current appropriate rotation
		## for an object spinning at 1/3 rps.
		glRotated( time.time()%(3.0)/3 * 360, 0,1,0)
		glBegin(GL_TRIANGLES)
		glColor3f(1,0,0)
		glVertex3f( 0.0,  1.0, 0.0)
		glColor3f(0,1,0)
		glVertex3f(-1.0, -1.0, 0.0)
		glColor3f(0,0,1)
		glVertex3f( 1.0, -1.0, 0.0)
		glEnd()

		glLoadIdentity()
		glTranslatef(1.5,0.0,-6.0);
		## As above, but 1 rps
		glRotated( time.time()%(1.0)/1 * -360, 1,0,0)

		glColor3f(0.5,0.5,1.0)
		glBegin(GL_QUADS)
		glVertex3f(-1.0, 1.0, 0.0)
		glVertex3f( 1.0, 1.0, 0.0)
		glVertex3f( 1.0,-1.0, 0.0)
		glVertex3f(-1.0,-1.0, 0.0)
		glEnd()
	def OnIdle( self, ):
		"""Request refresh of the context whenever idle"""
		self.triggerRedraw(1)
		return 1
	

if __name__ == "__main__":
	MainFunction ( TestContext)
