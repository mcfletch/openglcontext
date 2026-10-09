"""The programs' side of texture layers: units, uniforms and binds

A :class:`~OpenGLContext.scenegraph.texturelayers.LayerTable` says what a
draw's chain combines; :class:`TextureLayersMixin` gives it to whichever
program draws (the PBR program and the VRML97 one both include
``shaders/_layers_inc.glsl``). A program names its units in
:class:`LayerUnits`: the 2D slots, in order, and a unit each for the chain's
cube map and 3D texture where it has samplers for them.

Each 2D layer takes the next 2D slot, the first cube map layer the cube unit
and the first 3D layer the 3D unit. A layer with no unit left for it -- a
fifth 2D layer on a program of four slots, a second cube map, any cube map
on a program with no cube sampler -- and a layer whose texture has nothing
to draw yet is given no kind, which leaves it out of the chain; the first
case is reported once.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NamedTuple, Optional

import numpy as np
from OpenGL.GL import (
    GL_TEXTURE0, GL_TEXTURE_2D, glActiveTexture, glBindTexture, glUniform4fv, glUniform4iv,
)

from OpenGLContext.scenegraph.texturelayers import (
    COORD_GENERATED, KIND_2D, KIND_3D, KIND_CUBE, MAX_LAYERS, LayerTable,
)

__all__ = ['LayerUnits', 'PackedLayers', 'TextureLayersMixin', 'pack_layers', 'box_of']

log = logging.getLogger(__name__)

_reported: set[str] = set()


def _report(message: str) -> None:
    if message not in _reported:
        _reported.add(message)
        log.warning(message)


class LayerUnits(NamedTuple):
    """Where a program reads layer textures from"""

    #: The texture unit of each 2D slot, in slot order.
    flat: tuple[int, ...]
    #: The cube map unit, or None where the program has no cube sampler.
    cube: Optional[int] = None
    #: The 3D texture unit, or None where the program has no 3D sampler.
    volume: Optional[int] = None
    #: The shader's number for each 2D slot, where it is not the slot's place
    #: in :attr:`flat`.
    slots: tuple[int, ...] = ()


class PackedLayers(NamedTuple):
    """One draw's layer uniforms and the textures to bind for them"""

    #: How many layers the chain combines.
    layers: int
    info: np.ndarray        # (MAX_LAYERS, 4) int32
    rows: np.ndarray        # (3 * MAX_LAYERS, 4) float32
    parameters: np.ndarray  # (2 * MAX_LAYERS, 4) float32
    factor: tuple[float, float, float, float]
    #: (unit, GL target, texture name) for each layer that reads a texture.
    binds: tuple[tuple[int, int, int], ...]
    #: Whether a layer reads a generator, which needs the camera in the shape's space.
    generated: bool


def pack_layers(table: LayerTable, units: LayerUnits, mode: Any) -> PackedLayers:
    """``table`` as ``units`` lets a program read it, with each texture's GL object"""
    info = np.zeros((MAX_LAYERS, 4), np.int32)
    rows = np.zeros((3 * MAX_LAYERS, 4), np.float32)
    rows[0::3, 0] = rows[1::3, 1] = rows[2::3, 2] = 1.0
    parameters = np.zeros((2 * MAX_LAYERS, 4), np.float32)
    binds = []
    flat = cube = volume = 0
    generated = False
    for index, layer in enumerate(table.layers[:MAX_LAYERS]):
        kind = 0
        slot = 0
        tex = None
        if layer.source == 0:
            tex = layer.texture.cached(mode) if hasattr(layer.texture, 'cached') else None
        unit: Optional[int] = None
        if layer.kind == KIND_2D:
            if flat < len(units.flat):
                slot = units.slots[flat] if units.slots else flat
                unit = units.flat[flat]
                flat += 1
            else:
                _report('A MultiTexture has more 2D layers than the %d this renderer '
                        'reads at once; the rest are left out' % (len(units.flat),))
        elif layer.kind == KIND_CUBE:
            if units.cube is not None and not cube:
                unit, cube = units.cube, 1
            else:
                _report('A cube map layer is left out: the renderer reads one cube map a '
                        'draw, and only where it has a texture unit for it')
        elif layer.kind == KIND_3D:
            if units.volume is not None and not volume:
                unit, volume = units.volume, 1
            else:
                _report('A 3D texture layer is left out: the renderer reads one 3D texture '
                        'a draw, and only where it has a texture unit for it')
        if unit is not None and (layer.source != 0 or (tex is not None
                                                      and getattr(tex, 'texture', None))):
            kind = layer.kind
            if tex is not None and layer.source == 0:
                binds.append((unit, int(getattr(tex, 'target', GL_TEXTURE_2D)),
                              int(tex.texture)))
        elif layer.source != 0:
            kind = layer.kind
        generated = generated or bool(kind and layer.coordinate == COORD_GENERATED)
        info[index] = (
            kind | (layer.coordinate << 2) | ((layer.set & 1) << 5) | ((layer.generator & 15) << 6),
            layer.mode | (layer.alpha_mode << 5),
            layer.source | (layer.function << 2),
            slot)
        rows[3 * index:3 * index + 3] = layer.transform
        values = (tuple(layer.parameters) + (0.0,) * 8)[:8]
        parameters[2 * index] = values[:4]
        parameters[2 * index + 1] = values[4:]
    return PackedLayers(len(table.layers[:MAX_LAYERS]), info, rows, parameters, table.factor,
                        tuple(binds), bool(generated))


def box_of(geometry: Any, mode: Any) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(low corner, size) of a geometry's bounds in its own space; the unit cube without"""
    volume = None
    getter = getattr(geometry, 'boundingVolume', None)
    if getter is not None:
        try:
            volume = getter(mode)
        except Exception:
            volume = None
    try:
        points = np.asarray(volume.getPoints(), np.float64)[:, :3] if volume is not None else None
    except Exception:
        points = None
    if points is None or not len(points) or not np.all(np.isfinite(points)):
        return (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
    low, high = points.min(axis=0), points.max(axis=0)
    return tuple(float(v) for v in low), tuple(float(v) for v in high - low)


def _ints(location: int, value: Any) -> None:
    glUniform4iv(location, len(value) // 4, np.asarray(value, np.int32))


def _floats(location: int, value: Any) -> None:
    glUniform4fv(location, len(value) // 4, np.asarray(value, np.float32))


class TextureLayersMixin:
    """Setting a program's texture layer uniforms and binding their textures

    Mixed into the shader programs, which give :meth:`layer_units` and the
    uniform setters (``_set_uniform``, ``_set_uniform1i``, ...).
    """

    if TYPE_CHECKING:
        # What the program this is mixed into provides, declared for a checker.
        program: Optional[int]

        def _set_uniform(self, name: str, value: Any, program: Optional[int],
                         upload: Callable[[int, Any], None]) -> None: ...
        def _set_uniform1i(self, name: str, value: int, program: Optional[int] = None) -> None: ...
        def _set_uniform3f(self, name: str, value: Any, program: Optional[int] = None) -> None: ...
        def _set_uniform4f(self, name: str, value: Any, program: Optional[int] = None) -> None: ...

    def layer_units(self) -> LayerUnits:
        """Where this program reads layer textures from"""
        return LayerUnits(())

    def set_texture_layers(self, table: Optional[LayerTable], mode: Any = None,
                           geometry: Any = None, program: Any = None,
                           units: Optional[LayerUnits] = None) -> tuple[int, ...]:
        """Have the next draw combine ``table``'s layers, or none for None

        Binds each layer's texture on its unit and returns the units bound,
        so a caller binding other maps knows which it must leave alone.
        ``geometry`` gives the bounding box a 3D texture with no coordinates
        is read across; ``mode.matrix`` places the camera for a generator.
        ``units`` are this draw's, where they differ from :meth:`layer_units`.
        """
        target = program if program is not None else self.program
        if table is None or not table.layers:
            self._set_uniform1i('textureLayerCount', 0, target)
            return ()
        packed = pack_layers(table, units if units is not None else self.layer_units(), mode)
        self._set_uniform('textureLayer', tuple(int(v) for v in packed.info.ravel()),
                          target, _ints)
        self._set_uniform('textureLayerRows', tuple(float(v) for v in packed.rows.ravel()),
                          target, _floats)
        self._set_uniform('textureLayerParameter',
                          tuple(float(v) for v in packed.parameters.ravel()), target, _floats)
        self._set_uniform4f('textureLayerFactor', packed.factor, target)
        if table.needs_box:
            low, size = box_of(geometry, mode)
            self._set_uniform3f('textureBoxLow', low, target)
            self._set_uniform3f('textureBoxSize', size, target)
        if packed.generated:
            matrix = getattr(mode, 'matrix', None)
            if matrix is not None:
                try:
                    eye = np.linalg.inv(np.asarray(matrix, dtype=np.float64))[3, :3]
                except np.linalg.LinAlgError:
                    eye = np.zeros(3)
                self._set_uniform3f('texGenLocalEye',
                                    (float(eye[0]), float(eye[1]), float(eye[2])), target)
        for unit, texture_target, name in packed.binds:
            glActiveTexture(GL_TEXTURE0 + unit)
            glBindTexture(texture_target, name)
        glActiveTexture(GL_TEXTURE0)
        self._set_uniform1i('textureLayerCount', packed.layers, target)
        return tuple(unit for unit, _target, _name in packed.binds)

    def init_layer_samplers(self, program: Any) -> None:
        """Point a program's cube map and 3D layer samplers at their units, once"""
        units = self.layer_units()
        if units.cube is not None:
            self._set_uniform1i('textureLayerCube', units.cube, program)
        if units.volume is not None:
            self._set_uniform1i('textureLayer3D', units.volume, program)
        self._set_uniform1i('textureLayerCount', 0, program)
