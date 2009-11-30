from OpenGLContext import wxinteractivecontext
from OpenGLContext.scenegraph import basenodes
import wx
from OpenGLContext.events.timer import Timer

class TestContext( wxinteractivecontext.wxInteractiveContext ):
    rotating = 1
    def OnInit( self ):
        self.sg = basenodes.sceneGraph(
            children = [
                basenodes.Transform(
                    children = [
                        basenodes.Shape(
                            geometry = basenodes.Box(
                                size = (2,3,4),
                            ),
                            appearance=basenodes.Appearance(
                                material = basenodes.Material(
                                    diffuseColor = (1,0,0),
                                ),
                            ),
                        ),
                    ],
                ),
                basenodes.PointLight(
                    location=(5,6,5),
                ),
            ],
        )
        self.time = Timer( duration = 32.0, repeating = 1 )
        self.time.addEventHandler( "fraction", self.OnTimerFraction )
        self.time.register (self)
        self.time.start ()
        self.rotation =  0
    def OnTimerFraction( self, event ):
        """Update our rotation from the timer event"""
        self.sg.children[0].rotation = (
            0,1,0,event.fraction()* 3.14149*2
        )
        
    def OnButtonPause( self, event ):
        """Handle the wxPython event from our button"""
        if self.rotating:
            self.time.pause()
        else:
            self.time.resume()
        self.rotating = not self.rotating
    

if __name__ == "__main__":
    class DemoFrame( wx.Frame ):
        def __init__(self, parent, sceneGraph=None):
            wx.Frame.__init__(self, parent, 2400, "VRMLTreeControl Demo", size=(800,600) )
            outerbox = wx.BoxSizer(wx.HORIZONTAL)
            for x in range( 2 ):
                box = self.createSet()
                outerbox.Add( box, 1, wx.EXPAND )
            self.SetAutoLayout(True)
            self.SetSizer( outerbox )
        def createSet( self ):
            outerbox = wx.BoxSizer(wx.HORIZONTAL)
            box = wx.BoxSizer(wx.VERTICAL)
            outerbox.Add( box, 5, wx.EXPAND )
            tID = wx.NewId()
            context = TestContext(
                self,
            )
            box.Add(context, 1, wx.EXPAND )
            ID = wx.NewId()
            box.Add(wx.Button(self, ID, "Stop Rotation"), 0)
            wx.EVT_BUTTON(self, ID, context.OnButtonPause)
            return outerbox
        def OnCloseWindow(self, event):
            self.Destroy()

    class DemoApp(wx.App):
        def OnInit(self):
            frame = DemoFrame(None)
            frame.Show(True)
            self.SetTopWindow(frame)
            return True
        
    def test( sceneGraph=None ):
        app = DemoApp(0)
        app.MainLoop()
    test( )