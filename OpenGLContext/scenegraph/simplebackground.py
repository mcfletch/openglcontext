"""Solid-color background node"""
from vrml import field, node
from vrml.vrml97 import nodetypes

from OpenGL.GL import *
from OpenGLContext.arrays import *
from math import pi

class SimpleBackground(nodetypes.Background, nodetypes.Children, node.Node ):
    """Solid-color Background node

    This Background node provides the simplest rendering
    algorithm, merely clearing the color buffer to the node's
    "color" value.

    It also clears the depth buffer.

    Attributes of note within the Box object:

        color -- r,g,b giving the clear color
        bound -- whether or not this Background is active

    See:
        glClearColor, glClear
    """
    color = field.newField( 'color', 'SFColor', 1, [0.0, 0.0, 0.0])
    bound = field.newField( 'bound', 'SFBool', 1, 0)
    def Render (self, mode = None, clear=True):
        # should only do this on visible passes...
        if mode.passCount == 0:
            if self.bound and clear:
                r,g,b = self.color
                glClearColor( r,g,b, 1.0 )
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)