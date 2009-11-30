'''Low-level WGL bitmap fonts test (broken)

We don't have a mechanism for extracting metrics from
the bitmap fonts under WGL, so this test produces garbage
rendering, as it can't guess how large the lines should
be.
'''
import _bitmap_font, _fontstyles
from OpenGLContext.scenegraph.text import wglfont

class TestContext( _bitmap_font.TestContext ):
    
    testingClass = wglfont.WGLBitmapFont
if __name__ == "__main__":
    TestContext.ContextMainLoop()