"""Low level testing function (draw a cube)

This module provides a simple function for drawing
a cube.  It is used by various modules for low level
testing purposes (i.e. in module-level rather than
system level tests).

This version was taken from the NeHe tutorials,
to replace the original which did not include
texture coordinate information.
"""
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array

def yieldVertices():
	normal = ( 0.0, 0.0, 1.0)
	yield (0.0, 0.0)+ normal + (-1.0, -1.0,  1.0);
	yield (1.0, 0.0)+ normal + ( 1.0, -1.0,  1.0);
	yield (1.0, 1.0)+ normal + ( 1.0,  1.0,  1.0);
	yield (0.0, 0.0)+ normal + (-1.0, -1.0,  1.0);
	yield (1.0, 1.0)+ normal + ( 1.0,  1.0,  1.0);
	yield (0.0, 1.0)+ normal + (-1.0,  1.0,  1.0);

	normal = ( 0.0, 0.0,-1.0);
	yield (1.0, 0.0)+ normal + (-1.0, -1.0, -1.0);
	yield (1.0, 1.0)+ normal + (-1.0,  1.0, -1.0);
	yield (0.0, 1.0)+ normal + ( 1.0,  1.0, -1.0);
	yield (1.0, 0.0)+ normal + (-1.0, -1.0, -1.0);
	yield (0.0, 1.0)+ normal + ( 1.0,  1.0, -1.0);
	yield (0.0, 0.0)+ normal + ( 1.0, -1.0, -1.0);

	normal = ( 0.0, 1.0, 0.0)
	yield (0.0, 1.0)+ normal + (-1.0,  1.0, -1.0);
	yield (0.0, 0.0)+ normal + (-1.0,  1.0,  1.0);
	yield (1.0, 0.0)+ normal + ( 1.0,  1.0,  1.0);
	yield (0.0, 1.0)+ normal + (-1.0,  1.0, -1.0);
	yield (1.0, 0.0)+ normal + ( 1.0,  1.0,  1.0);
	yield (1.0, 1.0)+ normal + ( 1.0,  1.0, -1.0);

	normal = ( 0.0,-1.0, 0.0)
	yield (1.0, 1.0)+ normal + (-1.0, -1.0, -1.0);
	yield (0.0, 1.0)+ normal + ( 1.0, -1.0, -1.0);
	yield (0.0, 0.0)+ normal + ( 1.0, -1.0,  1.0);
	yield (1.0, 1.0)+ normal + (-1.0, -1.0, -1.0);
	yield (0.0, 0.0)+ normal + ( 1.0, -1.0,  1.0);
	yield (1.0, 0.0)+ normal + (-1.0, -1.0,  1.0);

	normal = ( 1.0, 0.0, 0.0)
	yield (1.0, 0.0)+ normal + ( 1.0, -1.0, -1.0);
	yield (1.0, 1.0)+ normal + ( 1.0,  1.0, -1.0);
	yield (0.0, 1.0)+ normal + ( 1.0,  1.0,  1.0);
	yield (1.0, 0.0)+ normal + ( 1.0, -1.0, -1.0);
	yield (0.0, 1.0)+ normal + ( 1.0,  1.0,  1.0);
	yield (0.0, 0.0)+ normal + ( 1.0, -1.0,  1.0);

	normal = (-1.0, 0.0, 0.0)
	yield (0.0, 0.0)+ normal + (-1.0, -1.0, -1.0);
	yield (1.0, 0.0)+ normal + (-1.0, -1.0,  1.0);
	yield (1.0, 1.0)+ normal + (-1.0,  1.0,  1.0);
	yield (0.0, 0.0)+ normal + (-1.0, -1.0, -1.0);
	yield (1.0, 1.0)+ normal + (-1.0,  1.0,  1.0);
	yield (0.0, 1.0)+ normal + (-1.0,  1.0, -1.0);

VBO = None

def drawCube():
	"""Draw a cube 2,2,2 units centered around the origin"""
	# draw six faces of a cube
	global VBO 
	if not VBO:
		VBO = vbo.VBO( array( list(yieldVertices()), 'f') )
	VBO.bind()
	try:
		glPushClientAttrib(GL_CLIENT_ALL_ATTRIB_BITS)
		try:
			glInterleavedArrays( GL_T2F_N3F_V3F, 0, VBO )
			glDrawArrays( GL_TRIANGLES, 0, 36 )
		finally:
			glPopClientAttrib()
	finally:
		VBO.unbind()
		
