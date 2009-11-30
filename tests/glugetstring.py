#! /usr/bin/env python
"""Retrieve OpenGL Light state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GLU import *

class TestContext( BaseContext ):
    def OnInit( self ):
        print 'version', gluGetString( GLU_VERSION )
        print 'extensions', gluGetString( GLU_EXTENSIONS )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
