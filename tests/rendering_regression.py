#!/usr/bin/env python
"""Comprehensive rendering regression test suite.

This module provides automated visual regression testing between compatibility
(fixed-function) and core (shader-based) OpenGL rendering profiles.

Features:
- Tests multiple scene configurations (geometry, lighting, texturing, transparency)
- Compares compat vs core rendering with configurable threshold
- Detects regressions against previous baseline images
- Generates comprehensive markdown reports with embedded images

Usage:
    python tests/rendering_regression.py [--output-dir DIR] [--threshold PERCENT]
    python tests/rendering_regression.py --update-baseline  # Save current compat as baseline

The test produces:
- Reference images for each test in both profiles
- Diff images showing differences
- A markdown report summarizing all results
"""

import argparse
import datetime
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# Import from existing testing infrastructure
from OpenGLContext.testing.framebuffer_comparison import (
    ComparisonResult,
    FramebufferCapture,
    AutomatedRegressionContext,
    DEFAULT_REFERENCE_DIR,
    DEFAULT_CAPTURE_DELAY,
    ensure_pillow,
)

# Test configuration
DEFAULT_THRESHOLD = 0.06  # 0.06% similarity error threshold
CAPTURE_DELAY = 0.3  # Short delay for fast tests
RENDER_TIMEOUT = 10  # Timeout per render in seconds
WINDOW_SIZE = (300, 300)


def calculate_similarity_error(pixels_different: int, mean_diff: float,
                               total_pixels: int, depth: int = 255) -> float:
    """Calculate similarity error as percentage.

    Formula: (diff_pixels * avg_diff) / (total_pixels * depth) * 100
    """
    if total_pixels == 0 or pixels_different == 0:
        return 0.0
    return (pixels_different * mean_diff) / (total_pixels * depth) * 100


def count_non_black_pixels(arr: np.ndarray, threshold: int = 5) -> int:
    """Count pixels that are not black (or near-black).

    Args:
        arr: Image array (H, W, 3) RGB
        threshold: Maximum brightness to consider "black" (default 5 for very dim detection)

    Returns:
        Number of pixels with any channel above threshold
    """
    # A pixel is "non-black" if any channel exceeds the threshold
    max_channel = np.max(arr, axis=2)
    return int(np.sum(max_channel > threshold))


def calculate_content_ratio(non_black1: int, non_black2: int, total: int) -> float:
    """Calculate ratio of content between two images.

    Returns a value indicating how different the content amounts are.
    0.0 = same amount of content, 1.0 = one is empty, other has content
    """
    if total == 0:
        return 0.0

    # Normalize to percentages of total
    pct1 = non_black1 / total
    pct2 = non_black2 / total

    # If both have no content or same amount, ratio is 0
    if pct1 == 0 and pct2 == 0:
        return 0.0

    # Calculate relative difference
    max_pct = max(pct1, pct2)
    min_pct = min(pct1, pct2)

    if max_pct == 0:
        return 0.0

    # Ratio of how much content is missing
    return (max_pct - min_pct) / max_pct


@dataclass
class TestResult:
    """Result of a single rendering comparison test."""
    name: str
    description: str
    compat_image: Optional[Path] = None
    core_image: Optional[Path] = None
    diff_image: Optional[Path] = None
    baseline_image: Optional[Path] = None
    baseline_diff_image: Optional[Path] = None

    # Metrics for compat vs core comparison
    pixels_different: int = 0
    total_pixels: int = 0
    mean_diff: float = 0.0
    max_diff: int = 0
    similarity_error: float = 0.0

    # Content metrics (non-black pixel counts)
    compat_content_pixels: int = 0
    core_content_pixels: int = 0
    content_ratio: float = 0.0  # How different the content amounts are

    # Metrics for baseline comparison (regression detection)
    baseline_pixels_different: int = 0
    baseline_mean_diff: float = 0.0
    baseline_similarity_error: float = 0.0

    passed: bool = False
    baseline_passed: bool = True  # True if no baseline or matches
    error_message: str = ""
    compat_only: bool = False  # True if test uses fixed-function features unavailable in core


@dataclass
class TestSuite:
    """Collection of test results with summary statistics."""
    name: str
    timestamp: str
    threshold: float
    results: List[TestResult] = field(default_factory=list)

    @property
    def total_tests(self) -> int:
        return len(self.results)

    @property
    def passed_tests(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed_tests(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def regression_tests(self) -> int:
        return sum(1 for r in self.results if not r.baseline_passed)


# Test scene definitions - each defines a complete test context
TEST_SCENES = [
    {
        'name': 'basic_geometry',
        'description': 'Basic geometric shapes (Box, Sphere, Cone, Cylinder)',
        'module': 'test_basic_geometry',
    },
    {
        'name': 'teapot_lighting',
        'description': 'Teapot with directional lighting',
        'module': 'test_teapot_lighting',
    },
    {
        'name': 'multiple_lights',
        'description': 'Scene with multiple directional lights (red, green, blue)',
        'module': 'test_multiple_lights',
    },
    {
        'name': 'point_light',
        'description': 'Point light with attenuation',
        'module': 'test_point_light',
    },
    {
        'name': 'spot_light',
        'description': 'Spot light with cone falloff',
        'module': 'test_spot_light',
    },
    {
        'name': 'material_properties',
        'description': 'Various material properties (ambient, specular, emissive)',
        'module': 'test_material_properties',
    },
    {
        'name': 'transparency',
        'description': 'Transparent objects with alpha blending',
        'module': 'test_transparency',
    },
    {
        'name': 'textured_box',
        'description': 'Textured geometry with procedural checkerboard',
        'module': 'test_textured_box',
    },
    {
        'name': 'texture_transform',
        'description': 'Texture with coordinate transformation (scale, rotate)',
        'module': 'test_texture_transform',
    },
    {
        'name': 'complex_scene',
        'description': 'Complex scene with multiple objects, lights, and materials',
        'module': 'test_complex_scene',
    },
    {
        'name': 'nurbs_surface',
        'description': 'NURBS surface with trimming contours (GLU tessellation)',
        'module': 'test_nurbs_surface',
        # Now works in core profile via GLU tessellator callbacks + VBO rendering
        # Higher threshold because GLU tessellation and shader lighting differ from fixed-function
        'threshold': 2.0,
    },
    {
        'name': 'text_3d',
        'description': '3D extruded text geometry (GLE - compat only)',
        'module': 'test_text_3d',
        'compat_only': True,  # Uses GLE extrusion which requires fixed-function pipeline
    },
    {
        'name': 'text_2d',
        'description': '2D bitmap text overlay',
        'module': 'test_text_2d',
    },
    {
        'name': 'indexed_lineset',
        'description': 'IndexedLineSet with per-vertex colors',
        'module': 'test_indexed_lineset',
    },
    {
        'name': 'indexed_lineset_large',
        'description': 'IndexedLineSet with 10000 points (lorentz data)',
        'module': 'test_indexed_lineset_large',
    },
    {
        'name': 'pointset',
        'description': 'PointSet with per-vertex colors',
        'module': 'test_pointset',
    },
]


def generate_test_script(name: str, scene_code: str, output_dir: Path) -> Path:
    """Generate a test script file that can be run standalone."""
    script_content = f'''#!/usr/bin/env python
"""Auto-generated regression test: {name}"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.framebuffer_comparison import AutomatedRegressionContext

{scene_code}

class TestContext(AutomatedRegressionContext, SceneSetup):
    test_name = "{name}"

    def OnInit(self):
        super().OnInit()
        self.setup_regression_test()

    def OnDraw(self, force=1, *arguments):
        """Draw the scene and check for regression capture."""
        result = super().OnDraw(force, *arguments)
        self._check_regression_capture()
        return result

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''
    script_dir = output_dir / 'scripts'
    script_dir.mkdir(parents=True, exist_ok=True)
    script_path = script_dir / f'{name}.py'
    script_path.write_text(script_content)
    return script_path


# Scene setup code for each test (class body for SceneSetup)
SCENE_CODE = {
    'basic_geometry': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    translation=(-1.5, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Box(size=(1, 1, 1)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.8, 0.2, 0.2))
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(0, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.6),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.2, 0.8, 0.2))
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(1.5, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Cone(bottomRadius=0.5, height=1.2),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.2, 0.2, 0.8))
                        )
                    )]
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=1.0),
            ]
        )
''',

    'teapot_lighting': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.Teapot(size=1.0),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(
                            diffuseColor=(0.7, 0.3, 0.2),
                            specularColor=(1.0, 1.0, 1.0),
                            shininess=0.5
                        )
                    )
                ),
                basenodes.DirectionalLight(direction=(0.5, -1.0, -0.5), intensity=1.0),
            ]
        )
''',

    'multiple_lights': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.Sphere(radius=1.0),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(
                            diffuseColor=(0.9, 0.9, 0.9),
                            specularColor=(1.0, 1.0, 1.0),
                            shininess=0.8
                        )
                    )
                ),
                basenodes.DirectionalLight(direction=(1, 0, -0.5), color=(1, 0, 0), intensity=0.7),
                basenodes.DirectionalLight(direction=(-1, 0, -0.5), color=(0, 1, 0), intensity=0.7),
                basenodes.DirectionalLight(direction=(0, -1, -0.5), color=(0, 0, 1), intensity=0.7),
            ]
        )
''',

    'point_light': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    translation=(0, -1, 0),
                    rotation=(1, 0, 0, -1.57),
                    children=[basenodes.Shape(
                        geometry=basenodes.Box(size=(4, 4, 0.1)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.6, 0.6, 0.6))
                        )
                    )]
                ),
                basenodes.Shape(
                    geometry=basenodes.Sphere(radius=0.5),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(0.8, 0.4, 0.1))
                    )
                ),
                basenodes.PointLight(
                    location=(0, 2, 2),
                    color=(1, 1, 0.9),
                    intensity=1.0,
                    attenuation=(1.0, 0.1, 0.01)
                ),
            ]
        )
''',

    'spot_light': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    translation=(0, -1, 0),
                    rotation=(1, 0, 0, -1.57),
                    children=[basenodes.Shape(
                        geometry=basenodes.Box(size=(4, 4, 0.1)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.7, 0.7, 0.7))
                        )
                    )]
                ),
                basenodes.Shape(
                    geometry=basenodes.Cylinder(radius=0.3, height=0.8),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(0.3, 0.5, 0.8))
                    )
                ),
                basenodes.SpotLight(
                    location=(0, 3, 3),
                    direction=(0, -0.7, -0.7),
                    color=(1, 1, 1),
                    intensity=1.5,
                    cutOffAngle=0.4,
                    beamWidth=0.2
                ),
            ]
        )
''',

    'material_properties': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    translation=(-2, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.5),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.5, 0.2, 0.2), ambientIntensity=0.8)
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(0, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.5),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.2, 0.5, 0.2), specularColor=(1, 1, 1), shininess=0.9)
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(2, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.5),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.1, 0.1, 0.3), emissiveColor=(0.3, 0.3, 0.8))
                        )
                    )]
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=1.0),
            ]
        )
''',

    'transparency': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    translation=(0, 0, -1),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.8),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.8, 0.2, 0.2))
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(0.5, 0, 0.5),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.6),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.2, 0.2, 0.8), transparency=0.5)
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(-0.5, 0, 0.3),
                    children=[basenodes.Shape(
                        geometry=basenodes.Box(size=(0.8, 0.8, 0.8)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.2, 0.8, 0.2), transparency=0.3)
                        )
                    )]
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=1.0),
            ]
        )
''',

    'textured_box': '''
from PIL import Image
import numpy as np
import tempfile
import os

class SceneSetup(BaseContext):
    def OnInit(self):
        # Create checkerboard texture
        size = 64
        checker = np.zeros((size, size, 3), dtype=np.uint8)
        for i in range(size):
            for j in range(size):
                if (i // 8 + j // 8) % 2 == 0:
                    checker[i, j] = [255, 200, 100]
                else:
                    checker[i, j] = [100, 50, 20]

        img = Image.fromarray(checker)
        self.tex_path = os.path.join(tempfile.gettempdir(), 'regression_checker.png')
        img.save(self.tex_path)

        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.Box(size=(2, 2, 2)),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(1, 1, 1)),
                        texture=basenodes.ImageTexture(url=[self.tex_path])
                    )
                ),
                basenodes.DirectionalLight(direction=(0.3, -1, -0.5), intensity=1.0),
            ]
        )
''',

    'texture_transform': '''
from PIL import Image
import numpy as np
import tempfile
import os

class SceneSetup(BaseContext):
    def OnInit(self):
        # Create gradient texture
        size = 64
        gradient = np.zeros((size, size, 3), dtype=np.uint8)
        for i in range(size):
            for j in range(size):
                gradient[i, j] = [int(255 * i / size), int(255 * j / size), 128]

        img = Image.fromarray(gradient)
        self.tex_path = os.path.join(tempfile.gettempdir(), 'regression_gradient.png')
        img.save(self.tex_path)

        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.Box(size=(2, 2, 0.2)),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(1, 1, 1)),
                        texture=basenodes.ImageTexture(url=[self.tex_path]),
                        textureTransform=basenodes.TextureTransform(scale=(2, 2), rotation=0.785, center=(0.5, 0.5))
                    )
                ),
                basenodes.DirectionalLight(direction=(0, -1, -0.5), intensity=1.0),
            ]
        )
''',

    'complex_scene': '''
class SceneSetup(BaseContext):
    def OnInit(self):
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    translation=(0, -1.5, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Box(size=(6, 0.1, 6)),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.4, 0.4, 0.4))
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(-1.2, -0.5, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Teapot(size=0.8),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.7, 0.3, 0.1), specularColor=(1, 1, 1), shininess=0.6)
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(1.2, 0, 0),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=0.6),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.1, 0.3, 0.6), specularColor=(1, 1, 1), shininess=0.9)
                        )
                    )]
                ),
                basenodes.Transform(
                    translation=(0, 0, 1.2),
                    children=[basenodes.Shape(
                        geometry=basenodes.Cylinder(radius=0.3, height=1.5),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.6, 0.6, 0.2))
                        )
                    )]
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=0.8),
                basenodes.DirectionalLight(direction=(-0.5, -0.3, -0.5), color=(0.6, 0.6, 0.8), intensity=0.4),
            ]
        )
''',

    'nurbs_surface': '''
from OpenGLContext.arrays import zeros, array

class SceneSetup(BaseContext):
    initialPosition = (0, 0, 4)

    def buildControlPoints(self, centerHeight=3.0, edgeHeight=-3.0):
        """Build 4x4 control point grid for NURBS surface."""
        ctlpoints = zeros((4, 4, 3), "d")
        for u in range(4):
            for v in range(4):
                ctlpoints[u][v][0] = 2.0 * (u - 1.5)
                ctlpoints[u][v][1] = 2.0 * (v - 1.5)
                if (u == 1 or u == 2) and (v == 1 or v == 2):
                    ctlpoints[u][v][2] = centerHeight
                else:
                    ctlpoints[u][v][2] = edgeHeight
        return ctlpoints

    def OnInit(self):
        knots = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        color = zeros((4, 4, 3), "d")
        color[0, :, :] = (1.0, 0, 0)
        color[1, :, :] = (0.66, 0.33, 0)
        color[2, :, :] = (0.33, 0.66, 0)
        color[3, :, :] = (0, 1.0, 0)

        trimmingContour = [
            basenodes.Contour2D(
                children=[
                    basenodes.Polyline2D(
                        point=array([[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]], "d")
                    ),
                ],
            ),
            basenodes.Contour2D(
                children=[
                    basenodes.Polyline2D(
                        point=array([[0.75, 0.5], [0.5, 0.25], [0.25, 0.5]], "d")
                    ),
                    basenodes.NurbsCurve2D(
                        knot=array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], "d"),
                        controlPoint=array([[0.25, 0.5], [0.25, 0.75], [0.75, 0.75], [0.75, 0.5]], "d"),
                    ),
                ]
            ),
        ]

        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Transform(
                    scale=[0.5, 0.5, 0.5],
                    rotation=[1, 0, 0, -0.5],
                    children=[
                        basenodes.Shape(
                            appearance=basenodes.Appearance(material=basenodes.Material()),
                            geometry=basenodes.TrimmedSurface(
                                surface=basenodes.NurbsSurface(
                                    controlPoint=self.buildControlPoints(),
                                    color=color,
                                    vDimension=4,
                                    uDimension=4,
                                    uKnot=knots,
                                    vKnot=knots,
                                    sampling=basenodes.NurbsToleranceSample(tolerance=3.0),
                                ),
                                trimmingContour=trimmingContour,
                            ),
                        )
                    ],
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=1.0),
            ]
        )
''',

    'text_3d': '''
from OpenGL.GL import glPushMatrix, glPopMatrix, glTranslatef, glScalef, glColor3f, glLineWidth
from OpenGL.GLUT import glutStrokeCharacter, GLUT_STROKE_ROMAN

class SceneSetup(BaseContext):
    initialPosition = (0, 0, 10)

    def OnInit(self):
        # Create a simple scene with geometry - text will be rendered in Render method
        self.sg = basenodes.sceneGraph(
            children=[
                # Background sphere to show depth
                basenodes.Transform(
                    translation=(0, 0, -3),
                    children=[basenodes.Shape(
                        geometry=basenodes.Sphere(radius=1.5),
                        appearance=basenodes.Appearance(
                            material=basenodes.Material(diffuseColor=(0.3, 0.3, 0.5))
                        )
                    )]
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=1.0),
            ]
        )

    def Render(self, mode=None):
        """Render scene with 3D stroke text."""
        result = super().Render(mode)

        # Render 3D stroke text using GLUT
        glPushMatrix()
        try:
            glTranslatef(-3.0, 1.0, 0.0)
            glScalef(0.01, 0.01, 0.01)  # GLUT stroke fonts are large (about 100 units high)
            glColor3f(1.0, 0.8, 0.2)
            glLineWidth(2.0)
            for char in "3D TEXT":
                glutStrokeCharacter(GLUT_STROKE_ROMAN, ord(char))
        finally:
            glPopMatrix()

        return result
''',

    'text_2d': '''
from OpenGL.GL import glColor4f, glRasterPos3f, glPushAttrib, glPopAttrib, glDisable
from OpenGL.GL import GL_LIGHTING, GL_DEPTH_TEST, GL_ALL_ATTRIB_BITS
from OpenGLContext.scenegraph.text import glutfont

class SceneSetup(BaseContext):
    def OnInit(self):
        # Create font for 2D text rendering
        self.font = glutfont.GLUTFontProvider.get(basenodes.FontStyle(family=["SANS"]))

        # Create a simple scene with geometry behind the text
        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.Sphere(radius=1.0),
                    appearance=basenodes.Appearance(
                        material=basenodes.Material(diffuseColor=(0.3, 0.5, 0.7))
                    )
                ),
                basenodes.DirectionalLight(direction=(0.5, -1, -0.5), intensity=1.0),
            ]
        )

    def Render(self, mode=None):
        """Render scene with 2D text overlay."""
        # First render the 3D scene
        result = super().Render(mode)

        # Then render 2D text overlay
        glPushAttrib(GL_ALL_ATTRIB_BITS)
        try:
            glDisable(GL_DEPTH_TEST)
            glDisable(GL_LIGHTING)
            glColor4f(1.0, 1.0, 0.0, 1.0)
            glRasterPos3f(-2.5, 2.0, 0.0)
            self.font.render("2D Text Overlay")
            glRasterPos3f(-2.5, 1.5, 0.0)
            self.font.render("Line 2: Testing")
        finally:
            glPopAttrib()

        return result
''',

    'indexed_lineset': '''
import math
from OpenGLContext.arrays import zeros, sin, cos, arange

class SceneSetup(BaseContext):
    initialPosition = (0, 0, 3)

    def OnInit(self):
        # Create a circular IndexedLineSet with per-vertex colors
        a = arange(0.0, 2 * math.pi, 0.02)
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

        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.IndexedLineSet(
                        coord=basenodes.Coordinate(point=coords),
                        coordIndex=list(range(len(coords))),
                        color=basenodes.Color(color=colors),
                        colorIndex=list(range(len(coords))),
                    ),
                ),
            ]
        )
''',

    'indexed_lineset_large': '''
from OpenGLContext.arrays import arange

class SceneSetup(BaseContext):
    """Test with lorentz-like large data (10000 points)."""
    initialPosition = (0, 0, 100)

    def lorentz(self, iterations=10000, start=(0, -2, -1)):
        """Calculate the lorentz equation."""
        h = 0.01
        a = 10.0
        b = 28.0
        c = 8.0 / 3.0
        x0, y0, z0 = start
        points = []
        for n in range(iterations):
            x1 = x0 + h * a * (y0 - x0)
            y1 = y0 + h * (x0 * (b - z0) - y0)
            z1 = z0 + h * (x0 * y0 - c * z0)
            x0, y0, z0 = x1, y1, z1
            points.append((x0, y0, z0))
        return points

    def OnInit(self):
        count = 10000
        points = self.lorentz(count)
        line = arange(0.0, 1.0, 1.0 / float(count))
        line2 = line[::-1]
        colors = list(zip(line, line2, [0] * len(line)))

        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.IndexedLineSet(
                        coord=basenodes.Coordinate(point=points),
                        coordIndex=list(range(len(points))),
                        color=basenodes.Color(color=colors),
                    ),
                ),
            ]
        )
''',

    'pointset': '''
import numpy as np

class SceneSetup(BaseContext):
    initialPosition = (0, 0, 5)

    def OnInit(self):
        # Create a grid of points with per-vertex colors
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

        self.sg = basenodes.sceneGraph(
            children=[
                basenodes.Shape(
                    geometry=basenodes.PointSet(
                        coord=basenodes.Coordinate(point=points),
                        color=basenodes.Color(color=colors),
                    )
                ),
            ]
        )
''',
}


def run_render(script_path: Path, output_path: Path, profile: str,
               backend: Optional[str] = None, timeout: int = RENDER_TIMEOUT) -> bool:
    """Run a rendering test and capture the output."""
    env = os.environ.copy()
    env['OPENGLCONTEXT_PROFILE'] = profile
    # Always use GLFW backend for reliable exit behavior
    env['OPENGLCONTEXT_BACKEND'] = backend or 'glfw'

    cmd = [
        sys.executable, '-u', str(script_path),
        '--record',
        '--output-dir', str(output_path.parent),
        '--capture-delay', str(CAPTURE_DELAY),
        '--exit-after'
    ]

    try:
        result = subprocess.run(
            cmd, env=env, timeout=timeout,
            capture_output=True, text=True
        )
        # The script saves to {output_dir}/{test_name}.png
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"    Timeout after {timeout}s")
        return False
    except Exception as e:
        print(f"    Error: {e}")
        return False


@dataclass
class DiffResult:
    """Result of comparing two images."""
    pixels_different: int
    total_pixels: int
    mean_diff: float
    max_diff: int
    img1_content_pixels: int  # Non-black pixels in first image
    img2_content_pixels: int  # Non-black pixels in second image
    content_ratio: float  # How different the content amounts are


def calculate_diff(img1_path: Path, img2_path: Path,
                   diff_path: Optional[Path] = None) -> DiffResult:
    """Calculate difference between two images using ComparisonResult."""
    Image = ensure_pillow()
    if Image is None:
        return DiffResult(0, 0, 0.0, 0, 0, 0, 0.0)

    img1 = Image.open(img1_path).convert('RGB')
    img2 = Image.open(img2_path).convert('RGB')

    # Ensure same size
    if img1.size != img2.size:
        img2 = img2.resize(img1.size, Image.LANCZOS)

    arr1 = np.array(img1, dtype=np.uint8)
    arr2 = np.array(img2, dtype=np.uint8)

    # Use the existing ComparisonResult class
    result = ComparisonResult(arr1, arr2, threshold=0)

    # Save diff image if requested
    if diff_path and result.diff_image is not None:
        diff_img = Image.fromarray(result.diff_image, mode='RGB')
        diff_img.save(diff_path)

    # Calculate content statistics
    content1 = count_non_black_pixels(arr1)
    content2 = count_non_black_pixels(arr2)
    content_rat = calculate_content_ratio(content1, content2, result.total_pixels)

    return DiffResult(
        pixels_different=result.pixels_different,
        total_pixels=result.total_pixels,
        mean_diff=result.mean_diff,
        max_diff=int(result.max_diff),
        img1_content_pixels=content1,
        img2_content_pixels=content2,
        content_ratio=content_rat
    )


def run_test(test_config: dict, output_dir: Path, baseline_dir: Optional[Path],
             threshold: float) -> TestResult:
    """Run a single rendering test."""
    name = test_config['name']
    description = test_config['description']
    compat_only = test_config.get('compat_only', False)
    # Use per-test threshold if specified, otherwise use global threshold
    test_threshold = test_config.get('threshold', threshold)

    result = TestResult(name=name, description=description, compat_only=compat_only)

    # Generate the test script
    if name not in SCENE_CODE:
        result.error_message = f"No scene code for test: {name}"
        return result

    script_path = generate_test_script(name, SCENE_CODE[name], output_dir)

    # Define output paths
    compat_path = output_dir / f'{name}_compat.png'
    core_path = output_dir / f'{name}_core.png'
    diff_path = output_dir / f'{name}_diff.png'

    # The AutomatedRegressionContext saves to {output_dir}/{test_name}.png
    # We need to rename after capture

    # Run compatibility render
    print(f"  Running {name} (compatibility)...", end=' ', flush=True)
    if not run_render(script_path, compat_path, 'compatibility'):
        result.error_message = "Failed to render compatibility image"
        print("FAILED")
        return result

    # Rename the output file
    default_output = output_dir / f'{name}.png'
    if default_output.exists():
        default_output.rename(compat_path)
    if not compat_path.exists():
        result.error_message = "Compatibility image not created"
        print("FAILED")
        return result
    print("OK")
    result.compat_image = compat_path

    # Run core render
    print(f"  Running {name} (core)...", end=' ', flush=True)
    if not run_render(script_path, core_path, 'core', backend='glfw'):
        result.error_message = "Failed to render core image"
        print("FAILED")
        return result

    # Rename the output file
    if default_output.exists():
        default_output.rename(core_path)
    if not core_path.exists():
        result.error_message = "Core image not created"
        print("FAILED")
        return result
    print("OK")
    result.core_image = core_path

    # Calculate compat vs core diff
    diff_result = calculate_diff(compat_path, core_path, diff_path)
    result.diff_image = diff_path
    result.pixels_different = diff_result.pixels_different
    result.total_pixels = diff_result.total_pixels
    result.mean_diff = diff_result.mean_diff
    result.max_diff = diff_result.max_diff
    result.compat_content_pixels = diff_result.img1_content_pixels
    result.core_content_pixels = diff_result.img2_content_pixels
    result.content_ratio = diff_result.content_ratio
    result.similarity_error = calculate_similarity_error(
        diff_result.pixels_different, diff_result.mean_diff, diff_result.total_pixels
    )

    # Determine pass/fail with multiple criteria:
    # 1. Similarity error must be below threshold
    # 2. Content ratio must not indicate one image is mostly empty
    #    (if compat has content but core doesn't, that's a failure)
    CONTENT_THRESHOLD = 0.5  # Fail if >50% of content is missing
    content_ok = diff_result.content_ratio < CONTENT_THRESHOLD

    # Also check absolute content: if compat has significant content
    # but core has almost none, that's a failure
    MIN_CONTENT_RATIO = 0.3  # Core should have at least 30% of compat's content
    if diff_result.img1_content_pixels > 100:  # Compat has meaningful content
        core_content_ok = (diff_result.img2_content_pixels /
                          max(diff_result.img1_content_pixels, 1)) >= MIN_CONTENT_RATIO
    else:
        core_content_ok = True  # Both mostly empty, that's OK

    # For compat_only tests, we expect core to have no content (uses fixed-function features)
    # These tests pass if compat renders correctly (has content)
    if compat_only:
        result.passed = diff_result.img1_content_pixels > 100  # Compat has meaningful content
    else:
        result.passed = (result.similarity_error <= test_threshold and
                         content_ok and core_content_ok)

    # Check against baseline if available
    if baseline_dir:
        baseline_compat = baseline_dir / f'{name}_compat.png'
        if baseline_compat.exists():
            result.baseline_image = baseline_compat
            baseline_diff_path = output_dir / f'{name}_baseline_diff.png'

            b_diff = calculate_diff(baseline_compat, compat_path, baseline_diff_path)
            result.baseline_diff_image = baseline_diff_path
            result.baseline_pixels_different = b_diff.pixels_different
            result.baseline_mean_diff = b_diff.mean_diff
            result.baseline_similarity_error = calculate_similarity_error(
                b_diff.pixels_different, b_diff.mean_diff, b_diff.total_pixels
            )
            # Baseline should match exactly (or very close) for regression detection
            result.baseline_passed = result.baseline_similarity_error <= 0.01

    status = "PASS" if result.passed else "FAIL"
    if compat_only:
        detail = f"compat-only, content: {diff_result.img1_content_pixels} pixels"
    else:
        detail = f"error: {result.similarity_error:.4f}%"
        if not content_ok or not core_content_ok:
            detail += f", content: {diff_result.img2_content_pixels}/{diff_result.img1_content_pixels}"
    print(f"  Result: {status} ({detail})")

    return result


def generate_report(suite: TestSuite, output_dir: Path) -> str:
    """Generate a comprehensive markdown report."""
    report = []

    # Header
    report.append("# OpenGLContext Rendering Regression Report")
    report.append("")
    report.append(f"**Generated:** {suite.timestamp}")
    report.append(f"**Threshold:** {suite.threshold}%")
    report.append("")

    # Summary
    report.append("## Summary")
    report.append("")
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| Total Tests | {suite.total_tests} |")
    report.append(f"| Passed | {suite.passed_tests} |")
    report.append(f"| Failed | {suite.failed_tests} |")
    report.append(f"| Regressions | {suite.regression_tests} |")
    report.append("")

    # Overall status
    if suite.failed_tests == 0 and suite.regression_tests == 0:
        report.append("**All tests passed!**")
    else:
        if suite.failed_tests > 0:
            report.append(f"**{suite.failed_tests} test(s) failed!**")
        if suite.regression_tests > 0:
            report.append(f"**{suite.regression_tests} regression(s) detected!**")
    report.append("")

    # Results table
    report.append("## Results Overview")
    report.append("")
    report.append("| Test | Description | Error % | Status | Mode | Baseline |")
    report.append("|------|-------------|---------|--------|------|----------|")
    for r in suite.results:
        status = "PASS" if r.passed else "FAIL"
        mode = "compat-only" if r.compat_only else "both"
        baseline = "OK" if r.baseline_passed else "REGR"
        if not r.baseline_image:
            baseline = "-"
        error_pct = f"{r.similarity_error:.4f}%" if not r.compat_only else "N/A"
        report.append(f"| {r.name} | {r.description} | {error_pct} | {status} | {mode} | {baseline} |")
    report.append("")

    # Detailed results
    report.append("## Detailed Results")
    report.append("")

    for r in suite.results:
        report.append(f"### {r.name}")
        report.append("")
        report.append(f"**{r.description}**")
        report.append("")

        if r.error_message:
            report.append(f"**Error:** {r.error_message}")
            report.append("")
            continue

        # Metrics
        report.append("#### Metrics")
        report.append("")
        report.append("| Metric | Value |")
        report.append("|--------|-------|")
        if r.compat_only:
            report.append(f"| **Mode** | **Compat-only** (uses fixed-function features) |")
            report.append(f"| Compat Content | {r.compat_content_pixels:,} pixels |")
            report.append(f"| Status | {'PASS' if r.passed else 'FAIL'} |")
        else:
            pct_diff = 100 * r.pixels_different / r.total_pixels if r.total_pixels > 0 else 0
            report.append(f"| Pixels Different | {r.pixels_different:,} / {r.total_pixels:,} ({pct_diff:.2f}%) |")
            report.append(f"| Mean Difference | {r.mean_diff:.2f} |")
            report.append(f"| Max Difference | {r.max_diff} |")
            report.append(f"| **Similarity Error** | **{r.similarity_error:.4f}%** |")
            report.append(f"| Compat Content | {r.compat_content_pixels:,} pixels |")
            report.append(f"| Core Content | {r.core_content_pixels:,} pixels |")
            content_pct = 100 * r.core_content_pixels / max(r.compat_content_pixels, 1)
            report.append(f"| Content Ratio | {content_pct:.1f}% |")
            report.append(f"| Status | {'PASS' if r.passed else 'FAIL'} |")
        report.append("")

        # Baseline comparison
        if r.baseline_image:
            report.append("#### Baseline Comparison")
            report.append("")
            report.append(f"| Baseline Error | {r.baseline_similarity_error:.4f}% |")
            report.append(f"| Status | {'No regression' if r.baseline_passed else 'REGRESSION DETECTED'} |")
            report.append("")

        # Images
        report.append("#### Images")
        report.append("")

        if r.compat_image and r.compat_image.exists():
            report.append(f"**Compatibility:**")
            report.append(f"![{r.name} compat]({r.compat_image.name})")
            report.append("")

        if r.core_image and r.core_image.exists():
            report.append(f"**Core:**")
            report.append(f"![{r.name} core]({r.core_image.name})")
            report.append("")

        if r.diff_image and r.diff_image.exists():
            report.append(f"**Difference (amplified):**")
            report.append(f"![{r.name} diff]({r.diff_image.name})")
            report.append("")

        report.append("---")
        report.append("")

    return '\n'.join(report)


def main():
    parser = argparse.ArgumentParser(
        description='Run rendering regression tests'
    )
    parser.add_argument(
        '--output-dir', '-o',
        type=Path,
        default=Path('tests/regression_output'),
        help='Output directory for test results'
    )
    parser.add_argument(
        '--baseline-dir', '-b',
        type=Path,
        default=None,
        help='Baseline directory for regression detection'
    )
    parser.add_argument(
        '--threshold', '-t',
        type=float,
        default=DEFAULT_THRESHOLD,
        help=f'Similarity error threshold (default: {DEFAULT_THRESHOLD}%)'
    )
    parser.add_argument(
        '--update-baseline',
        action='store_true',
        help='Copy compat images to baseline after test'
    )
    parser.add_argument(
        '--tests',
        nargs='+',
        default=None,
        help='Run only specified tests (by name)'
    )
    parser.add_argument(
        '--list-tests',
        action='store_true',
        help='List available tests and exit'
    )

    args = parser.parse_args()

    if args.list_tests:
        print("Available tests:")
        for t in TEST_SCENES:
            print(f"  {t['name']}: {t['description']}")
        sys.exit(0)

    # Setup output directory
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # Filter tests if specified
    tests_to_run = TEST_SCENES
    if args.tests:
        tests_to_run = [t for t in TEST_SCENES if t['name'] in args.tests]
        if not tests_to_run:
            print(f"No matching tests found for: {args.tests}")
            print(f"Available tests: {[t['name'] for t in TEST_SCENES]}")
            sys.exit(1)

    # Create test suite
    timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    suite = TestSuite(
        name='OpenGLContext Rendering Regression',
        timestamp=timestamp,
        threshold=args.threshold
    )

    print(f"Running {len(tests_to_run)} rendering tests...")
    print(f"Output directory: {args.output_dir}")
    print(f"Threshold: {args.threshold}%")
    print()

    # Run tests
    for test_config in tests_to_run:
        print(f"Test: {test_config['name']}")
        result = run_test(
            test_config,
            args.output_dir,
            args.baseline_dir,
            args.threshold
        )
        suite.results.append(result)
        print()

    # Generate report
    report = generate_report(suite, args.output_dir)
    report_path = args.output_dir / 'regression_report.md'
    report_path.write_text(report)
    print(f"Report written to: {report_path}")

    # Update baseline if requested
    if args.update_baseline:
        baseline_dir = args.baseline_dir or (args.output_dir / 'baseline')
        baseline_dir.mkdir(parents=True, exist_ok=True)
        import shutil
        for result in suite.results:
            if result.compat_image and result.compat_image.exists():
                shutil.copy(result.compat_image, baseline_dir / result.compat_image.name)
        print(f"Baseline updated in: {baseline_dir}")

    # Summary
    print()
    print("=" * 60)
    print(f"Total: {suite.total_tests} | Passed: {suite.passed_tests} | Failed: {suite.failed_tests}")
    if suite.regression_tests > 0:
        print(f"Regressions detected: {suite.regression_tests}")
    print("=" * 60)

    # Exit code
    sys.exit(0 if suite.failed_tests == 0 else 1)


if __name__ == '__main__':
    main()
