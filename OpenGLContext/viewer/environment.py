"""What is behind the model, and whether it brings its own light.

The environment a viewer shows and the environment its metals reflect want to be
the same one, or a chrome sphere reflects a room the viewer is not in.  These
build the ``Background`` node for whichever environment the IBL probe has loaded
-- an equirectangular Radiance panorama, a six-face cubemap, or neither, in
which case an analytic gradient sky stands in.

:func:`apply_render_env` is the other half, and a caller building a viewer
without a command line needs it: several of the options a viewer takes are
read once by the render passes at start-up rather than per frame, so they are
put into the environment before a context exists. A ``ViewerOptions`` that is
never passed through it is a viewer whose shadows, exposure and environment
settings say nothing.
"""
import os
from typing import Any, Optional, Set

from vrml.vrml97 import nodetypes

from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.light import Light
from OpenGLContext.viewer.options import ViewerOptions

__all__ = ['count_nodes', 'count_lights', 'count_backgrounds', 'sky_background',
           'hdr_background', 'cube_background', 'background_for',
           'apply_render_env', 'viewer_defaults', 'VIEWER_DEFAULTS']


#: What a viewer needs the renderer set to before anything imports it, and what
#: a program that shows a model through :class:`ViewerContext` must therefore
#: apply first: the core profile and the metallic/roughness pass, because a PBR
#: material has nothing to say to any other one, and a warm sky held back far
#: enough that the sun's shadows read against it.
VIEWER_DEFAULTS = {
    'OPENGLCONTEXT_PROFILE': 'core',
    'OPENGLCONTEXT_BACKEND': 'glfw',
    'OPENGLCONTEXT_RENDERER': 'pbr',
    'OPENGLCONTEXT_SHADOWS': '1',
    # The directional-shadow cascade count is left fps-adaptive for interactive
    # use: each extra cascade is a full depth pass over the whole scene (the
    # dominant shadow-pass cost), so the controller sheds cascades when the
    # frame rate sags. It is pinned only for a capture (see
    # :func:`apply_render_env`), where a reproducible frame matters more than
    # the frame rate.
    'OPENGLCONTEXT_IBL_INTENSITY': '0.4',
}


def viewer_defaults() -> None:
    """Put the viewer's renderer settings into the environment, once.

    Call it **before importing anything that renders**: the passes read these
    at import, so a setting made afterwards is a setting nobody sees. Anything
    already set is left alone, so a caller or a shell that has chosen
    differently keeps its choice.
    """
    for name, value in VIEWER_DEFAULTS.items():
        os.environ.setdefault(name, value)

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


#: The colour the sky reaches at eye level in :func:`sky_background`, and so
#: the colour a distance fades into.
HORIZON_HAZE = (0.88, 0.93, 0.98)


def horizon_background(haze: Any = HORIZON_HAZE) -> Background:
    """The same sky over a horizon that fades rather than ends.

    A world of finite extent runs out, and what a camera at ground level sees
    past the last of it is the background's lower half. Ground-coloured, that
    is a wall of earth standing at the edge of the world; haze-coloured, it is
    the distance. Pair it with a
    :class:`~OpenGLContext.scenegraph.fog.Fog` of the same colour and the
    terrain fades into the air the background is already made of.

    ``haze`` defaults to the colour the sky reaches at eye level, so the band
    below the horizon carries on from the band above it and the join is not
    there to see.
    """
    sky = sky_background()
    colours = [tuple(colour) for colour in sky.skyColor[:-1]] + [tuple(haze)]
    return Background(
        skyColor=colours,
        skyAngle=list(sky.skyAngle),
        groundColor=[tuple(haze)],
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


def _is_hdr_environment(spec: Optional[str]) -> bool:
    """Whether ``--environment SPEC`` names a Radiance ``.hdr`` panorama.

    An equirectangular ``.hdr``/``.pic`` (local path or http(s) URL) is treated as
    an HDR IBL source + skybox; anything else is a six-face cubemap prefix. The
    query string of a URL is ignored so a CDN link with parameters still matches.
    """
    if not spec:
        return False
    path = spec.split('?', 1)[0].split('#', 1)[0]
    return path.lower().endswith(('.hdr', '.pic'))


def apply_render_env(args: ViewerOptions) -> None:
    """Translate render-affecting options into the variables the renderer reads.

    These are start-up switches read once by the passes (see
    :mod:`OpenGLContext.renderoptions`), so they are set before a context exists
    rather than carried on the options object.
    """
    if args.shadows is not None:
        os.environ['OPENGLCONTEXT_SHADOWS'] = '1' if args.shadows else '0'
    if args.ibl_intensity is not None:
        os.environ['OPENGLCONTEXT_IBL_INTENSITY'] = str(args.ibl_intensity)
    if args.environment:
        from OpenGLContext.loaders import hdri
        try:
            args.environment = hdri.resolve(args.environment)   # catalogue name -> URL
        except KeyError:
            pass    # not a catalogue name; treat as a cubemap prefix / path
        environment: str = args.environment
        if _is_hdr_environment(environment):
            # An equirectangular Radiance .hdr (local path or URL): drives the IBL
            # probe and the HDR skybox. The probe loads it via OPENGLCONTEXT_ENV_HDR.
            os.environ['OPENGLCONTEXT_ENV_HDR'] = environment
        else:
            os.environ['OPENGLCONTEXT_ENV_CUBEMAP'] = environment
        os.environ.setdefault('OPENGLCONTEXT_IBL', 'full')   # env probe needs full IBL
    elif (args.background == 'none'
          and not os.environ.get('OPENGLCONTEXT_ENV_CUBEMAP')
          and not os.environ.get('OPENGLCONTEXT_ENV_HDR')):
        # A self-lit scene (its own KHR_lights_punctual, black backdrop, NO env probe)
        # must get no analytic-sky IBL, or the ambient sky washes it pale grey instead
        # of the dark scene its lights make. But only when there is genuinely no
        # environment: the browser demo defaults --background 'none' yet loads an env
        # cubemap probe for metals to reflect, so forcing IBL off there rendered every
        # metal black. Honour an explicit env cubemap or HDR panorama.
        os.environ['OPENGLCONTEXT_IBL'] = 'off'
    if args.capture:
        # a --capture run wants a clean frame, not the fps overlay
        os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'
        # A capture must be reproducible: pin the otherwise fps-adaptive cascade
        # count so the shadows don't vary with the frame rate between runs. An
        # explicit user setting still wins.
        os.environ.setdefault('OPENGLCONTEXT_SHADOW_CASCADES', '3')
        # Nobody is watching a capture, and a *mapped* surface is what makes it
        # hang: a compositor throttles the swap to its own frame callback, and
        # with no window on screen consuming frames the swap never returns. A
        # hidden window renders and reads back identically. Both stay
        # overridable, since watching a capture happen is how you find out why
        # it looks wrong.
        os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
        os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
