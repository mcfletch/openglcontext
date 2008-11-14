#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
import OpenGL 
OpenGL.ERROR_CHECKING = False 
#OpenGL.ERROR_ON_COPY = True
from OpenGLContext.testingcontext import getInteractive
BaseContext, MainFunction = getInteractive()
from OpenGLContext import vrmlcontext
import sys

class TestContext( 
	vrmlcontext.VRMLContext, 
	BaseContext 
):
	"""VRML97-loading Context testing class"""
	def OnInit( self ):
		"""Load the image on initial load of the application"""
		filename = sys.argv[1]
		self.load( filename )
		vrmlcontext.VRMLContext.OnInit( self )
		BaseContext.OnInit( self )

def main():
	usage = """vrml_view.py myscene.wrl

	A very limited VRML97 viewer which saves profile results
	to OpenGLContext.profile using the cProfile module.
	"""
	import sys, os, cProfile
	if not sys.argv[1:2]:
		print usage
		sys.exit(1)
	try:
		from lsprofcalltree import KCacheGrind
	except ImportError, err:
		return cProfile.run( 
			"MainFunction ( TestContext)", 'OpenGLContext.profile' 
		)
	else:
		PROFILER = cProfile.Profile()
		def top( ):
			return MainFunction( TestContext )
		PROFILER.runcall( top )
		def newfile( base ):
			new = base 
			count = 0
			while os.path.isfile( new ):
				new = '%s-%s'%( base, count )
				count += 1
			return new
		KCacheGrind( PROFILER ).output( open(
			newfile( 'callgrind.out' ), 'wb'
		))


if __name__ == "__main__":
	main()