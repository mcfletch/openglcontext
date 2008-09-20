#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
from OpenGLContext.testingcontext import getInteractive
BaseContext, MainFunction = getInteractive()
import sys

class TestContext( 
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
	import sys, cProfile
	if not sys.argv[1:2]:
		print usage
		sys.exit(1)
	return cProfile.run( "MainFunction ( TestContext)", 'OpenGLContext.profile' )


if __name__ == "__main__":
	main()
