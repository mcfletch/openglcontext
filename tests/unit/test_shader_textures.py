#! /usr/bin/env python
"""Test shader rendering with textures

This test exercises texture rendering in both legacy and shader modes:
- RGB textures
- RGBA textures with transparency
- Texture repetition
- Texture transforms

Press 'f' to toggle between shader and legacy rendering modes.
Press 'n' to cycle through test scenes.
Press 'q' to quit.
"""
import os
from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()

from OpenGL.GL import *
from OpenGLContext.scenegraph.basenodes import *


# Path to test textures
from OpenGLContext.testing.paths import tests_root
TEXTURE_DIR = os.path.join(str(tests_root(__file__)), 'wrls')


class TextureTestContext(BaseContext):
    """Test context for texture rendering"""

    def OnInit(self):
        """Set up the test scene with various textured objects"""
        print("""Shader Texture Rendering Test
=============================
Press 'f' - Toggle shader/legacy mode
Press 'n' - Next scene
Press 'q' - Quit

Test textures from: {}
""".format(TEXTURE_DIR))

        self.scene_index = 0
        self.scenes = [
            self._build_rgb_texture_scene,
            self._build_rgba_texture_scene,
            self._build_repeat_texture_scene,
            self._build_multi_texture_scene,
        ]
        self.scene_names = [
            "RGB Texture",
            "RGBA Texture (with alpha)",
            "Texture Repetition",
            "Multiple Textured Objects",
        ]
        self._load_scene()

        self.addEventHandler('keyboard', name='f', function=self.toggle_shader)
        self.addEventHandler('keyboard', name='n', function=self.next_scene)

    def _load_scene(self):
        """Load the current scene"""
        new_sg = self.scenes[self.scene_index]()

        current_sg = getattr(self, 'sg', None)
        if current_sg is None:
            # First time - just assign
            self.sg = new_sg
        else:
            # Replace children of existing scenegraph instead of replacing sg
            # This triggers the proper child add/remove signals
            current_sg.children[:] = new_sg.children

        print(f"Scene {self.scene_index + 1}/{len(self.scenes)}: {self.scene_names[self.scene_index]}")
        self.triggerRedraw()

    def _build_rgb_texture_scene(self):
        """Scene with RGB textured box"""
        mat = Material(
            diffuseColor=(1.0, 1.0, 1.0),
            ambientIntensity=0.3,
        )
        tex = ImageTexture(
            url=[os.path.join(TEXTURE_DIR, 'simple_texturergb.png')],
        )
        box = Shape(
            appearance=Appearance(material=mat, texture=tex),
            geometry=Box(size=(2, 2, 2)),
        )
        light = DirectionalLight(direction=(0.5, -1.0, -0.5), intensity=1.0)
        return sceneGraph(children=[box, light])

    def _build_rgba_texture_scene(self):
        """Scene with RGBA textured geometry (transparency)"""
        mat = Material(
            diffuseColor=(1.0, 1.0, 1.0),
            ambientIntensity=0.3,
        )
        # Use an RGBA texture
        tex = ImageTexture(
            url=[os.path.join(TEXTURE_DIR, 'simple_texturergba.png')],
        )

        # Textured quad in front
        quad = Shape(
            appearance=Appearance(material=mat, texture=tex),
            geometry=IndexedFaceSet(
                coord=Coordinate(point=[
                    (-1.5, -1.5, 0.5),
                    (1.5, -1.5, 0.5),
                    (1.5, 1.5, 0.5),
                    (-1.5, 1.5, 0.5),
                ]),
                coordIndex=[0, 1, 2, 3, -1],
                texCoord=TextureCoordinate(point=[
                    (0, 0), (1, 0), (1, 1), (0, 1),
                ]),
                solid=False,
            )
        )

        # Solid colored box behind
        back_mat = Material(
            diffuseColor=(0.8, 0.2, 0.2),
            ambientIntensity=0.3,
        )
        back_box = Shape(
            appearance=Appearance(material=back_mat),
            geometry=Box(size=(3, 3, 0.5)),
        )

        light = DirectionalLight(direction=(0, 0, -1), intensity=1.0)
        return sceneGraph(children=[
            Transform(translation=(0, 0, -1), children=[back_box]),
            quad,
            light,
        ])

    def _build_repeat_texture_scene(self):
        """Scene demonstrating texture repetition"""
        mat = Material(
            diffuseColor=(1.0, 1.0, 1.0),
            ambientIntensity=0.3,
        )
        tex = ImageTexture(
            url=[os.path.join(TEXTURE_DIR, 'yingyang.png')],
            repeatS=True,
            repeatT=True,
        )

        # Plane with repeated texture coordinates
        plane = Shape(
            appearance=Appearance(material=mat, texture=tex),
            geometry=IndexedFaceSet(
                coord=Coordinate(point=[
                    (-2, -2, 0),
                    (2, -2, 0),
                    (2, 2, 0),
                    (-2, 2, 0),
                ]),
                coordIndex=[0, 1, 2, 3, -1],
                # Texture coordinates > 1 will repeat
                texCoord=TextureCoordinate(point=[
                    (0, 0), (4, 0), (4, 4), (0, 4),
                ]),
                solid=False,
            )
        )

        light = DirectionalLight(direction=(0, 0, -1), intensity=1.0)
        return sceneGraph(children=[plane, light])

    def _build_multi_texture_scene(self):
        """Scene with multiple differently textured objects"""
        textures = [
            'simple_texturergb.png',
            'yingyang.png',
            'logoinstaller.png',
        ]

        shapes = []
        for i, tex_file in enumerate(textures):
            mat = Material(
                diffuseColor=(1.0, 1.0, 1.0),
                ambientIntensity=0.3,
            )
            tex = ImageTexture(
                url=[os.path.join(TEXTURE_DIR, tex_file)],
            )

            # Different geometry for each
            if i == 0:
                geom = Box(size=(1.2, 1.2, 1.2))
            elif i == 1:
                geom = Sphere(radius=0.7)
            else:
                geom = Cylinder(radius=0.5, height=1.2)

            shape = Shape(
                appearance=Appearance(material=mat, texture=tex),
                geometry=geom,
            )
            shapes.append(
                Transform(translation=(i * 2 - 2, 0, 0), children=[shape])
            )

        light = DirectionalLight(direction=(0.5, -1.0, -0.5), intensity=1.0)
        return sceneGraph(children=shapes + [light])

    def toggle_shader(self, event):
        """Toggle shader mode"""
        from OpenGLContext.passes import renderpass
        if renderpass.FLAT is not None:
            renderpass.FLAT.use_shaders = not renderpass.FLAT.use_shaders
            mode = "SHADER" if renderpass.FLAT.use_shaders else "LEGACY"
            print(f"Rendering mode: {mode}")
        self.triggerRedraw()

    def next_scene(self, event):
        """Load next scene"""
        self.scene_index = (self.scene_index + 1) % len(self.scenes)
        self._load_scene()


if __name__ == "__main__":
    TextureTestContext.ContextMainLoop()
