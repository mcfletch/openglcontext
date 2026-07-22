"""GL regression tests for the PBR render pass (subprocess + capture)."""
import os
import socket
import subprocess
import sys

import pytest

pytest.importorskip("PIL")
import numpy as np
from PIL import Image

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))
CAPTURE = os.path.join(TESTS_DIR, "helpers", "_pbr_capture.py")


def _have_internet(host="raw.githubusercontent.com"):
    try:
        socket.create_connection((host, 443), timeout=5).close()
        return True
    except OSError:
        return False


def _capture(out_path, mode="spheres", source=None, env=None):
    args = [sys.executable, CAPTURE, out_path, mode]
    if source:
        args.append(source)
    run_env = dict(os.environ)
    if env:
        run_env.update(env)
    try:
        subprocess.run(args, timeout=180, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env=run_env)
    except subprocess.TimeoutExpired:
        return False
    return os.path.exists(out_path)


@pytest.fixture(scope="module")
def spheres_image(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("pbr") / "spheres.png")
    if not _capture(out):
        pytest.skip("OpenGL context unavailable for PBR render test")
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def test_pbr_scene_renders(spheres_image):
    """The PBR pass renders visible geometry (not a black frame)."""
    assert (spheres_image.sum(2) > 30).mean() > 0.02


def test_metal_sphere_is_gold(spheres_image):
    """The metallic gold sphere (left) reads warm; the red sphere (right) reads red."""
    img = spheres_image
    h, w, _ = img.shape
    left = img[:, : w // 2]
    right = img[:, w // 2:]
    left_lit = left[left.sum(2) > 40]
    right_lit = right[right.sum(2) > 40]
    assert len(left_lit) > 50 and len(right_lit) > 50
    # gold: red and green both elevated; red sphere: red dominant over green
    assert left_lit[:, 1].mean() > right_lit[:, 1].mean()      # more green on the gold side
    assert right_lit[:, 0].mean() > right_lit[:, 1].mean()     # red dominates on the red side


@pytest.fixture(scope="module")
def blend_image(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("pbr") / "blend.png")
    if not _capture(out, mode="blend"):
        pytest.skip("OpenGL context unavailable for PBR blend test")
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def test_blend_panel_is_translucent(blend_image):
    """A BLEND-mode panel over a red sphere shows the sphere through it.

    The overlap region must carry both the panel's blue and the sphere's red --
    the defining evidence of alpha blending. If the panel rendered opaque the
    overlap would be pure blue; if BLEND weren't routed to the transparent pass
    the panel would z-fail against the sphere or drop out entirely.
    """
    img = blend_image
    # Panel: blue-dominant (B well above R). Sphere: red-dominant (R above B).
    panel = (img[:, :, 2] > img[:, :, 0] + 30) & (img[:, :, 2] > 90)
    sphere = (img[:, :, 0] > img[:, :, 1] + 40) & (img[:, :, 0] > 90)
    # Overlap: red from the sphere AND blue from the panel both present.
    overlap = (img[:, :, 0] > 80) & (img[:, :, 2] > 120) & (img[:, :, 1] < img[:, :, 2])

    assert panel.sum() > 500, "translucent panel not visible"
    assert sphere.sum() > 500, "opaque sphere not visible"
    assert overlap.sum() > 300, "no blended (see-through) region -- panel is opaque"
    # The blend is a mix, not either pure colour: the overlap's red sits between
    # the panel's low red and the bare sphere's high red.
    overlap_red = img[overlap][:, 0].mean()
    panel_red = img[panel & ~overlap][:, 0].mean()
    sphere_red = img[sphere & ~overlap][:, 0].mean()
    assert panel_red < overlap_red < sphere_red


def _transmission_image(tmp_path, transmission_mode):
    out = str(tmp_path / ("trans_%s.png" % transmission_mode))
    if not _capture(out, mode="transmission",
                    env={"OPENGLCONTEXT_TRANSMISSION": transmission_mode}):
        pytest.skip("OpenGL context unavailable for transmission test")
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def _left_half_red_dominant(img):
    """Count red-dominant lit pixels in the left half (where the glass panel is).

    These are the red sphere seen *through* the panel -- present only when the
    panel actually transmits the backdrop.
    """
    h, w, _ = img.shape
    left = img[:, : w // 2]
    r, g, b = left[:, :, 0], left[:, :, 1], left[:, :, 2]
    return int(((r > g + 20) & (r > b + 20) & (r > 80)).sum())


def test_transmission_full_reveals_backdrop(tmp_path):
    """In 'full' mode the glass panel refracts the opaque backdrop (red sphere)."""
    img = _transmission_image(tmp_path, "full")
    assert _left_half_red_dominant(img) > 300, "sphere not visible through the glass"


def test_transmission_off_hides_backdrop(tmp_path):
    """With transmission off the same panel is opaque and hides the sphere.

    Guards the capability switch and confirms 'full' genuinely differs from 'off'.
    """
    off = _transmission_image(tmp_path, "off")
    full = _transmission_image(tmp_path, "full")
    off_red = _left_half_red_dominant(off)
    full_red = _left_half_red_dominant(full)
    # The opaque panel shows its own (cyan) colour, not the red sphere behind it.
    h, w, _ = off.shape
    left = off[:, : w // 2]
    cyan = ((left[:, :, 1] > left[:, :, 0] + 10) &
            (left[:, :, 2] > left[:, :, 0] + 10) & (left[:, :, 1] > 80)).sum()
    assert cyan > 1000, "opaque glass panel not visible"
    assert off_red < full_red * 0.4, "backdrop leaked through an opaque panel"


@pytest.fixture(scope="module")
def teapot_image(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("pbr") / "teapot.png")
    if not _capture(out, mode="teapot", env={"OPENGLCONTEXT_LOD": "off"}):
        pytest.skip("OpenGL context unavailable for PBR teapot test")
    return np.asarray(Image.open(out).convert("RGB")).astype(int)


def test_pbr_material_on_non_gltf_teapot_renders(teapot_image):
    """A PBRMaterial on the non-glTF Teapot geometry renders under the PBR pass.

    This is the first PBR material applied to a hand-built (non-glTF) Shape: it
    proves the teapot's texcoords/tangents feed the PBR shader and that the PBR
    pass draws non-instanceable geometry via the Shape path (not just glTF meshes).
    """
    assert (teapot_image.sum(2) > 30).mean() > 0.03


def test_pbr_teapot_reads_as_celadon(teapot_image):
    """The glaze base-color texture applies: lit pixels read pale green-white.

    Guards that the baseColor texture is sampled (a missing texture would leave
    the default white factor, and a wrong UV binding would not tint celadon).
    """
    img = teapot_image
    lit = img[img.sum(2) > 120]
    assert len(lit) > 500
    # Celadon glaze is slightly green: the green channel leads red and blue, and
    # red ~= blue (a neutral-green tint, not a pure/saturated green).
    assert lit[:, 1].mean() > lit[:, 0].mean() + 5   # green above red
    assert lit[:, 1].mean() > lit[:, 2].mean() + 5   # green above blue
    assert abs(lit[:, 0].mean() - lit[:, 2].mean()) < 20   # red ~= blue


@pytest.mark.skipif(not _have_internet(), reason="no internet for glTF sample download")
def test_gltf_box_renders(tmp_path):
    """A Khronos sample glTF (Box) loads from the network and renders under PBR."""
    from OpenGLContext.loaders import gltf
    out = str(tmp_path / "box.png")
    if not _capture(out, mode="gltf", source=gltf.sample_model_url("BoxTextured")):
        pytest.skip("OpenGL/network unavailable")
    img = np.asarray(Image.open(out).convert("RGB")).astype(int)
    assert (img.sum(2) > 30).mean() > 0.01


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
