#! /usr/bin/env python
'''=Molehill NURBS Introduction=

[molehill.py-screen-0001.png Screenshot]

This version of the demo shows how to create the same 
visual effect as the original MoleHill Demo using the 
OpenGLContext Nurbs extension (patterned after the Blaxxun
Nurbs extension).
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import nurbs

class TestContext( BaseContext ):
    def buildControlPoints( self ):
        """Build control points for NURBS mole hills"""
        '''Normally you would use a 3D modeller to create nurbs 
        geometry, but we'll generate it by paper-and-pencil method 
        (actually, Mark Kilgard did in 1995, we're just copying the 
        setup here).
        '''
        pts1 = []
        pts2 = []
        pts3 = []
        pts4 = []

        for u in range(4):
            pts1.append([])
            pts2.append([])
            pts3.append([])
            pts4.append([])
            for v in range(4):
                '''Red surface'''
                pts1[u].append([2.0*u, 2.0*v, 0.0])
                if (u == 1 or u == 2) and (v == 1 or v == 2):
                    pts1[u][v][2] = 6.0
        
                '''Green surface'''
                pts2[u].append([2.0*u - 6.0, 2.0*v - 6.0, 0.0])
                if (u == 1 or u == 2) and (v == 1 or v == 2):
                    if u == 1 and v == 1: 
                        '''Pull hard on single middle square.'''
                        pts2[u][v][2] = 15.0
                    else:
                        '''Push down on other middle squares.'''
                        pts2[u][v][2] = -2.0
        
                '''Blue surface'''
                pts3[u].append([2.0*u - 6.0, 2.0*v, 0.0])
                if (u == 1 or u == 2) and (v == 1 or v == 2):
                    if u == 1 and v == 2: 
                        '''Pull up on single middle square.'''
                        pts3[u][v][2] = 11.0
                    else:
                        '''Pull up slightly on other middle squares.'''
                        pts3[u][v][2] = 2.0
        
                '''Yellow surface'''
                pts4[u].append([2.0*u, 2.0*v - 6.0, 0.0])
                if u != 0 and (v == 1 or v == 2):
                    if v == 1: 
                        '''Push down front middle and right squares.'''
                        pts4[u][v][2] = -2.0
                    else:
                        '''Pull up back middle and right squares.'''
                        pts4[u][v][2] = 5.0
        

        '''Stretch up red's far right corner.'''
        pts1[3][3][2] = 6.0
        '''Pull down green's near left corner a little.'''
        pts2[0][0][2] = -2.0
        '''Turn up meeting of four corners.'''
        pts1[0][0][2] = 1.0
        pts2[3][3][2] = 1.0
        pts3[3][0][2] = 1.0
        pts4[0][3][2] = 1.0
        return pts1,pts2,pts3,pts4
        
    def OnInit( self ):
        """Create the scenegraph for rendering"""
        print """You should see a 4-colour "molehill" composed of four different NurbsSurface nodes."""
        
        knots = array( (0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0),'f' )

        pts1,pts2,pts3,pts4 = self.buildControlPoints()
        colors = [[1,0,0],[0,1,0],[0,0,1],[1,1,0],]
        
        '''All of the shapes have the same structure (number of knots 
        in both u and v dimensions). They only vary in the control 
        points and colours with which we will render them.'''
        self.shapes = []
        for pts,color in zip((pts1,pts2,pts3,pts4),colors):
            appearance = Appearance(
                material = Material(
                    diffuseColor = color,
                ),
            )
            '''The actual NURBS surfaces are simple NurbsSurface 
            instances, with no trimming or other complex operations.'''
            self.shapes.append(
                Shape(
                    appearance = appearance,
                    geometry = NurbsSurface(
                        controlPoint = pts,
                        vDimension = 4,
                        uDimension = 4,
                        uKnot = knots,
                        vKnot = knots,
                    ),
                )
            )
            '''Here we render the control points so you can see them in 
            relation to the surface.'''
            self.shapes.append(
                Shape(
                    geometry = PointSet(
                        coord = Coordinate( 
                            point = pts,
                        ),
                    ),
                )
            )
        '''Scenegraph is transformed so that the initial view looks
        approximately like the original code'''
        self.sg = sceneGraph(
            children = [ 
                Transform(
                    scale = [.5,.5,.5],
                    rotation = [1,0,0,-.5],
                    children = self.shapes,
                ),
            ],
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''
Original Demo:

    Copyright (c) Mark J. Kilgard, 1995

    This program is freely distributable without licensing fees 
    and is provided without guarantee or warrantee expressed or 
    implied. This program is -not- in the public domain.

    molehill uses the GLU NURBS routines to draw some nice surfaces.
'''