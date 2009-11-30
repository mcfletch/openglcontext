#! /usr/bin/env python
'''=RedBook NURBS Trim=

[nurbsobject.py-screen-0001.png Screenshot]

This tutorial demonstrates more involve usage of the OpenGLContext
scenegraph NURBs nodes.  It implements the RedBook trimmed-nurbs 
demo using the scenegraph API.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import nurbs

class TestContext( BaseContext ):
    """RedBook Trimmed Nurbs Demo"""
    '''Setup a reasonably close camera.'''
    initialPosition = (0,0,3)
    def buildControlPoints( self ):
        """Build control points for the main surface"""
        '''We create a single 4x4x3 grid that holds the control 
        points for the main surface.  Basically we're just creating 
        a "mound" that tapers off on the edges here.
        '''
        ctlpoints = zeros( (4,4,3), 'd')
        for u in range( 4 ):
            for v in range( 4):
                ctlpoints[u][v][0] = 2.0*(u - 1.5)
                ctlpoints[u][v][1] = 2.0*(v - 1.5);
                if (u == 1 or u ==2) and (v == 1 or v == 2):
                    ctlpoints[u][v][2] = 3.0;
                else:
                    ctlpoints[u][v][2] = -3.0;
        return ctlpoints
    def OnInit( self ):
        """Create the scenegraph"""
        print """You should see a multi-coloured Nurbs surface
with an ice-cream-cone-shaped trimming curve
(a hole cut out of it)."""
        
        '''GLU Nurbs trims via contours which are applied in the 
        same way as tessellation, i.e. your outermost contour will 
        trim off the edges of your nurbs, while inner contours will 
        cut "holes" in to the Nurbs.  Since we don't want to trim off 
        the edge of the hill, we define a contour that includes all 
        of the surface.  The coordinates are in the parametric 
        coordinate system, so 0.0 is the start and 1.0 is the finish.
        '''
        trimmingContour = [
            Contour2D(
                children = [
                    Polyline2D(
                        # outside edge
                        point = array(  [
                            [0.0, 0.0],
                            [1.0, 0.0],
                            [1.0, 1.0],
                            [0.0, 1.0],
                            [0.0, 0.0],
                        ], 'd')
                    ),
                ],
            ),
            Contour2D(
                children = [
                    Polyline2D(
                        # inside edge
                        point = array([
                            [0.75, 0.5],
                            [0.5, 0.25],
                            [0.25, 0.5],
                        ],'d')
                    ),
                    NurbsCurve2D(
                        knot = array( [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], 'd'),
                        controlPoint = array( [
                            [0.25, 0.5],
                            [0.25, 0.75],
                            [0.75, 0.75],
                            [0.75, 0.5],
                        ],'d')
                    )
                ]
            ),
        ]

        knots = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        '''The color array is indexed to the control-point array 
        when/if it is provided.  Here we make a progression of colours 
        across the surface'''
        color = zeros( (4,4,3), 'd' )
        color[0,:,:] = (1.,0,0)
        color[1,:,:] = (.66,.33,0)
        color[2,:,:] = (.33,.66,0)
        color[3,:,:] = (0,1.,0)
        self.shape = Shape(
            appearance = Appearance(
                material = Material(),
            ),
            geometry = TrimmedSurface(
                surface = NurbsSurface(
                    controlPoint = self.buildControlPoints(),
                    color = color,
                    vDimension = 4,
                    uDimension = 4,
                    uKnot = knots,
                    vKnot = knots,
                ),
                trimmingContour = trimmingContour,
            ),
        )
        self.sg = sceneGraph(
            children = [ 
                Transform(
                    scale = [.5,.5,.5],
                    rotation = [1,0,0,-.5],
                    children = [self.shape],
                ),
            ],
        )

if __name__ == "__main__":
    TestContext.ContextMainLoop()