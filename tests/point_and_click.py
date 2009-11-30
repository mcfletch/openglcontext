#! /usr/bin/env python
'''Primitive mouse event handler test/demo
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import drawcube, context, interactivecontext
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import *
import string, time


def buildGeometry():
    from OpenGLContext.scenegraph import basenodes
    return basenodes.sceneGraph(
        children = [
        basenodes.Transform(
            translation = (3,0,0),
            children = [
                basenodes.TouchSensor(),
                basenodes.Shape(
                    geometry = basenodes.Sphere( radius = 2 ),
                    appearance = basenodes.Appearance(
                        material = basenodes.Material( diffuseColor = (0,1,1))),
                ),
            ],
        ),
        basenodes.Transform(
            translation = (-3,2,-1),
            children = [
                basenodes.TouchSensor(),
                basenodes.Shape(
                    geometry = basenodes.Sphere( radius = 1 ),
                    appearance = basenodes.Appearance(
                        material = basenodes.Material( diffuseColor = (1,1,0))),
                ),
            ],
        ),

        basenodes.Transform(
            translation = (0,-2,2),
            children = [
                basenodes.TouchSensor(),
                basenodes.Shape(
                    geometry = basenodes.Sphere( radius = .25 ),
                    appearance = basenodes.Appearance(
                        material = basenodes.Material( diffuseColor = (0,1,0))),
                ),
            ],
        ),
    ])


class TestContext( BaseContext ):
    def OnInit( self ):
        print 'Clicking on geometry (or off geometry) will report status here'
        self.addEventHandler( "mousebutton", button = 0, state = 1, function = self.OnClick1 )
        self.sg = buildGeometry()
    def OnClick1( self, event ):
        x,y  = event.getPickPoint()
        print 'click'
        for near, far, names in event.getNameStack():
            print 'Hit', list(names)
            print '  unproject ->', event.unproject()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
