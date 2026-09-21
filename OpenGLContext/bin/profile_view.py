#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
import os

# Before anything imports an API namespace: the entry points are built with
# whatever error checking was configured when PyOpenGL first read its
# settings, so an assignment after that has no effect and says so.
os.environ.setdefault('PYOPENGL_ERROR_CHECKING', '0')

from typing import Any                                       # noqa: E402
from OpenGLContext import testingcontext                     # noqa: E402
#: The backend is chosen at run time, so the class this subclasses is not
#: one a checker can name -- which is what Any says here.
BaseContext: Any = testingcontext.getInteractive()
from OpenGLContext import vrmlcontext
import sys

class TestContext( 
    vrmlcontext.VRMLContext, 
    BaseContext 
):
    """VRML97-loading Context testing class"""
    def OnInit( self ) -> None:
        """Load the image on initial load of the application"""
        filename = sys.argv[1]
        self.load( filename )
        vrmlcontext.VRMLContext.OnInit( self )
        BaseContext.OnInit( self )

def main() -> None:
    usage = """python -m OpenGLContext.bin.profile_view myscene.wrl

    A VRML97 viewer which writes cProfile results to a file named
    OpenGLContext.profile in the working directory.  Not a console
    script: oglc-view is the viewer, and this is the profiling harness
    behind it.
    """
    import sys
    import cProfile
    if not sys.argv[1:2]:
        print(usage)
        sys.exit(1)
    cProfile.run(
        "TestContext.ContextMainLoop()", 'OpenGLContext.profile'
    )

if __name__ == "__main__":
    main()
