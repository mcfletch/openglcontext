#! /usr/bin/env python
"""Comparison test for VRML97 shader-based vs legacy rendering

This test provides a split-screen view comparing:
- Left side: Legacy fixed-function rendering
- Right side: Shader-based rendering

It uses the reusable framebuffer comparison framework for pixel comparison.

Press 'p' to print comparison statistics.
Press 'd' to toggle difference highlighting mode.
Press 'l' to cycle through light types (directional/point/spot).
Press 'r' to save current left side as reference.
Press 't' to test right side against saved reference.
"""
from __future__ import print_function
from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array, zeros
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph import box as box_module
from OpenGLContext.passes.shaderpass import get_shader_program
from OpenGLContext.testing.framebuffer_comparison import (
    FramebufferCapture, compare_images, RegressionTestMixin
)
import numpy as np

class ComparisonContext(RegressionTestMixin, BaseContext):
    """Side-by-side comparison of shader and legacy rendering"""

    test_name = "shader_vs_legacy"
    show_difference = False

    def OnInit(self):
        """Set up the test scene"""
        print("""VRML97 Shader vs Legacy Rendering Comparison
=============================================
Left half: Legacy fixed-function pipeline
Right half: Shader-based pipeline

Press 'p' to print pixel comparison statistics
Press 'd' to toggle difference highlighting
Press 'l' to cycle through light types (directional/point/spot)
Press 'r' to save left side as reference
Press 't' to test right side against reference
""")

        # Initialize regression test support
        self.OnInit_regression()

        # Material for testing
        self.test_material = Material(
            diffuseColor=(0.7, 0.3, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            emissiveColor=(0.0, 0.0, 0.0),
            shininess=0.6,
            ambientIntensity=0.3,
            transparency=0.0,
        )

        # Create test geometry
        self.test_box = Box(size=(1.5, 1.5, 1.5))

        # Light type index (0=directional, 1=point, 2=spot)
        self.light_type = 0
        self.light_types = ['directional', 'point', 'spot']

        # Initialize shader program
        self.shader_program = None

        # Framebuffer captures for comparison
        self.left_capture = FramebufferCapture()
        self.right_capture = FramebufferCapture()

        # Register key handlers
        self.addEventHandler('keyboard', name='p', function=self.print_comparison)
        self.addEventHandler('keyboard', name='d', function=self.toggle_difference)
        self.addEventHandler('keyboard', name='l', function=self.cycle_light)

    def cycle_light(self, event):
        """Cycle through light types"""
        self.light_type = (self.light_type + 1) % len(self.light_types)
        print(f"Light type: {self.light_types[self.light_type]}")
        self.triggerRedraw()

    def toggle_difference(self, event):
        """Toggle difference highlighting mode"""
        self.show_difference = not self.show_difference
        print(f"Difference highlighting: {'ON' if self.show_difference else 'OFF'}")
        self.triggerRedraw()

    def print_comparison(self, event):
        """Print pixel comparison statistics using the comparison framework"""
        # Capture both halves
        self.left_capture.capture_left_half()
        self.right_capture.capture_right_half()

        # Compare
        result = compare_images(self.left_capture.pixels, self.right_capture.pixels)

        print(f"\nPixel Comparison Statistics:")
        print(f"  {result}")

        if result.is_match(max_diff_threshold=0.1, max_percent_different=5.0):
            print("  PASS - Rendering is visually similar")
        else:
            print("  ATTENTION - Significant differences detected")

    def Render(self, mode):
        """Render comparison view"""
        viewport = glGetIntegerv(GL_VIEWPORT)
        width, height = viewport[2], viewport[3]
        half_width = width // 2

        # Get matrices
        modelview = mode.getModelView()
        projection = mode.getProjection()

        # Initialize shader if needed
        if self.shader_program is None:
            self.shader_program = get_shader_program()
            if not self.shader_program.compile():
                print("Shader compilation failed!")
                return

        # Clear the whole screen
        glClearColor(0.1, 0.1, 0.15, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)

        # === Left half: Legacy rendering ===
        glViewport(0, 0, half_width, height)
        self._render_legacy(mode, modelview, projection)

        # === Right half: Shader rendering ===
        glViewport(half_width, 0, half_width, height)
        self._render_shader(mode, modelview, projection)

        # Restore viewport
        glViewport(0, 0, width, height)

        # Draw dividing line
        self._draw_divider(width, height)

    def _render_legacy(self, mode, modelview, projection):
        """Render using legacy fixed-function pipeline"""
        glMatrixMode(GL_PROJECTION)
        glLoadMatrixf(projection.astype('f'))
        glMatrixMode(GL_MODELVIEW)
        glLoadMatrixf(modelview.astype('f'))

        # Set up lighting
        glEnable(GL_LIGHTING)
        glEnable(GL_LIGHT0)

        light_type = self.light_types[self.light_type]

        if light_type == 'directional':
            # Directional light (w=0)
            glLightfv(GL_LIGHT0, GL_POSITION, array([0.5, 1.0, 0.5, 0.0], 'f'))
        else:
            # Positional light (w=1)
            glLightfv(GL_LIGHT0, GL_POSITION, array([3.0, 3.0, 3.0, 1.0], 'f'))

        glLightfv(GL_LIGHT0, GL_DIFFUSE, array([1.0, 1.0, 1.0, 1.0], 'f'))
        glLightfv(GL_LIGHT0, GL_SPECULAR, array([1.0, 1.0, 1.0, 1.0], 'f'))
        glLightfv(GL_LIGHT0, GL_AMBIENT, array([0.2, 0.2, 0.2, 1.0], 'f'))

        if light_type == 'spot':
            glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, array([-0.5, -0.5, -0.5], 'f'))
            glLightf(GL_LIGHT0, GL_SPOT_CUTOFF, 30.0)
            glLightf(GL_LIGHT0, GL_SPOT_EXPONENT, 10.0)
        else:
            glLightf(GL_LIGHT0, GL_SPOT_CUTOFF, 180.0)  # Disable spot

        # Attenuation for point/spot
        if light_type in ('point', 'spot'):
            glLightf(GL_LIGHT0, GL_CONSTANT_ATTENUATION, 1.0)
            glLightf(GL_LIGHT0, GL_LINEAR_ATTENUATION, 0.0)
            glLightf(GL_LIGHT0, GL_QUADRATIC_ATTENUATION, 0.01)
        else:
            glLightf(GL_LIGHT0, GL_CONSTANT_ATTENUATION, 1.0)
            glLightf(GL_LIGHT0, GL_LINEAR_ATTENUATION, 0.0)
            glLightf(GL_LIGHT0, GL_QUADRATIC_ATTENUATION, 0.0)

        # Set material
        mat = self.test_material
        alpha = 1.0 - mat.transparency

        diffuse = array(list(mat.diffuseColor) + [alpha], 'f')
        specular = array(list(mat.specularColor) + [alpha], 'f')
        emissive = array(list(mat.emissiveColor) + [alpha], 'f')
        ambient = array(list(mat.diffuseColor * mat.ambientIntensity) + [alpha], 'f')

        glMaterialfv(GL_FRONT_AND_BACK, GL_DIFFUSE, diffuse)
        glMaterialfv(GL_FRONT_AND_BACK, GL_SPECULAR, specular)
        glMaterialfv(GL_FRONT_AND_BACK, GL_EMISSION, emissive)
        glMaterialfv(GL_FRONT_AND_BACK, GL_AMBIENT, ambient)
        glMaterialf(GL_FRONT_AND_BACK, GL_SHININESS, mat.shininess * 128)

        # Render box
        self.test_box.render(lit=True, textured=False, mode=mode)

        glDisable(GL_LIGHTING)

    def _render_shader(self, mode, modelview, projection):
        """Render using shader pipeline"""
        self.shader_program.use(lit=True)

        # Set matrices
        self.shader_program.set_matrices(modelview, projection)

        # Set scene ambient
        self.shader_program.set_scene_ambient((0.2, 0.2, 0.2))

        # Set up light
        light_type = self.light_types[self.light_type]
        self.shader_program.set_num_lights(1)

        if light_type == 'directional':
            self.shader_program.set_light(
                0,
                light_type='directional',
                color=(1.0, 1.0, 1.0),
                direction=(-0.5, -1.0, -0.5),  # Negated for shader
                intensity=1.0,
            )
        elif light_type == 'point':
            self.shader_program.set_light(
                0,
                light_type='point',
                color=(1.0, 1.0, 1.0),
                position=(3.0, 3.0, 3.0, 1.0),
                attenuation=(1.0, 0.0, 0.01),
                intensity=1.0,
            )
        else:  # spot
            self.shader_program.set_light(
                0,
                light_type='spot',
                color=(1.0, 1.0, 1.0),
                position=(3.0, 3.0, 3.0, 1.0),
                direction=(-0.5, -0.5, -0.5),
                attenuation=(1.0, 0.0, 0.01),
                intensity=1.0,
                beam_width=0.4,  # ~23 degrees
                cutoff_angle=0.52,  # ~30 degrees
            )

        # Set material
        mat = self.test_material
        self.shader_program.set_material(
            diffuse=tuple(mat.diffuseColor),
            specular=tuple(mat.specularColor),
            emissive=tuple(mat.emissiveColor),
            ambient_intensity=mat.ambientIntensity,
            shininess=mat.shininess,
            transparency=mat.transparency,
        )

        self.shader_program.set_texture_enabled(False)

        # Render box with shader
        self._render_box_shader(mode)

        self.shader_program.unuse()

    def _render_box_shader(self, mode):
        """Render box using shader"""
        # Get or create VBO
        box_vbo = mode.cache.getData(self.test_box, 'shader_vbo')
        if box_vbo is None:
            vertices = array(list(box_module.yieldVertices(self.test_box.size)), 'f')
            box_vbo = vbo.VBO(vertices)
            mode.cache.holder(self.test_box, box_vbo, 'shader_vbo')

        box_vbo.bind()
        try:
            stride = 32  # 8 floats * 4 bytes

            # Get attribute locations
            program = self.shader_program.program
            tex_loc = glGetAttribLocation(program, 'aTexCoord')
            normal_loc = glGetAttribLocation(program, 'aNormal')
            pos_loc = glGetAttribLocation(program, 'aPosition')

            # Enable and set up attributes
            if tex_loc >= 0:
                glEnableVertexAttribArray(tex_loc)
                glVertexAttribPointer(tex_loc, 2, GL_FLOAT, GL_FALSE, stride, box_vbo)

            if normal_loc >= 0:
                glEnableVertexAttribArray(normal_loc)
                glVertexAttribPointer(normal_loc, 3, GL_FLOAT, GL_FALSE, stride, box_vbo + 8)

            if pos_loc >= 0:
                glEnableVertexAttribArray(pos_loc)
                glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, stride, box_vbo + 20)

            glDrawArrays(GL_TRIANGLES, 0, 36)

            # Cleanup
            if tex_loc >= 0:
                glDisableVertexAttribArray(tex_loc)
            if normal_loc >= 0:
                glDisableVertexAttribArray(normal_loc)
            if pos_loc >= 0:
                glDisableVertexAttribArray(pos_loc)
        finally:
            box_vbo.unbind()

    def _draw_divider(self, width, height):
        """Draw a vertical line dividing the two halves"""
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0, width, 0, height, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        glDisable(GL_LIGHTING)
        glDisable(GL_DEPTH_TEST)

        glColor3f(0.5, 0.5, 0.5)
        glLineWidth(2.0)
        glBegin(GL_LINES)
        glVertex2f(width / 2, 0)
        glVertex2f(width / 2, height)
        glEnd()

        glEnable(GL_DEPTH_TEST)


if __name__ == "__main__":
    ComparisonContext.ContextMainLoop()
