"""Wavefront MTL material libraries read into :class:`MtlMaterial` records.

An ``.obj`` file names a library with ``mtllib`` and a material in it with
``usemtl``; this reads the library's text. It imports no scenegraph and no GL.
:mod:`OpenGLContext.loaders.objmaterials` turns the records into
``PhysicalMaterial`` nodes.

Statements read, keywords in any case:

- colours ``Ka``, ``Kd``, ``Ks``, ``Ke`` as one number (a grey), three numbers,
  or ``xyz`` and one to three CIE XYZ numbers (converted to linear sRGB);
- ``Ns`` shininess, ``d`` and ``Tr`` opacity and transparency (the later of
  the two wins), ``Ni`` optical density, ``illum``;
- the physically based extensions ``Pr``, ``Pm``, ``Ps``, ``Pc``, ``Pcr``,
  ``aniso`` and ``anisor``;
- maps: ``map_Kd``, ``map_Ka``, ``map_Ks``, ``map_Ke``, ``map_Ns``, ``map_d``,
  ``map_Bump`` (also ``map_bump`` and ``bump``), ``norm`` (also ``map_Kn``),
  ``disp``, ``decal``, ``refl``, ``map_Pr``, ``map_Pm``, ``map_Ps``,
  ``map_Pc``, ``map_Pcr``, ``map_aniso`` and ``map_anisor``, each with the
  options ``-s``, ``-o``, ``-bm``, ``-mm``, ``-clamp`` and ``-imfchan`` that
  precede the file name. A file name runs to the end of the line, so it may
  hold spaces.

A statement that cannot be read raises ``ValueError`` naming the file and the
line. Statements this reader does not use are counted in
:attr:`MtlLibrary.ignored`.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Optional, Union

from OpenGLContext.loaders.objfile import decode_text, logical_lines

__all__ = ['MtlLibrary', 'MtlMaterial', 'TextureMap', 'parse_mtl']

Colour = tuple[float, float, float]

#: Each map statement (lower case) and the channel it fills.
MAP_CHANNELS = {
    'map_kd': 'diffuse', 'map_ka': 'ambient', 'map_ks': 'specular', 'map_ke': 'emissive',
    'map_ns': 'shininess', 'map_d': 'opacity', 'map_bump': 'bump', 'bump': 'bump',
    'norm': 'normal', 'map_kn': 'normal', 'disp': 'displacement', 'decal': 'decal',
    'refl': 'reflection', 'map_pr': 'roughness', 'map_pm': 'metallic', 'map_ps': 'sheen',
    'map_pc': 'clearcoat', 'map_pcr': 'clearcoat_roughness', 'map_aniso': 'anisotropy',
    'map_anisor': 'anisotropy_rotation',
}

COLOUR_FIELDS = {'ka': 'ambient', 'kd': 'diffuse', 'ks': 'specular', 'ke': 'emissive'}
SCALAR_FIELDS = {
    'ns': 'shininess', 'ni': 'ior', 'pr': 'roughness', 'pm': 'metallic', 'ps': 'sheen',
    'pc': 'clearcoat', 'pcr': 'clearcoat_roughness', 'aniso': 'anisotropy',
    'anisor': 'anisotropy_rotation',
}

#: The options of a map statement that take one value this reader reads past.
_ONE_VALUE_OPTIONS = frozenset({'-blendu', '-blendv', '-cc', '-texres', '-type'})


@dataclass
class TextureMap:
    """A map statement: the file and the options given before it

    ``file`` uses ``/`` for separators. ``scale`` and ``offset`` are the ``-s``
    and ``-o`` triples, ``bump_multiplier`` is ``-bm``, ``base`` and ``gain`` are
    ``-mm``, ``clamp`` is ``-clamp on`` and ``channel`` is the ``-imfchan`` letter
    (empty where not given).
    """
    file: str
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    offset: tuple[float, float, float] = (0.0, 0.0, 0.0)
    bump_multiplier: float = 1.0
    base: float = 0.0
    gain: float = 1.0
    clamp: bool = False
    channel: str = ''


@dataclass
class MtlMaterial:
    """One ``newmtl`` block

    A field is None where the block did not state it. ``opacity`` is 1 for an
    opaque surface, whichever of ``d`` and ``Tr`` stated it. ``maps`` is keyed by
    channel: ``diffuse``, ``ambient``, ``specular``, ``emissive``, ``shininess``,
    ``opacity``, ``bump``, ``normal``, ``displacement``, ``decal``,
    ``reflection``, ``roughness``, ``metallic``, ``sheen``, ``clearcoat``,
    ``clearcoat_roughness``, ``anisotropy`` and ``anisotropy_rotation``.
    """
    name: str
    ambient: Optional[Colour] = None
    diffuse: Optional[Colour] = None
    specular: Optional[Colour] = None
    emissive: Optional[Colour] = None
    shininess: Optional[float] = None
    opacity: Optional[float] = None
    ior: Optional[float] = None
    illum: Optional[int] = None
    roughness: Optional[float] = None
    metallic: Optional[float] = None
    sheen: Optional[float] = None
    clearcoat: Optional[float] = None
    clearcoat_roughness: Optional[float] = None
    anisotropy: Optional[float] = None
    anisotropy_rotation: Optional[float] = None
    maps: dict[str, TextureMap] = field(default_factory=dict)


class MtlLibrary(dict[str, MtlMaterial]):
    """The materials of a library by name, in file order

    ``ignored`` counts the statements read past, by keyword.
    """

    def __init__(self) -> None:
        super().__init__()
        self.ignored: Counter[str] = Counter()


def parse_mtl(data: Union[bytes, str], name: str = 'mtl') -> MtlLibrary:
    """The materials a library file defines

    ``name`` is what an error message calls the file. A material defined twice
    is the later definition.
    """
    library = MtlLibrary()
    material: Optional[MtlMaterial] = None

    def error(number: int, message: str) -> ValueError:
        return ValueError('%s:%d: %s' % (name, number, message))

    for number, line in logical_lines(decode_text(data)):
        parts = line.split('#', 1)[0].split()
        if not parts:
            continue
        word = parts[0]
        key = word.lower()
        if key == 'newmtl':
            material = library[' '.join(parts[1:])] = MtlMaterial(' '.join(parts[1:]))
            continue
        if material is None:
            library.ignored['%s (before newmtl)' % word] += 1
            continue
        if key in COLOUR_FIELDS:
            colour = _colour(parts, number, name)
            if colour is None:
                library.ignored['%s spectral' % word] += 1
            else:
                setattr(material, COLOUR_FIELDS[key], colour)
        elif key in SCALAR_FIELDS:
            setattr(material, SCALAR_FIELDS[key], _number(parts, 1, number, name))
        elif key == 'd':
            material.opacity = _number(parts[:1] + [piece for piece in parts[1:] if piece != '-halo'],
                                       1, number, name)
        elif key == 'tr':
            material.opacity = 1.0 - _number(parts, 1, number, name)
        elif key == 'illum':
            material.illum = int(_number(parts, 1, number, name))
        elif key in MAP_CHANNELS:
            texture = _map(parts, library.ignored)
            if texture is not None:
                material.maps[MAP_CHANNELS[key]] = texture
        else:
            library.ignored[word] += 1
    return library


def _number(parts: list[str], index: int, number: int, name: str) -> float:
    """``parts[index]`` as a finite number, or ``ValueError`` naming the line"""
    if len(parts) <= index:
        raise ValueError('%s:%d: %s needs a number' % (name, number, parts[0]))
    try:
        value = float(parts[index])
    except ValueError:
        raise ValueError('%s:%d: cannot read %r as a number' % (name, number, parts[index])) from None
    if not math.isfinite(value):
        raise ValueError('%s:%d: %r is not a finite number' % (name, number, parts[index]))
    return value


def _colour(parts: list[str], number: int, name: str) -> Optional[Colour]:
    """A colour statement's value, or None for a spectral curve

    One number is a grey, three are red, green and blue, and ``xyz`` followed by
    one to three numbers is CIE XYZ. Two numbers, or a different count, is an
    error.
    """
    if len(parts) > 1 and parts[1].lower() == 'spectral':
        return None
    if len(parts) > 1 and parts[1].lower() == 'xyz':
        x = _number(parts, 2, number, name)
        y = _number(parts, 3, number, name) if len(parts) > 3 else x
        z = _number(parts, 4, number, name) if len(parts) > 4 else x
        return _from_xyz(x, y, z)
    values = [_number(parts, index, number, name) for index in range(1, min(len(parts), 4))]
    if len(values) == 1:
        return (values[0], values[0], values[0])
    if len(values) != 3:
        raise ValueError('%s:%d: %s needs one number or three, not %d'
                         % (name, number, parts[0], len(values)))
    return (values[0], values[1], values[2])


def _from_xyz(x: float, y: float, z: float) -> Colour:
    """CIE XYZ (D65) as linear sRGB, clipped to the gamut"""
    red = 3.2406 * x - 1.5372 * y - 0.4986 * z
    green = -0.9689 * x + 1.8758 * y + 0.0415 * z
    blue = 0.0557 * x - 0.2040 * y + 1.0570 * z
    return (min(max(red, 0.0), 1.0), min(max(green, 0.0), 1.0), min(max(blue, 0.0), 1.0))


def _numbers(parts: list[str], start: int, most: int) -> list[float]:
    """Up to ``most`` numbers from ``start``, stopping at the first that is not one"""
    found: list[float] = []
    for piece in parts[start:start + most]:
        try:
            value = float(piece)
        except ValueError:
            break
        if not math.isfinite(value):
            break
        found.append(value)
    return found


def _map(parts: list[str], ignored: Counter[str]) -> Optional[TextureMap]:
    """A map statement: its options, then the file name to the end of the line

    None where there is no file name.
    """
    texture = TextureMap(file='')
    position = 1
    while position < len(parts) and parts[position].startswith('-') and len(parts[position]) > 1 \
            and parts[position][1].isalpha():
        option = parts[position].lower()
        position += 1
        if option in ('-s', '-o', '-t'):
            values = _numbers(parts, position, 3)
            position += len(values)
            padded = tuple(values + [(1.0 if option == '-s' else 0.0)] * (3 - len(values)))
            if option == '-s':
                texture.scale = (padded[0], padded[1], padded[2])
            elif option == '-o':
                texture.offset = (padded[0], padded[1], padded[2])
        elif option == '-bm':
            values = _numbers(parts, position, 1)
            position += len(values)
            if values:
                texture.bump_multiplier = values[0]
        elif option == '-mm':
            values = _numbers(parts, position, 2)
            position += len(values)
            if len(values) == 2:
                texture.base, texture.gain = values
        elif option == '-clamp':
            if position < len(parts):
                texture.clamp = parts[position].lower() == 'on'
                position += 1
        elif option == '-imfchan':
            if position < len(parts):
                texture.channel = parts[position].lower()
                position += 1
        elif option in _ONE_VALUE_OPTIONS:
            position += 1
        else:
            ignored['%s %s' % (parts[0], parts[position - 1])] += 1
    texture.file = ' '.join(parts[position:]).replace('\\', '/')
    return texture if texture.file else None
