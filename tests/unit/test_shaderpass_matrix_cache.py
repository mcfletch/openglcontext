"""set_matrices skips redundant modelview uploads and the normal-matrix solve.

Merged static scenes render many shapes under one shared transform, so the
modelview (and its derived normal matrix) repeat draw after draw. set_matrices
must upload/recompute them only when the modelview actually changes, while still
uploading correctly whenever it does. The GL entry points are monkeypatched to
count calls -- no real context.
"""
import numpy as np
import pytest

from OpenGLContext.passes import shaderpass
from OpenGLContext.passes.shaderpass import VRML97ShaderProgram


PROG = 7


@pytest.fixture
def rec(monkeypatch):
    counts = {'mv4': 0, 'm3': 0, 'normal_solve': 0}
    monkeypatch.setattr(shaderpass, 'glUniformMatrix4fv',
                        lambda *a: counts.__setitem__('mv4', counts['mv4'] + 1))
    monkeypatch.setattr(shaderpass, 'glUniformMatrix3fv',
                        lambda *a: counts.__setitem__('m3', counts['m3'] + 1))
    real_normal = shaderpass.normal_matrix

    def counting_normal(m):
        counts['normal_solve'] += 1
        return real_normal(m)
    monkeypatch.setattr(shaderpass, 'normal_matrix', counting_normal)
    return counts


def _program():
    p = VRML97ShaderProgram.__new__(VRML97ShaderProgram)
    p._uniform_value_cache = {}
    p._location_cache = {}
    p.program = PROG
    p.vertex_color_program = PROG + 1
    p._get_location = lambda name, program=None: 1     # always a valid location
    return p


def test_repeated_identical_modelview_uploaded_once(rec):
    p = _program()
    mv, proj = np.eye(4), np.eye(4) * 2.0

    p.set_matrices(mv, proj, program=PROG)
    # first draw: modelview + projection uploaded, normal solved+uploaded once
    assert rec['mv4'] == 2 and rec['m3'] == 1 and rec['normal_solve'] == 1

    p.set_matrices(mv, proj, program=PROG)
    p.set_matrices(mv, proj, program=PROG)
    # identical draws: nothing re-uploaded, normal never re-solved
    assert rec['mv4'] == 2 and rec['m3'] == 1 and rec['normal_solve'] == 1


def test_changed_modelview_reuploads_and_resolves_normal(rec):
    p = _program()
    proj = np.eye(4) * 2.0
    p.set_matrices(np.eye(4), proj, program=PROG)
    base_mv4, base_m3 = rec['mv4'], rec['m3']

    moved = np.eye(4)
    moved[0, 3] = 5.0
    p.set_matrices(moved, proj, program=PROG)
    # modelview re-uploaded (+1) and normal re-solved+uploaded (+1); projection stays cached
    assert rec['mv4'] == base_mv4 + 1
    assert rec['m3'] == base_m3 + 1
    assert rec['normal_solve'] == 2


def test_cache_is_per_program(rec):
    p = _program()
    mv, proj = np.eye(4), np.eye(4) * 2.0
    p.set_matrices(mv, proj, program=PROG)
    before = rec['mv4']
    # same matrices, different program -> its own cache, so it must upload again
    p.set_matrices(mv, proj, program=PROG + 1)
    assert rec['mv4'] > before
