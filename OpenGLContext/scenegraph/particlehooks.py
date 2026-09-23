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
``density``
    Particles per second, burst and budget multiplied: more of the same effect.
any :class:`~OpenGLContext.scenegraph.particles.ParticleEmitter` field
    Set before ``scale`` and ``density`` are applied: ``{"color": [0.3, 0.6,
    1.0]}`` for a gas flame. A name that is not a field, or a value the field
    will not take, is logged and passed over.

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
from typing import Any, Dict, FrozenSet, List

import numpy as np
from vrml import protofunctions

from OpenGLContext.loaders.gltf import hooks
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.particles import PRESETS, ParticleEmitter

log = logging.getLogger(__name__)

__all__ = ['KINDS', 'AUTHORED', 'FIELDS', 'emitter_for', 'particle_hook',
           'advance']

#: What a document names these hooks, each the preset it starts from.
KINDS = ('fire', 'smoke', 'sparks')

#: Where an authored effect differs from the preset of the same name.
AUTHORED: Dict[str, Dict[str, Any]] = {
    'sparks': {'rate': 60.0, 'burst': 0},
}

#: The emitter fields a tag may set by name.
FIELDS: FrozenSet[str] = frozenset(
    spec.name for spec in protofunctions.getFields(ParticleEmitter)
    if not spec.name.startswith(' ') and spec.name != 'externalURL')

#: The fields ``scale`` multiplies: every length, and every length per second.
_LENGTHS = ('size', 'endSize', 'speed')

#: The fields ``density`` multiplies.
_COUNTS = ('burst', 'maxParticles')


def emitter_for(kind: str, params: Dict[str, Any],
                extent: float = 1.0) -> ParticleEmitter:
    """The emitter a tag of ``kind`` with ``params`` describes.

    ``extent`` is the tagged object's own scale, which multiplies the tag's
    ``scale``.
    """
    emitter = ParticleEmitter(**{**PRESETS[kind], **AUTHORED.get(kind, {})})
    for name, value in params.items():
        if name in ('scale', 'density'):
            continue
        if name not in FIELDS:
            log.warning('%r is not a particle emitter field; the %s tag passes '
                        'it over', name, kind)
            continue
        try:
            setattr(emitter, name, value)
        except (TypeError, ValueError) as error:
            log.warning('the %s tag sets %s to %r, which it will not take: %s',
                        kind, name, value, error)
    scale = _number(params, 'scale', kind) * extent
    for name in _LENGTHS:
        setattr(emitter, name, getattr(emitter, name) * scale)
    emitter.gravity = np.asarray(emitter.gravity, dtype='d') * scale
    density = _number(params, 'density', kind)
    emitter.rate = emitter.rate * density
    for name in _COUNTS:
        setattr(emitter, name, int(np.ceil(getattr(emitter, name) * density)))
    emitter.maxParticles = max(1, emitter.maxParticles)
    return emitter


def _number(params: Dict[str, Any], name: str, kind: str) -> float:
    """A positive multiplier from the tag, or 1 where it gives none it can use."""
    value = params.get(name, 1.0)
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = -1.0
    if number < 0.0:
        log.warning('the %s tag gives %s as %r, which is not a positive number; '
                    'it is taken as 1', kind, name, value)
        return 1.0
    return number


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
                                      _extent(ctx.world_matrix)))
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
