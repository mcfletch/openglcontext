#! /usr/bin/env python
'''SelectRenderMode demonstration code with background thread

Demonstrates use of "named transforms", objects which
use push/pop of the name-stack to report selection during
the rendermode.SelectRenderMode pass.

Background thread perturbs the object positions.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import drawcube, context, interactivecontext
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGLContext.arrays import *
import string, time, random, threading, random
from OpenGLContext.scenegraph import basenodes

class TestContext( BaseContext ):
    def OnInit( self ):
        """Setup callbacks and build geometry for rendering"""
        self.addEventHandler( "mousebutton", button = 0, state = 1, function = self.OnClick1 )
        print """Click on the spheres and watch here for feedback..."""
        self.objects = basenodes.sceneGraph()
        self.buildGeometry()
        self.addEventHandler(
            "mousebutton", button = 0, state = 1,
            node = self.objects.children[-1].children[-1],
            function = self.OnClick2,
        )
        r = threading.Thread( target = self.randomiser )
        r.setDaemon(1)
        r.start()
    def getSceneGraph( self ):
        return self.objects
    def OnClick1( self, event ):
        """Handle a mouse-click in our window.

        Retrieves the "pick point", and the unprojected (world-space) coordinates
        of the clicked geometry (if a named object was clicked).
        """
        x,y  = event.getPickPoint()
        print 'Click', (x,y)
        for near, far, names in event.getNameStack():
            if names:
                print '  clicked on #%s'%(names[-1]), event.unproject()
    def OnClick2( self, event ):
        """Handle mouse click for a given name/id"""
        print "You clicked on the magic sphere!"
        self.OnClick1( event )
    COUNT = 100
    def buildGeometry( self ):
        """Create some named geometry for selection"""
        objects = []
        while len(objects) < self.COUNT:
            p = random.random()*6-3, random.random()*6-3, random.random()*6-3
            c = random.random(), random.random(), random.random()
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
    def randomiser( self ):
        while self:
            self.lockScenegraph()
            try:
                for object in self.objects.children:
                    a,b,c = object.translation
                    f = random.random()*.05 - (.025)
                    object.translation = (a+f,b+f,c+f)
            finally:
                self.unlockScenegraph()
            if self:
                self.triggerRedraw(1)
            time.sleep( .5 )
            
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()