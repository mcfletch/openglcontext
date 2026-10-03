#! /usr/bin/env python
"""Retrieve OpenGL polygon stipple state values and print to console"""
from OpenGLContext.context import Context as BaseContext
#from arraystuff import *
from OpenGL.GL import *


class TestContext( BaseContext ):
    profile = 'compatibility'   # reads fixed-function polygon stipple
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        print('glGetPolygonStipple',  glGetPolygonStippleub())
        print('as string...')
        print(repr(glGetPolygonStipple()))

if __name__ == "__main__":
    TestContext.ContextMainLoop()
