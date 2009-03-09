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
from vrml.vrml97 import shaders
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
		shader_log = glGetShaderInfoLog( vertexShader )
		if shader_log:
			log.info( '''Shader compilation generated log: %s''', shader_log )
		glAttachShader(program, vertexShader)
	else:
		vertexShader = None
	if fragmentSource:
		fragmentShader = compileShader(
			fragmentSource, GL_FRAGMENT_SHADER_ARB
		)
		shader_log = glGetShaderInfoLog( fragmentShader )
		if shader_log:
			log.info( '''Shader compilation generated log: %s''', shader_log )
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
	return shader

class FloatUniform( shaders.FloatUniform ):
	"""Uniform (variable) binding for a shader
	"""
	
class IntUniform( shaders.IntUniform ):
	"""Uniform (variable) binding for a shader (integer form)
	"""
class GLSLShader( shaders.GLSLShader ):
	"""GLSL-based shader node"""
	def compile(self, holder):
		holder.depend( self,  'source')
		holder.depend( self,  'type')
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
	def compile(self, holder):
		"""Compile into GLSL linked object"""
		holder.depend( self,  'shaders' )
		program = glCreateProgram()
		subShaders = []
		for shader in self.shaders:
			# TODO: cache links...
			subShader = shader.compile(holder)
			if subShader:
				glAttachShader(program, subShader )
				subShaders.append( subShader )
			else:
				log.warn( 'Failure compiling: %s', shader )
		glValidateProgram( program )
		warnings = glGetProgramInfoLog( program )
		if warnings:
			log.error( 'Shader compile log: %s', warnings )
		glLinkProgram(program)
		for subShader in subShaders:
			glDeleteShader( subShader )
		return program
		
class Shader( shaders.Shader ):
	"""Shader is a programmable substitute for an Appearance node"""
	def render (self, mode=None):
		"""Render the shader"""
		renderer = mode.cache.getData(self)
		if renderer is None:
			renderer = self.compile( mode )
		if renderer:
			try:
				glUseProgram( renderer )
			except error.GLError, err:
				log.error( '''Failure compiling: %s''', self.toString() )
				raise
		return True, True, True, renderer
	def compile(self,  mode ):
		holder = mode.cache.holder(self,None)
		for object in self.objects:
			if object.IMPLEMENTATION == 'GLSL':
				renderer = object.compile(holder)
				if renderer:
					holder.data = renderer 
					return renderer
			# TODO: invalidate holder here...
		log.warn( 'Shader not loaded' )
	def renderPost( self, textureToken=None, mode=None ):
		"""Cleanup after rendering of this node has completed"""
		if textureToken: # actually program...
			glUseProgram( 0 )
