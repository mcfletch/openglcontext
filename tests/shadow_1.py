#! /usr/bin/env python
'''=ARB Shadow on the Back Buffer=

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
which maps the eye-space of the camera (render pass 3) into the clip-space
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

class TestContext( BaseContext ):
    """Shadow rendering tutorial code"""
    '''We're going to get up nice and close to our geometry in the
    initial view'''
    initialPosition = (.5,1,3)

    '''=Scene Set Up=

    Our tutorial requires a number of OpenGL extensions.  We're going
    to test for these extensions using the glInit* functions.  These are
    PyOpenGL-2.x style queries which will return True if the extension is
    available.  PyOpenGL 3.x also allows you to do bool( entryPoint ) to
    check if an entry point is available, but that does not allow you to
    check for extensions which *only* define new constants.
    '''
    def OnInit( self ):
        """Initialize the context with GL active"""
        if not glInitShadowARB() or not glInitDepthTextureARB():
            print 'Missing required extensions!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        '''Configure some parameters to make for nice shadows
        at the expense of some extra calculations'''
        glHint(GL_PERSPECTIVE_CORRECTION_HINT, GL_NICEST)
        glEnable( GL_POLYGON_SMOOTH )
        '''We create the geometry for our scene in a method to allow
        later tutorials to subclass and provide more interesting scenes.
        '''
        self.geometry = self.createGeometry()
        '''To make the demo a little more interesting, we're going to
        animate the first light's position and direction.  Here we're setting
        up a raw Timer object.  OpenGLContext scenegraph timers can't be used
        as we're not using the scenegraph mechanisms.
        '''
        self.time = Timer( duration = 8.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        '''Here are the lights we're going to use to cast shadows.'''
        self.lights = self.createLights()
        self.addEventHandler( "keypress", name="s", function = self.OnToggleTimer)
    def createLights( self ):
        """Create the light's we're going to use to cast shadows"""
        '''Our first tutorial can only handle "spotlights", so we'll limit
        ourselves to those.'''
        return [
            SpotLight(
                location = [0,5,10],
                color = [1,.95,.95],
                intensity = 1,
                ambientIntensity = 0.10,
                direction = [0,-5,-10],
            ),
            SpotLight(
                location = [3,3,3],
                color = [.75,.75,1.0],
                intensity = .5,
                ambientIntensity = .05,
                direction = [-3,-3,-3],
            ),
        ]
    def createGeometry( self ):
        """Create a simple VRML scenegraph to be rendered with shadows"""
        '''This simple scene is a Teapot and a tall thin box on a flat
        box.  It's not particularly exciting, but it does let us see the
        shadows quite clearly.'''
        return Transform(
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
                            DEF = 'Tea',
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
                            DEF = 'Pole',
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
    def OnTimerFraction( self, event ):
        """Update light position/direction"""
        '''Every cycle we want to do a full rotation, and we want the
        light to be 10 units from the y axis in the x,z plane.
        All else is math.'''
        light = self.lights[0]
        a = event.fraction() * 2 * pi
        xz = array( [
            sin(a),cos(a),
        ],'f') * 10 # radius
        position = light.location
        position[0] = xz[0]
        position[2] = xz[1]
        light.location = position
        '''We point the light at the origin, mostly because it's easy.'''
        light.direction = -position
    def OnToggleTimer( self, event ):
        """Allow the user to pause/restart the timer."""
        if self.time.active:
            self.time.pause()
        else:
            self.time.resume()

    '''=Overall Rendering Process=

    OpenGLContext does a lot of "boilerplate" setup code to establish
    a perspective and model-view matrix, clear the background, and
    generally get you to a "normal 3D rendering" setup before it calls
    this method (Render).  It will *not* call this method if we have
    a scenegraph as self.sg, as then it will use to optimized "Flat"
    rendering engine.

    The overall process for the shadow rendering code looks like this:

        * for each light, render a depth-texture and calculate a texture
          matrix
        * restore the perspective and model-view matrices for the camera
        * render the scene with only ambient lighting
        * for each light, render the scene with diffuse and specular lighting
          with the depth-texture and texture matrix filtering the areas
          which are affected.

    We only want to apply this process for the "normal diffuse" rendering
    mode, not, for instance, for the mouse-selection passes or the
    transparent rendering pass (transparent shadows will have to wait for
    another tutorial).
    '''
    def Render( self, mode):
        assert mode
        BaseContext.Render( self, mode )
        if mode.visible and mode.lighting and not mode.transparent:
            '''These settings tell us we are being asked to do a
            regular opaque rendering pass (with lighting).  This is
            where we are going to do our shadow-rendering multi-pass.'''
            shadowTokens = [
                (light,self.renderLightTexture( light, mode ))
                for light in self.lights
            ]
            '''Since our depth buffer currently has the light's view rendered
            into it, we need to clear it before we render our geometry from the
            camera's viewpoint.'''
            glClear(GL_DEPTH_BUFFER_BIT)
            '''OpenGLContext's camera is represented by a "View Platform"
            this camera's view has already been set up once during this
            rendering pass, but our light-texture-rendering pass will have
            reset the matrices to match the light's perspective.

            The view platform object has a method to render the matrices
            using regular OpenGL legacy calls (the "Flat" renderer calculates
            and loads these values directly).  We just call this method to
            have the platform restore its state.  The "identity" parameter
            tells the platform to do a glLoadIdentity() call for each matrix
            first.
            '''
            platform = self.getViewPlatform()
            platform.render( identity = True )
            '''We do our ambient rendering pass.'''
            self.renderAmbient( mode )
            '''Then we do the diffuse/specular lighting for our lights.
            We want to make our "extra light" blend into the current light
            reflected from the surfaces at 1:1 ratio, so we enable blending
            before doing the diffuse/specular pass.
            '''
            glEnable(GL_BLEND)
            glBlendFunc(GL_ONE,GL_ONE)
            try:
                for i,(light,(texture,textureMatrix)) in enumerate(shadowTokens):
                    self.renderDiffuse( light, texture, textureMatrix, mode, id=i )
            finally:
                glDisable(GL_BLEND)
        else:
            '''If we are *not* doing the shadowed opaque rendering pass,
            just visit the "scenegraph" with our mode.'''
            self.drawScene( mode )
    '''Let's get the simple part out of the way first; drawing the geometry.
    OpenGLContext has two different rendering engines.  One is an
    optimized "Flat" renderer, and the other is a hierarchic "traversing"
    renderer which uses a visitor pattern to traverse the scenegraph for
    each pass.  For our purposes, this slower traversing renderer is
    sufficient, and is easily invoked.'''
    def drawScene( self, mode ):
        """Draw our scene at current animation point"""
        mode.visit( self.geometry )

    '''=Rendering Light Depth Texture=

    The depth texture is created by rendering the scene from the
    point-of-view of the light.  In this version of the tutorial,
    we'll render the depth texture into the Context's regular
    "back" buffer and then copy it into the texture.
    '''
    offset = 1.0
    def renderLightTexture( self, light, mode,direction=None, fov = None, textureKey = None ):
        """Render ourselves into a texture for the given light"""
        '''We're going to render our scene into the depth buffer,
        so we'll explicitly specify the depth operation.  The use
        of GL_LEQUAL means that we can rewrite the same geometry
        to the depth buffer multiple times and (save for floating-point
        artefacts), should see the geometry render each time.
        '''
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_DEPTH_TEST)
        '''Our setupShadowContext method will reset our viewport to match
        the size of the depth-texture we're creating.'''
        glPushAttrib(GL_VIEWPORT_BIT)
        '''We invoke our setupShadowContext method to establish the
        texture we'll use as our target.  This tutorial is just going
        to reset the viewport to a subset of the back-buffer (the regular
        rendering target for OpenGL).  Later tutorials will set up an
        off-screen rendering target (a Frame Buffer Object) by overriding
        this method-call.'''
        texture = self.setupShadowContext(light,mode)
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

            The complexity of supporting these features doesn't
            particularly suit an introductory tutorial.
        '''
        if fov:
            cutoff = fov /2.0
        else:
            cutoff = None
        lightView = light.viewMatrix(
            cutoff, near=.3, far=30.0
        )
        lightModel = light.modelMatrix( direction=direction )
        '''The texture matrix translates from camera eye-space into
        light eye-space.  See the original tutorial for an explanation
        of how the mapping is done, and how it interacts with the
        current projection matrix.

        Things to observe about the calculation of the matrix compared
        to the values in the original tutorial:

         * we are explicitly taking the transpose of the result matrix
         * the order of operations is the reverse of the calculations in
           the tutorial
         * we take the transpose of the matrix so that matrix[0] is a row
           in the sense that the tutorial uses it

        This pattern of reversing order-of-operations and taking the
        transpose happens frequently in PyOpenGL when working with matrix
        code from C sources.

        Note:

            A number of fixes to matrix multiply order came from
            comparing results with [http://www.geometrian.com/Programs.php Ian Mallett's OpenGL Library v1.4].
        '''
        textureMatrix = transpose(
            dot(
                dot( lightModel, lightView ),
                self.BIAS_MATRIX
            )
        )
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
        try:
            '''Because we *only* care about the depth buffer, we can mask
            out the color buffer entirely. We can use frustum-culling
            to only render those objects which intersect with the light's
            frustum (this is done automatically by the render-visiting code
            we use for drawing).

            Note:
                The glColorMask call does not prevent OpenGL from ever
                attempting to write to the color buffer, it just masks
                regular drawing operations.  A call to glClear() for
                instance, could still clear the colour buffer.
            '''
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
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(1.0, self.offset)
            '''Don't render front-faces, so that we avoid moire effects in 
            the rendering of shadows'''
            glCullFace(GL_FRONT)
            glEnable( GL_CULL_FACE )
            '''And now we draw our scene into the depth-buffer.'''
            self.drawScene( mode )
            '''Our closeShadowContext will copy the current depth buffer
            into our depth texture and deactivate the texture.'''
            self.closeShadowContext( texture )

            '''Return the configured texture into which we will render'''
            return texture, textureMatrix
        finally:
            '''Restore "regular" rendering...'''
            glDisable(GL_POLYGON_OFFSET_FILL)
            glShadeModel( GL_SMOOTH )
            glCullFace(GL_BACK)
            glDisable( GL_CULL_FACE )
            glColorMask( 1,1,1,1 )
            '''Now restore the viewport.'''
            glPopAttrib()
    '''The setup of the bias matrix was discussed at some length in the original
    tutorial.  In sum, the depth-buffer is going to return values in the -1 to 1
    range, while the texture has values in range 0-1.  The bias matrix simply maps
    from -1 to 1 to 0 to 1.  We multiply this by the "raw" translation matrix
    to get the final texture matrix which translates from camera eye coordinates
    to texture clip coordinates.'''
    BIAS_MATRIX = array([
        [0.5, 0.0, 0.0, 0.0],
        [0.0, 0.5, 0.0, 0.0],
        [0.0, 0.0, 0.5, 0.0],
        [0.5, 0.5, 0.5, 1.0],
    ], 'f')
    '''==Generating the Depth-Texture==

    Depth texture sizes can have a large effect on the quality
    of the shadows produced.  If your texture only has a couple of dozen
    pixels covering a particular piece of geometry then the shadows on that
    piece of geometry are going to be extremely pixelated.  This is
    particularly so if your light has a wide-angle cutoff.  As more of the
    scene is rendered into the texture, each object covers fewer pixels.
    '''
    shadowMapSize = 512
    textureCacheKey = 'shadowTexture'
    def setupShadowContext( self, light=None, mode=None ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        '''We don't want to re-generate the depth-texture for every frame,
        so we want to keep a cached version of it around.  OpenGLContext has
        an explicit caching mechanism which allows us to check and store the
        value easily.  The cache can hold different elements for a single node,
        so we use a cache key to specify that we're storing the shadow texture
        for the node.'''
        texture = mode.cache.getData(light,key=self.textureCacheKey)
        if not texture:
            '''We didn't find the texture in the cache, so we need to generate it.

            We create a single texture and tell OpenGL to make it the current
            2D texture.
            '''
            texture = glGenTextures( 1 )
            glBindTexture( GL_TEXTURE_2D, texture )
            '''The use of GL_DEPTH_COMPONENT here marks the use of the
            ARB_depth_texture extension.  The GL_DEPTH_COMPONENT constant
            tells OpenGL to use the current OpenGL bit-depth as the format
            for the texture.  So if our context has a 16-bit depth channel,
            we will use that.  If it uses 24-bit depth, we'll use that.

            The None at the end of the argument list tells OpenGL not to
            initialize the data, i.e. not to read it from anywhere.
            '''
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT,
                shadowMapSize, shadowMapSize, 0,
                GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
            )
            '''Now we store the texture in the cache for later passes.'''
            holder = mode.cache.holder( light,texture,key=self.textureCacheKey)
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
        on the machine.  We will develop the FBO-based rendering in the
        next tutorial.
        '''
        glViewport( 0,0, shadowMapSize, shadowMapSize )
        
        return texture
    def closeShadowContext( self, texture ):
        """Close our shadow-rendering context/texture"""
        '''This is the function that actually copies the depth-buffer into
        the depth-texture we've created.  The operation is a standard OpenGL
        glCopyTexSubImage2D, which is performed entirely "on card", so
        is reasonably fast, though not as fast as having rendered into an
        FBO in the first place.  We'll look at that in the next tutorial.
        '''
        shadowMapSize = self.shadowMapSize
        glBindTexture(GL_TEXTURE_2D, texture)
        glCopyTexSubImage2D(
            GL_TEXTURE_2D, 0, 0, 0, 0, 0, shadowMapSize, shadowMapSize
        )
        return texture
    '''=Render Ambient-lit Geometry=

    Our second rendering pass draws the ambient light to the scene.  It
    also fills in the depth buffer which will filter out geometry which
    is behind shadowed geometry which would otherwise "bleed through".
    '''
    def renderAmbient( self, mode ):
        """Render ambient-only lighting for geometry"""
        '''Again, we configure the mode to tell the geometry how to
        render itself.  Here we want to have almost everything save
        the diffuse lighting calculations performed.'''
        mode.visible = True
        mode.lighting = True
        mode.lightingAmbient = True
        mode.lightingDiffuse = False
        mode.textured = True
        '''As with the geometry, the light will respect the mode's
        parameters for lighting.'''
        for i,light in enumerate( self.lights ):
            light.Light( GL_LIGHT0+i, mode=mode )
        self.drawScene( mode )
    '''=Render Diffuse/Specular Lighting Filtered by Shadow Map=

    This rendering pass is where the magic of the shadow-texture algorithm
    happens.  Our process looks like this:

        * configure the GL to synthesize texture coordinates in
          eye-linear space (the camera's eye coordinate space)
        * load our texture matrix into the "eye planes" of the texture
          coordinate pipeline, there they server to transform the
          texture coordinates into the clip-space coordinates of the
          depth texture
        * configure the GL to generate an "alpha" value by comparing
          the "R" (Z) component of the generated texture coordinates
          to the Z component stored in the depth-texture.  That is,
          generate a 1.0 alpha where the camera-Z component is
          less-than-or-equal-to the depth in the depth texture.
        * configure the GL to only pass fragments where the alpha is
          greater than .99
    '''
    def renderDiffuse( self, light, texture, textureMatrix, mode, id=0 ):
        """Render lit-pass for given light"""
        '''If we were to turn *off* ambient lighting, we would find that
        our shadowed geometry would be darker whereever there happened
        to be a hole in the geometry through which light was hitting
        (the back of) the geometry.  With fully closed geometry, not
        a problem, but a problem for our Teapot object.  We could solve
        this with a blend operation which only blended brighter pixels,
        but simply re-calculating ambient lighting in this pass is about
        as simple.
        '''
        mode.lightingAmbient = False
        mode.lightingDiffuse = True
        '''Again, the light looks at the mode parameters to determine how
        to configure itself.'''
        light.Light( GL_LIGHT0 + id, mode=mode )
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
        glBindTexture(GL_TEXTURE_2D, texture)
        glEnable(GL_TEXTURE_2D)
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
        '''Accept anything as "lit" which gives this value or greater.'''
        glAlphaFunc(GL_GEQUAL, .99)
        glEnable(GL_ALPHA_TEST)
        try:
            return self.drawScene( mode )
        finally:
            '''Okay, so now we need to do cleanup and get back to a regular
            rendering mode...'''
            glDisable(GL_TEXTURE_2D)
            for _,gen_token,_ in texGenData:
                glDisable(gen_token)
            glDisable(GL_LIGHTING)
            glDisable(GL_LIGHT0+id)
            glDisable(GL_ALPHA_TEST)
            mode.lightingAmbient = True
            glTexParameteri(
                GL_TEXTURE_2D, GL_TEXTURE_COMPARE_MODE,
                GL_NONE
            )

if __name__ == "__main__":
    '''We specify a large size for the context because we need at least
    this large a context to render our depth texture.'''
    TestContext.ContextMainLoop(
        size = (512,512),
    )
