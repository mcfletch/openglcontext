#! /usr/bin/env python
"""Volumetric Tree Rendering Demo

Demonstrates procedural tree generation using space colonization algorithm
and volumetric rendering via ray-marching through a 3D voxel texture.

The tree is generated once at startup, voxelized into a 3D texture,
and then rendered each frame using a ray-marching fragment shader.
"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.scenegraph.tree import VolumetricTree
import logging

# Enable logging to see tree generation progress
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


class TestContext(BaseContext):
    """Demo context for volumetric tree rendering"""

    initialPosition = (0, 5, 15)  # Camera position to see the tree

    def OnInit(self):
        """Initialize the scene with a volumetric tree"""
        log.info("Initializing volumetric tree demo...")

        # Create a volumetric tree
        self.tree = VolumetricTree(
            # Crown shape and size
            crownShape='sphere',
            crownRadius=2.0,
            crownOffset=2.0,

            # Number of attractors affects branch density
            attractorCount=1000,

            # Material colors
            barkColor=[0.4, 0.25, 0.1],  # Brown bark
            leafColor=[0.2, 0.5, 0.15],  # Green leaves
            leafDensity=0.4,  # More visible leaves
            leafClusterSize=0.12,  # Small clusters

            # Rendering quality - higher resolution for sharper detail
            volumeResolution=96,  # 96^3 voxels for detail
            maxRaySteps=200,  # More steps for smooth traversal
            rayStepSize=0.008,  # Smaller steps to avoid popping
            densityScale=1.2,

            # Random seed (change for different trees)
            seed=42,
        )

        log.info("Tree node created, will compile on first render")

    def Render(self, mode=None):
        """Render the scene"""
        BaseContext.Render(self, mode)

        # Clear with sky blue background
        glClearColor(0.5, 0.7, 0.9, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # Enable depth testing
        glEnable(GL_DEPTH_TEST)

        # Set up basic lighting direction (used by shader)
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)
        glLightfv(GL_LIGHT0, GL_POSITION, [0.5, 1.0, 0.3, 0.0])

        # Draw a simple ground plane
        self._draw_ground()

        # Render the tree
        self.tree.render(mode=mode)

    def _draw_ground(self):
        """Draw a simple ground plane for reference"""
        glDisable(GL_LIGHTING)
        glColor3f(0.3, 0.5, 0.2)  # Green-brown grass

        glBegin(GL_QUADS)
        size = 20.0
        glNormal3f(0, 1, 0)
        glVertex3f(-size, -0.1, -size)
        glVertex3f(size, -0.1, -size)
        glVertex3f(size, -0.1, size)
        glVertex3f(-size, -0.1, size)
        glEnd()

        glEnable(GL_LIGHTING)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
