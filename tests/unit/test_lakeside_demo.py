"""The lakeside demo world: a Blender scene whose water and fire are tags.

``tools/blender/demos/lakeside.py`` builds it in Blender with the ``oglc_hook``
panel, and the ``.glb`` and ``.blend`` it wrote are shipped beside it. These
tests load the shipped file the way ``oglc-view`` does and hold it to what the
demo says it is; where Blender is installed, they build it again and hold the
shipped file to the script.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pygltflib
import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph import water

DEMOS = Path(__file__).resolve().parents[2] / 'tools' / 'blender' / 'demos'
SHIPPED = DEMOS / 'lakeside.glb'


@pytest.fixture(scope='module')
def scene():
    return gltf.load_gltf(str(SHIPPED))


def test_the_blender_file_ships_beside_it():
    assert (DEMOS / 'lakeside.blend').stat().st_size > 0


def test_the_lake_is_water(scene):
    body, = scene.hook_data['water']
    assert body.style is water.BREEZE
    assert body.volume.contains((0.0, -1.0, 0.0))


def test_the_fires_burn(scene):
    """The brazier, the campfire and a torch either side of the jetty."""
    assert len(scene.hook_data['fire']) == 4
    assert len(scene.hook_data['smoke']) == 1
    assert len(scene.hook_data['sparks']) == 1


def test_the_campfire_is_on_the_shore(scene):
    body, = scene.hook_data['water']
    campfire = scene.getDEF('Campfire')
    assert not body.volume.contains(tuple(campfire.translation))


def test_it_opens_through_its_own_camera(scene):
    assert [camera['name'] for camera in scene.cameras] == ['Lakeside']


def test_everything_moving_is_advanced(scene):
    assert scene.advance(1.0) is True


def _tags(path):
    """Each tagged material and node, by name, with the tag it carries."""
    document = pygltflib.GLTF2.load(str(path))
    tagged = {}
    for holders in (document.materials or [], document.nodes or []):
        for holder in holders:
            block = (holder.extensions or {}).get(hooks.EXTENSION)
            if block is not None:
                tagged[holder.name] = json.loads(json.dumps(block))
    return tagged


@pytest.mark.skipif(shutil.which('blender') is None,
                    reason='Blender is not installed')
def test_the_shipped_file_is_what_the_script_builds(tmp_path):
    built = tmp_path / 'lakeside.glb'
    proc = subprocess.run(
        [shutil.which('blender'), '-b', '--factory-startup', '--python-exit-code',
         '1', '--python', str(DEMOS / 'lakeside.py'), '--', '--glb', str(built)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _tags(built) == _tags(SHIPPED)
    rebuilt = pygltflib.GLTF2.load(str(built))
    shipped = pygltflib.GLTF2.load(str(SHIPPED))
    assert sorted(node.name for node in rebuilt.nodes) == \
        sorted(node.name for node in shipped.nodes)
