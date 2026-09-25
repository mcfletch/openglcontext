"""Instances of opposite modelview determinant (mirror / negative scale) must not
share one instanced draw: a batch has a single front-face winding, so mixing +det
and -det instances mis-culls and mis-lights the negatively-scaled ones
(NegativeScaleTest). The grouping must split them by winding sign.
"""
from OpenGLContext.passes.instancing import build_instance_groups


class FakeGeometry:
    def __init__(self, name):
        self.name = name


class FakeShape:
    def __init__(self, geometry, material):
        self.geometry = geometry
        self.appearance = type('A', (), {'material': material, 'texture': None})()


def rec(shape, mv):
    key = (False, [], 0.0)
    return (key, mv, [[1]], None, [shape], shape)


IDENT = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
MIRROR_X = [[-1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]   # det < 0


def _one_key(path):
    return 'shared'      # every record shares a geometry/material key


class TestWindingSplit:
    def test_mixed_determinant_instances_split_into_two_groups(self):
        g = FakeGeometry('g')
        m = object()
        records = [
            rec(FakeShape(g, m), IDENT),
            rec(FakeShape(g, m), IDENT),
            rec(FakeShape(g, m), MIRROR_X),
            rec(FakeShape(g, m), MIRROR_X),
        ]
        groups, singles = build_instance_groups(records, min_instances=2, key=_one_key)
        assert len(groups) == 2, "positive- and negative-scale instances must not batch together"
        # each group is internally uniform in winding sign
        for grp in groups:
            dets = [_det3_sign(rec_[1]) for rec_ in grp.members]
            assert len(set(dets)) == 1

    def test_all_same_determinant_still_one_group(self):
        g = FakeGeometry('g')
        m = object()
        records = [rec(FakeShape(g, m), IDENT) for _ in range(4)]
        groups, singles = build_instance_groups(records, min_instances=2, key=_one_key)
        assert len(groups) == 1
        assert len(groups[0].members) == 4


def _det3_sign(mv):
    a = mv
    d = (a[0][0] * (a[1][1] * a[2][2] - a[1][2] * a[2][1])
         - a[0][1] * (a[1][0] * a[2][2] - a[1][2] * a[2][0])
         + a[0][2] * (a[1][0] * a[2][1] - a[1][1] * a[2][0]))
    return -1 if d < 0 else 1


class TestWindingSigns:
    def test_each_matrix_gets_its_own_sign(self):
        from OpenGLContext.passes.instancing import winding_signs
        import numpy as np
        scaled = np.diag([2.0, -3.0, 1.0, 1.0])
        assert winding_signs([IDENT, MIRROR_X, scaled, np.eye(4, dtype='f')]) == [1, -1, -1, 1]

    def test_matrices_that_do_not_stack_are_answered_one_at_a_time(self):
        from OpenGLContext.passes.instancing import winding_signs
        assert winding_signs([IDENT, MIRROR_X[:3], None]) == [1, -1, 1]

    def test_none_is_nothing(self):
        from OpenGLContext.passes.instancing import winding_signs
        assert winding_signs([]) == []
