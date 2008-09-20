#! /usr/bin/env python
'''DEK's Texturesurf demo without the texture, tests glEvalMesh2'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.arrays import array
import string, time

## Control points for the bezier surface
ctrlpoints = array([
	[[-1.5, -1.5, 4.0] ,
	 [-0.5, -1.5, 2.0] ,
	 [0.5, -1.5, -1.0] ,
	 [1.5, -1.5, 2.0]] ,
	[[-1.5, -0.5, 1.0] ,
	 [-0.5, -0.5, 3.0] ,
	 [0.5, -0.5, 0.0] ,
	 [1.5, -0.5, -1.0]] ,
	[[-1.5, 0.5, 4.0] ,
	 [-0.5, 0.5, 0.0] ,
	 [0.5, 0.5, 3.0] ,
	 [1.5, 0.5, 4.0]] ,
	[[-1.5, 1.5, -2.0] ,
	 [-0.5, 1.5, -2.0] ,
	 [0.5, 1.5, 0.0] ,
	 [1.5, 1.5, -1.0]] ,
], 'f' )

## Texture control points
texpts = array([
	[[0.0, 0.0],
	 [0.0, 1.0]],
	[[1.0, 0.0],
	 [1.0, 1.0]],
], 'f')


class TestContext( BaseContext ):
	def Render( self, mode= 0 ):
		BaseContext.Render( self, mode )
		glEnable(GL_DEPTH_TEST)
		glEnable( GL_LIGHT0 )
		glLight( GL_LIGHT0, GL_SPOT_DIRECTION, (-10,0,-10))
		glLight( GL_LIGHT0, GL_SPOT_CUTOFF, 1.57 )
		glLight( GL_LIGHT0, GL_DIFFUSE, (0,0,1))
		glLight( GL_LIGHT0, GL_POSITION, (10,0,10))
		
		glCallList( self.surfaceID )
		
	def buildDisplayList( self):
		glDisable(GL_CULL_FACE)
		glEnable(GL_NORMALIZE)
		glEnable(GL_MAP2_VERTEX_3)
		glEnable(GL_MAP2_NORMAL)
		glMap2f(GL_MAP2_VERTEX_3, 0., 1., 0., 1., ctrlpoints)
		glMap2f(GL_MAP2_NORMAL, 0., 1., 0., 1., ctrlpoints)
		glMapGrid2f(20, 0.0, 1.0, 20, 0.0, 1.0)
		displayList = glGenLists(1)
		glNewList( displayList, GL_COMPILE)
		glColor3f( 1.0,0,0)
		glEvalMesh2(GL_FILL, 0, 20, 0, 20)
		glEndList()
		return displayList
	def OnInit( self ):
		"""Initialise"""
		print """Should see curvy surface with no texture"""
		self.surfaceID = self.buildDisplayList()
		
	

if __name__ == "__main__":
	MainFunction ( TestContext)
