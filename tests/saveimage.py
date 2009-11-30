#! /usr/bin/env python
'''Demo of saving images from PyOpenGL using PIL
'''
import OpenGL
OpenGL.UNSIGNED_BYTE_IMAGES_AS_STRING = False
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import drawcube
from OpenGLContext.scenegraph import imagetexture
from OpenGL.GL import *
from OpenGLContext.arrays import array, reshape, nonzero, ravel, amin,amax
import string, time, os

class TestContext( BaseContext ):
    initialPosition = (0,0,0) # set initial camera position, tutorial does the re-positioning
    drawCapture = 0
    capturedImage = ()
    useStringDraw = 0
    reverseShape = 0
    capturedImageFormat = GL_RGB
    typedFunction = True
    def Render( self, mode):
        BaseContext.Render( self, mode )
        if self.drawCapture and len(self.capturedImage):
            if self.useStringDraw:
                glDrawPixels( 
                    self.capturedSize[0], 
                    self.capturedSize[1], 
                    self.capturedImageFormat, GL_UNSIGNED_BYTE, 
                    self.capturedImage.tostring() 
                )
            else:
                glDrawPixelsub( self.capturedImageFormat, self.capturedImage )
        else:
            glTranslatef(
                1.5,0.0,
                #-((time.time()%2)*25)-6.0
                -6.0,
            )
            glRotated( time.time()%(8.0)/8 * -360, 1,0,0)
            self.texture.render(mode=mode)
            drawcube.drawCube()
            self.texture.renderPost(mode=mode)
    def OnIdle( self, ):
        self.triggerRedraw(1)
        return 1
    def OnInit( self ):
        """Load the image on initial load of the application"""
        self.texture = imagetexture.ImageTexture( url = ["nehe_wall.bmp"] )
        self.addEventHandler( 'keypress', name='c', function=self.OnCaptureColour )
        self.addEventHandler( 'keypress', name='d', function=self.OnCaptureDepth )
        self.addEventHandler( 'keypress', name='v', function=self.OnViewCapture )
        self.addEventHandler( 'keypress', name='s', function=self.OnSave )
        self.addEventHandler( 'keypress', name='t', function=self.OnUseStringDraw )
        self.addEventHandler( 'keypress', name='r', function=self.OnCapture1Colour )
        self.addEventHandler( 'keypress', name='g', function=self.OnCapture1Colour )
        self.addEventHandler( 'keypress', name='b', function=self.OnCapture1Colour )
        self.addEventHandler( 'keypress', name='u', function=self.OnTypedFunction )
        
        usage = """		s -- save the captured buffer to the file test.jpg'
        c -- capture the colour buffer 
        r,g,b -- capture red/green/blue channels independently
        d -- capture the depth buffer 
        v -- view the captured buffer 
        s -- save the captured buffer to file test.jpg 
        t -- use the "string" version of the glDrawPixels function 
        u -- use the "ub" variant of the base glReadPixels function
        """
        print usage
        self.getViewPlatform().setFrustum( near = 3, far = 10 )
        print self.getViewPlatform().frustum
        print 'Current depth scale', glGetDouble( GL_DEPTH_SCALE )
        print 'Current depth bias', glGetDouble( GL_DEPTH_BIAS )
    def OnSave( self, event=None):
        self.SaveTo( 'test.jpg' )
    def SaveTo( self, filename, format="JPEG" ):
        try:
            from PIL import Image # get PIL's functionality...
        except ImportError, err:
            # old style?
            import Image
        if not len(self.capturedImage):
            self.OnCaptureColour()
        data = self.capturedImage
        if self.capturedImageFormat == GL_RGB:
            pixelFormat = 'RGB'
        else:
            pixelFormat = 'L'
        width,height,depth = self.capturedSize
        image = Image.fromstring( pixelFormat, (int(width),int(height)), data.tostring() )
        image = image.transpose( Image.FLIP_TOP_BOTTOM)
        image.save( filename, format )
        print 'Saved image to %s'% (os.path.abspath( filename))
        return image
    def OnCaptureColour( self , event=None):
        try:
            from PIL import Image # get PIL's functionality...
        except ImportError, err:
            # old style?
            import Image
        width, height = self.getViewPort()
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        if self.typedFunction:
            data = glReadPixelsub(0, 0, width, height, GL_RGB)
        else:
            data = glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE)
        if hasattr( data, 'shape' ):
            assert data.shape == (width,height,3), """Got back array of shape %r, expected %r"""%(
                data.shape,
                (width,height,3),
            )
            string = data.tostring()
            #print 'array returned was', data.shape
            if self.reverseShape:
                data.shape = (height,width,3)
                #print 'reversed shape', data.shape
            assert data.tostring() == string, """Data stored differs in format"""
        self.capturedImage = data
        self.capturedImageFormat = GL_RGB
        self.capturedSize = (width,height,3)
    def OnViewCapture( self, event ):
        """Trigger viewing of saved data-set"""
        if not len(self.capturedImage):
            self.OnCaptureColour( event )
        self.drawCapture = not self.drawCapture
    def OnUseStringDraw( self, event ):
        """Trigger use of string drawing for display of captured"""
        self.useStringDraw = not self.useStringDraw
        print 'Use string drawing:', self.useStringDraw
    def OnTypedFunction( self, event ):
        """Use typed function for capture"""
        self.typedFunction = not self.typedFunction
        print 'Use typed function:', self.typedFunction
    def OnReverseShape( self, event ):
        self.reverseShape = not self.reverseShape
        print 'Reverse image shape:', self.reverseShape
    
    def OnCapture1Colour( self, event ):
        if event.name == 'r':
            return self.OnCaptureDepth( event, GL_RED )
        elif event.name == 'g':
            return self.OnCaptureDepth( event, GL_GREEN )
        elif event.name == 'b':
            return self.OnCaptureDepth( event, GL_BLUE )
    
    def OnCaptureDepth( self, event, component = GL_DEPTH_COMPONENT ):
        """Trigger saving of depth buffer for display"""
        width, height = self.getViewPort()
        glPixelStorei(GL_PACK_ALIGNMENT, 1)
        #data = glReadPixels(0,0,width,height, GL_DEPTH_COMPONENT, GL_FLOAT)
        if self.typedFunction:
            data = glReadPixelsub(0,0,width,height, component)
        else:
            data = glReadPixels(0,0,width,height, component, GL_UNSIGNED_BYTE)
#		data = ravel( data )
#		dMin = amin(data)
#		print 'Minimum data point: %s'%(dMin )
#		data = data-dMin
#		dMax = amax(data)
#		print 'Total data point range: %s'%(dMax )
#		if dMax:
#			data = data / dMax * 255
#		data = data.astype( 'B' )
#		data.shape = (width,height)
        self.capturedImage = data
        self.capturedImageFormat = GL_LUMINANCE
        self.capturedSize = (width,height,1)

if __name__ == "__main__":
    TestContext.ContextMainLoop()
