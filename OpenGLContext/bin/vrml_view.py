#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
import OpenGL 
#OpenGL.FULL_LOGGING = True
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
    usage = """vrml_view.py myscene.wrl

    A very limited VRML97 viewer.
    """
    import sys
    if not sys.argv[1:2]:
        print usage
        sys.exit(1)
    return TestContext.ContextMainLoop()


if __name__ == "__main__":
    main()