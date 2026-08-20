#! /usr/bin/env python
"""Walk-around viewer for a 3D scene (``oglc-view``).

Opens a local file **or an http(s) URL**, renders it with the metallic/roughness
PBR pass, and lets you walk through it with the keyboard/mouse. What format the
source is in is worked out from the source itself, so one command opens them
all:

===============================  ==============================================
``.gltf`` ``.glb``               a glTF 2.0 model
``.wrl`` ``.wrz`` ``.vrml``      a VRML97 world
===============================  ==============================================

Every format gets everything the viewer can do. If the file contains no lights, a
default sun + fill rig is added so the scene is never rendered in the dark;
shadows are on by default. A scene that brings its own sky keeps it.

A model with no camera of its own is centred and auto-framed. The fit is on the
*model*: a part the file stranded far outside the rest is still drawn but does
not push the camera back to take it in, and the viewer prints a line saying how
many such parts there are and how far out they go. See docs/viewer.html.

Each camera the scene defines becomes a ``Viewpoint`` node, so PageUp/PageDown
cycle between them through OpenGLContext's standard viewpoint mechanism; cameras
are referred to by name where they have one. ``--capture`` renders the scene to a
PNG and exits, after a short settle delay so the analytic-sky IBL has converged.

Usage::

    oglc-view path/to/model.glb
    oglc-view path/to/world.wrl
    oglc-view https://example.com/model.glb
    oglc-view model.glb --camera aerial --capture shot.png --capture-delay 0.5
    oglc-view model.glb --list-cameras
    GLTF=path/to/model.gltf oglc-view

A ``.glb`` is self-contained, so URLs work cleanly. A ``.gltf`` URL fetches only
that file; models that reference external ``.bin``/texture files by relative URI
will be missing those (download the whole model set locally instead).

Controls (OpenGLContext's default view-platform navigation)::

    Up / Down arrow        walk forward / back
    Left / Right arrow     turn (yaw) left / right
    Ctrl + Up/Down          look up / down (pitch)
    Alt + Up/Down           move up / down (fly)
    Alt + Left/Right        strafe (slide) left / right
    -                       level the horizon
    right-mouse drag        orbit / examine about a point
    PgUp / PgDn (or p / n)  cycle named cameras (if any)
    g                       toggle walk (physics) / free-fly
    k                       pause / resume animation; [ / ] switch animation
    t                       stop/start the turntable (stopping resets orientation)
    F2                      save a screenshot (iso-dated PNG in the current directory)
    Alt + s                 the same thing through the engine's own handler,
                            named for the program: oglc-view-screen-0001.png,
                            also in the current directory
    Alt + f                 the developer overlay: frame rate and time, which
                            renderer features are on, what the last frame cost
                            in shapes and draw calls, and where the camera is
                            (see docs/hud.html)

Free-fly by default; ``--physics`` (or ``g``) walks the scene instead, with
gravity and collision keeping you on the ground and out of walls. ``g`` again
returns to free-fly, so a viewpoint inside the geometry is never a trap.

The viewer itself is :mod:`OpenGLContext.viewer`, which an application can embed
without this command line, and the formats it opens are the adapters registered
in :mod:`OpenGLContext.viewer.adapters`; see docs/gltf.html.
"""
import argparse
import os
import sys
from typing import Any, Optional

from OpenGLContext.viewer.environment import apply_render_env, viewer_defaults

viewer_defaults()   # before anything that renders is imported

from OpenGLContext.viewer.adapters import (  # noqa: E402
    UnknownSourceType, adapter_for, adapter_named, known_sources,
)
from OpenGLContext.viewer.sceneviewer import ViewerContext  # noqa: E402
from OpenGLContext.viewer.options import ViewerOptions  # noqa: E402
from OpenGLContext.viewer.source import resolve_source  # noqa: E402


# -- command line ---------------------------------------------------------

def _parse_size(text: str) -> tuple[int, int]:
    """Parse a ``WxH`` window size into an (int, int) tuple."""
    try:
        w, h = (int(v) for v in text.lower().split('x'))
        return (w, h)
    except Exception:
        raise argparse.ArgumentTypeError("size must be WxH, e.g. 1100x680") from None


def _format_names() -> list[str]:
    """The registered adapter names, for ``--format``'s help."""
    from OpenGLContext import plugins
    return sorted(entry.name for entry in plugins.Adapter.all())


def _parse_vec3(text: str) -> tuple[float, ...]:
    """Parse an ``X,Y,Z`` world-space point."""
    parts = text.split(',')
    if len(parts) != 3:
        raise argparse.ArgumentTypeError('expected X,Y,Z, got %r' % text)
    return tuple(float(v) for v in parts)


def build_parser(prog: str = 'oglc-view') -> argparse.ArgumentParser:
    """The viewer's command line.

    Every option is declared ``default=argparse.SUPPRESS`` so that an option
    nobody passed leaves the corresponding :class:`ViewerOptions` field alone.
    The defaults are the dataclass's, stated once, and the help text below
    names them where a user needs to know.
    """
    parser = argparse.ArgumentParser(
        prog=prog,
        description='Walk-around viewer for a 3D scene: %s.' % ', '.join(
            # Suffixes and conventional file names; the content types the same
            # adapters answer to are not something anyone types.
            key for key in known_sources() if '/' not in key),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        argument_default=argparse.SUPPRESS,
        epilog="A local path or an http(s) URL. .glb is self-contained (URLs work "
               "cleanly); a .gltf that references external .bin/textures should be "
               "downloaded locally as a set. Falls back to the GLTF env var.",
    )
    parser.add_argument('source', nargs='?',
                        help='scene file path or http(s) URL (or set GLTF=...)')
    parser.add_argument('--format', metavar='NAME',
                        help='read the source as this format instead of guessing '
                             'from its name (%s); for a URL that serves a scene '
                             'from a path with no suffix'
                             % ', '.join(_format_names()))
    parser.add_argument('--camera', metavar='NAME|INDEX',
                        help='initial camera, by the name the scene gives it '
                             '(preferred) or 0-based index')
    parser.add_argument('--list-cameras', action='store_true',
                        help="print the scene's camera names and exit")
    parser.add_argument('--no-cameras', action='store_true',
                        help="ignore the scene's own cameras; centre and auto-frame it")
    parser.add_argument('--capture', metavar='PATH',
                        help='render to PATH (PNG) after settling, then exit')
    parser.add_argument('--capture-delay', type=float, metavar='SECONDS',
                        help='seconds to let the scene settle before --capture (default 0.5)')
    parser.add_argument('--frames', type=int, metavar='N',
                        help='minimum frames to render before --capture (default 10)')
    parser.add_argument('--shadows', action=argparse.BooleanOptionalAction,
                        help='force shadows on/off (default: on)')
    parser.add_argument('--lights', choices=['auto', 'on', 'off'],
                        help="default light rig: auto (add only if the file has none), "
                             "on (always add), off (never add)")
    parser.add_argument('--ibl-intensity', type=float, metavar='SCALE',
                        help='scale the analytic-sky ambient/IBL contribution')
    parser.add_argument('--environment', metavar='PREFIX|HDR|NAME',
                        help='image-based environment: a cubemap face prefix '
                             '(<PREFIX>{RT,LF,UP,DN,FR,BK}.jpg), an equirectangular '
                             'Radiance .hdr panorama (local path or http(s) URL), or a '
                             'bundled CC0 HDRI name (e.g. studio_small_03). Reflected '
                             'by metals and drawn as the skybox. Pins full IBL.')
    parser.add_argument('--background', metavar='SPEC',
                        help="background: 'sky' (default), 'none', or 'R,G,B'")
    parser.add_argument('--size', type=_parse_size, metavar='WxH',
                        help='window size, e.g. 1100x680')
    # Streaming sources (3D Tiles): ignored by a format that is read once.
    parser.add_argument('--sse', type=float, metavar='PIXELS',
                        help='streamed datasets: max screen-space error in '
                             'pixels; lower = more detail (default 16)')
    parser.add_argument('--memory', type=int, metavar='MiB',
                        help='streamed datasets: resident tile memory budget '
                             '(default 512)')
    parser.add_argument('--no-recenter', dest='no_recenter', action='store_true',
                        help='streamed datasets: do not shift a geospatial '
                             '(Earth-centred) dataset to the origin')
    parser.add_argument('--cache-dir', dest='cache_dir', metavar='DIR',
                        help='where to cache data fetched from a URL')
    parser.add_argument('--physics', action=argparse.BooleanOptionalAction,
                        help='walk the model with gravity + collision (default off, so '
                             'an isolated/floorless model stays framed instead of the '
                             'avatar falling past it); press "g" or pass --physics to walk')
    parser.add_argument('--turntable', action='store_true',
                        help='slowly rotate the model')
    parser.add_argument('--no-rotate', dest='no_rotate', action='store_true',
                        help='never rotate the model (fixed orientation, to line a '
                             'capture up with a reference image)')
    parser.add_argument('--animation', metavar='NAME|INDEX',
                        help='play this glTF animation (name or 0-based index); '
                             'default: play the first animation if any')
    parser.add_argument('--no-animation', dest='animate', action='store_false',
                        help='do not play embedded animations')
    parser.add_argument('--anim-time', type=float, metavar='SECONDS',
                        help='pin the animation to this time (deterministic capture)')
    parser.add_argument('--yaw', type=float,
                        help='initial model yaw (radians) when auto-framing '
                             '(default -0.62, or $OPENGLCONTEXT_VIEW_YAW)')
    parser.add_argument('--margin', type=float, metavar='FACTOR',
                        help='auto-frame fit factor (default 1.15); below 1 pulls '
                             'the camera in so the model fills more of the frame')
    parser.add_argument('--elevation', type=float, metavar='FRAC',
                        help='auto-frame camera height as a fraction of the model '
                             'radius (default 0.22)')
    parser.add_argument('--tilt', type=float, metavar='RADIANS',
                        help='auto-frame downward camera tilt in radians (default 0.10)')
    parser.add_argument('--eye', type=_parse_vec3, metavar='X,Y,Z',
                        help='explicit camera position (world space); with --look-at '
                             'this bypasses auto-framing (e.g. an interior shot)')
    parser.add_argument('--look-at', dest='look_at', type=_parse_vec3,
                        metavar='X,Y,Z', help='explicit camera target (world space)')
    return parser


def parse_args(argv: list[str] | None = None, prog: str = 'oglc-view',
               options: ViewerOptions | None = None) -> ViewerOptions:
    """Parse the viewer's command line into a :class:`ViewerOptions` (no GL).

    ``options`` is filled in and returned when given, so a program built on this
    one can start from its own defaults and let the user override them.
    """
    return build_parser(prog).parse_args(
        argv, namespace=options if options is not None else ViewerOptions())


class TestContext(ViewerContext):
    """``oglc-view`` itself: the viewing component, configured from the command line."""


def _list_cameras(source: str, format: Optional[str] = None) -> int:
    """Print the scene's camera names, for choosing one with ``--camera``.

    The adapter answers, so this works for every format rather than only the one
    the listing was first written for.
    """
    adapter = adapter_named(format) if format else adapter_for(source)
    scene = adapter.load(source)
    if not scene.cameras:
        sys.stdout.write("(no cameras defined in %s)\n" % os.path.basename(source))
    for i, camera in enumerate(scene.cameras):
        sys.stdout.write("%d: %s\n" % (i, camera.get('name') or 'camera'))
    return 0


def main(argv: Optional[list[str]] = None, prog: str = 'oglc-view') -> Any:
    parser = build_parser(prog)
    options = parser.parse_args(argv, namespace=ViewerOptions())
    source = options.source or os.environ.get('GLTF')
    if options.list_cameras and not source:
        parser.error('nothing to list cameras for (pass a path or a URL)')

    if options.list_cameras:
        try:
            return _list_cameras(resolve_source(source) or source, options.format)
        except UnknownSourceType as error:
            parser.error(str(error))

    apply_render_env(options)
    TestContext.options = options
    return TestContext.ContextMainLoop(size=options.size) if options.size \
        else TestContext.ContextMainLoop()


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    main()
