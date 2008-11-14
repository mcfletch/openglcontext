#! /usr/bin/env python
"""IndexedLineSet object test (draw circle in multiple or single colors)"""
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
	initialPosition = (0,0,3) # set initial camera position, tutorial does the re-positioning
	def Render( self, mode = 0):
		BaseContext.Render( self, mode )
		self.shape.Render( mode )
	def cpv( self, event=None ):
		"""colorPerVertex toggle"""
		self.shape.geometry.colorPerVertex = not self.shape.geometry.colorPerVertex
		self.triggerRedraw(1)
		
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		print """Should see multicolor circular ILS over white background"""
		print 'press c to toggle colorPerVertex (forces recompilation of display list)'
		self.addEventHandler( 'keypress', name = 'c', function = self.cpv )
		a = arange(0.0,2*math.pi,.02)
		xes = sin(a)
		yes = cos(a)
		coords = zeros( (len(xes),3),'d')
		coords[:,0] = xes
		coords[:,1] = yes
		
		self.shape = Shape(
			geometry = IndexedLineSet(
				coord = Coordinate(
					point = coords,
				),
				coordIndex = range( len(coords)),
				color = Color(
					color = coords,#[1,0,0], #
				),
				colorIndex = range( len(coords)),#[0], #
			),
		)
##	def OnIdle( self ):
##		self.shape.geometry.colorPerVertex = not self.shape.geometry.colorPerVertex
##		self.triggerRedraw(1)
		
if __name__ == "__main__":
	MainFunction ( TestContext)
