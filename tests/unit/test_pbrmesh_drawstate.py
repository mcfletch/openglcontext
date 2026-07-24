"""Draw-state decisions for PBRMesh: double-sided culling (3.5) and per-draw
GL state-churn / leaked-winding avoidance (4.3). No real GL context -- the GL
entry points pbrmesh calls are monkeypatched to record calls."""
import numpy as np
import pytest

from OpenGLContext.scenegraph import pbrmesh
from OpenGLContext.scenegraph.pbrmesh import PBRMesh


class FakeMode:
    shader_mode = True
    shadow_pass = False
    def __init__(self, matrix=None):
        self.matrix = np.eye(4) if matrix is None else matrix


def _mesh():
    return PBRMesh(positions=np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f'), solid=True)


class TestWantsCull:
    def test_solid_mesh_culls_by_default(self):
        assert _mesh()._wants_cull(FakeMode()) is True

    def test_non_solid_mesh_disables_cull(self):
        m = PBRMesh(positions=np.zeros((3, 3), 'f'), solid=False)
        assert m._wants_cull(FakeMode()) is False

    def test_double_sided_material_disables_cull(self):
        mode = FakeMode()
        mode._appearance_double_sided = True     # published by configure_appearance
        assert _mesh()._wants_cull(mode) is False

    def test_shadow_pass_disables_cull(self):
        mode = FakeMode()
        mode.shadow_pass = True
        assert _mesh()._wants_cull(mode) is False


class _GLRec:
    def __init__(self, monkeypatch):
        self.calls = []
        monkeypatch.setattr(pbrmesh, 'glFrontFace',
                            lambda v: self.calls.append(('front', v)))
        monkeypatch.setattr(pbrmesh, 'glEnable',
                            lambda v: self.calls.append(('enable', v)))
        monkeypatch.setattr(pbrmesh, 'glDisable',
                            lambda v: self.calls.append(('disable', v)))


class TestStateChurn:
    def test_repeated_same_state_issues_calls_once(self, monkeypatch):
        rec = _GLRec(monkeypatch)
        m = _mesh()
        mode = FakeMode()
        m._apply_draw_state(mode)
        n_after_first = len(rec.calls)
        m._apply_draw_state(mode)   # identical state -> no new GL calls (4.3)
        assert len(rec.calls) == n_after_first
        assert n_after_first > 0    # first call did set winding + cull

    def test_winding_change_reissued(self, monkeypatch):
        rec = _GLRec(monkeypatch)
        m = _mesh()
        mode = FakeMode()
        m._apply_draw_state(mode)                      # CCW (identity det>0)
        mirror = np.diag([-1.0, 1.0, 1.0, 1.0])        # det<0 -> CW
        mode.matrix = mirror
        m._apply_draw_state(mode)
        fronts = [v for kind, v in rec.calls if kind == 'front']
        assert len(fronts) == 2 and fronts[0] != fronts[1]

    def test_reset_restores_ccw_and_clears_tracking(self, monkeypatch):
        rec = _GLRec(monkeypatch)
        m = _mesh()
        mode = FakeMode(np.diag([-1.0, 1.0, 1.0, 1.0]))   # CW winding
        m._apply_draw_state(mode)
        PBRMesh.reset_draw_state(mode)
        assert ('front', pbrmesh.GL_CCW) in rec.calls     # winding restored
        assert mode._pbr_front_face is None
        assert mode._pbr_cull_enabled is None

    def test_reset_reenables_culling_if_left_disabled(self, monkeypatch):
        rec = _GLRec(monkeypatch)
        mode = FakeMode()
        m = PBRMesh(positions=np.zeros((3, 3), 'f'), solid=False)  # disables cull
        m._apply_draw_state(mode)
        PBRMesh.reset_draw_state(mode)
        assert ('enable', pbrmesh.GL_CULL_FACE) in rec.calls


class _FakeContext:
    """Stand-in for the render context that carries the pending-delete queue."""


class TestFinalizerNeverTouchesGL:
    """3.3: _MeshGPU.__del__ must not call glDeleteVertexArrays -- GC can run it
    with no current context (leak) or a different context current (deleting an
    unrelated live VAO). It hands the id to a per-context queue instead, drained
    by the pass while the right context is current."""

    def _gpu(self, vao, queue):
        gpu = pbrmesh._MeshGPU.__new__(pbrmesh._MeshGPU)   # skip GL-touching __init__
        gpu.vao = vao
        gpu._pending_deletes = queue
        return gpu

    def test_del_enqueues_instead_of_deleting(self, monkeypatch):
        deleted = []
        monkeypatch.setattr(pbrmesh, 'glDeleteVertexArrays',
                            lambda n, ids: deleted.extend(ids))
        queue = []
        gpu = self._gpu(7, queue)
        gpu.__del__()
        assert deleted == []          # no GL from the finalizer
        assert queue == [7]           # id handed to the per-context queue

    def test_del_without_queue_is_silent(self, monkeypatch):
        deleted = []
        monkeypatch.setattr(pbrmesh, 'glDeleteVertexArrays',
                            lambda n, ids: deleted.extend(ids))
        gpu = self._gpu(9, None)
        gpu.__del__()                 # no queue attached -> nothing happens, no crash
        assert deleted == []

    def test_flush_deletes_queued_ids_once(self, monkeypatch):
        deleted = []
        monkeypatch.setattr(pbrmesh, 'glDeleteVertexArrays',
                            lambda n, ids: deleted.extend(ids))
        ctx = _FakeContext()
        mode = FakeMode()
        mode.context = ctx
        queue = PBRMesh._pending_delete_queue(mode)
        queue.extend([3, 4, 5])
        PBRMesh.flush_pending_deletes(mode)
        assert sorted(deleted) == [3, 4, 5]
        deleted.clear()
        PBRMesh.flush_pending_deletes(mode)   # idempotent: queue now empty
        assert deleted == []

    def test_queue_is_per_context(self):
        mode_a = FakeMode()
        mode_a.context = _FakeContext()
        mode_b = FakeMode()
        mode_b.context = _FakeContext()
        qa = PBRMesh._pending_delete_queue(mode_a)
        qb = PBRMesh._pending_delete_queue(mode_b)
        assert qa is not qb
        # same context -> same queue
        assert PBRMesh._pending_delete_queue(mode_a) is qa


class TestDefensiveTeardown:
    """The GL-teardown paths swallow driver/attribute failures so a bad frame can
    never crash the app. Each guard is provoked with a failing collaborator."""

    def _bare_gpu(self, vao=1):
        gpu = pbrmesh._MeshGPU.__new__(pbrmesh._MeshGPU)   # skip GL-touching __init__
        gpu.vao = vao
        gpu._instance_vao = None
        return gpu

    def test_release_swallows_delete_failure(self, monkeypatch):
        monkeypatch.setattr(pbrmesh, 'glDeleteVertexArrays',
                            lambda *a: (_ for _ in ()).throw(RuntimeError("bad ctx")))
        gpu = self._bare_gpu()
        gpu.release()                       # exception is caught
        assert gpu.vao is None              # slot still cleared

    def test_finalizer_swallows_enqueue_failure(self):
        class _BadQueue:
            def append(self, _v):
                raise RuntimeError("queue is full")

        gpu = self._bare_gpu(vao=7)
        gpu._pending_deletes = _BadQueue()
        gpu.__del__()                       # append raises -> swallowed, no crash
        assert gpu.vao is None

    def test_pending_queue_falls_back_when_context_is_unwritable(self):
        class _Slotted:
            __slots__ = ()                  # setattr of the queue attr will fail

        mode = FakeMode()
        mode.context = _Slotted()
        assert PBRMesh._pending_delete_queue(mode) == []   # can't stash -> empty list

    def test_flush_swallows_delete_failure(self, monkeypatch):
        monkeypatch.setattr(pbrmesh, 'glDeleteVertexArrays',
                            lambda *a: (_ for _ in ()).throw(RuntimeError("bad ctx")))
        mode = FakeMode()
        mode.context = _FakeContext()
        queue = PBRMesh._pending_delete_queue(mode)
        queue.append(11)
        PBRMesh.flush_pending_deletes(mode)   # delete raises -> caught
        assert queue == []                    # queue still drained


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
