#! /usr/bin/env python
'''=Shadows in FrameBufferObject=

[shadow_2.py-screen-0001.png Screenshot]

In this tutorial, we will:

    * subclass our previous shadow tutorial code 
    * use Frame Buffer Objects to render the depth-texture 
    * render to a larger texture than the screen-size

This tutorial is a minor revision of our previous shadow tutorial,
the only change is to add off-screen rendering of the depth-texture 
rather than rendering on the back-buffer of the screen.
'''
import OpenGL,sys,os,traceback
from OpenGLContext import testingcontext
'''Import the previous tutorial as BaseContext'''
from shadow_1 import TestContext as BaseContext
from OpenGLContext.scenegraph.basenodes import *
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
from OpenGLContext.events.timer import Timer

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
    shadowColor = None
    shadowTexture = None
    '''We override this default in the init function.'''
    shadowMapSize = 2048
    '''Should you wish to experiment with different filtering functions,
    we'll parameterize the filtering operation here.'''
    FILTER_TYPE = GL_NEAREST 
    def setupShadowContext( self ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        if not self.shadowFBO:
            '''Creating FBOs is expensive, so we want to create and configure 
            our FBO once and reuse it.'''
            self.shadowFBO = glGenFramebuffers(1)
            '''It has to be bound to configure it.'''
            glBindFramebuffer(GL_FRAMEBUFFER, self.shadowFBO )
            '''The creation of a colour render buffer would not seem to be 
            necessary, after all, we are filtering out all of the colour-buffer 
            updates.  Unfortunately, at least on ATI's 3xxx series, it seems 
            there must be a colour buffer even if there are no updates to it.
            '''
            self.shadowColor = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.shadowColor)
            '''We are not going to actually use the buffer, so rather than 
            rendering to a texture, we'll just allocate the storage on the 
            back-end.  Note that if we *did* need to access the values,
            we *could* do a glCopyTexSubImage2D as we did in the previous
            tutorial, but that would obviate much of  the value of the FBO
            approach.  What it *would* do is allow us to use a 
            Multisampling buffer.  If you want to do antialiased off-screen 
            rendering you'll likely need that approach.
            
            Interestingly (annoyingly), the ARB spec states that the format can 
            only be one of a very limited set of formats, but the spec'd color 
            format isn't actually supported on nVidia hardware. The GL_RGBA
            value does appear to be supported on both ATI and nVidia hardware.
            '''
            glRenderbufferStorage(
                GL_RENDERBUFFER,
                GL_RGBA,
                shadowMapSize,
                shadowMapSize,
            )
            '''Now we attach our newly-created colour buffer to the FBO object,
            which makes it the (first) colour rendering buffer for the virtual
            context the FBO represents.  As noted above, while it wouldn't seem 
            necessary, real-world tests suggest that there always needs to be 
            at least one colour-buffer attached.'''
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER,
                GL_COLOR_ATTACHMENT0,
                GL_RENDERBUFFER,
                self.shadowColor,
            )
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
        '''This function in the OpenGL.GL.framebufferobjects wrapper will 
        raise an OpenGL.error.GLError if the FBO is not properly configured.'''
        checkFramebufferStatus( )
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
        return texture

if __name__ == "__main__":
    '''Our display size is now irrelevant to our rendering algorithm, so we 
    won't bother specifying a size.'''
    TestContext.ContextMainLoop()
