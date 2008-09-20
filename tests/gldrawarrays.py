#! /usr/bin/env python
'''Test of the glDrawArrays function (draws flower)'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string
from OpenGLContext.tests import flower_geometry

class TestContext( BaseContext):
	def OnInit( self ):
		"""Initialisation"""
		print """Should see flower pattern in gray over white background"""
	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		glVertexPointerd(flower_geometry.points_expanded )
		glNormalPointerf(flower_geometry.normals_expanded )
		glEnableClientState(GL_VERTEX_ARRAY);
		glEnableClientState(GL_NORMAL_ARRAY);
		glDrawArrays(GL_TRIANGLES, 0, len(flower_geometry.points_expanded))

if __name__ == "__main__":
	MainFunction ( TestContext)
