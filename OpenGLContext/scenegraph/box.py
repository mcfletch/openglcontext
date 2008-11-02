"""Box node for use in geometry attribute of Shapes"""
from OpenGLContext.scenegraph import cache
from OpenGLContext import displaylist
from OpenGL.GL import *
from vrml.vrml97 import basenodes
from vrml import protofunctions

class Box( basenodes.Box ):
	"""Simple Box object of given size centered about local origin

	The Box geometry node can be used in the geometry
	field of a Shape node to be displayed. Use Transform
	nodes to position the box within the world.

	The Box includes texture coordinates and normals.

	Attributes of note within the Box object:

		size -- x,y,z tuple giving the size of the box
		listID -- used internally to store the display list
			used to display the box during rendering

	Reference:
		http://www.web3d.org/technicalinfo/specifications/vrml97/part1/nodesRef.html#Box
	"""
	def compile( self, mode=None ):
		"""Compile the box as a display-list"""
		dl = displaylist.DisplayList()
		dl.start()
		try:
			drawBox( self.size )
			holder = mode.cache.holder(self, dl)
			holder.depend( self, protofunctions.getField(self, 'size') )
			return dl
		finally:
			dl.end()
	def render (
			self,
			visible = 1, # can skip normals and textures if not
			lit = 1, # can skip normals if not
			textured = 1, # can skip textureCoordinates if not
			transparent = 0, # XXX should sort triangle geometry...
			mode = None, # the renderpass object for which we compile
		):
		"""Render the Box (build and) call the display list"""
		# do we have a cached array-geometry?
		dl = mode.cache.getData(self)
		if not dl:
			dl = self.compile( mode=mode )
		dl()
		return 1
	def boundingVolume( self ):
		"""Create a bounding-volume object for this node"""
		from OpenGLContext.scenegraph import boundingvolume
		current = boundingvolume.getCachedVolume( self )
		if current:
			return current
		return boundingvolume.cacheVolume(
			self,
			boundingvolume.AABoundingBox(
				size = self.size,
			),
			( (self, 'size'), ),
		)

def drawBox( (x,y,z) ):
	"""Draw a box of given size centered around the origin,
	based on the NeHe6 demo via the drawcube module"""
	x,y,z = x/2.0, y/2.0, z/2.0
	glBegin(GL_QUADS);
	glNormal3f( 0.0, 0.0, 1.0)
	glTexCoord2f(0.0, 0.0); glVertex3f(-x, -y, z)
	glTexCoord2f(1.0, 0.0); glVertex3f( x, -y, z)
	glTexCoord2f(1.0, 1.0); glVertex3f( x, y, z)
	glTexCoord2f(0.0, 1.0); glVertex3f(-x, y, z)

	glNormal3f( 0.0, 0.0,-1.0);
	glTexCoord2f(1.0, 0.0); glVertex3f(-x, -y, -z)
	glTexCoord2f(1.0, 1.0); glVertex3f(-x, y, -z)
	glTexCoord2f(0.0, 1.0); glVertex3f( x, y, -z)
	glTexCoord2f(0.0, 0.0); glVertex3f( x, -y, -z)

	glNormal3f( 0.0, 1.0, 0.0)
	glTexCoord2f(0.0, 1.0); glVertex3f(-x, y, -z)
	glTexCoord2f(0.0, 0.0); glVertex3f(-x, y, z)
	glTexCoord2f(1.0, 0.0); glVertex3f( x, y, z)
	glTexCoord2f(1.0, 1.0); glVertex3f( x, y, -z)

	glNormal3f( 0.0,-1.0, 0.0)
	glTexCoord2f(1.0, 1.0); glVertex3f(-x, -y, -z)
	glTexCoord2f(0.0, 1.0); glVertex3f( x, -y, -z)
	glTexCoord2f(0.0, 0.0); glVertex3f( x, -y, z)
	glTexCoord2f(1.0, 0.0); glVertex3f(-x, -y, z)

	glNormal3f( 1.0, 0.0, 0.0)
	glTexCoord2f(1.0, 0.0); glVertex3f( x, -y, -z)
	glTexCoord2f(1.0, 1.0); glVertex3f( x, y, -z)
	glTexCoord2f(0.0, 1.0); glVertex3f( x, y, z)
	glTexCoord2f(0.0, 0.0); glVertex3f( x, -y, z)

	glNormal3f(-1.0, 0.0, 0.0)
	glTexCoord2f(0.0, 0.0); glVertex3f(-x, -y, -z)
	glTexCoord2f(1.0, 0.0); glVertex3f(-x, -y, z)
	glTexCoord2f(1.0, 1.0); glVertex3f(-x, y, z)
	glTexCoord2f(0.0, 1.0); glVertex3f(-x, y, -z)
	glEnd()
