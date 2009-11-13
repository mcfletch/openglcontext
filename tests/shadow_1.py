#! /usr/bin/env python
'''=Shadows from Scratch=

In this tutorial, we'll create basic ARB_shadow-based 
shadow-rendering code.  This tutorial follows roughly 
after this C tutorial:

    http://www.paulsprojects.net/tutorials/smt/smt.html

with alterations to work with OpenGLContext.  A number of 
fixes came from looking at Ian Mallett's OpenGL Library:

    http://www.geometrian.com/Programs.php
    

'''
import OpenGL 
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext import displaylist
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GL.ARB.depth_texture import *
from OpenGL.GL.ARB.shadow import *
from OpenGLContext.arrays import (
    array, frombuffer, sin, cos, pi, dot, allclose, transpose,
)
from OpenGL.arrays import vbo
from OpenGLContext.events.timer import Timer

import string, time
import ctypes,weakref

BIAS_MATRIX = array([
    [0.5, 0.0, 0.0, 0.0],
    [0.0, 0.5, 0.0, 0.0],
    [0.0, 0.0, 0.5, 0.0],
    [0.5, 0.5, 0.5, 1.0],
], 'f')

class TestContext( BaseContext ):
    currentImage = 0
    currentSize = 0
    lightTexture = None
    lightTransform = None
    
    sceneList = None
    
    def drawScene( self, mode ):
        """Draw our scene at current animation point"""
        self.shape.Render( mode )
    
    def getLightMatrices( self ):
        glPushMatrix()
        try:
            glLoadIdentity()
            gluPerspective( 60.0, 1.0, .5, 300.0 )
            lightProj = glGetFloatv( GL_MODELVIEW_MATRIX )
            glLoadIdentity()
            gluLookAt( 
                self.lightPosition[0],self.lightPosition[1],self.lightPosition[2],
                0.0, 0.0, 0.0, # origin
                0.0, 1.0, 0.0 # up-vector 
            )
            lightView = glGetFloatv( GL_MODELVIEW_MATRIX )
            return lightProj,lightView 
        finally:
            glPopMatrix()
    
    def getTextureMatrix( self, lightProj, lightView ):
        """Texture-matrix transforming eye-space into texture-space"""
        return transpose(
            dot(
                dot( lightView, lightProj ),
                BIAS_MATRIX
            )
        )
    
    def Render( self, mode):
        BaseContext.Render( self, mode )
        if mode.visible and mode.lighting and not mode.transparent:
            # is the regular opaque rendering pass...
            # Okay, first rendering pass, render geometry into depth 
            # texture from the perspective of the light...
            glDepthFunc(GL_LEQUAL);
            glEnable(GL_DEPTH_TEST);
            
            texture = glGenTextures( 1 )
            glBindTexture( GL_TEXTURE_2D, texture )
            shadowMapSize = 256
            glTexImage2D( 
                GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT, 
                shadowMapSize, shadowMapSize, 0,
                GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
            )
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)
            
            lightProj,lightView = self.getLightMatrices()
            glMatrixMode( GL_PROJECTION )
            glLoadMatrixf( lightProj )
            glMatrixMode( GL_MODELVIEW )
            glLoadMatrixf( lightView )
            
            glViewport( 0,0, shadowMapSize, shadowMapSize )
            glCullFace( GL_FRONT )
            glShadeModel( GL_FLAT )
            glColorMask( 0,0,0,0 )
            
            # Tell the geometry to optimize itself...
            mode.lighting = False 
            mode.visible = True 
            mode.textured = False 

            # our back-facing polygons are otherwise going to have 
            # floating-point-accuracy "moire" effects where the second 
            # rendering pass writes "dark" onto the ambient light.
            # Subtle, but annoying.
            # first 1.0 just gives us the raw fragment value,
            # second says "multiply it by the smallest discernable difference"
            # within the depth buffer (i.e. +1.0 units )
            glPolygonOffset(1.0, 1.0)
            glEnable(GL_POLYGON_OFFSET_FILL) 

            self.drawScene( mode )
            
            glBindTexture(GL_TEXTURE_2D, texture)
            
            glCopyTexSubImage2D(
                GL_TEXTURE_2D, 0, 0, 0, 0, 0, shadowMapSize, shadowMapSize
            )
            
            # Restore "regular" rendering...
            w,h = self.getViewPort()
            glViewport( 0,0,w,h)
            glDisable(GL_POLYGON_OFFSET_FILL) 
            glCullFace( GL_BACK )
            glShadeModel( GL_SMOOTH )
            glColorMask( 1,1,1,1 )
            glMatrixMode( GL_PROJECTION )
            glLoadIdentity()
            glMatrixMode( GL_MODELVIEW )
            glLoadIdentity()
            glClear(GL_DEPTH_BUFFER_BIT)
            platform = self.getViewPlatform()
            platform.render()

#            # Second rendering pass, render "ambient" light into 
#            # the scene...
            mode.visible = True
            mode.lighting = True 
            mode.lightingAmbient = True 
            mode.lightingDiffuse = False 
            mode.textured = True
            self.light.Light( GL_LIGHT0, mode=mode )
            self.drawScene( mode )
            
            # Third pass, now we do the shadow tests...
            
            mode.lightingAmbient = False
            mode.lightingDiffuse = True 
            self.light.Light( GL_LIGHT0, mode=mode )
            
            textureMatrix = self.getTextureMatrix( lightProj, lightView )
            
            glTexGeni(GL_S, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR);
            glTexGenfv(GL_S, GL_EYE_PLANE, textureMatrix[0]);
            glEnable(GL_TEXTURE_GEN_S);

            glTexGeni(GL_T, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR);
            glTexGenfv(GL_T, GL_EYE_PLANE, textureMatrix[1]);
            glEnable(GL_TEXTURE_GEN_T);

            glTexGeni(GL_R, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR);
            glTexGenfv(GL_R, GL_EYE_PLANE, textureMatrix[2]);
            glEnable(GL_TEXTURE_GEN_R);

            glTexGeni(GL_Q, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR);
            glTexGenfv(GL_Q, GL_EYE_PLANE, textureMatrix[3]);
            glEnable(GL_TEXTURE_GEN_Q);
            
            glBindTexture(GL_TEXTURE_2D, texture);
            glEnable(GL_TEXTURE_2D);

            # Enable shadow comparison
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE,
                GL_COMPARE_R_TO_TEXTURE
            )

            # Shadow comparison should be true (ie not in shadow) if r<=texture
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL
            )

            # Shadow comparison should generate an INTENSITY result
            glTexParameteri(
                GL_TEXTURE_2D, GL_DEPTH_TEXTURE_MODE, GL_INTENSITY
            )
            
            glAlphaFunc(GL_GEQUAL, 0.999)
            glEnable(GL_ALPHA_TEST)
            
            self.drawScene( mode )
            
            glDisable(GL_TEXTURE_2D)

            glDisable(GL_TEXTURE_GEN_S)
            glDisable(GL_TEXTURE_GEN_T)
            glDisable(GL_TEXTURE_GEN_R)
            glDisable(GL_TEXTURE_GEN_Q)
            glDisable(GL_LIGHTING);
            glDisable(GL_ALPHA_TEST);            
            
            mode.lightingAmbient = True 
            
        else:
            self.drawScene( mode )
#        self.vbo.bind()
#        glReadPixels(
#            0, 0, 
#            300, 300, 
#            GL_RGBA, 
#            GL_UNSIGNED_BYTE,
#            self.vbo,
#        )
#        # map_buffer returns an Byte view, we want an 
#        # UInt view of that same data...
#        data = map_buffer( self.vbo ).view( 'I' )
#        print data
#        del data
#        self.vbo.unbind()
        
    def OnInit( self ):
        """Scene set up and initial processing"""
#        self.vbo = vbo.VBO( 
#            None,
#            target = GL_PIXEL_PACK_BUFFER,
#            usage = GL_DYNAMIC_READ,
#            size = 300*300*4,
#        )
        self.shape = Shape(
            geometry = Teapot( size=2.5 ),
            appearance = Appearance(
                material = Material(
                    diffuseColor =(1,0,0),
                    ambientIntensity = .2,
                ),
#                texture = ImageTexture(
#                    url = ["nehe_wall.bmp"]
#                ),
            ),
        )
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        
        self.light = PointLight(
            location = [0,5,10],
            color = [1,.5,.5],
            ambientIntensity = 0.5,
        )
        
    lightPosition = array( [0,5,10],'f')
    def OnTimerFraction( self, event ):
        a = event.fraction() * 2 * pi
        xz = array( [
            sin(a),cos(a),
        ],'f') * 10 # radius
        self.lightPosition[0] = xz[0]
        self.lightPosition[2] = xz[1]
        self.light.location = self.lightPosition
#        print self.light.location
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()

