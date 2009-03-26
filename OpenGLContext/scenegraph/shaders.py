"""Shader node implementation"""
from OpenGL.GL import *
from OpenGL.GL.ARB.shader_objects import *
from OpenGL.GL.ARB.fragment_shader import *
from OpenGL.GL.ARB.vertex_shader import *
from OpenGL.GL.ARB.vertex_program import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGL import error
from OpenGLContext.arrays import array
from OpenGLContext import context
from vrml.vrml97 import shaders
from vrml import field,node,fieldtypes,protofunctions

import time, sys,logging
log = logging.getLogger( 'OpenGLContext.scenegraph.shaders' )
from OpenGL.extensions import alternate
glCreateShader = alternate( 'glCreateShader', glCreateShader, glCreateShaderObjectARB )
glShaderSource = alternate( 'glShaderSource', glShaderSource, glShaderSourceARB)
glCompileShader = alternate( 'glCompileShader', glCompileShader, glCompileShaderARB)
glCreateProgram = alternate( 'glCreateProgram', glCreateProgram, glCreateProgramObjectARB)
glAttachShader = alternate( 'glAttachShader', glAttachShader,glAttachObjectARB )
glValidateProgram = alternate( 'glValidateProgram',glValidateProgram,glValidateProgramARB )
glLinkProgram = alternate( 'glLinkProgram',glLinkProgram,glLinkProgramARB )
glDeleteShader = alternate( 'glDeleteShader', glDeleteShader,glDeleteObjectARB )
glUseProgram = alternate('glUseProgram',glUseProgram,glUseProgramObjectARB )
glGetProgramInfoLog = alternate( glGetProgramInfoLog, glGetInfoLogARB )
glGetShaderInfoLog = alternate( glGetShaderInfoLog, glGetInfoLogARB )
glGetAttribLocation = alternate( glGetAttribLocation, glGetAttribLocationARB )
glVertexAttribPointer = alternate( glVertexAttribPointer, glVertexAttribPointerARB )

def compileProgram(vertexSource=None, fragmentSource=None):
	program = glCreateProgram()
	if isinstance( vertexSource, (str,unicode)):
		vertexSource = [ vertexSource ]
	if isinstance( fragmentSource, (str,unicode)):
		fragmentSource = [ fragmentSource ]
	if vertexSource:
		vertexShader = compileShader(
			vertexSource, GL_VERTEX_SHADER_ARB
		)
		glAttachShader(program, vertexShader)
	else:
		vertexShader = None
	if fragmentSource:
		fragmentShader = compileShader(
			fragmentSource, GL_FRAGMENT_SHADER_ARB
		)
		glAttachShader(program, fragmentShader)
	else:
		fragmentShader = None

	glValidateProgram( program )
#	if glGetProgramiv:
#		validation = glGetProgramiv( program, GL_VALIDATE_STATUS )
#		if not validation:
#			raise RuntimeError(
#				"""Validation failure""",
#				validation,
#				glGetProgramInfoLog( program ),
#			)
	glLinkProgram(program)
	
#	if glGetProgramiv:
#		link_status = glGetProgramiv( program, GL_LINK_STATUS )
#		if not link_status:
#			raise RuntimeError(
#				"""Link failure""",
#				link_status,
#				glGetProgramInfoLog( program ),
#			)

	if vertexShader:
		glDeleteShader(vertexShader)
	if fragmentShader:
		glDeleteShader(fragmentShader)
	if glIsProgram:
		assert glIsProgram( program ), ("""Program does not seem to have compiled!""", vertexSource, fragmentSource )
	return program
def compileShader( source, shaderType ):
	"""Compile shader source of given type"""
	shader = glCreateShader(shaderType)
	glShaderSource( shader, source )
	glCompileShader( shader )
	shader_log = glGetShaderInfoLog( shader )
	if shader_log:
		log.info( '''Shader compilation generated log: %s''', shader_log )
	return shader

class _Uniform( object ):
	"""Uniform common operations"""
	location = field.newField( ' location','SFUInt32',1, 0L )
	warned = False
	def getLocation( self, shader ):
		"""Retrieve our uniform location"""
		location = self.location
		if not location:
			location = self.location = glGetUniformLocation( shader, self.name )
			self.warned=False
			if location == -1:
				if not self.warned:
					log.warn( 'Unable to resolve uniform name %s', self.name )
					self.warned=True
				return None
		return location 

class FloatUniform( _Uniform, shaders.FloatUniform ):
	"""Uniform (variable) binding for a shader"""
	def render( self, shader, shader_id, mode ):
		"""Set this uniform value for the given shader
		
		This is called at render-time to update the value...
		"""
		location = self.getLocation( shader_id )
		if location is not None:
			value = self.value
			shape = value.shape 
			shape_length = len(self.shape)
			assert shape[-shape_length:] == self.shape,(shape,self.shape, value)
			if shape[:-shape_length]:
				size = reduce( operator.mul, shape[:-shape_length] )
			else:
				size = 1
			return self.baseFunction( location, size, value )
		return None
class IntUniform( _Uniform, shaders.IntUniform ):
	"""Uniform (variable) binding for a shader (integer form)
	"""
	
class TextureUniform( _Uniform, shaders.TextureUniform ):
	"""Uniform (variable) binding for a texture sampler"""
	baseFunction = staticmethod( glUniform1i )
	def render( self, shader, shader_id, mode, index ):
		"""Bind the actual uniform value"""
		location = self.getLocation( shader_id )
		if location is not None:
			if self.value:
				glActiveTexture( GL_TEXTURE0 + index )
				self.value.render( mode.visible, mode.lighting, mode )
				self.baseFunction( location, index )
				return True 
		return False


def _uniformCls( suffix ):
	def buildAlternate( function_name ):
		if globals().has_key( function_name+'ARB' ):
			function = alternate( 
				globals()[function_name], globals()[function_name+'ARB'] 
			)
		else:
			function = globals()[function_name]
		globals()[function_name] = function
		return function
		
	def buildCls( suffix, size, function, base ):
		name = 'FloatUniform'+suffix
		cls = type( name, (base,), {
			'suffix': suffix,
			'PROTO': name,
			'baseFunction': function,
			'shape': size,
		} )
		globals()[name] = cls 
	
	function_name = 'glUniform'
	if suffix.startswith( 'm' ):
		size = suffix[1:]
		function_name = 'glUniformMatrix%sfv'%( size, )
		function = buildAlternate( function_name )
		size = map( int, size.split('x' ))
		if len(size) == 1:
			size = [size[0],size[0]]
		size = tuple(size)
		buildCls( suffix, size, function, FloatUniform )
	else:
		if suffix.endswith( 'i' ):
			base = IntUniform
		else:
			base = FloatUniform
		function_name = 'glUniform%sv'%( suffix, )
		function = buildAlternate( function_name )
		size = (int(suffix[:1]), )
		buildCls( suffix, size, function, base )

FLOAT_UNIFORM_SUFFIXES = ('1f','2f','3f','4f','m2','m3','m4','m2x3','m3x2','m2x4','m4x2','m3x4','m4x3')
INT_UNIFORM_SUFFIXES = ('1i','2i','3i','4i')
for suffix in FLOAT_UNIFORM_SUFFIXES + INT_UNIFORM_SUFFIXES:
	_uniformCls( suffix )

class ShaderURLField( fieldtypes.MFString ):
	"""Field for managing interactions with a Shader's URL value"""
	fieldType = "MFString"
	def fset( self, client, value, notify=1 ):
		"""Set the client's URL, then try to load the image"""
		value = super(ShaderURLField, self).fset( client, value, notify )
		import threading
		threading.Thread(
			name = "Background load of %s"%(value),
			target = self.loadBackground,
			args = ( client, value, context.Context.allContexts,),
		).start()
		return value
	def loadBackground( self, client, url, contexts ):
		from OpenGLContext.loaders.loader import Loader, loader_log
		try:
			baseNode = protofunctions.root(client)
			if baseNode:
				baseURI = baseNode.baseURI
			else:
				baseURI = None
			result = Loader( url, baseURL = baseURI )
		except IOError:
			pass
		else:
			if result:
				baseURL, filename, file, headers = result
				client.source = file.read()
				for context in contexts:
					c = context()
					if c:
						c.triggerRedraw(1)
				return
		
		# should set client.image to something here to indicate
		# failure to the user.
		log.warn( """Unable to load any shader from the url %s for the node %s""", url, str(client))


class GLSLShader( shaders.GLSLShader ):
	"""GLSL-based shader node"""
	url = ShaderURLField( 'url', 'MFString', 1)
	def compile(self, holder):
		holder.depend( self,  'source')
		holder.depend( self,  'type')
		if not self.source:
			return False
		if self.type == 'VERTEX':
			return compileShader(
				self.source, 
				GL_VERTEX_SHADER_ARB
			)
		elif self.type == 'FRAGMENT':
			return compileShader(
				self.source, GL_FRAGMENT_SHADER_ARB
			)
		else:
			log.error(
				'Unknown shader type: %s in %s', 
				self.type, 
				self, 
			)
			return None

class GLSLObject( shaders.GLSLObject ):
	"""GLSL-based shader object (compiled set of shaders)"""
	IMPLEMENTATION = 'GLSL'
	shapeMap = {
	}
	def render( self, mode ):
		"""Render this shader in the current mode"""
		renderer = mode.cache.getData(self)
		if not renderer:
			renderer = self.compile( mode )
		if renderer:
			try:
				glUseProgram( renderer )
			except error.GLError, err:
				log.error( '''Failure compiling: %s''', self.toString()[:50] )
				raise
			else:
				for uniform in self.uniforms:
					uniform.render( self, renderer, mode )
				# TODO: retrieve maximum texture count and restrict to that...
				i = 0
				for texture in self.textures:
					if texture.render( self, renderer, mode, i ):
						i += 1
				for attribute in self.attributes:
					attribute.render( self, renderer, mode )
		return True,True,True,renderer 
		
	def compile(self, mode):
		"""Compile into GLSL linked object"""
		holder = mode.cache.getHolder(self)
		if holder is None:
			holder = mode.cache.holder(self,None)
		holder.depend( self,  'shaders' )
		program = glCreateProgram()
		subShaders = []
		for shader in self.shaders:
			# TODO: cache links...
			subShader = shader.compile(holder)
			if subShader:
				glAttachShader(program, subShader )
				subShaders.append( subShader )
			elif shader.source:
				log.info( 'Failure compiling: %s', shader )
		if len(subShaders) == len(self.shaders):
			glValidateProgram( program )
			warnings = glGetProgramInfoLog( program )
			if warnings:
				log.error( 'Shader compile log: %s', warnings )
			glLinkProgram(program)
			for subShader in subShaders:
				glDeleteShader( subShader )
			holder.data = program
			return program
		holder.data = 0
		return None
	def program( self, mode ):
		"""Retrieve our program ID"""
		return mode.cache.getData( self )
	def renderPost( self, token, mode ):
		"""Post-render cleanup..."""
		if token:
			glUseProgram( 0 )
	def getVariable( self, name ):
		"""Retrieve uniform/attribute by name"""
		for uniform in self.uniforms:
			if uniform.name == name:
				return uniform 
		return None
		
class Shader( shaders.Shader ):
	"""Shader is a programmable substitute for an Appearance node"""
	current = field.newField( ' current','SFNode',1, node.NULL )
	uniformIDs = None
	attributeIDs = None
	def render (self, mode=None):
		"""Render the shader"""
		current = self.current
		if not current:
			for object in self.objects:
				if object.IMPLEMENTATION == 'GLSL':
					self.current = current = object 
		if current:
			return current.render( mode )
		else:
			return True,True,True,None
	def renderPost( self, textureToken=None, mode=None ):
		"""Cleanup after rendering of this node has completed"""
		if self.current:
			return self.current.renderPost( textureToken, mode )

