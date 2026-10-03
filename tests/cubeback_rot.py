#! /usr/bin/env python
'''CubeBackground object test (image cube background)

NOTE: CubeBackground currently uses GL_QUADS which requires compatibility profile.
'''
import OpenGL
OpenGL.ERROR_ON_COPY = True
#OpenGL.FULL_LOGGING = True
from OpenGLContext.context import Context as BaseContext

scene = """#VRML V2.0 utf8

Shape {
    geometry Teapot { }
    appearance Appearance { 
        material Material { 
            diffuseColor .2 .2 0
            specularColor 1,0,0
        }
    }
}

DEF TR Transform {
    rotation 0,1,0,0
    children [
        DEF S Switch {
            whichChoice 0
            choice [
                DEF BG CubeBackground {
                    backUrl "pimbackground_BK.jpg"
                    frontUrl "pimbackground_FR.jpg"
                    leftUrl "pimbackground_LF.jpg"
                    rightUrl "pimbackground_RT.jpg"
                    topUrl "pimbackground_UP.jpg"
                    bottomUrl "pimbackground_DN.jpg"
                }
                DEF BG2 SphereBackground {
                    skyColor [ 0 1 0, 1,0,0 ]
                    skyAngle [ .75 ]
                    groundColor [ 0,0,0, 0,0,0 ]
                    groundAngle [ .75 ]
                }
            ]
        }
    ]
}

DEF T TimeSensor {
    cycleInterval 128.0
    loop TRUE 
}
DEF Rot OrientationInterpolator {
    key [0, .5, 1]
    keyValue [ 1,0,0,0,   1,0,0,1.57,  1,0,0,0 ]
}
ROUTE T.fraction_changed TO Rot.set_fraction
ROUTE Rot.value_changed TO TR.set_rotation
"""
    

class TestContext( BaseContext ):
    """Tests the CubeBackground object's rendering
    """
    # Requires compatibility profile for GL_QUADS in CubeBackground
    profile = 'compatibility'   # draws with the fixed-function pipeline
    def OnInit( self ):
        """Scene set up and initial processing"""
        print('Loading scene from embedded VRML97 file')
        self.sceneLoader.load( scene.encode('utf-8'), name='test.wrl',
                               on_loaded=self.OnLoaded )
        print('press <b> to switch backgrounds')
        self.addEventHandler( "keypress", name="b", function = self.OnSwitch)
    def OnLoaded( self, request ):
        """Mount the scene when the loader has parsed it"""
        self.sg = request.result
        self.tr = self.sg.getDEF( 'TR' )
    def OnSwitch( self, _event ):
        if self.sg is None:
            return
        switch= self.getSceneGraph().getDEF( 'S' )
        if switch.whichChoice:
            switch.whichChoice = 0
        else:
            switch.whichChoice = 1
        self.triggerRedraw(1)

if __name__ == "__main__":
    TestContext.ContextMainLoop()
