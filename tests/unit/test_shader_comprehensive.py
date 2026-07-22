#! /usr/bin/env python
"""Comprehensive shader rendering comparison tests

This test suite exercises all major rendering features in both legacy
and shader modes to verify visual equivalence:

- Multi-light scenarios (directional, point, spot)
- Material properties (diffuse, specular, emissive, transparency)
- Textured geometry
- Background rendering
- All geometry types (Box, Sphere, Cone, Cylinder, IndexedFaceSet, Gear)
- PointSet and IndexedLineSet

Usage:
    python test_shader_comprehensive.py

Press 'f' to toggle between shader and legacy rendering modes.
Press 'n' to cycle through test scenes.
Press 's' to take screenshot comparison.
Press 'q' to quit.
"""
import os
import sys

# Use GLFW backend for core profile support
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive('glfw')

from OpenGL.GL import *
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.gear import Gear
from OpenGLContext.arrays import array
import numpy as np


class TestScene:
    """Base class for test scenes"""
    name = "Base"
    description = "Base test scene"

    def build(self):
        """Build and return the scenegraph"""
        raise NotImplementedError


class MultiLightScene(TestScene):
    """Test scene with multiple light types"""
    name = "Multi-Light"
    description = "Tests DirectionalLight, PointLight, and SpotLight together"

    def build(self):
        # Materials
        red_mat = Material(
            diffuseColor=(0.8, 0.2, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.2,
        )
        green_mat = Material(
            diffuseColor=(0.2, 0.8, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.8,
            ambientIntensity=0.2,
        )
        blue_mat = Material(
            diffuseColor=(0.2, 0.2, 0.8),
            specularColor=(0.5, 0.5, 1.0),
            shininess=0.3,
            ambientIntensity=0.2,
        )

        # Geometry
        sphere1 = Shape(
            appearance=Appearance(material=red_mat),
            geometry=Sphere(radius=0.8),
        )
        sphere2 = Shape(
            appearance=Appearance(material=green_mat),
            geometry=Sphere(radius=0.8),
        )
        sphere3 = Shape(
            appearance=Appearance(material=blue_mat),
            geometry=Sphere(radius=0.8),
        )

        # Floor plane
        floor_mat = Material(
            diffuseColor=(0.5, 0.5, 0.5),
            specularColor=(0.3, 0.3, 0.3),
            shininess=0.1,
            ambientIntensity=0.3,
        )
        floor = Shape(
            appearance=Appearance(material=floor_mat),
            geometry=Box(size=(8, 0.1, 8)),
        )

        # Lights
        directional = DirectionalLight(
            direction=(0.5, -1.0, -0.3),
            color=(1.0, 1.0, 0.9),
            intensity=0.6,
        )
        point_light = PointLight(
            location=(0, 3, 0),
            color=(0.8, 0.8, 1.0),
            intensity=0.8,
            radius=10,
        )
        spot_light = SpotLight(
            location=(3, 4, 3),
            direction=(-0.5, -0.7, -0.5),
            color=(1.0, 0.9, 0.8),
            intensity=0.7,
            cutOffAngle=0.5,
            beamWidth=0.3,
        )

        return sceneGraph(
            children=[
                # Spheres arranged in a triangle
                Transform(translation=(-2, 1, 0), children=[sphere1]),
                Transform(translation=(2, 1, 0), children=[sphere2]),
                Transform(translation=(0, 1, -2), children=[sphere3]),
                # Floor
                Transform(translation=(0, -0.5, 0), children=[floor]),
                # Lights
                directional,
                point_light,
                spot_light,
            ],
        )


class TransparencyScene(TestScene):
    """Test scene with transparent materials"""
    name = "Transparency"
    description = "Tests material transparency with non-intersecting layers"

    def build(self):
        # Opaque red box in back
        red_mat = Material(
            diffuseColor=(0.9, 0.2, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
            transparency=0.0,
        )

        # Semi-transparent green sphere in middle
        green_mat = Material(
            diffuseColor=(0.2, 0.9, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
            transparency=0.5,
        )

        # More transparent blue box in front
        blue_mat = Material(
            diffuseColor=(0.2, 0.2, 0.9),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
            transparency=0.7,
        )

        # Create flat panels that don't intersect but overlap in screen space
        # This properly tests transparency blending without sorting issues
        red_box = Shape(
            appearance=Appearance(material=red_mat),
            geometry=Box(size=(3, 3, 0.1)),
        )
        green_box = Shape(
            appearance=Appearance(material=green_mat),
            geometry=Box(size=(2.5, 2.5, 0.1)),
        )
        blue_box = Shape(
            appearance=Appearance(material=blue_mat),
            geometry=Box(size=(2, 2, 0.1)),
        )

        # Also add a sphere to show 3D transparency
        yellow_mat = Material(
            diffuseColor=(0.9, 0.9, 0.2),
            specularColor=(1.0, 1.0, 1.0),
            shininess=0.5,
            ambientIntensity=0.3,
            transparency=0.4,
        )
        yellow_sphere = Shape(
            appearance=Appearance(material=yellow_mat),
            geometry=Sphere(radius=0.6),
        )

        light = DirectionalLight(
            direction=(0.3, -1.0, -0.5),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
        )

        return sceneGraph(
            children=[
                # Layered panels at different depths (no intersection)
                Transform(translation=(-1, 0, -2), children=[red_box]),
                Transform(translation=(-1, 0, -1), children=[green_box]),
                Transform(translation=(-1, 0, 0), children=[blue_box]),
                # Sphere offset to the side
                Transform(translation=(1.5, 0, -1), children=[yellow_sphere]),
                light,
            ],
        )


class AllGeometryScene(TestScene):
    """Test scene with all geometry types"""
    name = "All Geometry"
    description = "Tests Box, Sphere, Cone, Cylinder, Gear, IndexedFaceSet"

    def build(self):
        # Create materials with distinct colors
        materials = [
            Material(diffuseColor=(0.8, 0.2, 0.2), specularColor=(1, 1, 1), shininess=0.5, ambientIntensity=0.3),
            Material(diffuseColor=(0.2, 0.8, 0.2), specularColor=(1, 1, 1), shininess=0.5, ambientIntensity=0.3),
            Material(diffuseColor=(0.2, 0.2, 0.8), specularColor=(1, 1, 1), shininess=0.5, ambientIntensity=0.3),
            Material(diffuseColor=(0.8, 0.8, 0.2), specularColor=(1, 1, 1), shininess=0.5, ambientIntensity=0.3),
            Material(diffuseColor=(0.8, 0.2, 0.8), specularColor=(1, 1, 1), shininess=0.5, ambientIntensity=0.3),
            Material(diffuseColor=(0.2, 0.8, 0.8), specularColor=(1, 1, 1), shininess=0.5, ambientIntensity=0.3),
        ]

        # Geometry types
        box = Shape(appearance=Appearance(material=materials[0]), geometry=Box(size=(0.8, 0.8, 0.8)))
        sphere = Shape(appearance=Appearance(material=materials[1]), geometry=Sphere(radius=0.5))
        cone = Shape(appearance=Appearance(material=materials[2]), geometry=Cone(bottomRadius=0.4, height=1.0))
        cylinder = Shape(appearance=Appearance(material=materials[3]), geometry=Cylinder(radius=0.35, height=0.9))
        gear = Shape(
            appearance=Appearance(material=materials[4]),
            geometry=Gear(inner_radius=0.15, outer_radius=0.45, width=0.12, teeth=12, tooth_depth=0.08)
        )

        # Simple IndexedFaceSet pyramid
        pyramid = Shape(
            appearance=Appearance(material=materials[5]),
            geometry=IndexedFaceSet(
                coord=Coordinate(point=[
                    (0, 0.6, 0),      # top
                    (-0.4, -0.3, 0.4),  # front left
                    (0.4, -0.3, 0.4),   # front right
                    (0.4, -0.3, -0.4),  # back right
                    (-0.4, -0.3, -0.4), # back left
                ]),
                coordIndex=[
                    0, 1, 2, -1,  # front
                    0, 2, 3, -1,  # right
                    0, 3, 4, -1,  # back
                    0, 4, 1, -1,  # left
                    4, 3, 2, 1, -1,  # bottom
                ],
                solid=False,
            )
        )

        light = DirectionalLight(direction=(0.4, -1.0, -0.5), intensity=1.0)

        return sceneGraph(
            children=[
                Transform(translation=(-2.5, 0, 0), children=[box]),
                Transform(translation=(-1.5, 0, 0), children=[sphere]),
                Transform(translation=(-0.5, 0, 0), children=[cone]),
                Transform(translation=(0.5, 0, 0), children=[cylinder]),
                Transform(translation=(1.5, 0, 0), rotation=(1, 0, 0, 1.57), children=[gear]),
                Transform(translation=(2.5, 0, 0), children=[pyramid]),
                light,
            ],
        )


class PointsAndLinesScene(TestScene):
    """Test scene with PointSet and IndexedLineSet"""
    name = "Points & Lines"
    description = "Tests PointSet and IndexedLineSet geometry"

    def build(self):
        # Create a simple point cloud
        points = []
        colors = []
        for i in range(50):
            x = (i % 10) * 0.2 - 1.0
            y = (i // 10) * 0.2 - 0.5
            z = np.sin(i * 0.3) * 0.3
            points.append((x, y, z))
            # Color gradient
            r = i / 50.0
            g = 1.0 - i / 50.0
            b = 0.5
            colors.append((r, g, b))

        point_set = Shape(
            geometry=PointSet(
                coord=Coordinate(point=points),
                color=Color(color=colors),
            )
        )

        # Create a line set (wireframe cube)
        line_points = [
            (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (-0.5, 0.5, -0.5),
            (-0.5, -0.5, 0.5), (0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5),
        ]
        line_indices = [
            0, 1, 2, 3, 0, -1,  # back face
            4, 5, 6, 7, 4, -1,  # front face
            0, 4, -1, 1, 5, -1, 2, 6, -1, 3, 7, -1,  # connecting edges
        ]

        line_set = Shape(
            geometry=IndexedLineSet(
                coord=Coordinate(point=line_points),
                coordIndex=line_indices,
            )
        )

        light = DirectionalLight(direction=(0.4, -1.0, -0.5), intensity=1.0)

        return sceneGraph(
            children=[
                Transform(translation=(-1.5, 0, 0), children=[point_set]),
                Transform(translation=(1.5, 0, 0), children=[line_set]),
                light,
            ],
        )


class SpecularHighlightScene(TestScene):
    """Test scene for specular highlights"""
    name = "Specular"
    description = "Tests various shininess values for specular highlights"

    def build(self):
        # Row of spheres with varying shininess
        spheres = []
        for i, shininess in enumerate([0.0, 0.2, 0.4, 0.6, 0.8, 1.0]):
            mat = Material(
                diffuseColor=(0.3, 0.3, 0.8),
                specularColor=(1.0, 1.0, 1.0),
                shininess=shininess,
                ambientIntensity=0.2,
            )
            sphere = Shape(
                appearance=Appearance(material=mat),
                geometry=Sphere(radius=0.5),
            )
            spheres.append(
                Transform(translation=(i * 1.2 - 3.0, 0, 0), children=[sphere])
            )

        light = DirectionalLight(
            direction=(0, -0.5, -1.0),
            color=(1.0, 1.0, 1.0),
            intensity=1.0,
        )

        return sceneGraph(children=spheres + [light])


class EmissiveMaterialScene(TestScene):
    """Test scene for emissive materials"""
    name = "Emissive"
    description = "Tests emissive material properties"

    def build(self):
        # Objects with emissive colors
        shapes = []
        emissive_colors = [
            (0.8, 0.0, 0.0),  # Red glow
            (0.0, 0.8, 0.0),  # Green glow
            (0.0, 0.0, 0.8),  # Blue glow
            (0.8, 0.8, 0.0),  # Yellow glow
        ]

        for i, emit_color in enumerate(emissive_colors):
            mat = Material(
                diffuseColor=(0.2, 0.2, 0.2),
                emissiveColor=emit_color,
                specularColor=(0.5, 0.5, 0.5),
                shininess=0.5,
                ambientIntensity=0.1,
            )
            shape = Shape(
                appearance=Appearance(material=mat),
                geometry=Sphere(radius=0.6),
            )
            shapes.append(
                Transform(translation=(i * 1.5 - 2.25, 0, 0), children=[shape])
            )

        # Dim light to show emissive effect
        light = DirectionalLight(
            direction=(0, -1, -0.5),
            intensity=0.3,
        )

        return sceneGraph(children=shapes + [light])


class BackgroundScene(TestScene):
    """Test scene with background"""
    name = "Background"
    description = "Tests Background node with sky gradient"

    def build(self):
        # Simple geometry
        sphere = Shape(
            appearance=Appearance(
                material=Material(
                    diffuseColor=(0.8, 0.8, 0.8),
                    specularColor=(1, 1, 1),
                    shininess=0.8,
                )
            ),
            geometry=Sphere(radius=1.0),
        )

        # Background with sky gradient
        # Note: bound=1 is set directly here - the background will be bound
        # when the context processes the scenegraph
        bg = Background(
            skyColor=[
                (0.0, 0.0, 0.4),   # Dark blue at horizon
                (0.4, 0.6, 1.0),   # Light blue overhead
            ],
            skyAngle=[1.57],
            groundColor=[
                (0.2, 0.3, 0.1),   # Dark green
                (0.4, 0.5, 0.2),   # Light green
            ],
            groundAngle=[1.3],
            bound=1,
        )

        light = DirectionalLight(
            direction=(0.5, -1.0, -0.5),
            intensity=1.0,
        )

        return sceneGraph(
            children=[
                sphere,
                light,
                bg,
            ],
        )


# List of all test scenes
TEST_SCENES = [
    MultiLightScene(),
    TransparencyScene(),
    AllGeometryScene(),
    PointsAndLinesScene(),
    SpecularHighlightScene(),
    EmissiveMaterialScene(),
    BackgroundScene(),
]


class TestContext(BaseContext):
    """Test context that cycles through test scenes"""

    def OnInit(self):
        """Set up the test environment"""
        print("""Comprehensive Shader Rendering Tests
====================================
Press 'f' - Toggle shader/legacy rendering mode
Press 'n' - Next test scene
Press 'p' - Previous test scene
Press 's' - Take comparison screenshot
Press 'q' - Quit

""")
        # Use start scene from command line if specified
        start_scene = getattr(self.__class__, '_start_scene', 0)
        self.scene_index = 0
        self.load_scene(start_scene)

        # Register handlers
        self.addEventHandler('keyboard', name='f', function=self.toggle_shader)
        self.addEventHandler('keyboard', name='n', function=self.next_scene)
        self.addEventHandler('keyboard', name='p', function=self.prev_scene)
        self.addEventHandler('keyboard', name='s', function=self.screenshot)

    def load_scene(self, index):
        """Load a test scene by index"""
        self.scene_index = index % len(TEST_SCENES)
        scene = TEST_SCENES[self.scene_index]
        new_sg = scene.build()

        current_sg = getattr(self, 'sg', None)
        if current_sg is None:
            # First time - just assign
            self.sg = new_sg
        else:
            # Replace children of existing scenegraph instead of replacing sg
            # This triggers the proper child add/remove signals
            current_sg.children[:] = new_sg.children

        print(f"Scene {self.scene_index + 1}/{len(TEST_SCENES)}: {scene.name}")
        print(f"  {scene.description}")
        self.triggerRedraw()

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
        self.load_scene(self.scene_index + 1)

    def prev_scene(self, event):
        """Load previous scene"""
        self.load_scene(self.scene_index - 1)

    def screenshot(self, event):
        """Take a comparison screenshot"""
        from OpenGLContext.passes import renderpass
        from OpenGLContext.testing.framebuffer_comparison import FramebufferCapture, compare_images

        capture = FramebufferCapture()
        pixels = capture.capture()

        mode = "shader" if (renderpass.FLAT and renderpass.FLAT.use_shaders) else "legacy"
        scene = TEST_SCENES[self.scene_index]

        # Save screenshot
        from OpenGLContext.testing.paths import tests_root
        screenshot_dir = os.path.join(str(tests_root(__file__)), 'screenshots')
        os.makedirs(screenshot_dir, exist_ok=True)
        filename = os.path.join(screenshot_dir, f"{scene.name.lower().replace(' ', '_')}_{mode}.npy")
        np.save(filename, pixels)
        print(f"Saved: {filename}")

        # Try to compare with the other mode
        other_mode = "legacy" if mode == "shader" else "shader"
        other_filename = os.path.join(screenshot_dir, f"{scene.name.lower().replace(' ', '_')}_{other_mode}.npy")
        if os.path.exists(other_filename):
            other_pixels = np.load(other_filename)
            result = compare_images(pixels, other_pixels)
            print(f"Comparison with {other_mode}: {result}")
            if result.is_match(max_diff_threshold=0.1, max_percent_different=5.0):
                print("  PASS - Visual output matches")
            else:
                print("  DIFF - Visual output differs (may be expected for some features)")


if __name__ == "__main__":
    import sys
    # Allow starting on a specific scene by name or index
    # Usage: python test_shader_comprehensive.py [scene_name_or_index]
    start_scene = 0
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        # Try as index first
        try:
            start_scene = int(arg)
        except ValueError:
            # Try as scene name (case-insensitive partial match)
            arg_lower = arg.lower()
            for i, scene in enumerate(TEST_SCENES):
                if arg_lower in scene.name.lower():
                    start_scene = i
                    break
            else:
                print(f"Unknown scene: {arg}")
                print("Available scenes:")
                for i, scene in enumerate(TEST_SCENES):
                    print(f"  {i}: {scene.name}")
                sys.exit(1)

    # Store start scene for OnInit to use
    TestContext._start_scene = start_scene

    # Use core profile to enable shader-based rendering via flatcore
    from OpenGLContext import contextdefinition
    TestContext.ContextMainLoop(
        definition=contextdefinition.ContextDefinition(
            profile="core",
            version=(3, 3),  # Core profile requires OpenGL 3.2+
            size=(800, 600),
        )
    )
