#! /usr/bin/env python
"""Add teapots to the scene at runtime, staying fast via instancing.

Every teapot shares one ``Teapot`` geometry node but carries its own coloured
``Material``.  Under the PBR pass (selected by the two environment variables
below) they collapse into a single ``glDrawElementsInstanced`` -- each instance
indexes its own colour in the group's material array -- so the frame cost stays
flat as the count climbs instead of growing with one draw call per teapot.

PBR pass selection is a whole-process decision (see passes/renderpass.py) and
must be set before the first render; glfw is required for a core context.
"""
import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
import random
from OpenGLContext.events.timer import Timer

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
        self.teapot = Teapot( size=.2)
        
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
                        geometry = self.teapot,
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
