#! /usr/bin/env python
'''SphereBackground object testing code
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import context
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *

colors = [
    (1,1,1),
    (1,0,0),
    (1,.5,0),
    (1,1,0),
    (0,1,0),
    (0,0,1),
    (0,0,0),
]

sg = sceneGraph(
    children = [
        Switch(
            whichChoice = 0,
            choice = [
                SphereBackground(
                    # sky-only
                    skyColor = colors[:4],
                    skyAngle=[.5, 1, 1.5],
                    bound = 1,
                ),
                SphereBackground(
                    # ground-only
                    skyColor = [],
                    groundColor = colors[:3],
                    groundAngle=[1.3,1.58],
                    bound = 1,
                ),
                SphereBackground(
                    skyColor = colors[-4:],
                    skyAngle=[.5, 1, 1.75],
                    groundColor = colors[:3],
                    groundAngle=[1.3,1.58],
                    bound = 1,
                ),
            ],
        ),
        Shape(
            geometry = Box (),
            appearance = Appearance( material=Material()),
        ),
    ],
)

class TestContext( BaseContext ):
    """Tests the background object's rendering
    """
    current = 0
    def OnBGSwitch( self, event=None):
        current = sg.children[0].whichChoice
        sg.children[0].whichChoice = (current+1) % len(sg.children[0].choice)
        self.triggerRedraw(1)
        
    def OnInit( self ):
        print 'press b to choose another background'
        self.addEventHandler(
            'keypress', name = 'b', function = self.OnBGSwitch
        )
    def getSceneGraph( self, mode = None):
        """Render the geometry for the scene."""
        return sg

if __name__ == "__main__":
    TestContext.ContextMainLoop()
