"""FXPy context functionality based on gltest.py [LGPL, UNFINISHED]

Adapted from Lyle Johnson's gltest.py in the FXPy distribution.
As a result, this module is LGPL'd (as differentiated from the
bulk of PyOpenGL, which is BSD licensed).  See FXPy for license
details.
"""
from FXPy.fox import *
from OpenGL.GL import *
from drawcube import drawCube
from OpenGLContext import context
from OpenGLContext.events import fxevents
import traceback

# Test for OpenGL
class FXContext(
	FXMainWindow, # shouldn't this just be a control???
	fxevents.EventHandlerMixin,
	context.Context,
):
	# Enumerated message identifiers
	ID_CANVAS = FXMainWindow.ID_LAST

	# Constructor
	def __init__(self,app):
		# Must invoke base class constructor explicitly
		FXMainWindow.__init__(self,app,"FXPy GL Context",w=400,h=300)
		# A visual to draw OpenGL
		self.glvisual = FXGLVisual(self.getApp(),VISUAL_DOUBLEBUFFER)
		# Drawing glcanvas
		self.glcanvas = FXGLCanvas(self,self.glvisual,self,self.ID_CANVAS,LAYOUT_FILL_X|LAYOUT_FILL_Y|LAYOUT_TOP|LAYOUT_LEFT)
		
		context.Context.__init__ (self)
		
	def setupCallbacks( self ):
		# Message map
		try:
			self.setCurrent()
			FXMAPFUNC(self,SEL_PAINT,    self.ID_CANVAS, self.__class__.fxOnExpose)
			FXMAPFUNC(self,SEL_CONFIGURE,self.ID_CANVAS, self.__class__.fxOnConfigure)
			FXMAPFUNC(self,SEL_MOTION,   self.ID_CANVAS, self.__class__.fxOnMouseMove)
			FXMAPFUNC(self,SEL_LEFTBUTTONPRESS,   self.ID_CANVAS, self.__class__.fxOnMouseButton)
			FXMAPFUNC(self,SEL_RIGHTBUTTONPRESS,   self.ID_CANVAS, self.__class__.fxOnMouseButton)
			FXMAPFUNC(self,SEL_MIDDLEBUTTONPRESS,   self.ID_CANVAS, self.__class__.fxOnMouseButton)
			FXMAPFUNC(self,SEL_LEFTBUTTONRELEASE,   self.ID_CANVAS, self.__class__.fxOnMouseButton)
			FXMAPFUNC(self,SEL_RIGHTBUTTONRELEASE,   self.ID_CANVAS, self.__class__.fxOnMouseButton)
			FXMAPFUNC(self,SEL_MIDDLEBUTTONRELEASE,   self.ID_CANVAS, self.__class__.fxOnMouseButton)
			FXMAPFUNC(self,SEL_KEYPRESS,   self.ID_CANVAS, self.__class__.fxOnKeyDown)
			FXMAPFUNC(self,SEL_KEYRELEASE,   self.ID_CANVAS, self.__class__.fxOnKeyUp)
		finally:
			self.unsetCurrent()
	def setCurrent( self ):
		self.glcanvas.makeCurrent()
		context.Context.setCurrent( self )
	def unsetCurrent( self ):
		self.glcanvas.makeNonCurrent()
		context.Context.unsetCurrent( self )
	def SwapBuffers( self ):
		if self.glvisual.isDoubleBuffer(): self.glcanvas.swapBuffers()
		

	# Widget was resized
	def fxOnConfigure(self,sender,sel,ptr):
		try:
			self.setCurrent()
			self.ViewPort( self.glcanvas.getWidth(),self.glcanvas.getHeight() )
			self.unsetCurrent()
			return 1
		except:
			traceback.print_exc()
	# Expose
	def fxOnExpose(self,sender,sel,ptr):
		self.triggerRedraw(1)
		return 1
	# Create and initialize
	def create(self):
		FXMainWindow.create(self)
		self.show()
		self.triggerRedraw(0)
		return 1
		



# Main program starts here
if __name__ == '__main__':
	class TestContext( FXContext ):
		def Render( self, mode = None):
			FXContext.Render (self, mode)
			glTranslate ( 2,0,-4)
			drawCube()
	import sys
	app = FXApp("GLTest", "Test")
	app.init(sys.argv)
	TestContext(app)
	app.create()
	app.run()
