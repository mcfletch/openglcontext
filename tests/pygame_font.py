#! /usr/bin/env python
'''Low-level Pygame bitmap fonts test'''
import _bitmap_font, _fontstyles
from OpenGLContext.scenegraph.text import pygamefont, fontprovider

class TestContext( _bitmap_font.TestContext ):
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
    TestContext.ContextMainLoop()

