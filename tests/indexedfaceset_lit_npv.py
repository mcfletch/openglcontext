#! /usr/bin/env python
'''IndexedFaceSet test (test for normal smoothing)

Lit
Material
Normal-per-vertex generation
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.arrays import *
import string, time, StringIO
from OpenGLContext.scenegraph import basenodes

def loadData( data ):
    file = StringIO.StringIO( data )
    points = []
    indices = []
    readingPoints = 1
    while readingPoints:
        line = file.readline().strip().split()
        if len(line) > 1:
            points.append( map( float, line ))
        else:
            readingPoints = 0
    readingIndices = 1
    while readingIndices:
        line = file.readline().strip().split()
        if len(line) > 1:
            indices.extend( map( int, line ))
        else:
            readingIndices = 0
    print 'got %s point and %s indices'% ( len(points), len(indices))
    return points, indices
            

class TestContext( BaseContext ):
    initialPosition = (0,0,5) # set initial camera position, tutorial does the re-positioning
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Should see 6-sided polygon with normal-per-vertex smoothing
    This polygon is produced using the GLU tesselator
    from a simple linear progression of indices across
    the 6 points of the polygon."""
        points, indices = loadData( TESTDATA )
        self.sg = basenodes.sceneGraph(
            children = [
                basenodes.Transform(
                    children = [
                        basenodes.Shape(
                            appearance = basenodes.Appearance(
                                material = basenodes.Material(
                                    diffuseColor =(1,0,0)
                                )
                            ),
                            geometry = basenodes.IndexedFaceSet(
                                coord = basenodes.Coordinate (
                                    point = points,
                                ),
                                coordIndex = indices,
                                creaseAngle = 3.14,
                                normalPerVertex = 1,
                            ),
                        ),
                    ],
                ),
            ]
        )


TESTDATA = """-1 0 0
0 -.5 -1
2 0 0
1 1 0
0 1.5 1
-1 1 0

0 1 2 3 4 5
"""
##TESTDATA = """-1 0 0
##1 0 0
##1 1 0
##-1 1 0
##
##0 1 2 3 
##"""
##

if __name__ == "__main__":
    TestContext.ContextMainLoop()


