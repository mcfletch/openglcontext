#!/usr/bin/env python
"""Interactive context using the Tkinter API (provides navigation support)"""
import string

from OpenGLContext.tkcontext import *
from OpenGLContext import interactivecontext
from OpenGLContext.move import viewplatformmixin

class TkInteractiveContext(
	viewplatformmixin.ViewPlatformMixin,
	interactivecontext.InteractiveContext,
	TkContext,
):
	'''PyGame context providing mouse and keyboard interaction '''

if __name__ == '__main__':
	from drawcube import drawCube
	class TestContext( TkInteractiveContext ):
		def Render( self, mode = None):
			TkInteractiveContext.Render (self, mode)
			glTranslated ( 2,0,-4)
			drawCube()
	TestContext.ContextMainLoop( )
	
