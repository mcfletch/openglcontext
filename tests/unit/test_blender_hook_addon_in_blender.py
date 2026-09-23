"""The ``oglc_hook`` add-on, run inside Blender.

``test_blender_hook_addon.py`` holds the rules the add-on follows, as ordinary
code. This runs the add-on where artists run it: Blender, started without a
window, enables it from this tree, draws its panels into a layout that records
what they asked for, builds a scene with the panels' properties and exports it
with Blender's own glTF exporter. The file that comes out is loaded by the
engine, which is the whole claim.

Blender is an optional tool here; a machine without ``blender`` on its path
skips these.
"""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from OpenGLContext.loaders import gltf
from OpenGLContext.scenegraph import particles

ADDONS = Path(__file__).resolve().parents[2] / 'tools' / 'blender'
BLENDER = shutil.which('blender')

pytestmark = pytest.mark.skipif(BLENDER is None, reason='Blender is not installed')

SCRIPT = r'''
import json, sys
import addon_utils, bpy

addons, out, report = sys.argv[sys.argv.index('--') + 1:]
sys.path.insert(0, addons)
addon = addon_utils.enable('oglc_hook', default_set=True)
if addon is None:
    sys.exit('the add-on did not enable')


class Layout:
    """Records what a panel draws, since there is no window to draw it in."""

    def __init__(self, drawn):
        self.drawn = drawn
        self.use_property_split = False
        self.enabled = True
        self.alert = False

    def prop(self, owner, name):
        self.drawn.append(('prop', name))

    def label(self, text='', icon='NONE'):
        self.drawn.append(('alert' if self.alert else 'label', text))

    def column(self):
        return Layout(self.drawn)

    row = column


def drawn(settings, on):
    record = []
    addon._draw(Layout(record), settings, on)
    return record


for thing in list(bpy.data.objects):
    bpy.data.objects.remove(thing)

bpy.ops.mesh.primitive_plane_add(size=10)
lake = bpy.context.object
lake.name = 'Lake'
material = bpy.data.materials.new('Water')
lake.data.materials.append(material)
material.oglc_hook.enabled = True
material.oglc_hook.style = 'choppy'
material.oglc_hook.depth = 3.0

bpy.ops.object.empty_add(location=(3.0, 0.0, 1.0))
torch = bpy.context.object
torch.name = 'Torch'
torch.oglc_hook.enabled = True
torch.oglc_hook.kind = 'fire'
torch.oglc_hook.scale = 2.0

bpy.ops.object.empty_add(location=(-3.0, 0.0, 0.0))
chimney = bpy.context.object
chimney.name = 'Chimney'
chimney.oglc_hook.enabled = True
chimney.oglc_hook.kind = 'smoke'
chimney.oglc_hook.density = 0.5

wrong = bpy.data.materials.new('Burning').oglc_hook
wrong.enabled = True
wrong.kind = 'fire'

result = {
    'fire on an object': drawn(torch.oglc_hook, 'object'),
    'water on a material': drawn(material.oglc_hook, 'material'),
    'fire on a material': drawn(wrong, 'material'),
    'suggested for f': addon._kind_search(torch.oglc_hook, bpy.context, 'f'),
}
bpy.ops.export_scene.gltf(filepath=out, export_format='GLB')
with open(report, 'w') as written:
    json.dump(result, written)
'''


@pytest.fixture(scope='module')
def exported(tmp_path_factory):
    """The report of what the panels drew, and the file Blender wrote."""
    where = tmp_path_factory.mktemp('blender')
    script = where / 'drive.py'
    script.write_text(SCRIPT, encoding='utf-8')
    glb, report = where / 'scene.glb', where / 'report.json'
    proc = subprocess.run(
        [BLENDER, '-b', '--factory-startup', '--python-exit-code', '1',
         '--python', str(script), '--', str(ADDONS), str(glb), str(report)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0 and report.exists(), proc.stdout + proc.stderr
    return json.loads(report.read_text(encoding='utf-8')), glb


def _props(record):
    return [name for kind, name in record if kind == 'prop']


# --- the panels ---------------------------------------------------------------

def test_an_effect_panel_offers_the_effect_fields(exported):
    drawn = _props(exported[0]['fire on an object'])
    assert 'scale' in drawn and 'density' in drawn
    assert 'style' not in drawn


def test_a_water_panel_offers_the_water_fields(exported):
    drawn = _props(exported[0]['water on a material'])
    assert {'style', 'material', 'medium', 'depth'} <= set(drawn)
    assert 'scale' not in drawn


def test_the_panel_says_what_the_file_will_carry(exported):
    labels = [text for kind, text in exported[0]['fire on an object']
              if kind == 'label']
    assert any('"kind": "fire"' in text and '"scale": 2.0' in text
               for text in labels)


def test_a_flame_on_a_material_is_drawn_as_a_warning(exported):
    alerts = [text for kind, text in exported[0]['fire on a material']
              if kind == 'alert']
    assert any('object' in text for text in alerts)


def test_the_kind_field_suggests_the_engines_kinds(exported):
    assert exported[0]['suggested for f'] == ['fire']


# --- the file the exporter wrote ----------------------------------------------

def test_the_exported_lake_loads_as_water(exported):
    scene = gltf.load_gltf(str(exported[1]))
    body, = scene.hook_data['water']
    assert body.style.name == 'choppy'
    assert body.volume.maximum[1] - body.volume.minimum[1] == pytest.approx(3.0)


def test_the_exported_torch_loads_burning_where_it_was_put(exported):
    scene = gltf.load_gltf(str(exported[1]))
    flame, = scene.hook_data['fire']
    assert flame.size == pytest.approx(2.0 * particles.PRESETS['fire']['size'])
    # Blender's Z-up (3, 0, 1) is glTF's Y-up (3, 1, 0).
    assert tuple(scene.getDEF('Torch').translation) == pytest.approx((3.0, 1.0, 0.0))


def test_the_exported_chimney_loads_smoking(exported):
    scene = gltf.load_gltf(str(exported[1]))
    smoke, = scene.hook_data['smoke']
    assert smoke.rate == pytest.approx(0.5 * particles.PRESETS['smoke']['rate'])
