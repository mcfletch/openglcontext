#!/usr/bin/env python
"""Unit tests for OpenGLContext.passes.renderpass module."""

import unittest
from unittest import mock


class TestDefaultRenderPassesSceneSwap(unittest.TestCase):
    """The cached FLAT FlatPass must be rebuilt when the active scenegraph is replaced."""

    def setUp(self) -> None:
        from OpenGLContext.passes import renderpass
        self.renderpass = renderpass
        self._saved_flat = renderpass.FLAT
        renderpass.FLAT = None

    def tearDown(self) -> None:
        self.renderpass.FLAT = self._saved_flat

    def _make_context(self, sg, profile: str = 'compatibility'):
        ctx = mock.MagicMock()
        ctx.getSceneGraph.return_value = sg
        ctx.contextDefinition.profile = profile
        ctx.allContexts = []
        return ctx

    def test_first_call_creates_flat_for_current_scenegraph(self) -> None:
        sg = object()
        ctx = self._make_context(sg)
        runner = self.renderpass._defaultRenderPasses()

        with mock.patch('OpenGLContext.passes.flatcompat.FlatPass') as FlatPassCls:
            FlatPassCls.return_value.scene = sg
            runner(ctx)

        FlatPassCls.assert_called_once_with(sg, ctx.allContexts)
        self.assertIs(self.renderpass.FLAT.scene, sg)

    def test_swapping_scenegraph_rebuilds_flat(self) -> None:
        """When context.getSceneGraph() returns a different sg, FLAT is recreated."""
        sg_a = object()
        sg_b = object()
        runner = self.renderpass._defaultRenderPasses()

        with mock.patch('OpenGLContext.passes.flatcompat.FlatPass') as FlatPassCls:
            flat_a = mock.MagicMock()
            flat_a.scene = sg_a
            flat_b = mock.MagicMock()
            flat_b.scene = sg_b
            FlatPassCls.side_effect = [flat_a, flat_b]

            ctx_a = self._make_context(sg_a)
            runner(ctx_a)
            self.assertIs(self.renderpass.FLAT, flat_a)

            ctx_b = self._make_context(sg_b)
            runner(ctx_b)
            self.assertIs(self.renderpass.FLAT, flat_b)

        self.assertEqual(FlatPassCls.call_count, 2)

    def test_same_scenegraph_reuses_flat(self) -> None:
        """When the scenegraph is unchanged, FLAT is reused."""
        sg = object()
        runner = self.renderpass._defaultRenderPasses()

        with mock.patch('OpenGLContext.passes.flatcompat.FlatPass') as FlatPassCls:
            flat = mock.MagicMock()
            flat.scene = sg
            FlatPassCls.return_value = flat

            ctx = self._make_context(sg)
            runner(ctx)
            runner(ctx)

        FlatPassCls.assert_called_once()


if __name__ == '__main__':
    unittest.main()
