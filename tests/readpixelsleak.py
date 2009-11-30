#! /usr/bin/env python
'''Test leak on glReadPixelsub
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import drawcube
from OpenGL.GL import *
from OpenGLContext.arrays import array, reshape
import string, time, os, sys

class TestContext( BaseContext ):
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    drawCapture = 0
    capturedImage = 0
    useStringDraw = 0
    reverseShape = 0
    def Render( self, mode = 0):
        BaseContext.Render( self, mode )
        glTranslatef(1.5,0.0,-6.0);
        glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
        drawcube.drawCube()
        width, height = self.getViewPort()
        red = glReadPixelsub(0,0, width, height,GL_RED)
        print 'refcount for array', sys.getrefcount( red )
        red = glReadPixels(0,0, width, height,GL_RED, GL_UNSIGNED_BYTE)
        print 'refcount for string', sys.getrefcount( red )

        

##		glTranslatef(-5,0.0,0);
##		drawcube.drawCube()
##
##		# draw different scene
##		pixels = glReadPixelsub(0,0, width, height,GL_RGB)
##		pixels[:,:, 0] = red
##		glDrawPixelsub(GL_RGB, pixels)
        
    def OnIdle( self, ):
        self.triggerRedraw(1)
        return 1
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.addEventHandler( 'keypress', name='s', function=self.OnSave )
        self.addEventHandler( 'keypress', name='d', function=self.OnViewUB )
        self.addEventHandler( 'keypress', name='t', function=self.OnUseStringDraw )
        self.addEventHandler( 'keypress', name='r', function=self.OnReverseShape )
    def OnSave( self, event):
        self.SaveTo( 'test.jpg' )
    def SaveTo( self, filename, format="JPEG" ):
        try:
            from PIL import Image # get PIL's functionality...
        except ImportError, err:
            # old style?
            import Image
        width, height = self.getViewPort()
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        data = glReadPixelsub(0, 0, width, height, GL_RGB)
        assert data.shape == (width,height,3), """Got back array of shape %r, expected %r"""%(
            data.shape,
            (width,height,3),
        )
        image = Image.fromstring( "RGB", (width, height), data.tostring() )
        image = image.transpose( Image.FLIP_TOP_BOTTOM)
        image.save( filename, format )
        print 'Saved image to %s'% (os.path.abspath( filename))
        return image
    def SaveToUB( self ):
        try:
            from PIL import Image # get PIL's functionality...
        except ImportError, err:
            # old style?
            import Image
        width, height = self.getViewPort()
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        data = glReadPixelsub(0, 0, width, height, GL_RGB)
        assert data.shape == (width,height,3), """Got back array of shape %r, expected %r"""%(
            data.shape,
            (width,height,3),
        )
        string = data.tostring()
        print 'array returned was', data.shape
        if self.reverseShape:
            data.shape = (height,width,3)
            print 'reversed shape', data.shape
        assert data.tostring() == string, """Data stored differs in format"""
        self.capturedImage = data
        self.capturedSize = (width,height,3)
    def OnViewUB( self, event ):
        """Trigger viewing of saved data-set"""
        self.SaveToUB( )
        self.drawCapture = not self.drawCapture
    def OnUseStringDraw( self, event ):
        """Trigger use of string drawing for display of captured"""
        self.useStringDraw = not self.useStringDraw
    def OnReverseShape( self, event ):
        self.reverseShape = not self.reverseShape

if __name__ == "__main__":
    print 'Press "s" to save the buffer to the file test.jpg'
    TestContext.ContextMainLoop()
