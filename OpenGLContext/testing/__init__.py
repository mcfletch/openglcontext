#! /usr/bin/env python
"""Testing utilities for OpenGLContext

This package provides utilities for testing OpenGLContext rendering:

- framebuffer_comparison: Compare rendered output between rendering paths
  or against saved reference images for regression testing
- subprocess_runner: Run tests in isolated subprocesses with coverage
- event_injector: Inject keyboard/mouse events for interactive testing
"""
from OpenGLContext.testing.framebuffer_comparison import (
    FramebufferCapture,
    ComparisonResult,
    compare_images,
    save_comparison_images,
    AutomatedRegressionContext,
    RegressionTestRunner,
    RegressionTestMixin,  # Legacy alias for AutomatedRegressionContext
    VisualRegressionTest,
    ProfileComparisonTest,
)
from OpenGLContext.testing.subprocess_runner import (
    TestResult,
    TestRunner,
    run_test,
    run_test_with_popen,
    kill_process_tree,
    DEFAULT_TIMEOUT,
    SLOW_TEST_TIMEOUT,
)
from OpenGLContext.testing.event_injector import (
    EventInjector,
    EventInjectionMixin,
    EventSender,
)
from OpenGLContext.testing.report_generator import (
    TestReportGenerator,
    generate_report,
)

__all__ = [
    # Framebuffer comparison
    'FramebufferCapture',
    'ComparisonResult',
    'compare_images',
    'save_comparison_images',
    'AutomatedRegressionContext',
    'RegressionTestRunner',
    'RegressionTestMixin',
    'VisualRegressionTest',
    'ProfileComparisonTest',
    # Subprocess runner
    'TestResult',
    'TestRunner',
    'run_test',
    'run_test_with_popen',
    'kill_process_tree',
    'DEFAULT_TIMEOUT',
    'SLOW_TEST_TIMEOUT',
    # Event injection
    'EventInjector',
    'EventInjectionMixin',
    'EventSender',
    # Report generation
    'TestReportGenerator',
    'generate_report',
]
