"""Polygon sorting support functions for ArrayGeometry

For your transparent geometry, get a set of object-space
centers for the triangles being drawn:
	centers( self.verticies )

Store this somewhere, as you'll need it on every transparent
rendering pass.  During the pass, when you get to the point
where you want to draw the transparent geometry:
	map(
		gluProject,
			centers[:,0],
			centers[:,1],
			centers[:,2],
			[modelview]*len(centers),
			[projection]*len(centers),
			[viewport]*len(centers),
	)

Then take the z values from that and pass to:
	indices( zFloats )

glDrawElements(
	GL_QUADS,
	GL_UNSIGNED_INT, # this changed with PyOpenGLSWIG 2.0, not previously needed
	indices
)
"""


import arraygeometry
from OpenGLContext.arrays import *
from OpenGL.GL import *
from OpenGL.GLU import *

def distances( centers, modelView=None, projection=None, viewport=None ):
	"""Get distances to centers into view-space coords"""
	if modelView is None:
		modelView = glGetDoublev( GL_MODELVIEW_MATRIX )
	if projection is None:
		projection = glGetDoublev( GL_PROJECTION_MATRIX )
	if viewport is None:
		viewport = glGetIntegerv( GL_VIEWPORT )
	return array(map(
		gluProject,
			centers[:,0],
			centers[:,1],
			centers[:,2],
			[modelView]*len(centers),
			[projection]*len(centers),
			[viewport]*len(centers),
	), 'd')[:,2]
	

def indices( zFloats ):
	"""Calculate rendering indices from center-distance-floats

	zFloats -- distance-to-center-of-polygons as calculated
		by the distances function

	calculates indices required to render from back to front
	(least float to greatest float)
	"""
	indices = argsort( zFloats ) * 3
	result = repeat(
		indices,
		ones((len(indices),), 'i' )*3,
		0
	)
	result[1::3] = result[1::3] + 1
	result[2::3] = result[2::3] + 2
	return result

if __name__ == "__main__":
	def test2( v ):
		c = centers( v )
		print 'centers', c
		value2 = indices( c[:,2] )
		print 'indices', value2
		return value2
	test2(
		array( [
			[0,0,0],[1,0,0],[1,1,0],
			[0,0,0],[1,0,0],[1,1,-1],
			[0,0,-1],[1,0,-1],[1,1,-1],
		], 'd')
	)
	test2(
		array( [
			[0,0,0],[1,0,0],[1,1,-1],
			[0,0,0],[1,0,0],[1,1,0],
			[0,0,-1],[1,0,-1],[1,1,-1],
		], 'd')
	)
	
