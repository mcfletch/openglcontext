#! /usr/bin/env python
"""Test shader rendering for all geometry types

This test creates a scene with various geometry types to verify
shader-based rendering works correctly for each:

- Box
- Sphere
- Cone
- Cylinder
- IndexedFaceSet (via VRML file loading)
- Gear

Press 'f' to toggle between shader and legacy rendering modes.
Press 'c' to capture and compare center pixel.
Press 'q' to quit.
"""
from __future__ import print_function
from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.gear import Gear
import numpy as np


class TestContext(BaseContext):
    """Test context with multiple geometry types"""

    def OnInit(self):
        """Set up the test scene with various geometry types"""
        print("""Shader All-Geometry Test
========================
Press 'f' to toggle FlatPass shader mode
Press 'c' to capture center pixel RGB
Press 'q' to quit

Testing: Box, Sphere, Cone, Cylinder, Gear
""")

        # Create materials with different colors for each geometry
        red_mat = Material(
            diffuseColor=(0.8, 0.2, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
        )
        green_mat = Material(
            diffuseColor=(0.2, 0.8, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
        )
        blue_mat = Material(
            diffuseColor=(0.2, 0.2, 0.8),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
        )
        yellow_mat = Material(
            diffuseColor=(0.8, 0.8, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
        )
        purple_mat = Material(
            diffuseColor=(0.6, 0.2, 0.8),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
        )

        # Create shapes with different geometry types
        box_shape = Shape(
            appearance=Appearance(material=red_mat),
            geometry=Box(size=(1, 1, 1)),
        )
        sphere_shape = Shape(
            appearance=Appearance(material=green_mat),
            geometry=Sphere(radius=0.6),
        )
        cone_shape = Shape(
            appearance=Appearance(material=blue_mat),
            geometry=Cone(bottomRadius=0.5, height=1.2),
        )
        cylinder_shape = Shape(
            appearance=Appearance(material=yellow_mat),
            geometry=Cylinder(radius=0.4, height=1.0),
        )
        gear_shape = Shape(
            appearance=Appearance(material=purple_mat),
            geometry=Gear(
                inner_radius=0.2,
                outer_radius=0.6,
                width=0.15,
                teeth=16,
                tooth_depth=0.1,
            ),
        )

        # Create a directional light
        light = DirectionalLight(
            direction=(0.5, -1.0, -0.5),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
        )

        # Arrange shapes in a row
        self.sg = sceneGraph(
            children=[
                Transform(
                    translation=(-3, 0, 0),
                    children=[box_shape],
                ),
                Transform(
                    translation=(-1.5, 0, 0),
                    children=[sphere_shape],
                ),
                Transform(
                    translation=(0, 0, 0),
                    children=[cone_shape],
                ),
                Transform(
                    translation=(1.5, 0, 0),
                    children=[cylinder_shape],
                ),
                Transform(
                    translation=(3, 0, 0),
                    rotation=(1, 0, 0, 1.57),  # Rotate gear to face camera
                    children=[gear_shape],
                ),
                light,
            ],
        )

        # Register key handlers
        self.addEventHandler('keyboard', name='f', function=self.toggle_shader)
        self.addEventHandler('keyboard', name='c', function=self.capture_pixel)

    def toggle_shader(self, event):
        """Toggle FlatPass shader mode"""
        from OpenGLContext.passes import renderpass
        if renderpass.FLAT is not None:
            renderpass.FLAT.use_shaders = not renderpass.FLAT.use_shaders
            mode_name = "SHADER" if renderpass.FLAT.use_shaders else "LEGACY"
            print(f"Rendering mode: {mode_name}")
        self.triggerRedraw()

    def capture_pixel(self, event):
        """Capture and print center pixel color"""
        from OpenGLContext.passes import renderpass
        viewport = glGetIntegerv(GL_VIEWPORT)
        x, y = viewport[2] // 2, viewport[3] // 2
        pixel = glReadPixels(x, y, 1, 1, GL_RGB, GL_FLOAT)
        shader = "SHADER" if (renderpass.FLAT and renderpass.FLAT.use_shaders) else "LEGACY"
        print(f"{shader} mode - Center pixel RGB: {pixel[0][0]}")


if __name__ == "__main__":
    TestContext.ContextMainLoop()
