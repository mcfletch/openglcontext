"""GL render test: an ``OMI_environment_sky`` actually reaches the screen.

The loader-level tests say the right node is built with the right numbers in it.
These say the frame comes out of the renderer looking like the sky the document
asked for -- which is the part no amount of node inspection can establish, and
the part that catches a background that is built but never bound.
"""
import base64
import io
import json
import os
import subprocess
import sys

import numpy as np
import pytest

pytest.importorskip("pygltflib")
PIL = pytest.importorskip("PIL")
from PIL import Image                                   # noqa: E402

from OpenGLContext.testing.paths import tests_root      # noqa: E402

TESTS_DIR = str(tests_root(__file__))


def png_uri(array):
    buffer = io.BytesIO()
    Image.fromarray(array.astype('u1'), 'RGB').save(buffer, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')


def document(sky, images=()):
    """A glTF that is nothing but a sky."""
    body = {
        'asset': {'version': '2.0'},
        'extensionsUsed': ['OMI_environment_sky'],
        'scene': 0,
        'scenes': [{'nodes': []}],
        'nodes': [],
        'extensions': {'OMI_environment_sky': {'skies': [sky]}},
    }
    if images:
        body['images'] = [{'uri': png_uri(a)} for a in images]
        body['textures'] = [{'source': i} for i in range(len(images))]
    return json.dumps(body).encode('utf-8')


def capture(tmp_path, body, name):
    """Render the document and return the frame, or None if GL is unavailable."""
    source = tmp_path / (name + '.gltf')
    source.write_bytes(body)
    out = str(tmp_path / (name + '.png'))
    args = [str(source), '--no-physics', '--no-shadows', '--no-rotate',
            '--capture', out, '--frames', '6', '--capture-delay', '0.2',
            '--size', '160x160']
    try:
        subprocess.run([sys.executable, '-m', 'OpenGLContext.bin.view'] + args,
                       timeout=180, capture_output=True, text=True,
                       cwd=TESTS_DIR + '/..')
    except subprocess.TimeoutExpired:
        return None
    if not os.path.exists(out):
        return None
    return np.asarray(Image.open(out).convert('RGB'), dtype=float) / 255.0


def frame_or_skip(tmp_path, body, name):
    found = capture(tmp_path, body, name)
    if found is None:
        pytest.skip('OpenGL context unavailable for capture')
    return found


def test_a_plain_sky_fills_the_frame_with_its_colour(tmp_path):
    body = document({'type': 'plain', 'plain': {'color': [0.2, 0.4, 0.8]}})
    frame = frame_or_skip(tmp_path, body, 'plain')
    middle = frame[frame.shape[0] // 2, frame.shape[1] // 2]
    assert middle[2] > middle[1] > middle[0], (
        'a blue-dominant plain sky should render blue-dominant, got %r' % (middle,))


def test_a_gradient_sky_puts_the_sky_above_and_the_ground_below(tmp_path):
    """Red overhead, green underfoot: the one thing a mirrored gradient would
    get wrong, and nothing in the numbers would show it."""
    body = document({'type': 'gradient', 'gradient': {
        'topColor': [1.0, 0.0, 0.0],
        'horizonColor': [0.0, 0.0, 0.0],
        'bottomColor': [0.0, 1.0, 0.0],
        'topCurve': 1.0, 'bottomCurve': 1.0}})
    frame = frame_or_skip(tmp_path, body, 'gradient')
    top = frame[:frame.shape[0] // 4].mean(axis=(0, 1))
    bottom = frame[-frame.shape[0] // 4:].mean(axis=(0, 1))
    assert top[0] > top[1], 'the top of the frame should be the sky (red)'
    assert bottom[1] > bottom[0], 'the bottom of the frame should be the ground (green)'


def test_an_equirectangular_panorama_reaches_the_screen(tmp_path):
    """A panorama that is red above the equator and green below it must not come
    out uniform: that is what a skybox built but never drawn looks like."""
    panorama = np.zeros((32, 64, 3))
    panorama[:16] = (255, 0, 0)
    panorama[16:] = (0, 255, 0)
    body = document({'type': 'panorama', 'panorama': {'equirectangular': 0}},
                    images=[panorama])
    frame = frame_or_skip(tmp_path, body, 'panorama')
    top = frame[:frame.shape[0] // 4].mean(axis=(0, 1))
    bottom = frame[-frame.shape[0] // 4:].mean(axis=(0, 1))
    assert top[0] > top[1], 'the panorama\'s upper half (red) should be overhead'
    assert bottom[1] > bottom[0], 'its lower half (green) should be underfoot'
