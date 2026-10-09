"""X3D's volume render styles as a plan for the ray march (no GL)

A VolumeData, SegmentedVolumeData or IsoSurfaceVolumeData is drawn by
marching rays through its voxels (:mod:`OpenGLContext.scenegraph.volumedata`).
What each sample becomes is decided by the node's render styles, and
:func:`plan` turns those into a :class:`Plan`: the GLSL the march compiles
(:meth:`Plan.source`), a :attr:`Plan.signature` that is equal for every
plan making the same GLSL, the uniform values each draw is given
(:meth:`Plan.values`) and the textures it samples (:attr:`Plan.textures`).

The equations are ISO/IEC 19775-1, 41.4. Each style takes the colour and
opacity the previous style gave (Cv, Ov) and gives its own (Cg, Og). The
first style is given the voxel's colour channels (Table 41.6) and, as
opacity, the voxel's first component: the default OpacityMapVolumeStyle's
ramp from transparent at 0 to opaque at 1. An IsoSurfaceVolumeData's
surfaces have an opacity of 1. Where the specification leaves a choice, the
behaviour X_ITE shows is followed:

- a style whose ``enabled`` is FALSE is drawn as though it were absent; a
  volume left with no style is drawn by the default OpacityMapVolumeStyle;
- CartoonVolumeStyle's colour keeps the opacity it is given, times the
  colour's alpha;
- an isosurface with no style is drawn in its voxel colour, opaque and unlit.

A ProjectionVolumeStyle replaces the march with a projection of the voxel
intensities along the ray (``mode`` ``'projection'``); it is drawn as the
style of a VolumeData. In a SegmentedVolumeData or an IsoSurfaceVolumeData it
is drawn as the default OpacityMapVolumeStyle.

Normals are the normalised gradient of the voxels' first component (41.2.2.2.2),
pointing from higher values to lower, unless a style's ``surfaceNormals``
texture of three or more channels gives them. The gradient's magnitude (|Δf|)
is measured in value per voxel, values running 0 to 1.

The ten style nodes are the engine's classes at the end of this module, with
the fields X3D gives them and no behaviour of their own.

Transfer functions and BlendedVolumeStyle's weight tables are read as RGBA
tables (:func:`transfer_table`), so a style samples the same layout whatever
the texture held.
"""
from __future__ import annotations

import colorsys
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np
from vrml.x3d import nodes as x3d

__all__ = [
    'BlendedVolumeStyle', 'BoundaryEnhancementVolumeStyle', 'CartoonVolumeStyle', 'ComposedVolumeStyle', 'EdgeEnhancementVolumeStyle', 'OpacityMapVolumeStyle', 'ProjectionVolumeStyle', 'ShadedVolumeStyle', 'SilhouetteEnhancementVolumeStyle', 'ToneMappedVolumeStyle',
    'MAX_CARTOON_STEPS', 'MAX_ISOSURFACES', 'MAX_SEGMENTS', 'PROJECTIONS', 'Plan', 'Step',
    'TextureSlot', 'cartoon_palette', 'channels_of', 'isosurfaces', 'plan', 'rgba_table',
    'transfer_table',
]

#: The most colours a CartoonVolumeStyle's colorSteps gives (41.4.3).
MAX_CARTOON_STEPS = 64
#: The most isosurfaces one IsoSurfaceVolumeData draws.
MAX_ISOSURFACES = 64
#: Segment identifiers are a texture's first component: 0 to 255.
MAX_SEGMENTS = 256
#: ProjectionVolumeStyle's types, as the shader numbers them.
PROJECTIONS = {'MAX': 0, 'MIN': 1, 'AVERAGE': 2}
#: BlendedVolumeStyle's weight functions, as GLSL on the colour given (c) and the
#: second volume's (blend); ``TABLE`` is written where it is used.
_WEIGHTS = {
    'CONSTANT': 's%d_weight%d', 'ALPHA1': 'c.a', 'ALPHA2': 'blend.a',
    'ONE_MINUS_ALPHA1': '(1.0 - c.a)', 'ONE_MINUS_ALPHA2': '(1.0 - blend.a)',
}
#: How a voxel's components (in its first one to four places) are read from the
#: sampled colour, by the number of channels the texture has: luminance is
#: sampled as (L, L, L, 1) and luminance-alpha as (L, L, L, A).
_RAW = {1: 'vec4(%s.r, 0.0, 0.0, 0.0)', 2: 'vec4(%s.r, %s.a, 0.0, 0.0)',
        3: 'vec4(%s.rgb, 0.0)', 4: '%s'}

# -- tables ------------------------------------------------------------------------


def rgba_table(pixels: np.ndarray) -> np.ndarray:
    """``pixels`` (any shape, one to four channels last) as RGBA by Table 41.6

    Luminance is (L, L, L, 1), luminance-alpha (L, L, L, A), RGB (R, G, B, 1).
    """
    pixels = np.asarray(pixels, np.uint8)
    channels = pixels.shape[-1]
    opaque = np.full(pixels.shape[:-1] + (1,), 255, np.uint8)
    if channels == 1:
        found = np.concatenate([pixels, pixels, pixels, opaque], -1)
    elif channels == 2:
        grey = pixels[..., :1]
        found = np.concatenate([grey, grey, grey, pixels[..., 1:]], -1)
    elif channels == 3:
        found = np.concatenate([pixels, opaque], -1)
    else:
        found = pixels[..., :4]
    return np.ascontiguousarray(found)


def _pixels(texture: Any) -> Optional[np.ndarray]:
    """A texture node's pixels: ``(h, w, c)`` for 2D, ``(d, h, w, c)`` for 3D; None without"""
    if not texture:
        return None
    volume = getattr(texture, 'volumeData', None)
    if volume is not None:
        found: Optional[np.ndarray] = volume()
        return found
    from OpenGLContext.scenegraph.texture3d import image_array  # noqa: PLC0415 PIL only for 2D tables
    try:
        return image_array(texture)
    except (TypeError, ValueError):
        return None


def transfer_table(texture: Any) -> Optional[np.ndarray]:
    """A transfer function texture as an RGBA table, or None while it has no pixels

    ``(h, w, 4)`` for a 2D texture, ``(d, h, w, 4)`` for a 3D one, uint8.
    """
    found = _pixels(texture)
    return None if found is None else rgba_table(found)


def channels_of(texture: Any) -> int:
    """How many channels a texture node's pixels have; 0 while it has none"""
    found = _pixels(texture)
    return 0 if found is None else int(found.shape[-1])


def _is_3d(texture: Any) -> bool:
    return isinstance(texture, x3d.X3DTexture3DNode)


def _hsv(colour: Any) -> tuple[float, float, float]:
    red, green, blue = (min(1.0, max(0.0, float(part))) for part in colour[:3])
    return colorsys.rgb_to_hsv(red, green, blue)


def cartoon_palette(orthogonal: Sequence[float], parallel: Sequence[float],
                    steps: int) -> np.ndarray:
    """CartoonVolumeStyle's colours, one per range of the angle from the viewer (41.4.3)

    ``steps`` ranges divide 0 to pi/2; the first is ``orthogonal``, the last
    ``parallel``, and each between is the colour at its midpoint angle,
    interpolated in HSV (hue the short way round) with alpha linear. One step
    is ``orthogonal`` alone. ``(steps, 4)`` float32, steps held to 1..64.
    """
    steps = min(MAX_CARTOON_STEPS, max(1, int(steps)))
    first = np.asarray(tuple(orthogonal) + (1.0,) * (4 - len(orthogonal)), np.float64)[:4]
    last = np.asarray(tuple(parallel) + (1.0,) * (4 - len(parallel)), np.float64)[:4]
    if steps == 1:
        return first.astype(np.float32)[None]
    hue0, saturation0, value0 = _hsv(first)
    hue1, saturation1, value1 = _hsv(last)
    # A grey has no hue of its own: it takes the other end's.
    if saturation0 == 0.0:
        hue0 = hue1
    if saturation1 == 0.0:
        hue1 = hue0
    if abs(hue1 - hue0) > 0.5:
        hue1 += -1.0 if hue1 > hue0 else 1.0
    found = [first]
    for index in range(1, steps - 1):
        share = (index + 0.5) / steps
        hue = (hue0 + (hue1 - hue0) * share) % 1.0
        rgb = colorsys.hsv_to_rgb(hue, saturation0 + (saturation1 - saturation0) * share,
                                  value0 + (value1 - value0) * share)
        found.append(np.array(rgb + (first[3] + (last[3] - first[3]) * share,)))
    found.append(last)
    return np.asarray(found, np.float32)


def isosurfaces(values: Sequence[float], step: float,
                styles: int) -> list[tuple[float, int]]:
    """IsoSurfaceVolumeData's surfaces (41.4.6): ``(value, style index)`` by value

    Several ``values`` are drawn as listed, each with the style of its index.
    One value with a ``step`` adds every multiple of the step from it within
    0 to 1, and these take the styles after the first from the smallest
    value up. A surface past the last style takes the last. At most
    :data:`MAX_ISOSURFACES`: the ones nearest the value.
    """
    last = max(1, int(styles)) - 1
    values = [float(value) for value in values]
    if not values:
        return []
    if len(values) > 1:
        listed = [(value, min(index, last)) for index, value in enumerate(values)]
        return sorted(listed[:MAX_ISOSURFACES])
    first = values[0]
    step = abs(float(step))
    if step == 0.0 or not math.isfinite(step) or not math.isfinite(first):
        return [(first, 0)]
    low = math.ceil((0.0 - first) / step - 1e-9)
    high = math.floor((1.0 - first) / step + 1e-9)
    multiples = sorted((k for k in range(int(low), int(high) + 1) if k != 0), key=abs)
    kept = sorted(multiples[:MAX_ISOSURFACES - 1])
    found = [(first, 0)] + [(first + k * step, min(1 + rank, last))
                            for rank, k in enumerate(kept)]
    return sorted(found)


# -- the plan -----------------------------------------------------------------------


@dataclass(frozen=True)
class TextureSlot:
    """A texture the march samples: its sampler's name, what it is, the node

    ``kind`` is ``'volume'`` (the node's own 3D texture, sampled as it is
    uploaded), ``'table2d'`` or ``'table3d'`` (:func:`transfer_table`). Every
    one is a ``sampler3D``: a 2D table is uploaded one slice deep.
    """

    name: str
    kind: str
    node: Any


@dataclass
class Step:
    """One style the march applies: its kind, its node, the steps it applies in turn

    ``channels`` is the number of channels of the voxels it reads.
    """

    kind: str
    node: Any
    channels: int
    children: tuple[int, ...] = ()
    #: What the step's GLSL is made from beyond its kind and children.
    shape: tuple[Any, ...] = ()
    #: The step's own textures, by role.
    textures: dict[str, str] = field(default_factory=dict)
    #: For a BlendedVolumeStyle, the step its second volume is styled by (-1: none).
    second: int = -1


@dataclass
class Plan:
    """What one volume's ray march does; see the module's description

    ``mode`` is ``'composite'`` (front-to-back compositing of every sample),
    ``'projection'`` or ``'isosurface'``. ``roots`` are the step each
    segment (or each isosurface style) starts from.
    """

    mode: str
    channels: int
    steps: list[Step] = field(default_factory=list)
    textures: list[TextureSlot] = field(default_factory=list)
    roots: list[int] = field(default_factory=list)
    segmented: bool = False
    #: Whether the march works out the voxels' gradient (normals, |Δf|).
    gradient: bool = False
    #: Whether a style reads the scene's lights.
    lights: bool = False
    node: Any = None
    #: GLSL uniform declarations: name -> (type, array length or 0).
    uniforms: dict[str, tuple[str, int]] = field(default_factory=dict)
    _getters: list[tuple[str, Callable[[], Any]]] = field(default_factory=list)

    @property
    def segments(self) -> tuple[int, ...]:
        """The step each segment identifier starts from, by identifier"""
        return tuple(self.roots)

    @property
    def clearStaysClear(self) -> bool:
        """Whether a voxel whose first component is 0 is drawn transparent

        True where every style scales the opacity it is given: none is a
        transfer function or a BlendedVolumeStyle, which give opacity of their own.
        """
        return self.mode == 'composite' and not any(
            step.kind == 'blended' or (step.kind == 'opacity' and 'table' in step.textures)
            for step in self.steps)

    @property
    def signature(self) -> tuple[Any, ...]:
        """Equal for every plan whose GLSL is the same"""
        return (self.mode, self.channels, self.segmented, self.gradient, self.lights,
                tuple(self.roots),
                tuple((step.kind, step.channels, step.children, step.shape, step.second,
                       tuple(sorted(step.textures.items()))) for step in self.steps),
                tuple((slot.name, slot.kind) for slot in self.textures))

    def values(self) -> dict[str, Any]:
        """Every uniform's value, read from the nodes' fields as they stand"""
        return {name: get() for name, get in self._getters}

    def declare(self, name: str, kind: str, get: Callable[[], Any], length: int = 0) -> None:
        self.uniforms[name] = (kind, length)
        self._getters.append((name, get))

    def texture(self, name: str, kind: str, node: Any) -> str:
        self.textures.append(TextureSlot(name, kind, node))
        return name

    def source(self) -> str:
        """The GLSL: the style uniforms and samplers, a function per step, and
        ``volumeStyle(VSample s)``, the colour and opacity of one sample"""
        lines = []
        for name, (kind, length) in self.uniforms.items():
            lines.append('uniform %s %s%s;' % (kind, name, '[%d]' % length if length else ''))
        for slot in self.textures:
            lines.append('uniform sampler3D %s;' % (slot.name,))
        for index in range(len(self.steps) - 1, -1, -1):
            lines.append(_function(self, index))
        lines.append(self._top())
        return '\n'.join(lines) + '\n'

    def _top(self) -> str:
        if self.mode == 'isosurface':
            body = ['    vec4 c = vec4(s.voxel.rgb, 1.0);']
            for index, root in enumerate(self.roots):
                body.append('    if (s.surface == %d) return style%d(c, s);' % (index, root))
        else:
            body = ['    vec4 c = vec4(s.voxel.rgb, %s.x);' % (_raw('s.voxel', self.channels),)]
            if self.segmented:
                body.append('    if ((segmentsOff[s.segment >> 5] & (1u << uint(s.segment & 31)))'
                            ' != 0u) return vec4(0.0);')
            for index, root in enumerate(self.roots):
                if root >= 0:
                    body.append('    if (s.segment == %d) return style%d(c, s);' % (index, root))
        body.append('    return c;')
        return 'vec4 volumeStyle(VSample s) {\n%s\n}' % ('\n'.join(body),)


def _raw(name: str, channels: int) -> str:
    """GLSL for a sampled voxel's components, in their first places"""
    pattern = _RAW.get(channels, '%s')
    return pattern.replace('%s', name)


def _colour(value: Any, length: int = 4) -> np.ndarray:
    return np.asarray(tuple(value)[:length], np.float32)


# -- building the steps -------------------------------------------------------------

_KINDS: dict[type, str] = {
    x3d.OpacityMapVolumeStyle: 'opacity',
    x3d.BoundaryEnhancementVolumeStyle: 'boundary',
    x3d.CartoonVolumeStyle: 'cartoon',
    x3d.ComposedVolumeStyle: 'composed',
    x3d.EdgeEnhancementVolumeStyle: 'edge',
    x3d.ShadedVolumeStyle: 'shaded',
    x3d.SilhouetteEnhancementVolumeStyle: 'silhouette',
    x3d.ToneMappedVolumeStyle: 'tone',
    x3d.BlendedVolumeStyle: 'blended',
}

#: The kinds that read a surface normal, and so the gradient.
_NORMALS = frozenset(('cartoon', 'edge', 'silhouette', 'tone', 'shaded'))


def _kind_of(style: Any) -> Optional[str]:
    for kind_type, kind in _KINDS.items():
        if isinstance(style, kind_type):
            return kind
    return None


def _enabled(style: Any) -> bool:
    return bool(style) and bool(getattr(style, 'enabled', True))


class _Builder:
    """Adds a style tree's steps to a plan, numbering them in the order met"""

    def __init__(self, found: Plan) -> None:
        self.plan = found

    def add(self, style: Any, channels: int, main: bool = True) -> int:
        """The index of the step for ``style``, or -1 where it draws as though absent"""
        if not _enabled(style):
            return -1
        kind = _kind_of(style)
        if kind is None:
            return -1
        if kind == 'blended' and not channels_of(style.voxels):
            return -1
        found = self.plan
        index = len(found.steps)
        step = Step(kind, style, channels)
        found.steps.append(step)
        prefix = 's%d_' % (index,)
        getattr(self, '_' + kind)(step, index, prefix, main)
        if kind in _NORMALS and 'normals' not in step.textures and main:
            if kind != 'shaded' or step.shape[1]:
                found.gradient = True
        return index

    def _normals(self, step: Step, prefix: str, style: Any) -> None:
        normals = getattr(style, 'surfaceNormals', None)
        if normals and _is_3d(normals) and channels_of(normals) >= 3:
            step.textures['normals'] = self.plan.texture(prefix + 'normals', 'volume', normals)

    def _opacity(self, step: Step, index: int, prefix: str, main: bool) -> None:
        table = step.node.transferFunction
        if table and transfer_table(table) is not None:
            kind = 'table3d' if _is_3d(table) else 'table2d'
            step.textures['table'] = self.plan.texture(prefix + 'table', kind, table)

    def _boundary(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        if main:
            self.plan.gradient = True
        self.plan.declare(prefix + 'retained', 'float', lambda: float(style.retainedOpacity))
        self.plan.declare(prefix + 'boundary', 'float', lambda: float(style.boundaryOpacity))
        self.plan.declare(prefix + 'exponent', 'float', lambda: float(style.opacityFactor))

    def _cartoon(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        self._normals(step, prefix, style)

        def palette() -> np.ndarray:
            colours = cartoon_palette(style.orthogonalColor, style.parallelColor,
                                      style.colorSteps)
            padded = np.zeros((MAX_CARTOON_STEPS, 4), np.float32)
            padded[:len(colours)] = colours
            return padded
        self.plan.declare(prefix + 'steps', 'int',
                          lambda: min(MAX_CARTOON_STEPS, max(1, int(style.colorSteps))))
        self.plan.declare(prefix + 'palette', 'vec4', palette, MAX_CARTOON_STEPS)

    def _composed(self, step: Step, index: int, prefix: str, main: bool) -> None:
        children = [self.add(child, step.channels, main) for child in step.node.renderStyle]
        step.children = tuple(child for child in children if child >= 0)

    def _edge(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        self._normals(step, prefix, style)
        self.plan.declare(prefix + 'color', 'vec3', lambda: _colour(style.edgeColor, 3))
        self.plan.declare(prefix + 'threshold', 'float',
                          lambda: math.cos(float(style.gradientThreshold)))

    def _silhouette(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        self._normals(step, prefix, style)
        self.plan.declare(prefix + 'retained', 'float',
                          lambda: float(style.silhouetteRetainedOpacity))
        self.plan.declare(prefix + 'boundary', 'float',
                          lambda: float(style.silhouetteBoundaryOpacity))
        self.plan.declare(prefix + 'sharpness', 'float', lambda: float(style.silhouetteSharpness))

    def _tone(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        self._normals(step, prefix, style)
        self.plan.lights = True
        self.plan.declare(prefix + 'warm', 'vec3', lambda: _colour(style.warmColor, 3))
        self.plan.declare(prefix + 'cool', 'vec3', lambda: _colour(style.coolColor, 3))

    def _shaded(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        material = style.material
        lit = bool(style.lighting)
        step.shape = (bool(material), lit)
        if lit:
            self._normals(step, prefix, style)
            self.plan.lights = True

        def read(name: str, default: Any) -> Callable[[], Any]:
            def get() -> Any:
                held = style.material
                value = getattr(held, name, default) if held else default
                return _colour(value, 3) if isinstance(default, tuple) else float(value)
            return get
        self.plan.declare(prefix + 'diffuse', 'vec3', read('diffuseColor', (0.8, 0.8, 0.8)))
        self.plan.declare(prefix + 'specular', 'vec3', read('specularColor', (0.0, 0.0, 0.0)))
        self.plan.declare(prefix + 'emissive', 'vec3', read('emissiveColor', (0.0, 0.0, 0.0)))
        self.plan.declare(prefix + 'ambient', 'float', read('ambientIntensity', 0.0))
        self.plan.declare(prefix + 'shininess', 'float', read('shininess', 0.0))
        transparency = read('transparency', 0.0)
        self.plan.declare(prefix + 'opacity', 'float', lambda: 1.0 - transparency())

    def _blended(self, step: Step, index: int, prefix: str, main: bool) -> None:
        style = step.node
        second = style.voxels
        channels = channels_of(second)
        step.textures['voxels'] = self.plan.texture(prefix + 'voxels', 'volume', second)
        functions = []
        for which in (1, 2):
            function = str(getattr(style, 'weightFunction%d' % which))
            table = getattr(style, 'weightTransferFunction%d' % which)
            if function == 'TABLE':
                if table and not _is_3d(table) and transfer_table(table) is not None:
                    step.textures['weights%d' % which] = self.plan.texture(
                        '%sweightTable%d' % (prefix, which), 'table2d', table)
                else:
                    function = 'ALPHA1'
            functions.append(function)
            if function == 'CONSTANT':
                self.plan.declare('%sweight%d' % (prefix, which), 'float',
                                  _field_reader(style, 'weightConstant%d' % which))
        step.second = self.add(style.renderStyle, channels, False)
        normals = step.second >= 0 and any(
            other.kind in _NORMALS or other.kind == 'boundary'
            for other in self.plan.steps[step.second:])
        step.shape = (tuple(functions), channels, normals)


def _field_reader(node: Any, name: str) -> Callable[[], float]:
    """A reader of ``node``'s float field ``name`` as it stands"""
    return lambda: float(getattr(node, name))


def plan(node: Any) -> Optional[Plan]:
    """The plan for drawing a volume data node, or None while its voxels have not loaded"""
    voxels = getattr(node, 'voxels', None)
    channels = channels_of(voxels) if voxels and _is_3d(voxels) else 0
    if not channels:
        return None
    styles = node.renderStyle
    if isinstance(node, x3d.IsoSurfaceVolumeData):
        return _isosurface_plan(node, channels)
    if (isinstance(node, x3d.VolumeData) and _enabled(styles)
            and isinstance(styles, x3d.ProjectionVolumeStyle)):
        found = Plan('projection', channels, node=node)
        found.declare('projectionType', 'int', lambda: PROJECTIONS.get(str(styles.type), 0))
        found.declare('projectionThreshold', 'float', lambda: float(styles.intensityThreshold))
        return found
    found = Plan('composite', channels, node=node)
    builder = _Builder(found)
    if isinstance(node, x3d.SegmentedVolumeData):
        identifiers = node.segmentIdentifiers
        volume = _pixels(voxels)
        others = _pixels(identifiers) if identifiers and _is_3d(identifiers) else None
        found.segmented = (others is not None and volume is not None
                           and others.shape[:3] == volume.shape[:3])
        listed = list(styles)[:MAX_SEGMENTS] if found.segmented else list(styles)[:1]
        found.roots = [builder.add(style, channels) for style in listed]
        if found.segmented:
            found.texture('segments', 'volume', identifiers)
            found.declare('segmentsOff', 'uint', lambda: _segments_off(node.segmentEnabled), 8)
        if all(root < 0 for root in found.roots):
            found.roots = []
    else:
        root = builder.add(styles, channels)
        found.roots = [root] if root >= 0 else []
    if not found.roots:
        found.steps.append(Step('default', None, channels))
        found.roots = [len(found.steps) - 1]
    return found


def _segments_off(enabled: Any) -> np.ndarray:
    """``segmentEnabled`` as 256 bits, set for each segment not drawn"""
    bits = np.zeros(8, np.uint32)
    for index, value in enumerate(list(enabled)[:MAX_SEGMENTS]):
        if not value:
            bits[index >> 5] |= np.uint32(1 << (index & 31))
    return bits


def _isosurface_plan(node: Any, channels: int) -> Plan:
    found = Plan('isosurface', channels, node=node)
    builder = _Builder(found)
    roots = [builder.add(style, channels) for style in node.renderStyle]
    found.roots = []
    for root in roots:
        if root < 0:
            found.steps.append(Step('surface', None, channels))
            root = len(found.steps) - 1
        found.roots.append(root)
    if not found.roots:
        found.steps.append(Step('surface', None, channels))
        found.roots = [len(found.steps) - 1]
    count = len(found.roots)
    gradients = node.gradients
    if gradients and _is_3d(gradients) and channels_of(gradients) >= 3:
        found.texture('gradients', 'volume', gradients)
    found.gradient = True

    def surfaces() -> list[tuple[float, int]]:
        return isosurfaces(node.surfaceValues, node.contourStepSize, count)

    def values() -> np.ndarray:
        held = np.zeros(MAX_ISOSURFACES, np.float32)
        listed = surfaces()
        held[:len(listed)] = [value for value, _style in listed]
        return held

    def styles() -> np.ndarray:
        held = np.zeros(MAX_ISOSURFACES, np.int32)
        listed = surfaces()
        held[:len(listed)] = [style for _value, style in listed]
        return held
    found.declare('isoCount', 'int', lambda: len(surfaces()))
    found.declare('isoValues', 'float', values, MAX_ISOSURFACES)
    found.declare('isoStyles', 'int', styles, MAX_ISOSURFACES)
    found.declare('isoTolerance', 'float', lambda: float(node.surfaceTolerance))
    return found


# -- GLSL --------------------------------------------------------------------------


def _normal(step: Step, index: int) -> str:
    """GLSL setting ``n``, the surface normal the step reads, eye space"""
    if 'normals' in step.textures:
        return '    vec3 n = textureNormal(s%d_normals, s.tc);' % (index,)
    return '    vec3 n = s.normal;'


def _function(found: Plan, index: int) -> str:
    step = found.steps[index]
    kind = step.kind
    prefix = 's%d_' % (index,)
    body: list[str]
    if kind in ('default', 'surface'):
        body = ['    return c;']
    elif kind == 'opacity':
        raw = _raw('s.voxel', step.channels)
        if 'table' not in step.textures:
            body = ['    return vec4(s.voxel.rgb, %s.x);' % (raw,)]
        elif 'table3d' in [slot.kind for slot in found.textures
                           if slot.name == step.textures['table']]:
            body = ['    return textureLod(%stable, %s.xyz, 0.0);' % (prefix, raw)]
        else:
            body = ['    return textureLod(%stable, vec3(%s.xy, 0.5), 0.0);' % (prefix, raw)]
    elif kind == 'boundary':
        body = ['    return vec4(c.rgb, c.a * (%sretained + %sboundary'
                ' * pow(max(s.gradient, 1e-6), %sexponent)));' % (prefix, prefix, prefix)]
    elif kind == 'cartoon':
        body = [_normal(step, index),
                '    float facing = dot(n, s.V);',
                '    if (facing < 0.0) return vec4(c.rgb, 0.0);',
                '    float angle = acos(min(facing, 1.0));',
                '    int bin = min(int(angle / (0.5 * PI) * float(%ssteps)), %ssteps - 1);'
                % (prefix, prefix),
                '    vec4 colour = %spalette[bin];' % (prefix,),
                '    return vec4(colour.rgb, c.a * colour.a);']
    elif kind == 'composed':
        body = ['    vec4 g = c;']
        body += ['    g = style%d(g, s);' % (child,) for child in step.children]
        body.append('    return g;')
    elif kind == 'edge':
        body = [_normal(step, index),
                '    float facing = abs(dot(n, s.V));',
                '    if (facing >= %sthreshold) return c;' % (prefix,),
                '    return vec4(c.rgb * facing + %scolor * (1.0 - facing), c.a);' % (prefix,)]
    elif kind == 'silhouette':
        body = [_normal(step, index),
                '    float facing = abs(dot(n, s.V));',
                '    return vec4(c.rgb, c.a * (%sretained + %sboundary'
                ' * pow(max(1.0 - facing, 1e-6), %ssharpness)));' % (prefix, prefix, prefix)]
    elif kind == 'tone':
        body = [_normal(step, index),
                '    return vec4(toneMapped(n, s.position, %swarm, %scool), c.a);'
                % (prefix, prefix)]
    elif kind == 'shaded':
        has_material, lit = step.shape
        diffuse = prefix + 'diffuse' if has_material else 'c.rgb'
        body = ['    float opacity = c.a * %sopacity;' % (prefix,)]
        if not lit:
            body.append('    return vec4(%s, opacity);' % (diffuse,))
        else:
            body += [_normal(step, index),
                     '    vec3 lit = shadedLights(n, s, %s, %sambient * %s, %sspecular,'
                     ' %sshininess);' % (diffuse, prefix, diffuse, prefix, prefix),
                     '    return vec4(clamp(%semissive + lit, 0.0, 1.0), opacity);' % (prefix,)]
    elif kind == 'blended':
        functions, channels, normals = step.shape
        raw = _raw('b.voxel', channels)
        body = ['    VSample b = s;',
                '    b.voxel = textureLod(%svoxels, s.tc, 0.0);' % (prefix,)]
        if normals:
            body.append('    gradientOf(b, %svoxels);' % (prefix,))
        body.append('    vec4 blend = vec4(b.voxel.rgb, %s.x);' % (raw,))
        if step.second >= 0:
            body.append('    blend = style%d(blend, b);' % (step.second,))
        for which, function in enumerate(functions, 1):
            if function == 'TABLE':
                weight = 'textureLod(%sweightTable%d, vec3(c.a, blend.a, 0.5), 0.0).r' % (prefix, which)
            else:
                weight = _WEIGHTS[function]
                if '%d' in weight:
                    weight = weight % (index, which)
            body.append('    float w%d = %s;' % (which, weight))
        body.append('    return clamp(c * w1 + blend * w2, 0.0, 1.0);')
    else:  # pragma: no cover - every kind made above has GLSL
        raise ValueError(kind)
    return 'vec4 style%d(vec4 c, VSample s) {\n%s\n}' % (index, '\n'.join(body))


# -- the style nodes --------------------------------------------------------------


class BlendedVolumeStyle(x3d.BlendedVolumeStyle):
    """X3D's BlendedVolumeStyle: values the volume it styles is drawn by"""


class BoundaryEnhancementVolumeStyle(x3d.BoundaryEnhancementVolumeStyle):
    """X3D's BoundaryEnhancementVolumeStyle: values the volume it styles is drawn by"""


class CartoonVolumeStyle(x3d.CartoonVolumeStyle):
    """X3D's CartoonVolumeStyle: values the volume it styles is drawn by"""


class ComposedVolumeStyle(x3d.ComposedVolumeStyle):
    """X3D's ComposedVolumeStyle: values the volume it styles is drawn by"""


class EdgeEnhancementVolumeStyle(x3d.EdgeEnhancementVolumeStyle):
    """X3D's EdgeEnhancementVolumeStyle: values the volume it styles is drawn by"""


class OpacityMapVolumeStyle(x3d.OpacityMapVolumeStyle):
    """X3D's OpacityMapVolumeStyle: values the volume it styles is drawn by"""


class ProjectionVolumeStyle(x3d.ProjectionVolumeStyle):
    """X3D's ProjectionVolumeStyle: values the volume it styles is drawn by"""


class ShadedVolumeStyle(x3d.ShadedVolumeStyle):
    """X3D's ShadedVolumeStyle: values the volume it styles is drawn by"""


class SilhouetteEnhancementVolumeStyle(x3d.SilhouetteEnhancementVolumeStyle):
    """X3D's SilhouetteEnhancementVolumeStyle: values the volume it styles is drawn by"""


class ToneMappedVolumeStyle(x3d.ToneMappedVolumeStyle):
    """X3D's ToneMappedVolumeStyle: values the volume it styles is drawn by"""
