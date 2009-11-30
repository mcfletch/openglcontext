#! /usr/bin/env python
"""VRML-viewing context that only renders ambient-lighting"""
from OpenGLContext.bin import vrml_view
from OpenGLContext.shadow import passes

class TestContext( vrml_view.TestContext ):
    """VRML-viewing context that only renders ambient-lighting"""
    renderPasses = passes.ambientRenderPass

if __name__ == "__main__":
    usage = """vrml_view.py myscene.wrl

    A very limited VRML97 viewer.  Requires OpenGLContext and
    the mcf.vrml processing libraries.  Does not support
    prototypes, scripts, or many of the primitive geometry types.
    """
    import sys
    if not sys.argv[1:2]:
        print usage
        sys.exit(1)
    TestContext.ContextMainLoop()


