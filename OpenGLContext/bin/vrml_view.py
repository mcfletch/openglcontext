#! /usr/bin/env python
"""VRML97 load-and-view demonstration/test

Usage:
    vrml_view.py [--shaders] myscene.wrl

Options:
    --shaders    Use shader-based rendering (core-profile compatible)
                 instead of legacy fixed-function pipeline

A very limited VRML97 viewer.

Environment:
    OPENGLCONTEXT_PROFILE=core    Automatically enables shader rendering
"""
import argparse
import os
import OpenGL
#OpenGL.FULL_LOGGING = True
OpenGL.ERROR_CHECKING = False
#OpenGL.ERROR_ON_COPY = True
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext import vrmlcontext

# Global flag for shader mode - default based on profile
USE_SHADERS = os.environ.get('OPENGLCONTEXT_PROFILE', 'compatibility') == 'core'


class TestContext(
    vrmlcontext.VRMLContext,
    BaseContext
):
    """VRML97-loading Context testing class"""

    _shader_mode_enabled = False

    def OnInit(self):
        """Load the image on initial load of the application"""
        # Get filename from parsed args
        filename = getattr(self, '_vrml_file', None)
        if filename:
            self.load(filename)
        vrmlcontext.VRMLContext.OnInit(self)
        BaseContext.OnInit(self)

    def Redraw(self, *args, **kwargs):
        """Override to enable shader mode on first render."""
        # Enable shader mode on first redraw when FLAT exists
        if USE_SHADERS and not TestContext._shader_mode_enabled:
            self._enable_shader_mode()
        return super().Redraw(*args, **kwargs)

    def _enable_shader_mode(self):
        """Enable shader-based rendering on the FlatPass."""
        from OpenGLContext.passes import renderpass
        if renderpass.FLAT is not None:
            renderpass.FLAT.use_shaders = True
            TestContext._shader_mode_enabled = True
            print(f"Enabled shader mode on {renderpass.FLAT.__class__.__name__}")


def main():
    parser = argparse.ArgumentParser(
        description='VRML97 load-and-view demonstration/test',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    vrml_view.py scene.wrl           # Use legacy fixed-function rendering
    vrml_view.py --shaders scene.wrl # Use shader-based rendering

    # Or set environment variable for automatic shader mode:
    OPENGLCONTEXT_PROFILE=core vrml_view.py scene.wrl
        """
    )
    parser.add_argument(
        '--shaders',
        action='store_true',
        default=None,
        help='Use shader-based rendering (core-profile compatible). '
             'Automatically enabled when OPENGLCONTEXT_PROFILE=core'
    )
    parser.add_argument(
        '--no-shaders',
        action='store_true',
        help='Force legacy fixed-function rendering even with core profile'
    )
    parser.add_argument(
        'file',
        help='VRML97 file to load (.wrl)'
    )

    args = parser.parse_args()

    global USE_SHADERS
    # Priority: --no-shaders > --shaders > environment-based default
    if args.no_shaders:
        USE_SHADERS = False
    elif args.shaders:
        USE_SHADERS = True
    # else: USE_SHADERS keeps its environment-based default

    # Store filename for TestContext to access
    TestContext._vrml_file = args.file

    if USE_SHADERS:
        print("Using shader-based rendering (GLSL 3.30)", flush=True)
    else:
        print("Using legacy fixed-function rendering", flush=True)

    return TestContext.ContextMainLoop()


if __name__ == "__main__":
    main()
