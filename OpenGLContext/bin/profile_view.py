#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
import OpenGL

# The package has been imported by now (OpenGLContext imports it), so its
# environment variables have been read. The package attribute is still read:
# PyOpenGL's flags module copies it when the first API namespace imports that
# module, and the entry points are built with whatever it copied. Measuring
# the engine rather than the per-call glGetError is what this harness is for.
OpenGL.ERROR_CHECKING = False

from typing import Any
from OpenGLContext import testingcontext
#: The backend is chosen at run time, so the class this subclasses is not
#: one a checker can name -- which is what Any says here.
BaseContext: Any = testingcontext.getInteractive()
import sys

class TestContext( BaseContext ):
    """VRML97-loading Context testing class"""
    def OnInit( self ) -> None:
        """Load the image on initial load of the application"""
        filename = sys.argv[1]
        self.load( filename )
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
