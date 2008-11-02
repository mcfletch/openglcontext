"""Panoramic image-cube Background node
"""
from OpenGLContext.scenegraph import imagetexture
from vrml import field, protofunctions, fieldtypes, node
from vrml.vrml97 import basenodes, nodetypes

from OpenGL.GL import *
from OpenGLContext.arrays import *
from math import pi

class URLField( fieldtypes.MFString ):
	"""Cube-background URL field which forwards to the corresponding ImageTexture node's url
	"""
	fieldType = "MFString"
	def fset( self, client, value, notify=1 ):
		value = super( URLField, self).fset( client, value, notify )
		imageObject = getattr(client, self.name[:-3])
		setattr( imageObject, 'url', value )
		return value
	def fdel( self, client, notify=1 ):
		value = super( URLField, self).fdel( client, notify )
		imageObject = getattr(client, self.name[:-3])
		delattr( imageObject, 'url')
		return value

class _CubeBackground( object ):
	right = field.newField('right', 'SFNode', default=imagetexture.ImageTexture)
	top = field.newField('top', 'SFNode', default=imagetexture.ImageTexture)
	back = field.newField('back', 'SFNode', default=imagetexture.ImageTexture)
	left = field.newField('left', 'SFNode', default=imagetexture.ImageTexture)
	front = field.newField('front', 'SFNode', default=imagetexture.ImageTexture)
	bottom = field.newField('bottom', 'SFNode', default=imagetexture.ImageTexture)
	
	rightUrl = URLField( 'rightUrl')
	topUrl = URLField( 'topUrl')
	backUrl = URLField( 'backUrl')
	leftUrl = URLField( 'leftUrl')
	frontUrl = URLField( 'frontUrl')
	bottomUrl = URLField( 'bottomUrl')
	
	bound = field.newField( 'bound', 'SFBool', 1, 0)
	
	def Render( self, mode, clear=1 ):
		"""Render the cube background

		This renders those of our cube-faces which are
		facing us, and which have a non-0 component-count.

		After it's finished, it clears the depth-buffer
		to make the geometry appear "behind" everything
		else.
		"""
		if mode.passCount == 0:
			try:
				glDisable( GL_DEPTH_TEST ) # we don't want to do anything with the depth buffer...
				glDisable( GL_LIGHTING )
				glDisable( GL_COLOR_MATERIAL )
				# yuck, why is this necessary with the previous line?
				glColor3f( 1.0, 1.0, 1.0, )
				if clear:
					glClear(GL_COLOR_BUFFER_BIT|GL_DEPTH_BUFFER_BIT|GL_STENCIL_BUFFER_BIT)
				try:
					matrix = glGetDoublev( GL_MODELVIEW_MATRIX )
					if matrix is None:
						# glGetDoublev can return None if uninitialised...
						matrix = identity( 4, 'd')
					forward = dot(matrix, [0,0,-1,0])
					textures = [
						(self.front, (0,0,1,0),[
							((-1,-1,-1), (0,0)),
							((1,-1,-1), (1,0)),
							((1,1,-1), (1,1)),
							((-1,1,-1), (0,1)),
						]),
						(self.right,(-1,0,0,0),[
							((1,-1,-1), (0,0)),
							((1,-1,1), (1,0)),
							((1,1,1), (1,1)),
							((1,1,-1), (0,1)),
						]),
						(self.back, (0,0,-1,0), [
							((1,-1,1), (0,0)),
							((-1,-1,1), (1,0)),
							((-1,1,1), (1,1)),
							((1,1,1), (0,1)),
						]),
						(self.left,(1,0,0,0),[
							((-1,-1,1), (0,0)),
							((-1,-1,-1), (1,0)),
							((-1,1,-1), (1,1)),
							((-1,1,1), (0,1)),
						]),
						(self.bottom,(0,1,0,0),[
							((-1,-1,1), (0,0)),
							((1,-1,1), (1,0)),
							((1,-1,-1), (1,1)),
							((-1,-1,-1), (0,1)),
						]),
						(self.top,(0,-1,0,0),[
							((-1,1,-1), (0,0)),
							((1,1,-1), (1,0)),
							((1,1,1), (1,1)),
							((-1,1,1), (0,1)),
						]),
					]
					for texture, normal, data in textures:
						if dot(forward, normal) <=0 and texture.components:
							# we are facing it, and it's loaded/non-null
							texture.render(lit=0, mode=mode)
							try:
								glBegin( GL_QUADS )
								try:
									for point, coord in data:
										glTexCoord2dv( coord )
										glVertex3dv( point )
								finally:
									glEnd()
							finally:
								texture.renderPost(mode=mode)
				finally:
					glEnable( GL_COLOR_MATERIAL )
			finally:
				glEnable( GL_DEPTH_TEST )
				glEnable( GL_LIGHTING )
				# now, completely wipe out the depth buffer,
				# so this appears as a "background"...
				glClear(GL_DEPTH_BUFFER_BIT)

class CubeBackground( _CubeBackground, nodetypes.Background, nodetypes.Children, node.Node  ):
	"""Image-cube Background node

	The CubeBackground node implements 1/2 of the VRML97
	background node, particularly the image-cube
	functionality represented by the rightUrl, topUrl,
	backUrl, leftUrl, frontUrl, and bottomUrl fields.

	Fields of note within the CubeBackground object:

		back, front, left, right, top, bottom -- texture
			objects applied to the geometry of the cube.
			Any node which supports the texture API
			should work for these attributes
			
		backUrl, frontUrl, leftUrl, rightUrl, topUrl,
		bottomUrl -- texture urls (MFStrings) used to
			load the images above

	Note: the common practice in 3DSMax for creating
	a cubic environment map produces useful
	background images, but it is often necessary to
	swap left and right images to work with the
	VRML 97 system.
	"""
	
