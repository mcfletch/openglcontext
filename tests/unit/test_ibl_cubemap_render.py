"""GL render test: a loaded environment cubemap is reflected by metals.

With OPENGLCONTEXT_ENV_CUBEMAP pointing at a face set and full IBL pinned, a metal
sphere reflects that real environment -- visibly different (and more chromatic)
than the procedural studio env it reflects otherwise.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("pygltflib")
import numpy as np
from pygltflib import (
    GLTF2, Scene, Node, Mesh, Primitive, Attributes, Accessor, BufferView,
    Buffer, Material, PbrMetallicRoughness,
)

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))
ENV_PREFIX = os.path.join(TESTS_DIR, 'pimbackground_')


def _uv_sphere(rings=24, sectors=48):
    verts, idx = [], []
    for i in range(rings + 1):
        phi = np.pi * i / rings
        for j in range(sectors + 1):
            th = 2 * np.pi * j / sectors
            verts.append((np.sin(phi) * np.cos(th), np.cos(phi), np.sin(phi) * np.sin(th)))
    for i in range(rings):
        for j in range(sectors):
            a = i * (sectors + 1) + j
            b = a + sectors + 1
            # CCW/outward winding (front faces face out); a reversed winding here
            # hid an env-reflection Y-flip because the mesh rendered inside-out.
            idx += [a, a + 1, b, a + 1, b + 1, b]
    p = np.array(verts, '<f4')
    return p, p.copy(), np.array(idx, '<u4')


def _mirror_glb():
    pos, nrm, idx = _uv_sphere()
    blob, spans = b"", []
    for arr in (pos, nrm, idx):
        raw = np.ascontiguousarray(arr).tobytes()
        blob += b"\x00" * ((-len(blob)) % 4)
        spans.append((len(blob), len(raw)))
        blob += raw
    views = [BufferView(buffer=0, byteOffset=o, byteLength=l) for o, l in spans]
    acc = [
        Accessor(bufferView=0, componentType=5126, count=len(pos), type='VEC3',
                 min=pos.min(0).tolist(), max=pos.max(0).tolist()),
        Accessor(bufferView=1, componentType=5126, count=len(nrm), type='VEC3'),
        Accessor(bufferView=2, componentType=5125, count=len(idx), type='SCALAR'),
    ]
    g = GLTF2()
    g.scene = 0
    g.scenes = [Scene(nodes=[0])]
    g.nodes = [Node(mesh=0)]
    g.meshes = [Mesh(primitives=[Primitive(
        attributes=Attributes(POSITION=0, NORMAL=1), indices=2, material=0)])]
    g.materials = [Material(pbrMetallicRoughness=PbrMetallicRoughness(
        baseColorFactor=[1, 1, 1, 1], metallicFactor=1.0, roughnessFactor=0.05))]
    g.accessors = acc
    g.bufferViews = views
    g.buffers = [Buffer(byteLength=len(blob))]
    g.set_binary_blob(blob)
    return b"".join(g.save_to_bytes())


def _capture(glb, out, env_cubemap, background='none'):
    env = dict(os.environ, OPENGLCONTEXT_IBL='full')
    if env_cubemap:
        env['OPENGLCONTEXT_ENV_CUBEMAP'] = ENV_PREFIX
    else:
        env.pop('OPENGLCONTEXT_ENV_CUBEMAP', None)
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'on', '--ibl-intensity', '1.2', '--background', background,
            '--capture', out, '--frames', '8', '--capture-delay', '0.3',
            '--size', '200x200']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                   timeout=180, capture_output=True, text=True,
                   cwd=TESTS_DIR + '/..', env=env)


def _obj(arr):
    return arr[arr.astype(int).sum(2) > 30]


def test_env_cubemap_is_reflected(tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image
    glb = tmp_path / "mirror.glb"
    glb.write_bytes(_mirror_glb())
    frames = {}
    for tag, use_env in (('proc', False), ('env', True)):
        out = str(tmp_path / (tag + ".png"))
        try:
            _capture(str(glb), out, use_env)
        except subprocess.TimeoutExpired:
            pytest.skip("OpenGL context unavailable / capture timed out")
        if not os.path.exists(out):
            pytest.skip("OpenGL context unavailable for capture")
        frames[tag] = np.asarray(Image.open(out).convert("RGB"))
    proc, env = frames['proc'], frames['env']
    if not _obj(proc).size or not _obj(env).size:
        pytest.skip("sphere not visible in capture")
    diff = float(np.abs(proc.astype(int) - env.astype(int)).mean())
    assert diff > 5.0, ("the loaded environment cubemap should change the metal's "
                        "reflection (mean diff %.2f)" % diff)
    # the garden env is greener than the neutral procedural studio env
    def green_bias(a):
        o = _obj(a).astype(float)
        return float(o[:, 1].mean() - 0.5 * (o[:, 0].mean() + o[:, 2].mean()))
    assert green_bias(env) > green_bias(proc), "env reflection should carry its hue"


def test_env_cubemap_renders_as_skybox(tmp_path):
    """With the env cubemap set and no explicit background, the cube renders as the
    skybox (the frame corners show the environment, not black)."""
    pytest.importorskip("PIL")
    from PIL import Image
    glb = tmp_path / "mirror.glb"
    glb.write_bytes(_mirror_glb())
    out = str(tmp_path / "sky.png")
    try:
        _capture(str(glb), out, env_cubemap=True, background='cube')  # show the cubemap skybox
    except subprocess.TimeoutExpired:
        pytest.skip("OpenGL context unavailable / capture timed out")
    if not os.path.exists(out):
        pytest.skip("OpenGL context unavailable for capture")
    arr = np.asarray(Image.open(out).convert("RGB")).astype(int)
    # sample the four corners (background, away from the centred sphere)
    h, w, _ = arr.shape
    corners = np.concatenate([arr[:12, :12].reshape(-1, 3), arr[:12, -12:].reshape(-1, 3),
                              arr[-12:, :12].reshape(-1, 3), arr[-12:, -12:].reshape(-1, 3)])
    assert corners.max() > 40, "skybox background is black (cubemap not drawn)"
    g = corners[:, 1].mean() - 0.5 * (corners[:, 0].mean() + corners[:, 2].mean())
    assert g > 3.0, "skybox should show the green garden environment"


def _write_synth_env(prefix):
    """Six solid, distinct faces so a mirror sphere's reflection is unambiguous:
    UP=red, DN=blue, RT(+X)=green, LF(-X)=yellow, FR(+Z)=cyan, BK(-Z)=magenta."""
    from PIL import Image
    faces = {'RT': (20, 200, 20), 'LF': (220, 220, 20), 'UP': (230, 20, 20),
             'DN': (20, 20, 230), 'FR': (20, 200, 200), 'BK': (220, 20, 220)}
    for suffix, col in faces.items():
        Image.new('RGB', (128, 128), col).save(prefix + suffix + '.jpg', quality=95)


def _capture_env(glb, out, env_prefix, background='cube'):
    env = dict(os.environ, OPENGLCONTEXT_IBL='full',
               OPENGLCONTEXT_ENV_CUBEMAP=env_prefix)
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'on', '--ibl-intensity', '1.2', '--background', background,
            '--capture', out, '--frames', '6', '--capture-delay', '0.3',
            '--size', '256x256']
    subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                   timeout=180, capture_output=True, text=True,
                   cwd=TESTS_DIR + '/..', env=env)


def test_mirror_sphere_reflects_env_right_way_up(tmp_path):
    """A near-mirror sphere must reflect the world un-rotated: the UP face (red)
    on the sphere's top, DOWN (blue) on the bottom, and RT/+X (green) on the right.

    Solid-colour faces make this unambiguous where a photographic env's top/bottom
    brightness heuristic could not: an earlier flipY inverted the reflection while
    still passing a brightness check.
    """
    pytest.importorskip("PIL")
    from PIL import Image
    prefix = str(tmp_path / 'synenv_')
    _write_synth_env(prefix)
    glb = tmp_path / "mirror.glb"
    glb.write_bytes(_mirror_glb())
    out = str(tmp_path / "syn.png")
    try:
        _capture_env(str(glb), out, prefix, background='cube')
    except subprocess.TimeoutExpired:
        pytest.skip("OpenGL context unavailable / capture timed out")
    if not os.path.exists(out):
        pytest.skip("OpenGL context unavailable for capture")
    arr = np.asarray(Image.open(out).convert("RGB")).astype(int)
    H, W, _ = arr.shape
    # background is the cyan FR face; the sphere is everything else, centred.
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    isbg = (np.abs(r - 20) < 60) & (g > 150) & (b > 150)
    obj = ~isbg
    ys, xs = np.where(obj)
    if len(ys) < 500:
        pytest.skip("sphere not visible in capture")
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0, x1 - x0

    def band_med(mask):
        px = arr[mask & obj]
        return np.median(px, 0) if len(px) else np.array([0, 0, 0])

    rows = np.arange(H)[:, None]
    cols_ = np.arange(W)[None, :]
    top = band_med(rows < y0 + 0.28 * h)
    bot = band_med(rows > y1 - 0.28 * h)
    right = band_med((cols_ > x1 - 0.28 * w) & (rows > y0 + 0.3 * h) & (rows < y1 - 0.3 * h))

    # top must read RED (UP face): red channel dominant, not blue.
    assert top[0] > top[2] + 40, ("sphere top should reflect the UP face (red), got "
                                  "rgb=%s -- env reflection is upside down" % top.tolist())
    # bottom must read BLUE (DOWN face).
    assert bot[2] > bot[0] + 40, ("sphere bottom should reflect the DOWN face (blue), got "
                                  "rgb=%s" % bot.tolist())
    # right must read GREEN (RT/+X face): reflection not mirror-reversed horizontally.
    assert right[1] > right[0] + 30 and right[1] > right[2] + 30, (
        "sphere right side should reflect the RT/+X face (green), got rgb=%s" % right.tolist())


def test_env_reflection_is_not_upside_down(tmp_path):
    """The reflected environment must match the world: the bright sky reflects on
    the TOP of a mirror sphere and the dark/green ground on the bottom (a Y-flip
    bug had them swapped)."""
    pytest.importorskip("PIL")
    from PIL import Image
    glb = tmp_path / "mirror.glb"
    glb.write_bytes(_mirror_glb())
    out = str(tmp_path / "m.png")
    try:
        _capture(str(glb), out, env_cubemap=True, background='none')
    except subprocess.TimeoutExpired:
        pytest.skip("OpenGL context unavailable / capture timed out")
    if not os.path.exists(out):
        pytest.skip("OpenGL context unavailable for capture")
    arr = np.asarray(Image.open(out).convert("RGB")).astype(float)
    lit = arr.sum(2) > 40
    ys, xs = np.where(lit)
    if len(ys) < 200:
        pytest.skip("sphere not visible")
    cy = ys.mean()
    upper = ys < cy
    top = arr[ys[upper], xs[upper]]         # reflections on the upper hemisphere
    bot = arr[ys[~upper], xs[~upper]]
    # UP face of the garden env is bright/hazy sky; DN is dark ground -> the top of
    # the sphere (reflecting up) must be brighter than the bottom.
    assert top.mean() > bot.mean() + 8.0, (
        "sky should reflect on top, ground on bottom (top=%.1f bot=%.1f)"
        % (top.mean(), bot.mean()))
