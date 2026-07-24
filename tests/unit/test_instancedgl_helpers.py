"""Portability/teardown helpers shared by the instanced veg/terrain nodes.

Covers the graceful-degradation guard (a GL/shader init failure disables the node
instead of crashing the frame loop) and the in-memory texture-upload path (an
embedded image uploads without writing a file beside a read-only asset). Neither
needs a real GL context: the GL entry points are stubbed.
"""
import numpy as np
from PIL import Image

import OpenGLContext.scenegraph.instancedgl as ig


class _Node:
    """Minimal stand-in with the (_gl, _init_gl) contract ensure_gl relies on."""
    def __init__(self, fail=False):
        self._gl = None
        self._fail = fail
        self.inits = 0

    def _init_gl(self):
        self.inits += 1
        if self._fail:
            raise RuntimeError("shader compile failed")
        self._gl = object()


def test_ensure_gl_ready_on_success():
    n = _Node(fail=False)
    assert ig.ensure_gl(n) is True
    assert n._gl is not None and n.inits == 1
    assert ig.ensure_gl(n) is True          # already built -> no re-init
    assert n.inits == 1


def test_ensure_gl_disables_node_on_failure():
    n = _Node(fail=True)
    assert ig.ensure_gl(n) is False         # failure -> caller draws nothing
    assert getattr(n, '_disabled', False) is True
    assert ig.ensure_gl(n) is False         # stays disabled, does not retry
    assert n.inits == 1                     # _init_gl not called again


def test_texture_rgba_accepts_in_memory_image(monkeypatch):
    """A PIL image uploads directly -- no filesystem path, no file written."""
    calls = {}
    monkeypatch.setattr(ig, 'glGenTextures', lambda n: 77)
    monkeypatch.setattr(ig, 'glBindTexture', lambda *a: None)
    monkeypatch.setattr(ig, 'glTexImage2D',
                        lambda *a: calls.__setitem__('uploaded', a))
    monkeypatch.setattr(ig, 'glGenerateMipmap', lambda *a: None)
    monkeypatch.setattr(ig, 'glTexParameteri', lambda *a: None)
    # Image.open must not be touched when an image is passed in.
    monkeypatch.setattr(ig.Image, 'open',
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("opened a file")))

    img = Image.new("RGB", (4, 2), (10, 20, 30))
    tid = ig.texture_rgba(img, clamp=False)
    assert tid == 77
    assert 'uploaded' in calls               # the RGBA bytes reached glTexImage2D


def test_setup_instance_attribs_advances_per_instance(monkeypatch):
    """The shared divisor block: vec4 xform @0 + float scale @16, stride 20, divisor 1."""
    ptrs = []
    divs = []
    monkeypatch.setattr(ig, 'glVertexAttribPointer',
                        lambda loc, sz, typ, norm, stride, off: ptrs.append((loc, sz, stride)))
    monkeypatch.setattr(ig, 'glEnableVertexAttribArray', lambda loc: None)
    monkeypatch.setattr(ig, 'glVertexAttribDivisor', lambda loc, d: divs.append((loc, d)))

    ig.setup_instance_attribs(3, 4)
    assert (3, 4, 20) in ptrs                # xform: vec4, stride 20
    assert (4, 1, 20) in ptrs                # scale: float, stride 20
    assert divs == [(3, 1), (4, 1)]          # both advance once per instance


def test_instance_buffer_grows_only_when_capacity_exceeded(monkeypatch):
    """Grow reallocates; a same-or-smaller restream reuses the store via glBufferSubData."""
    events = []
    monkeypatch.setattr(ig, 'glGenBuffers', lambda n: 5)
    monkeypatch.setattr(ig, 'glBindBuffer', lambda *a: None)
    monkeypatch.setattr(ig, 'glBufferData',
                        lambda tgt, size, data, usage: events.append(('data', size)))
    monkeypatch.setattr(ig, 'glBufferSubData',
                        lambda tgt, off, size, data: events.append(('sub', size)))

    buf = ig.InstanceBuffer()
    assert buf.id == 5 and buf.capacity == 0
    buf.upload(np.zeros((3, 5), 'f4'))       # first fill -> allocate
    grew = buf.capacity
    buf.upload(np.zeros((2, 5), 'f4'))       # shrink -> in-place
    assert buf.count == 2 and buf.capacity == grew
    buf.upload(np.zeros((10, 5), 'f4'))      # exceed capacity -> reallocate
    assert buf.count == 10 and buf.capacity > grew
    buf.upload(np.zeros((0, 5), 'f4'))       # empty -> no GL call, nothing to draw
    assert buf.count == 0

    assert [e[0] for e in events] == ['data', 'sub', 'data']


def test_instance_buffer_delete_frees_its_store(monkeypatch):
    monkeypatch.setattr(ig, 'glGenBuffers', lambda n: 42)
    monkeypatch.setattr(ig, 'glBindBuffer', lambda *a: None)
    freed = {}
    monkeypatch.setattr(ig, 'delete_gl', lambda **k: freed.update(k))
    buf = ig.InstanceBuffer()
    buf.delete()
    assert freed == {'buffers': [42]}


def test_delete_gl_swallows_bad_handles(monkeypatch):
    """A double-free or absent GL context must not crash teardown -- every
    per-object delete is guarded, so freeing already-dead handles is a no-op."""
    def boom(*a):
        raise RuntimeError("no current GL context")
    monkeypatch.setattr(ig, 'glDeleteVertexArrays', boom)
    monkeypatch.setattr(ig, 'glDeleteBuffers', boom)
    monkeypatch.setattr(ig, 'glDeleteTextures', boom)
    monkeypatch.setattr(ig, 'glDeleteProgram', boom)
    # Must not raise despite every underlying delete throwing.
    ig.delete_gl(vaos=[1], buffers=[2], textures=[3], programs=[4])
