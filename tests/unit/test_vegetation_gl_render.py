"""Real-GL smoke tests for the instanced vegetation nodes.

These nodes are streamed every frame by the forest demo but are otherwise only
exercised through it, so this drives their render()/dispose() against a real
core-profile context to cover: the compile-failure disable guard, composition with
the pass's CPU cull memo and bound program (so they need no glGet snapshot of live
GL state), in-memory clump textures, and resource teardown.
"""
import types

import numpy as np
import pytest

glfw = pytest.importorskip("glfw")
from OpenGL.GL import *  # noqa: E402
from PIL import Image  # noqa: E402

from OpenGLContext.scenegraph.vegetation.billboards import InstancedBillboards
from OpenGLContext.scenegraph.vegetation.clumps import InstancedClumps
from OpenGLContext.scenegraph.vegetation.nearmesh import InstancedMeshLOD
from OpenGLContext.scenegraph.vegetation import LOD_NEAR, LOD_FAR


def _uniformf(prog, name):
    """Read back a single float uniform's current value from ``prog``."""
    loc = glGetUniformLocation(prog, name)
    assert loc != -1, name
    out = np.zeros(1, 'f4')
    glGetUniformfv(prog, loc, out)
    return float(out[0])


def _species_npz(tmp_path):
    """Minimal one-triangle species (opaque + foliage parts) for InstancedMeshLOD."""
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 2, 0]], 'f4')
    N = np.tile(np.array([0, 0, 1], 'f4'), (3, 1))
    U = np.array([[0, 0], [1, 0], [0, 1]], 'f4')
    I = np.array([0, 1, 2], np.uint32)
    npz = tmp_path / "tree.npz"
    np.savez(str(npz), oP=P, oN=N, oU=U, oI=I, bP=P, bN=N, bU=U, bI=I)
    otex = tmp_path / "bark.png"; Image.new("RGBA", (4, 4), (90, 60, 40, 255)).save(otex)
    btex = tmp_path / "leaf.png"; Image.new("RGBA", (4, 4), (40, 120, 40, 255)).save(btex)
    return dict(npz=str(npz), o_keys=("oP", "oN", "oU", "oI"), o_tex=str(otex),
                b_keys=("bP", "bN", "bU", "bI"), b_tex=str(btex))


@pytest.fixture
def gl():
    if not glfw.init():
        pytest.skip("glfw init failed (no GL)")
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, True)
    win = glfw.create_window(64, 64, "veg", None, None)
    if not win:
        glfw.terminate()
        pytest.skip("no core-profile GL context available")
    glfw.make_context_current(win)
    try:
        yield win
    finally:
        glfw.destroy_window(win)
        glfw.terminate()


def _mode():
    return types.SimpleNamespace(
        matrix=np.eye(4, dtype='f4'), projection=np.eye(4, dtype='f4'),
        shadow_pass=False, visible=True)


def _tex_png(tmp_path):
    p = tmp_path / "blade.png"
    Image.new("RGBA", (4, 4), (60, 120, 40, 255)).save(p)
    return str(p)


def test_billboards_render_composes_with_cull_memo_and_disposes(gl, tmp_path):
    pos = np.array([[0, 0, 0], [1, 0, 1], [-1, 0, 2]], 'f4')
    node = InstancedBillboards(pos, np.zeros(3, 'f4'), np.ones(3, 'f4'), _tex_png(tmp_path))
    mode = _mode()

    # Incoming state the node does not depend on: it composes with the pass's CPU
    # state memo, not with whatever GL happened to be set before it.
    glEnable(GL_CULL_FACE); glCullFace(GL_FRONT); glFrontFace(GL_CW)
    glDepthMask(GL_FALSE); glEnable(GL_BLEND)
    assert glGetError() == GL_NO_ERROR

    node.render(mode)
    assert glGetError() == GL_NO_ERROR

    # Foliage draws double-sided: the node disables cull and records that on the
    # pass's cull memo, so the pass re-issues its own winding on its next mesh
    # (and resets to the GL default once per frame) -- no glGet snapshot/restore.
    assert not glIsEnabled(GL_CULL_FACE)
    assert mode._cull_enabled is False
    assert int(mode._cull_front_face) == GL_CCW
    # State it never touches is left exactly as it found it.
    mask = glGetBooleanv(GL_DEPTH_WRITEMASK)
    assert not bool(mask[0] if hasattr(mask, '__len__') else mask)
    assert glIsEnabled(GL_BLEND)

    node.dispose()
    assert node._gl is None
    node.dispose()   # idempotent


def test_billboards_disabled_on_init_failure_no_crash(gl, tmp_path, monkeypatch):
    node = InstancedBillboards(np.zeros((1, 3), 'f4'), np.zeros(1, 'f4'),
                               np.ones(1, 'f4'), _tex_png(tmp_path))
    # billboards binds load_program into its own namespace at import.
    monkeypatch.setattr("OpenGLContext.scenegraph.vegetation.billboards.load_program",
                        lambda *a: (_ for _ in ()).throw(RuntimeError("no shader")))
    assert node.render(_mode()) == 1        # a compile failure must not raise
    assert node._disabled is True
    assert node.render(_mode()) == 1        # stays a no-op


def test_clumps_render_with_in_memory_texture_and_dispose(gl):
    # One triangle, textured from a decoded PIL image (no file on disk).
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f4')
    N = np.tile(np.array([0, 0, 1], 'f4'), (3, 1))
    UV = np.array([[0, 0], [1, 0], [0, 1]], 'f4')
    idx = np.array([0, 1, 2], np.uint32)
    img = Image.new("RGBA", (4, 4), (30, 90, 30, 255))
    node = InstancedClumps(P, N, UV, idx, img)
    node.update_instances(np.array([[0, 0, 0]], 'f4'), np.zeros(1, 'f4'), np.ones(1, 'f4'))

    node.render(_mode())
    assert glGetError() == GL_NO_ERROR

    node.dispose()
    assert node._gl is None
    node.dispose()                                # idempotent: no GL objects left to free


def test_far_clump_renders_with_inner_cut_window(gl):
    """A coarse far-clump node carries the inner fade-in window (uCutStart/uCutEnd)
    that dithers it IN at the geometry-LOD boundary; it compiles and draws clean."""
    P = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'f4')
    N = np.tile(np.array([0, 0, 1], 'f4'), (3, 1))
    UV = np.array([[0, 0], [1, 0], [0, 1]], 'f4')
    idx = np.array([0, 1, 2], np.uint32)
    img = Image.new("RGBA", (4, 4), (30, 90, 30, 255))
    node = InstancedClumps(P, N, UV, idx, img,
                           cut_start=8.0, cut_end=13.0, fade_start=24.0, fade_end=30.0)
    node.update_instances(np.array([[0, 0, 0]], 'f4'), np.zeros(1, 'f4'), np.ones(1, 'f4'))
    node.render(_mode())
    assert glGetError() == GL_NO_ERROR
    assert node.U["uCutStart"] != -1 and node.U["uCutEnd"] != -1   # uniforms are live
    assert (node.cut_start, node.cut_end) == (8.0, 13.0)
    node.dispose()


def test_meshlod_skips_species_with_no_near_instances(gl, tmp_path):
    """A species whose near-set is empty is skipped in the draw loop while another
    species still draws -- the per-species empty-buffer guard."""
    two = [_species_npz(tmp_path), _species_npz(tmp_path)]
    pos = np.array([[0, 0, 0], [0, 0, 500]], 'f4')   # species 1 tree is far away
    node = InstancedMeshLOD(pos, np.zeros(2, 'f4'), np.ones(2, 'f4'), two,
                            species_id=np.array([0, 1]))
    node.update(0.0, 0.0, radius=42.0)               # only the species-0 tree is near
    assert node.render(_mode()) == 1
    assert glGetError() == GL_NO_ERROR
    assert node._sp[0]["buf"].count == 1
    assert node._sp[1]["buf"].count == 0             # empty species -> `continue`
    node.dispose()


def test_lod_window_shared_by_impostor_and_near_mesh(gl, tmp_path):
    """One LOD constant pair drives both shaders so the handoff can't drift apart."""
    imp = InstancedBillboards(np.zeros((1, 3), 'f4'), np.zeros(1, 'f4'), np.ones(1, 'f4'),
                              _tex_png(tmp_path), near_fade=True)
    imp.render(_mode())
    assert glGetError() == GL_NO_ERROR
    assert _uniformf(imp._prog, "uLodStart") == pytest.approx(LOD_NEAR)
    assert _uniformf(imp._prog, "uLodEnd") == pytest.approx(LOD_FAR)

    mesh = InstancedMeshLOD(np.array([[0, 0, 0]], 'f4'), np.zeros(1, 'f4'),
                            np.ones(1, 'f4'), [_species_npz(tmp_path)])
    mesh.update(0.0, 0.0, radius=100.0)
    mesh.render(_mode())
    assert glGetError() == GL_NO_ERROR
    # identical window on both sides -> complementary dither, no seam/double-draw
    assert _uniformf(mesh._prog, "uLodStart") == _uniformf(imp._prog, "uLodStart")
    assert _uniformf(mesh._prog, "uLodEnd") == _uniformf(imp._prog, "uLodEnd")

    imp.dispose(); mesh.dispose()


def test_instance_buffer_survives_shrink_then_grow(gl, tmp_path):
    """Restreaming does not reallocate on a shrink and stays correct across a grow."""
    node = InstancedBillboards(np.zeros((5, 3), 'f4'), np.zeros(5, 'f4'),
                               np.ones(5, 'f4'), _tex_png(tmp_path))
    node.render(_mode())
    assert node._ibuf.count == 5
    cap5 = node._ibuf.capacity
    assert cap5 > 0

    node.update_instances(np.zeros((2, 3), 'f4'), np.zeros(2, 'f4'), np.ones(2, 'f4'))
    node.render(_mode())
    assert node._ibuf.count == 2
    assert node._ibuf.capacity == cap5            # shrink reuses the store, no realloc

    node.update_instances(np.zeros((12, 3), 'f4'), np.zeros(12, 'f4'), np.ones(12, 'f4'))
    node.render(_mode())
    assert node._ibuf.count == 12
    assert node._ibuf.capacity > cap5             # grow reallocates
    assert glGetError() == GL_NO_ERROR

    node.update_instances(np.zeros((0, 3), 'f4'), np.zeros(0, 'f4'), np.zeros(0, 'f4'))
    assert node.render(_mode()) == 1              # count==0 draws nothing, no crash
    assert node._ibuf.count == 0
    assert glGetError() == GL_NO_ERROR
    node.dispose()


def test_meshlod_render_and_dispose_frees_everything(gl, tmp_path):
    node = InstancedMeshLOD(np.array([[0, 0, 0]], 'f4'), np.zeros(1, 'f4'),
                            np.ones(1, 'f4'), [_species_npz(tmp_path)])
    node.update(0.0, 0.0, radius=100.0)
    node.render(_mode())
    assert glGetError() == GL_NO_ERROR
    assert node._sp[0]["buf"].count == 1

    node.dispose()
    assert node._gl is None
    assert node._vaos == [] and node._buffers == [] and node._sp == []
    node.dispose()                                # idempotent


def test_splat_terrain_render_restores_state_and_disposes(gl, tmp_path):
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField
    from OpenGLContext.scenegraph.terrain.splat import SplatTerrain

    tex = tmp_path / "layer.png"
    Image.new("RGBA", (8, 8), (120, 110, 90, 255)).save(tex)
    ctl = tmp_path / "control.png"
    Image.new("RGBA", (8, 8), (255, 0, 0, 0)).save(ctl)

    grid = (np.sin(np.linspace(0, 3, 8))[:, None] * np.ones((8, 8))).astype('f8') * 0.5 + 0.5
    hf = HeightField(grid, 100.0, 10.0)
    node = SplatTerrain(hf, ["floor"], str(ctl),
                        material_fn=lambda name, res: {"color": str(tex)})

    glEnable(GL_BLEND); glDepthMask(GL_FALSE)
    node.render(_mode())
    assert glGetError() == GL_NO_ERROR
    # The terrain draws with cull on + depth write on, then restores the entry state.
    assert glIsEnabled(GL_BLEND)
    mask = glGetBooleanv(GL_DEPTH_WRITEMASK)
    assert not bool(mask[0] if hasattr(mask, '__len__') else mask)

    node.dispose()
    assert node._gl is None
