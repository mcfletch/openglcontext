#! /usr/bin/env python
'''Test of texture atlas behaviour...'''
from OpenGL.GL import *
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import _fontstyles
import sys, math
from OpenGLContext.scenegraph.text import pygamefont, fontprovider
from OpenGLContext.arrays import zeros, array
from OpenGLContext import atlas as atlasmodule
	
class TestContext( BaseContext ):
	def OnInit( self ):
		"""Initialize the texture atlas test"""
		
	def setupFontProviders( self ):
		"""Load font providers for the context

		See the OpenGLContext.scenegraph.text package for the
		available font providers.
		"""
		fontprovider.setTTFRegistry(
			self.getTTFFiles(),
		)
	testingClass = pygamefont.PyGameBitmapFont
if __name__ == "__main__":
	MainFunction ( TestContext )


