#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test"""
import sys
from typing import Any


def profiled_context() -> Any:
    """The viewer's Context class, made with PyOpenGL's error checking off.

    Measuring the engine rather than the per-call glGetError is what this
    harness is for.  PyOpenGL's flags module copies ``OpenGL.ERROR_CHECKING``
    when the first API namespace imports it, so the switch is thrown here,
    before the backend is imported; importing this module sets nothing.
    """
    import OpenGL  # noqa: PLC0415 configured before anything imports an API namespace

    OpenGL.ERROR_CHECKING = False
    from OpenGLContext import testingcontext  # noqa: PLC0415 imports OpenGL.GL, so after the switch

    #: The backend is chosen at run time, so the class this subclasses is not
    #: one a checker can name -- which is what Any says here.
    BaseContext: Any = testingcontext.getInteractive()

    class TestContext( BaseContext ):
        """VRML97-loading Context testing class"""
        def OnInit( self ) -> None:
            """Load the image on initial load of the application"""
            BaseContext.OnInit( self )
            self.sceneLoader.load( sys.argv[1], on_loaded=self.OnLoaded )

        def OnLoaded( self, request: Any ) -> None:
            """Mount the scene once the loader has read it"""
            self.sg = request.result

    return TestContext

def main() -> None:
    usage = """python -m OpenGLContext.bin.profile_view myscene.wrl

    A VRML97 viewer which writes cProfile results to a file named
    OpenGLContext.profile in the working directory.  Not a console
    script: oglc-view is the viewer, and this is the profiling harness
    behind it.
    """
    import cProfile
    if not sys.argv[1:2]:
        print(usage)
        sys.exit(1)
    TestContext = profiled_context()
    cProfile.runctx(
        "TestContext.ContextMainLoop()",
        globals(),
        {'TestContext': TestContext},
        'OpenGLContext.profile',
    )

if __name__ == "__main__":
    main()
