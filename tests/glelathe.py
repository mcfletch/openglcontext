#! /usr/bin/env python
'''Test of gleLathe and related functions
'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *
from math import pi
from OpenGLContext.scenegraph import extrusions
from OpenGLContext.scenegraph.basenodes import *

contour = array([
    (0,0), (1,0),
    (1,1), (0,1),
    (0,0),
],'d')

normals = array([
    (0,-1), (1,0),
    (0,1), (-1,0),
],'d')

    

class TestContext( BaseContext ):
    def OnInit( self ):
        """Load the image on initial load of the application"""
        print """You should see a round "washer" formed by sweeping a square
through a circle.  A drill-like screw should penetrate the
center of the washer.  Around the washer should be a cone-
shaped "spring", which should extend some distance downward."""
        appearance = Appearance(
            material=Material(
                shininess = 1.0,
            ),
            texture = ImageTexture(
                url = "wrls/irradiation.jpg",
            ),
            textureTransform = TextureTransform(
                scale = [8,1],
            ),
        )
        self.sg = sceneGraph(
            children = [
                Transform(
                    DEF = 'Screw-Trans',
                    children = [
                        Transform(
                            rotation = (1,0,0, 1.57),
                            scale = (.8,.8,.8),
                            children = [
                                Shape(
                                    geometry = extrusions.Lathe(
                                        contour = contour,
                                        normals = normals,
                                        startRadius = 1.5,
                                        textureMode = 'cylinder vertex',
                                    ),
                                    appearance = appearance,
                                ),
                                Shape(
                                    geometry = extrusions.Screw(
                                        contour = contour,
                                        normals = normals,
                                        startZ = -5,
                                        endZ = 5,
                                        totalAngle = 5 * pi,
                                        textureMode = 'flat normal model',
                                    ),
                                    appearance = Appearance(
                                        material=Material(),
                                    ),
                                ),
                                Shape(
                                    geometry = extrusions.Spiral(
                                        contour = contour,
                                        normals = normals,
                                        startRadius = 3,
                                        deltaRadius = 1.5,
                                        startZ = 0,
                                        deltaZ = 1.5,
                                        totalAngle = 8 * pi,
                                        textureMode = 'cylinder vertex model',
                                    ),
                                    appearance = appearance,
                                ),
                            ],
                        ),
                    ],
                ),
                OrientationInterpolator(
                    DEF = 'Rot',
                    key = [0,.25,.5,.75,1.0],
                    keyValue = [ 
                        0,1,0,0,  
                        0,1,0,1.57,  
                        0,1,0,3.14159,
                        0,1,0,4.71,
                        0,1,0,0,
                        ],
                ),
                TimeSensor(
                    DEF = 'T',
                    cycleInterval = 30.0,
                    loop = True,
                ),
                PointLight( location = (20,10,4) ),
                PointLight( location = (-20,10,-4), color=(.3,.3,.5) ),
            ],
        )
        self.sg.addRoute( 
            'T','fraction_changed','Rot','set_fraction' 
        )
        self.sg.addRoute( 
            'Rot','value_changed','Screw-Trans','set_rotation'
        )
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
