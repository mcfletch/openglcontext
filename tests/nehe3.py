#! /usr/bin/env python
'''Flat and Smooth Colors on simple geometry

Based on:
	OpenGL Tutorial #3.

	Project Name: Jeff Molofee's OpenGL Tutorial

	Project Description: Flat and Smooth Colors

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
	See nehe2.py for discussion.
	"""
	initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
	def Render( self, mode = 0):
		"""Renders the geometry for the scene.
		Unlike the nehe tutorial, we need to explicitly disable
		lighting, as the context automatically enables lighting
		to avoid a common class of new user errors where unlit
		geometry does not appear due to lack of light.
		"""
		BaseContext.Render( self, mode )
		glDisable( GL_CULL_FACE)
		## The context lights geometry by default, this turns off lighting
		## Without this call, you would not see the colors of the geometry
		glDisable( GL_LIGHTING)
		
		glTranslatef(-1.5,0.0,-6.0);
		glBegin(GL_TRIANGLES)
		glColor3f(1,0,0)
		glVertex3f( 0.0,  1.0, 0.0)
		glColor3f(0,1,0)
		glVertex3f(-1.0, -1.0, 0.0)
		glColor3f(0,0,1)
		glVertex3f( 1.0, -1.0, 0.0)
		glEnd()

		glTranslatef(3.0,0.0,0.0);

		glColor3f(0.5,0.5,1.0)
		glBegin(GL_QUADS)
		glVertex3f(-1.0,-1.0, 0.0)
		glVertex3f( 1.0,-1.0, 0.0)
		glVertex3f( 1.0, 1.0, 0.0)
		glVertex3f(-1.0, 1.0, 0.0)
		glEnd()
	
if __name__ == "__main__":
	MainFunction ( TestContext)

