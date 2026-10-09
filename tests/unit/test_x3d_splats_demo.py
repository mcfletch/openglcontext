"""The GaussianSplats showcase `oglc-x3d-splats` opens

`x3d_splats.x3d` is written with its maps and the Inlined hedge, read by the
engine's loader and drawn: the vase is a GaussianSplats node in the document
whose harmonics carry brass's sheen, the hedge a KHR_gaussian_splatting glTF.
"""
import os

import numpy as np
import pytest

from OpenGLContext.bin import x3d_splats
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph import splatmath
from OpenGLContext.testing.glcontext import profile_unavailable


@pytest.fixture(scope='module')
def directory(tmp_path_factory):
    return str(tmp_path_factory.mktemp('x3d-splats'))


def test_the_document_and_its_files_are_written(directory):
    path = x3d_splats.prepare(directory)
    assert os.path.basename(path) == 'x3d_splats.x3d'
    for name in ('hedge.glb', 'marble_base.png', 'marble_normal.png', 'sandstone_base.png'):
        assert os.path.exists(os.path.join(directory, name)), name


def test_brass_is_brass_coloured_and_changes_with_the_view():
    directions = splatmath.sphere_directions(64)
    seen = x3d_splats.brass(directions, np.array([(0.0, 0.0, 1.0)]))
    assert seen.shape == (1, 64, 3)
    assert (seen >= 0.0).all() and (seen <= 1.0).all()
    assert seen[0, :, 0].mean() > seen[0, :, 2].mean() + 0.1
    assert np.ptp(seen[0].sum(axis=1)) > 0.3


def test_the_vase_lies_on_its_profile_and_faces_out():
    splats = x3d_splats.vase()
    positions = splats['positions']
    radius = np.hypot(positions[:, 0], positions[:, 2])
    profile = np.asarray(x3d_splats.PROFILE)
    assert len(positions) > 2000
    assert (radius <= profile[:, 0].max() + 1e-9).all()
    assert (positions[:, 1] >= 0.0).all() and (positions[:, 1] <= profile[-1, 1]).all()
    across = splatmath.rotations(splats['rotations']) @ np.array((0.0, 0.0, 1.0))
    sideways = positions[:, 1] > 0.1
    outward = np.sum(across[sideways][:, [0, 2]] * positions[sideways][:, [0, 2]], axis=1)
    assert (outward > 0.0).all()
    assert len(splats['harmonics']) == (x3d_splats.HARMONIC_DEGREE + 1) ** 2


def test_the_hedge_fills_its_block():
    splats = x3d_splats.hedge(500)
    half = np.asarray(x3d_splats.HEDGE_SIZE) / 2.0
    centred = splats['positions'] - (0.0, half[1], 0.0)
    assert len(centred) == 500
    assert (np.abs(centred) <= half + 1e-9).all()
    green = splatmath.colours(np.asarray(splats['harmonics'])[0][:, None, :], np.zeros((500, 3)))
    assert (green[:, 1] > green[:, 0]).mean() > 0.95


def test_the_keys_answer(directory):
    showcase = x3d_splats.Showcase(directory)
    assert background.wait_for_idle(20.0)
    assert showcase.vase.splats().degree == 3
    assert showcase.press('d') == "the vase's harmonics to degree 0"
    assert showcase.vase.splats().degree == 0
    assert showcase.press('d') == "the vase's harmonics to degree 3"
    assert showcase.vase.splats().degree == 3
    sets = showcase.splat_sets()
    assert len(sets) == 2
    assert showcase.press('s') == 'the splats cast no shadows'
    assert not any(node.castShadow for node in sets)
    assert showcase.press('s') == 'the splats cast shadows'
    assert all(node.castShadow for node in sets)
    assert showcase.press('g').startswith('wrote written-vase.glb')
    from OpenGLContext.loaders import gltf  # noqa: PLC0415 kept with its use
    written = gltf.load_gltf(os.path.join(directory, 'written-vase.glb'))
    assert written is not None
    assert showcase.press('w').startswith('wrote written.x3d')
    assert showcase.press('?') == ''


def test_the_terrace_is_drawn(directory):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    showcase = x3d_splats.Showcase(directory)
    with scene_context(showcase.scene, size=(320, 180), renderer='pbr') as context:
        for _ in range(3):
            drawn_image(context)
        assert background.wait_for_idle(20.0)
        for _ in range(2):
            drawn_image(context)
        image = drawn_image(context).astype(int)
    vase = image[75:95, 132:152].reshape(-1, 3).mean(axis=0)
    hedge = image[95:120, 40:80].reshape(-1, 3).mean(axis=0)
    assert vase[0] > vase[2] + 30                           # brass: warm
    assert hedge[1] > hedge[0] and hedge[1] > hedge[2]      # leaves: green
