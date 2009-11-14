#! /usr/bin/env python
'''=Shadows from Scratch=

In this tutorial, we will:

    * setup basic ARB_shadow-based shadow-rendering
    * render geometry into the "back buffer" depth-buffer
    * copy the depth-buffer into a depth-texture image
    * use the depth-texture to filter a multi-pass renderer

This tutorial follows roughly after this C tutorial:

    http://www.paulsprojects.net/tutorials/smt/smt.html

with alterations to work with OpenGLContext.  A number of 
fixes to matrix multiply order came from comparing results with 
Ian Mallett's OpenGL Library v1.4:

    http://www.geometrian.com/Programs.php
'''
import OpenGL 
#OpenGL.FULL_LOGGING = True
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
    initialPosition = (.5,1,3)
    
    sceneList = None
    
    def drawScene( self, mode ):
        """Draw our scene at current animation point"""
        mode.visit( self.geometry )
        #self.shape.Render( mode )
    
    shadowTexture = None
    shadowMapSize = 1024
    def setupShadowContext( self ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        if not self.shadowTexture:
            texture = glGenTextures( 1 )
            glBindTexture( GL_TEXTURE_2D, texture )
            glTexImage2D( 
                GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT, 
                shadowMapSize, shadowMapSize, 0,
                GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
            )
            self.shadowTexture = texture
        else:
            texture = self.shadowTexture
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)
        '''We assume here that shadowMapSize is smaller than the size 
        of the viewport.  Real world implementations would normally 
        render to a Frame Buffer Object (off-screen render) to an 
        appropriately sized texture, regardless of screen size, falling 
        back to this implementation *only* if there was no FBO support 
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
            lightView = self.light.viewMatrix( 
                pi/3, near=.3, far=100.0
            )
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
            #glCullFace( GL_FRONT )
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
            
            We want to avoid depth-buffer artefacts where the front-face 
            appears to be ever-so-slightly behind itself due to multiplication
            and transformation artefacts.  The original tutorial uses 
            rendering of the *back* faces of objects into the depth buffer,
            but with "open" geometry such as the Utah Teapot, we wind up with 
            nasty artefacts where e.g. the area on the body around the spout 
            isn't shadowed because there's no back-faces in front of it.
            
            Even with the original approach, using a polygon offset will tend 
            to avoid "moire" effects in the shadows where precision issues 
            cause the depths in the buffer to pass back and forth across the 
            LEQUAL threshold as they cross the surface of the object.
            
            To avoid these problems, we use a polygon-offset operation.  
            The first 1.0 gives us the raw fragment depth-value, the 
            second 1.0, the parameter "units" says to take 1.0 
            depth-buffer units and subtract it from the depth-value 
            from the previous step.
            '''
            # glCullFace( GL_BACK ) # Original tutorial approach...
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
            '''We want to restore our view-platform's matrices, so we 
            ask it to render, restoring identity matrices before doing 
            so.'''
            platform = self.getViewPlatform()
            platform.render( identity = True )
            
            '''=Render Ambient-lit Geometry=
            
            Our geometry will be written with two passes, the first will 
            write all geometry with "ambient" light only.  The second will 
            write "direct" (diffuse) light filtered by the depth texture.
            
            Since our depth buffer currently has the camera's view rendered 
            into it, we need to clear it.
            '''
            glClear(GL_DEPTH_BUFFER_BIT)
            '''Again, we configure the mode to tell the geometry how to 
            render itself.  Here we want to have almost everything save 
            the diffuse lighting calculations performed.'''
            mode.visible = True
            mode.lighting = True 
            mode.lightingAmbient = True 
            mode.lightingDiffuse = False 
            mode.textured = True
            self.light.Light( GL_LIGHT0, mode=mode )
            self.drawScene( mode )
            
            '''=Render Diffuse Lighting Filtered by Shadow Map=
            
            We do *not* want ambient light added on this pass,
            but we *do* want diffuse light, so we configure the mode.
            '''
            mode.lightingAmbient = True
            mode.lightingDiffuse = True 
            self.light.Light( GL_LIGHT0, mode=mode )
            '''The texture matrix translates from camera eye-space into 
            light eye-space.  See the original tutorial for an explanation 
            of how the mapping is done, and how it interacts with the 
            current projection matrix.
            '''
            textureMatrix = transpose(
                dot(
                    dot( lightModel, lightView ),
                    BIAS_MATRIX
                )
            )
            texGenData = [
                (GL_S,GL_TEXTURE_GEN_S,textureMatrix[0]),
                (GL_T,GL_TEXTURE_GEN_T,textureMatrix[1]),
                (GL_R,GL_TEXTURE_GEN_R,textureMatrix[2]),
                (GL_Q,GL_TEXTURE_GEN_Q,textureMatrix[3]),
            ]
            for token,gen_token,row in texGenData:
                '''We want to generate coordinates as a linear mapping 
                with each "eye plane" corresponding to a row of our 
                translation matrix.'''
                glTexGeni(token, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR)
                glTexGenfv(token, GL_EYE_PLANE, row )
                glEnable(gen_token)
            '''Now use our light's depth-texture, created above.'''
            glBindTexture(GL_TEXTURE_2D, texture);
            glEnable(GL_TEXTURE_2D);
            '''Enable shadow comparison.  "R" here is not "red", but 
            the third of 4 texture coordinates, i.e. the transformed 
            Z-depth of the coordinate, as we saw in texGenData above.'''
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE,
                GL_COMPARE_R_TO_TEXTURE
            )
            '''Shadow comparison should be true (ie not in shadow) 
            if R <= value stored in the texture.  That is, if the 
            eye-space Z coordinate multiplied by our transformation 
            matrix is at a lower depth (closer) than the depth value 
            stored in the texture, then that coordinate is "in the light".
            '''
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_COMPARE_FUNC, GL_LEQUAL
            )
            '''Shadow comparison should generate an INTENSITY result.'''
            glTexParameteri(
                GL_TEXTURE_2D, GL_DEPTH_TEXTURE_MODE, GL_INTENSITY
            )
            '''Accept anything as "lit" which gives this value.'''
            glAlphaFunc(GL_EQUAL, 1.0)
            glEnable(GL_ALPHA_TEST)
            
            self.drawScene( mode )
            
            glDisable(GL_TEXTURE_2D)
            for _,gen_token,_ in texGenData:
                glDisable(gen_token)
            glDisable(GL_LIGHTING);
            glDisable(GL_ALPHA_TEST);            
            '''Just to be sure, set the ambient light setting back to 
            its previous value for the mode.'''
            mode.lightingAmbient = True 
        else:
            self.drawScene( mode )
        
    def OnInit( self ):
        """Scene set up and initial processing"""
        if not glInitShadowARB() or not glInitDepthTextureARB():
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        self.shape = Teapot( size=.5 )
        self.geometry = Transform(
            children = [
                Transform(
                    translation = (0,-.38,0),
                    children = [
                        Shape(
                            DEF = 'Floor',
                            geometry = Box( size=(5,.05,5)),
                            appearance = Appearance( material=Material(
                                diffuseColor = (.7,.7,.7),
                                shininess = .8,
                                ambientIntensity = .1,
                            )),
                        ),
                    ],
                ),
                Transform( 
                    translation = (0,0,0),
                    children = [
                        Shape(
                            geometry = Teapot( size = .5 ),
                            appearance = Appearance(
                                material = Material(
                                    diffuseColor =( .5,1.0,.5 ),
                                    ambientIntensity = .2,
                                    shininess = .5,
                                ),
                            ),
                        )
                    ],
                ),
                Transform( 
                    translation = (2,3.62,0),
                    children = [
                        Shape(
                            geometry = Box( size=(.1,8,.1) ),
                            appearance = Appearance(
                                material = Material(
                                    diffuseColor =( 1.0,0,0 ),
                                    ambientIntensity = .4,
                                    shininess = 0.0,
                                ),
                            ),
                        )
                    ],
                ),
            ],
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
    TestContext.ContextMainLoop(
        size = (1024,1024),
    )

