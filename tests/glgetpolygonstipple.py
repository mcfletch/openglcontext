#! /usr/bin/env python
"""Retrieve OpenGL polygon stipple state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import string

#from arraystuff import *
from OpenGL.GL import *


class TestContext( BaseContext ):
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        print 'glGetPolygonStipple',  glGetPolygonStippleub()
        print 'as string...'
        print  repr(glGetPolygonStipple())

if __name__ == "__main__":
    TestContext.ContextMainLoop()
