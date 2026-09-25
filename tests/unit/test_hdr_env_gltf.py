"""End-to-end: a Poly Haven CC0 HDRI drives the glTF viewer skybox + reflections.

Runs the real viewer over a mirror-metal sphere with ``--environment <hdri>``,
fetching and caching the panorama through the Resolver, and checks that the HDR
sky is drawn and that the metal reflects it (differently from the procedural env).

Network- and GL-gated: skips cleanly offline or without a usable GL context.
"""
import os
import sys

import numpy as np
import pytest

pytest.importorskip("pygltflib")

from tests.unit.viewcapture import view_frame
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.testing.network import unreachable
from tests.unit.test_ibl_cubemap_render import _mirror_glb

HDRI_URL = ('https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/1k/'
            'studio_small_03_1k.hdr')


@pytest.fixture(scope='module')
def cached_hdri():
    """Fetch the panorama once through the Resolver; skip the module if offline."""
    reason = unreachable(HDRI_URL)
    if reason:
        pytest.skip(reason)
    return fetch_to_cache(HDRI_URL)


def _mirror_glb_bytes():
    return _mirror_glb()


def _frame(glb, out, environment, background):
    env = dict(os.environ, OPENGLCONTEXT_IBL='full')
    env.pop('OPENGLCONTEXT_ENV_CUBEMAP', None)
    env.pop('OPENGLCONTEXT_ENV_HDR', None)
    args = [glb, '--no-cameras', '--no-physics', '--no-shadows', '--no-rotate',
            '--lights', 'on', '--ibl-intensity', '1.1', '--background', background,
            '--frames', '10', '--capture-delay', '0.5', '--size', '256x256']
    if environment:
        args += ['--environment', environment]
    return view_frame(args, out, env=env, timeout=240)


def _corners(a, k=16):
    return np.concatenate([a[:k, :k].reshape(-1, 3), a[:k, -k:].reshape(-1, 3),
                           a[-k:, :k].reshape(-1, 3), a[-k:, -k:].reshape(-1, 3)])


def _sphere_pixels(a):
    """Centre disc of the frame -- the sphere is auto-framed and centred."""
    H, W, _ = a.shape
    yy, xx = np.mgrid[0:H, 0:W]
    r = min(H, W) * 0.28
    mask = (yy - H / 2) ** 2 + (xx - W / 2) ** 2 < r * r
    return a[mask]


@pytest.mark.usefixtures('cached_hdri')
def test_hdri_skybox_and_reflection(tmp_path):
    glb = tmp_path / "mirror.glb"
    glb.write_bytes(_mirror_glb_bytes())

    hdr = _frame(str(glb), str(tmp_path / "hdr.png"),
                 environment=HDRI_URL, background='hdr')
    proc = _frame(str(glb), str(tmp_path / "proc.png"),
                  environment=None, background='none')

    # 1. the HDR sky is actually drawn (corners are not black).
    corners = _corners(hdr)
    assert corners.max() > 40, "HDR skybox not drawn (corners black): %s" % corners.mean(0)

    # 2. the studio has a bright white floor below and a dark ceiling above, so the
    #    lower skybox band is clearly brighter than the upper one.
    top = hdr[:24].reshape(-1, 3).mean()
    bottom = hdr[-24:].reshape(-1, 3).mean()
    assert bottom > top + 15, ("studio floor should light the lower sky brighter "
                               "than the ceiling (top=%.1f bottom=%.1f)" % (top, bottom))

    # 3. the metal reflects the HDR: its reflection differs from the procedural env,
    #    and it catches the bright softbox as a near-white specular highlight.
    hs, ps = _sphere_pixels(hdr), _sphere_pixels(proc)
    assert hs.size >= 500 and ps.size >= 500, "sphere not visible in capture"
    diff = float(np.abs(hs.mean(0) - ps.mean(0)).mean())
    assert diff > 4.0, "metal reflection unchanged by the HDR env (diff %.2f)" % diff
    bright = (hs.min(axis=1) > 180).mean()      # fraction of near-white pixels
    assert bright > 0.005, "no softbox highlight reflected on the metal (%.3f)" % bright


if __name__ == '__main__':
    sys.exit(pytest.main([__file__, '-v', '-s']))
