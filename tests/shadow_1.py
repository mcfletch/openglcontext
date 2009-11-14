#! /usr/bin/env python
'''=Shadows with ARB Shadow=

[shadow_1.py-screen-0001.png Screenshot]

In this tutorial, we will:

    * setup basic ARB_shadow-based shadow-rendering
    * render geometry into the "back buffer" depth-buffer
    * copy the depth-buffer into a depth-texture image
    * use the depth-texture to filter a multi-pass renderer

The ARB Shadow extension allows you to use a "depth-texture"
(provided by the ARB_depth_texture extension) as a lookup table 
to filter your rendering passes in such a way as to simulate 
shadows.

The shadowed render operates in three passes for a single light,
with an extra 2 passes for each extra shadow-casting light you 
would like to add.  However, while we do not do it within this 
tutorial, you can cache partial solutions for first rendering pass 
so that you only need to render "non-static" geometry again for 
each rendering pass (though this requires an extra depth texture).

The process works as follows:

    * render your scene from the point-of-view of your light with just 
        the depth-buffer being updated
    * copy the depth-buffer into a depth texture as a lookup table
    * render your scene with just ambient light 
    * render your scene with diffuse/specular light using the lookup 
        table and a per-fragment alpha filter to determine which fragments 
        are "shadowed"

Most confusion during the process comes during the creation of a matrix 
which maps the eye-space of the camera (render pass 3) into the eye-space 
of the light (render pass 1).  The actual calculations are simple, but 
knowing in which order to combine the matrices can be confusing.

This tutorial follows roughly after [http://www.paulsprojects.net/tutorials/smt/smt.html this C tutorial] 
with alterations to work with OpenGLContext and a few different 
choices with regard to attempts to minimize artefacts in the shadows.
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
    array, sin, cos, pi, dot, transpose,
)
from OpenGLContext.events.timer import Timer

BIAS_MATRIX = array([
    [0.5, 0.0, 0.0, 0.0],
    [0.0, 0.5, 0.0, 0.0],
    [0.0, 0.0, 0.5, 0.0],
    [0.5, 0.5, 0.5, 1.0],
], 'f')

class TestContext( BaseContext ):
    """Shadow rendering tutorial code"""
    '''We're going to get up nice and close to our geometry in the 
    initial view'''
    initialPosition = (.5,1,3)
    def OnInit( self ):
        """Scene set up and initial processing"""
        '''We test for the two extensions, though we are actually using 
        the core entry points (constants) throughout.'''
        if not glInitShadowARB() or not glInitDepthTextureARB():
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        '''This simple scene is a Teapot and a tall thin box on a flat 
        box.  It's not particularly exciting, but it does let us see the 
        shadows quite clearly.'''
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
        '''To make the demo a little more interesting, we're going to 
        animate the light's position and direction.  Here we're setting up 
        a raw Timer object.  OpenGLContext scenegraph timers can't be used 
        as we're not using the scenegraph mechanisms.
        '''
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        '''Here's the light we're going to use to cast the shadows.'''
        self.light = SpotLight(
            location = [0,5,10],
            color = [1,.5,.5],
            ambientIntensity = 0.5,
            direction = [0,-5,-10],
        )
        
    def OnTimerFraction( self, event ):
        """Update light position/direction"""
        '''Every cycle we want to do a full rotation, and we want the 
        light to be 10 units from the y axis in the x,z plane. 
        All else is math.'''
        a = event.fraction() * 2 * pi
        xz = array( [
            sin(a),cos(a),
        ],'f') * 10 # radius
        position = self.light.location
        position[0] = xz[0]
        position[2] = xz[1]
        self.light.location = position
        '''We point the light at the origin, mostly because it's easy.'''
        self.light.direction = -position
    
    def drawScene( self, mode ):
        """Draw our scene at current animation point"""
        '''Because we are not using a scenegraph, our "mode" object is one
        of the older multi-pass (non-flat) rendering modes.  This has the 
        advantage of being able to render arbitrary geometry recursively,
        though it is slower than the flat rendering modes for larger 
        scenegraphs.
        '''
        mode.visit( self.geometry )
    
    '''=Setting up the Depth Texture=
    
    The depth texture is a specialized form of floating-point texture 
    which can be used as a lookup table.  The specialization is that the 
    GL will lookup the *current* bit-depth of the depth buffer when creating 
    the texture, so you can use a depth texture without needing to figure 
    out in which format your depth texture happens to be.
    
    Depth texture sizes can have an extremely large effect on the quality 
    of the shadows produced.  If your texture only has a couple of dozen 
    pixels covering a particular piece of geometry then the shadows on that 
    piece of geometry are going to be extremely pixelated.  This is
    particularly so if your light has a wide-angle cutoff, as the more of the 
    scene that is rendered into the texture, the smaller each object appears 
    in the buffer.
    '''
    shadowTexture = None
    shadowMapSize = 1024
    def setupShadowContext( self ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        if not self.shadowTexture:
            '''We create a single texture and tell OpenGL 
            its data-format parameters.  The None at the end of the 
            argument list tells OpenGL not to initialize the data, i.e. 
            not to read it from anywhere.
            '''
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
        '''These parameters simply keep us from doing interpolation on the 
        data-values for the texture.  If we were to use, for instance 
        GL_LINEAR interpolation, our shadows would tend to get "moire" 
        patterns.  The cutoff threshold for the shadow would get crossed 
        halfway across each shadow-map texel as the neighbouring pixels'
        values were blended.'''
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
    
    def Render( self, mode):
        BaseContext.Render( self, mode )
        if mode.visible and mode.lighting and not mode.transparent:
            '''These settings tell us we are being asked to do a 
            regular opaque rendering pass (with lighting).  This is 
            where we are going to do our shadow-rendering multi-pass.
            
            =Rendering Geometry into a Depth Texture=
            
            We're going to render our scene into the depth buffer,
            so we'll explicitly specify the depth operation.  The use 
            of GL_LEQUAL means that we can rewrite the same geometry 
            to the depth buffer multiple times and (save for floating-point 
            artefacts), should see the geometry render each time.
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
            '''Because we *only* care about the depth buffer, we can mask 
            out the color buffer entirely.'''
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
            depth-buffer units and add it to the depth-value 
            from the previous step, making the depth buffer record values 
            1.0 units less than the geometry's natural value.
            '''
            # glCullFace( GL_BACK ) # Original tutorial approach...
            glPolygonOffset(1.0, 1.0)
            glEnable(GL_POLYGON_OFFSET_FILL) 
            '''And now we draw our scene into the depth-buffer.'''
            self.drawScene( mode )
            '''Our closeShadowContext will copy the current depth buffer 
            into our depth texture and deactivate the texture.'''
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
            '''=Render Diffuse/Specular Lighting Filtered by Shadow Map=
            
            If we were to turn *off* ambient lighting, we would find that 
            our shadowed geometry would be darker whereever there happened
            to be a hole in the geometry through which light was hitting 
            (the back of) the geometry.  With fully closed geometry, not 
            a problem, but a problem for our Teapot object.  We could solve 
            this with a blend operation which only blended brighter pixels,
            but simply re-calculating ambient lighting in this pass is about 
            as simple.
            '''
            mode.lightingAmbient = True
            mode.lightingDiffuse = True 
            self.light.Light( GL_LIGHT0, mode=mode )
            '''The texture matrix translates from camera eye-space into 
            light eye-space.  See the original tutorial for an explanation 
            of how the mapping is done, and how it interacts with the 
            current projection matrix.
            
            Note:
                A number of fixes to matrix multiply order came from 
                comparing results with [http://www.geometrian.com/Programs.php Ian Mallett's OpenGL Library v1.4].
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
                translation matrix.  We're going to generate texture 
                coordinates that are linear in the eye-space of the 
                camera and then transform them with the eye-planes 
                into texture-lookups within the depth-texture.'''
                glTexGeni(token, GL_TEXTURE_GEN_MODE, GL_EYE_LINEAR)
                glTexGenfv(token, GL_EYE_PLANE, row )
                glEnable(gen_token)
            '''Now enable our light's depth-texture, created above.'''
            glBindTexture(GL_TEXTURE_2D, texture);
            glEnable(GL_TEXTURE_2D);
            '''Enable shadow comparison.  "R" here is not "red", but 
            the third of 4 texture coordinates, i.e. the transformed 
            Z-depth of the generated texture coordinate, now in eye-space 
            of the light.'''
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
            '''I don't see any real reason to prefer ALPHA versus 
            INTENSITY for the generated values, but I like the symetry 
            of using glAlphaFunc with Alpha values.  The original tutorial 
            used intensity values, however, so there may be some subtle 
            reason to use them.'''
            glTexParameteri(
                GL_TEXTURE_2D, GL_DEPTH_TEXTURE_MODE, GL_ALPHA
            )
            '''Accept anything as "lit" which gives this value.'''
            glAlphaFunc(GL_EQUAL, 1.0)
            glEnable(GL_ALPHA_TEST)
            
            self.drawScene( mode )
            '''Okay, so now we need to do cleanup and get back to a regular 
            rendering mode...'''
            glDisable(GL_TEXTURE_2D)
            for _,gen_token,_ in texGenData:
                glDisable(gen_token)
            glDisable(GL_LIGHTING);
            glDisable(GL_ALPHA_TEST);            
            mode.lightingAmbient = True 
        else:
            '''If we are *not* doing the shadowed opaque rendering pass,
            just visit the "scenegraph" with our mode.'''
            self.drawScene( mode )
        
    def closeShadowContext( self, texture ):
        """Close our shadow-rendering context/texture"""
        '''This is the function that actually copies the depth-buffer into 
        the depth-texture specified.  The operation is a standard OpenGL 
        glCopyTexSubImage2D, which is performed entirely "on card", so 
        is reasonably fast, though not as fast as having rendered into an 
        FBO in the first place.'''
        shadowMapSize = self.shadowMapSize
        glBindTexture(GL_TEXTURE_2D, texture)
        glCopyTexSubImage2D(
            GL_TEXTURE_2D, 0, 0, 0, 0, 0, shadowMapSize, shadowMapSize
        )
        w,h = self.getViewPort()
        glViewport( 0,0,w,h)
        glDisable( GL_TEXTURE_2D )
        return texture

if __name__ == "__main__":
    '''We specify a large size for the context because we need at least 
    this large a context to render our 1024x1024 depth texture.'''
    TestContext.ContextMainLoop(
        size = (1024,1024),
    )
