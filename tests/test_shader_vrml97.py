#! /usr/bin/env python
"""Test for VRML97 shader-based rendering

This test compares shader-based rendering with the legacy fixed-function
rendering to verify visual compatibility.

It renders a simple scene with:
- A colored box with material properties
- A directional light

Press 's' to toggle between shader and legacy rendering modes.
Press 'f' to toggle FlatPass shader mode (integrated mode).
Press 'c' to capture comparison screenshots.
"""
from __future__ import print_function
from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.passes.shaderpass import get_shader_program, VRML97ShaderProgram
import numpy as np

class TestContext(BaseContext):
    """Test context comparing shader and legacy rendering"""

    use_shader = False  # Start with legacy rendering

    def OnInit(self):
        """Set up the test scene"""
        print("""VRML97 Shader Rendering Test
============================
Press 's' to toggle between shader and legacy rendering (manual shader test)
Press 'f' to toggle FlatPass shader mode (integrated rendering)
Press 'c' to capture comparison (prints color values)

Current mode: LEGACY (fixed-function)
""")

        # Create a simple scene with a box
        self.shape = Shape(
            appearance=Appearance(
                material=Material(
                    diffuseColor=(0.8, 0.2, 0.2),  # Red
                    specularColor=(1.0, 1.0, 1.0),
                    shininess=0.5,
                    ambientIntensity=0.3,
                ),
            ),
            geometry=Box(size=(2, 2, 2)),
        )

        self.light = DirectionalLight(
            direction=(0.5, -1.0, -0.5),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
        )

        self.sg = sceneGraph(
            children=[
                Transform(
                    translation=(0, 0, 0),
                    children=[self.shape],
                ),
                self.light,
            ],
        )

        # Initialize shader program (but don't compile yet - need GL context)
        self.shader_program = None

        # Register key handlers
        self.addEventHandler('keyboard', name='s', function=self.toggle_shader)
        self.addEventHandler('keyboard', name='f', function=self.toggle_flatpass_shader)
        self.addEventHandler('keyboard', name='c', function=self.capture_comparison)

    def toggle_shader(self, event):
        """Toggle between shader and legacy rendering (manual test)"""
        self.use_shader = not self.use_shader
        mode_name = "SHADER (manual)" if self.use_shader else "LEGACY"
        print(f"Switched to {mode_name} rendering mode")
        self.triggerRedraw()

    def toggle_flatpass_shader(self, event):
        """Toggle FlatPass shader mode (integrated rendering)"""
        from OpenGLContext.passes import renderpass
        if renderpass.FLAT is not None:
            renderpass.FLAT.use_shaders = not renderpass.FLAT.use_shaders
            mode_name = "ENABLED" if renderpass.FLAT.use_shaders else "DISABLED"
            print(f"FlatPass shader mode: {mode_name}")
        self.triggerRedraw()

    def capture_comparison(self, event):
        """Capture and compare pixel values"""
        # Read a pixel from the center of the screen
        viewport = glGetIntegerv(GL_VIEWPORT)
        x, y = viewport[2] // 2, viewport[3] // 2
        pixel = glReadPixels(x, y, 1, 1, GL_RGB, GL_FLOAT)
        mode_name = "SHADER" if self.use_shader else "LEGACY"
        print(f"{mode_name} mode - Center pixel RGB: {pixel[0][0]}")

    def Render(self, mode):
        """Render the scene using either shader or legacy path"""
        if self.use_shader:
            self._render_with_shader(mode)
        else:
            # Legacy rendering - let OpenGLContext handle it
            pass  # The scenegraph will be rendered by the default path

    def _render_with_shader(self, mode):
        """Render using the VRML97 shader"""
        if self.shader_program is None:
            self.shader_program = get_shader_program()
            if not self.shader_program.compile():
                print("Failed to compile shader, falling back to legacy")
                self.use_shader = False
                return

        # Clear
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        # Enable depth testing
        glEnable(GL_DEPTH_TEST)
        glDepthFunc(GL_LESS)

        # Get matrices from mode
        modelview = mode.matrix if hasattr(mode, 'matrix') and mode.matrix is not None else mode.getModelView()
        projection = mode.getProjection()

        # Activate shader
        self.shader_program.use(lit=True)

        # Set matrices
        self.shader_program.set_matrices(modelview, projection)

        # Set scene ambient
        self.shader_program.set_scene_ambient((0.2, 0.2, 0.2))

        # Set up light from scenegraph
        self.shader_program.set_num_lights(1)
        light_dir = self.light.direction
        self.shader_program.set_light(
            0,
            light_type='directional',
            color=tuple(self.light.color),
            direction=tuple(light_dir),
            intensity=self.light.intensity,
        )

        # Set material from shape's appearance
        mat = self.shape.appearance.material
        self.shader_program.set_material(
            diffuse=tuple(mat.diffuseColor),
            specular=tuple(mat.specularColor),
            emissive=tuple(mat.emissiveColor),
            ambient_intensity=mat.ambientIntensity,
            shininess=mat.shininess,
            transparency=mat.transparency,
        )

        # Disable texture
        self.shader_program.set_texture_enabled(False)

        # Render the box geometry manually using shader
        self._render_box_with_shader(mode)

        # Deactivate shader
        self.shader_program.unuse()

    def _render_box_with_shader(self, mode):
        """Render a box using the shader with VAO/VBO"""
        from OpenGLContext.scenegraph.box import yieldVertices

        # Get or create VBO for box
        box_data = mode.cache.getData(self.shape.geometry, 'shader_vbo')
        if box_data is None:
            # Create interleaved vertex data: texcoord(2) + normal(3) + position(3)
            vertices = array(list(yieldVertices(self.shape.geometry.size)), 'f')
            box_vbo = vbo.VBO(vertices)
            box_data = box_vbo
            mode.cache.holder(self.shape.geometry, box_vbo, 'shader_vbo')

        # Bind and render
        box_data.bind()
        try:
            # Set up vertex attributes
            # Layout: texcoord(2) + normal(3) + position(3) = 8 floats = 32 bytes stride
            stride = 32

            # Texture coords at offset 0
            tex_loc = glGetAttribLocation(self.shader_program.program, 'aTexCoord')
            if tex_loc >= 0:
                glEnableVertexAttribArray(tex_loc)
                glVertexAttribPointer(tex_loc, 2, GL_FLOAT, GL_FALSE, stride, box_data)

            # Normals at offset 8 (2 floats * 4 bytes)
            normal_loc = glGetAttribLocation(self.shader_program.program, 'aNormal')
            if normal_loc >= 0:
                glEnableVertexAttribArray(normal_loc)
                glVertexAttribPointer(normal_loc, 3, GL_FLOAT, GL_FALSE, stride, box_data + 8)

            # Positions at offset 20 (5 floats * 4 bytes)
            pos_loc = glGetAttribLocation(self.shader_program.program, 'aPosition')
            if pos_loc >= 0:
                glEnableVertexAttribArray(pos_loc)
                glVertexAttribPointer(pos_loc, 3, GL_FLOAT, GL_FALSE, stride, box_data + 20)

            # Draw
            glDrawArrays(GL_TRIANGLES, 0, 36)

            # Cleanup
            if tex_loc >= 0:
                glDisableVertexAttribArray(tex_loc)
            if normal_loc >= 0:
                glDisableVertexAttribArray(normal_loc)
            if pos_loc >= 0:
                glDisableVertexAttribArray(pos_loc)
        finally:
            box_data.unbind()


if __name__ == "__main__":
    TestContext.ContextMainLoop()
