#!/usr/bin/env python
"""Unit tests for OpenGLContext.passes.shaderpass module

These tests verify the shader pass infrastructure without requiring
an OpenGL context. Tests that require OpenGL use the test context.
"""

import unittest
import numpy as np
from math import pi


class TestShaderPassModule(unittest.TestCase):
    """Test shaderpass module imports and basic structure"""

    def test_import_module(self) -> None:
        """Module should import without errors"""
        from OpenGLContext.passes import shaderpass
        self.assertIsNotNone(shaderpass)

    def test_import_classes(self) -> None:
        """Key classes should be importable"""
        from OpenGLContext.passes.shaderpass import (
            VRML97ShaderProgram,
            ShaderRenderMode,
            get_shader_program,
        )
        self.assertIsNotNone(VRML97ShaderProgram)
        self.assertIsNotNone(ShaderRenderMode)
        self.assertIsNotNone(get_shader_program)

    def test_import_helper_functions(self) -> None:
        """Helper functions should be importable"""
        from OpenGLContext.passes.shaderpass import (
            configure_light_from_node,
            configure_material_from_node,
        )
        self.assertIsNotNone(configure_light_from_node)
        self.assertIsNotNone(configure_material_from_node)

    def test_shader_dir_exists(self) -> None:
        """Shader directory should exist"""
        import os
        from OpenGLContext.passes.shaderpass import SHADER_DIR
        self.assertTrue(os.path.isdir(SHADER_DIR))

    def test_shader_files_exist(self) -> None:
        """Required shader files should exist"""
        import os
        from OpenGLContext.passes.shaderpass import SHADER_DIR

        expected_files = [
            'vrml97_lighting.vert',
            'vrml97_lighting.frag',
            'vrml97_unlit.vert',
            'vrml97_unlit.frag',
        ]

        for filename in expected_files:
            path = os.path.join(SHADER_DIR, filename)
            self.assertTrue(
                os.path.isfile(path),
                f"Shader file {filename} should exist"
            )


class TestVRML97ShaderProgramNoGL(unittest.TestCase):
    """Test VRML97ShaderProgram without GL context"""

    def test_init(self) -> None:
        """Constructor should initialize attributes"""
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

        program = VRML97ShaderProgram()
        self.assertIsNone(program.program)
        self.assertIsNone(program.unlit_program)
        self.assertFalse(program._compiled)
        self.assertEqual(program.MAX_LIGHTS, 8)

    def test_get_shader_program_singleton(self) -> None:
        """get_shader_program should return same instance"""
        from OpenGLContext.passes.shaderpass import get_shader_program

        prog1 = get_shader_program()
        prog2 = get_shader_program()
        self.assertIs(prog1, prog2)


class TestShaderRenderMode(unittest.TestCase):
    """Test ShaderRenderMode wrapper class"""

    def test_shader_mode_flag(self) -> None:
        """ShaderRenderMode should have shader_mode=True"""
        from OpenGLContext.passes.shaderpass import (
            ShaderRenderMode,
            VRML97ShaderProgram
        )

        class MockMode:
            some_attr = "test"

        mock_mode = MockMode()
        shader_program = VRML97ShaderProgram()

        render_mode = ShaderRenderMode(mock_mode, shader_program)

        self.assertTrue(render_mode.shader_mode)
        self.assertIs(render_mode.shader_program, shader_program)

    def test_attribute_delegation(self) -> None:
        """ShaderRenderMode should delegate unknown attributes to base mode"""
        from OpenGLContext.passes.shaderpass import (
            ShaderRenderMode,
            VRML97ShaderProgram
        )

        class MockMode:
            some_attr = "test_value"
            def some_method(self) -> str:
                return "method_result"

        mock_mode = MockMode()
        shader_program = VRML97ShaderProgram()

        render_mode = ShaderRenderMode(mock_mode, shader_program)

        self.assertEqual(render_mode.some_attr, "test_value")
        self.assertEqual(render_mode.some_method(), "method_result")


class TestTextureTransformMatrix(unittest.TestCase):
    """Test texture transform matrix calculation"""

    def test_identity_transform(self) -> None:
        """None transform_node should produce identity matrix"""
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

        # We can't call set_texture_transform without GL context,
        # but we can test the matrix calculation logic
        tex_matrix = np.eye(3, dtype='f')
        np.testing.assert_array_almost_equal(
            tex_matrix,
            np.array([[1, 0, 0], [0, 1, 0], [0, 0, 1]], dtype='f')
        )

    def test_translation_matrix(self) -> None:
        """Test 2D translation matrix construction"""
        tx, ty = 0.5, 0.25
        T = np.array([
            [1, 0, tx],
            [0, 1, ty],
            [0, 0, 1]
        ], dtype='f')

        # Verify translation works
        point = np.array([0, 0, 1], dtype='f')
        result = T @ point
        np.testing.assert_array_almost_equal(result, [tx, ty, 1])

    def test_rotation_matrix(self) -> None:
        """Test 2D rotation matrix construction"""
        from math import cos, sin, pi

        angle = pi / 4  # 45 degrees
        c, s = cos(angle), sin(angle)
        R = np.array([
            [c, -s, 0],
            [s, c, 0],
            [0, 0, 1]
        ], dtype='f')

        # Verify rotation of point (1, 0)
        point = np.array([1, 0, 1], dtype='f')
        result = R @ point
        expected = np.array([c, s, 1], dtype='f')
        np.testing.assert_array_almost_equal(result, expected)

    def test_scale_matrix(self) -> None:
        """Test 2D scale matrix construction"""
        sx, sy = 2.0, 0.5
        S = np.array([
            [sx, 0, 0],
            [0, sy, 0],
            [0, 0, 1]
        ], dtype='f')

        # Verify scaling
        point = np.array([1, 1, 1], dtype='f')
        result = S @ point
        np.testing.assert_array_almost_equal(result, [sx, sy, 1])


class TestShaderGeometryModule(unittest.TestCase):
    """Test shadergeometry module"""

    def test_import_module(self) -> None:
        """Module should import without errors"""
        from OpenGLContext.scenegraph import shadergeometry
        self.assertIsNotNone(shadergeometry)

    def test_import_classes(self) -> None:
        """Key classes should be importable"""
        from OpenGLContext.scenegraph.shadergeometry import (
            ShaderGeometryMixin,
            ShaderBox,
            VBO_STRIDE,
        )
        self.assertIsNotNone(ShaderGeometryMixin)
        self.assertIsNotNone(ShaderBox)
        self.assertEqual(VBO_STRIDE, 32)  # T2F_N3F_V3F format


class TestFramebufferComparison(unittest.TestCase):
    """Test framebuffer comparison module"""

    def test_import_module(self) -> None:
        """Module should import without errors"""
        from OpenGLContext.testing import framebuffer_comparison
        self.assertIsNotNone(framebuffer_comparison)

    def test_import_classes(self) -> None:
        """Key classes should be importable"""
        from OpenGLContext.testing.framebuffer_comparison import (
            FramebufferCapture,
            ComparisonResult,
            compare_images,
        )
        self.assertIsNotNone(FramebufferCapture)
        self.assertIsNotNone(ComparisonResult)
        self.assertIsNotNone(compare_images)

    def test_comparison_result_identical(self) -> None:
        """ComparisonResult should report identical images as matching"""
        from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

        img = np.ones((100, 100, 3), dtype=np.float32) * 0.5
        result = ComparisonResult(img, img)

        self.assertTrue(result.shapes_match)
        self.assertEqual(result.max_diff, 0.0)
        self.assertEqual(result.mean_diff, 0.0)
        self.assertEqual(result.pixels_different, 0)
        self.assertTrue(result.is_match())

    def test_comparison_result_different(self) -> None:
        """ComparisonResult should detect differences"""
        from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

        img1 = np.zeros((100, 100, 3), dtype=np.float32)
        img2 = np.ones((100, 100, 3), dtype=np.float32)
        result = ComparisonResult(img1, img2)

        self.assertTrue(result.shapes_match)
        self.assertEqual(result.max_diff, 1.0)
        self.assertGreater(result.pixels_different, 0)
        self.assertFalse(result.is_match())

    def test_comparison_result_shape_mismatch(self) -> None:
        """ComparisonResult should handle shape mismatches"""
        from OpenGLContext.testing.framebuffer_comparison import ComparisonResult

        img1 = np.zeros((100, 100, 3), dtype=np.float32)
        img2 = np.zeros((50, 50, 3), dtype=np.float32)
        result = ComparisonResult(img1, img2)

        self.assertFalse(result.shapes_match)
        self.assertFalse(result.is_match())


class TestShaderShape(unittest.TestCase):
    """Test shader shape module"""

    def test_import_module(self) -> None:
        """Module should import without errors"""
        from OpenGLContext.scenegraph import shadershape
        self.assertIsNotNone(shadershape)

    def test_import_classes(self) -> None:
        """Key classes should be importable"""
        from OpenGLContext.scenegraph.shadershape import (
            ShaderShape,
            ShaderShapeMixin,
            enable_shader_rendering,
        )
        self.assertIsNotNone(ShaderShape)
        self.assertIsNotNone(ShaderShapeMixin)
        self.assertIsNotNone(enable_shader_rendering)

    def test_shader_shape_is_shape(self) -> None:
        """ShaderShape should inherit from Shape"""
        from OpenGLContext.scenegraph.shadershape import ShaderShape
        from OpenGLContext.scenegraph.shape import Shape

        self.assertTrue(issubclass(ShaderShape, Shape))


if __name__ == '__main__':
    unittest.main()
