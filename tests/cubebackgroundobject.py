#! /usr/bin/env python
'''CubeBackground object test (image cube background)'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import context
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *

class TestContext( BaseContext ):
    """Tests the CubeBackground object's rendering
    """
    def OnInit( self ):
        """Scene set up and initial processing"""
        self.sg = sceneGraph(
            children = [
                Shape(
                    geometry = Teapot(),
                    appearance = Appearance( material=Material(
                        diffuseColor=(1,0,0),
                        specularColor=(0,1,0),
                    )),
                ),
                CubeBackground(
                    backUrl = "pimbackground_BK.jpg",
                    frontUrl = "pimbackground_FR.jpg",
                    leftUrl = "pimbackground_LF.jpg",
                    rightUrl = "pimbackground_RT.jpg",
                    topUrl = "pimbackground_UP.jpg",
                    bottomUrl = "pimbackground_DN.jpg",
                ),
            ]
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
