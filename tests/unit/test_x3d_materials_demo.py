"""The X_ITE showcase `oglc-x3d-materials` opens

`x3d_materials.x3d` is written with its maps and atlas, read by the engine's
loader with X_ITE's nodes as the engine's classes, and drawn.
"""
import os

import numpy as np
import pytest

from OpenGLContext.bin import x3d_materials
from OpenGLContext.loaders import background
from OpenGLContext.scenegraph.instancedshape import InstancedShape
from OpenGLContext.scenegraph.texture3d import ImageTextureAtlas
from OpenGLContext.testing.glcontext import profile_unavailable


@pytest.fixture(scope='module')
def directory(tmp_path_factory):
    return str(tmp_path_factory.mktemp('x3d-materials'))


def test_the_document_and_its_files_are_written(directory):
    path = x3d_materials.prepare(directory)
    assert os.path.basename(path) == 'x3d_materials.x3d'
    for name in ('atlas.png', 'marble_base.png', 'sandstone_normal.png'):
        assert os.path.exists(os.path.join(directory, name)), name


def test_the_atlas_has_its_tiles():
    across, down, _slices = x3d_materials.ATLAS_TILES
    picture = x3d_materials.atlas(16)
    assert picture.shape == (16 * down, 16 * across, 3)
    means = [picture[:16, column * 16:(column + 1) * 16].mean() for column in range(across)]
    assert len(set(np.round(means, 1))) == across


def test_the_nodes_are_the_engines(directory):
    showcase = x3d_materials.Showcase(directory)
    found = {type(node).__name__ for node in showcase.scene.children}
    assert 'InstancedShape' in found
    assert not [problem for problem in showcase.scene.problems
                if 'has no implementation' in problem.message
                and any(name in problem.message for name in (
                    'Extension', 'BlendMode', 'DepthMode', 'InstancedShape', 'Atlas',
                    'Glossiness', 'FogCoordinate'))]
    pillars = showcase.scene.getDEF('Pillars')
    assert isinstance(pillars, InstancedShape) and len(pillars.instancePlacements()) == 5
    crate = [node for node in _walk(showcase.scene) if isinstance(node, ImageTextureAtlas)]
    assert crate and crate[0].numberOfSlices == x3d_materials.ATLAS_TILES[2]


def _walk(scene):
    pending = [scene]
    while pending:
        current = pending.pop()
        yield current
        for name in ('children', 'appearance', 'texture'):
            value = getattr(current, name, None)
            if isinstance(value, list):
                pending.extend(value)
            elif value:
                pending.append(value)


def test_the_keys_answer(directory):
    showcase = x3d_materials.Showcase(directory)
    assert showcase.press('r') == 'the sign is ordinary paint'
    assert showcase.sign.retroreflection == 0.0
    assert showcase.press('r') == 'the sign is retroreflective'
    assert showcase.press('x') == 'the candle does not scatter light beneath its surface'
    assert showcase.press('x') == 'the candle scatters light beneath its surface'
    assert showcase.press('f') == 'the banner is fogged by distance'
    assert showcase.press('f') == 'the banner is fogged by its depths'
    assert showcase.press('w').startswith('wrote written.x3d')
    assert showcase.press('?') == ''


def test_the_gallery_is_drawn(directory):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)
    showcase = x3d_materials.Showcase(directory)
    with scene_context(showcase.scene, size=(320, 180), renderer='pbr') as context:
        for _ in range(3):
            drawn_image(context)
        assert background.wait_for_idle(20.0)
        for _ in range(2):
            drawn_image(context)
        image = drawn_image(context).astype(int)
    red = image[100:110, 20:35].reshape(-1, 3).mean(axis=0)
    marker = image[20:30, 183:193].reshape(-1, 3).mean(axis=0)
    assert red[0] > red[1] + 40                        # the clearcoated red metal
    assert marker[0] > 150 and marker[1] > 120         # the marker over everything
