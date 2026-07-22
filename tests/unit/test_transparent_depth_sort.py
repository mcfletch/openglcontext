"""Unit tests for the transparent-object depth sort (no GL).

``TransparentRenderPass.__call__`` sorted its projected objects with a Python-2
``cmp`` comparator (``items.sort(lambda x,y: cmp(x[0],y[0]))``) -- ``cmp`` does
not exist in Python 3, so the whole transparent pass raised ``NameError`` the
moment it had anything to draw. The sort is extracted to ``depthSort`` so it can
be exercised directly; these tests pin its ordering.
"""
from OpenGLContext.passes.renderpass import TransparentRenderPass


def _item(distance, tag):
    # (distance, object, matrix) triples as built in __call__; only [0] matters.
    return (distance, tag, None)


class TestDepthSort:
    def test_orders_far_to_near(self):
        # Post-sort order is farthest-first (largest projected depth first),
        # matching the historical sort-ascending-then-reverse behaviour.
        items = [_item(0.2, 'near'), _item(0.9, 'far'), _item(0.5, 'mid')]
        ordered = TransparentRenderPass.depthSort(items)
        assert [tag for _d, tag, _m in ordered] == ['far', 'mid', 'near']

    def test_stable_and_total(self):
        items = [_item(0.5, 'a'), _item(0.5, 'b'), _item(0.1, 'c')]
        ordered = TransparentRenderPass.depthSort(items)
        assert len(ordered) == 3
        # equal depths keep first-seen order after the far-to-near arrangement
        assert [tag for _d, tag, _m in ordered] == ['a', 'b', 'c']

    def test_empty(self):
        assert TransparentRenderPass.depthSort([]) == []
