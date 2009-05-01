#! /usr/bin/env python
'''CubeBackground object test (image cube background)'''
import OpenGL 
OpenGL.ERROR_ON_COPY = True
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.loaders.loader import Loader
from math import pi
from OpenGLContext.events.timer import Timer

scene = """#VRML V2.0 utf8

Shape {
	geometry Box { }
	appearance Appearance { material Material {}}
}

DEF TR Transform {
	rotation 0,1,0,0
	children [
		DEF S Switch {
			whichChoice 0
			choice [
				DEF BG CubeBackground {
					backUrl "pimbackground_BK.jpg"
					frontUrl "pimbackground_FR.jpg"
					leftUrl "pimbackground_RT.jpg"
					rightUrl "pimbackground_LF.jpg"
					topUrl "pimbackground_UP.jpg"
					bottomUrl "pimbackground_DN.jpg"
				}
				DEF BG2 SphereBackground {
					skyColor [ 0 1 0, 1,0,0 ]
					skyAngle [ .75 ]
					groundColor [ 0,0,0, 0,0,0 ]
					groundAngle [ .75 ]
				}
			]
		}
	]
}

"""
	

class TestContext( BaseContext ):
	"""Tests the CubeBackground object's rendering
	"""
	def OnInit( self ):
		"""Scene set up and initial processing"""
		self.sg = Loader.loads( scene, 'test.wrl' )
		self.tr = self.sg.getDEF( 'TR' )
		self.time = Timer( duration = 128.0, repeating = 1 )
		self.time.addEventHandler( "fraction", self.OnTimerFraction )
		self.time.register (self)
		self.time.start ()
		print 'press <b> to switch backgrounds'
		self.addEventHandler( "keypress", name="b", function = self.OnSwitch)
	def OnTimerFraction( self, event ):
		"""Update rotation of the background"""
		self.tr.rotation = (1,0,0, 2 * pi * event.fraction() )
	def OnSwitch( self, event ):
		switch= self.getSceneGraph().getDEF( 'S' )
		if switch.whichChoice:
			switch.whichChoice = 0
		else:
			switch.whichChoice = 1
		self.triggerRedraw(1)

if __name__ == "__main__":
	MainFunction ( TestContext)

