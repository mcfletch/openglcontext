#! /usr/bin/env python
"""Testing utilities for OpenGLContext

This package provides utilities for testing OpenGLContext rendering:

- framebuffer_comparison: Compare rendered output between rendering paths
  or against saved reference images for regression testing
"""
from OpenGLContext.testing.framebuffer_comparison import (
    FramebufferCapture,
    ComparisonResult,
    compare_images,
    compare_side_by_side,
    RegressionTestMixin,
)

__all__ = [
    'FramebufferCapture',
    'ComparisonResult',
    'compare_images',
    'compare_side_by_side',
    'RegressionTestMixin',
]
