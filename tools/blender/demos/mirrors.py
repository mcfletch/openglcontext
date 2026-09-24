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

The stone, brick, plaster and metal are baked from the engine's own procedural
surfaces (``OpenGLContext/scenegraph/surfaces.py``), loaded here by path: that
module needs nothing but NumPy, which Blender has.
"""
import argparse
import importlib.util
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


def load_surfaces():
    """The engine's procedural surfaces module, loaded without the engine."""
    path = Path(__file__).resolve().parents[3] / 'OpenGLContext' / 'scenegraph' / 'surfaces.py'
    spec = importlib.util.spec_from_file_location('oglc_surfaces', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


surfaces = load_surfaces()


def image(name, pixels, colour):
    """A packed Blender image of an 8-bit RGB array whose first row is the top."""
    height, width = pixels.shape[:2]
    made = bpy.data.images.new(name, width, height, alpha=False)
    made.colorspace_settings.name = 'sRGB' if colour else 'Non-Color'
    rgba = surfaces.np.ones((height, width, 4), 'f')
    rgba[..., :3] = pixels[::-1] / 255.0
    made.pixels.foreach_set(rgba.ravel())
    made.pack()
    return made


def surface_material(name, maps, relief=2.0):
    """A material wearing a procedural surface, wired as the glTF exporter reads it."""
    base, packed, normal = surfaces.images(maps, relief)
    made = bpy.data.materials.new(name)
    made.use_nodes = True
    nodes, links = made.node_tree.nodes, made.node_tree.links
    shader = nodes['Principled BSDF']
    colour = nodes.new('ShaderNodeTexImage')
    colour.image = image(name + 'Colour', base, True)
    links.new(colour.outputs['Color'], shader.inputs['Base Color'])
    rough = nodes.new('ShaderNodeTexImage')
    rough.image = image(name + 'MetalRough', packed, False)
    split = nodes.new('ShaderNodeSeparateColor')
    links.new(rough.outputs['Color'], split.inputs['Color'])
    links.new(split.outputs['Green'], shader.inputs['Roughness'])
    links.new(split.outputs['Blue'], shader.inputs['Metallic'])
    bumps = nodes.new('ShaderNodeTexImage')
    bumps.image = image(name + 'Normal', normal, False)
    mapped = nodes.new('ShaderNodeNormalMap')
    links.new(bumps.outputs['Color'], mapped.inputs['Color'])
    links.new(mapped.outputs['Normal'], shader.inputs['Normal'])
    return made


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


def panel(name, size, location, rotation, material_, texture=None):
    """A flat rectangle, ``size`` = (width, height), facing where it is turned.

    ``texture`` is the metres one repeat of its material covers; its texture
    coordinates are scaled to match, so a wall repeats its brick at brick size.
    """
    bpy.ops.mesh.primitive_plane_add(size=1.0, location=location, rotation=rotation)
    obj = placed(bpy.context.object, name, material_)
    obj.scale = (size[0], size[1], 1.0)
    if texture is not None:
        for loop in obj.data.uv_layers.active.data:
            loop.uv = (loop.uv[0] * size[0] / texture, loop.uv[1] * size[1] / texture)
    return obj


def block(name, size, location, material_):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = placed(bpy.context.object, name, material_)
    obj.scale = size
    return obj


def room(brick, plaster):
    """Four brick walls and a plaster ceiling, faced into the room."""
    half_w, half_l, middle = WIDTH / 2.0, LENGTH / 2.0, HEIGHT / 2.0
    right_angle = math.radians(90.0)
    # A plane faces +z; turned a right angle about x it faces -y, and each
    # wall is then turned about z to face into the room.
    panel('WallFar', (WIDTH, HEIGHT), (0.0, half_l, middle), (right_angle, 0.0, 0.0),
          brick, texture=1.0)
    panel('WallNear', (WIDTH, HEIGHT), (0.0, -half_l, middle), (right_angle, 0.0, math.pi),
          brick, texture=1.0)
    panel('WallLeft', (LENGTH, HEIGHT), (-half_w, 0.0, middle),
          (right_angle, 0.0, right_angle), brick, texture=1.0)
    panel('WallRight', (LENGTH, HEIGHT), (half_w, 0.0, middle),
          (right_angle, 0.0, -right_angle), brick, texture=1.0)
    panel('Ceiling', (WIDTH, LENGTH), (0.0, 0.0, HEIGHT), (math.pi, 0.0, 0.0),
          plaster, texture=3.0)


def mirrors():
    """The floor, the far mirror and the corridor: materials tagged ``mirror``."""
    marble = mirror(surface_material('Marble', surfaces.checkered_marble(512, tiles=2)),
                    interval=2, priority=0.5)
    panel('Floor', (WIDTH, LENGTH), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0), marble, texture=2.0)
    silver = mirror(material('Silver', (0.95, 0.95, 0.96), roughness=0.02,
                             metallic=1.0), interval=2, priority=2.0)
    panel('FarMirror', (6.0, 3.0), (0.0, LENGTH / 2 - 0.1, 2.0),
          (math.radians(90.0), 0.0, 0.0), silver)
    gilt = surface_material('Gilt', surfaces.brushed_metal(128, surfaces.GOLD, 0.22))
    block('FarFrame', (6.4, 0.1, 3.4), (0.0, LENGTH / 2 - 0.03, 2.0), gilt)
    corridor = mirror(material('CorridorGlass', (0.9, 0.92, 0.95), roughness=0.03,
                               metallic=1.0), resolution=0.35)
    bronze = surface_material('Bronze', surfaces.brushed_metal(128, surfaces.BRONZE, 0.35))
    for index in range(10):
        y = -9.0 + 2.0 * index
        panel('CorridorMirror%d' % index, (1.0, 1.4), (-WIDTH / 2 + 0.1, y, 1.8),
              (0.0, math.radians(90.0), 0.0), corridor)
        block('CorridorFrame%d' % index, (0.08, 1.2, 1.6), (-WIDTH / 2 + 0.04, y, 1.8),
              bronze)


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
    """Four columns of brushed metal, each with a lamp over it that lights the room."""
    metals = [(surfaces.GOLD, 0.25), (surfaces.COPPER, 0.3), (surfaces.STEEL, 0.2),
              (surfaces.BRONZE, 0.32)]
    for index, (colour, rough) in enumerate(metals):
        x, y = -4.5 + 3.0 * index, 7.0 - 5.0 * (index % 2)
        metal = surface_material('Column%d' % index,
                                 surfaces.brushed_metal(128, colour, rough))
        block('Column%d' % index, (0.6, 0.6, 3.0), (x, y, 1.5), metal)
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
    brick = surface_material('Brick', surfaces.brick(256))
    plaster = surface_material('Plaster', surfaces.plaster(256), relief=0.5)
    rim = surface_material('Sandstone', surfaces.sandstone(256))
    room(brick, plaster)
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
                              export_lights=True, export_apply=True,
                              export_tangents=True)


main()
