"""Solid-color background node"""
from typing import Any

from vrml import field, node
from vrml.vrml97 import nodetypes
from vrml.x3d import binding

from OpenGL.GL import *
from OpenGLContext.arrays import *
from math import pi

class SimpleBackground(binding.Bindable, nodetypes.Background, nodetypes.Children, node.Node ):
    """Solid-color Background node

    This Background node provides the simplest rendering
    algorithm, merely clearing the color buffer to the node's
    "color" value.

    It also clears the depth buffer.

    Attributes of note within the Box object:

        color -- r,g,b giving the clear color
        set_bind, isBound, bindTime -- X3D's binding (:mod:`vrml.x3d.binding`):
            the background on top of its scene's stack is the one drawn

    See:
        glClearColor, glClear
    """
    color = field.newField( 'color', 'SFColor', 1, [0.0, 0.0, 0.0])
    def Render (self, mode: Any = None, clear: bool = True) -> None:
        # should only do this on visible passes...
        if mode.passCount == 0:
            if binding.bound(self) is self and clear:
                r,g,b = self.color
                glClearColor( r,g,b, 1.0 )
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)