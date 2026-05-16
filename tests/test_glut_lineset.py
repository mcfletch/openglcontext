#!/usr/bin/env python
"""Test IndexedLineSet rendering with GLUT backend specifically.

This test checks if IndexedLineSet renders correctly in GLUT's compatibility
profile using the legacy display list rendering path.
"""
import os
import sys

# Force GLUT backend
os.environ['OPENGLCONTEXT_BACKEND'] = 'glut'

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.arrays import arange, zeros, sin, cos
import math

class TestContext(BaseContext):
    """Test context for IndexedLineSet with GLUT backend."""
    initialPosition = (0, 0, 3)

    def OnInit(self):
        """Create a simple colored circle using IndexedLineSet."""
        # Create a circular IndexedLineSet with per-vertex colors
        a = arange(0.0, 2 * math.pi, 0.1)  # Fewer points for simpler test
        xes = sin(a)
        yes = cos(a)
        coords = zeros((len(xes), 3), "d")
        coords[:, 0] = xes
        coords[:, 1] = yes

        # Colors based on position (rainbow-ish)
        colors = zeros((len(xes), 3), "d")
        colors[:, 0] = (xes + 1) / 2  # Red varies with x
        colors[:, 1] = (yes + 1) / 2  # Green varies with y
        colors[:, 2] = 0.5  # Blue constant

        print(f"Creating IndexedLineSet with {len(coords)} vertices")
        print(f"First coord: {coords[0]}")
        print(f"First color: {colors[0]}")
        print(f"Last coord: {coords[-1]}")
        print(f"Last color: {colors[-1]}")

        self.sg = sceneGraph(
            children=[
                Shape(
                    geometry=IndexedLineSet(
                        coord=Coordinate(point=coords),
                        coordIndex=list(range(len(coords))),
                        color=Color(color=colors),
                        colorIndex=list(range(len(coords))),
                    ),
                ),
            ]
        )
        print("OnInit complete - should see a colored circle")
        print("Press 'q' to quit")


if __name__ == "__main__":
    print(f"Backend: {os.environ.get('OPENGLCONTEXT_BACKEND', 'default')}")
    print(f"Profile: {os.environ.get('OPENGLCONTEXT_PROFILE', 'default')}")
    TestContext.ContextMainLoop()
