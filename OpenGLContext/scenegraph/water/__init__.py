"""Water: what it looks like, how it moves, and what it is like inside.

Four pieces, and they are one subsystem because water is one substance:

``surface``
    the wave field, the three motions a body of water has -- still, flowing,
    choppy -- and the meshes that carry them
``medium``
    what a substance does to a body inside it: how far you can see, what the
    view closes to, what the mix loses, what it costs
``volumes``
    where the media are, as boxes, and what is at a point
``submersion``
    putting a context inside one: the fog it already binds and the mix it
    already has

Where there *is* water is authoring and lives with whatever builds the world;
everything here is the runtime half and decides nothing.
"""
from OpenGLContext.scenegraph.water.medium import (
    LAVA,
    MEDIA,
    SLIME,
    UNKNOWN,
    WATER,
    Medium,
    medium_for,
    worst_of,
)
from OpenGLContext.scenegraph.water.submersion import (
    apply,
    medium_fog,
    muffle_for,
    submerge,
)
from OpenGLContext.scenegraph.water.surface import (
    CHOPPY,
    LAKE,
    MESH_LIMIT,
    MESH_PER_WAVE,
    mesh_across,
    FLOWING,
    RIPPLE,
    RIPPLE_SCALE,
    STILL,
    WATER_ALBEDO,
    WATER_IOR,
    WATER_ROUGHNESS,
    WATER_TRANSPARENCY,
    WaterStyle,
    bounds,
    water_material,
    water_glints,
    water_ribbon,
    water_surface,
    wave_height,
    wave_normal,
)
from OpenGLContext.scenegraph.water.volumes import Volume, Volumes

__all__ = [
    'WATER_ALBEDO', 'WATER_ROUGHNESS', 'WATER_TRANSPARENCY', 'WATER_IOR',
    'RIPPLE', 'RIPPLE_SCALE', 'water_material', 'water_surface', 'water_ribbon', 'water_glints',
    'bounds',
    'WaterStyle', 'STILL', 'FLOWING', 'CHOPPY', 'LAKE', 'MESH_LIMIT',
    'MESH_PER_WAVE', 'mesh_across', 'wave_height', 'wave_normal',
    'Medium', 'MEDIA', 'WATER', 'SLIME', 'LAVA', 'UNKNOWN', 'medium_for',
    'worst_of', 'Volume', 'Volumes',
    'medium_fog', 'apply', 'muffle_for', 'submerge',
]
