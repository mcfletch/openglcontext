"""Deciding which ground material shows where.

A :class:`~OpenGLContext.scenegraph.terrain.splat.SplatTerrain` blends up to four
detail materials per pixel by an RGBA *control map*: red is how much of the first
layer shows there, green the second, and so on. Painting one is how a landscape
artist works. Deriving one from the land is how a generated world gets its
ground, and that is what this is.

A :class:`LayerRule` says where a layer belongs -- an elevation band, a slope
band, and how hard it pushes -- and :func:`control_map` turns a height field and
a list of rules into the image. Anything the rules cannot know about is
``painted`` over the top: a road's corridor, a lake bed, a clearing.

The rules are deliberately about *the land* rather than about noise: grass on the
flat, rock where it is too steep for soil to stay, shingle at the waterline. A
map that reads the ground stays right when the ground changes, which is what a
generated or edited landscape does.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from PIL import Image

if TYPE_CHECKING:
    from OpenGLContext.scenegraph.terrain.heightfield import HeightField

__all__ = ['LayerRule', 'control_map', 'MAXIMUM_LAYERS']

#: How many layers a control map can carry: one per channel of an RGBA image,
#: which is what the splat shader samples.
MAXIMUM_LAYERS = 4

#: How wide a band's edges are by default, in the band's own units. A hard edge
#: between two ground materials reads as a painted line rather than as ground.
HEIGHT_FEATHER = 25.0
SLOPE_FEATHER = 0.12


@dataclass
class LayerRule:
    """Where one splat layer shows.

    ``height`` is the world elevation band it belongs in, in metres, and
    ``slope`` the steepness band, as rise over run -- so ``slope=(0.6, 20.0)``
    is rock on anything past about thirty degrees. Both default to everywhere.

    ``feather`` softens the band's edges, in metres for the height band; the
    slope band gets its own proportionate softening. ``weight`` is how hard the
    layer pushes where it does apply, so two layers that both belong somewhere
    share it in proportion.
    """

    height: tuple[float, float] = (-1.0e9, 1.0e9)
    slope: tuple[float, float] = (0.0, 1.0e9)
    weight: float = 1.0
    feather: float = HEIGHT_FEATHER

    def strength(self, height: np.ndarray, slope: np.ndarray) -> np.ndarray:
        """How much of this layer shows at each sample of the land."""
        found: np.ndarray = self.weight * (
            _band(height, self.height, self.feather)
            * _band(slope, self.slope, SLOPE_FEATHER))
        return found


def control_map(field: "HeightField", rules: Sequence[LayerRule],
                size: int = 512,
                painted: Optional[Sequence[tuple[int, Any]]] = None) -> Image.Image:
    """An RGBA control map for ``field``, from what the rules say about the land.

    ``size`` is the map's resolution, which need not match the height field's:
    the control map is sampled by world position and is usually the coarser of
    the two, since where the ground changes material is a broader thing than
    where it changes height.

    ``painted`` is a sequence of ``(layer, mask)`` pairs -- a ``(size, size)``
    array from 0 to 1 -- forcing a layer where the rules cannot know to. Each is
    applied in turn, taking that fraction of the pixel away from everything else
    and giving it to that layer, so a corridor at 1.0 is entirely its layer and
    the weights still add to one.
    """
    if not rules:
        raise ValueError("a control map needs at least one layer")
    if len(rules) > MAXIMUM_LAYERS:
        raise ValueError("a control map carries at most %d layers, not %d"
                         % (MAXIMUM_LAYERS, len(rules)))
    axis = np.linspace(-field.extent / 2.0, field.extent / 2.0, int(size))
    x, z = np.meshgrid(axis, axis)
    height = np.asarray(field.sample(x, z), dtype='d')
    slope = np.asarray(field.slope(x, z), dtype='d')

    weights = np.stack([rule.strength(height, slope) for rule in rules], axis=-1)
    total = weights.sum(axis=-1, keepdims=True)
    # Ground no rule wants still has to be made of something, and the first
    # layer is the one a caller lists first for exactly that reason.
    barren = total[..., 0] <= 0.0
    weights[barren] = 0.0
    weights[barren, 0] = 1.0
    total = np.where(total > 0.0, total, 1.0)
    weights = weights / total

    for layer, mask in painted or ():
        if not 0 <= layer < len(rules):
            raise ValueError("no layer %d to paint: there are %d"
                             % (layer, len(rules)))
        cover = np.clip(np.asarray(mask, dtype='d'), 0.0, 1.0)
        if cover.shape != (size, size):
            raise ValueError("a mask for a %dx%d map cannot be %r"
                             % (size, size, (cover.shape,)))
        weights *= (1.0 - cover)[..., None]
        weights[..., layer] += cover

    channels = np.zeros((int(size), int(size), MAXIMUM_LAYERS), dtype='d')
    channels[..., :len(rules)] = weights
    return Image.fromarray(
        np.clip(np.rint(channels * 255.0), 0, 255).astype(np.uint8), mode='RGBA')


def _band(values: np.ndarray, span: tuple[float, float],
          feather: float) -> np.ndarray:
    """1 inside a band, 0 outside it, and a ramp of ``feather`` between.

    Feathering only where the band actually ends: a rule reaching to the
    horizon should not fade out somewhere near it.
    """
    low, high = float(span[0]), float(span[1])
    width = max(float(feather), 1e-9)
    rising = np.clip((values - low) / width + 1.0, 0.0, 1.0)
    falling = np.clip((high - values) / width + 1.0, 0.0, 1.0)
    return np.asarray(rising * falling, dtype='d')
