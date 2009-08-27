#! /usr/bin/env python
'''=First steps (Basic Geometry)=

[shader_1.py-screen-0001.png Screenshot]

In this tutorial we'll learn:

	* What a vertex shader *must* do in GLSL.
	* What a fragment shader *must* do.
	* What a VBO object looks like.
	* How to activate and deactivate shaders and VBOs.
	* How to render simple geometry.

First we do our imports, the [http://pyopengl.sourceforge.net/context OpenGLContext] testingcontext allows
for the use of Pygame, wxPython, or GLUT GUI systems with the same 
code.  These imports retrieve an appropriate context for this 
machine.  If you have not installed any "extra" packages, such as 
Pygame or wxPython, this will likely be a GLUT context on your 
machine.
'''
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
'''Now we import the PyOpenGL functionality we'll be using.

OpenGL.GL contains the standard OpenGL functions that you can 
read about in the PyOpenGL man pages.
'''
from OpenGL.GL import *
'''The OpenGL.arrays.vbo.VBO class is a convenience wrapper 
which makes it easier to use Vertex Buffer Objects from within 
PyOpenGL.  It takes care of determining which implementation 
to use, the creation of offset objects, and even basic slice-based 
updating of the content in the VBO.'''
from OpenGL.arrays import vbo
'''OpenGLContext.arrays is just an abstraction point which imports 
either Numpy (preferred) or the older Numeric library 
with a number of compatability functions to make Numeric look like 
the newer Numpy module.'''
from OpenGLContext.arrays import *
'''OpenGL.GL.shaders is a convenience library for accessing the 
shader functionality.'''
from OpenGL.GL.shaders import *

'''OpenGLContext contexts are all sub-classes of Context, with 
various mix-ins providing support for different windowing classes,
different interaction mechanisms and the like.  BaseContext here 
is the TestingContext we imported above.'''
class TestContext( BaseContext ):
	"""Creates a simple vertex shader..."""
	'''The OnInit method is called *after* there is a valid
	OpenGL rendering Context.  You must be very careful not 
	to call (most) OpenGL entry points until the OpenGL context 
	has been created (failure to observe this will often cause 
	segfaults or other extreme behaviour).
	'''
	def OnInit( self ):
		'''The OpenGL.GL.shaders.compileProgram function is a
		convenience function which performs a number of base 
		operations using to abstract away much of the complexity 
		of shader setup.  GLSL Shaders started as extensions to OpenGL
		and later became part of Core OpenGL, but some drivers 
		will not support the "core" versions of the shader APIs.
		This extension mechanism is the "normal" way to extend 
		OpenGL, but it makes for messy APIs.
		
		Each "shader program" consists of a number of simpler 
		components "shaders" which are linked together.  There are 
		two common shader types at the moment, the vertex and fragment 
		shaders.  Newer hardware may include other shader types, such 
		as geometry shaders.
		
		=Vertex Shader=
		
		Our first shader is the VERTEX_SHADER, which must calculate
		a vertex position for each vertex which is to be generated.
		Normally this is one vertex for each vertex we pass into the 
		GL, but with geometry shaders and the like more vertices could 
		be created.
		
		A vertex shader only needs to do one thing, which is to 
		generate a gl_Position value, which must be a vec4() type.
		With legacy OpenGL (which we are using here), the gl_Position
		is generally calculated by using the built-in variable "gl_Vertex",
		which is a vec4() which represents the vertex generated by 
		the fixed-function rendering pipeline.
		
		Most OpenGL programs tend to use a perspective projection 
		matrix to transform the model-space coordinates of a cartesian 
		model into the "view coordinate" space of the screen.  Legacy
		OpenGL included functions which would manipulate these matrices
		via "translation", "rotation", "scaling" and the like.  Modern 
		OpenGL programmers are expected the calculate the matrices 
		themselves (or have a library that does it for them).
		
		Here we are just going to use OpenGLContext's built-in matrix
		calculation which will set up the "model-view matrix" for us 
		as a simple perspective transformation.
		
		The final vertex position in view coordinates is calculated 
		with a simple dot-product of the model-view matrix and the
		vertex to be transformed.  The main() function is defined using 
		the C-like GLSL syntax to return nothing (void).  Each of the 
		variables used here is a (built-in) global, so we don't have 
		to declare their data-types.
		
		The OpenGL.GL.shaders.compileShader function 
		compiles the shader and checks for any compilation errors.
		(Using glCreateShader, glShaderSource, and glCompileShader).
		'''
		VERTEX_SHADER = compileShader("""
		void main() {
			gl_Position = gl_ModelViewProjectionMatrix * gl_Vertex;
		}""", GL_VERTEX_SHADER)
		'''After a vertex is processed by the vertex shader, it passes 
		through a number of fixed-function processes, including the 
		"clipping" process, which may turn a single vertex into multiple
		vertices in order to only render geometry "ahead" of the near 
		clipping plane.
		
		Thus if a triangle is "poking into your eye" the GL will
		generate two vertices that are at the points where the 
		triangle intersects the near clipping plane and create 3
		triangles from the original one triangle (the same is true of 
		all of the clipping plans for the frustum).
		
		=Fragment Shader=
		
		The fixed-function operations will generate "fragments", which 
		can be loosely thought of as a "possible pixel". They may 
		represent a sub-sampling interpolation value, or a value that 
		will eventually be hidden behind another pixel (overdrawn).
		Our renderer will be given a (large number of) fragments each 
		of which will have a position calculated based on the area 
		of the triangle vertices (gl_Position values) that our vertex 
		shader generated.
		
		The fragment shader only *needs* to do one thing, which is to 
		generate a gl_FragColor value, that is, to determine what colour 
		the fragment should be.  The shader can also decide to write 
		different colours to different colour buffers, or even change 
		the position of the fragment, but its primary job is simply 
		to determine the colour of the pixel (a vec4() value).
		
		In our code here, we create a new colour for each pixel, which 
		is a pure green opaque (the last 1) value.  We assign the value 
		to the (global, built-in) gl_FragColor value and we are finished.
		'''
		FRAGMENT_SHADER = compileShader("""
		void main() {
			gl_FragColor = vec4( 0, 1, 0, 1 );
		}""", GL_FRAGMENT_SHADER)
		'''Now that we have defined our shaders, we need to compile them 
		into a program on our video card which can be applied to geometry.
		The compileProgram convenience function does these operations:
		
			* creates a shader "program" (glCreateProgram)
			* for each of the shaders provided
				* attaches the shader to the program 
			* links the program (glLinkProgram)
			* validates the program (glValidateProgram,glGetProgramiv)
			* cleans up and returns the shader program
		
		The shader program is an opaque GLuint that is used to refer 
		to the shader when speaking to the GL.  With this, we have 
		created an OpenGL shader, now we just need to give it something 
		to render.
		'''
		self.shader = compileProgram(VERTEX_SHADER,FRAGMENT_SHADER)
		'''=Vertex Buffer Data Objects (VBOs)=
		
		Modern OpenGL wants you to load your data onto your video 
		card as much as possible.  For geometric data, this is generally 
		done via a Vertex Buffer Object.  These are flexible data-storage
		areas reserved on the card, with various strategies available
		for streaming data in/out.
		
		For our purposes we can think of the VBO as a place on the card
		to which we are going to copy our vertex-description data.  We'll
		use a Numpy array to define this data, as it's a convenient format
		for dealing with large arrays of numeric values.
		
		Modern cards work best with a format where all of the data
		associated with a single vertex is "tightly packed" into a VBO,
		so each record in the array here represents all of the data 
		needed to render a single vertex.  Since our shader only needs 
		the vertex coordinate to do its rendering, we'll use 3
		floating-point values.  (Note: not doubles, as in a Python
		float, but 3 machine floating point values).
		
		Modern OpenGL only supports triangle and point-type geometry,
		so the simplest form of drawing (though not necessarily the 
		fastest) is to specify each vertex of a set of triangles in 
		order.  Here we create one triangle and what looks like a 
		square to the viewer (two triangles with two shared vertices).
		
		The vbo.VBO class simply takes an array-compatible format and 
		stores the value to be pushed to the card later.  It also takes 
		various flags to control the more advanced features, but we'll 
		look at those later.
		'''
		self.vbo = vbo.VBO(
			array( [
				[  0, 1, 0 ],
				[ -1,-1, 0 ],
				[  1,-1, 0 ],
				
				[  2,-1, 0 ],
				[  4,-1, 0 ],
				[  4, 1, 0 ],
				[  2,-1, 0 ],
				[  4, 1, 0 ],
				[  2, 1, 0 ],
			],'f')
		)
		'''We've now completed our application initialization, we 
		have our shaders compiled and our VBO ready-to-render.  Now 
		we need to actually tell OpenGLContext how to render our scene.
		The Render() method of the context is called after all of the 
		boilerplate OpenGL setup has been completed and the scene 
		should be rendered in model-space.  OpenGLContext has created 
		a default Model-View matrix for a perspective scene where the 
		camera is sitting 10 units from the origin.  It has cleared the 
		screen to white and is ready to accept rendering commands.
		'''
	def Render( self, mode):
		"""Render the geometry for the scene."""
		'''=Rendering=
		
		We tell OpenGL to use our compiled shader, this is 
		a simple GLuint that is an opaque token that describes the shader 
		for OpenGL.  Until we Use the shader, the GL is using the 
		fixed-function (legacy) rendering pipeline.
		'''
		glUseProgram(self.shader)
		'''Now we tell OpenGL that we want to enable our VBO as the 
		source for geometric data.  There are two VBO types that can 
		be active at any given time, a geometric data buffer and an 
		index buffer, the default here is the geometric buffer.
		'''
		try:
			self.vbo.bind()
			try:
				'''Here we tell OpenGL to process vertex (location) data 
				from our vertex pointer (here we pass the VBO).  The VBO 
				acts just like regular array data, save that it is stored 
				on the card, rather than in main memory.  The VBO object 
				is actually passing in a void pointer (None) for the array 
				pointer, as the start of the enabled VBO is taken as 
				the 0 address for the arrays.
				
				Note the use here of the "typed" glVertexPointerf function,
				while this is a convenient form for this particular
				tutorial, most VBO-based rendering will use the standard 
				form which includes specifying offsets, data-types,
				strides, and the like for interpreting the array.  We 
				will see the more involved form in the next tutorial.
				'''
				glEnableClientState(GL_VERTEX_ARRAY);
				glVertexPointerf( self.vbo )
				'''Finally we actually tell OpenGL to draw some geometry.
				Here we tell OpenGL to draw triangles using vertices, 
				starting with the offset 0 and continuing for 9 vertices
				(that is, three triangles).  glDrawArrays always draws 
				"in sequence" from the vertex array.  We'll look at using 
				indexed drawing functions later.
				'''
				glDrawArrays(GL_TRIANGLES, 0, 9)
				'''Having completed rendering our geometry, we clean up 
				the OpenGL environment.  We unbind our vbo, so that any 
				traditional non-VBO-using code can operate, and unbind 
				our shader so that geometry that uses the fixed-function 
				(legacy) rendering behaviour will work properly.
				'''
			finally:
				self.vbo.unbind()
				glDisableClientState(GL_VERTEX_ARRAY);
		finally:
			glUseProgram( 0 )
'''We need to actually run the code when operating as a top-level 
script.  The TestingContext import above also gave us an appropriate
mainloop function to call.'''

if __name__ == "__main__":
	MainFunction ( TestContext)
'''
When run from the command-line, we should see a triangle and a 
rectangle in solid green floating over a white background, as seen
in our screenshot above.

Terms:

	frustum -- the viewing "stage" of your world, i.e. the part 
		of the world which is visible to the "camera", includes 
		a near and far clipping plane, as well as clipping planes 
		for the left, right, top and bottom
	
	GLSL -- the OpenGL Shading Language, there are two levels 
		of shading language defined within OpenGL, the earlier of 
		the two is a low-level assembly-like language.  The later,
		GLSL is a slightly higher-level C-like language, this is 
		the language we will be using in these tutorials.  There 
		are also third-party languages, such as Cg, which can 
		compile the same source-code down to e.g. 
		DirectX and/or OpenGL renderers.

	legacy -- OpenGL is an old standard, the traditional API has 
		been largely deprecated by the OpenGL standards board, the 
		vendors generally support the old APIs, but their use is 
		officially discouraged.  The Legacy APIs had a single 
		rendering model which was customized via a large number of 
		global state values.  The new APIs are considerably more 
		flexible, but require somewhat more effort to use.
'''
