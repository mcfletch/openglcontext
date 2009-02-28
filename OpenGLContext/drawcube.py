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

def drawCube():
	"""Draw a cube 2,2,2 units centered around the origin"""
	# draw six faces of a cube
	glBegin(GL_TRIANGLES);
	for record in yieldVertices():
		glTexCoord2f( *record[:2] )
		glNormal3f( *record[2:5] )
		glVertex3f( *record[5:8] )
	glEnd()
	
