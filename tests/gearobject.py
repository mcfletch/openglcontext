#! /usr/bin/env python
'''Tests rendering of the Box geometry object
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.arrays import *
from OpenGL.GL import *
import string, time
from math import pi

class TestContext( BaseContext ):
    def OnInit( self ):
        """Scene set up and initial processing"""
        print """Should see two interlocked gears
"""

        g2 = Transform( 
            DEF = 'g2',
            children = [
                Shape(
                    geometry = Gear(
                        teeth = 60,
                        outer_radius = 1.5,
                        tooth_depth = 0.05,
                    ),
                    appearance = Appearance(
                        material = Material(
                            diffuseColor =(1,0,0),
                            shininess = .5,
                            specularColor = (1,1,0),
                        ),
                    ),
                ),
            ],
        )
        self.sg = sceneGraph(
            children = [
                Transform( 
                    DEF = 'g1',
                    children = [
                        Transform(
                            rotation = [0,0,1,-pi/40],
                            children = [
                                Shape(
                                    geometry = Gear(
                                        teeth = 20,
                                        tooth_depth = 0.05,
                                    ),
                                    appearance = Appearance(
                                        material = Material(
                                            diffuseColor =(.2,.2,.2),
                                            shininess = .5,
                                            specularColor = (1,0,0),
                                        ),
                                    ),
                                ),
                            ],
                        ),
                    ],
                ),
                Transform(
                    DEF = 'g2-position',
                    translation = (2.0,0,0),
                    children = [
                        g2,
                    ],
                ),
                Transform(
                    DEF = 'g4-position',
                    translation = (5.1,0,1.05),
                    rotation = [0,0,1,pi/120],
                    children = [
                        g2,
                    ],
                ),
                Transform( 
                    DEF = 'g3-orient',
                    rotation = [0,1,0,pi/2],
                    translation = [3.55,0,.5],
                    children = [
                        Transform(
                            DEF = 'g3',
                            children = [
                                Transform(
                                    rotation = [0,0,1,-pi/40],
                                    children = [
                                        Shape(
                                            geometry = Gear(
                                                teeth = 20,
                                                outer_radius = .5,
                                                tooth_depth = 0.05,
                                            ),
                                            appearance = Appearance(
                                                material = Material(
                                                    diffuseColor =(0,0,.5),
                                                    specularColor = (0,0,1),
                                                ),
                                            ),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ],
                ),
                Transform(
                    DEF = 'lights',
                    children = [
                        PointLight(
                            location = [-5,5,5],
                            color = [1,1,0],
                        ),
                        PointLight(
                            location = [10,80,-5],
                            color = [0,1,1],
                        ),
                        PointLight(
                            location = [0,0,-20],
                            color = [1,1,1],
                        ),
                    ],
                ),
                OrientationInterpolator(
                    DEF = 'lights1',
                    key = [0.0, 0.5, 1.0 ],
                    keyValue = [
                        0,1,0,0.0, 
                        0,1,0,pi, 
                        0,1,0,2*pi,
                    ],
                ),
                OrientationInterpolator(
                    DEF = 'oi1',
                    key = [0.0, 0.5, 1.0 ],
                    keyValue = [
                        0,0,1,0.0, 
                        0,0,1,pi, 
                        0,0,1,2*pi,
                    ],
                ),
                OrientationInterpolator(
                    DEF = 'oi2',
                    key = [0.0, 0.5, 1.0 ],
                    keyValue = [
                        0,0,1,2*pi,
                        0,0,1,pi, 
                        0,0,1,0.0, 
                    ],
                ),
                OrientationInterpolator(
                    DEF = 'oi3',
                    key = [0.0, 0.5, 1.0 ],
                    keyValue = [
                        0,0,1,2*pi,
                        0,0,1,pi, 
                        0,0,1,0.0, 
                    ],
                ),
                TimeSensor(
                    DEF = 'lights-time',
                    cycleInterval = 180.0,
                    loop = True,
                ),
                TimeSensor(
                    DEF = 't1',
                    cycleInterval = 30.0,
                    loop = True,
                ),
                TimeSensor(
                    DEF = 't2',
                    cycleInterval = 90.0,
                    loop = True,
                ),
                TimeSensor(
                    DEF = 't3',
                    cycleInterval = 30.0,
                    loop = True,
                ),
            ],
        )
        for i in range( 1,4):
            self.sg.addRoute( 
                't%s'%(i),'fraction_changed',
                'oi%s'%(i),'set_fraction' 
            )
            self.sg.addRoute( 
                'oi%s'%(i),'value_changed',
                'g%s'%(i),'set_rotation',
            )
        self.sg.addRoute(
            'lights-time','fraction_changed',
            'lights1','set_fraction',
        )
        self.sg.addRoute(
            'lights1','value_changed',
            'lights','set_rotation',
        )
            
    multiplier = 1.0
    def OnIdle( self, event=None ):
        self.multiplier = (self.multiplier * 1.00001)
        for name in ('t1','t2','t3'):
            t1 = self.sg.getDEF( name )
            timer = t1.getTimer(self)
            timer.internal.multiplier = self.multiplier
    

if __name__ == "__main__":
    TestContext.ContextMainLoop()
