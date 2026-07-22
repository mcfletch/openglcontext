"""HDRBackground node: IBL registration + async load logic (headless).

Verifies that installing a panorama registers it as the IBL probe environment,
that clearing it de-registers, that a local .hdr decodes through loadBackground,
and that the node is discoverable as a bound Background by the render pass.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.hdrbackground import HDRBackground
from OpenGLContext.passes import ibl
from vrml.vrml97 import nodetypes


@pytest.fixture(autouse=True)
def _clear_env():
    ibl.set_equirect_env(None)
    yield
    ibl.set_equirect_env(None)


def _panorama(h=16, w=32):
    env = np.zeros((h, w, 3), np.float32)
    env[:h // 2] = (4.0, 0.5, 0.5)     # bright sky
    env[h // 2:] = (0.1, 0.2, 0.1)     # dark ground
    return env


def test_construct_with_image_registers_ibl_env():
    bg = HDRBackground(image=_panorama())
    assert bg._equirect is not None
    got = ibl.get_equirect_env()
    assert got is not None and got.shape == (16, 32, 3)


def test_set_image_none_clears_ibl_env():
    bg = HDRBackground(image=_panorama())
    assert ibl.get_equirect_env() is not None
    bg.setImage(None)
    assert bg._equirect is None
    assert ibl.get_equirect_env() is None


def test_load_background_from_local_hdr(tmp_path):
    from tests.unit.test_hdr_loader import encode_new_rle
    src = _panorama(16, 32)
    p = tmp_path / "sky.hdr"
    p.write_bytes(encode_new_rle(src))
    bg = HDRBackground()
    bg.loadBackground(str(p))          # synchronous call (no thread)
    assert bg._equirect is not None
    assert bg._equirect.shape == (16, 32, 3)
    # top (sky) is brighter than bottom (ground) -> orientation preserved
    assert bg._equirect[0].mean() > bg._equirect[-1].mean()
    assert ibl.get_equirect_env() is not None


def test_bad_url_leaves_env_unregistered(tmp_path):
    bg = HDRBackground()
    bg.loadBackground(str(tmp_path / "does-not-exist.hdr"))
    assert bg._equirect is None
    assert ibl.get_equirect_env() is None


def test_is_a_background_node():
    bg = HDRBackground(image=_panorama())
    assert isinstance(bg, nodetypes.Background)
    # carries the fields the pass reads
    bg.bound = 1
    assert bg.bound
    assert hasattr(bg, 'RenderShader') and hasattr(bg, 'Render')


def test_url_field_assignment_triggers_load(tmp_path):
    """Assigning .url spawns a loader thread; joining it installs the panorama."""
    import threading
    from tests.unit.test_hdr_loader import encode_flat
    p = tmp_path / "viaurl.hdr"
    p.write_bytes(encode_flat(_panorama(8, 16)))
    bg = HDRBackground()
    bg.url = [str(p)]
    # find and join the loader thread the field spawned
    for t in threading.enumerate():
        if t.name.startswith("HDR background load"):
            t.join(timeout=10)
    assert bg._equirect is not None
    assert ibl.get_equirect_env() is not None


if __name__ == '__main__':
    import sys
    sys.exit(pytest.main([__file__, '-v']))


def test_setimage_defers_stale_render_data_for_gl_thread():
    """A superseded panorama's GL objects are queued (not deleted off-thread).

    setImage can run on the async loader thread, so it must not call glDelete;
    the previous compiled skybox is handed to _stale_render_data for the GL
    thread to free on the next render/drain (else each env change leaks it)."""
    bg = HDRBackground(image=_panorama())
    sentinel = ("tex", "vbo", "ibo", "prog", {}, "vao")
    bg._render_data = sentinel
    bg.setImage(_panorama())                 # swap to a new panorama
    assert bg._render_data is None
    assert bg._stale_render_data == [sentinel]

    # Draining frees each queued item exactly once and empties the queue.
    freed = []
    import OpenGLContext.scenegraph.hdrbackground as H
    orig = H._free_render_data
    H._free_render_data = lambda rd: freed.append(rd)
    try:
        bg._drain_stale_render_data()
    finally:
        H._free_render_data = orig
    assert freed == [sentinel]
    assert bg._stale_render_data == []


def test_setimage_none_also_defers_stale_render_data():
    bg = HDRBackground(image=_panorama())
    sentinel = ("tex", "vbo", "ibo", "prog", {}, "vao")
    bg._render_data = sentinel
    bg.setImage(None)                        # clear
    assert bg._render_data is None
    assert bg._stale_render_data == [sentinel]
