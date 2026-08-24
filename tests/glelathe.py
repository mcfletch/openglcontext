#! /usr/bin/env python
'''=Lathe, Screw and Spiral=

[glelathe.py-screen-0001.png Screenshot]

A washer, a drill-like screw through its centre, and a cone-shaped spring
around it -- one `Lathe`, one `Screw` and one `Spiral`, all built from the
same square contour and turning under an `OrientationInterpolator`.

The geometry is generated as vertex arrays, so this renders in a core
profile as well as a compatibility one. See `extrusions_shapes.py` for the
whole set of swept nodes, and `docs/extrusions.html` for what each field
does.
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
        print("""A round "washer" formed by sweeping a square through a
circle. A drill-like screw penetrates the centre of the washer, and around
it is a cone-shaped "spring" extending some distance downward.""")
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
                                        normals2d = normals,
                                        startRadius = 1.5,
                                        sides = 48,
                                    ),
                                    appearance = appearance,
                                ),
                                Shape(
                                    geometry = extrusions.Screw(
                                        contour = contour,
                                        normals2d = normals,
                                        startZ = -5,
                                        endZ = 5,
                                        totalAngle = 5 * pi,
                                    ),
                                    appearance = Appearance(
                                        material=Material(),
                                    ),
                                ),
                                Shape(
                                    geometry = extrusions.Spiral(
                                        contour = contour,
                                        normals2d = normals,
                                        startRadius = 3,
                                        deltaRadius = 1.5,
                                        startZ = 0,
                                        deltaZ = 1.5,
                                        totalAngle = 8 * pi,
                                        sides = 48,
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
