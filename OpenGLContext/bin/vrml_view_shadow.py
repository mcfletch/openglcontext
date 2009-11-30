#! /usr/bin/env python
"""Shadow-casting version of the VRML-viewing demonstration

This version of the VRML-viewing demonstration functions as
a demonstration of the shadow-casting package.
"""
from OpenGLContext.bin import vrml_view
from OpenGLContext.shadow import shadowcontext

class TestContext( shadowcontext.ShadowContext, vrml_view.TestContext ):
    """Shadow-enabled testing context"""


if __name__ == "__main__":
    usage = """vrml_view_shadow.py myscene.wrl

    Attempts to view the file myscene.wrl as a VRML97
    file within a shadow-casting viewer/window.
    """
    import sys
    if not sys.argv[1:2]:
        print usage
        sys.exit(1)
    TestContext.ContextMainLoop()
