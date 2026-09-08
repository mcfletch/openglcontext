#! /usr/bin/env python
"""Retrieve OpenGL Light state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GLU import *

class TestContext( BaseContext ):
    # GLU is a compatibility-profile library: it answers GLU_EXTENSIONS by
    # asking GL for GL_EXTENSIONS, which a core profile does not have, so the
    # query leaves GL_INVALID_ENUM behind for whatever calls next.
    profile = 'compatibility'
    def OnInit( self ):
        print('version', gluGetString( GLU_VERSION ))
        print('extensions', gluGetString( GLU_EXTENSIONS ))

if __name__ == "__main__":
    TestContext.ContextMainLoop()
