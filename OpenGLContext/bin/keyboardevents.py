#! /usr/bin/env python
'''Demonstrate capture of keyboard and keypress events
'''
from typing import Any
from OpenGLContext import testingcontext, vrmlcontext
#: The backend is chosen at run time, so the class this subclasses is not
#: one a checker can name -- which is what Any says here.
BaseContext: Any = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *

class TestContext( vrmlcontext.VRMLContext, BaseContext ):
    def OnInit( self ) -> None:
        """Scene set up and initial processing"""
        self.addEventHandler(
            'keypress', name=None, function = self.OnKeyPress
        )
        self.addEventHandler(
            'keyboard', name=None, function = self.OnKeyBoard
        )
        print('strike keys to see generated events')
        self.keypressText = Text(
            string=["Keypress events"],
            fontStyle = FontStyle(
                justify = "MIDDLE",
                family = ["SANS"],
                format = 'bitmap',
            ),
        )
        self.keyboardText = Text(
            string=["Keyboard events"],
            fontStyle = FontStyle(
                justify = "MIDDLE",
                family = ["SANS"],
                format = 'bitmap',
            ),
        )
        self.sg = sceneGraph(
            children = [
                Viewpoint(
                    position = (0,0,10),
                ),
                Transform(
                    translation = (0,3,0),
                    children = [
                        Shape(
                            geometry = self.keypressText,
                            appearance = Appearance(
                                material = Material(
                                    diffuseColor = (1,1,1),
                                    shininess = .1,
                                ),
                            ),
                        ),
                    ],
                ),
                Transform(
                    translation = (0,-1,0),
                    children = [
                        Shape(
                            geometry = self.keyboardText,
                            appearance = Appearance(
                                material = Material(
                                    diffuseColor = (.5,.5,1),
                                    shininess = .1,
                                ),
                            ),
                        ),
                    ],
                ),
            ]
        )
    def OnKeyBoard( self, event: Any = None ) -> bool:
        """Choose a new mapped texture"""
        self.keyboardText.string = [
            event.__class__.__name__,
            repr(event.name),
            '%s (%s)'%( ['Up','Down'][event.state], event.state),
            str( event.getModifiers()),
        ]
        self.triggerRedraw( 1 )
        return True
    def OnKeyPress( self, event: Any = None ) -> bool:
        """Choose a new size"""
        self.keypressText.string = [
            event.__class__.__name__,
            repr(event.name),
            'Side: %s (%s)'%( ['Unknown','Left',"Right","Keypad"][event.side],event.side),
            'Repeating: %s (%s)'%( ['No','Yes'][event.repeating],event.repeating ),
            str( event.getModifiers()),
        ]
        return True
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
