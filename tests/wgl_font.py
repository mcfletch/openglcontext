'''Test of text objects with fontprovider
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.text import wglfontprovider, fontprovider

TESTINGTEXT = """Hello world!
\tWhat's up?
Where are you going?
""" + "".join([unichr(o) for o in range(ord('z')+1,256)])

class TestContext( BaseContext ):
    font = None
    font2 = None
    def OnInit(self):
        """Create the font for use later"""
        self.style = FontStyle(
            family = ["Times New Roman", "SANS"],
            style = "BOLD",
            size = 2.0,
            spacing = 1.0,
            justify = "RIGHT",
            format = 'polygon',
        )
        provider, font = fontprovider.FontProvider.getProviderFont( self.style )
        self.style2 = FontStyle(
            family = ["Times New Roman", "SANS"],
            style = "BOLD",
            size = 2.0,
            spacing = 1.0,
            justify = "RIGHT",
            format = 'bitmap',
        )
        self.font = font
        provider, font = fontprovider.FontProvider.getProviderFont( self.style2 )
        self.font2 = font
    def Render( self, mode ):
        """Render the text for this mode"""
        BaseContext.Render( self, mode )
        if self.font and self.font2:
            if mode.passCount == 0:
                glClearColor(0.0,0.0,1.0,1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )
            if mode.visible:
                glDisable(GL_LIGHTING)
                self.font.render( TESTINGTEXT, mode=mode)
                glTranslate( 2,3,0)
                self.font2.render( "Hello World!", mode=mode )
            

if __name__ == "__main__":
    TestContext.ContextMainLoop()

