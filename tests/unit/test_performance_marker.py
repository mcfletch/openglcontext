"""When a ``performance``-marked test runs, and when it is passed over.

A test that asserts how *fast* something draws is asking a question about the
renderer as much as about the code, and a CPU rasteriser answers it wrongly by
three orders of magnitude -- so on one those tests are skipped rather than left
to fail. The decision is a plain function over a renderer description and an
environment so that it can be examined here; the plugin only applies it.
"""
import pytest

from OpenGLContext.testing.glcontext import GLDescription
from OpenGLContext.testing.plugin import (
    PERFORMANCE_TESTS,
    performance_skip_reason,
)

LLVMPIPE = GLDescription(vendor='Mesa', renderer='llvmpipe (LLVM 20.1.2)',
                         version='4.5 (Core Profile)')
GPU = GLDescription(vendor='AMD', renderer='Radeon 8060S Graphics',
                    version='4.6 (Core Profile)')


class TestTheRendererDecides:
    def test_a_gpu_runs_them(self):
        assert performance_skip_reason(GPU, {}) is None

    def test_a_cpu_rasteriser_does_not(self):
        reason = performance_skip_reason(LLVMPIPE, {})
        assert reason and 'llvmpipe' in reason

    def test_a_machine_with_no_gl_does_not_either(self):
        """Nothing to measure, and the fixtures would skip these anyway; saying
        so here gives the run one reason instead of a bare missing context."""
        assert performance_skip_reason(None, {}) is not None


class TestOverridingTheDecision:
    def test_it_can_be_insisted_on(self):
        """Somebody profiling the software rasteriser itself wants these to
        run, and is entitled to say so."""
        env = {PERFORMANCE_TESTS: '1'}
        assert performance_skip_reason(LLVMPIPE, env) is None

    def test_it_can_be_refused_on_a_gpu(self):
        """A shared or throttled machine is no place for a stopwatch, whatever
        it has in it."""
        env = {PERFORMANCE_TESTS: '0'}
        reason = performance_skip_reason(GPU, env)
        assert reason and PERFORMANCE_TESTS in reason

    def test_an_empty_setting_leaves_the_renderer_to_decide(self):
        """An unexported shell variable expands to this, and means the same as
        not setting it at all."""
        assert performance_skip_reason(GPU, {PERFORMANCE_TESTS: ''}) is None
        assert performance_skip_reason(LLVMPIPE, {PERFORMANCE_TESTS: ''}) is not None

    def test_a_value_that_is_neither_is_reported_rather_than_swallowed(self):
        """This variable is how a CI run pins the behaviour; a typo that
        silently reversed the pin would make that run's result a lie."""
        with pytest.raises(ValueError, match=PERFORMANCE_TESTS):
            performance_skip_reason(GPU, {PERFORMANCE_TESTS: 'maybe'})
