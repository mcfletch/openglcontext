#! /usr/bin/env python
"""Script to automatically generate OpenGLContext documentation"""
import gldoc, pydoc2

if __name__ == "__main__":
    excludes = [
        "wx",
        "Numeric",
        "numpy",
        "_tkinter",
        "Tkinter",
        "math",
        "string",
        "pygame",
        "pygame.locals",
    ]
    modules = [
        "OpenGLContext",
        "OpenGLContext_qt",
        "wx.glcanvas",
        "vrml",
        "vrml_accelerate",
        'logging',
        "OpenGL",
        "OpenGL_accelerate",
        "ttfquery",
        "simpleparse",
        "fontTools",
        "numpy",
    ]	
    pydoc2.PackageDocumentationGenerator(
        baseModules = modules,
        destinationDirectory = ".",
        exclusions = excludes,
        #recursionStops = stops,
        formatter = gldoc.GLFormatter(),
    ).process ()
    