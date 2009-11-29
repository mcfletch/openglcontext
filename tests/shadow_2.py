#! /usr/bin/env python
'''=Shadows in a Frame Buffer Object=

[shadow_2.py-screen-0001.png Screenshot]

In this tutorial, we will:

    * subclass our previous shadow tutorial code 
    * use Frame Buffer Objects (FBO) to render the depth-texture 
    * render to a larger texture than the screen-size

This tutorial is a minor revision of our previous shadow tutorial,
the only change is to add off-screen rendering of the depth-texture 
rather than rendering on the back-buffer of the screen.
'''
import OpenGL,sys,os,traceback
from OpenGLContext import testingcontext
'''Import the previous tutorial as BaseContext'''
from shadow_1 import TestContext as BaseContext
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GL.ARB.depth_texture import *
from OpenGL.GL.ARB.shadow import *
'''Import the PyOpenGL convenience wrappers for the FrameBufferObject
extension(s) we're going to use.  (Requires PyOpenGL 3.0.1b2 or above).'''
from OpenGL.GL.framebufferobjects import *
from OpenGLContext.arrays import (
    array, sin, cos, pi, dot, transpose,
)

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
                2048,
            )
        )
        if self.shadowMapSize < 256:
            print 'Warning: your hardware only supports extremely small textures!'
        print 'Using shadow map of %sx%s pixels'%( 
            self.shadowMapSize,self.shadowMapSize 
        )
    '''As before, we want to store our depth-texture between rendering 
    passes.  The new item is the FrameBufferObject which represents the 
    off-screen context into which we will be rendering.'''
    shadowFBO = None 
    shadowTexture = None
    '''We override this default in the init function.'''
    shadowMapSize = 2048
    '''Should you wish to experiment with different filtering functions,
    we'll parameterize the filtering operation here.'''
    FILTER_TYPE = GL_NEAREST 
    def setupShadowContext( self,light=None, mode=None ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        if not self.shadowFBO:
            '''Creating FBOs is expensive, so we want to create and configure 
            our FBO once and reuse it.'''
            self.shadowFBO = glGenFramebuffers(1)
            '''It has to be bound to configure it.'''
            glBindFramebuffer(GL_FRAMEBUFFER, self.shadowFBO )
        else:
            '''We've already got the FBO with its colour buffer, just bind to 
            render into it.'''
            glBindFramebuffer(GL_FRAMEBUFFER, self.shadowFBO )
        if not self.shadowTexture:
            '''The texture itself is the same as the last tutorial.'''
            texture = glGenTextures( 1 )
            glBindTexture( GL_TEXTURE_2D, texture )
            glTexImage2D( 
                GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT, 
                shadowMapSize, shadowMapSize, 0,
                GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
            )
            self.shadowTexture = texture
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
        else:
            '''Just make the texture current to configure parameters.'''
            texture = self.shadowTexture
            glBindTexture( GL_TEXTURE_2D, texture )
        glPushAttrib(GL_VIEWPORT_BIT)
        '''Unlike in the previous tutorial, we now *know* this is a 
        valid size for the viewport in the off-screen context.'''
        glViewport(0,0,shadowMapSize,shadowMapSize)
        '''We use the same "nearest" filtering as before'''
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, self.FILTER_TYPE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)
        
        '''Disable drawing to the colour buffers entirely.  Without this our 
        framebuffer would be incomplete, as it would not have any colour buffer 
        into which to render.'''
        glDrawBuffer( GL_NONE )
        '''This function in the OpenGL.GL.framebufferobjects wrapper will 
        raise an OpenGL.error.GLError if the FBO is not properly configured.'''
        try:
            checkFramebufferStatus( )
        except Exception, err:
            traceback.print_exc()
            import os
            os._exit(1)
        '''Un-bind the texture so that regular rendering isn't trying to 
        lookup a texture in our depth-buffer-bound texture.'''
        glBindTexture( GL_TEXTURE_2D, 0 )
        '''Clear the depth buffer (texture) on each pass.'''
        glClear(GL_DEPTH_BUFFER_BIT)
        return texture
    def closeShadowContext( self, texture ):
        """Close our shadow-rendering context/texture"""
        '''This is a very simple function now, we just disable the FBO,
        and restore the viewport.'''
        glBindFramebuffer(GL_FRAMEBUFFER, 0 )
        glPopAttrib(GL_VIEWPORT_BIT)
        glDrawBuffer( GL_BACK )
        return texture

if __name__ == "__main__":
    '''Our display size is now irrelevant to our rendering algorithm, so we 
    won't bother specifying a size.'''
    TestContext.ContextMainLoop(
        depthBuffer = 24,
    )
