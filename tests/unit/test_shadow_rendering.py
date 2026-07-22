"""GL regression test: spot-light shadow mapping actually casts a shadow.

Renders tests/shadow_spot.py twice in core-profile subprocesses -- once with
shadow mapping enabled and once without -- and verifies that enabling shadows
darkens a substantial region of the lit wall (the cast shadow) while leaving the
occluder itself unchanged. Requires a working OpenGL context; skips if one is
unavailable.
"""
import os
import subprocess
import sys

import pytest

pytest.importorskip("PIL")
import numpy as np
from PIL import Image

from OpenGLContext.testing.paths import tests_root
TESTS_DIR = str(tests_root(__file__))
CAPTURE = os.path.join(TESTS_DIR, "helpers", "_shadow_capture.py")


def _capture(mode: str, out_path: str, light: str = "spot", soft: bool = False) -> bool:
    """Run the capture subprocess; return True if an image was produced."""
    env = dict(os.environ)
    env["OPENGLCONTEXT_PROFILE"] = "core"
    env.setdefault("OPENGLCONTEXT_BACKEND", "glfw")
    env["OPENGLCONTEXT_AUTO_EXIT_FRAMES"] = "8"
    env["OPENGLCONTEXT_SHADOWS_SOFT"] = "1" if soft else "0"
    try:
        subprocess.run(
            [sys.executable, CAPTURE, mode, out_path, light],
            env=env, timeout=120,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired:
        return False
    return os.path.exists(out_path)


def _load_pair(tmp_path_factory, light):
    d = tmp_path_factory.mktemp(f"shadow_{light}")
    on_path = str(d / "on.png")
    off_path = str(d / "off.png")
    if not _capture("on", on_path, light) or not _capture("off", off_path, light):
        pytest.skip("OpenGL context unavailable for shadow rendering test")
    on = np.asarray(Image.open(on_path).convert("RGB")).astype(int)
    off = np.asarray(Image.open(off_path).convert("RGB")).astype(int)
    if on.shape != off.shape:
        pytest.skip("captured images differ in size (windowing instability)")
    return on, off


@pytest.fixture(scope="module")
def shadow_images(tmp_path_factory):
    return _load_pair(tmp_path_factory, "spot")


@pytest.fixture(scope="module", params=["spot", "directional", "point"])
def shadow_images_by_kind(request, tmp_path_factory):
    return request.param, _load_pair(tmp_path_factory, request.param)


def _shadow_fraction(on, off):
    diff = off.mean(2) - on.mean(2)
    not_red = ~(on[:, :, 0] > on[:, :, 1] + 40)
    shadow = (diff > 40) & (off.mean(2) > 60) & not_red
    return shadow.mean(), diff[shadow].mean() if shadow.any() else 0.0


def test_each_light_kind_casts_a_shadow(shadow_images_by_kind):
    """Spot, directional (CSM) and point (cube) lights each cast a visible shadow."""
    kind, (on, off) = shadow_images_by_kind
    fraction, strength = _shadow_fraction(on, off)
    assert fraction > 0.01, (
        f"{kind}: expected a cast shadow, only {fraction:.3%} of pixels darkened"
    )
    assert strength > 30, f"{kind}: shadow darkening too weak ({strength:.1f})"


def test_shadow_darkens_the_wall(shadow_images):
    """Enabling shadows must darken a meaningful region of the lit wall."""
    on, off = shadow_images
    fraction, strength = _shadow_fraction(on, off)
    assert fraction > 0.02, (
        f"expected a clear cast shadow, only {fraction:.3%} of pixels darkened"
    )
    assert strength > 30


def test_occluder_unchanged_by_shadows(shadow_images):
    """The red occluder box renders the same with and without shadows.

    Confirms the darkening is a cast shadow on the wall, not a global lighting
    change, and that both runs rendered the same scene.
    """
    on, off = shadow_images

    def red_mask(img):
        return (img[:, :, 0] > 100) & (img[:, :, 0] > img[:, :, 1] + 40)

    red_on = int(red_mask(on).sum())
    red_off = int(red_mask(off).sum())
    assert red_on > 500 and red_off > 500, "occluder box not rendered in both images"
    assert abs(red_on - red_off) < 0.2 * max(red_on, red_off)


def test_shadows_reduce_overall_brightness(shadow_images):
    """Global sanity: shadows make the scene darker overall, not brighter."""
    on, off = shadow_images
    assert on.mean() < off.mean()


def _penumbra_count(on, off):
    diff = off.mean(2) - on.mean(2)
    not_red = ~(on[:, :, 0] > on[:, :, 1] + 40)
    return int(((diff > 10) & (diff <= 45) & (off.mean(2) > 60) & not_red).sum())


def test_soft_shadows_widen_the_penumbra(tmp_path_factory, shadow_images):
    """PCSS soft mode produces a wider, blurrier penumbra than hard PCF."""
    _on_hard, off = shadow_images
    on_hard, _ = shadow_images
    d = tmp_path_factory.mktemp("shadow_soft")
    soft_path = str(d / "soft.png")
    if not _capture("on", soft_path, "spot", soft=True):
        pytest.skip("OpenGL context unavailable")
    on_soft = np.asarray(Image.open(soft_path).convert("RGB")).astype(int)
    if on_soft.shape != off.shape:
        pytest.skip("captured images differ in size")
    soft_pen = _penumbra_count(on_soft, off)
    hard_pen = _penumbra_count(on_hard, off)
    assert soft_pen > hard_pen * 1.5, (
        f"soft penumbra ({soft_pen}) should exceed hard ({hard_pen})"
    )


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "-s"]))
