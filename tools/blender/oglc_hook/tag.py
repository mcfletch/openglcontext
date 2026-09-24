"""What the panel says, as the block that goes in the file.

The rules for turning a material's or an object's hook settings into an
``OGLC_hook`` payload, with no Blender in them: the Blender half reads the
properties off a datablock and hands them here, the exporter half puts what
comes back in the glTF, and a test drives this module directly.

``settings`` is anything with the panel's properties on it -- a Blender
``PropertyGroup`` at export time. The vocabularies below are the engine's: the
kinds it ships, the five water styles, the three media, the two ways to shade
a surface, and what a mirror is worth.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

__all__ = ['EXTENSION', 'WATER', 'MIRROR', 'MIRROR_PARAMETERS', 'EFFECTS',
           'KINDS', 'STYLES', 'MEDIA',
           'SHADING', 'DEFAULTS', 'parameters', 'hook_block', 'preview',
           'misplaced', 'suggestions']

#: The key the block is written under, as an ``extensions`` block on a material
#: or a node. The loader reads the same word out of ``extras``, which is what a
#: custom property becomes, so a file may carry either.
EXTENSION = 'OGLC_hook'

#: The kind the panel has water fields for. It belongs on a material: it is
#: what a surface is made of.
WATER = 'water'

#: The kind the panel has mirror fields for. It belongs on either holder: on a
#: material the surface's own shading is applied to its reflection, and on an
#: object every surface of it shows the reflection alone.
MIRROR = 'mirror'

#: The particle effects, which belong on an object: each stands where the
#: object stands. The panel has the same two fields for all three.
EFFECTS: Dict[str, str] = {
    'fire': 'A flame, standing where the object stands',
    'smoke': 'A column of smoke, rising from the object',
    'sparks': 'A fountain of sparks, thrown up from the object',
}

#: Every kind the engine ships, offered as the kind field is typed. A game's
#: own kinds are typed in full.
KINDS: Dict[str, str] = {
    WATER: 'A surface that moves as water, and a body you can be inside of',
    MIRROR: 'A flat surface that reflects the scene in front of it',
    **EFFECTS,
}

#: Where each of the engine's kinds is read. On the other holder the loader
#: passes it over, so the panel says so.
_BELONGS: Dict[str, str] = {WATER: 'material', **{kind: 'object' for kind in EFFECTS}}
_HOLDER = {'material': 'a material', 'object': 'an object'}

#: How water moves, and what each motion is.
STYLES: Dict[str, str] = {
    'still': 'A pond: the ripple is in the normals and the surface holds level',
    'breeze': 'A pond or small lake seen from its bank: wind-ruffled, fine waves',
    'flowing': 'A river: a long swell carried in one direction',
    'choppy': 'Open water with a wind on it',
    'lake': 'Open water seen from a distance: a slow, long, low swell',
}

#: What being inside the body is like.
MEDIA: Dict[str, str] = {
    'water': 'Water: you can see and it does not hurt',
    'slime': 'Slime: close, green and harmful',
    'lava': 'Lava: opaque, and harmful quickly',
}

#: What shades the surface.
SHADING: Dict[str, str] = {
    'keep': "The file's own material, so what was authored is what is drawn",
    'engine': "The engine's water material",
}

#: What the loader assumes when a parameter is absent. A panel left at one of
#: these writes nothing for it, so a tag says what the artist changed.
DEFAULTS: Dict[str, Any] = {
    'style': 'still', 'material': 'keep', 'medium': 'water', 'depth': 0.0,
    'scale': 1.0, 'density': 1.0,
    'mirror_scale': 0.5, 'interval': 3, 'priority': 1.0, 'distortion': 0.0,
    'reflectance': 0.97,
}

#: The panel's mirror fields, and the parameter each is written as. The
#: resolution is its own field because ``scale`` is already the effects'.
MIRROR_PARAMETERS: Dict[str, str] = {
    'mirror_scale': 'scale', 'interval': 'interval', 'priority': 'priority',
    'distortion': 'distortion', 'reflectance': 'reflectance',
}


def _typed(value: Any) -> float:
    """A float as it was typed: Blender stores float properties in single
    precision, and seven significant digits is all that holds."""
    return float('%.7g' % float(value))


def parameters(text: Any) -> Dict[str, Any]:
    """The JSON object in the parameters field, or ``{}`` where it is blank.

    Raises :class:`ValueError` with what is wrong with it, which the panel
    draws under the field and the exporter logs.
    """
    written = str(text or '').strip()
    if not written:
        return {}
    try:
        value = json.loads(written)
    except json.JSONDecodeError as error:
        raise ValueError('The hook parameters are not JSON: %s' % (error,)) from error
    if not isinstance(value, dict):
        raise ValueError(
            'The hook parameters are a JSON object naming each parameter, like '
            '{"level": 12.5}; this one is %s' % (type(value).__name__,))
    return value


def hook_block(settings: Any) -> Optional[Dict[str, Any]]:
    """The ``OGLC_hook`` payload these settings ask for, or None for no tag.

    The parameters field is merged last, so it is the way to reach a parameter
    the panel has no field for -- and to override one it does.
    """
    if not getattr(settings, 'enabled', False):
        return None
    kind = str(getattr(settings, 'kind', '') or '').strip()
    if not kind:
        return None
    named = kind.lower()
    if named == WATER:
        params = _water_parameters(settings)
    elif named in EFFECTS:
        params = _effect_parameters(settings)
    elif named == MIRROR:
        params = _mirror_parameters(settings)
    else:
        params = {}
    written = parameters(getattr(settings, 'parameters', ''))
    written.pop('kind', None)
    params.update(written)
    return {'kind': kind, **params}


def _water_parameters(settings: Any) -> Dict[str, Any]:
    """The four water fields, less the ones still saying what the loader assumes.

    ``style`` is written whatever it says: it is the choice the panel is there
    to make, and a file that names it reads as deliberate rather than defaulted.
    """
    style = str(getattr(settings, 'style', '') or '').strip().lower()
    params: Dict[str, Any] = {'style': style or DEFAULTS['style']}
    shading = str(getattr(settings, 'material', '') or '').strip().lower()
    if shading and shading != DEFAULTS['material']:
        params['material'] = shading
    medium = str(getattr(settings, 'medium', '') or '').strip().lower()
    if medium and medium != DEFAULTS['medium']:
        params['medium'] = medium
    depth = _typed(getattr(settings, 'depth', 0.0) or 0.0)
    if depth > 0.0:
        params['depth'] = depth
    return params


def _effect_parameters(settings: Any) -> Dict[str, Any]:
    """``scale`` and ``density``, where either differs from 1."""
    params: Dict[str, Any] = {}
    for name in ('scale', 'density'):
        value = _typed(getattr(settings, name, DEFAULTS[name]))
        if value != DEFAULTS[name]:
            params[name] = value
    return params


def _mirror_parameters(settings: Any) -> Dict[str, Any]:
    """The mirror fields that differ from what the loader assumes."""
    params: Dict[str, Any] = {}
    for name, written in MIRROR_PARAMETERS.items():
        value = getattr(settings, name, DEFAULTS[name])
        value = int(value) if name == 'interval' else _typed(value)
        if value != DEFAULTS[name]:
            params[written] = value
    return params


def misplaced(kind: Any, on: str) -> str:
    """What to tell the artist when ``kind`` is on the holder the loader ignores.

    ``on`` is ``'material'`` or ``'object'``. Empty where the kind belongs
    there, and for a kind the engine does not ship, whose home is its game's
    business.
    """
    belongs = _BELONGS.get(str(kind or '').strip().lower())
    if belongs is None or belongs == on:
        return ''
    return '%s is read from %s, not from %s' % (
        str(kind).strip(), _HOLDER[belongs], _HOLDER[on])


def suggestions(typed: Any) -> List[str]:
    """The engine's kinds that begin with what has been typed, in order."""
    start = str(typed or '').strip().lower()
    return sorted(kind for kind in KINDS if kind.startswith(start))


def preview(block: Optional[Dict[str, Any]]) -> str:
    """One line saying what goes in the file, for the panel to draw."""
    if not block:
        return ''
    return '%s: %s' % (EXTENSION, json.dumps(block, sort_keys=True))
