#! /usr/bin/env python
'''=Win32 Bitmap Text (NeHe 13)=

This tutorial draws text to screen using WGL bitmap functionality
WGL is only available on Win32 platforms!

This tutorial is based on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=13 NeHe13 tutorial] by Jeff Molofee and assumes that you are reading along 
with the tutorial, so that only changes from the tutorial are noted 
here.

We're going to have to use the wxPython context explicitly, so that 
we have a single API for getting a window handle.
'''
from OpenGLContext.wxinteractivecontext import wxInteractiveContext
from OpenGLContext import testingcontext
from OpenGL.GL import *
from math import cos, sin
import sys
try:
    from OpenGL.WGL import *
    import win32ui, win32con
except ImportError, err:
    print """Unable to import Win32 text modules: %s"""%(err,)
    sys.exit( testingcontext.REQUIRED_EXTENSION_MISSING )

'''Our "font" class takes care of creating the display-lists 
which perform the actual rendering of characters.  The Win32ui 
calls are loosely the same as those seen in the tutorial.'''
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
        '''Build 96 bitmaps as display lists starting from character 
        32.'''
        wglUseFontBitmaps(wgldc, 32, 96, self.base)
        '''f is deleted here, if it is deleted before the display-lists
        are created they will just use the default font!'''
    def __del__(self):
        glDeleteLists(self.base, 96)	# Delete All 96 Characters
    def draw(self, text):
        '''glCallLists is pretty much tailor-made for these kinds of 
        calls, a single GL call can render an entire string of text.
        Note, however, that glCallLists is now deprecated.'''
        glCallLists(
            map(
                lambda x, y: ord(x) - 32 + y, 
                text, 
                [self.base]*len(text)
            )
        )

'''The timer class here is a trivial wrapping of the wxPython timer 
class.  Real-world OpenGLContext code would likely use the Timer 
class instance.'''
import wx
class timer(wx.Timer):
    def __init__(self, parent):
        wx.Timer.__init__(self)
        self.parent = parent

    def Notify(self):
        if self.parent:
            self.parent.cnt1+=0.051
            self.parent.cnt2+=0.005
            '''Trigger a redraw using wxPython operation'''
            self.parent.Refresh()
        else:
            self.Stop()

class TestContext( wxInteractiveContext ):
##	rot = 0
    cnt1 = 0
    cnt2 = 0

    def __init__(self, parent):
        wxInteractiveContext.__init__(self, parent)
        # TODO: this font *shouldn't* be needed...
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


    def Render( self, mode):
        wxInteractiveContext.Render( self, mode )
        glDisable(GL_LIGHTING)
        glRasterPos2f(5*cos(self.cnt1), 5*sin(self.cnt2))
        self.my_font.draw("NeHe - %3.2f" % self.cnt1)
        if self.timer is None:
            self.timer = timer(self)
            self.timer.Start(25)
        
    def Background(self, mode = 0):
        """Clear to Blue"""
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
'''
Author: [http://nehe.gamedev.net Jeff Molofee (aka NeHe)]

COPYRIGHT AND DISCLAIMER: (c)2000 Jeff Molofee

If you plan to put this program on your web page or a cdrom of
any sort, let me know via email, I'm curious to see where
it ends up :)

If you use the code for your own projects please give me
credit, or mention my web site somewhere in your program 
or it's docs.
'''