#! /usr/bin/env python
'''Low-level GLUT bitmap fonts test'''
# GLUT bitmap fonts require a GLUT context; force it before _bitmap_font
# (shared with the wgl/pygame variants) resolves the default backend on import.
from OpenGLContext import testingcontext
testingcontext.CONFIGURED_BASE = testingcontext.getInteractive( 'glut' )
import _bitmap_font, _fontstyles
from OpenGLContext.scenegraph.text import glutfont

class TestContext( _bitmap_font.TestContext ):
    testingClass = glutfont.GLUTBitmapFont
if __name__ == "__main__":
    TestContext.ContextMainLoop()