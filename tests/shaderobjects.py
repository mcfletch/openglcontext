#! /usr/bin/env python
'''Tests rendering using the ARB shader objects extension...
'''
#import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import *
import time, sys,logging,math
log = logging.getLogger( 'shaderobjects' )
log.warn( 'Context %s',  BaseContext )

logging.getLogger( 'OpenGLContext.scenegraph.shaders' ).setLevel( logging.DEBUG )


shaders = [
    Shader( objects = [o], DEF='Shader_%s'%(i,) )
    for i,o in enumerate([
    GLSLObject(
        uniforms = [
            FloatUniform2f(name = 'henry',value = [0,1]),
        ],
        shaders = [
            GLSLShader( url = './resources/toon.vert.txt', type='VERTEX'),
            GLSLShader( url = './resources/toon.frag.txt', type='FRAGMENT'),
        ],
    ),
    GLSLObject(
        shaders = [
            GLSLShader( 
                url = [ 
                    'res://simpleshader_vert_txt', 
                ],
                type='VERTEX'
            ),
            GLSLShader( url = 'res://simpleshader_frag_txt', type='FRAGMENT'),
        ],
    ),
    GLSLObject(
        uniforms = [
            FloatUniform1f(name="Shininess", value=.9 ),
            FloatUniform1f(name="Diffuse", value=.9 ),
            FloatUniform1f(name="Specular", value=.8 ),
            
            FloatUniform1f(name="MaxIterations", value=10 ),
            FloatUniform2f(name="Center",value=(-0.64870076, 0.42840204), DEF='MAND_CENT'),
            FloatUniform1f(name="Zoom",value=1.0, DEF='MAND_ZOOM' ),
            FloatUniform3f(name="InnerColor",value=(1,0,0)),
            FloatUniform3f(name="OuterColor1",value=(0,1,0)),
            FloatUniform3f(name="OuterColor2",value=(0,0,1)),
        ],
        shaders = [
            GLSLShader( 
                url = './resources/CH18-mandel.vert.txt', type='VERTEX'
            ),
            GLSLShader( 
                url = './resources/CH18-mandel.frag.txt', type='FRAGMENT'
            ),
        ],
    ),
    GLSLObject(
        uniforms = [
        ],
        shaders = [
            GLSLShader( url = './resources/grid.frag.txt', type='FRAGMENT'),
        ],
    ),
    GLSLObject(
        uniforms = [
        ],
        shaders = [
            GLSLShader( url = './resources/discard.frag.txt', type='FRAGMENT'),
        ],
    ),
    GLSLObject(
        textures = [
            TextureUniform(
                value = ImageTexture( url='nehe_wall.bmp' ),
                name = 'SimpleTexture',
            ),
        ],
        shaders = [
            GLSLShader( url = './resources/simpletexture.frag.txt', type='FRAGMENT'),
        ],
    ),
    GLSLObject(
        shaders = [
            GLSLShader( url = 'res://simpleshader_vert_txt', type='VERTEX'),
            GLSLShader( url = 'res://simpleshader_frag_txt', type='FRAGMENT'),
        ],
    ),
    
        
    ])
]


class TestContext( BaseContext ):
    rotation = 0.00
    
    current_shader = 0
    
    def OnInit( self ):
        """Scene set up and initial processing"""
        t = Transform(
            children = [
                PointLight(
                    location = (1,4,10),
                ),
            ],
        )
        self.shaders = shaders
        self.shapes = [
            Shape(
                appearance = self.shaders[0],
                geometry = Sphere( radius = 2.0 ),
            ),
            Shape(
                appearance = self.shaders[0],
                geometry = Teapot( size = .75 ),
            ),
            Shape(
                appearance = self.shaders[0],
                geometry = Box( size=(3,3,3) ),
            ),
        ]
        self.sg = sceneGraph(
            children = [
                Transform(
                    DEF = 'scene',
                    children= [
                        self.shapes[0],
                        Transform(
                            translation = (-3,0,4),
                            children = [
                                self.shapes[1]
                            ],
                        ),
                        Transform(
                            translation = (-2,0,6),
                            children = [
                                Shape(
                                    appearance = Appearance(
                                        material = Material( diffuseColor = (0,0,1)),
                                    ),
                                    geometry = Sphere( radius = .25 ),
                                ),
                            ],
                        ),
                    ],
                ),
                t,
                Transform(
                    translation = (5,0,3),
                    children = [
                        self.shapes[2]
                    ],
                ),
                PointLight( location = (10,10,10) ),
            ],
        )
        self.time = Timer( duration = 30.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        print 'press "n" for next shader'
        self.addEventHandler( "keypress", name="n", function = self.OnNext)
        
        # MANDELBROT explorer...
        print 'Explore Orange-book mandelbrot with:\n   asdw (center) zx (zoom) and rf (iterations)'
        self.addEventHandler( "keypress", name="a", function = self.OnMand)
        self.addEventHandler( "keypress", name="d", function = self.OnMand)
        self.addEventHandler( "keypress", name="s", function = self.OnMand)
        self.addEventHandler( "keypress", name="w", function = self.OnMand)
        self.addEventHandler( "keypress", name="z", function = self.OnMand)
        self.addEventHandler( "keypress", name="x", function = self.OnMand)
        self.addEventHandler( "keypress", name="r", function = self.OnMand)
        self.addEventHandler( "keypress", name="f", function = self.OnMand)


        self.addEventHandler( "keypress", name="l", function = self.OnLeak)


    def OnTimerFraction( self, event ):
        r = event.fraction()
        self.sg.children[0].rotation = [0,1,0,r * math.pi *2]
    def OnNext( self, event ):
        self.current_shader += 1
        shader = self.shaders[ self.current_shader % len(self.shaders) ]
        for shape in self.shapes:
            shape.appearance = shader 
            #print shader.toString()
    def OnMand( self, event ):
        shader = self.shaders[2]
        zoom = shader.objects[0].getVariable( 'Zoom' )
        center = shader.objects[0].getVariable( 'Center' )
        iterations = shader.objects[0].getVariable( 'MaxIterations' )
        if event.name == 'z':
            zoom.value = zoom.value * .85
            print 'zoom value', zoom.value
        elif event.name == 'x':
            zoom.value = zoom.value * 1.15
            print 'zoom value', zoom.value
        elif event.name == 'r':
            if iterations is not None:
                iterations.value += 5
                if iterations.value[0] > 105:
                    # limit of floating-point precision...
                    iterations.value = 105
                print 'max iterations', iterations.value[0]
            else:
                print 'shader objects 0', shader.objects[0].toString()
        elif event.name == 'f':
            if iterations is not None:
                iterations.value -= 5
                if iterations.value[0] <= 0:
                    iterations.value = 1
                print 'max iterations', iterations.value[0]
        directions = { 'a':(-1,0),'d':(1,0),'w':(0,1),'s':(0,-1) }
        if event.name in directions:
            step = zoom.value / 10.0
            vec = array(directions[event.name],'f') * step 
            center.value = center.value + vec
            print 'new center', center.value
    def OnLeak( self, event ):
        from OpenGLContext.debug import leaks
        if leaks.whole_set:
            leaks.delta()
        else:
            leaks.init()

if __name__ == "__main__":
    #import cProfile
    #cProfile.run( "TestContext.ContextMainLoop()", 'shaderobjects.profile' )
    TestContext.ContextMainLoop()
