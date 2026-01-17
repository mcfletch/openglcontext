#!/usr/bin/env python
"""Teapot rendering regression test.

This test renders a teapot and compares the output between compatibility
(legacy GLUT) and core (embedded mesh) rendering modes.

Usage:
    # Record reference image (compatibility mode with GLUT teapot)
    OPENGLCONTEXT_PROFILE=compatibility python tests/teapot_comparison.py --record --exit-after

    # Test against reference (core mode with embedded mesh)
    OPENGLCONTEXT_PROFILE=core OPENGLCONTEXT_BACKEND=glfw python tests/teapot_comparison.py --test --exit-after

    # Run full automated comparison (legacy first, then core)
    python tests/teapot_comparison.py --run-comparison

    # Interactive mode (no flags) - just view the teapot
    python tests/teapot_comparison.py

Command-line options:
    --record          Save current render as reference image
    --test            Test current render against saved reference
    --run-comparison  Run full comparison (record with legacy, test with core)
    --output-dir DIR  Directory for reference/result/diff images
    --capture-delay N Seconds to wait before capture (default 0.5)
    --hud-height N    Pixels to exclude from top for HUD (default 40)
    --exit-after      Exit after capture/test completes
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.framebuffer_comparison import (
    AutomatedRegressionContext, RegressionTestRunner
)


class TeapotComparisonContext(AutomatedRegressionContext, BaseContext):
    """Context for teapot regression testing."""

    test_name = "teapot_regression"

    def OnInit(self):
        """Set up the scene with a teapot."""
        # Set up automated regression testing
        self.setup_regression_test()

        profile = getattr(self.contextDefinition, 'profile', 'unknown')
        print(f"Teapot Regression Test - Profile: {profile}")

        # Single teapot centered in view
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.DirectionalLight(
                    direction=(0.5, -1, -0.5),
                    color=(1, 1, 1),
                    intensity=1.0,
                ),
                basenodes.Transform(
                    children=[
                        basenodes.Shape(
                            geometry=basenodes.Teapot(size=1.0, solid=True),
                            appearance=basenodes.Appearance(
                                material=basenodes.Material(
                                    diffuseColor=(0.7, 0.3, 0.2),
                                    specularColor=(1, 1, 1),
                                    shininess=0.8,
                                ),
                            ),
                        ),
                    ],
                ),
                basenodes.Background(
                    skyColor=[(0.2, 0.2, 0.3)],
                ),
            ],
        )

        # Camera position
        self.platform = self.getViewPlatform()
        self.platform.setPosition((0, 1.5, 6))
        self.platform.setOrientation((1, 0, 0, -0.15))

    def OnDraw(self, force=1, *arguments):
        """Draw the scene and check for regression capture."""
        result = super().OnDraw(force, *arguments)
        self._check_regression_capture()
        return result


def run_comparison():
    """Run full comparison between legacy and core rendering."""
    runner = RegressionTestRunner(
        test_name='teapot_regression',
        context_class=TeapotComparisonContext,
    )
    success = runner.run_comparison()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    # Check for --run-comparison flag
    if '--run-comparison' in sys.argv:
        sys.argv.remove('--run-comparison')
        run_comparison()
    else:
        TeapotComparisonContext.ContextMainLoop()
