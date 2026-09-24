"""Build the mirror hall demo in Blender, tagged with the engine-hook panel.

A room with a polished floor, a large mirror on the far wall, a corridor of ten
small mirrors down the left wall, a pool of still water, and a round window on
the right wall that shows only what it reflects. Every mirror is authored with
the ``oglc_hook`` add-on's panel, exactly as an artist sets it by hand:

* the far mirror, the corridor and the floor are *materials* tagged
  ``mirror`` -- the material shades what they reflect, so the floor, a dark
  polished stone, reflects faintly looking down and strongly at a glance;
* the pool's material is tagged ``water``, which is a mirror as well;
* the window is an *object* tagged ``mirror``, so it shows the reflection and
  nothing of its own material.

Run it with Blender; it enables the add-on from this tree::

    blender -b --factory-startup --python tools/blender/demos/mirrors.py -- \\
        --glb tools/blender/demos/mirrors.glb \\
        --blend tools/blender/demos/mirrors.blend

and open the result in the viewer::

    oglc-view tools/blender/demos/mirrors.glb

The ``.blend`` is the same room to open in Blender, with the add-on installed,
to see how each mirror is tagged.
"""
import argparse
import math
import sys
from pathlib import Path

import addon_utils
import bpy
from mathutils import Vector

#: The room, in metres: its width across x, its length along y, its height.
WIDTH, LENGTH, HEIGHT = 16.0, 24.0, 4.4

#: What a lamp gives, in candela, against the viewer's sky of unit brightness:
#: a few lux on the floor under it.
LAMP_CANDELA = 30.0

#: Blender measures a point light in watts, and its glTF exporter writes
#: candela at this many lumens to the watt, spread over the whole sphere.
LUMENS_PER_WATT = 683.0


def arguments():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--glb', type=Path, required=True,
                        help='the glTF binary to write')
    parser.add_argument('--blend', type=Path,
                        help='the Blender file to save the room as, as well')
    after = sys.argv[sys.argv.index('--') + 1:] if '--' in sys.argv else []
    return parser.parse_args(after)


def enable_addon():
    """The ``oglc_hook`` add-on from this tree, whatever else is installed."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    if addon_utils.enable('oglc_hook', default_set=True) is None:
        raise SystemExit('the oglc_hook add-on would not enable')


def empty_scene():
    for thing in list(bpy.data.objects):
        bpy.data.objects.remove(thing)


def material(name, color, roughness, metallic=0.0):
    made = bpy.data.materials.new(name)
    made.use_nodes = True
    shader = made.node_tree.nodes['Principled BSDF']
    shader.inputs['Base Color'].default_value = (*color, 1.0)
    shader.inputs['Roughness'].default_value = roughness
    shader.inputs['Metallic'].default_value = metallic
    return made


def mirror(made, interval=None, resolution=None, priority=None):
    """Tag a material ``mirror`` with the panel, changing what is given."""
    settings = made.oglc_hook
    settings.enabled = True
    settings.kind = 'mirror'
    if interval is not None:
        settings.interval = interval
    if resolution is not None:
        settings.mirror_scale = resolution
    if priority is not None:
        settings.priority = priority
    return made


def placed(obj, name, material_=None):
    obj.name = name
    if material_ is not None:
        obj.data.materials.append(material_)
    return obj


def panel(name, size, location, rotation, material_):
    """A flat rectangle, ``size`` = (width, height), facing where it is turned."""
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=location, rotation=rotation)
    obj = placed(bpy.context.object, name, material_)
    obj.scale = (size[0], size[1], 1.0)
    return obj


def block(name, size, location, material_):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = placed(bpy.context.object, name, material_)
    obj.scale = size
    return obj


def room(stone, plaster):
    """Four walls and a ceiling, so every mirror has a room to show."""
    half_w, half_l = WIDTH / 2.0, LENGTH / 2.0
    block('WallFar', (WIDTH, 0.2, HEIGHT), (0.0, half_l + 0.1, HEIGHT / 2), stone)
    block('WallNear', (WIDTH, 0.2, HEIGHT), (0.0, -half_l - 0.1, HEIGHT / 2), stone)
    block('WallLeft', (0.2, LENGTH, HEIGHT), (-half_w - 0.1, 0.0, HEIGHT / 2), stone)
    block('WallRight', (0.2, LENGTH, HEIGHT), (half_w + 0.1, 0.0, HEIGHT / 2), stone)
    block('Ceiling', (WIDTH + 0.4, LENGTH + 0.4, 0.2), (0.0, 0.0, HEIGHT + 0.1), plaster)


def mirrors():
    """The floor, the far mirror and the corridor: materials tagged ``mirror``."""
    marble = mirror(material('Marble', (0.07, 0.07, 0.08), roughness=0.08),
                    interval=2, priority=0.5)
    panel('Floor', (WIDTH, LENGTH), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), marble)
    silver = mirror(material('Silver', (0.95, 0.95, 0.96), roughness=0.02,
                             metallic=1.0), interval=2, priority=2.0)
    panel('FarMirror', (6.0, 3.0), (0.0, LENGTH / 2 - 0.1, 2.0),
          (math.radians(90.0), 0.0, 0.0), silver)
    corridor = mirror(material('CorridorGlass', (0.9, 0.92, 0.95), roughness=0.03,
                               metallic=1.0), resolution=0.35)
    for index in range(10):
        y = -9.0 + 2.0 * index
        panel('CorridorMirror%d' % index, (1.0, 1.4), (-WIDTH / 2 + 0.1, y, 1.8),
              (0.0, math.radians(90.0), 0.0), corridor)


def window():
    """A round window that shows only its reflection: the *object* is tagged."""
    glass = material('WindowGlass', (0.6, 0.8, 0.9), roughness=0.05)
    bpy.ops.mesh.primitive_circle_add(vertices=8, radius=1.5, fill_type='TRIFAN',
                                      location=(WIDTH / 2 - 0.1, 0.0, 2.0),
                                      rotation=(0.0, math.radians(-90.0), 0.0))
    obj = placed(bpy.context.object, 'Window', glass)
    settings = obj.oglc_hook
    settings.enabled = True
    settings.kind = 'mirror'
    settings.interval = 1
    return obj


def pool(rim):
    """Still water in a stone rim: a material tagged ``water``."""
    water = material('Pool', (0.02, 0.06, 0.07), roughness=0.05)
    settings = water.oglc_hook
    settings.enabled = True
    settings.kind = 'water'
    settings.style = 'still'
    settings.depth = 0.25
    cx, cy = 3.5, 4.0
    panel('PoolWater', (4.0, 4.0), (cx, cy, 0.25), (0.0, 0.0, 0.0), water)
    block('PoolRimNear', (4.4, 0.2, 0.3), (cx, cy - 2.1, 0.15), rim)
    block('PoolRimFar', (4.4, 0.2, 0.3), (cx, cy + 2.1, 0.15), rim)
    block('PoolRimLeft', (0.2, 4.0, 0.3), (cx - 2.1, cy, 0.15), rim)
    block('PoolRimRight', (0.2, 4.0, 0.3), (cx + 2.1, cy, 0.15), rim)


def columns():
    """Four coloured columns, each with a lamp over it that lights the room."""
    colours = [(0.8, 0.2, 0.2), (0.2, 0.6, 0.9), (0.9, 0.7, 0.2), (0.3, 0.8, 0.4)]
    for index, colour in enumerate(colours):
        x, y = -4.5 + 3.0 * index, 7.0 - 5.0 * (index % 2)
        paint = material('Column%d' % index, colour, roughness=0.6)
        block('Column%d' % index, (0.6, 0.6, 3.0), (x, y, 1.5), paint)
        shade = material('Lamp%d' % index, (1.0, 0.95, 0.8), roughness=0.4)
        shade.node_tree.nodes['Principled BSDF'].inputs['Emission Color'].default_value = (
            1.0, 0.95, 0.8, 1.0)
        shade.node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value = 4.0
        block('Lamp%d' % index, (0.3, 0.3, 0.3), (x, y, 3.3), shade)
        bpy.ops.object.light_add(type='POINT', location=(x, y, 3.7))
        light = placed(bpy.context.object, 'LampLight%d' % index)
        light.data.energy = LAMP_CANDELA * 4.0 * math.pi / LUMENS_PER_WATT
        light.data.color = (1.0, 0.95, 0.85)


def camera():
    eye = Vector((0.0, -9.0, 1.7))
    bpy.ops.object.camera_add(location=eye)
    made = placed(bpy.context.object, 'Hall')
    made.rotation_euler = (Vector((0.0, 12.0, 1.7)) - eye).to_track_quat(
        '-Z', 'Y').to_euler()
    made.data.name = 'Hall'
    made.data.lens = 24.0
    bpy.context.scene.camera = made


def build():
    empty_scene()
    stone = material('Stone', (0.55, 0.5, 0.45), roughness=0.9)
    plaster = material('Plaster', (0.75, 0.73, 0.7), roughness=0.95)
    rim = material('Rim', (0.8, 0.78, 0.72), roughness=0.7)
    room(stone, plaster)
    mirrors()
    window()
    pool(rim)
    columns()
    camera()


def main():
    wanted = arguments()
    enable_addon()
    build()
    if wanted.blend is not None:
        # No numbered backups beside the file being rebuilt.
        bpy.context.preferences.filepaths.save_version = 0
        bpy.ops.wm.save_as_mainfile(filepath=str(wanted.blend.resolve()),
                                    compress=True)
    bpy.ops.export_scene.gltf(filepath=str(wanted.glb.resolve()),
                              export_format='GLB', export_cameras=True,
                              export_lights=True, export_apply=True)


main()
