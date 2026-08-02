"""``OMI_environment_sky``: a document's sky, as a ``Background`` node.

The extension does not ship a sky; it *describes* one, and three of its four
descriptions are of a background OpenGLContext already draws:

======================  ==========================================================
``gradient``            :class:`~OpenGLContext.scenegraph.background.Background`
                        -- the VRML97 gradient sphere, as sampled colour stops.
``panorama`` equirect   :class:`~OpenGLContext.scenegraph.hdrbackground.HDRBackground`,
                        which also registers the panorama as the IBL environment,
                        so metals reflect the sky drawn behind them.
``panorama`` cubemap    :class:`~OpenGLContext.scenegraph.cubebackground.CubeBackground`.
``plain``               :class:`~OpenGLContext.scenegraph.simplebackground.SimpleBackground`.
``physical``            Nothing yet: an analytic Rayleigh/Mie scattering skydome
                        is the one type that is a *renderer* rather than a
                        translation.  Read and reported, so a caller can say why
                        the sky is missing.
======================  ==========================================================

So this module is a translation and nothing more.  It reads the document's
``skies[]``, resolves the index the active scene names, and builds the node --
which the scene builder hangs off the root, where the ordinary Background pass
finds and binds it.

Two things the extension leaves to the consumer are **not** done here and are
worth knowing about:

- The **sun tint** the gradient sky's ``sunAngleMax``/``sunCurve`` describe.  It
  is a disc around the scene's directional light, and so varies with azimuth;
  the gradient sphere's stops are elevation-only and cannot express it.  Both
  fields are read and kept.
- The **ambient contribution** (``ambientLightColor``/``ambientSkyContribution``),
  likewise read and kept, and not yet wired to the ambient term.

References:
    ``OMI_environment_sky``
    https://github.com/omigroup/gltf-extensions/tree/main/extensions/2.0/OMI_environment_sky
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.loaders.gltf.textures import texture_image
from OpenGLContext.loaders.resolver import Resolver

if TYPE_CHECKING:
    import pygltflib
    from PIL import Image

log = logging.getLogger(__name__)

__all__ = ['EXTENSION', 'Sky', 'GradientSky', 'PanoramaSky', 'PhysicalSky',
           'PlainSky', 'read_skies', 'scene_sky', 'background_for']

#: The name this extension appears under, in the document and in each scene.
EXTENSION = 'OMI_environment_sky'

#: Colour stops per hemisphere of a gradient sky.  The stops are spaced evenly
#: in *colour* rather than in angle (see :func:`_gradient_stops`), so they crowd
#: wherever the curve is steep and this count buys fidelity where it is needed
#: rather than everywhere.
GRADIENT_STOPS = 12

#: Quarter turn.  The horizon, measured from either pole.
HALF_PI = math.pi / 2.0

#: Which ``CubeBackground`` face each of the extension's six cubemap entries is,
#: in the order the specification gives them: +X, -X, +Y, -Y, +Z, -Z.
CUBE_FACES = ('right', 'left', 'top', 'bottom', 'back', 'front')


# ----------------------------------------------------------------------
# The records
# ----------------------------------------------------------------------

@dataclass
class Sky:
    """What every sky carries, whatever its type.

    ``ambientSkyContribution`` blends between the sky's own colour and
    ``ambientLightColor``: at 1.0, the extension's default, the ambient light is
    the sky and the colour is ignored.  Neither is applied yet.
    """

    ambientLightColor: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    ambientSkyContribution: float = 1.0


@dataclass
class GradientSky(Sky):
    """Three colours up the dome, and how sharply each fades into the horizon.

    A curve of 1.0 is a linear transition.  Below 1.0 the end colour (top or
    bottom) holds further towards the horizon; above 1.0 the horizon colour
    takes more of the sky.  ``sunAngleMax`` and ``sunCurve`` describe a disc
    around the scene's directional light and are read but not drawn.
    """

    topColor: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    horizonColor: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    bottomColor: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    topCurve: float = 0.15
    bottomCurve: float = 0.02
    sunAngleMax: float = 0.5
    sunCurve: float = 0.15


@dataclass
class PanoramaSky(Sky):
    """A sky that is a picture: one equirectangular texture, or six faces."""

    equirectangular: Optional[int] = None
    cubemap: Optional[Tuple[int, ...]] = None


@dataclass
class PhysicalSky(Sky):
    """Atmospheric scattering parameters, in glTF's **inverse metres**.

    Engines that work in inverse kilometres scale these by 1000; the values here
    are the document's own.  Nothing draws them yet.
    """

    groundColor: Tuple[float, float, float] = (0.3, 0.2, 0.1)
    rayleighColor: Tuple[float, float, float] = (0.3, 0.5, 1.0)
    rayleighScale: float = 0.00003
    mieColor: Tuple[float, float, float] = (1.0, 1.0, 1.0)
    mieScale: float = 0.000005
    mieAnisotropy: float = 0.8


@dataclass
class PlainSky(Sky):
    """One colour, all the way round."""

    color: Tuple[float, float, float] = field(default=(0.0, 0.0, 0.0))


# ----------------------------------------------------------------------
# Reading
# ----------------------------------------------------------------------

def _color(block: Any, key: str, default: Tuple[float, float, float]
           ) -> Tuple[float, float, float]:
    """An RGB triple from ``block``, or ``default`` if it does not hold one.

    Values above 1.0 are kept: the extension permits them for an HDR sky, and
    clamping belongs where a low-dynamic-range node is actually built.
    """
    value = block.get(key) if isinstance(block, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return default
    try:
        return (float(value[0]), float(value[1]), float(value[2]))
    except (TypeError, ValueError):
        return default


def _number(block: Any, key: str, default: float) -> float:
    value = block.get(key) if isinstance(block, dict) else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _indices(block: Any, key: str, count: int) -> Optional[Tuple[int, ...]]:
    """``count`` texture indices from ``block``, or None if it does not hold them."""
    value = block.get(key) if isinstance(block, dict) else None
    if not isinstance(value, (list, tuple)) or len(value) != count:
        return None
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in value):
        return None
    return tuple(int(v) for v in value)


def _index(block: Any, key: str) -> Optional[int]:
    value = block.get(key) if isinstance(block, dict) else None
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _read_sky(entry: Any) -> Optional[Sky]:
    """One entry of ``skies[]`` as a record, or None where it is not one.

    An unknown ``type`` is not an error: this extension gains sky types over
    time, and a document using a newer one should lose its sky rather than its
    scene.
    """
    if not isinstance(entry, dict):
        return None
    ambient = _color(entry, 'ambientLightColor', (0.0, 0.0, 0.0))
    contribution = _number(entry, 'ambientSkyContribution', 1.0)
    common: dict[str, Any] = {'ambientLightColor': ambient,
                              'ambientSkyContribution': contribution}
    kind = entry.get('type')
    payload = entry.get(kind) if isinstance(kind, str) else None
    if not isinstance(payload, dict):
        payload = {}
    if kind == 'gradient':
        return GradientSky(
            topColor=_color(payload, 'topColor', (0.0, 0.0, 0.0)),
            horizonColor=_color(payload, 'horizonColor', (0.0, 0.0, 0.0)),
            bottomColor=_color(payload, 'bottomColor', (0.0, 0.0, 0.0)),
            topCurve=_number(payload, 'topCurve', 0.15),
            bottomCurve=_number(payload, 'bottomCurve', 0.02),
            sunAngleMax=_number(payload, 'sunAngleMax', 0.5),
            sunCurve=_number(payload, 'sunCurve', 0.15),
            **common)
    if kind == 'panorama':
        return PanoramaSky(
            equirectangular=_index(payload, 'equirectangular'),
            cubemap=_indices(payload, 'cubemap', 6),
            **common)
    if kind == 'physical':
        return PhysicalSky(
            groundColor=_color(payload, 'groundColor', (0.3, 0.2, 0.1)),
            rayleighColor=_color(payload, 'rayleighColor', (0.3, 0.5, 1.0)),
            rayleighScale=_number(payload, 'rayleighScale', 0.00003),
            mieColor=_color(payload, 'mieColor', (1.0, 1.0, 1.0)),
            mieScale=_number(payload, 'mieScale', 0.000005),
            mieAnisotropy=_number(payload, 'mieAnisotropy', 0.8),
            **common)
    if kind == 'plain':
        return PlainSky(color=_color(payload, 'color', (0.0, 0.0, 0.0)), **common)
    log.info('glTF: %s sky type %r is not one this build knows; ignoring it',
             EXTENSION, kind)
    return None


def read_skies(extensions: Any) -> list:
    """Every sky a document declares, in order, with an unreadable one as None.

    None is kept in place rather than dropped so that a scene's ``sky`` index
    still selects the entry the document meant.
    """
    block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    entries = block.get('skies') if isinstance(block, dict) else None
    if not isinstance(entries, list):
        if entries is not None:
            log.warning('glTF: %s skies is not an array; ignoring it', EXTENSION)
        return []
    return [_read_sky(entry) for entry in entries]


def scene_sky(extensions: Any, skies: Sequence[Optional[Sky]]) -> Optional[Sky]:
    """The sky a scene's ``extensions`` selects out of ``skies``.

    The index defaults to 0, which is what a document declaring one sky and
    saying nothing per scene means.  An index that names nothing costs the sky
    and not the scene.
    """
    if not skies:
        return None
    block = extensions.get(EXTENSION) if isinstance(extensions, dict) else None
    chosen = _index(block, 'sky') if isinstance(block, dict) else None
    if chosen is None:
        chosen = 0
    if not (0 <= chosen < len(skies)):
        log.warning('glTF: %s sky %d names nothing; the scene has no sky',
                    EXTENSION, chosen)
        return None
    return skies[chosen]


# ----------------------------------------------------------------------
# Building the background
# ----------------------------------------------------------------------

def _clamped(color: Sequence[float]) -> Tuple[float, float, float]:
    """``color`` inside [0, 1].

    The gradient sphere and the clear colour are drawn in low dynamic range,
    while the extension permits values above 1.0 for an HDR sky.  Clamping is
    the honest loss; letting one through wraps to a wrong colour entirely.
    """
    return tuple(min(1.0, max(0.0, float(c))) for c in color)  # type: ignore[return-value]


def _gradient_stops(horizon: Sequence[float], pole: Sequence[float], curve: float,
                    count: int = GRADIENT_STOPS) -> Tuple[list, list]:
    """Colour stops from ``pole`` to ``horizon``, and the angle each sits at.

    Angles are measured from the pole, as VRML97's ``Background`` measures both
    ``skyAngle`` (from the zenith) and ``groundAngle`` (from the nadir), so the
    first colour is at the pole and needs no angle of its own -- which is why
    ``count`` colours come back with ``count - 1`` angles.

    The extension states the curve's meaning rather than its formula: 1.0 is a
    linear transition, below 1.0 makes the pole colour dominant, above 1.0 the
    horizon colour.  ``blend = 1 - (1 - t)^(1/curve)`` over ``t``, the fraction
    of the way from horizon to pole, is the reading taken here: it is linear at
    1.0 and moves in the stated direction either side of it.

    The stops are spaced evenly **in colour**, not in angle, and the angle each
    lands at follows from inverting that blend.  A curve of 0.15 changes colour
    almost entirely within a few degrees of the horizon, and stops spread evenly
    up the dome would draw that as a visible kink; spaced this way they crowd
    where the colour is moving and thin out where it is not.
    """
    if curve <= 0.0:
        # The specification requires a positive number.  Content is not always
        # well formed, and a bad curve should cost the shaping, not the scene.
        log.warning('glTF: %s gradient curve %r is not positive; using a linear '
                    'transition', EXTENSION, curve)
        curve = 1.0
    near = np.asarray(horizon, dtype='d')
    far = np.asarray(pole, dtype='d')
    colors, angles = [], []
    for step in range(count):
        blend = 1.0 - step / float(count - 1)       # 1.0 at the pole, 0.0 at the horizon
        colors.append(_clamped(near + (far - near) * blend))
        if step:
            angles.append(((1.0 - blend) ** curve) * HALF_PI)
    return colors, angles


def _gradient_background(sky: GradientSky) -> Any:
    """The VRML97 gradient sphere this sky describes."""
    from OpenGLContext.scenegraph.background import Background

    sky_colors, sky_angles = _gradient_stops(
        sky.horizonColor, sky.topColor, sky.topCurve)
    ground_colors, ground_angles = _gradient_stops(
        sky.horizonColor, sky.bottomColor, sky.bottomCurve)
    return Background(skyColor=sky_colors, skyAngle=sky_angles,
                      groundColor=ground_colors, groundAngle=ground_angles)


def _linear_panorama(image: "Image.Image") -> np.ndarray:
    """An sRGB texture as the linear-light ``(H, W, 3)`` float the probe wants.

    The IBL probe and the PBR pass both work in linear light, so an sRGB texture
    handed over encoded would light the scene from a washed-out sky.  The
    transfer function is the sRGB EOTF, the same one the texture path applies on
    upload.
    """
    rgb = np.asarray(image.convert('RGB'), dtype=np.float32) / 255.0
    return np.where(rgb <= 0.04045, rgb / 12.92,
                    ((rgb + 0.055) / 1.055) ** 2.4).astype(np.float32)


def _to_shader_orientation(panorama: np.ndarray) -> np.ndarray:
    """Turn the extension's panorama orientation into the skybox shader's.

    Both map the panorama's top row to +Y, so only the horizontal offset moves.
    The extension puts the middle of the texture at +Z and +X to the left of it;
    ``dirToEquirect`` in ``_cubemap_inc.glsl`` puts the middle at +X and +Z a
    quarter turn to its right.  The two differ by exactly a quarter of the
    width, so rolling the columns is the whole conversion -- and doing it here,
    once, at load, keeps the one shared direction-to-UV mapping that stops the
    drawn sky and the reflections it drives from disagreeing.
    """
    return np.roll(panorama, panorama.shape[1] // 4, axis=1)


def _panorama_background(sky: PanoramaSky, g: "pygltflib.GLTF2",
                         resolver: Resolver) -> Any:
    """The skybox a panorama sky describes, or None if its textures will not load.

    The equirectangular form is preferred where a document offers both: the
    specification names it the fallback for engines without cubemap skyboxes,
    and it is the one that also drives the reflections.
    """
    if sky.equirectangular is not None:
        image = texture_image(g, sky.equirectangular, resolver)
        if image is None:
            log.warning('glTF: %s panorama texture %s would not load; the scene '
                        'has no sky', EXTENSION, sky.equirectangular)
            return None
        from OpenGLContext.scenegraph.hdrbackground import HDRBackground
        return HDRBackground(
            image=_to_shader_orientation(_linear_panorama(image)))
    if sky.cubemap is not None:
        faces = [texture_image(g, index, resolver) for index in sky.cubemap]
        if any(face is None for face in faces):
            # A partial face set would draw a skybox with holes in it.
            log.warning('glTF: %s cubemap is missing a face; the scene has no sky',
                        EXTENSION)
            return None
        from OpenGLContext.scenegraph.cubebackground import CubeBackground
        background = CubeBackground()
        for name, face in zip(CUBE_FACES, faces, strict=True):
            getattr(background, name).setImage(face)
        return background
    log.warning('glTF: %s panorama sky names no texture; the scene has no sky',
                EXTENSION)
    return None


def background_for(sky: Optional[Sky], g: "pygltflib.GLTF2",
                   resolver: Resolver) -> Any:
    """The ``Background`` node ``sky`` describes, or None where nothing draws it.

    None rather than a substitute: a viewer that adds its own backdrop when a
    scene brought none then does so, and one that does not shows the scene
    without a sky.  Inventing one here would be a third answer neither asked
    for.
    """
    if sky is None:
        return None
    if isinstance(sky, GradientSky):
        return _gradient_background(sky)
    if isinstance(sky, PanoramaSky):
        return _panorama_background(sky, g, resolver)
    if isinstance(sky, PlainSky):
        from OpenGLContext.scenegraph.simplebackground import SimpleBackground
        return SimpleBackground(color=_clamped(sky.color))
    log.info('glTF: %s physical sky needs an atmospheric-scattering skydome, '
             'which this build does not have; the scene has no sky', EXTENSION)
    return None
