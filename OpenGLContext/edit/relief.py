"""Reading relief off a plan view.

A map lit from straight overhead is flat: every surface faces the light equally
and a ridge and a valley are the same colour. A map is *read*, so the ground is
shaded by which way it faces relative to a fixed low sun -- the cartographic
hillshade -- and a designer sees the shape of the land without a single shadow
crossing the line drawn on it.

The sun is a convention, not a light: it sits in the **north west** at 45
degrees, which is where every printed relief map has put it for a century.
Lighting relief from anywhere east of north makes hills read as hollows, and
the illusion is strong enough that a designer will draw a road along the wrong
side of a ridge.

The shading is a function of the surface normal, so it costs one dot product a
vertex and needs no shadow map, no second pass, and no light in the scenegraph.
"""
from __future__ import annotations

from typing import Any

import numpy as np

__all__ = ['DEFAULT_ALTITUDE', 'DEFAULT_AZIMUTH', 'DEFAULT_AMBIENT',
           'DEFAULT_EXAGGERATION', 'hillshade', 'light_vector', 'shade_colors',
           'steepen']

#: Where the sun sits: degrees clockwise from north, and degrees above the
#: horizon. North west at 45, the cartographic convention.
DEFAULT_AZIMUTH = 315.0
DEFAULT_ALTITUDE = 45.0

#: How much light reaches ground that faces away from the sun. A map has to
#: stay readable everywhere, so the shaded side of a hill is darker rather than
#: dark: nothing on it goes to black.
DEFAULT_AMBIENT = 0.35

#: How much steeper the land is made before it is lit. Country a road can be
#: built through is gentle -- a one-in-twenty slope is a hard climb for a car
#: and almost nothing to the eye -- so shading it honestly leaves a flat green
#: sheet. Every printed relief map of lowland does the same. The exaggeration is
#: in the *shading* only: the ground is drawn at the height it really is, and a
#: contour still says what that height is.
DEFAULT_EXAGGERATION = 4.0


def light_vector(azimuth: float = DEFAULT_AZIMUTH,
                 altitude: float = DEFAULT_ALTITUDE) -> np.ndarray:
    """Which way the sun lies, as a unit vector towards it.

    ``azimuth`` is degrees clockwise from north and ``altitude`` degrees above
    the horizon. World axes: ``+x`` east, ``+y`` up, ``-z`` north, which is
    what a plan view draws with north up the screen.
    """
    turn = np.radians(float(azimuth))
    up = np.radians(float(altitude))
    flat = np.cos(up)
    return np.array([flat * np.sin(turn), np.sin(up), -flat * np.cos(turn)],
                    dtype='d')


def steepen(normals: Any, exaggeration: float = DEFAULT_EXAGGERATION
            ) -> np.ndarray:
    """The same surfaces, leaned over as if the land were taller.

    A surface normal is ``(-dh/dx, 1, -dh/dz)`` up to scale, so multiplying the
    height by a factor multiplies the two horizontal parts by it. Flat ground
    has none, and stays flat however much the land around it is exaggerated.
    """
    facing = np.asarray(normals, dtype='d').reshape(-1, 3).copy()
    factor = float(exaggeration)
    if factor != 1.0:
        upright = np.where(np.abs(facing[:, 1]) > 1e-9, facing[:, 1], 1e-9)
        facing[:, 0] *= factor / np.abs(upright)
        facing[:, 2] *= factor / np.abs(upright)
        facing[:, 1] = np.sign(upright)
    length = np.linalg.norm(facing, axis=1, keepdims=True)
    return facing / np.maximum(length, 1e-9)


def hillshade(normals: Any, azimuth: float = DEFAULT_AZIMUTH,
              altitude: float = DEFAULT_ALTITUDE,
              exaggeration: float = 1.0) -> np.ndarray:
    """How much of the sun each surface takes, from 0 (turned away) to 1.

    The cosine of the angle between the surface and the sun, clamped: ground
    facing away from a low sun would otherwise take a negative amount of it and
    come out brighter the further round it turned.
    """
    lit: np.ndarray = np.clip(steepen(normals, exaggeration)
                              @ light_vector(azimuth, altitude), 0.0, 1.0)
    return lit


def shade_colors(colors: Any, normals: Any,
                 azimuth: float = DEFAULT_AZIMUTH,
                 altitude: float = DEFAULT_ALTITUDE,
                 ambient: float = DEFAULT_AMBIENT,
                 exaggeration: float = DEFAULT_EXAGGERATION) -> np.ndarray:
    """Ground colours with the relief shaded into them.

    ``colors`` is ``(N,3)`` or ``(N,4)``; an alpha channel is carried through
    untouched, since how transparent the ground is has nothing to do with which
    way it faces. ``ambient`` is the floor, so the shaded side of a hill stays
    legible -- a map with an unreadable quarter is not a map.

    The result is what a mesh drawn *unlit* wants: the shading is in the
    vertex colours, so a plan view needs no lights and casts no shadows across
    the line the designer is reading.
    """
    tint = np.asarray(colors, dtype='f')
    lit = hillshade(normals, azimuth, altitude, exaggeration)
    scale = (float(ambient) + (1.0 - float(ambient)) * lit).astype('f')
    shaded: np.ndarray = tint.copy()
    shaded[:, :3] = np.clip(tint[:, :3] * scale[:, None], 0.0, 1.0)
    return shaded
