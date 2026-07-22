"""Robustness fixes in the legacy render-pass layer (no GL).

Covers three findings in `OpenGLContext/passes/renderpass.py`:
  3a — `OverallPass.__call__` referenced `self.visibleChange` even when the first
       sub-pass raised before it was ever set → `AttributeError`.
  3f — that same handler printed the traceback to stderr (bypassing logging) and
       continued, which is how the `cmp`/`visibleChange` bugs went unnoticed.
  3g — the frustum-culling mode was written to the *class* attribute
       (`self.__class__.frustumCulling`), so the first context to render decided
       culling for every context sharing the pass class.
"""
import logging
import types

from OpenGLContext.passes.renderpass import OverallPass, VisitingRenderPass


def _bare_overall(subpasses, on_swap):
    op = OverallPass.__new__(OverallPass)
    op.subPasses = subpasses
    op.context = types.SimpleNamespace(SwapBuffers=on_swap)
    return op


class TestOverallPassExceptionHandling:
    def test_first_subpass_exception_does_not_AttributeError(self, caplog):
        # 3a: a class-level default for visibleChange must exist so the trailing
        # `if self.visibleChange` doesn't blow up when the first pass raises.
        class Boom:
            def __call__(self):
                raise RuntimeError("boom in first pass")

        swaps = {'n': 0}
        op = _bare_overall([Boom()], lambda: swaps.__setitem__('n', swaps['n'] + 1))
        with caplog.at_level(logging.ERROR):
            result = op()            # must not raise
        assert result == 0
        assert swaps['n'] == 0       # nothing visible changed → no buffer swap

    def test_exception_is_logged_not_just_printed(self, caplog):
        # 3f: the failure must reach the logging system (with traceback), not only
        # a bare stderr print that leaves an empty log.
        class Boom:
            def __call__(self):
                raise RuntimeError("boom-should-be-logged")

        op = _bare_overall([Boom()], lambda: None)
        with caplog.at_level(logging.ERROR, logger='OpenGLContext.passes.renderpass'):
            op()
        assert any(r.levelno >= logging.ERROR and r.exc_info for r in caplog.records), \
            "expected an ERROR log record carrying exc_info"

    def test_successful_passes_swap_buffers(self):
        class Ok:
            def __call__(self):
                return 1
        swaps = {'n': 0}
        op = _bare_overall([Ok(), Ok()], lambda: swaps.__setitem__('n', swaps['n'] + 1))
        assert op() == 2
        assert swaps['n'] == 1


class TestFrustumCullingModeNotClassMutated:
    def test_detection_does_not_touch_class_attribute(self):
        # 3g: resolving the mode must not write the shared class attribute.
        ctx = types.SimpleNamespace(USE_FRUSTUM_CULLING=True,
                                    USE_OCCLUSION_CULLING=False)
        mode = VisitingRenderPass._detectFrustumCulling(ctx)
        assert mode == 1
        assert VisitingRenderPass.frustumCulling == -1, \
            "class attribute must stay at its -1 default"

    def test_mode_cached_on_context(self):
        calls = {'n': 0}

        class Ext:
            def initExtension(self, name):
                calls['n'] += 1
                return True
        ctx = types.SimpleNamespace(USE_FRUSTUM_CULLING=True,
                                    USE_OCCLUSION_CULLING=True, extensions=Ext())
        vp = VisitingRenderPass.__new__(VisitingRenderPass)
        vp.overall = types.SimpleNamespace(context=ctx)
        assert vp._frustumCullingMode() == 2
        assert vp._frustumCullingMode() == 2
        assert getattr(ctx, '_frustumCullingMode') == 2
        assert calls['n'] == 1, "detection should run once and cache on the context"

    def test_no_culling_when_flag_absent(self):
        ctx = types.SimpleNamespace()
        assert VisitingRenderPass._detectFrustumCulling(ctx) == 0
