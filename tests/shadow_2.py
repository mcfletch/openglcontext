#! /usr/bin/env python
'''=Shadows in a Frame Buffer Object=

[shadow_2.py-screen-0001.png Screenshot]

In this tutorial, we will:

    * subclass our previous shadow tutorial code
    * use Frame Buffer Objects (FBO) to render the depth-texture
    * render to a texture larger than the screen-size

This tutorial is a minor revision of our previous shadow tutorial,
the only change is to add off-screen rendering of the depth-texture
rather than rendering on the back-buffer of the screen.
'''
import OpenGL,sys,os,traceback
#OpenGL.FULL_LOGGING = True
'''Import the previous tutorial as BaseContext'''
from shadow_1 import TestContext as BaseContext
from OpenGLContext import testingcontext
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GL.ARB.depth_texture import *
from OpenGL.GL.ARB.shadow import *
'''Import the PyOpenGL convenience wrappers for the FrameBufferObject
extension(s) we're going to use.  (Requires PyOpenGL 3.0.1b2 or above).'''
from OpenGL.GL.framebufferobjects import *

class TestContext( BaseContext ):
    """Shadow rendering tutorial code"""
    def OnInit( self ):
        """Scene set up and initial processing"""
        super( TestContext, self ).OnInit()
        '''We'll use the slightly more idiomatic "check if the entry
        point is true" way of checking for the extension.  The alternates
        in the convenience wrapper will report true if there is any
        implementation of the function.'''
        if not glBindFramebuffer:
            print 'Missing required extensions!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
        '''Decide how big our depth-texture should be...'''
        self.shadowMapSize = min(
            (
                glGetIntegerv( GL_MAX_TEXTURE_SIZE ),
                self.shadowMapSize,
            )
        )
        if self.shadowMapSize < 256:
            print 'Warning: your hardware only supports extremely small textures!'
        print 'Using shadow map of %sx%s pixels'%(
            self.shadowMapSize,self.shadowMapSize
        )
    '''We override this default in the init function.'''
    shadowMapSize = 512
    '''Should you wish to experiment with different filtering functions,
    we will parameterize the filtering operation here.'''    
    offset = 1.0
    FILTER_TYPE = GL_NEAREST
    def setupShadowContext( self,light=None, mode=None, textureKey="" ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        '''As with the previous tutorial, we want to cache our texture (and FBO),
        so we check to see if the values have already been set up.'''
        key = self.textureCacheKey+textureKey
        token = mode.cache.getData(light,key=key)
        if not token:
            '''A cache miss, so we need to do the setup.'''
            fbo = glGenFramebuffers(1)
            '''It has to be bound to configure it.'''
            glBindFramebuffer(GL_FRAMEBUFFER, fbo )
            '''The texture itself is the same as the last tutorial.  We make the 
            texture current to configure parameters.'''
            texture = glGenTextures( 1 )
            glBindTexture( GL_TEXTURE_2D, texture )
            glTexImage2D(
                GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT,
                shadowMapSize, shadowMapSize, 0,
                GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
            )
            '''We attach the texture to the FBO's depth attachment point.  There
            is also a combined depth-stencil attachment point when certain
            extensions are available.  We don't actually need a stencil buffer
            just now, so we can ignore that.

            The final argument is the "mip-map-level" of the texture,
            which currently always must be 0.
            '''
            glFramebufferTexture2D(
                GL_FRAMEBUFFER,
                GL_DEPTH_ATTACHMENT,
                GL_TEXTURE_2D,
                texture,
                0 #mip-map level...
            )
            if sys.platform in ('win32','darwin'):
                """Win32 and OS-x require that a colour buffer be bound..."""
                color = glGenRenderbuffers(1)
                glBindRenderbuffer( GL_RENDERBUFFER, color )
                glRenderbufferStorage(
                    GL_RENDERBUFFER,
                    GL_RGBA,
                    shadowMapSize,
                    shadowMapSize,
                )
                glFramebufferRenderbuffer( GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, color )
                glBindRenderbuffer( GL_RENDERBUFFER, 0 )
            glBindFramebuffer(GL_FRAMEBUFFER, 0 )
            holder = mode.cache.holder(
                light,(fbo,texture),key=key
            )
        else:
            '''We've already got the FBO with its colour buffer, just bind to
            render into it.'''
            fbo,texture = token

        '''Make the texture current to configure parameters.'''
        glBindTexture( GL_TEXTURE_2D, texture )
        '''We use the same "nearest" filtering as before.  Note, we could use an alternate 
        texture unit and leave the parameters set, this just forces the setting back on 
        each rendering pass in case some clever geometry renders using our texture.'''
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, self.FILTER_TYPE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)

        '''BUG NOTE: on AMD hardware, binding the FBO before you have unbound the 
        texture will cause heavy moire-style rendering artefacts due to undefined 
        behaviour where the FBO and the current texture are bound to the same 
        texture.  You *must* unbind the texture before you bind the FBO.'''
        glBindTexture( GL_TEXTURE_2D, 0 )
        glBindFramebuffer(GL_FRAMEBUFFER, fbo )
        
        '''Unlike in the previous tutorial, we now *know* this is a
        valid size for the viewport in the off-screen context.'''
        glViewport(0,0,shadowMapSize,shadowMapSize)

        '''Disable drawing to the colour buffers entirely.  Without this our
        framebuffer would be incomplete, as it would not have any colour buffer
        into which to render.  Note that on Win32 we would *still* be considered 
        incomplete if we didn't define a color buffer.'''
        glDrawBuffer( GL_NONE )
        '''This function in the OpenGL.GL.framebufferobjects wrapper will
        raise an OpenGL.error.GLError if the FBO is not properly configured.'''
        try:
            checkFramebufferStatus( )
        except Exception, err:
            traceback.print_exc()
            import os
            os._exit(1)
        '''Clear the depth buffer (texture) on each pass.  Our previous
        tutorial didn't need to do this here because the back-buffer was
        shared with the regular rendering pass and the OpenGLContext renderer
        had already called glClear() during it's regular context setup.
        '''
        glClear(GL_DEPTH_BUFFER_BIT)
        return texture
    def closeShadowContext( self, texture, textureKey="" ):
        """Close our shadow-rendering context/texture"""
        '''This is a very simple function now, we just disable the FBO,
        and restore the draw buffer to the regular "back" buffer.'''
        glBindFramebuffer(GL_FRAMEBUFFER, 0 )
        glDrawBuffer( GL_BACK )
        return texture

if __name__ == "__main__":
    '''Our display size is now irrelevant to our rendering algorithm, so we
    won't bother specifying a size.'''
    TestContext.ContextMainLoop(
        depthBuffer = 24,
    )
'''There are a number of possible next steps to take:

    * create cube-maps for point light sources
    * create multiple depth maps which cover successively farther "tranches"
      of the camera view frustum to produce higher-resolution shadows
    * use shaders to combine the opaque and diffuse/specular passes into a
      single rendering pass
    * use shaders to do "Percentage Closer Filtering" on the shadow-map values
      in order to antialias the shadow edges.
'''

