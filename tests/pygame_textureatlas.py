#! /usr/bin/env python
'''Test of texture atlas behaviour...'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGL.GL import *
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import _fontstyles
import sys, math
from OpenGLContext.scenegraph.text import pygamefont, fontprovider
from OpenGLContext.arrays import zeros, array
from OpenGLContext import texturecache,texture
from OpenGLContext import atlas as atlasmodule
	
class TestContext( BaseContext ):
	testText = 'Hello world'
	_rendered = False
	def OnInit( self ):
		"""Initialize the texture atlas test"""
		self.font = pygamefont.PyGameBitmapFont()
		self.tc = texturecache.TextureCache( atlasSize=256)
		self.maps = {}
		self.box = Box( size=(.5,.5,.5))
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST )
		glTexParameteri( GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST )
		self.shape = Shape(
			geometry = Box( ),
			appearance = Appearance(
			),
		)
	def Render( self, mode=None ):
		if not self._rendered and mode.visible:
			for char in self.testText:
				if not self.maps.has_key( char ):
					dataArray, metrics = self.font.createCharTexture(
						char, mode=mode 
					)
					dataArray = array( dataArray[:,:,1] )
					dataArray.shape = dataArray.shape + (1,)
					map = self.tc.getTexture( dataArray, texture.Texture )
					self.maps[char] = map
			self._rendered = True
			atlas = self.maps.values()[0].atlas
			atlas.render()
			img = ImageTexture.forTexture( 
				atlas.texture, mode=mode 
			)
			self.shape.appearance.texture = img
		self.shape.Render( mode = mode )
		
	def setupFontProviders( self ):
		"""Load font providers for the context

		See the OpenGLContext.scenegraph.text package for the
		available font providers.
		"""
		fontprovider.setTTFRegistry(
			self.getTTFFiles(),
		)
if __name__ == "__main__":
	MainFunction ( TestContext )


