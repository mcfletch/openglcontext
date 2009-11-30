#! /usr/bin/env python
'''SelectRenderMode demonstration code

Demonstrates use of "named transforms", objects which
use push/pop of the name-stack to report selection during
the rendermode.SelectRenderMode pass.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import drawcube, context, interactivecontext
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import *
import string, time, random
from OpenGLContext.scenegraph import basenodes

class TestContext( BaseContext ):
    def OnInit( self ):
        """Setup callbacks and build geometry for rendering"""
        self.addEventHandler(
            "mousebutton", button = 0, state = 1,
            function = self.OnClick1
        )
        print """Click on the spheres and watch here for feedback..."""
        self.objects = basenodes.sceneGraph()
        self.buildGeometry()
        table = {}
        setattr( self.objects.children[-1], ' eventHandlers', table )
        self.objects.children[-1].children[
            -1
        ].appearance.material.diffuseColor = (1,0,0)
        self.addEventHandler(
            "mousebutton", button = 0, state = 1,
            #name = id(self.objects.children[-1]),
            node = self.objects.children[-1].children[-1],
            function = self.OnClick2,
        )
    def getSceneGraph( self ):
        return self.objects
    def OnClick1( self, event ):
        """Handle a mouse-click in our window.

        Retrieves the "pick point", and the unprojected (world-space) coordinates
        of the clicked geometry (if a named object was clicked).
        """
        x,y  = event.getPickPoint()
        print 'Click', (x,y)
        if event.getObjectPaths():
            print '  3DPoint: %s'%(event.unproject(),)
        print '  %s objects:'%( len(event.getObjectPaths()))
        for path in event.getObjectPaths():
            print ' ', path
    def OnClick2( self, event ):
        """Handle mouse click for a given name/id"""
        print "You clicked on the magic sphere!"
##		self.OnClick1( event )
        event.stopPropagation = 1
    COUNT = 100
    def buildGeometry( self ):
        """Create some named geometry for selection"""
        objects = []
        while len(objects) < self.COUNT:
            p = random.random()*6-3, random.random()*6-3, random.random()*6-3
            c = (1,1,1)#random.random(), random.random(), random.random()
            s = random.random()/2.0
            t = basenodes.Transform(
                translation = p,
                children = [
                    basenodes.TouchSensor(),
                    basenodes.Shape(
                        geometry = basenodes.Sphere( radius = s ),
                        appearance = basenodes.Appearance(
                            material = basenodes.Material( diffuseColor = c),
                        ),
                    ),
                ],
            )
            objects.append( t)
        self.objects.children = objects
            
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
