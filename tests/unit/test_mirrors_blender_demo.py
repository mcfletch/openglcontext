"""The mirror hall demo world: a Blender scene whose mirrors are tags.

``tools/blender/demos/mirrors.py`` builds it in Blender with the ``oglc_hook``
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
from OpenGLContext.passes import reflection
from OpenGLContext.scenegraph.reflector import WATER
from OpenGLContext.scenegraph.shape import Shape

DEMOS = Path(__file__).resolve().parents[2] / 'tools' / 'blender' / 'demos'
SHIPPED = DEMOS / 'mirrors.glb'


@pytest.fixture(scope='module')
def scene():
    return gltf.load_gltf(str(SHIPPED))


def _shapes(node, out=None):
    out = [] if out is None else out
    if isinstance(node, Shape):
        out.append(node)
    for child in getattr(node, 'children', None) or []:
        _shapes(child, out)
    return out


def _reflectors(node):
    return [shape.appearance.material.reflector for shape in _shapes(node)
            if getattr(shape.appearance.material, 'reflector', None)]


def test_the_blender_file_ships_beside_it():
    assert (DEMOS / 'mirrors.blend').stat().st_size > 0


def test_the_far_mirror_is_silvered_and_redrawn_every_other_frame(scene):
    reflector, = _reflectors(scene.getDEF('FarMirror'))
    assert (reflector.interval, reflector.priority) == (2, pytest.approx(2.0))
    assert not reflector.replace


def test_the_corridors_ten_mirrors_share_one_reflector(scene):
    found = [reflector for index in range(10)
             for reflector in _reflectors(scene.getDEF('CorridorMirror%d' % index))]
    assert len(found) == 10
    assert all(reflector is found[0] for reflector in found)
    assert found[0].scale == pytest.approx(0.35)


def test_the_floor_is_polished_stone_that_gives_way_to_the_mirrors(scene):
    reflector, = _reflectors(scene.getDEF('Floor'))
    assert reflector.priority == pytest.approx(0.5)
    material, = [shape.appearance.material for shape in _shapes(scene.getDEF('Floor'))]
    assert material.metallic == pytest.approx(0.0)


def test_the_window_shows_only_its_reflection(scene):
    reflector, = _reflectors(scene.getDEF('Window'))
    assert reflector.replace and reflector.interval == 1


def test_the_pool_is_water_and_a_mirror(scene):
    body, = scene.hook_data['water']
    assert _reflectors(scene.getDEF('PoolWater')) == [WATER]
    assert body.volume.contains((3.5, 0.1, -4.0))


def test_every_mirror_faces_into_the_room(scene):
    """Blender's planes face where they were turned, and the file keeps it."""
    from tests.unit.test_mirrors_demo import _placed
    records = _placed(scene.group)
    mirrors = [record for record in records if reflection.is_reflector(record)]
    assert len(mirrors) == 14
    middle = (0.0, 1.7, 0.0)
    for record in mirrors:
        point, normal = reflection.surface_plane(record)
        assert sum((m - p) * n for m, p, n in zip(middle, point, normal)) > 0.0


def test_it_opens_through_its_own_camera(scene):
    assert [camera['name'] for camera in scene.cameras] == ['Hall']


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


def test_the_tags_are_the_ones_the_panel_writes():
    assert _tags(SHIPPED) == {
        'Marble': {'kind': 'mirror', 'interval': 2, 'priority': 0.5},
        'Silver': {'kind': 'mirror', 'interval': 2, 'priority': 2.0},
        'CorridorGlass': {'kind': 'mirror', 'scale': 0.35},
        'Pool': {'kind': 'water', 'style': 'still', 'depth': 0.25},
        'Window': {'kind': 'mirror', 'interval': 1},
    }


@pytest.mark.skipif(shutil.which('blender') is None,
                    reason='Blender is not installed')
def test_the_shipped_file_is_what_the_script_builds(tmp_path):
    built = tmp_path / 'mirrors.glb'
    proc = subprocess.run(
        [shutil.which('blender'), '-b', '--factory-startup', '--python-exit-code',
         '1', '--python', str(DEMOS / 'mirrors.py'), '--', '--glb', str(built)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _tags(built) == _tags(SHIPPED)
    rebuilt = pygltflib.GLTF2.load(str(built))
    shipped = pygltflib.GLTF2.load(str(SHIPPED))
    assert sorted(node.name for node in rebuilt.nodes) == \
        sorted(node.name for node in shipped.nodes)
