#! /usr/bin/env python
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import random
from OpenGLContext.events.timer import Timer
from pydispatch import dispatcher

scene = sceneGraph(
    children = [
        Group(
            DEF = 'g',
            children = [
                Shape(
                    geometry = Teapot( size=.2),
                )
            ],
        ),
    ],
)
class TestContext( BaseContext ):
    def OnInit( self ):
        self.sg = scene
        self.addEventHandler( "keypress", name="a", function = self.OnAdd)
        self.time = Timer( duration = .1, repeating = 1 )
        self.time.addEventHandler( "cycle", self.OnAdd )
        self.time.register (self)
        self.time.start ()
        
    def OnAdd( self, event ):
        """Add a new box to the scene"""
        children = self.sg.children[0].children
        if len(children) > 128:
            children[:] = []
        else:
            cube = 10
            position = ( 
                (random.random()-.5)*cube,
                (random.random()-.5)*cube,
                (random.random()-.5)*cube 
            )
            color = (random.random(),random.random(),random.random())
            children.append( Transform(
                translation = position,
                children = [
                    Shape(
                        geometry = Teapot( size=.2),
                        appearance = Appearance(
                            material=Material( 
                                diffuseColor = color,
                            )
                        ),
                    ),
                ],
            ))
            #self.sg.children[0].children = children
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()