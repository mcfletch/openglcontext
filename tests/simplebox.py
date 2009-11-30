#! /usr/bin/env python
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *

scene = sceneGraph(
    children = [
        Group(
            DEF = 'g',
        ),
    ],
)
scene.children[0].children.append( Transform(
    DEF = 't',
    translation = ( 1,2,3 ),
    children = [
        Shape(
            geometry = Box(),
            # follows VRML97 standard, so normally
            # want the material Node so that there
            # will be lighting applied...
            appearance=Appearance(
                material = Material(),
            ),
        ),
    ],
))
class TestContext( BaseContext ):
    def OnInit( self ):
        self.sg = scene

if __name__ == "__main__":
    TestContext.ContextMainLoop()