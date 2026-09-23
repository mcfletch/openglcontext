"""What the panel says, as the block that goes in the file.

The rules for turning a material's or an object's hook settings into an
``OGLC_hook`` payload, with no Blender in them: the Blender half reads the
properties off a datablock and hands them here, the exporter half puts what
comes back in the glTF, and a test drives this module directly.

``settings`` is anything with the panel's properties on it -- a Blender
``PropertyGroup`` at export time. The vocabularies below are the engine's:
the four water styles, the three media, and the two ways to shade a surface.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

__all__ = ['EXTENSION', 'WATER', 'STYLES', 'MEDIA', 'SHADING', 'DEFAULTS',
           'parameters', 'hook_block', 'preview']

#: The key the block is written under, as an ``extensions`` block on a material
#: or a node. The loader reads the same word out of ``extras``, which is what a
#: custom property becomes, so a file may carry either.
EXTENSION = 'OGLC_hook'

#: The kind the panel has fields for. Every other kind is named in the ``kind``
#: field and parameterised by the JSON object beside it.
WATER = 'water'

#: How water moves, and what each motion is.
STYLES: Dict[str, str] = {
    'still': 'A pond: the ripple is in the normals and the surface holds level',
    'flowing': 'A river: a long swell carried in one direction',
    'choppy': 'Open water with a wind on it',
    'lake': 'A sheltered lake: a slow, shallow swell',
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
}


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
    params = _water_parameters(settings) if kind.lower() == WATER else {}
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
    depth = float(getattr(settings, 'depth', 0.0) or 0.0)
    if depth > 0.0:
        params['depth'] = depth
    return params


def preview(block: Optional[Dict[str, Any]]) -> str:
    """One line saying what goes in the file, for the panel to draw."""
    if not block:
        return ''
    return '%s: %s' % (EXTENSION, json.dumps(block, sort_keys=True))
