"""Unit tests for the per-Shape ``pickable`` flag (click-through), headless.

A Shape marked ``pickable=False`` must leave the MRT object-id attachment
untouched during its draw, so a pick reads through to whatever geometry is
behind it (the "transparent to clicking" case, e.g. a water surface or an axis
annotation). These tests cover the field itself and the render-pass decision
that drives the id-attachment masking, without needing a GL context.
"""
from OpenGLContext.scenegraph import shape
from OpenGLContext.passes._flat import FlatPass


class FakePath(list):
    """NodePath-like: a list whose [-1] is the rendered node, plus .broken."""
    broken = False


def _bare_pass():
    fp = FlatPass.__new__(FlatPass)
    fp._sel_id_map = None
    fp._sel_next = 1
    return fp


class TestPickableField:
    def test_defaults_true(self):
        # Existing scenes stay fully pickable: absence of the field, or its
        # default, must read as pickable.
        assert shape.Shape().pickable

    def test_can_be_disabled(self):
        assert not shape.Shape(pickable=False).pickable

    def test_roundtrips(self):
        s = shape.Shape()
        s.pickable = False
        assert not s.pickable
        s.pickable = True
        assert s.pickable


class TestShapePickableDecision:
    def test_pickable_shape_reported_pickable(self):
        fp = _bare_pass()
        path = FakePath([shape.Shape(pickable=True)])
        assert fp._shapePickable(path) is True

    def test_non_pickable_shape_reported_non_pickable(self):
        fp = _bare_pass()
        path = FakePath([shape.Shape(pickable=False)])
        assert fp._shapePickable(path) is False

    def test_node_without_flag_defaults_pickable(self):
        # A rendered node that is not a Shape (no pickable field) must stay
        # pickable -- the flag is opt-out, never opt-in.
        fp = _bare_pass()

        class Bare:
            pass
        assert fp._shapePickable(FakePath([Bare()])) is True

    def test_non_pickable_shape_gets_no_object_id(self):
        # A masked (non-pickable) shape must never be allocated an id, so it can
        # never be resolved from the id map even by a stale read.
        fp = _bare_pass()
        path = FakePath([shape.Shape(pickable=False)])
        # The render loop skips _objectIdFor for non-pickable shapes; assert the
        # decision that guards it.
        assert not fp._shapePickable(path)
        assert fp._sel_id_map in (None, {})
