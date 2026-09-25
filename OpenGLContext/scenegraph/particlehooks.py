"""Fire, smoke and sparks an artist placed in a model: three ``OGLC_hook`` kinds.

An object in a glTF tagged with one of these kinds loads with a
:class:`~OpenGLContext.scenegraph.particles.ParticleEmitter` standing where the
object stands (:mod:`OpenGLContext.loaders.gltf.hooks`). In Blender that is an
empty, or the brazier mesh itself, with a custom property or the add-on's
panel on the *object*:

    OGLC_hook = {"kind": "fire", "scale": 2.0}

The kind names a :data:`~OpenGLContext.scenegraph.particles.PRESETS` entry and
the rest are optional:

``scale``
    Lengths multiplied: the size of each particle at birth and death, the speed
    it is thrown at and the gravity bending it, so a flame of scale 2 is the
    same flame twice as tall over the same lifetime. The object's own scale
    multiplies it too, which is how an artist resizes one in the viewport.
    At most :data:`MULTIPLIER_MAXIMUM`, the object's scale included.
``density``
    Particles per second, burst and budget multiplied: more of the same effect.
    At most :data:`MULTIPLIER_MAXIMUM`.
a :class:`~OpenGLContext.scenegraph.particles.ParticleEmitter` field
    Any of :data:`FIELDS`, set before ``scale`` and ``density`` are applied:
    ``{"color": [0.3, 0.6, 1.0]}`` for a gas flame. A name that is not one of
    them, or a value the field cannot take, is logged and passed over.
    Numbers are held to :data:`RANGES`, and so is each field after ``scale``
    and ``density`` have multiplied it, so a file cannot make the particle
    pool larger than ``maxParticles``' declared maximum of 20000.
``texture``
    A sprite image, named relative to the document. It is resolved through
    the document's :class:`~OpenGLContext.loaders.resolver.Resolver`, which
    refuses a name outside the document's directory; a document loaded from
    bytes or from a URL has no sprite, and its particles are soft dots.

The tag belongs on an object. A material has no single place for a flame to
stand, so a material carrying one of these kinds loads as it stands.

``sparks`` in the presets is a single burst, which is what a game firing it on
an impact wants; a world has nobody to fire it, so an authored ``sparks`` is a
steady fountain unless the tag says otherwise.

Each emitter steps itself on the engine clock as it is drawn.
:meth:`~OpenGLContext.loaders.gltf.scene.GLTFScene.advance` reports whether
any is still emitting or has particles in the air, which is what keeps a viewer
drawing.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import numpy as np

from OpenGLContext.loaders.documentvalues import DocumentValues, JSONObject, bounded
from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.particles import PRESETS, ParticleEmitter

log = logging.getLogger(__name__)

__all__ = ['KINDS', 'AUTHORED', 'FIELDS', 'RANGES', 'MULTIPLIER_MAXIMUM',
           'emitter_for', 'particle_hook', 'advance']

#: What a document names these hooks, each the preset it starts from.
KINDS = ('fire', 'smoke', 'sparks')

#: Where an authored effect differs from the preset of the same name.
AUTHORED: Dict[str, Dict[str, Any]] = {
    'sparks': {'rate': 60.0, 'burst': 0},
}

_HINTS: Dict[str, Any] = ParticleEmitter.UI_HINTS
_BUDGET = int(_HINTS['maxParticles']['maximum'])


def _hinted(name: str) -> Tuple[Optional[float], Optional[float]]:
    return _HINTS[name]['minimum'], _HINTS[name]['maximum']


#: The number fields a tag may set, and the range each is held to,
#: ``(minimum, maximum)`` with None for an open end. The field's own
#: ``UI_HINTS`` range where it declares one; a burst is held to the pool's
#: largest budget, and the seed to what an ``SFInt32`` holds.
RANGES: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    **{name: _hinted(name) for name in ('rate', 'maxParticles', 'lifetime',
                                        'speed', 'spread', 'drag', 'size',
                                        'endSize')},
    'burst': (0, _BUDGET),
    'seed': (-1, 2 ** 31 - 1),
    'lifetimeVariation': (0.0, None), 'speedVariation': (0.0, None),
    'sizeVariation': (0.0, None), 'spin': (None, None),
    'spinVariation': (0.0, None), 'alpha': (0.0, 1.0), 'endAlpha': (0.0, 1.0),
}

#: The fields that are whole numbers.
_WHOLE = frozenset(('burst', 'maxParticles', 'seed'))
#: The fields that are three numbers.
_VECTORS = ('direction', 'gravity', 'color', 'endColor')
#: The fields that are true or false.
_FLAGS = ('worldSpace', 'enabled', 'burstOnStart')

#: The emitter fields a tag may set by name. ``texture`` names a file, which
#: is read beside the document only; ``externalURL`` is not authorable.
FIELDS: FrozenSet[str] = frozenset(
    (*RANGES, *_VECTORS, *_FLAGS, 'blending', 'texture'))

#: The largest ``scale`` or ``density`` a tag may give, after the tagged
#: object's own scale multiplies ``scale``.
MULTIPLIER_MAXIMUM = 100.0

#: The fields ``scale`` multiplies: every length, and every length per second.
_LENGTHS = ('size', 'endSize', 'speed')

#: The fields ``density`` multiplies.
_COUNTS = ('burst', 'maxParticles')


def emitter_for(kind: str, params: JSONObject, extent: float = 1.0,
                values: Optional[DocumentValues] = None,
                resolver: Any = None) -> ParticleEmitter:
    """The emitter a tag of ``kind`` with ``params`` describes.

    ``extent`` is the tagged object's own scale, which multiplies the tag's
    ``scale``. Each value is read through ``values`` and held to
    :data:`RANGES`, and so is each field once ``scale`` and ``density`` have
    multiplied it. ``resolver`` is the document's
    :class:`~OpenGLContext.loaders.resolver.Resolver`, which a ``texture`` is
    resolved through; without one, a ``texture`` is passed over.
    """
    values = values if values is not None else DocumentValues(logger=log)
    emitter = ParticleEmitter(**{**PRESETS[kind], **AUTHORED.get(kind, {})})
    for name, raw in params.items():
        if name in ('scale', 'density'):
            continue
        if name not in FIELDS:
            values.warn('%r is not a particle emitter field a %s tag may set; '
                        'it is passed over' % (name, kind))
            continue
        setattr(emitter, name, _read(emitter, name, raw, kind, values, resolver))
    scale = bounded(_multiplier(params, 'scale', kind, values) * extent, 1.0,
                    0.0, MULTIPLIER_MAXIMUM)
    for name in _LENGTHS:
        setattr(emitter, name, _held(name, getattr(emitter, name) * scale))
    emitter.gravity = np.asarray(emitter.gravity, dtype='d') * scale
    density = _multiplier(params, 'density', kind, values)
    emitter.rate = _held('rate', emitter.rate * density)
    for name in _COUNTS:
        setattr(emitter, name,
                int(_held(name, math.ceil(getattr(emitter, name) * density))))
    emitter.maxParticles = max(1, emitter.maxParticles)
    return emitter


def _read(emitter: ParticleEmitter, name: str, raw: object, kind: str,
          values: DocumentValues, resolver: Any) -> Any:
    """Field ``name`` of a tag of ``kind``, read from ``raw``.

    Whatever ``raw`` cannot be is the value ``emitter`` already holds.
    """
    what = 'the %s %s' % (kind, name)
    current = getattr(emitter, name)
    if name in RANGES:
        minimum, maximum = RANGES[name]
        if name in _WHOLE:
            return values.integer(raw, int(current), what,
                                  minimum=_whole(minimum), maximum=_whole(maximum))
        return values.number(raw, float(current), what, minimum=minimum,
                             maximum=maximum)
    if name in _VECTORS:
        return values.vector(raw, tuple(float(v) for v in current), what)
    if name in _FLAGS:
        return values.flag(raw, bool(current), what)
    if name == 'blending':
        return values.choice(raw, str(current), what,
                             _HINTS['blending']['options'])
    return _sprite(raw, what, values, resolver)


def _whole(bound: Optional[float]) -> Optional[int]:
    return None if bound is None else int(bound)


def _held(name: str, value: float) -> float:
    """``value`` within field ``name``'s range."""
    minimum, maximum = RANGES[name]
    if minimum is not None:
        value = max(value, minimum)
    if maximum is not None:
        value = min(value, maximum)
    return value


def _multiplier(params: JSONObject, name: str, kind: str,
                values: DocumentValues) -> float:
    """A non-negative multiplier from the tag, or 1 where it gives none it can use."""
    raw = params.get(name, 1.0)
    what = 'the %s %s' % (kind, name)
    number = values.number(raw, 1.0, what, maximum=MULTIPLIER_MAXIMUM)
    if number < 0.0 or raw is None:
        values.warn('%s is %r, which is not a positive number; it is taken as 1'
                    % (what, raw))
        return 1.0
    return number


def _sprite(raw: object, what: str, values: DocumentValues, resolver: Any) -> str:
    """A ``texture`` the document names, as a path beside the document, or ''.

    Only a document read from a directory has a sprite: the name is resolved
    through the document's resolver, which refuses anything outside that
    directory. A document read from bytes or from a URL has no directory to
    read beside, and its sprite is passed over.
    """
    if raw in (None, ''):
        return ''
    if not isinstance(raw, str):
        values.warn('%s is %r, which is not a file name; it is passed over'
                    % (what, raw))
        return ''
    if resolver is None or getattr(resolver, 'base_url', None) is not None \
            or getattr(resolver, 'base_dir', None) is None:
        values.warn('%s is %r; a sprite is read only from beside a document '
                    'loaded from a file, and this one is passed over' % (what, raw))
        return ''
    try:
        return str(resolver.resolve(raw))
    except (IOError, OSError, ValueError) as error:
        values.warn('%s is %r, which is refused: %s' % (what, raw, error))
        return ''


def _extent(world: Any) -> float:
    """The uniform scale a world matrix applies: the cube root of its volume."""
    if world is None:
        return 1.0
    volume = abs(float(np.linalg.det(np.asarray(world, dtype='d')[:3, :3])))
    return volume ** (1.0 / 3.0) if volume > 0.0 else 1.0


def particle_hook(ctx: "hooks.HookContext") -> Any:
    """Stand an emitter under a tagged object, beside whatever it already holds."""
    if ctx.at != 'node':
        log.debug('a %s tag on a material has no place to stand; it is loaded '
                  'as it stands', ctx.kind)
        return None
    emitter = ctx.collect(emitter_for(ctx.kind, ctx.params,
                                      _extent(ctx.world_matrix),
                                      values=ctx.values, resolver=ctx.resolver))
    if not ctx.children:
        return emitter, False
    return Group(children=[*ctx.children, emitter]), False


def advance(emitters: List[ParticleEmitter], when: float) -> bool:
    """Whether any emitter is emitting or has particles in the air.

    Each steps itself on the engine clock as it is drawn, so ``when`` is not
    read.
    """
    return any(emitter.enabled or emitter.particleCount for emitter in emitters)


for _kind in KINDS:
    hooks.register(_kind, particle_hook, advance=advance)
