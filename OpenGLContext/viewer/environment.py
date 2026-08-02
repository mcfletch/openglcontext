"""What is behind the model, and whether it brings its own light.

The environment a viewer shows and the environment its metals reflect want to be
the same one, or a chrome sphere reflects a room the viewer is not in.  These
build the ``Background`` node for whichever environment the IBL probe has loaded
-- an equirectangular Radiance panorama, a six-face cubemap, or neither, in
which case an analytic gradient sky stands in.
"""
import os
from typing import Any, Optional, Set

from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.light import Light

__all__ = ['count_nodes', 'count_lights', 'count_backgrounds', 'sky_background',
           'hdr_background', 'cube_background', 'background_for']

#: Which ``CubeBackground`` field each of the loader's face suffixes fills.
_CUBE_FIELDS = {'RT': 'rightUrl', 'LF': 'leftUrl', 'UP': 'topUrl',
                'DN': 'bottomUrl', 'FR': 'frontUrl', 'BK': 'backUrl'}


def count_nodes(node: Any, kind: Any, seen: Optional[Set[int]] = None) -> int:
    """How many nodes of ``kind`` are reachable from ``node``.

    What a viewer asks to find out what a scene brought with it, so that it adds
    only what is missing.  Nodes already visited are remembered, since a
    scenegraph may share a subtree between several parents and a naive walk
    would either double-count it or, given a cycle, not finish.
    """
    if seen is None:
        seen = set()
    if id(node) in seen:
        return 0
    seen.add(id(node))
    total = 1 if isinstance(node, kind) else 0
    for child in getattr(node, 'children', None) or ():
        total += count_nodes(child, kind, seen)
    return total


def count_lights(node: Any, seen: Optional[Set[int]] = None) -> int:
    """How many lights a scene brought, and so whether it needs a rig."""
    return count_nodes(node, Light, seen)


def count_backgrounds(node: Any, seen: Optional[Set[int]] = None) -> int:
    """How many backdrops a scene brought.

    A world authored complete has its own sky, and a second backdrop in the same
    scene is not a second sky but a fight over which one is bound.

    Counted by the ``Background`` *interface* rather than by the VRML97 node,
    because the backdrops are a family: a gradient sphere, a solid colour, a
    cubemap and an equirectangular panorama are each a different class, and a
    glTF ``OMI_environment_sky`` may bring any of them.  The render pass binds
    whichever of them it finds, so it is that set this has to agree with.
    """
    return count_nodes(node, nodetypes.Background, seen)


def sky_background() -> Background:
    """A bright, clear Mediterranean afternoon: a strong blue zenith fading to a
    pale hazy horizon, over sunlit stone."""
    return Background(
        skyColor=[(0.28, 0.50, 0.82), (0.45, 0.66, 0.90),
                  (0.72, 0.84, 0.96), (0.88, 0.93, 0.98)],
        skyAngle=[1.05, 1.40, 1.5708],
        groundColor=[(0.62, 0.58, 0.50), (0.74, 0.70, 0.60)],
        groundAngle=[1.5708],
    )


def hdr_background() -> Any:
    """The Radiance panorama the IBL probe is using, as a skybox, or None."""
    source = os.environ.get('OPENGLCONTEXT_ENV_HDR', '').strip()
    if not source:
        return None
    from OpenGLContext.scenegraph.hdrbackground import HDRBackground
    return HDRBackground(url=[source])


def cube_background() -> Any:
    """The IBL environment cubemap as a skybox, or None if its faces are not all
    on disk -- a partial face set would draw a skybox with holes in it."""
    from OpenGLContext.passes.ibl import (
        environment_cubemap_prefix, _CUBE_EXTS, _CUBE_FACES,
    )
    prefix = environment_cubemap_prefix()
    if not prefix:
        return None
    urls = {}
    for suffix, _ in _CUBE_FACES:
        path = next((prefix + suffix + ext for ext in _CUBE_EXTS
                     if os.path.exists(prefix + suffix + ext)), None)
        if path is None:
            return None
        urls[_CUBE_FIELDS[suffix]] = [path]
    from OpenGLContext.scenegraph.cubebackground import CubeBackground
    return CubeBackground(**urls)


def background_for(spec: Optional[str], report: Any = None) -> Any:
    """The ``Background`` node a ``--background`` spec asks for.

    ``'none'`` draws nothing, ``'sky'`` the gradient above, an ``R,G,B`` triple a
    flat colour.  ``'cube'``, ``'hdr'`` and *unset* all mean "show whatever the
    IBL probe loaded", falling back to the sky, so the visible backdrop and the
    reflections agree without the caller having to know which kind was loaded.

    ``report`` is called with a message when the spec cannot be read; a bad
    colour falls back to the sky rather than failing, since a viewer that opens
    no window is worse than one with the wrong backdrop.
    """
    if spec == 'none':
        return None
    if spec == 'sky':
        return sky_background()
    if spec in ('cube', 'hdr', None):
        return hdr_background() or cube_background() or sky_background()
    try:
        rgb = tuple(float(v) for v in spec.split(','))
        if len(rgb) != 3:
            raise ValueError
    except ValueError:
        if report is not None:
            report("bad background %r; using sky.\n" % spec)
        return sky_background()
    return Background(skyColor=[rgb])
