#! /usr/bin/env python
'''Low-level GLUT bitmap fonts test'''
import _bitmap_font, _fontstyles
from OpenGLContext.scenegraph.text import glutfont

class TestContext( _bitmap_font.TestContext ):
    testingClass = glutfont.GLUTBitmapFont
if __name__ == "__main__":
    TestContext.ContextMainLoop()