#! /usr/bin/env python
'''=Shadows in FrameBufferObject=

[shadow_2.py-screen-0001.png Screenshot]

In this tutorial, we will:

    * subclass our previous shadow tutorial code 
    * use Frame Buffer Objects to render the depth-texture 

This tutorial is a minor revision of our previous shadow tutorial,
the only change is to add off-screen rendering of the depth-texture 
rather than rendering on the back-buffer of the screen.
'''
import OpenGL 
from OpenGLContext import testingcontext
'''Import the previous tutorial as BaseContext'''
from shadow_2 import TestingContext as BaseContext
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GL.ARB.depth_texture import *
from OpenGL.GL.ARB.shadow import *
'''Import the OpenGL extension we're going to use'''
from OpenGL.GL.ARB.framebuffer_object import *
from OpenGLContext.arrays import (
    array, sin, cos, pi, dot, transpose,
)
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
    """Shadow rendering tutorial code"""
    def OnInit( self ):
        """Scene set up and initial processing"""
        super( TestContext, self ).OnInit()
        if not glInitFrameBufferEXT():
            print 'Missing required extensions!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
    
    shadowFBO = None 
    shadowDepth = None
    shadowTexture = None
    shadowMapSize = 1024
    def setupShadowContext( self ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        if not self.shadowFBO:
            self.shadowFBO = glGenFramebuffers(1)
        '''We bind the FBO, both to configure and to render to it...'''
        glBindFramebufferEXT(GL_FRAMEBUFFER, self.shadowFBO )
        if not self.shadowDepth:
            '''Create a new render buffer'''
            self.shadowDepth = glGenRenderbuffers(1)
            '''Make it current so we can configure it'''
            glBindRenderbuffer(GL_RENDERBUFFER, self.shadowDepth)
            '''Tell it how much memory of what type to reserve'''
            glRenderbufferStorage(
                GL_RENDERBUFFER, 
                GL_DEPTH_COMPONENT,
                shadowMapSize, 
                shadowMapSize,
            )
            '''Make it the FBO's bound (attached) depth buffer'''
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER,
                GL_DEPTH_ATTACHMENT,
                GL_RENDERBUFFER, 
                self.shadowDepth,
            )
        else:
            glBindRenderbuffer(GL_RENDERBUFFER, self.shadowDepth)
        glPushAttrib(GL_VIEWPORT_BIT)
        glViewport(0,0,shadowMapSize,shadowMapSize)
            
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
    def closeShadowContext( self, texture ):
        """Close our shadow-rendering context/texture"""
        '''This is the function that actually copies the depth-buffer into 
        the depth-texture specified.  The operation is a standard OpenGL 
        glCopyTexSubImage2D, which is performed entirely "on card", so 
        is reasonably fast, though not as fast as having rendered into an 
        FBO in the first place.'''
        glBindFramebufferEXT(GL_FRAMEBUFFER, None )

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
