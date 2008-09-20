#! /usr/bin/env python
'''Draws text to screen using WGL bitmap functionality

This code is a descendant of NeHe tutorial #13...

OpenGL Tutorial #13.

Project Name: Jeff Molofee's OpenGL Tutorial

Project Description: Using Bitmap Fonts In OpenGL

Authors Name: Jeff Molofee (aka NeHe)

Authors Web Site: nehe.gamedev.net

COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee

	If you plan to put this program on your web page or a cdrom of
	any sort, let me know via email, I'm curious to see where
	it ends up :)

        If you use the code for your own projects please give me credit,
        or mention my web site somewhere in your program or it's docs.
'''
from OpenGLContext.wxinteractivecontext import wxInteractiveContext
from OpenGL.GL import *
from math import cos, sin
import sys
try:
	from OpenGL.WGL import *
	import win32ui, win32con
except ImportError, err:
	raise ImportError( """Unable to import Win32 text modules: %s"""%(err,))

### eventually this should turn into a module under scenegraph/text
class font:
	def __init__(self, context):
		self.base = glGenLists(96)								# Storage For 96 Characters
		wgldc = wglGetCurrentDC()
		if wgldc > sys.maxint:
			import struct
			print 'too-large wgldc', wgldc
			wgldc = struct.unpack( '>i', struct.pack( '>I', wgldc ))[0]
			print 'Converted wgldc to', wgldc
		dc = win32ui.CreateDCFromHandle( wgldc )
		## pitch and family value
		f = win32ui.CreateFont(
			{
				'italic': None, #use of None is required, 0 doesn't work
				'underline': None, #use of None is required, 0 doesn't work
				'name': 'Times New Roman',
				'weight': 700,
				'height': 20,
			}
		)
		dc.SelectObject(
			f
		)
		wglUseFontBitmaps(wgldc, 32, 96, self.base)	# Builds 96 Characters Starting At Character 32
		# f is deleted here, if it is deleted before the display-lists
		# are created they will just use the default font!
	def __del__(self):
		glDeleteLists(self.base, 96)	# Delete All 96 Characters
	def draw(self, text):
		glCallLists(map(lambda x, y: ord(x) - 32 + y, text, [self.base]*len(text)))		# Draws The Display List Text

import wx
class timer(wx.Timer):

	def __init__(self, parent):
		wx.Timer.__init__(self)
		self.parent = parent

	def Notify(self):
		if self.parent:
			self.parent.cnt1+=0.051
			self.parent.cnt2+=0.005
			self.parent.Refresh()
		else:
			self.Stop()

class TestContext( wxInteractiveContext ):
##	rot = 0
	cnt1 = 0
	cnt2 = 0

	def __init__(self, parent):
		wxInteractiveContext.__init__(self, parent)
		f = wx.Font(
			20,
			wx.DECORATIVE,
			wx.NORMAL,
			wx.NORMAL,
			0,
			"Script",
		)
		self.SetFont( f )
		self.my_font = font( self )
		self.timer = None


	def Render( self, mode = 0):
		wxInteractiveContext.Render( self, mode )
		glDisable(GL_LIGHTING)
		glRasterPos2f(5*cos(self.cnt1), 5*sin(self.cnt2))
		self.my_font.draw("NeHe - %3.2f" % self.cnt1)
		if self.timer is None:
			self.timer = timer(self)
			self.timer.Start(25)
		
	def Background(self, mode = 0):
		''' Clear the background for a particular rendering mode,
		potentially render a "cool" background node'''
		glClearColor(0.0,0.0,1.0,1.0)
		glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT )

if __name__ == "__main__":
	import wx
	class MyApp(wx.App):
		def OnInit(self):
			frame = wx.Frame(
				None, -1, "NeHe GL Text Demo",
				wx.DefaultPosition, wx.Size(600,300),
			)
			self.SetTopWindow(frame)
			frame.Show( True )
			win = TestContext(frame)
			return True
	app = MyApp(0)
	app.MainLoop()
