"""Implementation of the Context API using Tkinter [UNFINISHED]"""
from OpenGL.GL import *
from OpenGL.Tk import *

from OpenGLContext.context import Context
from OpenGLContext.events import tkevents

TKID_SHIFT = 1
TKID_CTRL = 4
TKID_ALT = 16

class TkContext (
	tkevents.EventHandlerMixin,
	Context,
	Togl
):
	"""Tkinter-based OpenGLContext Context object"""
	def __init__ (self, parent, title="Tk Rendering Context", size = (300,300)):
		# create an OpenGL rendering context within the parent frame
		# double indicates double buffering
		Togl.__init__(
			self, master=parent, width = size[0], height = size [1], double = 1
		)
		Context.__init__ (self)
	def setupCallbacks( self ):
		# tell the OpenGL context what method/function to run during redraw
		# effectively this binds the method to the redraw event
		self.redraw = self.OnDraw
		self.bind('<Map>', self.tkRedraw)
		self.bind('<Expose>', self.tkRedraw)
		self.bind('<Configure>', self.tkConfigure)
		
		self.bind('<Button>', self.tkOnMouseButton)
		self.bind('<Button-2>', self.tkOnMouseButton)
		self.bind('<Button-3>', self.tkOnMouseButton)
		
		self.bind('<B1-Motion>', self.tkOnMouseMove)
		self.bind('<B2-Motion>', self.tkOnMouseMove)
		self.bind('<B3-Motion>', self.tkOnMouseMove)
		self.bind('<B4-Motion>', self.tkOnMouseMove)
		self.bind('<B5-Motion>', self.tkOnMouseMove)
		self.bind( '<Motion>', self.tkOnMouseMove)
		
		self.bind('<ButtonRelease>', self.tkOnMouseRelease)

		# XXX Bug in Togl, won't catch key events itself, have
		# to bind application-wide, which is basically unacceptable :(
		# parent = self._nametowidget(self.winfo_parent())

		self.bind_all( '<KeyPress>', self.tkOnKeyDown ) # urgh, this doesn't seem to work :o(
		self.bind_all( '<KeyRelease>', self.tkOnKeyUp )
		self.after_idle( self.tkOnIdle, None )
		#self.bind_all( '<Key>', self.tkOnKeyUp ) # doesn't work :( 

	def tkConfigure( self, event=None ):
		"""Handle size/shape/whatever change events for Tk"""
		self.setCurrent()
		try:
			self.ViewPort( event.width, event.height )
		finally:
			self.unsetCurrent()
		self.triggerRedraw(1)
	def tkRedraw( self, event=None ):
		"""Handle damage/expose/draw events for Tk"""
		self.triggerRedraw(1)
	def tkOnIdle( self, event=None ):
		"""Deal with free time from the Tk GUI"""
		try:
			if self.drawPoll():
				self.update()
				try:
					self.update_idletasks()
				except TclError:
					pass
##			import pdb
##			pdb.set_trace()
		finally:
			self.after( 10, self.tkOnIdle)
	def SwapBuffers( self ):
		"""Customisation point: swap OpenGL buffers"""
		self.tk.call(self._w, 'swapbuffers')
	def setCurrent (self):
		"""Customisation point: Acquire the GL "focus" """
		Context.setCurrent( self )
		self.tk.call(self._w, 'makecurrent')

##	def tkOnKeyDown( self, event ):
##		'''Convert a key-press to a context-style event'''
##		print 'key down', repr(event.char), event.state, event.keycode, event.keysym, event.keysym_num
##	def tkOnKeyUp( self, event ):
##		'''Convert a key-press to a context-style event'''
##		print 'key up', repr(event.char), event.state
##	def tkOnCharacter( self, event ):
##		"""Convert character (non-control) press to context event"""
##		print 'character', repr(event.char), event.state
##	def tkOnMouseDown(self, event ):
##		''' mouse down
##
##		State:
##			down -- 0
##			mouse-l-up -- 256
##			mouse-r-up -- 1024
##			mouse-m-up -- 512
##			
##
##			ctrl=   0x00004
##			alt =   0x20000
##			shift = 0x00001
##			caps-lock = 0x00002
##			num-lock = 0x00008
##			
##		'''
##		print 'mouse down', event, event.num, (event.x, event.y), event.state
####		import pdb
####		pdb.set_trace()
##		
##	def tkOnMouseUp(self, event ):
##		''' mouse up
##		'''
##		print 'mouse up', event, event.num, (event.x, event.y), event.state
##		
##	def tkOnMouseDrag(self, event ):
##		''' mouse movement (with drag)
##		'''
##		print 'drag', event, event.num, (event.x, event.y), event.state
##	def tkOnMouseMove( self, event ):
##		''' mouse movement, no drag
##		'''
##		
##	def OnPick( self, event):
##		print "pick", event
##		results = self._pick( event.x, event.y)
##		print "pick results",results
	def ContextMainLoop( cls, *args, **named ):
		"""Run the context mainloop"""
		frame = Frame()
		frame.pack(side = 'top', expand = 1, fill = 'both')
		cls( frame, *args, **named ).pack(
			side = 'top', expand = 1, fill = 'both'
		)
		return frame.mainloop()
	ContextMainLoop = classmethod( ContextMainLoop )


if __name__ == '__main__':
	from drawcube import drawCube
	class TestContext( TkContext ):
		def Render( self, mode = None):
			TkContext.Render (self, mode)
			glTranslated ( 2,0,-4)
			drawCube()
	TestContext.ContextMainLoop()
