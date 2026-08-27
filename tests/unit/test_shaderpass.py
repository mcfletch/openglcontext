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


class _TexNode:
    """Minimal stand-in for a VRML97 TextureTransform node."""

    def __init__(self, translation=(0.0, 0.0), center=(0.0, 0.0),
                 rotation=0.0, scale=(1.0, 1.0)):
        self.translation = translation
        self.center = center
        self.rotation = rotation
        self.scale = scale


def _reference_texture_matrix(node):
    """The original hand-written five-matrix construction, kept here as an
    independent oracle for the collapsed texture_transform_matrix()."""
    from math import cos, sin
    if node is None:
        return np.eye(3, dtype='f')
    tx, ty = node.translation
    cx, cy = node.center
    angle = node.rotation
    sx, sy = node.scale
    m = np.eye(3, dtype='f')
    if cx != 0 or cy != 0:
        m = m @ np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1]], dtype='f')
    if angle != 0:
        c, s = cos(angle), sin(angle)
        m = m @ np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype='f')
    if sx != 1 or sy != 1:
        m = m @ np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]], dtype='f')
    if cx != 0 or cy != 0:
        m = m @ np.array([[1, 0, -cx], [0, 1, -cy], [0, 0, 1]], dtype='f')
    if tx != 0 or ty != 0:
        m = m @ np.array([[1, 0, tx], [0, 1, ty], [0, 0, 1]], dtype='f')
    return m


class TestTextureTransformMatrix(unittest.TestCase):
    """3m: the collapsed texture_transform_matrix() builder must be identical to
    the original five hand-written matrices it replaced, and it is now a pure
    function callable without a GL context (the old tests could not call it)."""

    def test_identity_for_none(self) -> None:
        from OpenGLContext.passes.shaderpass import texture_transform_matrix
        np.testing.assert_array_almost_equal(
            texture_transform_matrix(None), np.eye(3, dtype='f'))

    def test_matches_reference_across_cases(self) -> None:
        from OpenGLContext.passes.shaderpass import texture_transform_matrix
        cases = [
            _TexNode(),                                        # all-identity fields
            _TexNode(translation=(0.5, 0.25)),
            _TexNode(rotation=pi / 4),
            _TexNode(scale=(2.0, 0.5)),
            _TexNode(center=(0.3, 0.7), rotation=pi / 3),
            _TexNode(translation=(0.1, -0.2), center=(0.3, 0.7),
                     rotation=0.9, scale=(1.5, 0.4)),           # everything at once
        ]
        for node in cases:
            np.testing.assert_array_almost_equal(
                texture_transform_matrix(node), _reference_texture_matrix(node),
                err_msg=f'mismatch for {vars(node)}')

    def test_center_pivots_rotation(self) -> None:
        """A rotation about a non-zero center leaves that center fixed in UV."""
        from OpenGLContext.passes.shaderpass import texture_transform_matrix
        node = _TexNode(center=(0.5, 0.5), rotation=pi / 2)
        m = texture_transform_matrix(node)
        fixed = m @ np.array([0.5, 0.5, 1.0], dtype='f')
        np.testing.assert_array_almost_equal(fixed[:2], [0.5, 0.5])

    def test_affine_helpers_build_expected_matrices(self) -> None:
        from math import cos, sin
        from OpenGLContext.passes import shaderpass as sp
        np.testing.assert_array_almost_equal(
            sp._affine2d_translate(0.5, 0.25),
            [[1, 0, 0.5], [0, 1, 0.25], [0, 0, 1]])
        np.testing.assert_array_almost_equal(
            sp._affine2d_scale(2.0, 0.5), [[2, 0, 0], [0, 0.5, 0], [0, 0, 1]])
        c, s = cos(0.7), sin(0.7)
        np.testing.assert_array_almost_equal(
            sp._affine2d_rotate(0.7), [[c, -s, 0], [s, c, 0], [0, 0, 1]])


class TestSetUniformCollapse(unittest.TestCase):
    """3m: the five near-identical _set_uniform* methods now normalize their value
    and delegate to one shared _set_uniform(name, value, program, upload) body."""

    def _prog(self):
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        sp = VRML97ShaderProgram.__new__(VRML97ShaderProgram)
        calls = []
        sp._set_uniform = lambda name, value, program, upload: calls.append(
            (name, value, program, upload))
        return sp, calls

    def test_int_wrapper_normalizes_and_picks_setter(self) -> None:
        from OpenGLContext.passes import shaderpass as m
        sp, calls = self._prog()
        sp._set_uniform1i('flag', 3.9)
        name, value, program, upload = calls[-1]
        self.assertEqual(value, 3)
        self.assertIs(type(value), int)
        self.assertIs(upload, m.glUniform1i)
        self.assertIsNone(program)

    def test_vec_wrapper_normalizes_to_float_tuple(self) -> None:
        from OpenGLContext.passes import shaderpass as m
        sp, calls = self._prog()
        sp._set_uniform3f('c', (1, 2, 3), program=7)
        name, value, program, upload = calls[-1]
        self.assertEqual(value, (1.0, 2.0, 3.0))
        self.assertTrue(all(isinstance(v, float) for v in value))
        self.assertIs(upload, m._UPLOAD_3FV)
        self.assertEqual(program, 7)

    def test_shared_body_skips_unchanged_and_uploads_changed(self) -> None:
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        sp = VRML97ShaderProgram.__new__(VRML97ShaderProgram)
        sp.program = 1
        sp._uniform_value_cache = {}
        sp._get_location = lambda name, program: 5
        uploaded = []
        upload = lambda loc, value: uploaded.append((loc, value))
        sp._set_uniform('x', 3, None, upload)
        sp._set_uniform('x', 3, None, upload)   # unchanged -> skipped
        sp._set_uniform('x', 4, None, upload)   # changed -> uploaded
        self.assertEqual(uploaded, [(5, 3), (5, 4)])

    def test_shared_body_skips_when_location_absent(self) -> None:
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        sp = VRML97ShaderProgram.__new__(VRML97ShaderProgram)
        sp.program = 1
        sp._uniform_value_cache = {}
        sp._get_location = lambda name, program: -1
        uploaded = []
        sp._set_uniform('x', 3, None, lambda loc, value: uploaded.append(value))
        self.assertEqual(uploaded, [])


class TestShaderGeometryModule(unittest.TestCase):
    """Test shadergeometry module"""

    def test_import_module(self) -> None:
        """Module should import without errors"""
        from OpenGLContext.scenegraph import shadergeometry
        self.assertIsNotNone(shadergeometry)

    def test_import_functions(self) -> None:
        """Key names should be importable"""
        from OpenGLContext.scenegraph.shadergeometry import (
            VBO_STRIDE,
            VertexFormat,
            get_or_build_vao,
        )
        self.assertIsNotNone(get_or_build_vao)
        self.assertEqual(VBO_STRIDE, 32)  # both interleaved layouts
        self.assertEqual(VertexFormat.T2F_N3F_V3F['position_offset'], 20)
        self.assertEqual(VertexFormat.V3F_T2F_N3F['position_offset'], 0)


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


class TestNormalMatrix(unittest.TestCase):
    """normal_matrix must equal inv(M[:3,:3]).T without a per-shape LAPACK call."""

    def test_matches_inverse_transpose_random(self) -> None:
        from OpenGLContext.passes.shaderpass import normal_matrix
        rng = np.random.default_rng(7)
        for _ in range(200):
            M = np.eye(4, dtype='f')
            M[:3, :3] = rng.standard_normal((3, 3)).astype('f')
            ref = np.linalg.inv(M[:3, :3]).T
            got = normal_matrix(M)
            self.assertTrue(np.abs(got - ref).max() < 1e-3)
            self.assertEqual(got.dtype, np.dtype('float32'))

    def test_rotation_maps_to_itself(self) -> None:
        # For an orthonormal (pure-rotation) modelview the normal matrix is the
        # rotation itself; a translation in the 4th row must not affect it.
        from OpenGLContext.passes.shaderpass import normal_matrix
        from math import cos, sin, pi
        a = pi / 5
        R = np.eye(4, dtype='f')
        R[:3, :3] = [[cos(a), -sin(a), 0], [sin(a), cos(a), 0], [0, 0, 1]]
        R[3, :3] = [10.0, -3.0, 2.0]
        self.assertTrue(np.abs(normal_matrix(R) - R[:3, :3]).max() < 1e-4)

    def test_singular_falls_back_to_upper_3x3(self) -> None:
        from OpenGLContext.passes.shaderpass import normal_matrix
        M = np.eye(4, dtype='f')
        M[:3, :3] = 0.0
        out = normal_matrix(M)
        self.assertEqual(out.shape, (3, 3))
        self.assertEqual(out.dtype, np.dtype('float32'))


class TestDepthProgram(unittest.TestCase):
    """The VRML97 program uses a real position-only depth program in
    the shadow pass instead of falling back to the full lit+shadow shader."""

    def _program(self, depth):
        from OpenGLContext.passes import shaderpass
        p = shaderpass.VRML97ShaderProgram.__new__(shaderpass.VRML97ShaderProgram)
        p._compiled = True
        p._ok = True  # simulate a fully-linked program
        p.program = 10
        p.depth_program = depth
        return p

    def test_use_depth_prefers_depth_program(self):
        from unittest import mock
        from OpenGLContext.passes import shaderpass
        p = self._program(depth=42)
        with mock.patch.object(shaderpass, 'glUseProgram') as gu:
            result = p.use_depth()
        self.assertEqual(result, 42)
        gu.assert_called_once_with(42)

    def test_use_depth_falls_back_when_absent(self):
        # backward-compat: a program with no depth program still binds the lit one
        from unittest import mock
        from OpenGLContext.passes import shaderpass
        p = self._program(depth=None)
        with mock.patch.object(shaderpass, 'glUseProgram') as gu:
            result = p.use_depth()
        self.assertEqual(result, 10)

    def test_compile_source_compiles_shadow_depth(self):
        # lock that the base VRML97 compile path builds the depth program
        import inspect
        from OpenGLContext.passes.shaderpass import VRML97ShaderProgram
        src = inspect.getsource(VRML97ShaderProgram.compile)
        self.assertIn('shadow_depth.vert', src)
        self.assertIn('self.depth_program', src)


if __name__ == '__main__':
    unittest.main()
