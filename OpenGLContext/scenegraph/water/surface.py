"""Open water: the surface of a lake, a river or a sea.

Water is not ground of a different colour. Two things make it read as water and
a flat blue plate has neither:

**A shoreline comes from the ground, not from the water.** The shore is the line
where the land passes through the surface, so the terrain has to be meshed as it
actually is -- dipping under -- and the water laid over it. Clamping the ground
flat at the waterline and painting it blue removes the only thing that could
have drawn a shore.

**Water is dark and borrows its brightness.** Almost all of what a lake looks
like is the sky and the hills reflected in it, which is a question of *roughness*
rather than of colour: :func:`water_material` is nearly smooth, barely coloured,
and transparent enough to show the bed in the shallows.

    from OpenGLContext.scenegraph.water import water_surface
    sheet = water_surface(x0, x1, z0, z1, level=0.0)

**How it moves is what it is.** A pond, a river and a lake under weather are
the same material under three motions, and one :class:`WaterStyle` covers all
three: an amplitude, a wavelength, a speed, a steepness and a flow. Still water
has no displacement at all and carries its ripple in the *normals*, which is
what breaks the specular highlight into the moving glitter a still picture
reads as water -- and which keeps the shoreline exactly where the waterline is.
Choppy water displaces for real, so a shore moves and a boat pitches.

The field is a sum of directional waves taken from **where a point stands in
the world and what time it is**, so two sheets that meet agree along their
seam, a world rendered twice is the same world, and a caller can ask how high
the water is at a point -- which is what floating on it needs.

This is the runtime half, and it decides nothing. *Where* there is water -- which
is a question about the terrain -- is authoring, and lives with whatever builds
the world. What being *inside* it is like is
:mod:`OpenGLContext.scenegraph.water.medium`.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Optional, Tuple

import numpy as np

from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh

__all__ = ['WATER_ALBEDO', 'WATER_ROUGHNESS', 'WATER_TRANSPARENCY', 'WATER_IOR',
           'LAKE', 'MESH_FLOOR', 'MESH_LIMIT', 'MESH_PER_WAVE', 'mesh_across',
           'RIPPLE', 'RIPPLE_SCALE', 'water_material', 'water_surface',
           'WaterStyle', 'STILL', 'FLOWING', 'CHOPPY', 'wave_height',
           'wave_normal', 'water_ribbon', 'water_glints', 'bounds']

#: Deep water's own colour, which is very little of what is seen: a lake is
#: mostly the sky in it. Dark, and green-blue rather than the postcard blue --
#: fresh water carries silt and weed, and a saturated blue reads as a swimming
#: pool. Very dark, because almost none of what is seen is this: a lake is the
#: sky and the hills in it, and a light albedo washes those out.
WATER_ALBEDO = (0.014, 0.042, 0.058)

#: How smooth it is. Not zero: a perfect mirror is glass, and even still water
#: has enough surface to spread a highlight.
WATER_ROUGHNESS = 0.06

#: How much is seen through it, and how much it bends what is behind. Little:
#: seen from above, water over a pale bed is the bed, and what makes it read as
#: water at all is that it is *darker* than the shore beside it. 1.33 is water's
#: own refractive index.
WATER_TRANSPARENCY = 0.10
WATER_IOR = 1.33

#: How far the ripple tilts the surface, in radians, and over how many metres it
#: repeats. A long, shallow swell rather than chop: what it is for is breaking
#: the highlight up, and a steep one reads as corrugated iron.
RIPPLE = 0.045
RIPPLE_SCALE = 11.0


@dataclass(frozen=True)
class WaterStyle:
    """How a body of water moves.

    ``amplitude`` is metres from trough to crest, ``wavelength`` metres between
    crests, ``speed`` how fast the crests travel over the surface and
    ``steepness`` how far the normals tilt on top of whatever the displacement
    already tilts them -- which is what gives still water its glitter without
    moving it. ``flow`` is metres a second the surface drifts, as ``(x, z)``,
    and it is also the direction the crests travel where it is not zero.

    Three settings of it are named below. A caller who wants a fourth writes
    one: the point of the fields is that water is a continuum, and an
    enumeration of three would be a lie about that.
    """

    name: str = 'still'
    amplitude: float = 0.0
    wavelength: float = 11.0
    speed: float = 0.0
    steepness: float = RIPPLE
    flow: Tuple[float, float] = (0.0, 0.0)

    def moving(self) -> bool:
        """Whether anything about it changes with time."""
        return bool((self.amplitude and self.speed)
                    or self.flow[0] or self.flow[1])


#: A pond. Nothing moves; the ripple is in the light on it.
STILL = WaterStyle(name='still')

#: A river. Small crests travelling downstream, and the surface drifting with
#: them, so what is floating on it is visibly going somewhere.
FLOWING = WaterStyle(name='flowing', amplitude=0.09, wavelength=4.5,
                     speed=1.6, steepness=RIPPLE * 1.4, flow=(1.0, 0.0))

#: Weather. Crossing trains with real height in them, so a shoreline moves.
CHOPPY = WaterStyle(name='choppy', amplitude=0.42, wavelength=7.0, speed=2.4,
                    steepness=RIPPLE * 2.2)

#: Open water with nowhere to go: a lake or a reservoir. A slow swell with
#: enough height in it to read as a surface from a distance, which is the
#: distance most water is seen from. Still water is a *mirror*, and a mirror
#: a few hundred metres across with nothing to reflect but a pale sky is a
#: white plate lying in the landscape.
LAKE = WaterStyle(name='lake', amplitude=0.16, wavelength=9.0, speed=0.8,
                  steepness=RIPPLE * 1.3)

#: The most vertices across a sheet is meshed at. A sheet is one draw and this
#: is what it costs -- in a baked world, in the file as well as in the frame --
#: so it is a budget rather than a target.
MESH_LIMIT = 33

#: The fewest vertices across a sheet that carries any swell at all, matching
#: the fixed count this rule replaced. A pond was never the problem.
MESH_FLOOR = 9

#: How many samples a wavelength gets. The mesh only has to hold the *swell* --
#: the fine ripple that makes water read as water lives in the fragment shader
#: (``waveRipple``), where it is the same at any mesh density.
#:
#: Four rather than two. Two is the Nyquist limit: enough to represent a sine in
#: principle, and in practice whether the vertices land on the crests or on the
#: zero crossings is down to where the sheet happens to start. Measured against
#: the field sampled finely, two carries 73% of the wave over a 12 m sheet and
#: 84% over 40 m; four carries 89% and 96%. It costs nothing on the sheets that
#: matter most, which are already held at :data:`MESH_LIMIT`.
MESH_PER_WAVE = 4.0


def mesh_across(side: float, style: "Optional[WaterStyle]" = None,
                limit: int = MESH_LIMIT) -> int:
    """How many vertices across a sheet of this size has to be meshed at.

    From the *wavelength*, not from a count picked once: a sheet meshed at
    nine vertices across a tile hundreds of metres wide samples its own
    ripple every few hundred metres, which aliases the wave away and leaves
    a flat plate with a strange normal on it. That is what open water looks
    like when it looks like concrete.

    Capped at ``limit``, because a sheet is one draw and a lake the size of
    a valley would otherwise ask for a million vertices to carry a ripple
    nobody can see from the far side of it.
    """
    style = style if style is not None else STILL
    wave = max(float(style.wavelength), 1e-3)
    wanted = float(side) / wave * MESH_PER_WAVE + 1.0
    # Never below MESH_FLOOR on a sheet with a swell in it: the fixed count
    # this replaced was wrong on a lake and right on a pond, and a rule that
    # returns fewer vertices than it did on the small sheets would be a
    # regression dressed as a fix. Still water has no displacement to carry,
    # so it is left to ask for as little as it likes.
    floor = MESH_FLOOR if float(style.amplitude) else 2.0
    return int(min(max(wanted, floor), float(limit)))

#: The directions the wave trains run, as turns from the style's own heading,
#: and each one's share of the amplitude and of the wavelength. Three, crossing:
#: one train is corrugated iron, two beat against each other, and three read as
#: water without costing what a spectrum costs.
_TRAINS = (
    (0.0, 1.00, 1.00),
    (0.62, 0.55, 0.61),
    (-1.13, 0.34, 1.47),
)


def _heading(style: 'WaterStyle') -> float:
    """Which way the crests run, in radians, from the style's flow."""
    if style.flow[0] or style.flow[1]:
        return float(np.arctan2(style.flow[1], style.flow[0]))
    return 0.0


def _phases(style: 'WaterStyle', x: Any, z: Any, when: float):
    """Each train's phase at every point, and its own amplitude."""
    heading = _heading(style)
    x = np.asarray(x, dtype='d')
    z = np.asarray(z, dtype='d')
    for turn, share, stretch in _TRAINS:
        angle = heading + turn
        wavelength = max(float(style.wavelength) * stretch, 1e-6)
        number = 2.0 * np.pi / wavelength
        along = x * np.cos(angle) + z * np.sin(angle)
        yield (number * along - number * float(style.speed) * float(when),
               float(style.amplitude) * share, angle, number)


def wave_height(style: 'WaterStyle', x: Any, z: Any,
                when: float = 0.0) -> np.ndarray:
    """How far the surface stands above its level at each point, in metres.

    Zero everywhere for a style with no amplitude, which is what still water
    is: its ripple is in the normals and its surface is exactly its waterline.
    """
    x = np.asarray(x, dtype='d')
    z = np.asarray(z, dtype='d')
    height = np.zeros(np.broadcast(x, z).shape, dtype='d')
    if not style.amplitude:
        return height
    for phase, amplitude, _angle, _number in _phases(style, x, z, when):
        height = height + amplitude * np.sin(phase)
    return height


def wave_normal(style: 'WaterStyle', x: Any, z: Any,
                when: float = 0.0) -> np.ndarray:
    """The surface normal at each point, as ``(..., 3)`` unit vectors.

    Two things tilt it: the slope of whatever displacement there is, and the
    style's own ``steepness``, which is a ripple finer than the mesh carries.
    Still water has only the second, which is the whole of why it glitters.
    """
    x = np.asarray(x, dtype='d')
    z = np.asarray(z, dtype='d')
    shape = np.broadcast(x, z).shape
    slope_x = np.zeros(shape, dtype='d')
    slope_z = np.zeros(shape, dtype='d')
    for phase, amplitude, angle, number in _phases(style, x, z, when):
        rate = amplitude * number * np.cos(phase)
        slope_x = slope_x + rate * np.cos(angle)
        slope_z = slope_z + rate * np.sin(angle)
    fine_x, fine_z = _fine_ripple(x, z, float(style.steepness),
                                  _heading(style), when, style)
    normals = np.stack([-(slope_x + fine_x), np.ones(shape),
                        -(slope_z + fine_z)], axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    return normals


def _fine_ripple(x: np.ndarray, z: np.ndarray, steepness: float,
                 heading: float, when: float,
                 style: 'WaterStyle') -> Tuple[np.ndarray, np.ndarray]:
    """The ripple that lives in the normals rather than in the surface.

    Finer than any mesh a caller will pay for, which is why it is a normal and
    not a displacement: it exists to break the highlight into glitter, and a
    mesh fine enough to carry it would cost more than the glitter is worth.
    Carried downstream with the flow, so a river's light travels with it.
    """
    if steepness <= 0.0:
        zero = np.zeros(np.broadcast(x, z).shape, dtype='d')
        return (zero, zero)
    drift_x = x - float(style.flow[0]) * float(when)
    drift_z = z - float(style.flow[1]) * float(when)
    first = 2.0 * np.pi / RIPPLE_SCALE
    second = 2.0 * np.pi / (RIPPLE_SCALE * 1.7)
    slope_x = (steepness * np.cos(first * (drift_x + 0.6 * drift_z))
               + steepness * 0.6 * np.cos(second * (drift_x - 1.3 * drift_z)))
    slope_z = (steepness * 0.6 * np.sin(first * (drift_x + 0.6 * drift_z))
               - steepness * np.sin(second * (drift_x - 1.3 * drift_z)))
    return (slope_x, slope_z)


def water_material() -> PBRMaterial:
    """What open water is made of.

    Smooth, so it reflects; barely coloured, so what it reflects is what is
    seen; transparent, so the bed shows through where it is shallow; and
    two-sided, because a car that has gone in is looking up at it.
    """
    return PBRMaterial(baseColor=WATER_ALBEDO, metallic=0.0,
                       roughness=WATER_ROUGHNESS,
                       transparency=WATER_TRANSPARENCY, alphaMode='BLEND',
                       ior=WATER_IOR, doubleSided=True)


def water_surface(x0: float, x1: float, z0: float, z1: float,
                  level: float = 0.0, resolution: int = 9,
                  ripple: Optional[float] = None,
                  material: Optional[PBRMaterial] = None,
                  style: Optional[WaterStyle] = None,
                  when: float = 0.0, on_gpu: bool = False) -> PBRMesh:
    """A sheet of water over a footprint, at ``level``, moving as ``style`` says.

    ``resolution`` is how many vertices across it is meshed at. For still
    water that is not about its shape -- it is a plane -- but about how finely
    the ripple in the normals is carried; for choppy water it is also how much
    of the wave the surface can actually hold, and a sheet meshed too coarsely
    for its wavelength is a flat sheet with a strange normal.

    ``when`` is the time to build it at, in seconds. ``ripple`` overrides the
    style's steepness, and is there because a caller that had one before this
    had styles still means it.

    ``on_gpu`` meshes it **flat** and hands the style to the card instead: the
    surface is uploaded once and moving it is a handful of uniforms a frame,
    which is the only way a wave costs nothing. Set ``mesh.wave_time`` to
    advance it. A mesh built with the wave already in it and then moved on the
    card would have the wave applied twice, which is why this is one decision
    rather than two.
    """
    style = style if style is not None else STILL
    if ripple is not None:
        style = replace(style, steepness=float(ripple))
    xs = np.linspace(float(x0), float(x1), max(2, int(resolution)))
    zs = np.linspace(float(z0), float(z1), max(2, int(resolution)))
    gx, gz = np.meshgrid(xs, zs, indexing='ij')
    if on_gpu:
        # Flat, because the card is going to move it: a mesh built with the
        # wave already in it and then moved again is the wave applied twice.
        heights = np.full(gx.shape, float(level))
        normals = np.zeros(gx.shape + (3,), dtype='d')
        normals[..., 1] = 1.0
    else:
        heights = float(level) + wave_height(style, gx, gz, when)
        normals = wave_normal(style, gx, gz, when)
    positions = np.stack([gx, heights, gz], axis=-1).reshape(-1, 3)
    mesh = PBRMesh(positions=positions.astype('f'),
                   normals=normals.reshape(-1, 3).astype('f'),
                   indices=_grid(len(xs), len(zs)),
                   material=material if material is not None else water_material())
    return _driven(mesh, style, when, on_gpu)


def _ripple(gx: np.ndarray, gz: np.ndarray, ripple: float) -> np.ndarray:
    """Normals for a swell, from where each point stands in the world.

    Two waves crossing at an angle, so the highlight breaks up rather than
    striping. Taken from world position rather than from position within the
    sheet, so sheets that meet agree along their seam.
    """
    if ripple <= 0.0:
        normals = np.zeros(gx.shape + (3,), dtype='d')
        normals[..., 1] = 1.0
        return normals.reshape(-1, 3).astype('f')
    first = 2.0 * np.pi / RIPPLE_SCALE
    second = 2.0 * np.pi / (RIPPLE_SCALE * 1.7)
    slope_x = (ripple * np.cos(first * (gx + 0.6 * gz))
               + ripple * 0.6 * np.cos(second * (gx - 1.3 * gz)))
    slope_z = (ripple * 0.6 * np.sin(first * (gx + 0.6 * gz))
               - ripple * np.sin(second * (gx - 1.3 * gz)))
    normals = np.stack([-slope_x, np.ones_like(gx), -slope_z], axis=-1)
    normals /= np.linalg.norm(normals, axis=-1, keepdims=True)
    return normals.reshape(-1, 3).astype('f')


def _grid(across: int, along: int) -> np.ndarray:
    """Triangles for a grid of vertices, wound so the sheet faces up."""
    rows, columns = np.meshgrid(np.arange(across - 1), np.arange(along - 1),
                                indexing='ij')
    corner = (rows * along + columns).ravel()
    # Counter-clockwise seen from above, which is what makes the sheet
    # front-facing and agrees with the upward normals stored beside it. Wound
    # the other way the shader takes every fragment for a back face, flips the
    # normal away from the camera, and reads the surface at grazing incidence
    # wherever it is actually looked at square on.
    quads = np.stack([corner, corner + 1, corner + along + 1,
                      corner, corner + along + 1, corner + along], axis=-1)
    return quads.reshape(-1).astype(np.uint32)


def bounds(x0: float, x1: float, z0: float, z1: float, level: float) -> Any:
    """The box a sheet of water occupies, for a caller that partitions space."""
    return ((min(x0, x1), level, min(z0, z1)), (max(x0, x1), level, max(z0, z1)))


def water_ribbon(course: Any, width: Any, style: Optional[WaterStyle] = None,
                 when: float = 0.0, lift: float = 0.0,
                 material: Optional[PBRMaterial] = None,
                 on_gpu: bool = False) -> Optional[PBRMesh]:
    """Water swept along a course: a river.

    ``course`` is ``(N,3)`` world points -- where the water runs and how high
    it is there, which is what a routed channel already knows. ``width`` is
    metres across, either one number or one per point, so a river carrying more
    is wider further down.

    A lake is one flat plane and a river is not, which is the whole reason this
    exists: a sheet at a level cannot follow a course downhill. The wave field
    is the same one a sheet uses and is still taken from world position, so a
    river meeting a lake agrees with it along the join.

    The surface lies **across the flow** at every point, so a bend is a bend in
    plan rather than a ribbon sticking out sideways, and ``lift`` raises it
    above the course for a caller whose course is the bed rather than the
    surface. None where there is not enough course to sweep along.
    """
    line = np.asarray(course, dtype='d').reshape(-1, 3)
    if len(line) < 2:
        return None
    style = style if style is not None else FLOWING
    widths = np.broadcast_to(np.asarray(width, dtype='d'), (len(line),))
    across = _across(line)
    half = (widths / 2.0)[:, None]
    left = line + across * half
    right = line - across * half
    edges = np.stack([left, right], axis=1).reshape(-1, 3)
    edges[:, 1] += float(lift)
    if on_gpu:
        normals = np.zeros((len(edges), 3), dtype='d')
        normals[:, 1] = 1.0
    else:
        edges[:, 1] += wave_height(style, edges[:, 0], edges[:, 2], when)
        normals = wave_normal(style, edges[:, 0], edges[:, 2], when)
    mesh = PBRMesh(positions=edges.astype('f'), normals=normals.astype('f'),
                   indices=_ladder(len(line)),
                   material=material if material is not None else water_material())
    return _driven(mesh, style, when, on_gpu)


def _driven(mesh: PBRMesh, style: WaterStyle, when: float,
            on_gpu: bool) -> PBRMesh:
    """Tell a mesh what moves it, if anything does.

    The two attributes are the whole contract with the card: a shape reads them
    off its geometry and hands them to the shader, and a mesh that has neither
    is not water and pays nothing.
    """
    if on_gpu:
        mesh.wave_style = style
        mesh.wave_time = float(when)
    return mesh


def _across(line: np.ndarray) -> np.ndarray:
    """A unit vector across the course at each point, level with the ground.

    From the direction through each point rather than from the segment before
    or after it, so the two sides of a bend meet rather than stepping.
    """
    ahead = np.vstack([line[1:], line[-1:]]) - np.vstack([line[:1], line[:-1]])
    ahead[:, 1] = 0.0
    length = np.linalg.norm(ahead, axis=1, keepdims=True)
    ahead = ahead / np.maximum(length, 1e-9)
    # Level and to the left of the direction of travel.
    return np.stack([-ahead[:, 2], np.zeros(len(line)), ahead[:, 0]], axis=-1)


def _ladder(rungs: int) -> np.ndarray:
    """Triangles for a strip two vertices wide and ``rungs`` long."""
    first = np.arange(rungs - 1) * 2
    # Counter-clockwise seen from above, as in _grid.
    quads = np.stack([first, first + 3, first + 1,
                      first, first + 2, first + 3], axis=-1)
    return quads.reshape(-1).astype(np.uint32)


#: How much wider than the water a glint is, and how long. A glint is the sun
#: caught on a facet of the surface, so it is a patch rather than a line: wider
#: than the river only slightly, and about as long as it is wide.
GLINT_WIDTH = 0.8
GLINT_LENGTH = 1.2


def water_glints(course: Any, width: Any, spacing: float,
                 style: Optional[WaterStyle] = None, when: float = 0.0,
                 lift: float = 0.0, size: float = GLINT_WIDTH,
                 material: Optional[PBRMaterial] = None,
                 on_gpu: bool = False) -> Optional[PBRMesh]:
    """Water seen from far off: the sun catching it here and there.

    A river a kilometre away is not a ribbon. It is two pixels wide and mostly
    hidden by whatever stands over it, and what the eye actually gets is the
    surface flashing between the trees. A full ribbon at that range spends a
    tile's whole budget drawing a line nobody can resolve; this spends a
    handful of quads on the thing that is actually visible.

    ``spacing`` is how far apart the glints are, in metres -- wider with
    distance, which is the level of detail. Because a coarser tile is also a
    *bigger* tile, a spacing that grows with the tile's error keeps the number
    of glints in a tile roughly constant, which is what makes this a budget
    rather than a fade. ``size`` is how much of the river's width each one
    covers.

    Where they fall is a function of **where they are on the course**, not of a
    random draw, so a world baked twice glints in the same places.

    ``on_gpu`` meshes them flat and hands the style to the card, exactly as a
    sheet or a ribbon does: a glint is water, and it catches the light because
    the surface under it moves.
    """
    line = np.asarray(course, dtype='d').reshape(-1, 3)
    if len(line) < 2:
        return None
    style = style if style is not None else FLOWING
    widths = np.broadcast_to(np.asarray(width, dtype='d'), (len(line),))
    steps = np.linalg.norm(np.diff(line[:, [0, 2]], axis=0), axis=1)
    along = np.concatenate([[0.0], np.cumsum(steps)])
    total = float(along[-1])
    reach = max(float(spacing), 1e-3)
    at = np.arange(reach / 2.0, total, reach)
    if not len(at):
        # Wider apart than the river is long: one, in the middle. A river that
        # is drawn at all should catch the light somewhere, and a spacing that
        # happens to overshoot its length is not a reason for it to vanish.
        at = np.array([total / 2.0])
    where = np.stack([np.interp(at, along, line[:, axis]) for axis in range(3)],
                     axis=-1)
    across = _across(np.stack([np.interp(at, along, line[:, 0]),
                               np.interp(at, along, line[:, 1]),
                               np.interp(at, along, line[:, 2])], axis=-1))
    half = (np.interp(at, along, widths) * float(size) / 2.0)[:, None]
    # A glint is a patch on the surface, so it has length as well as width;
    # the length runs with the flow, which is what makes it read as water
    # rather than as a row of tiles.
    ahead = np.stack([-across[:, 2], np.zeros(len(at)), across[:, 0]], axis=-1)
    long_half = half * (GLINT_LENGTH / max(float(size), 1e-6)) * float(size)
    corners = [where - across * half - ahead * long_half,
               where + across * half - ahead * long_half,
               where + across * half + ahead * long_half,
               where - across * half + ahead * long_half]
    points = np.stack(corners, axis=1).reshape(-1, 3)
    points[:, 1] += float(lift)
    if on_gpu:
        normals = np.zeros((len(points), 3), dtype='d')
        normals[:, 1] = 1.0
    else:
        points[:, 1] += wave_height(style, points[:, 0], points[:, 2], when)
        normals = wave_normal(style, points[:, 0], points[:, 2], when)
    first = np.arange(len(at)) * 4
    # Counter-clockwise seen from above, as in _grid: `across` and `ahead`
    # put the corners round the patch the other way.
    quads = np.stack([first, first + 2, first + 1,
                      first, first + 3, first + 2], axis=-1)
    mesh = PBRMesh(positions=points.astype('f'), normals=normals.astype('f'),
                   indices=quads.reshape(-1).astype(np.uint32),
                   material=material if material is not None else water_material())
    return _driven(mesh, style, when, on_gpu)
