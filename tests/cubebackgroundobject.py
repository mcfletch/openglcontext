#! /usr/bin/env python
'''CubeBackground object test (image cube background)

NOTE: CubeBackground currently uses GL_QUADS which requires compatibility profile.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import context
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *

class TestContext( BaseContext ):
    """Tests the CubeBackground object's rendering
    """
    # Requires compatibility profile for GL_QUADS in CubeBackground
    profile = 'compatibility'   # draws with the fixed-function pipeline
    def OnInit( self ):
        """Scene set up and initial processing"""
        print('Press f to toggle shader/legacy mode')
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
        self.addEventHandler(
            'keypress', name='f', function=self.OnModeToggle
        )

    def OnModeToggle(self, event=None):
        from OpenGLContext.passes import renderpass
        if renderpass.FLAT is not None:
            renderpass.FLAT.use_shaders = not renderpass.FLAT.use_shaders
            mode = "SHADER" if renderpass.FLAT.use_shaders else "LEGACY"
            print(f"Rendering mode: {mode}")
        self.triggerRedraw(1)

if __name__ == "__main__":
    TestContext.ContextMainLoop()
