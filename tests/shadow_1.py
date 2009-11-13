#! /usr/bin/env python
'''=Shadows from Scratch=

In this tutorial, we will:

 * create basic ARB_shadow-based shadow-rendering
   * render geometry into a depth-buffer
   * use the depth-buffer to filter a multi-pass renderer

This tutorial follows roughly after this C tutorial:

    http://www.paulsprojects.net/tutorials/smt/smt.html

with alterations to work with OpenGLContext.  A number of 
fixes to matrix multiply order came from comparing results with 
Ian Mallett's OpenGL Library v1.4:

    http://www.geometrian.com/Programs.php
'''
import OpenGL 
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *
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
    
    shadowTexture = None
    shadowMapSize = 256
    def setupShadowContext( self ):
        """Create a shadow-rendering context/texture"""
        # TODO: render to a pixel-buffer-object instead, when 
        # available...
        texture = glGenTextures( 1 )
        glBindTexture( GL_TEXTURE_2D, texture )
        shadowMapSize = self.shadowMapSize
        glTexImage2D( 
            GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT, 
            shadowMapSize, shadowMapSize, 0,
            GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
        )
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)
        '''We assume here that shadowMapSize is smaller than the size 
        of the viewport.  Real world implementations would normally 
        render to a Pixel Buffer Object (off-screen render) to an 
        appropriately sized texture, regardless of screen size, falling 
        back to this implementation *only* if there was no PBO support 
        on the machine.
        '''
        glViewport( 0,0, shadowMapSize, shadowMapSize )
        return texture
    def closeShadowContext( self, texture ):
        """Close our shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        glBindTexture(GL_TEXTURE_2D, texture)
        glCopyTexSubImage2D(
            GL_TEXTURE_2D, 0, 0, 0, 0, 0, shadowMapSize, shadowMapSize
        )
        w,h = self.getViewPort()
        glViewport( 0,0,w,h)
        return texture
    
    def Render( self, mode):
        BaseContext.Render( self, mode )
        if mode.visible and mode.lighting and not mode.transparent:
            '''These settings tell us we are being asked to do a 
            regular opaque rendering pass (with lighting).  This is 
            where we are going to do our shadow-rendering multi-pass.
            
            =Rendering Geometry into a Depth Texture=
            
            '''
            glDepthFunc(GL_LEQUAL)
            glEnable(GL_DEPTH_TEST)
            
            '''We invoke our setupShadowContext method to establish the 
            texture we'll use as our target'''
            texture = self.setupShadowContext()
            '''==Setup Scene with Light as Camera==
            
            The algorithm requires us to set up the scene to render 
            from the point of view of our light.  We're going to use 
            a pair of methods on the light to do the calculations.
            These do the same calculations as "gluPerspective" for 
            the viewMatrix, and a pair of rotation,translation 
            transformations for the model-view matrix.
            
            Note: 
            
                For VRML97 scenegraphs, this wouldn't be sufficient,
                as we can have multiple lights, and lights can be children
                of arbitrary Transforms, and can appear multiple times
                within the same scenegraph.
                
                We would have to calculate the matrices for each path that 
                leads to a light, not just for each light. The node-paths 
                have methods to retrieve their matrices, so we would simply
                dot those matrices with the matrices we retrieve here.
            '''
            lightView = self.light.viewMatrix( pi/3, near=.1, far=10000.0)
            lightModel = self.light.modelMatrix( )
            '''This is a bit wasteful, as we've already loaded our 
            projection and model-view matrices for our view-platform into 
            the GL.  Real-world implementations would normally do the 
            light-rendering pass before doing their world-view setup.
            We'll restore the platform values later on.
            '''
            glMatrixMode( GL_PROJECTION )
            glLoadMatrixf( lightView )
            glMatrixMode( GL_MODELVIEW )
            glLoadMatrixf( lightModel )
            '''We want to avoid depth-buffer artefacts where the front-face 
            appears to be ever-so-slightly behind itself due to multiplication
            and transformation artefacts.  So we render the *back* of the 
            objects into the depth buffer, rather than the *front*.  This will 
            cause artefacts if there are un-closed objects in the scene,
            as we will see with our Teapot object.
            '''
            glCullFace( GL_FRONT )
            '''Because we *only* care about the depth buffer, we can set 
            a few OpenGL flags to optimize the rendering process.'''
            glShadeModel( GL_FLAT )
            glColorMask( 0,0,0,0 )
            '''We reconfigure the mode to tell the geometry to optimize its
            rendering process, for instance by disabling normal
            generation, and excluding color and texture information.'''
            mode.lighting = False 
            mode.textured = False 
            mode.visible = False

            '''==Offset Polygons to avoid Artefacts==
            
            When we render our third pass, we'll be comparing depth values 
            to those generated here.  We are rendering back-facing polygons 
            to avoid artefacts in the front-facing polygons where precision 
            of the depth-buffer causes the polygon to appear to be 
            ever-so-slightly "behind" itself when transformed via the 
            texture matrix.
            
            However, similar artefacts show up in the rendering of the 
            back-facing polygons, where the third rendering pass can wind up 
            seeing the back-facing polygons as being "in front of" themselves,
            basically declaring them to be "lit".  When the light is in front 
            of the camera and slightly to the side this results in a moire
            pattern of faint lighting on the back-facing (from the point of
            view of the light) faces.  The effect is subtle, but annoying.
            
            To avoid it, we use a polygon-offset operation.  The first 1.0
            just gives us the raw fragment depth-value, the second 1.0, the 
            parameter "units" says to take 1.0 depth-buffer units and add it 
            to the depth-value from multiplying 1.0 times the raw depth value.
            '''
            glPolygonOffset(1.0, 1.0)
            glEnable(GL_POLYGON_OFFSET_FILL) 
            '''And now we draw our scene into the depth-buffer.'''
            self.drawScene( mode )
            '''Our closeShadowContext will copy the current depth buffer into 
            our depth texture.'''
            self.closeShadowContext( texture )
            
            '''Restore "regular" rendering...'''
            glDisable(GL_POLYGON_OFFSET_FILL) 
            glCullFace( GL_BACK )
            glShadeModel( GL_SMOOTH )
            glColorMask( 1,1,1,1 )
            glClear(GL_DEPTH_BUFFER_BIT)
            '''We want to restore our view-platform's matrices, so we 
            ask it to render, restoring identity matrices before doing 
            so.'''
            platform = self.getViewPlatform()
            platform.render( identity = True )

            '''Second rendering pass, render "ambient" light into 
            the scene...'''
            mode.visible = True
            mode.lighting = True 
            mode.lightingAmbient = True 
            mode.lightingDiffuse = False 
            mode.textured = True
            self.light.Light( GL_LIGHT0, mode=mode )
            self.drawScene( mode )
            
            '''Third pass, now we do the shadow tests...
            We do *not* want ambient light added on this pass,
            but we *do* want diffuse light...'''
            mode.lightingAmbient = False
            mode.lightingDiffuse = True 
            self.light.Light( GL_LIGHT0, mode=mode )
            
            textureMatrix = transpose(
                dot(
                    dot( lightModel, lightView ),
                    BIAS_MATRIX
                )
            )
            for token,gen_token,row in [
                (GL_S,GL_TEXTURE_GEN_S,textureMatrix[0]),
                (GL_T,GL_TEXTURE_GEN_T,textureMatrix[1]),
                (GL_R,GL_TEXTURE_GEN_R,textureMatrix[2]),
                (GL_Q,GL_TEXTURE_GEN_Q,textureMatrix[3]),
            ]:
                glTexGeni(token, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR)
                glTexGenfv(token, GL_EYE_PLANE, row )
                glEnable(gen_token)
            
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
        if not glInitShadowARB() or not glInitDepthTextureARB():
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
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
            ),
        )
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        
        self.light = SpotLight(
            location = [0,5,10],
            color = [1,.5,.5],
            ambientIntensity = 0.5,
            direction = [0,-5,-10],
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
        self.light.direction = -self.lightPosition
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()

