#! /usr/bin/env python
'''Test of the glDrawElements function (draws flower)'''

from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import array
import string
from OpenGLContext.tests import flower_geometry

class TestContext( BaseContext ):
	def OnInit( self ):
		"""Initialisation"""
		print """Should see flower pattern in gray over white background"""
	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		glVertexPointerd( flower_geometry.points )
		glEnableClientState(GL_VERTEX_ARRAY);
		glDrawElementsui(
			GL_TRIANGLES,
			flower_geometry.indices
		)


if __name__ == "__main__":
	MainFunction ( TestContext)
