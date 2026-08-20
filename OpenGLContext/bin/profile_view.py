#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
import OpenGL 
OpenGL.ERROR_CHECKING = False 
#OpenGL.ERROR_ON_COPY = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
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
    usage = """python -m OpenGLContext.bin.profile_view myscene.wrl

    A VRML97 viewer which writes cProfile results to a file named
    OpenGLContext.profile in the working directory.  Not a console
    script: oglc-view is the viewer, and this is the profiling harness
    behind it.
    """
    import sys, cProfile
    if not sys.argv[1:2]:
        print(usage)
        sys.exit(1)
    return cProfile.run( 
        "TestContext.ContextMainLoop()", 'OpenGLContext.profile' 
    )

if __name__ == "__main__":
    main()
