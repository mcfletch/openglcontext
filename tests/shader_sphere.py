#! /usr/bin/env python
'''Shader sample-code for OpenGLContext
'''
import OpenGL 
#OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.shaders import *

def sphere( phi=pi/8.0 ):
	"""Create arrays for rendering a unit-sphere
	
	phi -- angle between points on the sphere (stacks/slices)
	
	Note: creates 'H' type indices...
	"""
	zsteps = arange( 0,pi+0.000003, phi )
	steps = arange( 0,pi*2+0.000003, phi )
	ystep = len(steps)
	zstep = len(zsteps)
	xstep = 1
	coords = zeros((zstep,ystep,3), 'f')
	coords[:,:,0] = sin(steps)
	coords[:,:,1] = cos(zsteps).reshape( (-1,1))
	coords[:,:,2] = cos(steps)
	
	# now scale by sin of y's 
	scale = sin(zsteps).reshape( (-1,1))
	coords[:,:,0] *= scale
	coords[:,:,2] *= scale
	
#	sqrt( x**2 + z**2) = (sin(steps).reshape( (-1,1))
#	# scale factor for x and y
#	# (x/r)**2 + (y/r)**2/r + z**2 == sqrt(1) == 1 (unit sphere)
#	# 1-(z**2) == (x**2 + y**2)/r
#	# r = (x**2 + y**2)/(1-(z**2))
#	lengths = 1-(coords[:,:,1]**2)
#	
#	
#	import pdb 
#	pdb.set_trace()
#	r = (coords[:,:,0]**2 + coords[:,:,2]**2)/(1-coords[:,:,1]**2)
#	
#	# now normalize the coordinates...
#	coords /= sqrt( sum( abs(coords), axis=2 ) ).reshape( (ystep,ystep,1))
	indices = zeros( (ystep-1,ystep-1,6),dtype='H' )
	# all indices now render the first rectangle...
#	import pdb
#	pdb.set_trace()
	indices[:] = (0,0+ystep,0+ystep+xstep, 0,0+ystep+xstep,0+xstep)
	xoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1))
	indices += xoffsets
	yoffsets = arange(0,ystep-1,1,dtype='H').reshape( (-1,1,1))
	#yoffsets = (xoffsets * ystep).reshape( (-1,1,1,))
	indices += (yoffsets * ystep)
	return coords.reshape((-1,3)), indices.reshape((-1,))
	


class TestContext( BaseContext ):
	"""OpenGL 3.1 deprecates non-vertex-attribute drawing
	
	This sample code shows how to draw geometry using VBOs
	and generic attribute objects, rather than using GL state
	to pass values.
	
	Each attribute within a compiled and linked program has 
	a "location" bound to it (similar to a uniform), the 
	location can be queried with a call go glGetAttribLocation
	and the location can be passed to the glVertexAttribPointer
	function to bind a particular data source (normally a 
	VBO, and only a VBO under OpenGL 3.1) to that attribute.
	"""
	
	def OnInit( self ):
		coords,indices = sphere( pi/2.0 )
		print 'coordinates', coords 
		print 'indices', indices
		print 'taken', take(coords,indices).reshape( (-1,3))
		self.coordLength = len(coords)
		self.coords = vbo.VBO( coords )
		self.indices = vbo.VBO( indices, target = 'GL_ELEMENT_ARRAY_BUFFER' )
		glEnableClientState(GL_VERTEX_ARRAY);
		glEnableClientState(GL_NORMAL_ARRAY);
	
	def Render( self, mode = 0):
		"""Render the geometry for the scene."""
		BaseContext.Render( self, mode )
		self.coords.bind()
		glVertexPointer( 3, GL_FLOAT,0,self.coords)
		glNormalPointer( GL_FLOAT,0,self.coords )
		self.indices.bind()
		glDrawElements( GL_TRIANGLES, self.coordLength, GL_UNSIGNED_SHORT, self.indices )
		

if __name__ == "__main__":
#	coords,indices = sphere( pi/2 )
#	print take( coords, indices )
	MainFunction ( TestContext)

