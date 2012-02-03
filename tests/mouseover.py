#! /usr/bin/env python
'''MouseInEvent/MouseOutEvent demonstration
'''
import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    def OnInit( self ):
        """Setup callbacks and build geometry for rendering"""
        print """Mouse-over the spheres to see them change colour"""
#        self.contextDefinition.debugSelection = True
        self.sg = sceneGraph(
            children = [
                Transform( children = [
                    MouseOver(
                        whichChoice = 0,
                        choice = [
                            Shape(
                                geometry = Sphere(radius=.5),
                                appearance = Appearance( material=Material( diffuseColor=(0,0,1) )),
                            ),
                            Shape(
                                geometry = Sphere(radius=.5),
                                appearance = Appearance( material=Material( diffuseColor=(0,1,0) )),
                            ),
                        ],
                    )], 
                    translation = (2,0,0)
                ),
                Transform( children = [
                        MouseOver(
                            whichChoice = 0,
                            choice = [
                                Shape(
                                    geometry = Sphere(radius=.5),
                                    appearance = Appearance( material=Material( diffuseColor=(1,0,0) )),
                                ),
                                Shape(
                                    geometry = Sphere(radius=.5),
                                    appearance = Appearance( material=Material( diffuseColor=(0,0,1) )),
                                ),
                            ],
                        )
                    ], 
                    translation = (-2,0,0),
                ),
            ],
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
