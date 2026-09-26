"""The order the shader pass draws opaque shapes in.

Grouped by material, so consecutive shapes sharing one skip the appearance
upload, and front to back within a group.  The groups follow the order the
frame's shapes arrive in, which is the scene's order: two shapes whose
fragments land at the same depth are drawn in the same order every run, so the
frame is the same every run, rather than depending on where each material
happened to be allocated.
"""
from types import SimpleNamespace

import numpy as np

from OpenGLContext.passes._flat import opaqueDrawOrder


def _record(material, depth):
    """A record as the pass collects one: its modelview carries the depth."""
    matrix = np.identity(4)
    matrix[3, 2] = depth
    shape = SimpleNamespace(appearance=SimpleNamespace(material=material))
    return (None, matrix, None, None, None, shape)


def _material_after(earlier):
    """A material at a higher address than ``earlier``, so address order and
    arrival order disagree."""
    held = []
    while True:
        candidate = object()
        if id(candidate) > id(earlier):
            return candidate
        held.append(candidate)


def test_groups_follow_the_order_their_first_shape_arrives_in():
    second = object()
    first = _material_after(second)
    records = [_record(first, -1.0), _record(second, -2.0), _record(first, -3.0)]
    ordered = opaqueDrawOrder(list(enumerate(records)))
    assert [index for index, _record in ordered] == [0, 2, 1]


def test_within_a_group_the_nearest_is_drawn_first():
    material = object()
    records = [_record(material, -9.0), _record(material, -1.0), _record(material, -5.0)]
    ordered = opaqueDrawOrder(list(enumerate(records)))
    assert [index for index, _record in ordered] == [1, 2, 0]


def test_shapes_at_one_depth_keep_their_arrival_order():
    """What decides which of two coincident fragments is seen."""
    one, other = object(), object()
    records = [_record(other, -2.0), _record(one, -2.0), _record(other, -2.0)]
    ordered = opaqueDrawOrder(list(enumerate(records)))
    assert [index for index, _record in ordered] == [0, 2, 1]


def test_shapes_with_no_appearance_group_together():
    bare = (None, np.identity(4), None, None, None, SimpleNamespace())
    material = object()
    records = [bare, _record(material, -1.0), bare]
    ordered = opaqueDrawOrder(list(enumerate(records)))
    assert [index for index, _record in ordered] == [0, 2, 1]
