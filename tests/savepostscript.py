#! /usr/bin/env python
'''Demo of saving vector images from PyOpenGL using gl2ps
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import drawcube
from OpenGLContext.passes import gl2psrenderpass
from OpenGL.GL import *
from OpenGLContext.arrays import array, reshape
import string, time, os
try:
    from OpenGL import gl2ps
except ImportError:
    gl2ps = None
    print """Warning: no gl2ps module loaded, this demo won't work"""

class TestContext( BaseContext ):
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.addEventHandler( 'keypress', name='s', function=self.OnSave )
    def OnSave( self, event):
        """Request to save, test the gl2ps module :) """
        self.setCurrent()
        self.drawing = 1
        try:
            state = gl2ps.GL2PS_OVERFLOW
            buffsize = 0
            w,h = self.getViewPort()
            colorGradations = 16
            fh = open( "test.eps", 'w')
            while state == gl2ps.GL2PS_OVERFLOW:
                buffsize += 1024*1024
                gl2ps.gl2psBeginPage(
                    "MyTitle",
                    "savepostscript.py",
                    (0,0,w,h),
                    gl2ps.GL2PS_EPS,
                    gl2ps.GL2PS_SIMPLE_SORT,
                    gl2ps.GL2PS_SIMPLE_LINE_OFFSET |
                    gl2ps.GL2PS_SILENT |
                    gl2ps.GL2PS_OCCLUSION_CULL |
                    gl2ps.GL2PS_BEST_ROOT |
                    gl2ps.GL2PS_NO_PS3_SHADING,
                    GL_RGBA,
                    0,
                    None,
                    colorGradations, colorGradations, colorGradations,
                    buffsize,
                    fh,
                    "MyTitle",
                )
                try:
                    visibleChange = gl2psrenderpass.defaultRenderPasses( self )
                finally:
                    state = gl2ps.gl2psEndPage()
            if state != gl2ps.GL2PS_SUCCESS:
                if state == gl2ps.GL2PS_WARNING:
                    print """There were warnings generated during export"""
                elif state == gl2ps.GL2PS_ERROR:
                    print """There were errors during export"""
                elif state == gl2ps.GL2PS_NO_FEEDBACK:
                    print """There was nothing drawn, though export succeeded"""
                else:
                    print """Unknown final state""", state
        finally:
            self.drawing = None
            self.unsetCurrent()
    

if __name__ == "__main__":
    print 'Press "s" to save the buffer to the file test.eps'
    TestContext.ContextMainLoop()
