#! /usr/bin/env python
'''Solid Models (slightly more complex geometry)

Based on:
	OpenGL Tutorial #5.

	Project Name: Jeff Molofee's OpenGL Tutorial

	Project Description: Solid Models.

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

class TestContext( BaseContext ):
	"""There are no new customizations here.  The context
	class defines two new methods drawPyramid and drawCube
	which respectively draw a pyramid and a cube.
	"""
	initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
	def Render( self, mode = 0):
		"""Draw scene geometry"""
		BaseContext.Render( self, mode )
		glDisable( GL_LIGHTING) # context lights by default
		glTranslatef(-1.5,0.0,-6.0);
		glRotated( time.time()%(3.0)/3 * 360, 0,1,0)
		self.drawPyramid()

		glLoadIdentity()
		glTranslatef(1.5,0.0,-6.0);
		glRotated( time.time()%(1.0)/1 * -360, 1,0,0)
		self.drawCube()
	def OnIdle( self, ):
		"""Request refresh of the context whenever idle"""
		self.triggerRedraw(1)
		return 1
	
	def drawPyramid( self ):
		"""Draw a multicolored pyramid"""
		glBegin(GL_TRIANGLES);
		glColor3f(1.0,0.0,0.0)
		glVertex3f( 0.0, 1.0, 0.0)
		glColor3f(0.0,1.0,0.0)
		glVertex3f(-1.0,-1.0, 1.0)
		glColor3f(0.0,0.0,1.0)
		glVertex3f( 1.0,-1.0, 1.0)
		glColor3f(1.0,0.0,0.0)
		glVertex3f( 0.0, 1.0, 0.0)
		glColor3f(0.0,0.0,1.0)
		glVertex3f( 1.0,-1.0, 1.0);
		glColor3f(0.0,1.0,0.0);
		glVertex3f( 1.0,-1.0, -1.0);
		glColor3f(1.0,0.0,0.0);
		glVertex3f( 0.0, 1.0, 0.0);
		glColor3f(0.0,1.0,0.0);
		glVertex3f( 1.0,-1.0, -1.0);
		glColor3f(0.0,0.0,1.0);
		glVertex3f(-1.0,-1.0, -1.0);
		glColor3f(1.0,0.0,0.0);
		glVertex3f( 0.0, 1.0, 0.0);
		glColor3f(0.0,0.0,1.0);
		glVertex3f(-1.0,-1.0,-1.0);
		glColor3f(0.0,1.0,0.0);
		glVertex3f(-1.0,-1.0, 1.0);
		glEnd()
	def drawCube( self ):
		"""Draw a multicolored cube"""
		glBegin(GL_QUADS);
		glColor3f(0.0,1.0,0.0)
		glVertex3f( 1.0, 1.0,-1.0)
		glVertex3f(-1.0, 1.0,-1.0)
		glVertex3f(-1.0, 1.0, 1.0)
		glVertex3f( 1.0, 1.0, 1.0)
		glColor3f(1.0,0.5,0.0)
		glVertex3f( 1.0,-1.0, 1.0)
		glVertex3f(-1.0,-1.0, 1.0)
		glVertex3f(-1.0,-1.0,-1.0)
		glVertex3f( 1.0,-1.0,-1.0)
		glColor3f(1.0,0.0,0.0)
		glVertex3f( 1.0, 1.0, 1.0)
		glVertex3f(-1.0, 1.0, 1.0)
		glVertex3f(-1.0,-1.0, 1.0)
		glVertex3f( 1.0,-1.0, 1.0)
		glColor3f(1.0,1.0,0.0)
		glVertex3f( 1.0,-1.0,-1.0)
		glVertex3f(-1.0,-1.0,-1.0)
		glVertex3f(-1.0, 1.0,-1.0)
		glVertex3f( 1.0, 1.0,-1.0)
		glColor3f(0.0,0.0,1.0)
		glVertex3f(-1.0, 1.0, 1.0)
		glVertex3f(-1.0, 1.0,-1.0)
		glVertex3f(-1.0,-1.0,-1.0)
		glVertex3f(-1.0,-1.0, 1.0)
		glColor3f(1.0,0.0,1.0)
		glVertex3f( 1.0, 1.0,-1.0)
		glVertex3f( 1.0, 1.0, 1.0)
		glVertex3f( 1.0,-1.0, 1.0)
		glVertex3f( 1.0,-1.0,-1.0)
		glEnd()
	

if __name__ == "__main__":
	MainFunction ( TestContext)

