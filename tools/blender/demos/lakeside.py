"""Build the lakeside demo world in Blender, tagged with the engine-hook panel.

A basin of grass holding a lake, a jetty running out into it with a brazier at
its end and a torch either side of its foot, and a campfire on the shore. Every
effect is authored with the ``oglc_hook`` add-on's panel, exactly as an artist
sets it by hand: the lake's *material* is tagged ``water``, and the brazier,
the torches and the campfire are *empties* tagged ``fire``, ``smoke`` and
``sparks``. Nothing about water or fire is in the geometry.

Run it with Blender; it enables the add-on from this tree::

    blender -b --factory-startup --python tools/blender/demos/lakeside.py -- \\
        --glb tools/blender/demos/lakeside.glb \\
        --blend tools/blender/demos/lakeside.blend

and open the result in the viewer, where the lake moves and the fires burn::

    oglc-view tools/blender/demos/lakeside.glb

The ``.blend`` is the same world to open in Blender and look at, with the
add-on installed, to see how each thing is tagged.
"""
import argparse
import math
import sys
from pathlib import Path

import addon_utils
import bpy
from mathutils import Vector

#: Where the lake's surface stands, in metres.
WATER_LEVEL = -0.35

#: What the sun delivers, in lux, against the viewer's sky of unit brightness:
#: the key light a few times the sky, as the engine's own gallery world has it.
SUN_LUX = 5.0

#: Blender measures a sun in watts per square metre, and its glTF exporter
#: writes lux at this many lumens to the watt.
LUMENS_PER_WATT = 683.0


def _smoothstep(low, high, value):
    t = min(1.0, max(0.0, (value - low) / (high - low)))
    return t * t * (3.0 - 2.0 * t)


def height(x, y):
    """The ground: a flat-bottomed basin for the lake, hills, a gentle roll.

    The basin's sides are steep enough that the lake's swell moves the
    waterline a little rather than flooding the shore.
    """
    basin = -2.5 + 2.8 * _smoothstep(6.5, 10.5, math.hypot(x, y))
    hills = (2.5 * math.exp(-((x + 17.0) ** 2 + (y - 15.0) ** 2) / 70.0)
             + 5.0 * math.exp(-((x + 30.0) ** 2 + (y + 25.0) ** 2) / 200.0)
             + 4.0 * math.exp(-((x - 5.0) ** 2 + (y - 35.0) ** 2) / 150.0))
    roll = 0.15 * math.sin(x * 0.4) * math.cos(y * 0.3)
    return basin + hills + roll


def arguments():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--glb', type=Path, required=True,
                        help='the glTF binary to write')
    parser.add_argument('--blend', type=Path,
                        help='the Blender file to save the world as, as well')
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


def placed(obj, name, material_=None):
    obj.name = name
    if material_ is not None:
        obj.data.materials.append(material_)
    return obj


def ground(grass):
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=96, y_subdivisions=96, size=80.0)
    obj = placed(bpy.context.object, 'Ground', grass)
    for vertex in obj.data.vertices:
        vertex.co.z = height(vertex.co.x, vertex.co.y)
    obj.data.shade_smooth()
    return obj


def lake():
    """The lake: a flat grid, and a material the panel says is water.

    The grid is fine enough for the wave to have vertices to move; the
    engine moves them on the card, so the file carries a flat sheet.
    """
    water = material('Lake', (0.02, 0.06, 0.07), roughness=0.05)
    settings = water.oglc_hook
    settings.enabled = True
    settings.kind = 'water'
    settings.style = 'breeze'
    settings.depth = 2.0
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=80, y_subdivisions=80, size=22.0,
                                    location=(0.0, 0.0, WATER_LEVEL))
    return placed(bpy.context.object, 'Lake', water)


def effect(name, kind, location, scale=1.0, density=1.0):
    """An empty the panel tags with one of the engine's particle kinds."""
    bpy.ops.object.empty_add(type='PLAIN_AXES', radius=0.25, location=location)
    obj = placed(bpy.context.object, name)
    settings = obj.oglc_hook
    settings.enabled = True
    settings.kind = kind
    settings.scale = scale
    settings.density = density
    return obj


def cylinder(name, radius, depth, location, stuff, rotation=(0.0, 0.0, 0.0)):
    bpy.ops.mesh.primitive_cylinder_add(radius=radius, depth=depth, vertices=16,
                                        location=location, rotation=rotation)
    return placed(bpy.context.object, name, stuff)


def jetty(wood, metal):
    """Planks from the shore out over the water, a brazier at the far end."""
    deck = WATER_LEVEL + 0.35
    bpy.ops.mesh.primitive_cube_add(location=(-8.0, 0.0, deck))
    planks = placed(bpy.context.object, 'Jetty', wood)
    planks.scale = (3.5, 0.8, 0.07)
    for index, x in enumerate((-10.5, -8.0, -5.5)):
        for side in (-0.7, 0.7):
            cylinder('JettyPile%d%s' % (index, 'LR'[side > 0]), 0.08, 1.4,
                     (x, side, deck - 0.6), wood)
    top = deck + 0.07
    cylinder('Brazier', 0.3, 0.5, (-4.8, 0.0, top + 0.25), metal)
    effect('BrazierFire', 'fire', (-4.8, 0.0, top + 0.55), scale=0.6)
    effect('BrazierSparks', 'sparks', (-4.8, 0.0, top + 0.6), scale=1.2, density=0.6)
    for side in (-1.0, 1.0):
        x, y = -11.2, side * 1.1
        base = height(x, y)
        cylinder('TorchPost%s' % 'LR'[side > 0], 0.05, 1.7, (x, y, base + 0.85), wood)
        effect('Torch%s' % 'LR'[side > 0], 'fire', (x, y, base + 1.75), scale=0.3)


def campfire(stone, wood):
    """A ring of stones on the shore with logs in it, burning and smoking."""
    cx, cy = 12.5, -3.0
    base = height(cx, cy)
    for index in range(8):
        angle = 2.0 * math.pi * index / 8
        bpy.ops.mesh.primitive_ico_sphere_add(
            subdivisions=1, radius=1.0,
            location=(cx + 0.6 * math.cos(angle), cy + 0.6 * math.sin(angle),
                      base + 0.05))
        rock = placed(bpy.context.object, 'Stone%d' % index, stone)
        rock.scale = (0.18, 0.14, 0.12)
        rock.rotation_euler = (0.0, 0.0, angle)
    for index in range(3):
        angle = math.pi * index / 3
        cylinder('Log%d' % index, 0.07, 0.9, (cx, cy, base + 0.12), wood,
                 rotation=(math.pi / 2, 0.0, angle))
    effect('Campfire', 'fire', (cx, cy, base + 0.15))
    effect('CampfireSmoke', 'smoke', (cx, cy, base + 1.0), density=0.8)


def light_and_camera():
    bpy.ops.object.light_add(type='SUN', rotation=(math.radians(55.0), 0.0,
                                                   math.radians(145.0)))
    sun = placed(bpy.context.object, 'Sun')
    sun.data.energy = SUN_LUX / LUMENS_PER_WATT
    eye = Vector((21.0, -15.0, 5.5))
    bpy.ops.object.camera_add(location=eye)
    camera = placed(bpy.context.object, 'Lakeside')
    camera.rotation_euler = (Vector((0.0, 0.0, 0.0)) - eye).to_track_quat(
        '-Z', 'Y').to_euler()
    camera.data.name = 'Lakeside'
    camera.data.lens = 28.0
    bpy.context.scene.camera = camera


def build():
    empty_scene()
    grass = material('Grass', (0.16, 0.28, 0.08), roughness=0.95)
    stone = material('Stone', (0.35, 0.34, 0.32), roughness=0.85)
    wood = material('Wood', (0.3, 0.19, 0.1), roughness=0.8)
    metal = material('Iron', (0.12, 0.12, 0.13), roughness=0.45, metallic=1.0)
    ground(grass)
    lake()
    jetty(wood, metal)
    campfire(stone, wood)
    light_and_camera()


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
