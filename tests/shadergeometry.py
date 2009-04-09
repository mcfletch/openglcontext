#! /usr/bin/env python
'''Tests rendering using the ARB shader objects extension...
'''
import OpenGL 
OpenGL.FULL_LOGGING = True
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGLContext.arrays import array
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.shaders import *
import time, sys,logging,math
log = logging.getLogger( 'shaderobjects' )
log.warn( 'Context %s',  BaseContext )

logging.getLogger( 'OpenGLContext.scenegraph.shaders' ).setLevel( logging.DEBUG )

class TestContext( BaseContext ):
	rotation = 0.00
	
	current_shader = 0
	
	def OnInit( self ):
		"""Scene set up and initial processing"""
		buffer = ShaderBuffer(
			buffer = [ 
				[  0, 1, 0,  0,1,0 ],
				[ -1,-1, 0,  1,1,0 ],
				[  1,-1, 0,  0,1,1 ],
				
				[  2,-1, 0,  1,0,0 ],
				[  4,-1, 0,  0,1,0 ],
				[  4, 1, 0,  0,0,1 ],
				[  2,-1, 0,  1,0,0 ],
				[  4, 1, 0,  0,0,1 ],
				[  2, 1, 0,  0,1,1 ],
			],
		)
		self.sg = sceneGraph(
			children = [
				Transform(
#					translation = (0,5,0),
					children = [
					ShaderGeometry(
						# test of shader geometry "shape" type...
						DEF = 'ShaderGeom',
						slices = [
							ShaderSlice( 
								offset=0,
								count=9,
							),
						],
						attributes = [
							ShaderAttribute(
								name = 'position',
								offset = 0,
								stride = 24,
								size = 3,
								dataType = 'FLOAT',
								buffer = buffer,
							),
							ShaderAttribute(
								name = 'Color',
								offset = 12,
								stride = 24,
								size = 3,
								dataType = 'FLOAT',
								buffer = buffer,
							),
						],
						appearance = 	Shader(
							objects = [GLSLObject(
								DEF = 'ShaderGeom_shader',
								shaders = [
									GLSLShader( 
										source = [
											"""
			attribute vec3 position;
			attribute vec3 Color;
			varying vec4 baseColor;
			void main() {
				gl_Position = gl_ModelViewProjectionMatrix * vec4( position,1.0);
				baseColor = vec4(Color,1.0);
			}""",
										],
										type = "VERTEX",
									),
									GLSLShader(
										source = ["""varying vec4 baseColor;
			void main() { 
				gl_FragColor = baseColor;
			}"""],
										type = "FRAGMENT",
									),
								],
							),]
						),
					),],
				),
			],
		)

if __name__ == "__main__":
	MainFunction ( TestContext)

