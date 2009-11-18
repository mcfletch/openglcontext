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
import OpenGL,sys,os,traceback
#sys.path.insert( 0, '.')
from OpenGLContext import testingcontext
'''Import the previous tutorial as BaseContext'''
from shadow_1 import TestContext as BaseContext
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
        if not glInitFramebufferObjectARB():
            print 'Missing required extensions!'
            sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )
    
    shadowFBO = None 
    shadowDepth = None
    shadowTexture = None
    shadowMapSize = 2048
    def setupShadowContext( self ):
        """Create a shadow-rendering context/texture"""
        shadowMapSize = self.shadowMapSize
        if not self.shadowFBO:
            self.shadowFBO = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self.shadowFBO )
            self.shadowColor = glGenRenderbuffers(1)
            glBindRenderbuffer(GL_RENDERBUFFER, self.shadowColor)      
            glRenderbufferStorage(
                GL_RENDERBUFFER,
                GL_RGBA4,
                shadowMapSize,
                shadowMapSize,
            )
            glFramebufferRenderbuffer(
                GL_FRAMEBUFFER,
                GL_COLOR_ATTACHMENT0,
                GL_RENDERBUFFER,
                self.shadowColor,
            )
        else:
            '''We bind the FBO, both to configure and to render to it...'''
            glBindFramebuffer(GL_FRAMEBUFFER, self.shadowFBO )
        if not self.shadowTexture:
            texture = glGenTextures( 1 )
            glBindTexture( GL_TEXTURE_2D, texture )
            glTexImage2D( 
                GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT, 
                shadowMapSize, shadowMapSize, 0,
                GL_DEPTH_COMPONENT, GL_UNSIGNED_BYTE, None
            )
            self.shadowTexture = texture
            glFramebufferTexture2D(
                GL_FRAMEBUFFER, 
                GL_DEPTH_ATTACHMENT, 
                GL_TEXTURE_2D, 
                texture, 
                0 #mip-map level...
            )
            glBindTexture( GL_TEXTURE_2D, 0 )
        else:
            texture = self.shadowTexture
            glBindTexture( GL_TEXTURE_2D, texture )
        glPushAttrib(GL_VIEWPORT_BIT)
        '''We use the same "nearest" filtering as before'''
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP)
        '''Unlike in the previous tutorial, we now *know* this is a 
        valid size for the viewport...'''
        glViewport(0,0,shadowMapSize,shadowMapSize)
        try:
            checkFramebufferStatus( )
        except Exception, err:
            traceback.print_exc()
            os._exit( 1 )
        glBindTexture( GL_TEXTURE_2D, 0 )
        glClear(GL_DEPTH_BUFFER_BIT)
        
        return texture
    def closeShadowContext( self, texture ):
        """Close our shadow-rendering context/texture"""
        '''This is the function that actually copies the depth-buffer into 
        the depth-texture specified.  The operation is a standard OpenGL 
        glCopyTexSubImage2D, which is performed entirely "on card", so 
        is reasonably fast, though not as fast as having rendered into an 
        FBO in the first place.'''
        glBindFramebuffer(GL_FRAMEBUFFER, 0 )
        glPopAttrib(GL_VIEWPORT_BIT)
        return texture

if __name__ == "__main__":
    '''We specify a large size for the context because we need at least 
    this large a context to render our 1024x1024 depth texture.'''
    TestContext.ContextMainLoop(
        size = (1024,1024),
    )
