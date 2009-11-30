#! /usr/bin/env python
'''IndexedFaceSet object test NPF versus NPV operation

Lit
Material
Normal-per-face generation
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
##	print 'got %s point and %s indices'% ( len(points), len(indices))
    return points, indices
    

class TestContext( BaseContext ):
    initialPosition = (-5,0,5) # set initial camera position, tutorial does the re-positioning
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """Should see two geodesic spheres over black background
        
    Sphere to left should be lit with normal-per-face,
    giving each face a hard-line edge with adjacent faces.
    
    Sphere to the right should be lit with normal-per-vertex
    which should make the lines between faces fuzzier."""
        points, indices = loadData( ICOSDATA )
##		light = basenodes.PointLight(
##			location = (2,10,10)
##		)
        self.sg = basenodes.sceneGraph(
##			lights = [
##				light
##			],
            children = [
##				light,
                basenodes.Transform(
                    translation = (-1.5,0,0),
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
                            ),
                        ),
                    ],
                ),
                basenodes.Transform(
                    translation = (1.5,0,0),
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
##	def Background( self, mode = 0):
##		glClearColor( 0,0,0,0)
##		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
                

TESTDATA = """-1 0 0
1 0 0
1 1 0
-1 1 0

0 1 2 3
"""
ICOSDATA = """-4.769095 1.349644 0.011604
-3.792492 0.603581 -0.697931
-5.142116 0.603581 -1.136457
-5.976250 0.603581 0.011604
-5.142116 0.603581 1.159665
-3.792492 0.603581 0.721138
-4.396073 -0.603581 -1.136458
-5.745697 -0.603581 -0.697931
-5.745697 -0.603581 0.721138
-4.396073 -0.603581 1.159664
-3.561940 -0.603581 0.011603
-4.769095 -1.349644 0.011603
-4.195061 1.148080 -0.405451
-4.988352 1.148081 -0.663212
-4.414316 0.709559 -1.080274
-4.195061 1.148080 0.428659
-3.621023 0.709556 0.011604
-5.478643 1.148077 0.011604
-5.697906 0.709557 -0.663214
-4.988352 1.148080 0.686420
-5.697906 0.709556 0.686421
-4.414316 0.709558 1.103482
-3.485506 -0.000000 0.428661
-3.485506 0.000000 -0.405453
-3.975794 0.000000 -1.080281
-4.769095 0.000000 -1.338040
-5.562396 0.000000 -1.080281
-6.052684 0.000000 -0.405453
-6.052684 -0.000000 0.428661
-5.562396 -0.000000 1.103488
-4.769095 -0.000000 1.361247
-3.975794 -0.000000 1.103488
-3.840284 -0.709556 -0.663214
-5.123874 -0.709558 -1.080274
-5.917166 -0.709556 0.011603
-5.123874 -0.709559 1.103481
-3.840284 -0.709557 0.686421
-4.059547 -1.148077 0.011603
-4.549838 -1.148080 -0.663212
-5.343129 -1.148080 -0.405452
-5.343129 -1.148080 0.428659
-4.549838 -1.148080 0.686419

12 14 13 -1
12 15 16 -1
13 18 17 -1
17 20 19 -1
19 21 15 -1
16 22 23 -1
14 24 25 -1
18 26 27 -1
20 28 29 -1
21 30 31 -1
23 32 24 -1
25 33 26 -1
27 34 28 -1
29 35 30 -1
31 36 22 -1
32 37 38 -1
33 38 39 -1
34 39 40 -1
35 40 41 -1
36 41 37 -1
9 41 36 -1
11 37 41 -1
10 36 37 -1
8 40 35 -1
11 41 40 -1
9 35 41 -1
7 39 34 -1
11 40 39 -1
8 34 40 -1
6 38 33 -1
11 39 38 -1
7 33 39 -1
10 37 32 -1
11 38 37 -1
6 32 38 -1
5 31 22 -1
10 22 36 -1
9 36 31 -1
4 29 30 -1
9 30 35 -1
8 35 29 -1
3 27 28 -1
8 28 34 -1
7 34 27 -1
2 25 26 -1
7 26 33 -1
6 33 25 -1
1 23 24 -1
6 24 32 -1
10 32 23 -1
4 30 21 -1
9 31 30 -1
5 21 31 -1
3 28 20 -1
8 29 28 -1
4 20 29 -1
2 26 18 -1
7 27 26 -1
3 18 27 -1
1 24 14 -1
6 25 24 -1
2 14 25 -1
5 22 16 -1
10 23 22 -1
1 16 23 -1
0 19 15 -1
5 15 21 -1
4 21 19 -1
0 17 19 -1
4 19 20 -1
3 20 17 -1
0 13 17 -1
3 17 18 -1
2 18 13 -1
0 15 12 -1
5 16 15 -1
1 12 16 -1
0 12 13 -1
2 13 14 -1
1 14 12 -1
"""


if __name__ == "__main__":
    TestContext.ContextMainLoop()


