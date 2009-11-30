#! /usr/bin/env python
'''DEK's Texturesurf demo without the texture, tests glEvalMesh2'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.arrays import array
from OpenGLContext.scenegraph.basenodes import *
import string, time

## Control points for the bezier surface
ctrlpoints = array([
    [[-1.5, -1.5, 4.0] ,
     [-0.5, -1.5, 2.0] ,
     [0.5, -1.5, -1.0] ,
     [1.5, -1.5, 2.0]] ,
    [[-1.5, -0.5, 1.0] ,
     [-0.5, -0.5, 3.0] ,
     [0.5, -0.5, 0.0] ,
     [1.5, -0.5, -1.0]] ,
    [[-1.5, 0.5, 4.0] ,
     [-0.5, 0.5, 0.0] ,
     [0.5, 0.5, 3.0] ,
     [1.5, 0.5, 4.0]] ,
    [[-1.5, 1.5, -2.0] ,
     [-0.5, 1.5, -2.0] ,
     [0.5, 1.5, 0.0] ,
     [1.5, 1.5, -1.0]] ,
], 'f' )

## Texture control points
texpts = array([
    [[0.0, 0.0],
     [0.0, 1.0]],
    [[1.0, 0.0],
     [1.0, 1.0]],
], 'f')


class TestContext( BaseContext ):
    def Render( self, mode ):
        BaseContext.Render( self, mode )
        self.light.Light( GL_LIGHT0, mode )
        glCallList( self.surfaceID )
        
    def buildDisplayList( self):
        glDisable(GL_CULL_FACE)
        glEnable(GL_NORMALIZE)
        glEnable(GL_MAP2_VERTEX_3)
        glEnable(GL_MAP2_NORMAL)
        glMap2f(GL_MAP2_VERTEX_3, 0., 1., 0., 1., ctrlpoints)
        glMap2f(GL_MAP2_NORMAL, 0., 1., 0., 1., ctrlpoints)
        glMapGrid2f(20, 0.0, 1.0, 20, 0.0, 1.0)
        displayList = glGenLists(1)
        glNewList( displayList, GL_COMPILE)
        glColor3f( 1.0,0,0)
        glEvalMesh2(GL_FILL, 0, 20, 0, 20)
        glEndList()
        return displayList
    def OnInit( self ):
        """Initialise"""
        print """Should see curvy surface with no texture"""
        self.surfaceID = self.buildDisplayList()
        self.light = SpotLight(
            direction = (-10,0,-10),
            cutOffAngle = 1.57,
            color = (0,0,1),
            location = (10,0,10),
        )
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()