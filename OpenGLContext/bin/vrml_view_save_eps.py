#! /usr/bin/env python
"""EPS-saving version of the VRML-viewing demonstration

This version of the VRML-viewing demonstration functions as
a test for the (LGPL) gl2ps extension, which is not part
of the core OpenGLContext library.
"""
from OpenGLContext.bin import vrml_view
from OpenGLContext.passes import gl2psrenderpass
from OpenGL.GL import GL_RGBA
try:
    from OpenGL import gl2ps
except ImportError:
    gl2ps = None
    print """Warning: no gl2ps module loaded, this demo won't work"""

class TestContext( vrml_view.TestContext ):
    """EPS-saving testing context"""
    def OnInit( self ):
        """Load the image on initial load of the application"""
        vrml_view.TestContext.OnInit( self )
        self.addEventHandler( 'keypress', name='s', function=self.OnSave )
        print "Press 's' to save to file 'test.eps'"
    def OnSave( self, event):
        """Request to save, test the gl2ps module :) """
        filename = "test.eps"
        colorGradations = 64
        self.setCurrent()
        try:
            self.drawing = 1
            w,h = self.getViewPort()
            state = gl2ps.GL2PS_OVERFLOW
            buffsize = 0
            fh = open( filename, 'w')
            while state == gl2ps.GL2PS_OVERFLOW:
                buffsize += 1024*1024
                gl2ps.gl2psBeginPage(
                    "MyTitle",
                    "savepostscript.py",
                    (0,0,w,h),
                    gl2ps.GL2PS_EPS,
                    gl2ps.GL2PS_BSP_SORT,
                    gl2ps.GL2PS_SIMPLE_LINE_OFFSET |
                    gl2ps.GL2PS_SILENT |
                    gl2ps.GL2PS_OCCLUSION_CULL |
                    gl2ps.GL2PS_BEST_ROOT, #|
                    #gl2ps.GL2PS_NO_PS3_SHADING,
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
            else:
                print """Finished save to %(filename)s"""%locals()
        finally:
            self.drawing = None
            self.unsetCurrent()
    


if __name__ == "__main__":
    usage = """vrml_view_save_eps.py myscene.wrl

    Attempts to view the file myscene.wrl as a VRML97
    file within a shadow-casting viewer/window.
    """
    import sys
    if not sys.argv[1:2]:
        print usage
        sys.exit(1)
    TestContext.ContextMainLoop()
